import logging
import json
import time
import datetime
import os
import redis
import requests
import base64
import uuid
from app.worker.celery_app import celery_app
from app.services.chatwoot import (
    send_message,
    apply_label,
    set_priority,
    toggle_typing_status,
    get_conversation_messages,
    get_or_create_contact,
    create_conversation,
    assign_agent,
    send_chatwoot_image_attachment,
    get_agent_id_by_email,
    CHATWOOT_ACCOUNT_ID,
    send_private_note,
    send_whatsapp_contact,
    send_whatsapp_template,
)
from app.services.llm import generate_response, transcribe_audio, extract_property_search_criteria, extract_valuer_data, extract_wordpress_property
from app.services.document_parser import extract_text_from_document
from app.services.db_services import get_or_create_customer, get_sender_role, search_properties, get_active_agents_and_employees
from app.services.session_manager import SessionManager
from app.services.minio_service import upload_media
from app.db.models import SessionLocal, Customer, Property, Transaction, Order, InteractionLog, User


logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

TIMEOUT_SECONDS = 10

CONFIGURED_LOCATIONS = [
    "Bentong", "Temerloh", "Karak", "Raub", "Kuantan",
    "Mentakab", "Pahang", "Selangor", "KL"
]

CONFIGURED_PROPERTY_TYPES = [
    "Rental", "Residential", "Commercial", "Land / Agriculture",
    "Industrial", "Durian Land", "Factory"
]

DEFAULT_FALLBACK_ADMIN_NUMBERS = ["+601165144931", "+14709202239"]


def calculate_agent_specialization_score(agent, lead_location_or_data=None, lead_property_type: str = "", raw_inquiry_text: str = "") -> int:
    """
    Scores an agent based on how many lead criteria match their assigned_locations
    and assigned_property_types.
    Accepts agent as dict or ORM object, and lead data as dict or individual strings.
    Returns integer hit count.
    """
    if not agent:
        return 0

    # Support dict or ORM agent
    if isinstance(agent, dict):
        assigned_locs = agent.get("assigned_locations") or []
        assigned_ptypes = agent.get("assigned_property_types") or []
    else:
        assigned_locs = getattr(agent, "assigned_locations", None) or getattr(agent, "specialization_locations", None) or []
        assigned_ptypes = getattr(agent, "assigned_property_types", None) or getattr(agent, "specialization_property_types", None) or []

    # Support lead_data dict as second arg (from tests) or individual strings (from production)
    if isinstance(lead_location_or_data, dict):
        lead_data = lead_location_or_data
        lead_location = lead_data.get("city") or lead_data.get("location") or lead_data.get("state") or ""
        cats = lead_data.get("property_category") or []
        lead_property_type = cats[0] if isinstance(cats, list) and cats else (cats if isinstance(cats, str) else "")
        raw_inquiry_text = lead_data.get("inquiry_text") or lead_data.get("raw_text") or ""
    else:
        lead_location = lead_location_or_data or ""

    score = 0
    searchable_text = f"{lead_location or ''} {lead_property_type or ''} {raw_inquiry_text or ''}".lower()

    # Match locations
    for loc in assigned_locs:
        if not loc or not isinstance(loc, str):
            continue
        loc_clean = loc.strip().lower()
        if not loc_clean:
            continue
        if (lead_location and loc_clean in lead_location.lower()) or (loc_clean in searchable_text):
            score += 1

    # Match property types
    for ptype in assigned_ptypes:
        if not ptype or not isinstance(ptype, str):
            continue
        ptype_clean = ptype.strip().lower()
        if not ptype_clean:
            continue
        if (lead_property_type and ptype_clean in lead_property_type.lower()) or (ptype_clean in searchable_text):
            score += 1
        elif ptype_clean == "land / agriculture" and (
            any(k in searchable_text for k in ["agriculture", "tanah", "kebun", "ladang", "pertanian"])
            or ("land" in searchable_text and "durian" not in searchable_text)
        ):
            score += 1
        elif ptype_clean == "durian land" and any(k in searchable_text for k in ["durian", "musang king", "black thorn", "d24"]):
            score += 1

    return score


def dispatch_hot_lead_handover(
    conversation_id_or_data=None,
    customer_name: str = "",
    customer_phone: str = "",
    intent: str = "BUYER",
    location: str = "",
    property_type: str = "",
    budget: str = "",
    conversation_summary: str = "",
    cw_link: str = "",
    inbox_id: int = 3,
    raw_inquiry_text: str = "",
    db: SessionLocal = None
) -> dict:
    """
    Dynamic Hot Lead Handover routing based on agent specialization:
    - Queries active agents and employees from crm_users (or get_active_agents_and_employees).
    - Scores each candidate based on hit count matching assigned_locations and assigned_property_types.
    - Top scoring agent receives WhatsApp alert template and customer contact card.
    - Tie Handling: If multiple agents have identical highest hit count, sends to all tied agents
      with additional remark: '⚠️ Shared Case: This inquiry is also shared with Agent [Name/Phone].'
    - Fallback: If no agents have hits (score = 0) or no active agents, routes to the 2 main admin numbers.
    - Always attaches the assigned contact card (vCard / WhatsApp contact payload) to the customer.
    """
    if isinstance(conversation_id_or_data, dict):
        lead_data = conversation_id_or_data
        conversation_id = lead_data.get("conversation_id", 0)
        customer_name = lead_data.get("customer_name") or "Valued Customer"
        customer_phone = lead_data.get("customer_phone") or ""
        intent = lead_data.get("intent") or "BUYER"
        location = lead_data.get("city") or lead_data.get("location") or lead_data.get("state") or ""
        cats = lead_data.get("property_category") or []
        property_type = cats[0] if isinstance(cats, list) and cats else (cats if isinstance(cats, str) else "")
        budget = lead_data.get("budget") or "Not Specified"
        conversation_summary = lead_data.get("title") or lead_data.get("inquiry_text") or "Inquiry"
        cw_link = lead_data.get("cw_link") or f"https://inbox.bentongland.com.my/app/accounts/1/conversations/{conversation_id}"
        inbox_id = lead_data.get("inbox_id") or 3
        raw_inquiry_text = lead_data.get("inquiry_text") or lead_data.get("raw_text") or ""
    else:
        conversation_id = conversation_id_or_data

    close_db = False
    if db is None:
        try:
            db = SessionLocal()
            close_db = True
        except Exception:
            db = None

    try:
        # 1. Query active agents and employees with configured phone number
        raw_agents = get_active_agents_and_employees()
        if raw_agents is None and db is not None:
            try:
                raw_agents = db.query(User).filter(
                    User.is_active == True,
                    User.role.in_(["agent", "employee"]),
                    User.phone_number.isnot(None),
                    User.phone_number != ""
                ).all()
            except Exception as dbe:
                logger.warning(f"Could not query User model from DB: {dbe}")
                raw_agents = []

        scored_candidates = []
        for agent in (raw_agents or []):
            agent_phone = agent.get("phone_number") if isinstance(agent, dict) else getattr(agent, "phone_number", None)
            if not agent_phone:
                continue
            score = calculate_agent_specialization_score(
                agent=agent,
                lead_location_or_data=location,
                lead_property_type=property_type,
                raw_inquiry_text=raw_inquiry_text
            )
            agent_name = agent.get("name") if isinstance(agent, dict) else (getattr(agent, "full_name", None) or getattr(agent, "username", "Agent"))
            scored_candidates.append({
                "agent": agent,
                "score": score,
                "phone": agent_phone,
                "name": agent_name
            })

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        max_score = scored_candidates[0]["score"] if scored_candidates else 0

        TEMPLATE_PHONE_NUMBER_ID = os.getenv(
            "WHATSAPP_TEMPLATE_PHONE_NUMBER_ID",
            "1039310802596891"
        )

        routed_targets = []
        is_fallback = False
        is_tie = False

        if max_score > 0:
            top_candidates = [c for c in scored_candidates if c["score"] == max_score]
            if len(top_candidates) == 1:
                winner = top_candidates[0]
                routed_targets.append({
                    "phone": winner["phone"],
                    "name": winner["name"],
                    "score": winner["score"],
                    "remark": ""
                })
            else:
                is_tie = True
                for cand in top_candidates:
                    other_agents = [f"{o['name']} ({o['phone']})" for o in top_candidates if o["phone"] != cand["phone"]]
                    others_str = ", ".join(other_agents)
                    shared_remark = f"⚠️ Shared Case: This inquiry is also shared with Agent {others_str}."
                    routed_targets.append({
                        "phone": cand["phone"],
                        "name": cand["name"],
                        "score": cand["score"],
                        "remark": shared_remark
                    })
        else:
            is_fallback = True
            for admin_phone in DEFAULT_FALLBACK_ADMIN_NUMBERS:
                routed_targets.append({
                    "phone": admin_phone,
                    "name": f"Admin ({admin_phone})",
                    "score": 0,
                    "remark": "ℹ️ Handover Fallback: No matching agent specialization found."
                })

        dispatched_phones = []
        for target in routed_targets:
            target_phone = target["phone"]
            try:
                contact_id = get_or_create_contact(target_phone, f"Staff/Admin {target['name']}")
                if contact_id:
                    create_conversation(contact_id, inbox_id)
            except Exception as ce:
                logger.warning(f"Could not prepare chatwoot contact for {target_phone}: {ce}")

            summary_with_remark = conversation_summary
            if target.get("remark"):
                summary_with_remark = f"{conversation_summary}\n\n{target['remark']}"
            if len(summary_with_remark) > 500:
                summary_with_remark = summary_with_remark[:497] + "..."

            template_params = [
                customer_name,
                customer_phone,
                intent.upper(),
                str(location),
                str(property_type),
                str(budget),
                summary_with_remark,
                cw_link
            ]

            # 1. Send WhatsApp Template to staff / admin
            send_whatsapp_template(
                inbox_id=inbox_id,
                to_phone=target_phone,
                template_name="new_lead_alert_utility",
                parameters=template_params,
                language_code="en",
                override_phone_number_id=TEMPLATE_PHONE_NUMBER_ID
            )
            dispatched_phones.append(target_phone)

        # 2. Attach primary contact card to customer once
        if customer_phone and routed_targets:
            primary_target = routed_targets[0]
            send_whatsapp_contact(
                inbox_id=inbox_id,
                to_phone=customer_phone,
                contact_name=primary_target["name"],
                contact_phone=primary_target["phone"],
                override_phone_number_id=TEMPLATE_PHONE_NUMBER_ID
            )

        routing_notes = []
        if is_fallback:
            routing_notes.append("⚠️ Routed to Main Admin Lines (Score: 0 - No specialization matches)")
        elif is_tie:
            tied_names = [f"{t['name']} ({t['phone']})" for t in routed_targets]
            routing_notes.append(f"⚠️ Multi-Agent Shared Tie (Score: {max_score}) dispatched to: {', '.join(tied_names)}")
        else:
            w = routed_targets[0]
            routing_notes.append(f"✅ Routed to Specialist Agent: {w['name']} ({w['phone']}) with Match Score: {w['score']}")

        private_note_text = (
            f"🔥 **HOT LEAD / HUMAN HANDOVER TRIGGERED**\n\n"
            f"👤 **Customer**: {customer_name} ({customer_phone})\n"
            f"🎯 **Intent**: {intent.upper()}\n"
            f"📍 **Location**: {location}\n"
            f"🏡 **Property Type**: {property_type}\n"
            f"💰 **Budget / Price**: {budget}\n\n"
            f"🔀 **Routing Decision**: {'; '.join(routing_notes)}\n"
            f"📝 **AI Summary**: {conversation_summary}\n\n"
            f"⚡ **Status**: AI response paused (`bypass_ai=True`). Handed over to human agent."
        )
        if conversation_id:
            try:
                send_private_note(conversation_id, private_note_text)
            except Exception as ne:
                logger.error(f"Failed to post internal private note on handover: {ne}")

        assigned_agent_list = [
            {"name": t["name"], "phone_number": t["phone"], "score": t["score"]}
            for t in routed_targets if not is_fallback
        ]

        return {
            "status": "fallback_to_admin" if is_fallback else "success",
            "assigned_agents": assigned_agent_list,
            "winning_score": max_score,
            "routed_to": dispatched_phones,
            "is_fallback": is_fallback,
            "is_tie": is_tie,
            "top_score": max_score,
            "targets": routed_targets
        }
    finally:
        if close_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=3)
def process_conversation_queue(self, conversation_id: int, task_scheduled_time: float):
    """
    Processes all queued messages for a conversation if the user has stopped typing.
    """
    try:
        active_key = f"convo_active_{conversation_id}"
        last_active_raw = redis_client.get(active_key)
        
        if not last_active_raw:
            logger.info(f"Conversation {conversation_id} has no active timestamp. Skipping.")
            return {"status": "skipped", "reason": "no active timestamp"}
            
        last_active = float(last_active_raw)
        
        # Check if the user is still typing within the 10 second window
        current_time = time.time()
        time_since_active = current_time - last_active
        
        # We want to wait for 10 seconds of inactivity
        if time_since_active < TIMEOUT_SECONDS:
            wait_time = int(TIMEOUT_SECONDS - time_since_active) + 1
            logger.info(f"User is still active in conversation {conversation_id}. Rescheduling for {wait_time}s.")
            process_conversation_queue.apply_async(
                args=[conversation_id, task_scheduled_time],
                countdown=wait_time
            )
            return {"status": "deferred", "reason": "user still active"}
            
        # Master AI Toggle check
        master_ai_raw = redis_client.get("master_ai_enabled")
        master_ai_enabled = master_ai_raw.decode("utf-8") == "true" if master_ai_raw else True
        if not master_ai_enabled:
            logger.info(f"Master AI Toggle is OFF. Skipping conversation {conversation_id} and clearing queue.")
            # Turn off typing indicator if it was triggered
            try:
                toggle_typing_status(conversation_id, "off")
            except Exception:
                pass
            # Flush the message queue so it doesn't pile up
            queue_key = f"convo_queue_{conversation_id}"
            redis_client.delete(queue_key)
            return {"status": "skipped", "reason": "master_ai_disabled"}

        # If we reach here, it's been at least 10 seconds since the last message and AI is ON.
        
        # Human Override Check: Only skip if the conversation has been explicitly assigned to a human or flagged
        # Note: Chatwoot API tokens create messages with sender_type='user', so we do not blindly drop on outgoing messages.


        # Let's atomically grab all messages in the queue and delete the queue.
        queue_key = f"convo_queue_{conversation_id}"
        
        # We can use a pipeline to execute this atomically
        pipe = redis_client.pipeline()
        pipe.lrange(queue_key, 0, -1)
        pipe.delete(queue_key)
        pipe.delete(active_key)
        results = pipe.execute()
        
        raw_messages = results[0]
        if not raw_messages:
            logger.info(f"Queue for conversation {conversation_id} is empty. Skipping.")
            return {"status": "skipped", "reason": "empty queue"}
            
        messages = [json.loads(msg) for msg in raw_messages]
        logger.info(f"Aggregating {len(messages)} messages for conversation {conversation_id}")
        
        combined_text = []
        combined_images = []
        contact_info = messages[0].get("sender", {})
        
        for msg_payload in messages:
            content = msg_payload.get("content", "")
            if content:
                combined_text.append(content)
                
            attachments = msg_payload.get("attachments", [])
            if attachments:
                for attachment in attachments:
                    file_type = attachment.get("file_type")
                    data_url = attachment.get("data_url")
                    
                    if file_type == "audio":
                        logger.info(f"Audio attachment detected. Downloading and transcribing...")
                        try:
                            transcription_text = transcribe_audio(data_url)
                            if transcription_text:
                                combined_text.append(f"[Audio Transcript]: {transcription_text}")
                        except Exception as e:
                            logger.error(f"Failed to process audio attachment: {e}")
                            
                    elif file_type == "image":
                        logger.info("Image attachment detected. Downloading and encoding...")
                        try:
                            img_resp = requests.get(data_url, timeout=30)
                            img_resp.raise_for_status()
                            b64_image = base64.b64encode(img_resp.content).decode("utf-8")
                            combined_images.append(b64_image)
                        except Exception as e:
                            logger.error(f"Failed to process image attachment: {e}")
                        
                    elif file_type == "file":
                        logger.info("Document/PDF attachment detected.")
                        try:
                            doc_result = extract_text_from_document(data_url, attachment.get("data_file_name", ""))
                            doc_text = doc_result.get("text", "")
                            if doc_text:
                                combined_text.append(f"[Document Content]: {doc_text}")
                            
                            doc_images = doc_result.get("images", [])
                            if doc_images:
                                logger.info(f"Extracted {len(doc_images)} images from document.")
                                combined_images.extend(doc_images)
                        except Exception as e:
                            logger.error(f"Failed to extract document text/images: {e}")
        final_prompt_text = "\n".join(combined_text).strip()
            
        if not final_prompt_text:
            logger.info("No text or audio to process. Skipping.")
            return {"status": "skipped", "reason": "empty aggregated input"}
            
        # 2. LLM Intent Classification & Response Generation
        logger.info(f"Generating LLM response for aggregated text:\n{final_prompt_text}")
        
        # Turn typing on
        try:
            toggle_typing_status(conversation_id, "on")
        except Exception as e:
            logger.warning(f"Failed to turn typing status on: {e}")
            
        # Auto-save Customer and enforce RBAC context
        phone_number = contact_info.get("phone_number", "")
        contact_name = contact_info.get("name", "Unknown")
        email = contact_info.get("email")
        
        # Extract additional metadata
        first_msg = messages[0] if messages else {}
        convo_data = first_msg.get("conversation", {})
        session_id = convo_data.get("uuid") or convo_data.get("session_id") or "Unknown"

        is_staging_env = (
            os.getenv("DB_HOST") == "whatsapp_ai_db_staging"
            or "staging" in os.getenv("REDIS_HOST", "")
            or os.getenv("APP_ENV") == "staging"
            or os.getenv("ENVIRONMENT", "").lower() == "staging"
        )
        staging_inbox_id = int(os.getenv("STAGING_INBOX_ID", "4"))
        default_inbox = staging_inbox_id if is_staging_env else 1

        inbox_id_raw = (
            first_msg.get("inbox", {}).get("id") 
            or convo_data.get("inbox_id") 
            or first_msg.get("inbox_id")
        )
        inbox_id_val = int(inbox_id_raw) if inbox_id_raw is not None else default_inbox
        metadata = {
            "session_id": session_id,
            "inbox_id": inbox_id_val,
            "contact_id": contact_info.get("id"),
            "environment": "staging" if is_staging_env else "production"
        }
        
        customer = get_or_create_customer(
            phone_number=phone_number, 
            contact_name=contact_name, 
            email=email, 
            conversation_id=conversation_id, 
            metadata=metadata
        )
        
        if customer and customer.metadata_json and customer.metadata_json.get("bypass_ai"):
            logger.info(f"Customer {customer.id} has bypass_ai set. Skipping AI response.")
            try:
                toggle_typing_status(conversation_id, "off")
            except:
                pass
            return {"status": "skipped", "reason": "bypass_ai is true"}
        
        role = get_sender_role(phone_number)
        
        criteria = {}
        conversation_history = ""
        
        # Build DB context based on RBAC
        db_context = {"role": role, "data": {}}
        db = SessionLocal()
        try:
            if role == "admin":
                # Admin: all data (properties, all customer records, employee/agent roster, system metrics)
                db_context["data"]["metrics"] = {
                    "total_properties": db.query(Property).count(),
                    "total_customers": db.query(Customer).count(),
                    "total_users": db.query(User).count(),
                    "active_agents": db.query(User).filter(User.role.in_(["agent", "employee"]), User.is_active == True).count()
                }
                db_context["data"]["customers"] = [
                    {"id": str(c.id), "name": c.contact_name, "phone": str(c.id), "email": c.email, "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None}
                    for c in db.query(Customer).order_by(Customer.last_interaction.desc()).limit(20).all()
                ]
                db_context["data"]["properties"] = [
                    {"id": str(p.id), "title": p.title, "price": p.asking_price_myr, "status": p.listing_status, "city": p.city, "category": p.property_category}
                    for p in db.query(Property).limit(20).all()
                ]
                db_context["data"]["roster"] = [
                    {"username": u.username, "name": u.full_name, "role": u.role, "phone": u.phone_number, "locations": u.assigned_locations, "types": u.assigned_property_types}
                    for u in db.query(User).filter(User.is_active == True).all()
                ]
            elif role in ["agent", "employee"]:
                # Agent or Employee: full property details plus customer information (leads, inquiries, customer requirements)
                db_context["data"]["customers"] = [
                    {"id": str(c.id), "name": c.contact_name, "phone": str(c.id), "email": c.email, "metadata": c.metadata_json}
                    for c in db.query(Customer).order_by(Customer.last_interaction.desc()).limit(25).all()
                ]
                db_context["data"]["properties"] = [
                    {"id": str(p.id), "title": p.title, "price": p.asking_price_myr, "status": p.listing_status, "city": p.city, "specs": p.search_corpus_markdown[:200] if p.search_corpus_markdown else None}
                    for p in db.query(Property).limit(25).all()
                ]
            else:
                # Customer: own data only
                if customer:
                    db_context["data"]["my_orders"] = [{"id": str(o.id), "status": o.status, "total": o.total_amount} for o in db.query(Order).filter(Order.customer_id == customer.id).all()]
                
                
                # Fetch conversation history
                logger.info(f"Fetching conversation history for {conversation_id}")
                try:
                    chatwoot_messages = get_conversation_messages(conversation_id)
                    chatwoot_messages.sort(key=lambda x: x.get("created_at", 0))

                    # Conversation Reset Cutoff: Ensure messages prior to /reset are never passed to AI
                    reset_cutoff_ts = 0.0
                    try:
                        reset_ts_raw = redis_client.get(f"convo_reset_at_{conversation_id}")
                        if reset_ts_raw:
                            reset_cutoff_ts = max(reset_cutoff_ts, float(reset_ts_raw.decode("utf-8") if isinstance(reset_ts_raw, bytes) else reset_ts_raw))
                    except Exception as r_err:
                        logger.warning(f"Could not check redis reset cutoff for conv {conversation_id}: {r_err}")

                    def _parse_msg_ts(m):
                        raw_ts = m.get("created_at")
                        if isinstance(raw_ts, (int, float)):
                            return raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
                        if isinstance(raw_ts, str):
                            try:
                                return datetime.datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
                            except Exception:
                                pass
                        return 0.0

                    for msg in chatwoot_messages:
                        if msg.get("private") and "/reset" in (msg.get("content") or ""):
                            msg_created = _parse_msg_ts(msg)
                            if msg_created > reset_cutoff_ts:
                                reset_cutoff_ts = msg_created

                    if reset_cutoff_ts > 0:
                        logger.info(f"Purging pre-reset messages for conv {conversation_id} prior to timestamp {reset_cutoff_ts}")
                        chatwoot_messages = [msg for msg in chatwoot_messages if _parse_msg_ts(msg) > reset_cutoff_ts]

                    # Prior conversation history must strictly exclude the incoming message currently being processed
                    prior_msgs = chatwoot_messages
                    if prior_msgs:
                        last_non_priv = next((m for m in reversed(prior_msgs) if not m.get("private")), None)
                        if last_non_priv and (last_non_priv.get("content") or "").strip() == final_prompt_text.strip():
                            prior_msgs = [m for m in prior_msgs if m is not last_non_priv]

                    history_lines = []
                    # Get last 10 messages, older first (chronological order), excluding private notes
                    for msg in prior_msgs[-10:]:
                        if msg.get("private"):
                            continue
                        m_type = msg.get("message_type")
                        is_assistant = m_type in [1, "1", "outgoing", 3, "3", "template"]
                        sender = "Assistant" if is_assistant else "User"
                        content = msg.get("content") or ""
                        if content.strip():
                            history_lines.append(f"{sender}: {content.strip()}")
                    conversation_history = "\n".join(history_lines)
                except Exception as e:
                    logger.error(f"Failed to fetch history: {e}")
                    conversation_history = ""
                    
                # Perform RAG search for properties
                logger.info(f"Extracting search criteria from prompt: {final_prompt_text}")
                criteria = extract_property_search_criteria(final_prompt_text, conversation_history)
                logger.info(f"Extracted criteria: {criteria}")
                
                if criteria and any(criteria.values()):
                    matched_properties = search_properties(criteria, limit=15)
                    logger.info(f"Found {len(matched_properties)} matching properties.")
                    db_context["data"]["properties"] = matched_properties
                else:
                    # Fallback to general available properties if no criteria
                    db_context["data"]["properties"] = [{"id": str(p.id), "name": p.title, "price": p.asking_price_myr, "status": p.listing_status} for p in db.query(Property).filter(Property.listing_status == "Available").limit(10).all()]
        finally:
            db.close()
        
        # Use Database-Driven Persona Agent State Machine
        from app.services.agent_logic import process_persona_state_machine
        
        with SessionManager.lock_session(phone_number):
            session = SessionManager.get_session(phone_number)
            # If conversation history is empty or reset cutoff occurred after session creation, perform a deep wipe
            is_fresh_convo = not conversation_history.strip() or (reset_cutoff_ts > 0 and reset_cutoff_ts >= session.get("created_at", 0))
            if is_fresh_convo:
                session.clear()
                session.update(SessionManager._new_session())
            
            agent_result = process_persona_state_machine(
                phone_number, final_prompt_text, session,
                conversation_history=conversation_history,
                contact_name=contact_name,
                role=role,
                db_context=db_context
            )
            session = agent_result.get("updated_session", session)
            
            intent = session.get("current_agent", "general").lower()
            response_text = agent_result.get("response", "Sorry, I couldn't process your request.")
            handover_from_state = agent_result.get("handover", False)
            assignee_email = agent_result.get("assignee_email")
            images_to_send = agent_result.get("images_to_send", [])
            
            # Dynamic lead temperature based on 80% persona data completeness
            REQUIRED_PERSONA_KEYS = {
                "buyer": ["name", "buyer_location", "buyer_property_type", "buyer_budget", "purchase_entity"],
                "seller": ["name", "is_owner", "property_type", "location", "asking_price"],
                "tenant": ["name", "current_location", "property_type", "budget", "use_type"],
                "landlord": ["name", "is_owner", "property_type", "location", "expected_rental"],
                "agent": ["name", "company_name", "coverage_area", "collaboration_type"],
                "bank valuer": ["customer_name", "property_address", "property_type", "contact_phone"]
            }
            alias_map = {
                "location": ["buyer_location", "seller_location", "current_location", "coverage_area"],
                "current_location": ["location", "buyer_location", "seller_location", "coverage_area"],
                "buyer_location": ["location", "current_location", "seller_location"],
                "seller_location": ["location", "current_location"],
                "property_type": ["buyer_property_type", "seller_property_type"],
                "buyer_property_type": ["property_type", "seller_property_type"],
                "seller_property_type": ["property_type", "buyer_property_type"],
                "budget": ["buyer_budget", "asking_price", "expected_rental", "max_price"],
                "buyer_budget": ["budget", "asking_price", "expected_rental", "max_price"],
                "asking_price": ["budget", "buyer_budget", "expected_rental"],
                "expected_rental": ["budget", "buyer_budget", "asking_price"]
            }
            
            collected = session.get("collected_data", {})
            req_keys = REQUIRED_PERSONA_KEYS.get(intent, ["name", "location", "property_type"])
            filled_count = 0
            for k in req_keys:
                if collected.get(k):
                    filled_count += 1
                elif k in alias_map and any(collected.get(alt) for alt in alias_map[k]):
                    filled_count += 1
            
            completeness_ratio = (filled_count / len(req_keys)) if req_keys else 0.0
            
            if completeness_ratio >= 0.8:
                lead_temp = "Hot"
            elif completeness_ratio >= 0.4:
                lead_temp = "Warm"
            else:
                lead_temp = "Cold"
            
            has_cached_prop = bool(session.get("interested_property"))
            # Detect explicit immediate human contact / phone call requests
            user_wants_immediate_human = any(phrase in final_prompt_text.lower() for phrase in [
                "call me", "speak to human", "talk to agent", "contact me directly",
                "transfer to human", "speak to a person", "talk to a person", "real agent",
                "real person", "human agent", "human staff", "person in charge", "pic",
                "真人", "转人工", "人工客服", "联系真人", "找真人",
                "电话联系", "安排见面", "nak jumpa", "call saya", "hubungi saya", "agent sebenar", 
                "cakap dengan orang", "temujanji"
            ])
            # Physical inspection bookings trigger handover when an actual property is selected
            user_books_inspection = has_cached_prop and any(phrase in final_prompt_text.lower() for phrase in [
                "安排看房", "预约看房", "睇楼", "tengok rumah", "tengok tanah", "arrange viewing", "schedule viewing", "book viewing"
            ])
            
            # Handover should ONLY trigger when:
            # 1. State machine finished workflow (handover_from_state == True)
            # 2. Or user explicitly asks for immediate human contact or books a physical inspection for a known property
            # 3. Or bank valuer submission complete
            # P1 fix: Require at least 1 prior AI response before explicit handover triggers
            assistant_msg_count = conversation_history.count("Assistant:") if conversation_history else 0
            handover_initiated = False
            if role not in ["admin", "employee"]:
                if handover_from_state:
                    handover_initiated = True
                elif (user_wants_immediate_human or user_books_inspection) and assistant_msg_count >= 1:
                    handover_initiated = True
                    # Append polite wrap-up if not already present
                    if "senior" not in response_text.lower() and "specialist" not in response_text.lower() and "representative" not in response_text.lower():
                        response_text += f"\n\nThank you, {contact_name}! 😊 We have noted your request. A senior property specialist from Home IHC will contact you shortly to assist directly."
                elif intent == "bank valuer" and 'valuer_data' in locals() and valuer_data:
                    handover_initiated = True
            
            SessionManager.save_session(phone_number, session)
            
        # Generate a real AI summary from the conversation
        try:
            from app.services.llm import llm_client, LLM_MODEL_NAME
            summary_messages = [
                {"role": "system", "content": "Summarize this customer interaction in 1-2 sentences for an agent briefing. Include the customer's intent, what information was collected, and current status. Be concise."},
                {"role": "user", "content": f"Customer: {contact_name}, Phone: {phone_number}\nLatest message: {final_prompt_text}\nCollected data: {json.dumps(session.get('collected_data', {}))}\nCurrent workflow: {intent}\nHandover: {handover_initiated}"}
            ]
            summary_resp = llm_client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=summary_messages,
                temperature=0.0,
                max_tokens=150
            )
            conversation_summary_text = summary_resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate AI summary: {e}")
            conversation_summary_text = f"Customer {contact_name} inquired about {intent}. Data collected: {json.dumps(session.get('collected_data', {}))}"
        
        llm_response = {"summary": conversation_summary_text}        
        if intent == "bank valuer":
            valuer_data = extract_valuer_data(final_prompt_text, conversation_history)
            if valuer_data and any(valuer_data.values()):
                logger.info(f"Extracted bank valuer data: {valuer_data}")
                if customer:
                    db = SessionLocal()
                    try:
                        db_cust = db.query(Customer).filter(Customer.id == customer.id).first()
                        if db_cust:
                            meta = db_cust.metadata_json.copy() if db_cust.metadata_json else {}
                            if "bank_valuations" not in meta:
                                meta["bank_valuations"] = []
                            meta["bank_valuations"].append(valuer_data)
                            db_cust.metadata_json = meta
                            db.commit()
                    except Exception as e:
                        logger.error(f"Failed to save valuer data: {e}")
                        db.rollback()
                    finally:
                        db.close()

        if role not in ["admin", "employee", "agent"] and handover_initiated:
            # 1. Extract enriched lead details for alert template and internal note
            loc_val = (
                collected.get("location") or 
                collected.get("seller_location") or 
                collected.get("buyer_location") or 
                collected.get("current_location") or 
                collected.get("coverage_area")
            )
            location = str(loc_val) if loc_val else "Pahang (To be advised)"
            
            ptype_val = (
                collected.get("property_type") or 
                collected.get("seller_property_type") or 
                collected.get("buyer_property_type") or 
                collected.get("use_type")
            )
            property_type = str(ptype_val) if ptype_val else "Commercial / Residential / Land"
            
            budget_val = (
                collected.get("budget") or 
                collected.get("buyer_budget") or 
                collected.get("asking_price") or 
                collected.get("expected_rental")
            )
            budget = str(budget_val) if budget_val else "To be discussed in meeting"
            
            if intent == "bank valuer" and 'valuer_data' in locals() and valuer_data:
                location = str(valuer_data)
                property_type = "Bank Valuation"
                budget = "N/A"
                
            conversation_summary = llm_response.get("summary", "No summary available.")
            if isinstance(conversation_summary, str):
                conversation_summary = conversation_summary.replace('\n', ' ').replace('\t', ' ')
                if len(conversation_summary) > 500:
                    conversation_summary = conversation_summary[:497] + "..."

            inbox_id = metadata.get("inbox_id") or (staging_inbox_id if is_staging_env else 1)
            cw_link = f"https://inbox.bentongland.com.my/app/accounts/{CHATWOOT_ACCOUNT_ID}/inbox/{inbox_id}/conversations/{conversation_id}"

            # 2. Dynamic Hot Lead Handover routing based on agent specialization
            try:
                handover_result = dispatch_hot_lead_handover(
                    conversation_id=conversation_id,
                    customer_name=contact_name,
                    customer_phone=phone_number,
                    intent=intent,
                    location=location,
                    property_type=property_type,
                    budget=budget,
                    conversation_summary=conversation_summary,
                    cw_link=cw_link,
                    inbox_id=inbox_id,
                    raw_inquiry_text=final_prompt_text
                )
                logger.info(f"Dynamic handover completed: {handover_result}")
            except Exception as e:
                logger.error(f"Failed in dispatch_hot_lead_handover: {e}")
        
        # 3. Dispatch native images if requested
        if images_to_send:
            for idx, img_url in enumerate(images_to_send):

                try:
                    logger.info(f"Dispatching transcoded image {idx+1}/{len(images_to_send)}: {img_url} to conv {conversation_id}")
                    send_chatwoot_image_attachment(
                        conversation_id=conversation_id,
                        image_url=img_url
                    )
                    time.sleep(0.4)
                except Exception as img_err:
                    logger.error(f"Failed to dispatch image {img_url}: {img_err}")


        # 4. Send response back to Chatwoot FIRST (ensures wrap-up message is delivered)
        logger.info(f"Sending response to conversation {conversation_id}")
        send_message(conversation_id, response_text)

        # 4.1 Autonomous Viewing Acknowledgement Form Dispatch
        if agent_result.get("schedule_viewing") and customer:
            try:
                from app.services.viewing_service import create_and_dispatch_viewing_form
                viewing_prop = agent_result.get("viewing_property") or {}
                prop_id = viewing_prop.get("id")
                v_date = agent_result.get("viewing_date")
                
                logger.info(f"Triggering autonomous viewing form generation for customer {phone_number} on {v_date}")
                create_and_dispatch_viewing_form(
                    customer_id=phone_number,
                    property_id=prop_id,
                    viewing_date=v_date,
                    conversation_id=conversation_id,
                    customer_name=contact_name or customer.contact_name,
                    phone_number=phone_number,
                    dispatch_to_customer=True
                )
            except Exception as vf_err:
                logger.error(f"Error in autonomous viewing form generation/dispatch: {vf_err}")
        
        # Turn typing off
        try:
            toggle_typing_status(conversation_id, "off")
        except Exception as e:
            logger.warning(f"Failed to turn typing status off: {e}")
            
        # Update customer with bypass_ai ONLY after response is sent
        if customer and handover_initiated:
            db = SessionLocal()
            try:
                db_cust = db.query(Customer).filter(Customer.id == customer.id).first()
                if db_cust:
                    meta = db_cust.metadata_json.copy() if db_cust.metadata_json else {}
                    meta["bypass_ai"] = True
                    db_cust.metadata_json = meta
                    db.commit()
            except Exception as e:
                logger.error(f"Failed to update customer bypass_ai flag: {e}")
                db.rollback()
            finally:
                db.close()
        
        # Turn typing off
        try:
            toggle_typing_status(conversation_id, "off")
        except Exception as e:
            logger.warning(f"Failed to turn typing status off: {e}")
        
        # 4. Apply intent label and priority
        labels_to_apply = []
        if role in ["admin", "employee", "agent"]:
            labels_to_apply.append(role)
        else:
            if intent in ["buyer", "seller", "tenant", "agent", "bank valuer"]:
                labels_to_apply.append(intent.lower())
                
            if handover_initiated:
                labels_to_apply.append("handover_initiated")
                
                # Assign agent if specified
                if assignee_email:
                    try:
                        agent_id = get_agent_id_by_email(assignee_email)
                        if agent_id:
                            assign_agent(conversation_id, agent_id)
                    except Exception as e:
                        logger.error(f"Failed to assign agent on handover: {e}")
                
            # Map temperature to priority and labels
            priority_map = {
                "hot": "high",
                "warm": "medium",
                "cold": "low"
            }
            
            temp_lower = lead_temp.lower() if lead_temp else "warm"
            if temp_lower in priority_map:
                labels_to_apply.append(temp_lower)
                try:
                    set_priority(conversation_id, priority_map[temp_lower])
                except Exception as e:
                    logger.warning(f"Failed to set priority: {e}")
                
        if labels_to_apply:
            logger.info(f"Applying labels {labels_to_apply} to conversation {conversation_id}")
            apply_label(conversation_id, labels_to_apply)
        
        return {"status": "success", "conversation_id": conversation_id, "messages_processed": len(messages)}
        
    except Exception as exc:
        # Attempt to turn typing off in case of an error
        try:
            toggle_typing_status(conversation_id, "off")
        except:
            pass
        logger.error(f"Error processing conversation {conversation_id}: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

@celery_app.task(bind=True, max_retries=3)
def process_wordpress_property(self, payload: dict):
    """
    Processes a raw WordPress webhook payload, extracts property details via LLM,
    and upserts into the database.
    """
    try:
        logger.info(f"Processing WordPress property: {payload.get('title')}")
        extracted_data = extract_wordpress_property(payload)
        
        title = payload.get("title", "")
        if not title:
            logger.error("No title found in WordPress payload, skipping.")
            return {"status": "failed", "reason": "no title"}
            
        # Optional fields from payload directly
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        image_urls = payload.get("image_urls", [])
        if isinstance(image_urls, str):
            image_urls = [image_urls]
        db = SessionLocal()
        try:
            existing = db.query(Property).filter(Property.title == title).first()
            if existing:
                # Update existing property
                existing.search_corpus_markdown = payload.get("description", existing.search_corpus_markdown)
                existing.source_url = payload.get("source_url", existing.source_url)
                if latitude is not None: existing.latitude = latitude
                elif extracted_data.get("latitude") is not None: existing.latitude = extracted_data.get("latitude")
                
                if longitude is not None: existing.longitude = longitude
                elif extracted_data.get("longitude") is not None: existing.longitude = extracted_data.get("longitude")
                
                if image_urls: existing.image_urls = image_urls
                
                # Fields from extraction
                existing.property_type_sub = extracted_data.get("property_type_sub", existing.property_type_sub)
                existing.asking_price_myr = extracted_data.get("asking_price_myr", existing.asking_price_myr)
                existing.monthly_rental_income_myr = extracted_data.get("monthly_rental_income_myr", existing.monthly_rental_income_myr)
                existing.price_per_acre_myr = extracted_data.get("price_per_acre_myr", existing.price_per_acre_myr)
                existing.price_per_sqft_myr = extracted_data.get("price_per_sqft_myr", existing.price_per_sqft_myr)
                existing.implied_yield_pct = extracted_data.get("implied_yield_pct", existing.implied_yield_pct)
                existing.property_category = extracted_data.get("property_category", existing.property_category)
                existing.land_area_sqft = extracted_data.get("land_area_sqft", existing.land_area_sqft)
                existing.land_area_acres = extracted_data.get("land_area_acres", existing.land_area_acres)
                existing.land_area_sqm = extracted_data.get("land_area_sqm", existing.land_area_sqm)
                existing.built_up_area_sqft = extracted_data.get("built_up_area_sqft", existing.built_up_area_sqft)
                existing.tenure_type = extracted_data.get("tenure_type", existing.tenure_type)
                existing.zoning_type = extracted_data.get("zoning_type", existing.zoning_type)
                existing.title_status = extracted_data.get("title_status", existing.title_status)
                
                existing.crop_types = extracted_data.get("crop_types", existing.crop_types)
                existing.tree_count_estimate = extracted_data.get("tree_count_estimate", existing.tree_count_estimate)
                existing.tree_age_years = extracted_data.get("tree_age_years", existing.tree_age_years)
                existing.harvest_readiness = extracted_data.get("harvest_readiness", existing.harvest_readiness)
                
                existing.topography = extracted_data.get("topography", existing.topography)
                existing.water_source_types = extracted_data.get("water_source_types", existing.water_source_types)
                existing.has_natural_stream = extracted_data.get("has_natural_stream", existing.has_natural_stream)
                existing.has_pond = extracted_data.get("has_pond", existing.has_pond)
                existing.has_piping_system = extracted_data.get("has_piping_system", existing.has_piping_system)
                existing.is_flood_free = extracted_data.get("is_flood_free", existing.is_flood_free)
                
                existing.power_supply_amp = extracted_data.get("power_supply_amp", existing.power_supply_amp)
                existing.utilities_available = extracted_data.get("utilities_available", existing.utilities_available)
                existing.has_office = extracted_data.get("has_office", existing.has_office)
                existing.office_features = extracted_data.get("office_features", existing.office_features)
                existing.road_access_quality = extracted_data.get("road_access_quality", existing.road_access_quality)
                existing.is_fenced = extracted_data.get("is_fenced", existing.is_fenced)
                existing.has_worker_quarters = extracted_data.get("has_worker_quarters", existing.has_worker_quarters)
                
                existing.is_tenanted = extracted_data.get("is_tenanted", existing.is_tenanted)
                existing.lease_start_date = extracted_data.get("lease_start_date", existing.lease_start_date)
                existing.lease_end_date = extracted_data.get("lease_end_date", existing.lease_end_date)
                existing.current_tenant_use = extracted_data.get("current_tenant_use", existing.current_tenant_use)
                
                existing.street_address = extracted_data.get("street_address", existing.street_address)
                existing.area = extracted_data.get("area", existing.area)
                existing.city = extracted_data.get("city", existing.city)
                existing.state = extracted_data.get("state", existing.state)
                existing.nearby_landmarks = extracted_data.get("nearby_landmarks", existing.nearby_landmarks)
                
                existing.suitable_industries = extracted_data.get("suitable_industries", existing.suitable_industries)
                existing.key_highlights = extracted_data.get("key_highlights", existing.key_highlights)
                existing.risk_flags = extracted_data.get("risk_flags", existing.risk_flags)
                existing.listing_status = extracted_data.get("listing_status", existing.listing_status)
                
                if extracted_data.get("embedding_location") is not None:
                    existing.embedding_location = extracted_data["embedding_location"]
                if extracted_data.get("embedding_specs") is not None:
                    existing.embedding_specs = extracted_data["embedding_specs"]
                if extracted_data.get("embedding_features") is not None:
                    existing.embedding_features = extracted_data["embedding_features"]
                if extracted_data.get("embedding_suitability") is not None:
                    existing.embedding_suitability = extracted_data["embedding_suitability"]
                if extracted_data.get("embedding_overview") is not None:
                    existing.embedding_overview = extracted_data["embedding_overview"]
                
                db.commit()
                logger.info(f"Updated property: {existing.title} with full 12-category data and 5-aspect embeddings.")
                return {"status": "success", "action": "updated"}
            else:
                # Create new property
                new_prop = Property(
                    id=str(uuid.uuid4()),
                    source_url=payload.get("source_url", ""),
                    title=title,
                    listing_status=extracted_data.get("listing_status", "For Sale"),
                    property_category=extracted_data.get("property_category", []),
                    property_type_sub=extracted_data.get("property_type_sub"),
                    asking_price_myr=extracted_data.get("asking_price_myr", 0.0),
                    currency="MYR",
                    price_per_acre_myr=extracted_data.get("price_per_acre_myr"),
                    price_per_sqft_myr=extracted_data.get("price_per_sqft_myr"),
                    monthly_rental_income_myr=extracted_data.get("monthly_rental_income_myr"),
                    implied_yield_pct=extracted_data.get("implied_yield_pct"),
                    land_area_acres=extracted_data.get("land_area_acres"),
                    land_area_sqft=extracted_data.get("land_area_sqft"),
                    land_area_sqm=extracted_data.get("land_area_sqm"),
                    built_up_area_sqft=extracted_data.get("built_up_area_sqft"),
                    tenure_type=extracted_data.get("tenure_type"),
                    zoning_type=extracted_data.get("zoning_type"),
                    title_status=extracted_data.get("title_status"),
                    crop_types=extracted_data.get("crop_types", []),
                    tree_count_estimate=extracted_data.get("tree_count_estimate"),
                    tree_age_years=extracted_data.get("tree_age_years"),
                    harvest_readiness=extracted_data.get("harvest_readiness"),
                    topography=extracted_data.get("topography"),
                    water_source_types=extracted_data.get("water_source_types", []),
                    has_natural_stream=extracted_data.get("has_natural_stream", False),
                    has_pond=extracted_data.get("has_pond", False),
                    has_piping_system=extracted_data.get("has_piping_system", False),
                    is_flood_free=extracted_data.get("is_flood_free", True),
                    power_supply_amp=extracted_data.get("power_supply_amp"),
                    utilities_available=extracted_data.get("utilities_available", []),
                    has_office=extracted_data.get("has_office", False),
                    office_features=extracted_data.get("office_features"),
                    road_access_quality=extracted_data.get("road_access_quality"),
                    is_fenced=extracted_data.get("is_fenced", False),
                    has_worker_quarters=extracted_data.get("has_worker_quarters", False),
                    is_tenanted=extracted_data.get("is_tenanted", False),
                    lease_start_date=extracted_data.get("lease_start_date"),
                    lease_end_date=extracted_data.get("lease_end_date"),
                    current_tenant_use=extracted_data.get("current_tenant_use"),
                    street_address=extracted_data.get("street_address"),
                    area=extracted_data.get("area"),
                    city=extracted_data.get("city"),
                    state=extracted_data.get("state", "Pahang"),
                    country="Malaysia",
                    latitude=latitude or extracted_data.get("latitude"),
                    longitude=longitude or extracted_data.get("longitude"),
                    nearby_landmarks=extracted_data.get("nearby_landmarks", []),
                    suitable_industries=extracted_data.get("suitable_industries", []),
                    key_highlights=extracted_data.get("key_highlights", []),
                    risk_flags=extracted_data.get("risk_flags", []),
                    search_corpus_markdown=payload.get("description", f"{title}\n\n"),
                    agency_name="HOME IHC SDN. BHD.",
                    agent_name="Irene Leong",
                    agent_phone="+6011-65144931",
                    agent_whatsapp_url="https://my.mecard.my/1733211127",
                    image_urls=image_urls or extracted_data.get("image_urls", []),
                    embedding_location=extracted_data.get("embedding_location"),
                    embedding_specs=extracted_data.get("embedding_specs"),
                    embedding_features=extracted_data.get("embedding_features"),
                    embedding_suitability=extracted_data.get("embedding_suitability"),
                    embedding_overview=extracted_data.get("embedding_overview"),
                )
                db.add(new_prop)
                db.commit()
                return {"status": "success", "action": "created"}
        finally:
            db.close()
            
    except Exception as exc:
        logger.error(f"Error processing WordPress property: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(bind=True, max_retries=3)
def process_whatsapp_message(self, payload: dict):
    """
    Processes incoming WhatsApp messages.
    Extracts wamid, locks session, handles media, and forwards to LLM.
    """
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                
                contact_name = "Unknown"
                if contacts:
                    contact_name = contacts[0].get("profile", {}).get("name", "Unknown")

                for message in messages:
                    wamid = message.get("id")
                    phone_number = message.get("from")
                    message_type = message.get("type")
                    
                    if not wamid or not phone_number:
                        continue
                        
                    # Acquire distributed lock for this user's session
                    with SessionManager.lock_session(phone_number):
                        session = SessionManager.get_session(phone_number)
                        
                        if session.get("is_paused"):
                            logger.info(f"Session for {phone_number} is paused. Skipping AI processing.")
                            continue
                            
                        text = ""
                        media_url = ""
                        
                        # Handle different message types
                        if message_type == "text":
                            text = message.get("text", {}).get("body", "")
                        elif message_type in ["image", "audio", "document", "video"]:
                            media_id = message.get(message_type, {}).get("id")
                            if media_id:
                                # Fetch media from WhatsApp (Placeholder - need actual WA API call to fetch media binary)
                                # Assuming we have binary data in `media_binary`
                                # media_binary = fetch_whatsapp_media(media_id)
                                # media_url = upload_media(media_binary, f"{wamid}.{message_type}", "application/octet-stream")
                                logger.info(f"Received {message_type} with id {media_id}. MinIO upload pending WhatsApp API fetch.")
                                text = f"[{message_type} attached]"

                        # Log interaction
                        db = SessionLocal()
                        try:
                            # Save interaction log
                            log = InteractionLog(
                                wamid=wamid,
                                phone_number=phone_number,
                                direction="incoming",
                                message_text=text,
                                media_url=media_url
                            )
                            db.add(log)
                            db.commit()
                        except Exception as e:
                            logger.error(f"Failed to log interaction: {e}")
                            db.rollback()
                        finally:
                            db.close()
                            
                        # Update session state with message
                        session["collected_data"]["last_message"] = text
                        
                        SessionManager.save_session(phone_number, session)
                        
                        logger.info(f"Processed WhatsApp message {wamid} from {phone_number}. Text: {text}")
                        
        return {"status": "success"}
    except Exception as exc:
        logger.error(f"Error processing WhatsApp message: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(bind=True, max_retries=2)
def run_lead_nurturing_daemon(self):
    """
    Accelerated lead nurturing daemon.
    Delegates to LeadNurturingManager OOP service layer.
    Periodically scans leads by temperature (Hot: 24h-72h, Warm: 3-7d, Cold: 7-14d).
    Strictly observes the Meta WhatsApp 24-hour customer care messaging window:
    - If customer interacted <= 24 hours ago: can send direct follow-up message via Chatwoot.
    - If customer interacted > 24 hours ago: free-form WhatsApp messages are prohibited;
      posts a private note in Chatwoot for human agent intervention or template dispatch.
    """
    from app.services.lead_nurturing import LeadNurturingManager
    logger.info("Starting lead nurturing daemon run via LeadNurturingManager...")
    try:
        manager = LeadNurturingManager(
            db_session=SessionLocal(),
            message_sender=send_message,
            note_sender=send_private_note
        )
        result = manager.run_cycle()
        logger.info(f"Completed lead nurturing daemon run: {result}")
        return result
    except Exception as exc:
        logger.error(f"Error in lead nurturing daemon: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=2)
def generate_and_send_weekly_reports(self, output_dir: str = None):
    """
    Weekly Celery Beat task to compile and archive Buyer Database.xlsx and Owner Database.xlsx.
    """
    logger.info("Executing weekly database reporting task...")
    try:
        from app.services.reporting import generate_weekly_database_reports, DEFAULT_REPORTS_DIR
        target_dir = output_dir or DEFAULT_REPORTS_DIR
        reports = generate_weekly_database_reports(output_dir=target_dir)
        logger.info(f"Successfully generated weekly reports: {reports}")
        return {
            "status": "success",
            "reports": reports
        }
    except Exception as exc:
        logger.error(f"Failed to generate weekly reports: {exc}")
        raise self.retry(exc=exc, countdown=120)


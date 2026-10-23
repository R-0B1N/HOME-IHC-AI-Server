"""
Conversation Queue Processor Service.
Decomposes the monolithic process_conversation_queue task into discrete,
testable stages:
1. Debounce and Activity Check
2. Master AI Toggle & Human Override Verification
3. Queue Message Popping and Multimodal Ingestion (Audio, Images, PDFs)
4. Customer Entity Resolution and RBAC Context Generation
5. Persona State Machine Execution and Dynamic Lead Temperature Scoring
6. AI Briefing Summary and Bank Valuer Particulars
7. Dynamic Hot Lead Handover Dispatch
8. Outbound Media and Message Transmission (Images, Response, Viewing Forms)
9. State, Priority, and Label Persistence
"""

import base64
import datetime
import json
import logging
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import redis
import requests

from app.db.models import Customer, Order, Property, SessionLocal, User
from app.services.agent_logic import process_persona_state_machine
from app.services.chatwoot import (
    CHATWOOT_ACCOUNT_ID,
    apply_label,
    assign_agent,
    get_agent_id_by_email,
    get_conversation_messages,
    send_chatwoot_image_attachment,
    send_message,
    send_message_with_attachment,
    set_priority,
    toggle_typing_status,
)
from app.services.db_services import (
    get_or_create_customer,
    get_sender_role,
    search_properties,
)
from app.services.document_parser import extract_text_from_document
from app.services.lead_handover import dispatch_hot_lead_handover
from app.services.llm import (
    LLM_MODEL_NAME,
    classify_turn_intent,
    extract_property_search_criteria,
    extract_valuer_data,
    llm_client,
    transcribe_audio,
)
from app.services.session_manager import SessionManager
from app.services.system_prompts import is_handover_promised

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10

REQUIRED_PERSONA_KEYS = {
    "buyer": ["name", "buyer_location", "buyer_property_type", "buyer_budget", "purchase_entity"],
    "seller": ["name", "is_owner", "property_type", "location", "asking_price"],
    "tenant": ["name", "current_location", "property_type", "budget", "use_type"],
    "landlord": ["name", "is_owner", "property_type", "location", "expected_rental"],
    "agent": ["name", "company_name", "coverage_area", "collaboration_type"],
    "bank valuer": ["customer_name", "property_address", "property_type", "contact_phone"],
}

PERSONA_ALIAS_MAP = {
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
    "expected_rental": ["budget", "buyer_budget", "asking_price"],
}


class ConversationQueueProcessor:
    """
    Modular domain service that processes batched messages from Redis queues,
    orchestrating multimodal processing, agent state machines, and downstream dispatches.
    """

    def __init__(
        self,
        celery_task: Optional[Any] = None,
        redis_client: Optional[Any] = None,
        session_factory: Optional[Any] = None,
        timeout_seconds: int = TIMEOUT_SECONDS,
    ):
        self.celery_task = celery_task
        self.timeout_seconds = timeout_seconds
        self.session_factory = session_factory or SessionLocal

        if redis_client is not None:
            self.redis_client = redis_client
        else:
            redis_host = os.getenv("REDIS_HOST", "redis")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=0)

    def check_debounce(
        self, conversation_id: int, task_scheduled_time: float
    ) -> Optional[Dict[str, Any]]:
        """
        Verifies if the user is still active within the debounce window.
        Returns a defer/skip dictionary if active or missing timestamp, or None to continue.
        """
        active_key = f"convo_active_{conversation_id}"
        last_active_raw = self.redis_client.get(active_key)

        if not last_active_raw:
            logger.info(f"Conversation {conversation_id} has no active timestamp. Skipping.")
            return {"status": "skipped", "reason": "no active timestamp"}

        last_active = float(last_active_raw)
        current_time = time.time()
        time_since_active = current_time - last_active

        if time_since_active < self.timeout_seconds:
            wait_time = int(self.timeout_seconds - time_since_active) + 1
            logger.info(
                f"User is still active in conversation {conversation_id}. Rescheduling for {wait_time}s."
            )
            if self.celery_task and hasattr(self.celery_task, "apply_async"):
                self.celery_task.apply_async(
                    args=[conversation_id, task_scheduled_time], countdown=wait_time
                )
            return {"status": "deferred", "reason": "user still active"}

        return None

    def check_master_ai_enabled(self, conversation_id: int) -> bool:
        """
        Checks whether Master AI toggle is active. If disabled, flushes queue and returns False.
        """
        try:
            from app.api.settings import get_system_toggle
            master_ai_enabled = get_system_toggle("master_ai_enabled", default=True)
        except Exception:
            master_ai_raw = self.redis_client.get("master_ai_enabled")
            master_ai_enabled = (
                master_ai_raw.decode("utf-8") == "true" if master_ai_raw else True
            )

        if not master_ai_enabled:
            logger.info(
                f"Master AI Toggle is OFF. Skipping conversation {conversation_id} and clearing queue."
            )
            try:
                toggle_typing_status(conversation_id, "off")
            except Exception:
                pass
            queue_key = f"convo_queue_{conversation_id}"
            try:
                self.redis_client.delete(queue_key)
            except Exception:
                pass
            return False

        return True

    def fetch_queued_messages(self, conversation_id: int) -> Optional[List[Dict[str, Any]]]:
        """
        Atomically pops all messages from Redis for this conversation and removes keys.
        """
        queue_key = f"convo_queue_{conversation_id}"
        active_key = f"convo_active_{conversation_id}"

        pipe = self.redis_client.pipeline()
        pipe.lrange(queue_key, 0, -1)
        pipe.delete(queue_key)
        pipe.delete(active_key)
        results = pipe.execute()

        raw_messages = results[0]
        if not raw_messages:
            logger.info(f"Queue for conversation {conversation_id} is empty. Skipping.")
            return None

        messages = [json.loads(msg) for msg in raw_messages]
        logger.info(f"Aggregating {len(messages)} messages for conversation {conversation_id}")
        return messages

    def parse_multimodal_content(
        self, messages: List[Dict[str, Any]], conversation_id: int
    ) -> Tuple[str, List[str], Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Parses text, audio attachments (transcription), image attachments (base64),
        and document attachments (extraction & mobile preview).
        """
        combined_text = []
        combined_images = []
        contact_info = messages[0].get("sender", {}) if messages else {}
        latest_doc_struct = None

        for msg_payload in messages:
            content = msg_payload.get("content", "")
            if content:
                combined_text.append(content)

            attachments = msg_payload.get("attachments", [])
            for attachment in attachments:
                file_type = attachment.get("file_type")
                data_url = attachment.get("data_url")

                if file_type == "audio":
                    logger.info("Audio attachment detected. Downloading and transcribing...")
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
                        file_name_val = (
                            attachment.get("data_file_name")
                            or attachment.get("file_name")
                            or attachment.get("title")
                            or ""
                        )
                        content_type_val = attachment.get("content_type", "")
                        extension_val = attachment.get("extension", "")
                        doc_result = extract_text_from_document(
                            data_url,
                            file_name=file_name_val,
                            content_type=content_type_val,
                            extension=extension_val,
                        )
                        doc_text = doc_result.get("text", "")
                        if doc_text:
                            combined_text.append(f"[Document Content]: {doc_text}")

                        doc_struct = doc_result.get("structured_data", {})
                        if doc_struct:
                            latest_doc_struct = doc_struct
                            combined_text.append(
                                f"[Document Analysis & Extracted Particulars]:\n"
                                f"{json.dumps(doc_struct, ensure_ascii=False, indent=2)}"
                            )

                        doc_images = doc_result.get("images", [])
                        if doc_images:
                            logger.info(f"Extracted {len(doc_images)} images from document.")
                            combined_images.extend(doc_images)

                        # Mobile PDF Viewer Fix: Dispatch inline Page-1 JPEG preview and mobile link
                        preview_bytes = doc_result.get("preview_image_bytes")
                        if preview_bytes and conversation_id:
                            try:
                                clean_doc_name = file_name_val or "Document.pdf"
                                backend_public_url = os.getenv(
                                    "BACKEND_PUBLIC_URL", "https://api.bentongland.com.my"
                                ).rstrip("/")
                                encoded_url = urllib.parse.quote(data_url, safe="")
                                mobile_viewer_url = (
                                    f"{backend_public_url}/api/v1/documents/proxy/"
                                    f"{urllib.parse.quote(clean_doc_name)}?url={encoded_url}"
                                )
                                preview_caption = (
                                    f"📄 **Client Document Received**: `{clean_doc_name}`\n"
                                    f"📱 *Mobile Preview (Page 1)* rendered below.\n"
                                    f"🔗 [Open Full PDF in Mobile Browser]({mobile_viewer_url})"
                                )
                                send_message_with_attachment(
                                    conversation_id=conversation_id,
                                    content=preview_caption,
                                    file_name=f"preview_{clean_doc_name}.jpg",
                                    file_content=preview_bytes,
                                    content_type="image/jpeg",
                                    is_private=True,
                                )
                                logger.info(
                                    f"Dispatched inline page 1 preview for {clean_doc_name} to conv {conversation_id}"
                                )
                            except Exception as prev_err:
                                logger.warning(
                                    f"Could not dispatch inline document preview: {prev_err}"
                                )
                    except Exception as e:
                        logger.error(f"Failed to extract document text/images: {e}")

        final_prompt_text = "\n".join(combined_text).strip()
        if not final_prompt_text and combined_images:
            final_prompt_text = (
                "[Customer shared land grant / document photo(s). "
                "Please analyze the document and extract property particulars.]"
            )
            logger.info(f"Synthesized prompt for {len(combined_images)} image attachment(s).")

        return final_prompt_text, combined_images, latest_doc_struct, contact_info

    def resolve_customer(
        self,
        conversation_id: int,
        contact_info: Dict[str, Any],
        messages: List[Dict[str, Any]],
        latest_doc_struct: Optional[Dict[str, Any]],
    ) -> Tuple[Optional[Any], bool, str, str, Dict[str, Any]]:
        """
        Resolves or creates Customer record, checks bypass_ai, and records document extract metadata.
        Returns (customer, is_bypassed, phone_number, contact_name, metadata).
        """
        phone_number = contact_info.get("phone_number", "")
        contact_name = contact_info.get("name", "Unknown")
        email = contact_info.get("email")

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
            "environment": "staging" if is_staging_env else "production",
        }

        customer = get_or_create_customer(
            phone_number=phone_number,
            contact_name=contact_name,
            email=email,
            conversation_id=conversation_id,
            metadata=metadata,
        )

        if customer and latest_doc_struct:
            try:
                db_doc = self.session_factory()
                try:
                    c_rec = db_doc.query(Customer).filter(Customer.id == customer.id).first()
                    if c_rec:
                        c_meta = dict(c_rec.metadata_json or {})
                        intake_props = c_meta.setdefault("intake_properties", [])
                        intake_props.append(latest_doc_struct)
                        c_meta["latest_document_extract"] = latest_doc_struct
                        c_rec.metadata_json = c_meta
                        db_doc.commit()
                finally:
                    db_doc.close()
            except Exception as e:
                logger.warning(f"Failed to persist intake property into customer metadata: {e}")

        is_bypassed = bool(
            customer and customer.metadata_json and customer.metadata_json.get("bypass_ai")
        )
        return customer, is_bypassed, phone_number, contact_name, metadata

    def build_rbac_and_context(
        self,
        conversation_id: int,
        customer: Any,
        phone_number: str,
        final_prompt_text: str,
        latest_doc_struct: Optional[Dict[str, Any]],
        combined_images: List[str],
    ) -> Tuple[str, Dict[str, Any], str, str, bool, float]:
        """
        Constructs RBAC data context (Admin, Agent, Customer) and executes semantic turn classification.
        Returns (role, db_context, conversation_history, turn_intent, is_seller_intent, reset_cutoff_ts).
        """
        role = get_sender_role(phone_number)
        db_context: Dict[str, Any] = {"role": role, "data": {}}
        conversation_history = ""
        turn_intent = "general"
        is_seller_intent = False
        reset_cutoff_ts = 0.0

        db = self.session_factory()
        try:
            if role == "admin":
                db_context["data"]["metrics"] = {
                    "total_properties": db.query(Property).count(),
                    "total_customers": db.query(Customer).count(),
                    "total_users": db.query(User).count(),
                    "active_agents": db.query(User).filter(
                        User.role.in_(["agent", "employee"]), User.is_active == True
                    ).count(),
                }
                db_context["data"]["customers"] = [
                    {
                        "id": str(c.id),
                        "name": c.contact_name,
                        "phone": str(c.id),
                        "email": c.email,
                        "last_interaction": (
                            c.last_interaction.isoformat() if c.last_interaction else None
                        ),
                    }
                    for c in db.query(Customer).order_by(Customer.last_interaction.desc()).limit(20).all()
                ]
                db_context["data"]["properties"] = [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "price": p.asking_price_myr,
                        "status": p.listing_status,
                        "city": p.city,
                        "category": p.property_category,
                    }
                    for p in db.query(Property).limit(20).all()
                ]
                db_context["data"]["roster"] = [
                    {
                        "username": u.username,
                        "name": u.full_name,
                        "role": u.role,
                        "phone": u.phone_number,
                        "locations": u.assigned_locations,
                        "types": u.assigned_property_types,
                    }
                    for u in db.query(User).filter(User.is_active == True).all()
                ]
            elif role in ["agent", "employee"]:
                db_context["data"]["customers"] = [
                    {
                        "id": str(c.id),
                        "name": c.contact_name,
                        "phone": str(c.id),
                        "email": c.email,
                        "metadata": c.metadata_json,
                    }
                    for c in db.query(Customer).order_by(Customer.last_interaction.desc()).limit(25).all()
                ]
                db_context["data"]["properties"] = [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "price": p.asking_price_myr,
                        "status": p.listing_status,
                        "city": p.city,
                        "specs": (
                            p.search_corpus_markdown[:200]
                            if p.search_corpus_markdown
                            else None
                        ),
                    }
                    for p in db.query(Property).limit(25).all()
                ]
            else:
                # Customer: own data only
                if customer:
                    db_context["data"]["my_orders"] = [
                        {"id": str(o.id), "status": o.status, "total": o.total_amount}
                        for o in db.query(Order).filter(Order.customer_id == customer.id).all()
                    ]

                # Fetch and filter conversation history
                logger.info(f"Fetching conversation history for {conversation_id}")
                try:
                    chatwoot_messages = get_conversation_messages(conversation_id)
                    chatwoot_messages.sort(key=lambda x: x.get("created_at", 0))

                    try:
                        reset_ts_raw = self.redis_client.get(f"convo_reset_at_{conversation_id}")
                        if reset_ts_raw:
                            reset_cutoff_ts = max(
                                reset_cutoff_ts,
                                float(
                                    reset_ts_raw.decode("utf-8")
                                    if isinstance(reset_ts_raw, bytes)
                                    else reset_ts_raw
                                ),
                            )
                    except Exception as r_err:
                        logger.warning(
                            f"Could not check redis reset cutoff for conv {conversation_id}: {r_err}"
                        )

                    def _parse_msg_ts(m):
                        raw_ts = m.get("created_at")
                        if isinstance(raw_ts, (int, float)):
                            return raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
                        if isinstance(raw_ts, str):
                            try:
                                return datetime.datetime.fromisoformat(
                                    raw_ts.replace("Z", "+00:00")
                                ).timestamp()
                            except Exception:
                                pass
                        return 0.0

                    for msg in chatwoot_messages:
                        if msg.get("private") and "/reset" in (msg.get("content") or ""):
                            msg_created = _parse_msg_ts(msg)
                            if msg_created > reset_cutoff_ts:
                                reset_cutoff_ts = msg_created

                    if reset_cutoff_ts > 0:
                        logger.info(
                            f"Purging pre-reset messages for conv {conversation_id} prior to {reset_cutoff_ts}"
                        )
                        chatwoot_messages = [
                            msg for msg in chatwoot_messages if _parse_msg_ts(msg) > reset_cutoff_ts
                        ]

                    prior_msgs = chatwoot_messages
                    if prior_msgs:
                        last_non_priv = next(
                            (m for m in reversed(prior_msgs) if not m.get("private")), None
                        )
                        if (
                            last_non_priv
                            and (last_non_priv.get("content") or "").strip()
                            == final_prompt_text.strip()
                        ):
                            prior_msgs = [m for m in prior_msgs if m is not last_non_priv]

                    history_lines = []
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

                # Semantic Turn Classification
                turn_intent = classify_turn_intent(
                    prompt=final_prompt_text,
                    conversation_history=conversation_history,
                    has_document=bool(
                        latest_doc_struct
                        or (combined_images and "document" in final_prompt_text.lower())
                    ),
                    document_extract=latest_doc_struct,
                )

                existing_sess_category = None
                try:
                    cached_sess = SessionManager.get_session(phone_number)
                    if cached_sess:
                        existing_sess_category = (
                            cached_sess.get("current_agent")
                            or cached_sess.get("collected_data", {}).get("customer_category")
                            or cached_sess.get("seller_track", {}).get("status")
                        )
                except Exception:
                    pass

                is_seller_intent = (
                    role in ["seller", "landlord"]
                    or turn_intent == "seller_intake"
                    or (
                        existing_sess_category in ["SELLER", "seller", "active"]
                        and turn_intent not in ["buyer_search", "agent_inquiry"]
                    )
                    or (
                        customer
                        and customer.metadata_json
                        and customer.metadata_json.get("customer_category") == "seller"
                    )
                )

                if is_seller_intent:
                    logger.info("Seller/landowner intent detected: suppressing buyer recommendations.")
                    db_context["data"]["properties"] = []
                    db_context["data"]["seller_market_context"] = {
                        "district": "Bentong",
                        "agriculture_rate_benchmark": (
                            "RM 150,000 - RM 280,000 per acre for agricultural land depending "
                            "on road access, terrain, and water source."
                        ),
                        "service_note": (
                            "Home IHC provides direct off-market listing and marketing services "
                            "directly to serious qualified buyers."
                        ),
                    }
                else:
                    logger.info(f"Extracting search criteria from prompt: {final_prompt_text}")
                    criteria = extract_property_search_criteria(final_prompt_text, "")
                    logger.info(f"Extracted criteria: {criteria}")

                    if criteria and any(criteria.values()):
                        matched_properties = search_properties(criteria, limit=15)
                        logger.info(f"Found {len(matched_properties)} matching properties.")
                        db_context["data"]["properties"] = matched_properties
                    else:
                        db_context["data"]["properties"] = [
                            {
                                "id": str(p.id),
                                "name": p.title,
                                "price": p.asking_price_myr,
                                "status": p.listing_status,
                            }
                            for p in db.query(Property).filter(
                                Property.listing_status == "Available"
                            ).limit(10).all()
                        ]
        finally:
            db.close()

        return (
            role,
            db_context,
            conversation_history,
            turn_intent,
            is_seller_intent,
            reset_cutoff_ts,
        )

    def execute_persona_state_machine(
        self,
        phone_number: str,
        contact_name: str,
        role: str,
        final_prompt_text: str,
        conversation_history: str,
        latest_doc_struct: Optional[Dict[str, Any]],
        turn_intent: str,
        combined_images: List[str],
        db_context: Dict[str, Any],
        is_seller_intent: bool,
        reset_cutoff_ts: float,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str, str, bool, str, List[str]]:
        """
        Executes the persona state machine under distributed session lock,
        calculates dynamic lead temperature, and determines handover status.
        Returns:
            (agent_result, session, intent, response_text, handover_initiated, lead_temp, images_to_send)
        """
        with SessionManager.lock_session(phone_number):
            session = SessionManager.get_session(phone_number)
            is_fresh_convo = not conversation_history.strip() or (
                reset_cutoff_ts > 0 and reset_cutoff_ts >= session.get("created_at", 0)
            )
            if is_fresh_convo:
                session.clear()
                session.update(SessionManager._new_session())

            if latest_doc_struct:
                session["latest_document_extract"] = latest_doc_struct
            session["turn_intent"] = turn_intent

            agent_result = process_persona_state_machine(
                phone_number,
                final_prompt_text,
                session,
                conversation_history=conversation_history,
                contact_name=contact_name,
                role=role,
                db_context=db_context,
                images=combined_images,
            )
            session = agent_result.get("updated_session", session)

            intent = session.get("current_agent", "general").lower()
            response_text = agent_result.get(
                "response", "Sorry, I couldn't process your request."
            )
            handover_from_state = agent_result.get("handover", False)
            images_to_send = agent_result.get("images_to_send", [])
            if (
                is_seller_intent
                or turn_intent == "seller_intake"
                or session.get("current_agent") == "SELLER"
                or session.get("seller_track", {}).get("status") == "active"
            ):
                images_to_send = []

            # Dynamic lead temperature based on 80% persona data completeness
            collected = session.get("collected_data", {})
            req_keys = REQUIRED_PERSONA_KEYS.get(intent, ["name", "location", "property_type"])
            filled_count = 0
            for k in req_keys:
                if collected.get(k):
                    filled_count += 1
                elif k in PERSONA_ALIAS_MAP and any(
                    collected.get(alt) for alt in PERSONA_ALIAS_MAP[k]
                ):
                    filled_count += 1

            completeness_ratio = (filled_count / len(req_keys)) if req_keys else 0.0
            if completeness_ratio >= 0.8:
                lead_temp = "Hot"
            elif completeness_ratio >= 0.4:
                lead_temp = "Warm"
            else:
                lead_temp = "Cold"

            # Check explicit human contact phrases & inspection requests
            user_wants_immediate_human = any(
                phrase in final_prompt_text.lower()
                for phrase in [
                    "call me", "speak to human", "talk to agent", "contact me directly",
                    "transfer to human", "speak to a person", "talk to a person", "real agent",
                    "real person", "human agent", "human staff", "person in charge", "pic",
                    "真人", "转人工", "人工客服", "联系真人", "找真人",
                    "电话联系", "安排见面", "nak jumpa", "call saya", "hubungi saya",
                    "agent sebenar", "cakap dengan orang", "temujanji"
                ]
            )
            user_books_inspection = any(
                phrase in final_prompt_text.lower()
                for phrase in [
                    "安排看房", "预约看房", "睇楼", "tengok rumah", "tengok tanah",
                    "arrange viewing", "schedule viewing", "book viewing"
                ]
            )

            handover_initiated = False
            llm_promises_handover = bool(agent_result.get("promises_handover"))
            response_promises_handover = (
                llm_promises_handover or is_handover_promised(response_text)
            )

            if role not in ["admin", "employee", "agent"]:
                if (
                    handover_from_state
                    or user_wants_immediate_human
                    or user_books_inspection
                    or response_promises_handover
                ):
                    handover_initiated = True
                    if (
                        not response_promises_handover
                        and "senior" not in response_text.lower()
                        and "specialist" not in response_text.lower()
                        and "representative" not in response_text.lower()
                        and "专员" not in response_text
                        and "pegawai" not in response_text.lower()
                    ):
                        response_text += (
                            f"\n\nThank you, {contact_name}! 😊 We have noted your request. "
                            f"A senior property specialist from Home IHC will contact you shortly to assist directly."
                        )

            SessionManager.save_session(phone_number, session)

        return (
            agent_result,
            session,
            intent,
            response_text,
            handover_initiated,
            lead_temp,
            images_to_send,
        )

    def generate_summary_and_handle_valuer(
        self,
        customer: Any,
        phone_number: str,
        contact_name: str,
        final_prompt_text: str,
        session: Dict[str, Any],
        intent: str,
        handover_initiated: bool,
        conversation_history: str,
    ) -> Tuple[str, Any]:
        """
        Generates 1-2 sentence AI briefing summary and persists bank valuer particulars if applicable.
        """
        try:
            summary_messages = [
                {
                    "role": "system",
                    "content": (
                        "Summarize this customer interaction in 1-2 sentences for an agent briefing. "
                        "Include the customer's intent, what information was collected, and current status. Be concise."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Customer: {contact_name}, Phone: {phone_number}\n"
                        f"Latest message: {final_prompt_text}\n"
                        f"Collected data: {json.dumps(session.get('collected_data', {}))}\n"
                        f"Current workflow: {intent}\n"
                        f"Handover: {handover_initiated}"
                    ),
                },
            ]
            summary_resp = llm_client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=summary_messages,
                temperature=0.0,
                max_tokens=150,
            )
            conversation_summary_text = summary_resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate AI summary: {e}")
            conversation_summary_text = (
                f"Customer {contact_name} inquired about {intent}. "
                f"Data collected: {json.dumps(session.get('collected_data', {}))}"
            )

        valuer_data = None
        if intent == "bank valuer":
            valuer_data = extract_valuer_data(final_prompt_text, conversation_history)
            if valuer_data and any(valuer_data.values()):
                logger.info(f"Extracted bank valuer data: {valuer_data}")
                if customer:
                    db = self.session_factory()
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

        return conversation_summary_text, valuer_data

    def route_hot_lead(
        self,
        conversation_id: int,
        contact_name: str,
        phone_number: str,
        intent: str,
        session: Dict[str, Any],
        conversation_summary: str,
        valuer_data: Any,
        metadata: Dict[str, Any],
        final_prompt_text: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Coordinates handover payload construction and delegates to LeadHandoverService.
        """
        collected = session.get("collected_data", {})
        loc_val = (
            collected.get("location")
            or collected.get("seller_location")
            or collected.get("buyer_location")
            or collected.get("current_location")
            or collected.get("coverage_area")
        )
        location = str(loc_val) if loc_val else "Pahang (To be advised)"

        ptype_val = (
            collected.get("property_type")
            or collected.get("seller_property_type")
            or collected.get("buyer_property_type")
            or collected.get("use_type")
        )
        property_type = str(ptype_val) if ptype_val else "Commercial / Residential / Land"

        budget_val = (
            collected.get("budget")
            or collected.get("buyer_budget")
            or collected.get("asking_price")
            or collected.get("expected_rental")
        )
        budget = str(budget_val) if budget_val else "To be discussed in meeting"

        if intent == "bank valuer" and valuer_data:
            location = str(valuer_data)
            property_type = "Bank Valuation"
            budget = "N/A"

        summary_clean = conversation_summary.replace("\n", " ").replace("\t", " ")
        if len(summary_clean) > 500:
            summary_clean = summary_clean[:497] + "..."

        is_staging_env = (
            os.getenv("DB_HOST") == "whatsapp_ai_db_staging"
            or "staging" in os.getenv("REDIS_HOST", "")
            or os.getenv("APP_ENV") == "staging"
            or os.getenv("ENVIRONMENT", "").lower() == "staging"
        )
        staging_inbox_id = int(os.getenv("STAGING_INBOX_ID", "4"))
        inbox_id = metadata.get("inbox_id") or (staging_inbox_id if is_staging_env else 1)
        cw_link = (
            f"https://inbox.bentongland.com.my/app/accounts/{CHATWOOT_ACCOUNT_ID}/inbox/"
            f"{inbox_id}/conversations/{conversation_id}"
        )

        try:
            handover_result = dispatch_hot_lead_handover(
                conversation_id=conversation_id,
                customer_name=contact_name,
                customer_phone=phone_number,
                intent=intent,
                location=location,
                property_type=property_type,
                budget=budget,
                conversation_summary=summary_clean,
                cw_link=cw_link,
                inbox_id=inbox_id,
                raw_inquiry_text=final_prompt_text,
            )
            logger.info(f"Dynamic handover completed: {handover_result}")
            return handover_result
        except Exception as e:
            logger.error(f"Failed in dispatch_hot_lead_handover: {e}")
            return None

    def dispatch_media_and_response(
        self,
        conversation_id: int,
        images_to_send: List[str],
        response_text: str,
        agent_result: Dict[str, Any],
        customer: Any,
        phone_number: str,
        contact_name: str,
    ) -> None:
        """
        Dispatches property images, Chatwoot message response, and autonomous viewing form if booked.
        """
        # 1. Transcoded images
        if images_to_send:
            for idx, img_url in enumerate(images_to_send):
                try:
                    logger.info(
                        f"Dispatching image {idx+1}/{len(images_to_send)}: {img_url} to conv {conversation_id}"
                    )
                    send_chatwoot_image_attachment(
                        conversation_id=conversation_id, image_url=img_url
                    )
                    time.sleep(0.4)
                except Exception as img_err:
                    logger.error(f"Failed to dispatch image {img_url}: {img_err}")

        # 2. Main response text
        logger.info(f"Sending response to conversation {conversation_id}")
        send_message(conversation_id, response_text)

        # 3. Viewing Form Dispatch
        if agent_result.get("schedule_viewing") and customer:
            try:
                from app.services.viewing_service import create_and_dispatch_viewing_form

                viewing_prop = agent_result.get("viewing_property") or {}
                prop_id = viewing_prop.get("id")
                v_date = agent_result.get("viewing_date")

                logger.info(
                    f"Triggering autonomous viewing form for customer {phone_number} on {v_date}"
                )
                create_and_dispatch_viewing_form(
                    customer_id=phone_number,
                    property_id=prop_id,
                    viewing_date=v_date,
                    conversation_id=conversation_id,
                    customer_name=contact_name or customer.contact_name,
                    phone_number=phone_number,
                    dispatch_to_customer=True,
                )
            except Exception as vf_err:
                logger.error(f"Error in autonomous viewing form generation/dispatch: {vf_err}")

        # Turn typing off
        try:
            toggle_typing_status(conversation_id, "off")
        except Exception as e:
            logger.warning(f"Failed to turn typing status off: {e}")

    def persist_state_and_labels(
        self,
        conversation_id: int,
        customer: Any,
        lead_temp: str,
        handover_initiated: bool,
        role: str,
        intent: str,
        assignee_email: Optional[str],
    ) -> None:
        """
        Persists customer lead temperature, bypass_ai toggle, and applies conversation priority/labels.
        """
        if customer:
            db = self.session_factory()
            try:
                db_cust = db.query(Customer).filter(Customer.id == customer.id).first()
                if db_cust:
                    meta = db_cust.metadata_json.copy() if db_cust.metadata_json else {}
                    meta["lead_temp"] = lead_temp
                    if handover_initiated:
                        meta["bypass_ai"] = True
                    db_cust.metadata_json = meta
                    db_cust.last_interaction = datetime.datetime.now(datetime.timezone.utc)
                    db.commit()
            except Exception as e:
                logger.error(f"Failed to update customer metadata/lead_temp: {e}")
                db.rollback()
            finally:
                db.close()

        labels_to_apply = []
        if role in ["admin", "employee", "agent"]:
            labels_to_apply.append(role)
        else:
            if intent in ["buyer", "seller", "tenant", "agent", "bank valuer"]:
                labels_to_apply.append(intent.lower())

            if handover_initiated:
                labels_to_apply.append("handover_initiated")
                if assignee_email:
                    try:
                        agent_id = get_agent_id_by_email(assignee_email)
                        if agent_id:
                            assign_agent(conversation_id, agent_id)
                    except Exception as e:
                        logger.error(f"Failed to assign agent on handover: {e}")

            priority_map = {"hot": "high", "warm": "medium", "cold": "low"}
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

    def process(self, conversation_id: int, task_scheduled_time: float) -> Dict[str, Any]:
        """
        Orchestrates full processing pipeline for batched messages in a conversation.
        """
        # 1. Debounce check
        debounce_result = self.check_debounce(conversation_id, task_scheduled_time)
        if debounce_result:
            return debounce_result

        # 2. Master AI Toggle check
        if not self.check_master_ai_enabled(conversation_id):
            return {"status": "skipped", "reason": "master_ai_disabled"}

        # 3. Message batching
        messages = self.fetch_queued_messages(conversation_id)
        if not messages:
            return {"status": "skipped", "reason": "empty queue"}

        # 4. Multimodal ingestion
        (
            final_prompt_text,
            combined_images,
            latest_doc_struct,
            contact_info,
        ) = self.parse_multimodal_content(messages, conversation_id)

        if not final_prompt_text:
            logger.info("No text, audio, or images to process. Skipping.")
            return {"status": "skipped", "reason": "empty aggregated input"}

        # Turn typing on
        try:
            toggle_typing_status(conversation_id, "on")
        except Exception as e:
            logger.warning(f"Failed to turn typing status on: {e}")

        # 5. Customer entity resolution & bypass check
        (
            customer,
            is_bypassed,
            phone_number,
            contact_name,
            metadata,
        ) = self.resolve_customer(conversation_id, contact_info, messages, latest_doc_struct)

        if is_bypassed:
            logger.info(f"Customer {customer.id} has bypass_ai set. Skipping AI response.")
            try:
                toggle_typing_status(conversation_id, "off")
            except Exception:
                pass
            return {"status": "skipped", "reason": "bypass_ai is true"}

        # 6. RBAC Context Building & Semantic Turn Intent
        (
            role,
            db_context,
            conversation_history,
            turn_intent,
            is_seller_intent,
            reset_cutoff_ts,
        ) = self.build_rbac_and_context(
            conversation_id,
            customer,
            phone_number,
            final_prompt_text,
            latest_doc_struct,
            combined_images,
        )

        # 7. Execute Persona State Machine
        (
            agent_result,
            session,
            intent,
            response_text,
            handover_initiated,
            lead_temp,
            images_to_send,
        ) = self.execute_persona_state_machine(
            phone_number=phone_number,
            contact_name=contact_name,
            role=role,
            final_prompt_text=final_prompt_text,
            conversation_history=conversation_history,
            latest_doc_struct=latest_doc_struct,
            turn_intent=turn_intent,
            combined_images=combined_images,
            db_context=db_context,
            is_seller_intent=is_seller_intent,
            reset_cutoff_ts=reset_cutoff_ts,
        )

        # 8. AI Briefing Summary & Bank Valuer extraction
        (
            conversation_summary_text,
            valuer_data,
        ) = self.generate_summary_and_handle_valuer(
            customer=customer,
            phone_number=phone_number,
            contact_name=contact_name,
            final_prompt_text=final_prompt_text,
            session=session,
            intent=intent,
            handover_initiated=handover_initiated,
            conversation_history=conversation_history,
        )

        # 9. Dynamic Hot Lead Handover
        if role not in ["admin", "employee", "agent"] and handover_initiated:
            self.route_hot_lead(
                conversation_id=conversation_id,
                contact_name=contact_name,
                phone_number=phone_number,
                intent=intent,
                session=session,
                conversation_summary=conversation_summary_text,
                valuer_data=valuer_data,
                metadata=metadata,
                final_prompt_text=final_prompt_text,
            )

        # 10. Dispatch media, response text, and viewing forms
        self.dispatch_media_and_response(
            conversation_id=conversation_id,
            images_to_send=images_to_send,
            response_text=response_text,
            agent_result=agent_result,
            customer=customer,
            phone_number=phone_number,
            contact_name=contact_name,
        )

        # 11. State and priority persistence
        assignee_email = agent_result.get("assignee_email")
        self.persist_state_and_labels(
            conversation_id=conversation_id,
            customer=customer,
            lead_temp=lead_temp,
            handover_initiated=handover_initiated,
            role=role,
            intent=intent,
            assignee_email=assignee_email,
        )

        return {
            "status": "success",
            "conversation_id": conversation_id,
            "messages_processed": len(messages),
        }

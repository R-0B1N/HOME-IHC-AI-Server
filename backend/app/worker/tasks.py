import logging
import json
import time
import os
import redis
import requests
import base64
from app.worker.celery_app import celery_app
from app.services.chatwoot import send_message, apply_label, set_priority, toggle_typing_status, get_conversation_messages, get_or_create_contact, create_conversation, assign_agent
from app.services.llm import generate_response, transcribe_audio, extract_property_search_criteria, extract_valuer_data, extract_wordpress_property
from app.services.document_parser import extract_text_from_document
from app.services.db_services import get_or_create_customer, get_sender_role, search_properties
from app.services.session_manager import SessionManager
from app.services.minio_service import upload_media
from app.db.models import SessionLocal, Customer, Property, Transaction, Order, InteractionLog


logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

TIMEOUT_SECONDS = 15

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
            logger.info(f"Master AI Toggle is OFF. Deferring conversation {conversation_id}.")
            return {"status": "deferred", "reason": "master ai is off"}

        # If we reach here, it's been at least 10 seconds since the last message and AI is ON.
        
        # Human Override Check
        try:
            chatwoot_messages = get_conversation_messages(conversation_id)
            if chatwoot_messages:
                chatwoot_messages.sort(key=lambda x: x.get("created_at", 0))
                last_msg = chatwoot_messages[-1]
                # If the last message is outgoing and NOT from our AI/bot (e.g., from a human agent)
                # Chatwoot marks bot messages with sender_type = "AgentBot" or user_id for humans
                sender = last_msg.get("sender", {})
                sender_type = sender.get("type", "")
                if last_msg.get("message_type") == "outgoing" and sender_type != "agent_bot" and sender.get("id") != 0:
                    logger.info(f"Human agent replied to conversation {conversation_id}. Clearing queue and skipping.")
                    queue_key = f"convo_queue_{conversation_id}"
                    pipe = redis_client.pipeline()
                    pipe.delete(queue_key)
                    pipe.delete(active_key)
                    pipe.execute()
                    return {"status": "skipped", "reason": "human override"}
        except Exception as e:
            logger.error(f"Failed to check for human override: {e}")

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
        metadata = {
            "session_id": session_id,
            "inbox_id": first_msg.get("inbox", {}).get("id"),
            "contact_id": contact_info.get("id"),
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
                # Admin: all data (limited for token size)
                db_context["data"]["customers"] = [{"id": str(c.id), "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": str(p.id), "name": p.name, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            elif role == "employee":
                # Employee: customer data only
                db_context["data"]["customers"] = [{"id": str(c.id), "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": str(p.id), "name": p.name, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            else:
                # Customer: own data only
                if customer:
                    db_context["data"]["my_orders"] = [{"id": str(o.id), "status": o.status, "total": o.total_amount} for o in db.query(Order).filter(Order.customer_id == customer.id).all()]
                
                
                # Fetch conversation history
                logger.info(f"Fetching conversation history for {conversation_id}")
                try:
                    chatwoot_messages = get_conversation_messages(conversation_id)
                    chatwoot_messages.sort(key=lambda x: x.get("created_at", 0))
                    history_lines = []
                    # Get last 10 messages, older first (chronological order)
                    for msg in chatwoot_messages[-10:]:
                        sender = "Assistant" if msg.get("message_type") == "outgoing" else "User"
                        history_lines.append(f"{sender}: {msg.get('content', '')}")
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
            
            agent_result = process_persona_state_machine(
                phone_number, final_prompt_text, session,
                conversation_history=conversation_history,
                contact_name=contact_name
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
                "property_type": ["buyer_property_type", "seller_property_type"],
                "budget": ["buyer_budget", "asking_price", "expected_rental"]
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
            
            # Detect explicit meeting / call / direct agent requests
            user_wants_meeting = any(phrase in final_prompt_text.lower() for phrase in [
                "arrange a meeting", "schedule a meeting", "meeting with your team",
                "meet up", "call me", "speak to human", "talk to agent", "contact me directly",
                "advise your availability", "discuss in meeting", "have a meeting"
            ])
            
            # Handover should ONLY trigger when:
            # 1. State machine finished workflow (handover_from_state == True)
            # 2. Or user explicitly asks for a meeting / call
            # 3. Or bank valuer submission complete
            handover_initiated = False
            if role not in ["admin", "employee"]:
                if handover_from_state:
                    handover_initiated = True
                elif user_wants_meeting:
                    handover_initiated = True
                    # Append polite wrap-up if not already present
                    if "senior agent" not in response_text.lower() and "specialist" not in response_text.lower():
                        response_text += f"\n\nThank you, {contact_name}! 😊 We have noted your request to meet with our team. A senior property specialist from Home IHC will contact you shortly to arrange the meeting."
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

        if role not in ["admin", "employee"] and handover_initiated:
            # Assign Agent 1 (ID 4) to the conversation
            try:
                assign_agent(conversation_id, agent_id=4)
            except Exception as e:
                logger.error(f"Failed to assign agent 1 to conversation {conversation_id}: {e}")
            
            # Send summary and contact card to main lines
            try:
                main_phones = ["+601165144931", "+14709202239"]
                for main_phone in main_phones:
                    contact_id = get_or_create_contact(main_phone, f"Main Line {main_phone}")
                    if contact_id:
                        inbox_id = metadata.get("inbox_id") or 4
                        new_conv_id = create_conversation(contact_id, inbox_id)
                        if new_conv_id:
                            from app.services.chatwoot import CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID
                            clean_phone = phone_number.replace("+", "")
                            cw_link = f"https://inbox.bentongland.com.my/app/accounts/{CHATWOOT_ACCOUNT_ID}/inbox/{inbox_id}/conversations/{conversation_id}"
                            
                            # Extract enriched lead details for alert template
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
                            
                            # Send the template summary
                            from app.services.chatwoot import send_whatsapp_contact, send_whatsapp_template
                            
                            template_params = [
                                contact_name,
                                phone_number,
                                intent.upper(),
                                str(location),
                                str(property_type),
                                str(budget),
                                conversation_summary,
                                cw_link
                            ]
                            
                            TEMPLATE_PHONE_NUMBER_ID = os.getenv(
                                "WHATSAPP_TEMPLATE_PHONE_NUMBER_ID",
                                "1039310802596891"
                            )
                            
                            send_whatsapp_template(
                                inbox_id=inbox_id,
                                to_phone=main_phone,
                                template_name="new_lead_alert_utility",
                                parameters=template_params,
                                language_code="en",
                                override_phone_number_id=TEMPLATE_PHONE_NUMBER_ID
                            )
                            
                            # Send native WhatsApp contact card directly to main lines
                            send_whatsapp_contact(
                                inbox_id=inbox_id,
                                to_phone=main_phone,
                                contact_name=contact_name,
                                contact_phone=phone_number,
                                override_phone_number_id=TEMPLATE_PHONE_NUMBER_ID
                            )
            except Exception as e:
                logger.error(f"Failed to forward lead to main lines: {e}")
        
        # 3. Dispatch native images if requested
        if images_to_send:
            from app.services.chatwoot import send_whatsapp_image, send_chatwoot_image_attachment
            inbox_id = metadata.get("inbox_id") or 4
            for img_url in images_to_send:
                try:
                    logger.info(f"Dispatching native image: {img_url} to {phone_number}")
                    send_whatsapp_image(
                        inbox_id=inbox_id,
                        to_phone=phone_number,
                        image_url=img_url
                    )
                    send_chatwoot_image_attachment(
                        conversation_id=conversation_id,
                        image_url=img_url
                    )
                except Exception as img_err:
                    logger.error(f"Failed to dispatch native image {img_url}: {img_err}")

        # 4. Send response back to Chatwoot FIRST (ensures wrap-up message is delivered)
        logger.info(f"Sending response to conversation {conversation_id}")
        send_message(conversation_id, response_text)
        
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
        if role in ["admin", "employee"]:
            labels_to_apply.append("employee")
        else:
            if intent in ["buyer", "seller", "tenant", "agent", "bank valuer"]:
                labels_to_apply.append(intent.lower())
                
            if handover_initiated:
                labels_to_apply.append("handover_initiated")
                
                # Assign agent if specified
                if assignee_email:
                    try:
                        from app.services.chatwoot import get_agent_id_by_email, assign_agent
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
            from app.db.models import Property
            import uuid
            
            existing = db.query(Property).filter(Property.title == title).first()
            if existing:
                # Update existing property
                existing.search_corpus_markdown = payload.get("description", existing.search_corpus_markdown)
                existing.source_url = payload.get("source_url", existing.source_url)
                if latitude is not None: existing.latitude = latitude
                if longitude is not None: existing.longitude = longitude
                if image_urls: existing.image_urls = image_urls
                
                # Fields from extraction
                existing.asking_price_myr = extracted_data.get("asking_price_myr", existing.asking_price_myr)
                existing.monthly_rental_income_myr = extracted_data.get("monthly_rental_income_myr", existing.monthly_rental_income_myr)
                existing.implied_yield_pct = extracted_data.get("implied_yield_pct", existing.implied_yield_pct)
                existing.property_category = extracted_data.get("category", existing.property_category)
                existing.land_area_sqft = extracted_data.get("land_area_sqft", existing.land_area_sqft)
                existing.land_area_acres = extracted_data.get("land_area_acres", existing.land_area_acres)
                existing.land_area_sqm = extracted_data.get("land_area_sqm", existing.land_area_sqm)
                existing.built_up_area_sqft = extracted_data.get("built_up_area_sqft", existing.built_up_area_sqft)
                existing.tenure_type = extracted_data.get("tenure_type", existing.tenure_type)
                existing.zoning_type = extracted_data.get("zoning_type", existing.zoning_type)
                existing.power_supply_amp = extracted_data.get("power_supply_amp", existing.power_supply_amp)
                existing.utilities_available = extracted_data.get("utilities_available", existing.utilities_available)
                existing.has_office = extracted_data.get("has_office", existing.has_office)
                existing.office_features = extracted_data.get("office_features", existing.office_features)
                existing.road_access_quality = extracted_data.get("road_access_quality", existing.road_access_quality)
                existing.is_tenanted = extracted_data.get("is_tenanted", existing.is_tenanted)
                existing.lease_start_date = extracted_data.get("lease_start_date", existing.lease_start_date)
                existing.lease_end_date = extracted_data.get("lease_end_date", existing.lease_end_date)
                existing.current_tenant_use = extracted_data.get("current_tenant_use", existing.current_tenant_use)
                existing.street_address = extracted_data.get("street_address", existing.street_address)
                existing.area = extracted_data.get("area", existing.area)
                existing.city = extracted_data.get("city", existing.city)
                existing.state = extracted_data.get("state", existing.state)
                existing.suitable_industries = extracted_data.get("suitable_industries", existing.suitable_industries)
                existing.key_highlights = extracted_data.get("key_highlights", existing.key_highlights)
                existing.risk_flags = extracted_data.get("risk_flags", existing.risk_flags)
                existing.listing_status = extracted_data.get("status", existing.listing_status)
                
                db.commit()
                logger.info(f"Updated property {title} in DB.")
                return {"status": "success", "action": "updated"}
            else:
                # Create new property
                new_property = Property(
                    id=str(uuid.uuid4()),
                    title=title,
                    search_corpus_markdown=payload.get("description", ""),
                    source_url=payload.get("source_url", ""),
                    latitude=latitude,
                    longitude=longitude,
                    image_urls=image_urls,
                    
                    asking_price_myr=extracted_data.get("asking_price_myr", 0.0),
                    monthly_rental_income_myr=extracted_data.get("monthly_rental_income_myr"),
                    implied_yield_pct=extracted_data.get("implied_yield_pct"),
                    property_category=extracted_data.get("category", []),
                    land_area_sqft=extracted_data.get("land_area_sqft"),
                    land_area_acres=extracted_data.get("land_area_acres", 0.0),
                    land_area_sqm=extracted_data.get("land_area_sqm"),
                    built_up_area_sqft=extracted_data.get("built_up_area_sqft"),
                    tenure_type=extracted_data.get("tenure_type"),
                    zoning_type=extracted_data.get("zoning_type"),
                    power_supply_amp=extracted_data.get("power_supply_amp"),
                    utilities_available=extracted_data.get("utilities_available", []),
                    has_office=extracted_data.get("has_office", False),
                    office_features=extracted_data.get("office_features"),
                    road_access_quality=extracted_data.get("road_access_quality"),
                    is_tenanted=extracted_data.get("is_tenanted", False),
                    lease_start_date=extracted_data.get("lease_start_date"),
                    lease_end_date=extracted_data.get("lease_end_date"),
                    current_tenant_use=extracted_data.get("current_tenant_use"),
                    street_address=extracted_data.get("street_address"),
                    area=extracted_data.get("area"),
                    city=extracted_data.get("city", ""),
                    state=extracted_data.get("state", ""),
                    suitable_industries=extracted_data.get("suitable_industries", []),
                    key_highlights=extracted_data.get("key_highlights", []),
                    risk_flags=extracted_data.get("risk_flags", []),
                    listing_status=extracted_data.get("status", "Available")
                )
                db.add(new_property)
                db.commit()
                logger.info(f"Created property {title} in DB.")
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

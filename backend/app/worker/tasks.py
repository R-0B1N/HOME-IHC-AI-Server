import logging
import json
import time
import os
import redis
import requests
import base64
from app.worker.celery_app import celery_app
from app.services.chatwoot import send_message, apply_label, set_priority, toggle_typing_status, get_conversation_messages, get_or_create_contact, create_conversation, assign_agent
from app.services.llm import generate_response, transcribe_audio, extract_property_search_criteria, extract_valuer_data
from app.services.document_parser import extract_text_from_document
from app.services.db_services import get_or_create_customer, get_sender_role, search_properties
from app.db.models import SessionLocal, Customer, Property, Transaction, Order


logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

TIMEOUT_SECONDS = 10

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
        if time_since_active < 10:
            wait_time = int(10 - time_since_active) + 1
            logger.info(f"User is still active in conversation {conversation_id}. Rescheduling for {wait_time}s.")
            process_conversation_queue.apply_async(
                args=[conversation_id, task_scheduled_time],
                countdown=wait_time
            )
            return {"status": "deferred", "reason": "user still active"}
            
        # If we reach here, it's been at least 5 seconds since the last message.
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
                            doc_text = extract_text_from_document(data_url, attachment.get("data_file_name", ""))
                            if doc_text:
                                combined_text.append(f"[Document Content]: {doc_text}")
                        except Exception as e:
                            logger.error(f"Failed to extract document text: {e}")
                            
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
        
        if customer and customer.metadata_json and customer.metadata_json.get("ignore_ai"):
            logger.info(f"Customer {customer.id} has ignore_ai set. Skipping AI response.")
            try:
                toggle_typing_status(conversation_id, "off")
            except:
                pass
            return {"status": "skipped", "reason": "ignore_ai is true"}
        
        role = get_sender_role(phone_number)
        
        criteria = {}
        
        # Build DB context based on RBAC
        db_context = {"role": role, "data": {}}
        db = SessionLocal()
        try:
            if role == "admin":
                # Admin: all data (limited for token size)
                db_context["data"]["customers"] = [{"id": c.id, "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": p.id, "name": p.name, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            elif role == "employee":
                # Employee: customer data only
                db_context["data"]["customers"] = [{"id": c.id, "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": p.id, "name": p.name, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            else:
                # Customer: own data only
                if customer:
                    db_context["data"]["my_orders"] = [{"id": o.id, "status": o.status, "total": o.total_amount} for o in db.query(Order).filter(Order.customer_id == customer.id).all()]
                
                
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
                    db_context["data"]["properties"] = [{"id": p.id, "name": p.name, "price": p.price, "status": p.status} for p in db.query(Property).filter(Property.status == "Available").limit(10).all()]
        finally:
            db.close()
        
        llm_response = generate_response(final_prompt_text, contact_info, db_context, images=combined_images, conversation_history=conversation_history)
        
        intent = llm_response.get("intent", "general").lower()
        lead_temp = llm_response.get("lead_temperature", "Warm")
        response_text = llm_response.get("response", "Sorry, I couldn't process your request.")
        
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

        handover_initiated = False
        if role not in ["admin", "employee"]:
            if lead_temp.lower() == "hot" or intent == "bank valuer":
                handover_initiated = True
                if intent == "bank valuer":
                    response_text += "\n\nThank you. Our team will review the valuation and reach out to you shortly."
                else:
                    response_text += "\n\nOur senior agent will reach out to you shortly."
                
                # Assign Agent 1 (ID 4) to the conversation
                try:
                    assign_agent(conversation_id, agent_id=4)
                except Exception as e:
                    logger.error(f"Failed to assign agent 1 to conversation {conversation_id}: {e}")
                
                # Send summary to main lines
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
                                wa_link = f"https://wa.me/{clean_phone}"
                                
                                if intent == "bank valuer" and 'valuer_data' in locals() and valuer_data:
                                    location = str(valuer_data)
                                    property_type = "N/A"
                                    budget = "N/A"
                                elif criteria:
                                    location = criteria.get('location', 'None')
                                    property_type = criteria.get('property_type', 'None')
                                    budget = criteria.get('max_price', 'None')
                                else:
                                    location = "None"
                                    property_type = "None"
                                    budget = "None"
                                    
                                conversation_summary = llm_response.get("summary", "No summary available.")
                                if isinstance(conversation_summary, str):
                                    conversation_summary = conversation_summary.replace('\n', ' ').replace('\t', ' ')
                                
                                # First send the template summary
                                from app.services.chatwoot import send_whatsapp_contact, send_whatsapp_template
                                
                                template_params = [
                                    contact_name,
                                    phone_number,
                                    intent.upper(),
                                    f"Location: {location} Property Type: {property_type} Budget: {budget}",
                                    str(conversation_summary),
                                    str(cw_link)
                                ]
                                
                                send_whatsapp_template(
                                    inbox_id=3,
                                    to_phone=main_phone,
                                    template_name="new_lead_alert_utility",
                                    parameters=template_params,
                                    language_code="en"
                                )
                                
                                # Then send the native contact card directly via WhatsApp API
                                send_whatsapp_contact(
                                    inbox_id=inbox_id,
                                    to_phone=main_phone,
                                    contact_name=contact_name,
                                    contact_phone=phone_number
                                )
                except Exception as e:
                    logger.error(f"Failed to forward lead to main lines: {e}")
        
        # Update customer with new intent and temp
        if customer:
            db = SessionLocal()
            try:
                db_cust = db.query(Customer).filter(Customer.id == customer.id).first()
                if db_cust:
                    db_cust.intent_category = intent
                    db_cust.intention_tag = lead_temp
                    if handover_initiated:
                        meta = db_cust.metadata_json.copy() if db_cust.metadata_json else {}
                        meta["ignore_ai"] = True
                        db_cust.metadata_json = meta
                    db.commit()
            except Exception as e:
                logger.error(f"Failed to update customer intent: {e}")
                db.rollback()
            finally:
                db.close()

        
        # 3. Send response back to Chatwoot
        logger.info(f"Sending response to conversation {conversation_id}")
        send_message(conversation_id, response_text)
        
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

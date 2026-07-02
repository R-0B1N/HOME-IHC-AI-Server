import logging
import json
import time
import os
import redis
import requests
import base64
from app.worker.celery_app import celery_app
from app.services.chatwoot import send_message, apply_label, toggle_typing_status
from app.services.llm import generate_response, transcribe_audio, extract_property_search_criteria
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
        
        # If the last_active time is newer than the time this specific task was scheduled,
        # it means a newer message arrived and scheduled its own task.
        # We abort this one silently.
        if last_active > task_scheduled_time:
            logger.info(f"User is still typing in conversation {conversation_id}. Deferring to later task.")
            return {"status": "deferred", "reason": "newer message arrived"}
            
        # If we reach here, it's been at least 10 seconds since the last message.
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
                        transcription_text = transcribe_audio(data_url)
                        if transcription_text:
                            combined_text.append(f"[Audio Transcript]: {transcription_text}")
                            
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
                        # Handle PDF text extraction
                        
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
        
        customer = get_or_create_customer(phone_number, contact_name, email)
        role = get_sender_role(phone_number)
        
        # Build DB context based on RBAC
        db_context = {"role": role, "data": {}}
        db = SessionLocal()
        try:
            if role == "admin":
                # Admin: all data (limited for token size)
                db_context["data"]["customers"] = [{"id": c.id, "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": p.id, "title": p.title, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            elif role == "employee":
                # Employee: customer data only
                db_context["data"]["customers"] = [{"id": c.id, "name": c.contact_name, "phone": c.phone_number} for c in db.query(Customer).limit(50).all()]
                db_context["data"]["properties"] = [{"id": p.id, "title": p.title, "price": p.price, "status": p.status} for p in db.query(Property).limit(50).all()]
            else:
                # Customer: own data only
                if customer:
                    db_context["data"]["my_orders"] = [{"id": o.id, "status": o.status, "total": o.total_amount} for o in db.query(Order).filter(Order.customer_id == customer.id).all()]
                
                # Perform RAG search for properties
                logger.info(f"Extracting search criteria from prompt: {final_prompt_text}")
                criteria = extract_property_search_criteria(final_prompt_text)
                logger.info(f"Extracted criteria: {criteria}")
                
                if criteria and any(criteria.values()):
                    matched_properties = search_properties(criteria, limit=5)
                    logger.info(f"Found {len(matched_properties)} matching properties.")
                    db_context["data"]["properties"] = matched_properties
                else:
                    # Fallback to general available properties if no criteria
                    db_context["data"]["properties"] = [{"id": p.id, "title": p.title, "price": p.price, "status": p.status} for p in db.query(Property).filter(Property.status == "Available").limit(5).all()]
        finally:
            db.close()
        
        llm_response = generate_response(final_prompt_text, contact_info, db_context, images=combined_images)
        
        intent = llm_response.get("intent", "general").lower()
        lead_temp = llm_response.get("lead_temperature", "Warm")
        response_text = llm_response.get("response", "Sorry, I couldn't process your request.")
        
        # Update customer with new intent and temp
        if customer:
            db = SessionLocal()
            try:
                db_cust = db.query(Customer).filter(Customer.id == customer.id).first()
                if db_cust:
                    db_cust.intent_category = intent
                    db_cust.intention_tag = lead_temp
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
        
        # 4. Apply intent label
        if intent in ["buyer", "seller", "tenant", "agent"]:
            label_name = intent.lower()
            logger.info(f"Applying label '{label_name}' to conversation {conversation_id}")
            apply_label(conversation_id, label_name)
        
        return {"status": "success", "conversation_id": conversation_id, "messages_processed": len(messages)}
        
    except Exception as exc:
        # Attempt to turn typing off in case of an error
        try:
            toggle_typing_status(conversation_id, "off")
        except:
            pass
        logger.error(f"Error processing conversation {conversation_id}: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

import os
import json
import time
import logging
import hmac
import hashlib
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Response
import redis
from app.worker.tasks import process_conversation_queue, process_whatsapp_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

# Setup Redis connection for debouncing
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
TIMEOUT_SECONDS = 10

@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """
    Handles WhatsApp Webhook Verification (Hub Challenge).
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            logger.info("WhatsApp WEBHOOK_VERIFIED")
            return Response(content=challenge, media_type="text/plain", status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Verification failed")
    raise HTTPException(status_code=400, detail="Missing parameters")

@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Handles WhatsApp Webhook Event Notifications.
    Validates HMAC SHA256 signature using raw body and offloads to Celery.
    """
    if WHATSAPP_APP_SECRET:
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            raise HTTPException(status_code=403, detail="Missing signature")
            
        raw_body = getattr(request.state, "raw_body", b"")
        expected_sig = "sha256=" + hmac.new(
            WHATSAPP_APP_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(expected_sig, signature):
            logger.error("Invalid WhatsApp webhook signature.")
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    
    # Extract entries
    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            
            for message in messages:
                wamid = message.get("id")
                
                if wamid:
                    # Idempotency check
                    lock_key = f"whatsapp_lock_msg_{wamid}"
                    is_new = redis_client.setnx(lock_key, "1")
                    if not is_new:
                        logger.info(f"Skipping duplicate WhatsApp message: {wamid}")
                        continue
                    redis_client.expire(lock_key, 300)
                
                # Offload to Celery
                process_whatsapp_message.apply_async(args=[payload])
                
    return Response(content="OK", status_code=200)

@router.post("/chatwoot")
@router.post("/chatwoot-ai")
async def chatwoot_webhook(request: Request):
    """
    Receives webhooks from Chatwoot.
    Implements signature validation and sliding window message batching.
    """
    raw_body = await request.body()
    
    if CHATWOOT_WEBHOOK_SECRET:
        signature = request.headers.get("X-Chatwoot-Signature")
        if not signature:
            logger.warning("Missing X-Chatwoot-Signature header")
            return {"status": "ignored", "reason": "Missing signature"}
            
        import base64
        timestamp = request.headers.get("X-Chatwoot-Timestamp")
        
        # Chatwoot v4.x signs "#{timestamp}.#{body}"
        if timestamp:
            signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        else:
            signed_payload = raw_body

        expected_hex = hmac.new(
            CHATWOOT_WEBHOOK_SECRET.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).hexdigest()
        
        expected_b64 = base64.b64encode(hmac.new(
            CHATWOOT_WEBHOOK_SECRET.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).digest()).decode()
        
        # Backward compatibility fallback for legacy direct raw body signing
        legacy_expected_hex = hmac.new(
            CHATWOOT_WEBHOOK_SECRET.encode('utf-8'),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        
        # Chatwoot sends signature as "sha256=..."
        received_hash = signature
        if signature.startswith("sha256="):
            received_hash = signature[7:]
            
        valid = (
            hmac.compare_digest(expected_hex, received_hash) or 
            hmac.compare_digest(expected_b64, received_hash) or
            hmac.compare_digest(legacy_expected_hex, received_hash)
        )
        
        if not valid:
            logger.error(
                f"Invalid Chatwoot webhook signature. Received: {signature}, "
                f"Expected Hex (with ts={timestamp}): {expected_hex}, "
                f"Expected Hex (raw body): {legacy_expected_hex}"
            )
            return {"status": "ignored", "reason": "Invalid signature"}

    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.error("Invalid or empty JSON payload in webhook")
        return {"status": "ignored", "reason": "invalid or empty json payload"}
    
    event_name = payload.get("event")
    
    # Handle typing events for faster dispatch
    if event_name == "conversation_typing_on":
        conversation_id = payload.get("conversation", {}).get("id")
        if conversation_id:
            active_key = f"convo_active_{conversation_id}"
            redis_client.set(active_key, time.time())
            redis_client.expire(active_key, 3600)
        return {"status": "typing_on_recorded"}

    if event_name == "conversation_typing_off":
        return {"status": "typing_off_recorded"}
        
    # Handle conversation metadata events
    if event_name in ["conversation_created", "conversation_status_changed", "conversation_updated", "message_updated", "webwidget_triggered", "contact_created"]:
        logger.info(f"Received metadata event: {event_name}. No immediate action required by AI.")
        return {"status": "ignored", "reason": f"metadata event {event_name} not handled"}

    if event_name == "contact_updated":
        # Sync bypass_ai flag from Chatwoot custom attributes
        custom_attributes = payload.get("custom_attributes", {})
        # If bypass_ai is not in custom_attributes, it means it's unchecked or unset
        bypass_ai_val = custom_attributes.get("bypass_ai", False)
        phone_number = payload.get("phone_number")
        
        if phone_number:
            # Clean phone number just in case
            if phone_number.startswith('+'):
                phone_number = phone_number[1:]
                
            from app.db.models import SessionLocal, Customer
            db = SessionLocal()
            try:
                customer = db.query(Customer).filter((Customer.id == phone_number) | (Customer.id.like(f"%{phone_number}%"))).first()
                if customer:
                    # Create a new dict to ensure SQLAlchemy detects the change
                    meta = dict(customer.metadata_json or {})
                    meta["bypass_ai"] = bool(bypass_ai_val)
                    customer.metadata_json = meta
                    db.commit()
                    logger.info(f"Synced bypass_ai={meta['bypass_ai']} for {phone_number} from Chatwoot")
            except Exception as e:
                logger.error(f"Failed to sync bypass_ai: {e}")
            finally:
                db.close()
        
        return {"status": "contact_updated_processed"}

    # We only care about message creation events below this point
    if event_name != "message_created":
        logger.info(f"Ignoring webhook, not a message_created event (was {event_name})")
        return {"status": "ignored", "reason": "not a message_created event"}
        
    # Intercept Private Note Agent Commands (e.g., /acknowledgement or /transcript)
    is_private = payload.get("private") is True
    content = (payload.get("content") or "").strip()
    conversation = payload.get("conversation", {})
    conversation_id = conversation.get("id")

    if is_private and conversation_id and (content.startswith("/acknowledgement") or content.startswith("/transcript") or content.startswith("/reset")):
        logger.info(f"Agent command detected in private note for conv {conversation_id}: {content}")
        try:
            if content.startswith("/acknowledgement"):
                from app.services.acknowledgement import generate_viewing_acknowledgement, get_sample_acknowledgement_data
                from app.services.chatwoot import send_private_note, send_message_with_attachment
                from app.db.models import SessionLocal, Customer
                
                args = content.split()
                should_send_customer = "send" in args
                
                contact_info = conversation.get("meta", {}).get("sender", {}) or payload.get("sender", {})
                phone = contact_info.get("phone_number") or ""
                cust_name = contact_info.get("name") or "Customer"
                
                ack_data = get_sample_acknowledgement_data()
                if cust_name:
                    ack_data["customer_name"] = cust_name
                    ack_data["customer_signer"] = cust_name
                if phone:
                    ack_data["phone"] = phone
                
                if phone:
                    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
                    try:
                        db = SessionLocal()
                        try:
                            cust = db.query(Customer).filter((Customer.id == clean_phone) | (Customer.id.like(f"%{clean_phone}%"))).first()
                            if cust and cust.metadata_json:
                                meta = cust.metadata_json
                                if meta.get("location"): ack_data["target_location"] = meta["location"]
                                if meta.get("budget"): ack_data["remarks"] = f"Budget: {meta['budget']}"
                                if meta.get("property_type"): ack_data["property_types"] = [meta["property_type"]]
                        finally:
                            db.close()
                    except Exception as dbe:
                        logger.warning(f"Could not load customer from DB for acknowledgement: {dbe}")
                
                res = generate_viewing_acknowledgement(ack_data)
                docx_path = res["docx_path"]
                pdf_path = res.get("pdf_path")
                form_no = res["form_no"]
                
                if should_send_customer:
                    dispatch_path = pdf_path if pdf_path and os.path.exists(pdf_path) else docx_path
                    mime = "application/pdf" if dispatch_path.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    filename = os.path.basename(dispatch_path)
                    with open(dispatch_path, "rb") as f:
                        file_bytes = f.read()
                    
                    send_message_with_attachment(
                        conversation_id=conversation_id,
                        content=f"Dear {cust_name}, here is your Customer Property Viewing Acknowledgement (Form No: {form_no}). Please review prior to our appointment. 😊",
                        file_name=filename,
                        file_content=file_bytes,
                        content_type=mime
                    )
                    send_private_note(
                        conversation_id,
                        f"✅ **Acknowledgement Form {form_no} Dispatched to Customer via WhatsApp.**\nFile: `{filename}`"
                    )
                else:
                    note_msg = (
                        f"📄 **Customer Property Viewing Acknowledgement Generated**\n\n"
                        f"• **Form No**: {form_no}\n"
                        f"• **Customer**: {cust_name} ({phone})\n"
                        f"• **DOCX**: `{docx_path}`\n"
                        f"• **PDF**: `{pdf_path or 'Server-side headless converter'}`\n\n"
                        f"💡 *To dispatch directly to customer on WhatsApp, reply with: `/acknowledgement send`*"
                    )
                    send_private_note(conversation_id, note_msg)
                return {"status": "command_executed", "command": "/acknowledgement"}

            elif content.startswith("/transcript"):
                from app.services.transcript import generate_conversation_transcript_pdf
                from app.services.chatwoot import send_private_note, send_message_with_attachment
                
                args = content.split()
                should_send_customer = "send" in args
                pdf_bytes, filename = generate_conversation_transcript_pdf(conversation_id)
                
                if should_send_customer:
                    send_message_with_attachment(
                        conversation_id=conversation_id,
                        content="Here is a verified PDF transcript of our WhatsApp conversation for your records. 😊",
                        file_name=filename,
                        file_content=pdf_bytes,
                        content_type="application/pdf"
                    )
                    send_private_note(
                        conversation_id,
                        f"📄 **Conversation Transcript {filename} dispatched to customer via WhatsApp.**"
                    )
                else:
                    send_private_note(
                        conversation_id,
                        f"📄 **Conversation Transcript Generated**\n\n"
                        f"• File: `{filename}` ({len(pdf_bytes):,} bytes)\n\n"
                        f"💡 *To dispatch directly to customer on WhatsApp, reply with: `/transcript send`*"
                    )
                return {"status": "command_executed", "command": "/transcript"}

            elif content.startswith("/reset"):
                from app.services.session_manager import SessionManager
                from app.services.chatwoot import send_private_note
                from app.db.models import SessionLocal, Customer
                
                contact_info = conversation.get("meta", {}).get("sender", {}) or payload.get("sender", {})
                phone = contact_info.get("phone_number") or ""
                
                # 1. Reset Redis Session
                try:
                    if phone:
                        SessionManager.reset_session(phone)
                        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
                        SessionManager.reset_session(clean_phone)
                    redis_client.delete(f"convo_active_{conversation_id}")
                    redis_client.delete(f"convo_queue_{conversation_id}")
                except Exception as rerr:
                    logger.warning(f"Could not clear Redis session (Redis may be offline): {rerr}")
                
                # 2. Reset Customer bypass_ai and collected state in DB
                try:
                    db = SessionLocal()
                    try:
                        if phone:
                            clean_p = phone.replace("+", "").replace(" ", "").replace("-", "")
                            cust = db.query(Customer).filter((Customer.id == clean_p) | (Customer.id.like(f"%{clean_p}%"))).first()
                            if cust:
                                meta = dict(cust.metadata_json or {})
                                meta["bypass_ai"] = False
                                meta["lead_temp"] = "Warm"
                                meta["collected_data"] = {}
                                cust.metadata_json = meta
                                db.commit()
                    finally:
                        db.close()
                except Exception as dbe:
                    logger.warning(f"Error resetting customer in DB: {dbe}")
                
                send_private_note(
                    conversation_id,
                    "🔄 **Session & AI State Reset Complete**\n\n"
                    "• Redis session state cleared.\n"
                    "• `bypass_ai` flag reset to `False` (AI re-enabled).\n"
                    "• Next customer message will be treated as a fresh conversation."
                )
                return {"status": "command_executed", "command": "/reset"}

        except Exception as cmd_err:
            logger.error(f"Failed to execute agent command '{content}': {cmd_err}")
            from app.services.chatwoot import send_private_note
            try:
                send_private_note(conversation_id, f"⚠️ Failed to execute command `{content}`: {cmd_err}")
            except Exception:
                pass
            return {"status": "command_error", "error": str(cmd_err)}

    message_type = payload.get("message_type")
    # message_type == "incoming" means incoming message from customer
    if message_type != "incoming" and message_type != 0:
        logger.info(f"Ignoring webhook, not an incoming customer message (was {message_type})")
        return {"status": "ignored", "reason": "not an incoming customer message"}
        
    # Master AI Toggle — if disabled, do NOT queue messages or trigger typing
    try:
        master_ai_raw = redis_client.get("master_ai_enabled")
        master_ai_on = master_ai_raw.decode("utf-8") == "true" if master_ai_raw else True
        if not master_ai_on:
            logger.info(f"Master AI is OFF. Ignoring incoming message (event: {event_name}).")
            return {"status": "skipped", "reason": "master_ai_disabled"}
    except Exception as e:
        logger.error(f"Error checking master AI status: {e}. Failing closed to protect production.")
        return {"status": "skipped", "reason": "master_ai_error_fail_closed"}

    inbox_id = payload.get("inbox", {}).get("id") or payload.get("conversation", {}).get("inbox_id")
    
    # Environment Isolation: Prevent Staging AI from cross-firing on live Production inboxes
    runtime_env = os.getenv("ENVIRONMENT", "production").lower()
    staging_inbox_id = str(os.getenv("STAGING_INBOX_ID", "4"))
    if runtime_env == "staging":
        # Staging must strictly ignore messages from production inboxes (including Inbox 3, which is Voon's live number)
        if str(inbox_id) != staging_inbox_id:
            logger.info(f"Staging environment ignoring production inbox message (inbox_id: {inbox_id}).")
            return {"status": "skipped", "reason": "staging_ignores_production_inbox"}
    
    conversation = payload.get("conversation", {})
    conversation_id = conversation.get("id")
    message_id = payload.get("id")
    
    if not message_id or not conversation_id:
        logger.info("Ignoring webhook, no message or conversation id found")
        return {"status": "ignored", "reason": "no message or conversation id"}
        
    # Strictly debounce duplicate message_ids to prevent processing the exact same webhook twice
    message_lock_key = f"chatwoot_lock_msg_{message_id}"
    is_new = redis_client.setnx(message_lock_key, "1")
    if not is_new:
        return {"status": "skipped", "reason": "exact message already processed (debounced)"}
    redis_client.expire(message_lock_key, 300)
    
    # 1. Append message payload to conversation queue
    queue_key = f"convo_queue_{conversation_id}"
    redis_client.rpush(queue_key, json.dumps(payload))
    # Ensure queue doesn't stay in redis forever if something fails
    redis_client.expire(queue_key, 3600)
    
    # 2. Update the last active timestamp
    active_key = f"convo_active_{conversation_id}"
    current_time = time.time()
    redis_client.set(active_key, current_time)
    redis_client.expire(active_key, 3600)
    
    # 3. Immediately trigger typing indicator so customer sees AI is active
    try:
        from app.services.chatwoot import toggle_typing_status
        toggle_typing_status(conversation_id, "on")
    except Exception as te:
        logger.warning(f"Could not immediately trigger typing indicator for conv {conversation_id}: {te}")
    
    # 4. Schedule the Celery task to check the queue in 10 seconds
    process_conversation_queue.apply_async(
        args=[conversation_id, current_time], 
        countdown=TIMEOUT_SECONDS
    )
    
    return {"status": "queued", "conversation_id": conversation_id, "message_id": message_id}

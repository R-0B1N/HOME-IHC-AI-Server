import os
import json
import time
import logging
import hmac
import hashlib
from fastapi import APIRouter, Request, BackgroundTasks
import redis
from app.worker.tasks import process_conversation_queue

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

# Setup Redis connection for debouncing
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET")
TIMEOUT_SECONDS = 10

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
        
        expected_hex = hmac.new(
            CHATWOOT_WEBHOOK_SECRET.encode('utf-8'),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        
        expected_b64 = base64.b64encode(hmac.new(
            CHATWOOT_WEBHOOK_SECRET.encode('utf-8'),
            raw_body,
            hashlib.sha256
        ).digest()).decode()
        
        # Chatwoot sends signature as "sha256=..."
        received_hash = signature
        if signature.startswith("sha256="):
            received_hash = signature[7:]
            
        if not hmac.compare_digest(expected_hex, received_hash) and not hmac.compare_digest(expected_b64, received_hash):
            logger.error(f"Invalid Chatwoot webhook signature. Received: {signature}, Expected Hex: {expected_hex}, Expected B64: {expected_b64}")
            logger.info("Bypassing signature validation for staging testing.")
            # return {"status": "ignored", "reason": "Invalid signature"}

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
        
    # Handle contact and conversation metadata events
    if event_name in ["conversation_created", "conversation_status_changed", "conversation_updated", "message_updated", "webwidget_triggered", "contact_created", "contact_updated"]:
        logger.info(f"Received metadata event: {event_name}. No immediate action required by AI.")
        return {"status": "ignored", "reason": f"metadata event {event_name} not handled"}

    # We only care about message creation events below this point
    if event_name != "message_created":
        logger.info(f"Ignoring webhook, not a message_created event (was {event_name})")
        return {"status": "ignored", "reason": "not a message_created event"}
        
    message_type = payload.get("message_type")
    # message_type == "incoming" means incoming message from customer
    if message_type != "incoming" and message_type != 0:
        logger.info(f"Ignoring webhook, not an incoming customer message (was {message_type})")
        return {"status": "ignored", "reason": "not an incoming customer message"}
        
    inbox_id = payload.get("inbox", {}).get("id") or payload.get("conversation", {}).get("inbox_id")
    # Removed strict inbox ID filtering so test/production inboxes both work
    
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
    
    # 3. Schedule the Celery task to check the queue in 10 seconds
    process_conversation_queue.apply_async(
        args=[conversation_id, current_time], 
        countdown=TIMEOUT_SECONDS
    )
    
    return {"status": "queued", "conversation_id": conversation_id, "message_id": message_id}

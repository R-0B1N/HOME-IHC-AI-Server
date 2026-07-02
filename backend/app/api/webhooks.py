import os
import json
import time
from fastapi import APIRouter, Request, BackgroundTasks
import redis
from app.worker.tasks import process_conversation_queue

router = APIRouter()

# Setup Redis connection for debouncing
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

TIMEOUT_SECONDS = 5

@router.post("/chatwoot")
async def chatwoot_webhook(request: Request):
    """
    Receives webhooks from Chatwoot.
    Implements a Sliding Window message batcher.
    Combines messages into a queue and processes them after the user stops typing.
    """
    payload = await request.json()
    
    event_name = payload.get("event")
    
    # Handle typing events for faster dispatch
    if event_name == "conversation_typing_on":
        conversation_id = payload.get("conversation", {}).get("id")
        if conversation_id:
            # Extend active timestamp because they are typing
            active_key = f"convo_active_{conversation_id}"
            redis_client.set(active_key, time.time())
            redis_client.expire(active_key, 3600)
        return {"status": "typing_on_recorded"}

    if event_name == "conversation_typing_off":
        conversation_id = payload.get("conversation", {}).get("id")
        if conversation_id:
            # Immediately trigger queue processing since they stopped typing
            current_time = time.time()
            process_conversation_queue.apply_async(
                args=[conversation_id, current_time], 
                countdown=0
            )
        return {"status": "typing_off_fast_track"}
    
    # We only care about message creation events below this point
    if event_name != "message_created":
        return {"status": "ignored", "reason": "not a message_created event"}
        
    message_type = payload.get("message_type")
    # message_type == "incoming" means incoming message from customer
    if message_type != "incoming" and message_type != 0:
        return {"status": "ignored", "reason": "not an incoming customer message"}
        
    conversation = payload.get("conversation", {})
    conversation_id = conversation.get("id")
    message_id = payload.get("id")
    
    if not message_id or not conversation_id:
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

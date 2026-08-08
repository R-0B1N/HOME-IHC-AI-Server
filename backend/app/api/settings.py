from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import redis
import os

router = APIRouter()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

class AIToggleState(BaseModel):
    enabled: bool

@router.get("/ai-status", response_model=AIToggleState)
def get_ai_status():
    status = redis_client.get("master_ai_enabled")
    if status is None:
        return {"enabled": True}  # Default is ON
    return {"enabled": status.decode("utf-8") == "true"}

@router.post("/ai-status", response_model=AIToggleState)
def set_ai_status(state: AIToggleState):
    status_str = "true" if state.enabled else "false"
    redis_client.set("master_ai_enabled", status_str)
    
    if state.enabled:
        # Re-trigger all pending conversations
        from app.worker.tasks import process_conversation_queue
        import time
        keys = redis_client.keys("convo_queue_*")
        for key in keys:
            conversation_id = key.decode("utf-8").split("_")[-1]
            process_conversation_queue.apply_async(
                args=[int(conversation_id), time.time()]
            )
            
    return {"enabled": state.enabled}

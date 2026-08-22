import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import redis

logger = logging.getLogger(__name__)

router = APIRouter()



REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
from app.core.auth import require_admin

REDIS_STAGING_HOST = os.getenv("REDIS_STAGING_HOST", "whatsapp_ai_redis_staging")
REDIS_STAGING_PORT = int(os.getenv("REDIS_STAGING_PORT", "6379"))

try:
    staging_redis_client = redis.Redis(host=REDIS_STAGING_HOST, port=REDIS_STAGING_PORT, db=0)
except Exception:
    staging_redis_client = None

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


@router.get("/staging/ai-status", response_model=AIToggleState)
def get_staging_ai_status(admin=Depends(require_admin)):
    """Admin-only endpoint to get AI response toggle state for Staging environment."""
    try:
        client = staging_redis_client or redis_client
        status = client.get("master_ai_enabled")
        if status is None:
            return {"enabled": True}
        return {"enabled": status.decode("utf-8") == "true"}
    except Exception as e:
        logger.error(f"Error reading staging Redis: {e}")
        return {"enabled": True}


@router.post("/staging/ai-status", response_model=AIToggleState)
def set_staging_ai_status(state: AIToggleState, admin=Depends(require_admin)):
    """Admin-only endpoint to set AI response toggle state for Staging environment."""
    try:
        client = staging_redis_client or redis_client
        status_str = "true" if state.enabled else "false"
        client.set("master_ai_enabled", status_str)
        return {"enabled": state.enabled}
    except Exception as e:
        logger.error(f"Error updating staging Redis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update staging AI toggle: {e}")


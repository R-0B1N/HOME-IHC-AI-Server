"""Per-conversation block after Meta says the message cannot be delivered."""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

BLOCK_PREFIX = "outbound_blocked:"


def block_key(conversation_id: Any) -> str:
    return f"{BLOCK_PREFIX}{conversation_id}"


def _client():
    import redis

    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )


def mark_outbound_blocked(conversation_id: Any) -> None:
    if conversation_id in (None, ""):
        return
    try:
        _client().set(block_key(conversation_id), "1")
    except Exception as exc:
        logger.warning("Could not store outbound block for %s: %s", conversation_id, exc)


def is_outbound_blocked(conversation_id: Any) -> bool:
    if conversation_id in (None, ""):
        return False
    try:
        return bool(_client().get(block_key(conversation_id)))
    except Exception:
        return False


def customer_outbound_blocked(customer: Optional[Any]) -> bool:
    meta = getattr(customer, "metadata_json", None) or {}
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("outbound_blocked") or meta.get("nurture_stopped"))

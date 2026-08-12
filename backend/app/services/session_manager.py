import os
import json
import time
import redis
from contextlib import contextmanager

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

# Sessions expire after 24 hours of inactivity (reset on each save)
SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# If a session is older than this, treat it as stale and reset
SESSION_STALE_THRESHOLD_SECONDS = 24 * 60 * 60  # 24 hours


class SessionManager:
    """
    Manages transient session state for Whatsapp users.
    Implements Redlock-style distributed locking to prevent race conditions during rapid messages.
    Sessions auto-expire after 24 hours of inactivity.
    Stale sessions (>24h old) are automatically reset on next access.
    """

    @staticmethod
    def get_session_key(phone_number: str) -> str:
        return f"session:{phone_number}"

    @staticmethod
    def get_lock_key(phone_number: str) -> str:
        return f"lock:session:{phone_number}"

    @staticmethod
    @contextmanager
    def lock_session(phone_number: str, timeout: int = 10):
        lock_key = SessionManager.get_lock_key(phone_number)
        lock = redis_client.lock(lock_key, timeout=timeout)
        try:
            lock.acquire(blocking=True)
            yield
        finally:
            if lock.locked():
                try:
                    lock.release()
                except redis.exceptions.LockError:
                    pass  # Already released or expired

    @staticmethod
    def _new_session() -> dict:
        """Create a fresh session with timestamp."""
        return {
            "current_agent": None,
            "state": "INIT",
            "collected_data": {},
            "retry_count": 0,
            "is_paused": False,
            "created_at": time.time(),
            "last_active_at": time.time(),
        }

    @staticmethod
    def get_session(phone_number: str) -> dict:
        key = SessionManager.get_session_key(phone_number)
        data = redis_client.get(key)
        if data:
            session = json.loads(data)
            # Check if session is stale (older than threshold)
            created_at = session.get("created_at", 0)
            if created_at and (time.time() - created_at) > SESSION_STALE_THRESHOLD_SECONDS:
                # Session is stale — reset it
                return SessionManager._new_session()
            return session
        return SessionManager._new_session()

    @staticmethod
    def save_session(phone_number: str, session_data: dict):
        key = SessionManager.get_session_key(phone_number)
        session_data["last_active_at"] = time.time()
        if "created_at" not in session_data:
            session_data["created_at"] = time.time()
        redis_client.setex(key, SESSION_TTL_SECONDS, json.dumps(session_data))

    @staticmethod
    def reset_session(phone_number: str):
        """Explicitly reset a session to fresh state."""
        key = SessionManager.get_session_key(phone_number)
        redis_client.delete(key)

    @staticmethod
    def pause_session(phone_number: str):
        with SessionManager.lock_session(phone_number):
            session = SessionManager.get_session(phone_number)
            session["is_paused"] = True
            SessionManager.save_session(phone_number, session)

    @staticmethod
    def unpause_session(phone_number: str):
        with SessionManager.lock_session(phone_number):
            session = SessionManager.get_session(phone_number)
            session["is_paused"] = False
            SessionManager.save_session(phone_number, session)

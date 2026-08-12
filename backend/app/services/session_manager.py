import os
import json
import redis
from contextlib import contextmanager

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

class SessionManager:
    """
    Manages transient session state for Whatsapp users.
    Implements Redlock-style distributed locking to prevent race conditions during rapid messages.
    TTL is set to 7 days to accommodate async conversations.
    """
    TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

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
                    pass # Already released or expired

    @staticmethod
    def get_session(phone_number: str) -> dict:
        key = SessionManager.get_session_key(phone_number)
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return {
            "current_agent": None,
            "state": "INIT",
            "collected_data": {},
            "retry_count": 0,
            "is_paused": False
        }

    @staticmethod
    def save_session(phone_number: str, session_data: dict):
        key = SessionManager.get_session_key(phone_number)
        redis_client.setex(key, SessionManager.TTL_SECONDS, json.dumps(session_data))

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

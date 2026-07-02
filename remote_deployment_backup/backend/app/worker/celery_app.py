import os
from celery import Celery
from app.db.models import Base, engine

# Initialize database
Base.metadata.create_all(bind=engine)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

celery_app = Celery(
    "real_estate_ai",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=["app.worker.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Rate limits or visibility timeouts can be configured here if necessary
)

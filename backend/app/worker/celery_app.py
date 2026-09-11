import os
from celery import Celery
from app.db.models import Base, engine

# Initialize database
try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

celery_app = Celery(
    "real_estate_ai",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=["app.worker.tasks"]
)

from celery.schedules import crontab

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "run-lead-nurturing-daemon-hourly": {
            "task": "app.worker.tasks.run_lead_nurturing_daemon",
            "schedule": crontab(minute=0),  # Runs every hour
        },
        "generate-weekly-reports-monday": {
            "task": "app.worker.tasks.generate_and_send_weekly_reports",
            "schedule": crontab(day_of_week="monday", hour=1, minute=0),  # Monday 01:00 UTC / 09:00 MYT
        },
    }
)


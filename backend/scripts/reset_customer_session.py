#!/usr/bin/env python3
"""
CLI Utility to reset conversation history, Redis sessions, and bypass_ai flags.

Usage:
    python scripts/reset_customer_session.py --phone +60123456789
    python scripts/reset_customer_session.py --all
"""

import sys
import os
import argparse
import logging
import redis

# Ensure backend root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.db.models import SessionLocal, Customer
from app.services.session_manager import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reset_customer_session")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)


def reset_customer(phone: str):
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "").strip()
    logger.info(f"Resetting session and AI state for phone: {phone} (clean: {clean_phone})")

    # 1. Clear Redis Session keys
    for p in [phone, clean_phone, f"+{clean_phone}"]:
        key = SessionManager.get_session_key(p)
        if redis_client.exists(key):
            redis_client.delete(key)
            logger.info(f"Deleted Redis key: {key}")

    # 2. Reset Customer record in PostgreSQL
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter((Customer.id == clean_phone) | (Customer.id.like(f"%{clean_phone}%"))).first()
        if cust:
            meta = dict(cust.metadata_json or {})
            conv_id = meta.get("conversation_id")
            meta["bypass_ai"] = False
            meta["lead_temp"] = "Warm"
            meta["collected_data"] = {}
            cust.metadata_json = meta
            db.commit()
            logger.info(f"Reset customer in DB: {cust.contact_name} ({cust.id}), bypass_ai=False")

            if conv_id:
                redis_client.delete(f"convo_active_{conv_id}")
                redis_client.delete(f"convo_queue_{conv_id}")
                logger.info(f"Cleared Redis convo queue for conversation {conv_id}")
        else:
            logger.warning(f"No customer record found in DB for {clean_phone}")
    finally:
        db.close()


def reset_all():
    logger.info("Resetting all customer sessions and clearing bypass_ai across the database...")
    db = SessionLocal()
    count = 0
    try:
        customers = db.query(Customer).all()
        for cust in customers:
            meta = dict(cust.metadata_json or {})
            meta["bypass_ai"] = False
            meta["lead_temp"] = "Warm"
            meta["collected_data"] = {}
            cust.metadata_json = meta
            count += 1
        db.commit()
        logger.info(f"Reset DB metadata for {count} customers.")
    finally:
        db.close()

    # Flush session:* keys from Redis
    keys = redis_client.keys("session:*")
    if keys:
        redis_client.delete(*keys)
        logger.info(f"Flushed {len(keys)} active Redis sessions.")

    # Flush queue keys
    q_keys = redis_client.keys("convo_*")
    if q_keys:
        redis_client.delete(*q_keys)
        logger.info(f"Flushed {len(q_keys)} convo queue keys.")


def main():
    parser = argparse.ArgumentParser(description="Reset conversation sessions and AI bypass flags.")
    parser.add_argument("--phone", type=str, help="Phone number to reset (e.g. +60123456789)")
    parser.add_argument("--all", action="store_true", help="Reset all customer sessions and AI flags")

    args = parser.parse_args()

    if args.all:
        reset_all()
        print("✅ Successfully reset all customer sessions and AI flags.")
    elif args.phone:
        reset_customer(args.phone)
        print(f"✅ Successfully reset session for {args.phone}.")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

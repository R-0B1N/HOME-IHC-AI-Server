"""
Lead Nurturing Management Service for Home IHC AI CRM.
Implements object-oriented cadence evaluation, Meta WhatsApp 24-hour messaging
policy window enforcement, and automated multi-channel re-engagement.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app.db.models import SessionLocal, Customer
from app.services.chatwoot import send_message, send_private_note

logger = logging.getLogger(__name__)


class LeadNurturingManager:
    """
    Object-Oriented Lead Nurturing Daemon.
    Evaluates lead qualification status and temperature cadences:
    - Hot Leads (18h to 72h): High priority follow-up.
    - Warm Leads (3d to 7d): Mid-cycle check-in.
    - Cold / Cooling Leads (7d to 14d): Long-cycle re-engagement.
    
    Meta Policy Guard:
    Strictly differentiates between <= 24h (conversational follow-up permitted)
    and > 24h (automated free-form messages blocked to protect against Meta bans).
    """

    def __init__(self, db_session=None, message_sender=None, note_sender=None):
        self.db_session = db_session
        self.message_sender = message_sender or send_message
        self.note_sender = note_sender or send_private_note

    def evaluate_customer(self, customer: Customer, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether a customer is due for nurturing.
        Returns cadence evaluation dict or None if ineligible.
        """
        now = now or datetime.now(timezone.utc)
        meta = customer.metadata_json or {}

        # Respect human handover / bypass AI
        if meta.get("bypass_ai"):
            return None

        # Check last nurtured timestamp (prevent duplicate pings within 24 hours)
        last_nurtured_str = meta.get("last_nurtured_at")
        if last_nurtured_str:
            try:
                last_nurtured = datetime.fromisoformat(last_nurtured_str)
                if last_nurtured.tzinfo is None:
                    last_nurtured = last_nurtured.replace(tzinfo=timezone.utc)
                if (now - last_nurtured).total_seconds() < 86400:
                    return None
            except Exception:
                pass

        last_active = getattr(customer, "updated_at", None) or getattr(customer, "last_interaction", None) or getattr(customer, "created_at", None)
        if not last_active:
            return None
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)

        elapsed_seconds = (now - last_active).total_seconds()
        elapsed_hours = elapsed_seconds / 3600.0
        elapsed_days = elapsed_hours / 24.0

        conversation_id = meta.get("conversation_id")
        if not conversation_id:
            return None

        lead_temp = (meta.get("lead_temp") or meta.get("temperature") or "warm").lower()

        should_nurture = False
        cadence_label = ""

        if lead_temp == "hot" and 18.0 <= elapsed_hours <= 72.0:
            should_nurture = True
            cadence_label = "18-72h Hot Lead"
        elif lead_temp == "warm" and 3.0 <= elapsed_days <= 7.0:
            should_nurture = True
            cadence_label = "3-7d Warm Lead"
        elif lead_temp in ["cold", "cooling"] and 7.0 <= elapsed_days <= 14.0:
            should_nurture = True
            cadence_label = "7-14d Cooling Lead"

        if not should_nurture:
            return None

        return {
            "customer_id": str(customer.id),
            "contact_name": customer.contact_name or "there",
            "phone_number": customer.phone_number or "Unknown",
            "conversation_id": conversation_id,
            "lead_temp": lead_temp,
            "cadence_label": cadence_label,
            "elapsed_hours": elapsed_hours,
            "elapsed_days": elapsed_days,
            "is_within_24h": (elapsed_hours <= 24.0)
        }

    def dispatch_nurture(self, customer: Customer, eval_result: Dict[str, Any], now: Optional[datetime] = None) -> str:
        """
        Executes the appropriate action based on Meta 24h customer care policy window.
        """
        now = now or datetime.now(timezone.utc)
        conversation_id = eval_result["conversation_id"]
        cust_name = eval_result["contact_name"]
        phone = eval_result["phone_number"]
        lead_temp = eval_result["lead_temp"]
        cadence_label = eval_result["cadence_label"]
        elapsed_hours = eval_result["elapsed_hours"]
        elapsed_days = eval_result["elapsed_days"]

        if eval_result["is_within_24h"]:
            message_text = (
                f"Hi {cust_name}, Irene here from Home IHC! 😊 "
                "Just checking in to see if you had any questions regarding the properties we discussed, "
                "or if you would like to schedule a site viewing session?"
            )
            try:
                self.message_sender(conversation_id, message_text)
                action_taken = "message_sent"
                logger.info(f"Dispatched automated follow-up to conv {conversation_id} ({cust_name})")
            except Exception as e:
                logger.error(f"Failed to dispatch nurturing message to conv {conversation_id}: {e}")
                action_taken = "message_failed"
        else:
            note_text = (
                f"⏰ **Lead Nurturing Due ({cadence_label})**\n\n"
                f"👤 **Customer**: {cust_name} ({phone})\n"
                f"🔥 **Temperature**: {lead_temp.upper()}\n"
                f"⏳ **Inactive for**: {elapsed_hours:.1f} hours ({elapsed_days:.1f} days)\n\n"
                f"⚠️ **WhatsApp 24-Hour Policy Window Closed**:\n"
                f"Free-form automated messages cannot be sent without Meta template approval. "
                f"Please follow up directly via phone call or send an approved Meta Utility Template."
            )
            try:
                self.note_sender(conversation_id, note_text)
                action_taken = "private_note_posted"
                logger.info(f"Posted nurturing private note to conv {conversation_id} ({cust_name})")
            except Exception as e:
                logger.error(f"Failed to post nurturing private note to conv {conversation_id}: {e}")
                action_taken = "note_failed"

        # Update customer metadata
        meta = dict(customer.metadata_json or {})
        meta["last_nurtured_at"] = now.isoformat()
        meta["last_nurture_action"] = action_taken
        customer.metadata_json = meta

        return action_taken

    def run_cycle(self) -> Dict[str, Any]:
        """
        Scans all database customers and processes due nurture cadences.
        """
        db = self.db_session or SessionLocal()
        should_close = self.db_session is None
        nurtured_messages = 0
        private_notes = 0
        now = datetime.now(timezone.utc)

        try:
            customers = db.query(Customer).all()
            for c in customers:
                eval_res = self.evaluate_customer(c, now=now)
                if not eval_res:
                    continue

                action = self.dispatch_nurture(c, eval_res, now=now)
                if action == "message_sent":
                    nurtured_messages += 1
                elif action == "private_note_posted":
                    private_notes += 1
                db.commit()

        except Exception as exc:
            logger.error(f"Error executing nurturing cycle: {exc}")
            db.rollback()
            raise exc
        finally:
            if should_close:
                db.close()

        logger.info(f"Completed lead nurturing cycle: {nurtured_messages} messages, {private_notes} notes.")
        return {
            "status": "success",
            "nurtured_messages": nurtured_messages,
            "private_notes": private_notes
        }

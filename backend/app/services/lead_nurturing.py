"""
Lead Nurturing Management Service for Home IHC AI CRM.
Strict Object-Oriented Architecture implementing Strategy Pattern for Temperature Cadences,
Meta WhatsApp 24-hour Messaging Policy Enforcement, and Automated Re-engagement Template Dispatch.
"""

import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app.db.models import SessionLocal, Customer
from app.services.chatwoot import send_message, send_private_note, send_whatsapp_template

logger = logging.getLogger(__name__)


class LeadCadenceStrategy(ABC):
    """
    Abstract Strategy representing qualification and timing cadences per lead temperature.
    """

    @abstractmethod
    def is_due(self, elapsed_hours: float, is_staging: bool = False) -> bool:
        """Determines if the lead has been inactive long enough to warrant re-engagement."""
        pass

    @abstractmethod
    def get_cadence_label(self) -> str:
        """Returns the human-readable label for reporting and private notes."""
        pass

    @abstractmethod
    def get_message_content(self, customer_name: str, location: str = "", intent: str = "buyer") -> str:
        """Constructs conversational re-engagement message when within 24h window."""
        pass

    @abstractmethod
    def get_template_name(self) -> str:
        """Returns approved Meta message template identifier for out-of-window re-engagement."""
        pass


class HotCadenceStrategy(LeadCadenceStrategy):
    """
    Cadence Strategy for HOT Leads (High engagement / complete profile).
    Production: 18h to 72h of inactivity.
    Staging: 5 mins to 60 mins of inactivity.
    """

    def is_due(self, elapsed_hours: float, is_staging: bool = False) -> bool:
        if is_staging:
            return 0.08 <= elapsed_hours <= 1.0  # ~5m to 60m
        return 18.0 <= elapsed_hours <= 72.0

    def get_cadence_label(self) -> str:
        return "18-72h Hot Lead Priority Follow-Up"

    def get_message_content(self, customer_name: str, location: str = "", intent: str = "buyer") -> str:
        loc_str = f" in {location}" if location else ""
        intent_clean = (intent or "buyer").lower()
        if intent_clean in ["seller", "landowner"]:
            return (
                f"Hi {customer_name}, Irene here from Home IHC! 😊 "
                f"Following up on your property/land{loc_str}. Have you finalized your target asking price, "
                "or would you like our team to provide a complimentary valuation benchmark and buyer matching update?"
            )
        elif intent_clean == "landlord":
            return (
                f"Hi {customer_name}, Irene here from Home IHC! 😊 "
                f"Checking in regarding your rental property{loc_str}. Would you like us to schedule viewings "
                "with prospective qualified tenants this week?"
            )
        elif intent_clean == "tenant":
            return (
                f"Hi {customer_name}, Irene here from Home IHC! 😊 "
                f"Checking in on your rental search{loc_str}. Have you found a suitable unit, "
                "or would you like to schedule an on-site viewing for the options we discussed?"
            )
        elif intent_clean == "agent":
            return (
                f"Hi {customer_name}, Irene here from Home IHC! 😊 "
                f"Following up on our co-agency collaboration{loc_str}. Do you have any active buyer inquiries "
                "or co-broke cases we can partner on this week?"
            )
        else:
            return (
                f"Hi {customer_name}, Irene here from Home IHC! 😊 "
                f"Just checking in to see if you had any questions regarding the properties{loc_str} we discussed, "
                "or if you would like to schedule an on-site viewing session with our team?"
            )

    def get_template_name(self) -> str:
        return os.getenv("WHATSAPP_REENGAGEMENT_TEMPLATE", "lead_reengagement_utility")


class WarmCadenceStrategy(LeadCadenceStrategy):
    """
    Cadence Strategy for WARM Leads (Moderate interest / partial criteria).
    Production: 3 to 7 days of inactivity.
    Staging: 15 mins to 120 mins of inactivity.
    """

    def is_due(self, elapsed_hours: float, is_staging: bool = False) -> bool:
        if is_staging:
            return 0.25 <= elapsed_hours <= 2.0  # ~15m to 2h
        elapsed_days = elapsed_hours / 24.0
        return 3.0 <= elapsed_days <= 7.0

    def get_cadence_label(self) -> str:
        return "3-7d Warm Lead Check-in"

    def get_message_content(self, customer_name: str, location: str = "", intent: str = "buyer") -> str:
        loc_str = f" in {location}" if location else " in Pahang"
        intent_clean = (intent or "buyer").lower()
        if intent_clean in ["seller", "landowner"]:
            return (
                f"Hi {customer_name}! Hope you are having a wonderful week. 😊 "
                f"Irene here from Home IHC. We currently have active buyers actively inquiring about properties{loc_str}. "
                "Are you still looking to sell or list your unit, or would you like an updated market matching report?"
            )
        elif intent_clean == "landlord":
            return (
                f"Hi {customer_name}! Hope you're doing well. 😊 Irene from Home IHC. "
                f"Are you still looking for a tenant for your property{loc_str}? We have verified tenant inquiries available."
            )
        elif intent_clean == "tenant":
            return (
                f"Hi {customer_name}! Hope you're having a great week. 😊 "
                f"We recently updated our available rental listings{loc_str}. Are you still looking for a home or shop to rent?"
            )
        elif intent_clean == "agent":
            return (
                f"Hi {customer_name}! Hope your week is going great. 😊 "
                f"Irene from Home IHC. Checking in to see if you have any co-agency opportunities in {location or 'Pahang'} we can collaborate on."
            )
        else:
            return (
                f"Hi {customer_name}! Hope you are having a wonderful week. 😊 "
                f"Irene here from Home IHC. We recently updated our listings for properties{loc_str}. "
                "Are you still exploring options, or would you like me to share our latest curated selections?"
            )

    def get_template_name(self) -> str:
        return os.getenv("WHATSAPP_REENGAGEMENT_TEMPLATE", "lead_reengagement_utility")


class ColdCadenceStrategy(LeadCadenceStrategy):
    """
    Cadence Strategy for COLD / COOLING Leads (Dormant inquiries).
    Production: 7 to 14 days of inactivity.
    Staging: 30 mins to 240 mins of inactivity.
    """

    def is_due(self, elapsed_hours: float, is_staging: bool = False) -> bool:
        if is_staging:
            return 0.5 <= elapsed_hours <= 4.0  # ~30m to 4h
        elapsed_days = elapsed_hours / 24.0
        return 7.0 <= elapsed_days <= 14.0

    def get_cadence_label(self) -> str:
        return "7-14d Cooling Lead Re-Engagement"

    def get_message_content(self, customer_name: str, location: str = "", intent: str = "buyer") -> str:
        intent_clean = (intent or "buyer").lower()
        loc_str = f" in {location}" if location else " in Bentong and surrounding areas"
        if intent_clean in ["seller", "landowner"]:
            return (
                f"Hello {customer_name}, Irene from Home IHC. 😊 "
                f"Just following up to see if you still require any assistance with property valuation, sale marketing, or title verifications{loc_str}?"
            )
        elif intent_clean in ["landlord", "tenant"]:
            return (
                f"Hello {customer_name}, Irene from Home IHC. 😊 "
                f"Just wanted to check if your tenancy needs{loc_str} have been settled, or if you still need our agency's support?"
            )
        elif intent_clean == "agent":
            return (
                f"Hello {customer_name}, Irene from Home IHC. 😊 "
                "Reaching out to stay connected for any future joint agency or co-broke property opportunities in Pahang."
            )
        else:
            return (
                f"Hello {customer_name}, Irene from Home IHC. 😊 "
                f"Just wanted to see if you have found what you were looking for, or if you still need any assistance with land, residential, or commercial properties{loc_str}?"
            )

    def get_template_name(self) -> str:
        return os.getenv("WHATSAPP_REENGAGEMENT_TEMPLATE", "lead_reengagement_utility")


class MetaPolicyWindowGuard:
    """
    Encapsulates Meta WhatsApp Business messaging policy boundaries:
    - <= 24 hours: Customer care window open (Free-form conversational response authorized).
    - > 24 hours: Customer care window closed (Requires approved Meta Message Template).
    """

    @staticmethod
    def is_within_24h(elapsed_hours: float) -> bool:
        return elapsed_hours <= 24.0


class ReengagementTemplateDispatcher:
    """
    Dispatches pre-approved Meta Utility Templates when 24h conversation window has closed.
    Polymorphically binds customer intent into template variables for 100% Meta compliance.
    """

    INTENT_CONTEXT_MAP = {
        "buyer": {
            "inquiry_type": "property search",
            "context_phrase": "property search in {location}",
        },
        "seller": {
            "inquiry_type": "property listing & valuation inquiry",
            "context_phrase": "property listing & valuation in {location}",
        },
        "landowner": {
            "inquiry_type": "land listing & valuation inquiry",
            "context_phrase": "land listing & valuation in {location}",
        },
        "landlord": {
            "inquiry_type": "rental property listing",
            "context_phrase": "rental property listing in {location}",
        },
        "tenant": {
            "inquiry_type": "rental home search",
            "context_phrase": "rental search in {location}",
        },
        "agent": {
            "inquiry_type": "co-agency collaboration",
            "context_phrase": "co-agency collaboration in {location}",
        },
    }

    def __init__(self, inbox_id: int = None, phone_number_id: str = None, language_code: str = None):
        is_staging = (
            os.getenv("ENVIRONMENT", "").lower() == "staging"
            or os.getenv("APP_ENV") == "staging"
            or "staging" in os.getenv("REDIS_HOST", "")
            or os.getenv("DB_HOST") == "whatsapp_ai_db_staging"
        )
        self.is_staging = is_staging
        self.inbox_id = inbox_id or int(os.getenv("STAGING_INBOX_ID" if is_staging else "WHATSAPP_INBOX_ID", "4" if is_staging else "3"))
        
        staging_default_phone = "1033113423218081"
        prod_default_phone = "1039310802596891"
        default_phone = staging_default_phone if is_staging else prod_default_phone

        self.phone_number_id = phone_number_id or os.getenv("WHATSAPP_TEMPLATE_PHONE_NUMBER_ID", default_phone)
        if is_staging and str(self.phone_number_id) == prod_default_phone:
            self.phone_number_id = staging_default_phone
        
        # Check Redis configuration for template language
        stored_language = None
        try:
            from app.api.settings import redis_client
            import json
            raw = redis_client.get("lead_nurturing_config")
            if raw:
                stored = json.loads(raw.decode("utf-8"))
                stored_language = stored.get("meta_template_language")
        except Exception:
            pass

        self.language_code = language_code or stored_language or os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")

    def resolve_context_phrase(self, intent: str, location: str) -> str:
        """Constructs natural context phrase for variable {{2}} based on customer intent."""
        intent_clean = (intent or "buyer").lower()
        mapping = self.INTENT_CONTEXT_MAP.get(intent_clean, self.INTENT_CONTEXT_MAP["buyer"])
        loc = location or "Bentong"
        return mapping["context_phrase"].format(location=loc)

    def dispatch(
        self,
        to_phone: str,
        customer_name: str,
        location: str,
        template_name: str,
        intent: str = "buyer"
    ) -> dict:
        """
        Sends the 2-parameter Meta utility/marketing re-engagement template:
        {{1}}: Customer Name
        {{2}}: Intent & Location Context (e.g. 'property search in Bentong', 'land listing & valuation in Raub')
        """
        context_phrase = self.resolve_context_phrase(intent, location)
        params = [customer_name or "there", context_phrase]
        try:
            res = send_whatsapp_template(
                inbox_id=self.inbox_id,
                to_phone=to_phone,
                template_name=template_name,
                parameters=params,
                language_code=self.language_code,
                override_phone_number_id=self.phone_number_id
            )
            if not res:
                return {
                    "status": "error",
                    "error": f"Meta Cloud API rejected template '{template_name}' ({self.language_code}). Verify template approval and language code in Meta Business Suite.",
                    "parameters": params
                }
            logger.info(f"Dispatched Meta re-engagement template '{template_name}' ({self.language_code}, intent={intent}) to {to_phone}")
            return {"status": "success", "result": res, "parameters": params}
        except Exception as e:
            logger.error(f"Failed to dispatch Meta re-engagement template to {to_phone}: {e}")
            return {"status": "error", "error": str(e), "parameters": params}


class LeadNurturingManager:
    """
    Object-Oriented Lead Nurturing Orchestrator.
    Manages customer evaluation, cadence resolution, policy enforcement, and multi-channel dispatch.
    """

    def __init__(
        self,
        db_session=None,
        message_sender=None,
        note_sender=None,
        template_dispatcher=None,
        is_staging: bool = None
    ):
        self.db_session = db_session
        self.message_sender = message_sender or send_message
        self.note_sender = note_sender or send_private_note
        
        # Detect environment
        if is_staging is None:
            self.is_staging = (
                os.getenv("ENVIRONMENT", "").lower() == "staging"
                or os.getenv("APP_ENV") == "staging"
                or "staging" in os.getenv("REDIS_HOST", "")
                or os.getenv("DB_HOST") == "whatsapp_ai_db_staging"
            )
        else:
            self.is_staging = is_staging

        target_inbox_id = int(os.getenv("STAGING_INBOX_ID" if self.is_staging else "WHATSAPP_INBOX_ID", "4" if self.is_staging else "3"))
        staging_default_phone = "1033113423218081"
        prod_default_phone = "1039310802596891"
        target_phone_id = os.getenv("WHATSAPP_TEMPLATE_PHONE_NUMBER_ID", staging_default_phone if self.is_staging else prod_default_phone)
        if self.is_staging and str(target_phone_id) == prod_default_phone:
            target_phone_id = staging_default_phone

        self.template_dispatcher = template_dispatcher or ReengagementTemplateDispatcher(
            inbox_id=target_inbox_id,
            phone_number_id=target_phone_id
        )

        # Strategy registry
        self.strategies: Dict[str, LeadCadenceStrategy] = {
            "hot": HotCadenceStrategy(),
            "warm": WarmCadenceStrategy(),
            "cold": ColdCadenceStrategy(),
            "cooling": ColdCadenceStrategy()
        }

    def evaluate_customer(
        self,
        customer: Customer,
        now: Optional[datetime] = None,
        force_temp: Optional[str] = None,
        force_due: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether a customer is due for nurturing.
        Supports force_temp and force_due for on-demand testing in staging.
        """
        now = now or datetime.now(timezone.utc)
        meta = customer.metadata_json or {}

        # Respect human handover / bypass AI unless forced in test
        if meta.get("bypass_ai") and not force_due:
            return None

        # Check last nurtured timestamp (prevent duplicate pings within 24h unless force_due)
        last_nurtured_str = meta.get("last_nurtured_at")
        if last_nurtured_str and not force_due:
            try:
                last_nurtured = datetime.fromisoformat(last_nurtured_str)
                if last_nurtured.tzinfo is None:
                    last_nurtured = last_nurtured.replace(tzinfo=timezone.utc)
                if (now - last_nurtured).total_seconds() < 86400:
                    return None
            except Exception:
                pass

        # Resolve active conversation_id across multiple sources
        conversation_id = meta.get("conversation_id")
        if not conversation_id and customer.conversation_ids:
            if isinstance(customer.conversation_ids, list) and customer.conversation_ids:
                conversation_id = customer.conversation_ids[-1]
            elif isinstance(customer.conversation_ids, (int, str)):
                conversation_id = customer.conversation_ids

        # In staging, guarantee conversation routes through Staging Inbox (Inbox 4)
        if self.is_staging:
            staging_inbox_id = int(os.getenv("STAGING_INBOX_ID", "4"))
            if meta.get("staging_conversation_id"):
                conversation_id = meta.get("staging_conversation_id")
            elif meta.get("inbox_id") != staging_inbox_id:
                try:
                    from app.services.chatwoot import get_or_create_contact, create_conversation
                    clean_p = customer.id or getattr(customer, "phone_number", "")
                    cust_name = customer.contact_name or "Staging Customer"
                    contact_id = get_or_create_contact(clean_p, cust_name)
                    if contact_id:
                        s_conv = create_conversation(contact_id, staging_inbox_id)
                        if s_conv:
                            conversation_id = s_conv
                            meta["staging_conversation_id"] = s_conv
                            customer.metadata_json = meta
                except Exception as ce:
                    logger.error(f"Failed to resolve staging conversation in Inbox {staging_inbox_id}: {ce}")

        if not conversation_id:
            return None

        # Resolve last active timestamp safely across real models and MagicMock specs
        candidates = [
            getattr(customer, "last_interaction", None),
            getattr(customer, "updated_at", None),
            getattr(customer, "created_at", None),
        ]
        last_active = None
        for cand in candidates:
            if isinstance(cand, datetime):
                last_active = cand
                break
            elif isinstance(cand, str):
                try:
                    last_active = datetime.fromisoformat(cand)
                    break
                except Exception:
                    pass

        if not last_active:
            last_active = now
        if getattr(last_active, "tzinfo", None) is None:
            last_active = last_active.replace(tzinfo=timezone.utc)

        elapsed_seconds = (now - last_active).total_seconds()
        try:
            elapsed_hours = max(0.0, float(elapsed_seconds) / 3600.0)
        except (TypeError, ValueError):
            elapsed_hours = 0.0
        elapsed_days = elapsed_hours / 24.0

        # Resolve temperature and strategy
        lead_temp = (force_temp or meta.get("lead_temp") or meta.get("temperature") or "warm").lower()
        strategy = self.strategies.get(lead_temp, self.strategies["warm"])

        is_due = force_due or strategy.is_due(elapsed_hours, is_staging=self.is_staging)
        if not is_due:
            return None

        # Resolve location context for template
        collected = meta.get("collected_data", {}) or {}
        req_prof = meta.get("requirements_profile", {}) or {}
        location = (
            collected.get("buyer_location")
            or collected.get("location")
            or req_prof.get("active_inquiry", {}).get("location")
            or "Bentong"
        )

        # Resolve customer intent (buyer, seller, landowner, landlord, tenant, agent)
        raw_intent = None
        if hasattr(customer, "intent_category"):
            try:
                val = getattr(customer, "intent_category", None)
                if isinstance(val, str):
                    raw_intent = val
            except Exception:
                pass

        if not raw_intent:
            raw_intent = (
                meta.get("intent_category")
                or collected.get("intent")
                or req_prof.get("active_inquiry", {}).get("intent")
                or "buyer"
            )

        intent = (raw_intent if isinstance(raw_intent, str) else "buyer").lower()

        is_within_24h = MetaPolicyWindowGuard.is_within_24h(elapsed_hours)

        return {
            "customer_id": str(customer.id),
            "contact_name": customer.contact_name or "there",
            "phone_number": customer.id or getattr(customer, "phone_number", "Unknown"),
            "conversation_id": int(conversation_id),
            "lead_temp": lead_temp,
            "intent": intent,
            "cadence_label": strategy.get_cadence_label(),
            "template_name": strategy.get_template_name(),
            "message_text": strategy.get_message_content(customer.contact_name or "there", location, intent=intent),
            "location": location,
            "elapsed_hours": elapsed_hours,
            "elapsed_days": elapsed_days,
            "is_within_24h": is_within_24h
        }

    def dispatch_nurture(self, customer: Customer, eval_result: Dict[str, Any], now: Optional[datetime] = None) -> str:
        """
        Executes follow-up dispatch according to Meta 24-hour compliance rules.
        """
        now = now or datetime.now(timezone.utc)
        conversation_id = eval_result["conversation_id"]
        cust_name = eval_result["contact_name"]
        phone = eval_result["phone_number"]
        lead_temp = eval_result["lead_temp"]
        intent = eval_result.get("intent", "buyer")
        cadence_label = eval_result["cadence_label"]
        elapsed_hours = eval_result["elapsed_hours"]
        elapsed_days = eval_result["elapsed_days"]
        location = eval_result["location"]
        template_name = eval_result["template_name"]

        action_taken = "none"

        if eval_result["is_within_24h"]:
            message_text = eval_result["message_text"]
            try:
                self.message_sender(conversation_id, message_text)
                action_taken = "message_sent"
                logger.info(f"Dispatched automated 24h follow-up to conv {conversation_id} ({cust_name}, intent={intent})")
            except Exception as e:
                logger.error(f"Failed to dispatch nurturing message to conv {conversation_id}: {e}")
                action_taken = "message_failed"
        else:
            # Outside 24 hours: Dispatch approved Meta Re-engagement Template directly to WhatsApp
            t_res = self.template_dispatcher.dispatch(
                to_phone=phone,
                customer_name=cust_name,
                location=location,
                template_name=template_name,
                intent=intent
            )
            template_success = t_res.get("status") == "success" and bool(t_res.get("result"))

            dispatch_status = "✅ Dispatched to WhatsApp" if template_success else f"❌ Template Dispatch Failed ({t_res.get('error', 'Translation/Language mismatch')})"
            diagnostic_tip = "" if template_success else (
                f"\n\n💡 **Troubleshooting Tip**:\n"
                f"- In Meta Business Suite, check if the template `{template_name}` is approved.\n"
                f"- If Meta updated it to **MARKETING**, it is still valid and operational.\n"
                f"- Ensure the template language code matches. Current configured code: `{getattr(self.template_dispatcher, 'language_code', 'en_US')}`."
            )

            note_text = (
                f"⏰ **Automated Lead Nurturing Executed ({cadence_label})**\n\n"
                f"👤 **Customer**: {cust_name} ({phone})\n"
                f"🎯 **Intent / Persona**: {intent.upper()}\n"
                f"🔥 **Temperature**: {lead_temp.upper()}\n"
                f"⏳ **Inactive for**: {elapsed_hours:.1f} hours ({elapsed_days:.1f} days)\n"
                f"📍 **Focus Area**: {location}\n\n"
                f"⚠️ **WhatsApp 24-Hour Policy Window Closed**:\n"
                f"Free-form automated messages cannot be sent without Meta template approval. "
                f"Automated template re-engagement preserves Meta health score.\n\n"
                f"📲 **Meta Re-engagement Template**: `{template_name}` ({dispatch_status})"
                f"{diagnostic_tip}"
            )
            try:
                self.note_sender(conversation_id, note_text)
                action_taken = "private_note_posted"
            except Exception as e:
                logger.error(f"Failed to post nurturing private note to conv {conversation_id}: {e}")
                action_taken = "dispatch_error"

        # Persist nurturing state to customer metadata
        meta = dict(customer.metadata_json or {})
        meta["last_nurtured_at"] = now.isoformat()
        meta["last_nurture_action"] = action_taken
        meta["lead_temp"] = lead_temp
        meta["intent_category"] = intent
        customer.metadata_json = meta

        return action_taken

    def run_cycle(self) -> Dict[str, Any]:
        """
        Scans all database customers and processes due nurture cadences.
        """
        db = self.db_session or SessionLocal()
        should_close = self.db_session is None
        nurtured_messages = 0
        templates_dispatched = 0
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
                elif action in ["template_dispatched", "private_note_posted"]:
                    templates_dispatched += 1
                    private_notes += 1
                elif "note" in action:
                    private_notes += 1
                db.commit()

        except Exception as exc:
            logger.error(f"Error executing nurturing cycle: {exc}")
            db.rollback()
            raise exc
        finally:
            if should_close:
                db.close()

        logger.info(
            f"Completed lead nurturing cycle: {nurtured_messages} 24h messages, "
            f"{templates_dispatched} templates, {private_notes} notes."
        )
        return {
            "status": "success",
            "nurtured_messages": nurtured_messages,
            "templates_dispatched": templates_dispatched,
            "private_notes": private_notes
        }

    def evaluate_single_lead(self, customer: Customer, forced_cadence: Optional[str] = None, db: Optional[Any] = None) -> Dict[str, Any]:
        """
        Evaluates and dispatches nurturing for a single lead on-demand.
        Supports forced cadence override ('hot', 'warm', 'cold').
        """
        now = datetime.now(timezone.utc)
        eval_res = self.evaluate_customer(customer, now=now, force_temp=forced_cadence, force_due=bool(forced_cadence))
        if not eval_res:
            return {"action": "none", "details": "Customer is not currently due for nurturing follow-up under current timing window."}
        action = self.dispatch_nurture(customer, eval_res, now=now)
        if db:
            try:
                db.commit()
            except Exception:
                pass
        return {
            "action": action,
            "details": f"Executed cadence '{eval_res['cadence_label']}' (Action: {action}).",
            "eval_result": eval_res
        }


# Service alias for backward compatibility and clean API importing
LeadNurturingService = LeadNurturingManager



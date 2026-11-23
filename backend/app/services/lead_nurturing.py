"""
Lead Nurturing Management Service for Home IHC AI CRM.
Strict Object-Oriented Architecture implementing Strategy Pattern for Temperature Cadences,
Meta WhatsApp 24-hour Messaging Policy Enforcement, and Automated Re-engagement Template Dispatch.
"""

import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional, Dict, Any, List

from app.db.models import SessionLocal, Customer
from app.services.chatwoot import (
    get_contact_conversations,
    get_conversation_messages,
    send_message,
    send_private_note,
    send_whatsapp_template,
)
from app.services.db_services import normalize_phone_variants

logger = logging.getLogger(__name__)

_INCOMING_MESSAGE_TYPES = {0, "0", "incoming"}
_OUTGOING_MESSAGE_TYPES = {1, "1", "outgoing", 3, "3", "template"}


def canonical_nurture_intent(intent: str) -> str:
    """Renter enquiries use the existing tenant nurture copy."""
    cleaned = (intent or "buyer").strip().lower()
    if cleaned == "renter":
        return "tenant"
    return cleaned or "buyer"


def nurture_allowlist_variants() -> set:
    """
    NURTURE_TEST_CONTACTS is a comma-separated list of E.164 numbers.
    Empty or unset is an empty set (staging then sends to nobody).
    """
    raw = os.getenv("NURTURE_TEST_CONTACTS", "") or ""
    variants = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            variants.update(normalize_phone_variants(part))
    return variants


def phone_in_nurture_allowlist(phone: str, variants: set) -> bool:
    if not phone or not variants:
        return False
    return bool(set(normalize_phone_variants(str(phone))) & set(variants))


def _message_direction(message: dict):
    if not isinstance(message, dict) or message.get("private"):
        return None
    kind = message.get("message_type")
    if kind in _INCOMING_MESSAGE_TYPES:
        return "in"
    if kind in _OUTGOING_MESSAGE_TYPES:
        return "out"
    return None


def _parse_message_time(message: dict):
    raw = message.get("created_at") if isinstance(message, dict) else None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e11:
            ts = ts / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            try:
                ts = float(raw)
                if ts > 1e11:
                    ts = ts / 1000.0
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_inbound_clock(conversation_id, fetcher=None):
    """
    Last inbound customer message, and whether the latest public message is ours.

    Returns None when the clock cannot be determined (fail closed).
    Does not use customer.last_interaction: our own reply writes that field.
    """
    fetcher = fetcher or get_conversation_messages
    try:
        messages = fetcher(int(conversation_id)) if conversation_id else None
    except Exception as exc:
        logger.info("Nurture inbound clock unavailable for conv %s: %s", conversation_id, exc)
        return None
    if not isinstance(messages, list) or not messages:
        logger.info("Nurture inbound clock undetermined for conv %s (no messages)", conversation_id)
        return None
    stamped = []
    for message in messages:
        direction = _message_direction(message)
        when = _parse_message_time(message)
        if direction and when:
            stamped.append((when, direction))
    if not stamped:
        logger.info(
            "Nurture inbound clock undetermined for conv %s (no public inbound or outbound)",
            conversation_id,
        )
        return None
    stamped.sort(key=lambda item: item[0])
    inbound_times = [when for when, direction in stamped if direction == "in"]
    latest_is_ours = stamped[-1][1] == "out"
    if latest_is_ours:
        return {"latest_is_ours": True, "last_inbound_at": inbound_times[-1] if inbound_times else None}
    if not inbound_times:
        logger.info("Nurture inbound clock undetermined for conv %s (no inbound message)", conversation_id)
        return None
    return {"latest_is_ours": False, "last_inbound_at": inbound_times[-1]}


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
        intent_clean = canonical_nurture_intent(intent)
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
        intent_clean = canonical_nurture_intent(intent)
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
        intent_clean = canonical_nurture_intent(intent)
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
        intent_clean = canonical_nurture_intent(intent)
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


def _copy_plain(value: Any) -> Any:
    """Keep JSON-able values. Drop MagicMock and ORM internals."""
    if isinstance(value, (str, int, float, bool, datetime)):
        return value
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return None


def _freeze_customer(row: Any) -> SimpleNamespace:
    """Detach the fields run_cycle needs so the scan session can close."""
    return SimpleNamespace(
        id=_copy_plain(getattr(row, "id", None)),
        contact_name=_copy_plain(getattr(row, "contact_name", None)),
        phone_number=_copy_plain(getattr(row, "phone_number", None)),
        conversation_ids=_copy_plain(getattr(row, "conversation_ids", None)),
        metadata_json=_copy_plain(getattr(row, "metadata_json", None)) or {},
        last_interaction=_copy_plain(getattr(row, "last_interaction", None)),
        updated_at=_copy_plain(getattr(row, "updated_at", None)),
        created_at=_copy_plain(getattr(row, "created_at", None)),
        intent_category=_copy_plain(getattr(row, "intent_category", None)),
    )


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
        self._allowlist_notice_logged = False

    def _log_empty_allowlist_once(self) -> None:
        if self._allowlist_notice_logged:
            return
        logger.info(
            "NURTURE_TEST_CONTACTS is unset; staging nurture will not send to anyone"
        )
        self._allowlist_notice_logged = True

    def _staging_contact_permitted(self, customer) -> bool:
        """Production is unchanged. Staging sends only to NURTURE_TEST_CONTACTS."""
        if not self.is_staging:
            return True
        allow = nurture_allowlist_variants()
        if not allow:
            self._log_empty_allowlist_once()
            return False
        phone = getattr(customer, "id", None) or getattr(customer, "phone_number", None)
        if not phone_in_nurture_allowlist(phone, allow):
            logger.info(
                "Staging nurture skipped %s; not in NURTURE_TEST_CONTACTS",
                phone,
            )
            return False
        return True

    def _existing_conversation_id(self, customer, meta: dict):
        """
        Reuse a conversation this contact already has. Never create one.
        """
        conversation_id = meta.get("conversation_id")
        if not conversation_id:
            ids = getattr(customer, "conversation_ids", None)
            if isinstance(ids, list) and ids:
                conversation_id = ids[-1]
            elif isinstance(ids, (int, str)) and str(ids).strip():
                conversation_id = ids
        if self.is_staging and meta.get("staging_conversation_id"):
            conversation_id = meta.get("staging_conversation_id")
        if conversation_id:
            return conversation_id
        contact_id = meta.get("chatwoot_contact_id") or meta.get("contact_id")
        if not contact_id:
            logger.info(
                "[NURTURE SKIP] no existing conversation for %s; not creating one",
                getattr(customer, "id", None),
            )
            return None
        try:
            existing = get_contact_conversations(int(contact_id))
        except Exception as exc:
            logger.info(
                "[NURTURE SKIP] could not list conversations for contact %s: %s",
                contact_id,
                exc,
            )
            return None
        inbox_id = int(os.getenv(
            "STAGING_INBOX_ID" if self.is_staging else "WHATSAPP_INBOX_ID",
            "4" if self.is_staging else "3",
        ))
        for conv in existing or []:
            if not isinstance(conv, dict):
                continue
            if str(conv.get("inbox_id")) == str(inbox_id) and conv.get("id"):
                logger.info(
                    "Nurture reusing conversation %s for contact %s",
                    conv.get("id"),
                    contact_id,
                )
                return conv.get("id")
        logger.info(
            "[NURTURE SKIP] contact %s has no conversation in inbox %s; not creating one",
            contact_id,
            inbox_id,
        )
        return None

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

        # Respect RBAC: Never send automated lead follow-ups to internal staff (admin, employee, agent)
        if not force_due:
            phone_cand = getattr(customer, "id", None) or getattr(customer, "phone_number", None)
            if phone_cand:
                try:
                    from app.services.db_services import get_sender_role
                    # Own short session. Never borrow the scan session: that
                    # connection used to stay checked out across Chatwoot calls.
                    sender_role = get_sender_role(str(phone_cand))
                    if sender_role in ["admin", "employee", "agent"]:
                        logger.info(
                            f"[NURTURE SUPPRESSED] Customer {phone_cand} is verified staff ({sender_role}). Skipping lead follow-up."
                        )
                        return None
                except Exception as role_err:
                    logger.warning(f"Could not verify sender role for nurturing candidate {phone_cand}: {role_err}")

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

        if not self._staging_contact_permitted(customer):
            return None

        # Reuse an existing conversation. Never call create-conversation.
        conversation_id = self._existing_conversation_id(customer, meta)
        if not conversation_id:
            return None

        clock = resolve_inbound_clock(conversation_id)
        if not clock:
            logger.info(
                "[NURTURE SKIP] inbound clock undetermined for %s conv %s",
                getattr(customer, "id", None),
                conversation_id,
            )
            return None
        if clock.get("latest_is_ours"):
            logger.info(
                "[NURTURE SKIP] latest message in conv %s is ours; not following up",
                conversation_id,
            )
            return None
        last_active = clock.get("last_inbound_at")
        if not isinstance(last_active, datetime):
            logger.info(
                "[NURTURE SKIP] no inbound timestamp for conv %s",
                conversation_id,
            )
            return None
        if last_active.tzinfo is None:
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

        intent = canonical_nurture_intent(raw_intent if isinstance(raw_intent, str) else "buyer")

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

    def _persist_nurture_metadata(self, customer: Any) -> None:
        """Write nurture metadata in a session that is closed before return."""
        customer_id = getattr(customer, "id", None)
        if not customer_id:
            return
        meta = getattr(customer, "metadata_json", None) or {}
        if not isinstance(meta, dict):
            return
        db = SessionLocal()
        try:
            row = db.query(Customer).filter(Customer.id == customer_id).first()
            if row is None:
                return
            row.metadata_json = dict(meta)
            try:
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(row, "metadata_json")
            except Exception:
                pass
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            db.close()

    def run_cycle(self) -> Dict[str, Any]:
        """
        Scans all database customers and processes due nurture cadences.
        """
        # Respect Dashboard Follow-Up Toggle
        try:
            from app.api.settings import get_system_toggle
            if not get_system_toggle("lead_nurturing_enabled", default=True):
                logger.info("[SKIPPED] Automated lead follow-up engine is disabled via dashboard settings.")
                return {
                    "status": "skipped",
                    "reason": "followup_disabled",
                    "nurtured_messages": 0,
                    "templates_dispatched": 0,
                    "private_notes": 0
                }
        except Exception as toggle_err:
            logger.warning(f"Could not check follow-up toggle status: {toggle_err}")

        # Load every row, copy the fields the cycle needs, and close the
        # session before any Chatwoot/WhatsApp call. A session passed in by
        # the caller is closed here too: SQLAlchemy 2.0 keeps the checked-out
        # connection alive until close(), so leaving it on the manager leaked
        # one connection per hourly run until the pool (15 + 25) was full.
        db = self.db_session or SessionLocal()
        now = datetime.now(timezone.utc)
        try:
            snapshots = [_freeze_customer(row) for row in db.query(Customer).all()]
        except Exception as exc:
            logger.error(f"Error executing nurturing cycle: {exc}")
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            db.close()

        nurtured_messages = 0
        templates_dispatched = 0
        private_notes = 0
        if self.is_staging and not nurture_allowlist_variants():
            self._log_empty_allowlist_once()
        try:
            for customer in snapshots:
                eval_res = self.evaluate_customer(customer, now=now)
                if not eval_res:
                    continue

                action = self.dispatch_nurture(customer, eval_res, now=now)
                self._persist_nurture_metadata(customer)
                if action == "message_sent":
                    nurtured_messages += 1
                elif action in ["template_dispatched", "private_note_posted"]:
                    templates_dispatched += 1
                    private_notes += 1
                elif "note" in action:
                    private_notes += 1
        except Exception as exc:
            logger.error(f"Error executing nurturing cycle: {exc}")
            raise

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



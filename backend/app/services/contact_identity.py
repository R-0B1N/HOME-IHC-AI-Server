"""Resolve a Chatwoot contact without inventing a phone or sharing ``session:``.

Order: sender phone, conversation meta phone, a digit identifier, then a digit
``source_id``. Anything else (a Meta BSUID such as ``MY.…``) becomes its own
``cw:{contact_id}`` customer and session. Logs name the id kind only.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_E164 = re.compile(r"^\+[1-9]\d{1,14}$")
_DIGIT_ID = re.compile(r"^\d{8,15}$")
_BSUID = re.compile(r"^[A-Za-z]{2}\.[A-Za-z0-9]+$")
_AUTH_TEMPLATE = re.compile(
    r"otp|one[_-]?time|authentication|auth[_-]?code|authcode|verify(?:_code)?|verification",
    re.IGNORECASE,
)


def is_e164(value: Any) -> bool:
    return bool(_E164.match(str(value or "").strip()))


def is_digit_identifier(value: Any) -> bool:
    return bool(_DIGIT_ID.match(str(value or "").strip()))


def is_bsuid(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or is_digit_identifier(text) or is_e164(text):
        return False
    if _BSUID.match(text):
        return True
    return "." in text and bool(re.search(r"[A-Za-z]", text))


def is_synthetic_customer_id(value: Any) -> bool:
    return str(value or "").strip().lower().startswith("cw:")


def to_e164(value: Any) -> Optional[str]:
    """Digit wa_id or a local 01x mobile becomes E.164. A BSUID does not."""
    raw = str(value or "").strip()
    if not raw or is_bsuid(raw) or is_synthetic_customer_id(raw):
        return None
    if is_e164(raw):
        return raw
    compact = re.sub(r"[\s().-]", "", raw)
    if not re.fullmatch(r"\+?\d{8,15}", compact):
        return None
    digits = compact[1:] if compact.startswith("+") else compact
    if not _DIGIT_ID.match(digits):
        return None
    if digits.startswith("0"):
        if digits.startswith("01") and len(digits) in (10, 11):
            digits = "60" + digits[1:]
        else:
            return None
    candidate = "+" + digits
    if is_e164(candidate):
        return candidate
    return None


def identity_kind(value: Any) -> str:
    if is_synthetic_customer_id(value):
        return "chatwoot"
    if to_e164(value):
        return "phone"
    if is_bsuid(value):
        return "bsuid"
    if not str(value or "").strip():
        return "empty"
    return "chatwoot"


def is_authentication_template(template_name: str) -> bool:
    """Meta error 131062: authentication templates cannot be sent to a BSUID."""
    return bool(_AUTH_TEMPLATE.search(str(template_name or "")))


def meta_destination_fields(destination: Any) -> Dict[str, str]:
    """Cloud API addressing. A BSUID goes in ``recipient``; a phone stays in ``to``."""
    text = str(destination or "").strip()
    if is_bsuid(text):
        return {"recipient": text}
    e164 = to_e164(text)
    if e164:
        return {"to": e164[1:]}
    digits = "".join(ch for ch in text if ch.isdigit())
    return {"to": digits or text}


def log_contact_identity(kind: str) -> None:
    """Kind only. The value is never written."""
    logger.info("contact identity kind=%s value=%s", kind or "empty", "[redacted]")


def _nested(mapping: Dict[str, Any], *keys) -> Dict[str, Any]:
    current = mapping or {}
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key) or {}
    return current if isinstance(current, dict) else {}


def resolve_contact_identity(
    sender: Optional[Dict[str, Any]] = None,
    conversation: Optional[Dict[str, Any]] = None,
    conversation_id: Any = None,
    inbox_id: Any = None,
) -> Dict[str, Any]:
    """Pick one stable customer id. Never the empty string."""
    sender = sender or {}
    conversation = conversation or {}
    meta_sender = _nested(conversation, "meta", "sender")
    contact_inbox = {}
    if isinstance(conversation.get("contact_inbox"), dict):
        contact_inbox = conversation.get("contact_inbox") or {}
    elif isinstance(sender.get("contact_inbox"), dict):
        contact_inbox = sender.get("contact_inbox") or {}

    source_id = contact_inbox.get("source_id") or conversation.get("source_id") or ""
    identifier = sender.get("identifier") or meta_sender.get("identifier") or ""
    contact_id = sender.get("id") or meta_sender.get("id")

    phone = to_e164(sender.get("phone_number")) or to_e164(meta_sender.get("phone_number"))
    if not phone and is_digit_identifier(identifier):
        phone = to_e164(identifier)
    if not phone and is_digit_identifier(source_id):
        phone = to_e164(source_id)

    if phone:
        kind = "phone"
        customer_id = phone
        phone_missing = False
    else:
        raw_other = str(source_id or identifier or "").strip()
        if is_bsuid(raw_other):
            kind = "bsuid"
        elif raw_other:
            kind = "chatwoot"
        else:
            kind = "chatwoot"
        if contact_id not in (None, ""):
            customer_id = f"cw:{contact_id}"
        elif conversation_id not in (None, ""):
            customer_id = f"cw:conv:{conversation_id}"
        else:
            customer_id = "cw:unknown"
        phone_missing = True

    log_contact_identity(kind)
    return {
        "customer_id": customer_id,
        "session_key": customer_id,
        "phone_e164": phone,
        "phone_missing": phone_missing,
        "kind": kind,
        "source_id_kind": identity_kind(source_id) if source_id else identity_kind(identifier),
        "chatwoot_contact_id": contact_id,
        "inbox_id": inbox_id,
        "conversation_id": conversation_id,
    }

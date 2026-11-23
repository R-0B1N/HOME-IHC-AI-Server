"""Meta error 131026 on a Chatwoot ``message_updated`` webhook.

Chatwoot stores the outgoing row first and reports Meta's later failure as
``status: failed`` plus ``content_attributes.external_error``
(``"131026: Message undeliverable"``). One conversation is noted, labelled,
alerted, and blocked once. A repeat delivery of the same status does not
alert again.
"""

import json
import logging
from typing import Any, Dict, Optional

from app.services.contact_identity import is_synthetic_customer_id, resolve_contact_identity
from app.services.handover_assignee import handover_without_specialist
from app.services.outbound_block import block_key, is_outbound_blocked, mark_outbound_blocked

logger = logging.getLogger(__name__)

UNDELIVERABLE_CODE = "131026"
UNDELIVERABLE_LABEL = "undeliverable"


def _external_error_blob(payload: Dict[str, Any]) -> str:
    attrs = payload.get("content_attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    extra = payload.get("additional_attributes") or {}
    if not isinstance(extra, dict):
        extra = {}
    parts = [attrs.get("external_error"), extra.get("external_error"), attrs.get("error")]
    rendered = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, str):
            rendered.append(part)
        else:
            try:
                rendered.append(json.dumps(part))
            except TypeError:
                rendered.append(str(part))
    return " ".join(rendered)


def meta_failure_code(payload: Dict[str, Any]) -> Optional[str]:
    """131026 only when Chatwoot marks the message failed and the code is present."""
    if not isinstance(payload, dict):
        return None
    status = str(payload.get("status") or "").strip().lower()
    blob = _external_error_blob(payload)
    if status != "failed":
        return None
    if UNDELIVERABLE_CODE in blob:
        return UNDELIVERABLE_CODE
    return None


def _conversation(payload: Dict[str, Any]) -> Dict[str, Any]:
    conversation = payload.get("conversation") or {}
    return conversation if isinstance(conversation, dict) else {}


def _message_id(payload: Dict[str, Any]) -> Any:
    return payload.get("id") or payload.get("message_id")


def _dedupe_marker(conversation_id: Any, code: str) -> str:
    return f"undeliverable_alerted:{conversation_id}:{code}"


def _already_handled(conversation_id: Any, code: str) -> bool:
    try:
        from app.services.outbound_block import _client

        return bool(_client().get(_dedupe_marker(conversation_id, code)))
    except Exception:
        return False


def _remember_handled(conversation_id: Any, code: str) -> None:
    try:
        from app.services.outbound_block import _client

        _client().set(_dedupe_marker(conversation_id, code), "1")
    except Exception as exc:
        logger.warning("Could not remember undeliverable alert for %s: %s", conversation_id, exc)


def _merge_label(conversation_id: int, label: str) -> None:
    from app.services.chatwoot import apply_label, get_conversation_details

    current = []
    try:
        details = get_conversation_details(conversation_id) or {}
        labels = details.get("labels") or []
        if isinstance(labels, list):
            current = [str(item) for item in labels if item]
    except Exception as exc:
        logger.warning("Could not read labels for %s: %s", conversation_id, exc)
    merged = list(dict.fromkeys([*current, label]))
    apply_label(conversation_id, merged)


def _stop_nurture(identity: Dict[str, Any], conversation_id: int) -> None:
    customer_id = identity.get("customer_id")
    if not customer_id:
        return
    try:
        from sqlalchemy.orm.attributes import flag_modified

        from app.db.models import Customer, SessionLocal

        db = SessionLocal()
        try:
            row = db.query(Customer).filter(Customer.id == customer_id).first()
            if row is None and not is_synthetic_customer_id(customer_id):
                return
            if row is None:
                return
            meta = dict(row.metadata_json or {})
            meta["outbound_blocked"] = True
            meta["nurture_stopped"] = True
            meta["undeliverable_code"] = UNDELIVERABLE_CODE
            row.metadata_json = meta
            try:
                flag_modified(row, "metadata_json")
            except Exception:
                pass
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Could not stop nurture for conv %s: %s", conversation_id, exc)


def handle_message_updated(payload: Dict[str, Any]) -> Dict[str, Any]:
    code = meta_failure_code(payload)
    if code != UNDELIVERABLE_CODE:
        return {"status": "ignored", "reason": "message_updated is not a 131026 failure"}

    conversation = _conversation(payload)
    conversation_id = conversation.get("id")
    if not conversation_id:
        return {"status": "ignored", "reason": "message_updated has no conversation"}

    if _already_handled(conversation_id, code) or is_outbound_blocked(conversation_id):
        mark_outbound_blocked(conversation_id)
        return {
            "status": "duplicate",
            "conversation_id": conversation_id,
            "code": code,
            "outbound_blocked": True,
        }

    sender = payload.get("sender") or {}
    if not isinstance(sender, dict):
        sender = {}
    meta_sender = (conversation.get("meta") or {}).get("sender") if isinstance(conversation.get("meta"), dict) else None
    identity = resolve_contact_identity(
        sender=sender or (meta_sender if isinstance(meta_sender, dict) else {}),
        conversation=conversation,
        conversation_id=conversation_id,
        inbox_id=(payload.get("inbox") or {}).get("id") if isinstance(payload.get("inbox"), dict) else conversation.get("inbox_id"),
    )
    message_id = _message_id(payload)
    blob = _external_error_blob(payload)
    note = (
        f"WhatsApp did not deliver message {message_id}. "
        f"Meta error {code}: {blob or 'Message undeliverable'}. "
        "The bot will not send anything else to this contact."
    )
    inbox_raw = identity.get("inbox_id") or conversation.get("inbox_id") or 1
    try:
        inbox_id = int(inbox_raw)
    except (TypeError, ValueError):
        inbox_id = 1

    result = handover_without_specialist(
        conversation_id,
        reason="undeliverable_131026",
        note=note,
        customer_name=(sender.get("name") if isinstance(sender, dict) else "") or "",
        customer_phone=identity.get("phone_e164") or "",
        intent="undeliverable",
        conversation_summary=note,
        inbox_id=inbox_id,
    )
    try:
        _merge_label(conversation_id, UNDELIVERABLE_LABEL)
    except Exception as exc:
        logger.warning("Could not apply undeliverable label on %s: %s", conversation_id, exc)
        result["label_error"] = str(exc)

    mark_outbound_blocked(conversation_id)
    _remember_handled(conversation_id, code)
    _stop_nurture(identity, conversation_id)
    result.update({
        "status": "undeliverable",
        "conversation_id": conversation_id,
        "code": code,
        "message_id": message_id,
        "outbound_blocked": True,
        "nurture_stopped": True,
        "label": UNDELIVERABLE_LABEL,
        "block_key": block_key(conversation_id),
    })
    return result

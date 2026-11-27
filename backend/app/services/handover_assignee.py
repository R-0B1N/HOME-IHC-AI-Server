"""Shared assignee step for photo no-match and undeliverable sends.

Both callers use ``resolve_general_handover_assignees``. An empty result keeps
the existing admin-alert path and leaves the conversation open and unassigned.
"""

import logging
from typing import Any, Dict, List, Optional

from app.services.chatwoot import unassign_agent
from app.services.general_assignee import resolve_general_pool
from app.services.lead_handover import LeadHandoverService

logger = logging.getLogger(__name__)

NO_GENERAL_ASSIGNEE = "No general assignee was found."
UNASSIGNED_OK = "The conversation stays open and is unassigned."
UNASSIGNED_FAILED = "Unassign failed; the previous assignee is unchanged."


def image_data_urls(messages) -> list:
    """Chatwoot image attachment data_urls from queued webhook messages."""
    found = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for attachment in message.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            if str(attachment.get("file_type") or "").lower() != "image":
                continue
            url = str(attachment.get("data_url") or attachment.get("thumb_url") or "").strip()
            if url and url not in found:
                found.append(url)
    return found


def with_photo_links(note: str, photo_urls) -> str:
    """Append photo links. None means this handover is not a photo turn."""
    if photo_urls is None:
        return note
    urls = []
    for url in photo_urls:
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    if urls:
        lines = "\n".join(f"Photo: {url}" for url in urls)
    else:
        lines = "Photo: no attachment URL on the triggering message."
    return f"{(note or '').rstrip()}\n{lines}"


def _clear_assignee(conversation_id: int) -> bool:
    if not conversation_id:
        return False
    try:
        return bool(unassign_agent(conversation_id))
    except Exception as exc:
        logger.warning("Could not unassign conversation %s: %s", conversation_id, exc)
        return False


def _email(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("email") or "").strip()
    return str(getattr(user, "email", "") or "").strip()


def _name(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("full_name") or user.get("name") or user.get("email") or "Agent")
    return str(
        getattr(user, "full_name", None)
        or getattr(user, "name", None)
        or getattr(user, "email", None)
        or "Agent"
    )


def handover_without_specialist(
    conversation_id: int,
    *,
    reason: str,
    note: str,
    customer_name: str = "",
    customer_phone: str = "",
    intent: str = "",
    location: str = "",
    property_type: str = "",
    budget: str = "",
    conversation_summary: str = "",
    cw_link: str = "",
    inbox_id: int = 1,
    service: Optional[LeadHandoverService] = None,
    assignees: Optional[List[Any]] = None,
    photo_urls: Optional[List[str]] = None,
    skip_admin_alert: bool = False,
) -> Dict[str, Any]:
    """Assign general employees, or alert admins and clear the Chatwoot assignee."""
    service = service or LeadHandoverService()
    note = with_photo_links(note, photo_urls)
    if skip_admin_alert:
        body = (
            f"{note}\nPhoto handover is already in place. Duplicate admin alert skipped."
        ).strip()
        if conversation_id:
            try:
                service.send_private_note_func(conversation_id, body)
            except Exception as exc:
                logger.warning("Could not post duplicate photo note: %s", exc)
        logger.info("photo handover duplicate admin alert skipped conversation_id=%s", conversation_id)
        return {
            "assignment_verified": False,
            "assigned_agents": [],
            "admin_alert": False,
            "alert_skipped": True,
            "unassigned": False,
            "reason": reason,
        }
    lookup_error = None
    if assignees is None:
        pool = resolve_general_pool()
        chosen = list(pool.get("users") or [])
        lookup_error = pool.get("error")
    else:
        chosen = list(assignees)
    assigned = []
    for user in chosen:
        email = _email(user)
        if not email or not conversation_id:
            continue
        if service._assign_verified(conversation_id, {"email": email, "name": _name(user)}):
            assigned.append({"email": email, "name": _name(user)})

    if assigned:
        names = ", ".join(item["name"] for item in assigned)
        body = f"{note}\nAssigned to {names}.".strip()
        if conversation_id:
            try:
                service.send_private_note_func(conversation_id, body)
            except Exception as exc:
                logger.warning("Could not post assignment note: %s", exc)
            try:
                service.update_status_func(conversation_id, "open")
            except Exception as exc:
                logger.warning("Could not leave conversation open: %s", exc)
        return {
            "assignment_verified": True,
            "assigned_agents": assigned,
            "admin_alert": False,
            "unassigned": False,
            "reason": reason,
        }

    cleared = _clear_assignee(conversation_id)
    if lookup_error:
        lead = f"General pool lookup failed ({lookup_error})."
    elif not chosen:
        lead = NO_GENERAL_ASSIGNEE
    else:
        names = ", ".join(_name(user) for user in chosen)
        lead = (
            f"General pool members were found ({names}) but Chatwoot did not "
            "accept the assignment."
        )
    tail = UNASSIGNED_OK if cleared else UNASSIGNED_FAILED
    body = f"{note}\n{lead} {tail}".strip()
    if conversation_id:
        try:
            service.send_private_note_func(conversation_id, body)
        except Exception as exc:
            logger.warning("Could not post unassigned handover note: %s", exc)
    alert = {}
    try:
        alert = service._alert_admins_no_specialist(
            conversation_id=conversation_id,
            reason=reason,
            score=0,
            db=None,
            customer_name=customer_name,
            customer_phone=customer_phone or "no phone",
            intent=intent or "TENANT",
            location=location or "Not Specified",
            property_type=property_type or "General Inquiry",
            budget=budget or "Not Specified",
            conversation_summary=conversation_summary or note,
            cw_link=cw_link,
            inbox_id=inbox_id,
            template_phone_number_id="",
        )
    except Exception as exc:
        logger.warning("Admin alert failed for %s: %s", reason, exc)
        alert = {"error": str(exc)}
    if conversation_id:
        try:
            service.update_status_func(conversation_id, "open")
        except Exception as exc:
            logger.warning("Could not leave conversation open: %s", exc)
    return {
        "assignment_verified": False,
        "assigned_agents": [],
        "admin_alert": True,
        "unassigned": cleared,
        "reason": reason,
        "alert": alert,
    }

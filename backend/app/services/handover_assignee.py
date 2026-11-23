"""Shared assignee step for photo no-match and undeliverable sends.

Both callers use ``resolve_general_handover_assignees``. An empty result keeps
the existing admin-alert path and leaves the conversation open and unassigned.
"""

import logging
from typing import Any, Dict, List, Optional

from app.services.general_assignee import resolve_general_handover_assignees
from app.services.lead_handover import LeadHandoverService

logger = logging.getLogger(__name__)

NO_GENERAL_ASSIGNEE = "No general assignee was found."


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
) -> Dict[str, Any]:
    """Assign general employees, or alert admins and leave the thread unassigned."""
    service = service or LeadHandoverService()
    chosen = list(assignees) if assignees is not None else list(resolve_general_handover_assignees() or [])
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

    body = f"{note}\n{NO_GENERAL_ASSIGNEE} The conversation stays open and unassigned.".strip()
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
        "unassigned": True,
        "reason": reason,
        "alert": alert,
    }

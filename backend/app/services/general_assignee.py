"""General Pool assignees for photo no-match and undeliverable handovers.

Nick, 24 Nov 2026: an employee or agent with no location tags and no property
type tags is in the general pool. That is the dashboard label at
``property-dashboard/src/pages/UsersManagement.jsx`` (empty
``assigned_locations`` and empty ``assigned_property_types``).

Legacy ``specialization_*`` columns are not a second tag set in live routing.
``User.specialization_locations`` and ``User.specialization_property_types``
are properties that read and write ``assigned_*`` (``models.py``). The scorer
fallback in ``lead_handover.py`` therefore sees the same arrays, and dict
agents do not consult ``specialization_*`` at all. A user the dashboard calls
General Pool is not specialized. This resolver ignores the legacy columns.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import func, or_

from app.db.models import SessionLocal, User

logger = logging.getLogger(__name__)

_POOL_ROLES = ("employee", "agent")


def _is_empty_tag_list(value: Any) -> bool:
    """NULL and an empty array are both untagged. A non-empty list is a tag."""
    if value is None:
        return True
    try:
        return len(value) == 0
    except TypeError:
        return False


def is_general_pool_member(user: Any) -> bool:
    """True for an active, approved agent or employee with no assigned tags.

    ``receive_lead_handovers`` must be true. Specialist scoring does not filter
    on that column; this pool does, because a handover assignment is a lead
    handover. Legacy ``specialization_*`` values are not read.
    """
    if user is None:
        return False
    if getattr(user, "is_active", None) is not True:
        return False
    if getattr(user, "is_approved", None) is not True:
        return False
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role not in _POOL_ROLES:
        return False
    if getattr(user, "receive_lead_handovers", None) is not True:
        return False
    if not _is_empty_tag_list(getattr(user, "assigned_locations", None)):
        return False
    if not _is_empty_tag_list(getattr(user, "assigned_property_types", None)):
        return False
    return True


def _untagged(column):
    """SQL for NULL or empty Postgres text arrays."""
    return or_(column.is_(None), func.coalesce(func.cardinality(column), 0) == 0)


def general_pool_filters():
    return (
        User.is_active.is_(True),
        User.is_approved.is_(True),
        func.lower(User.role).in_(_POOL_ROLES),
        User.receive_lead_handovers.is_(True),
        _untagged(User.assigned_locations),
        _untagged(User.assigned_property_types),
    )


def general_pool_query(db):
    return db.query(User).filter(*general_pool_filters())


def resolve_general_pool(db: Optional[Any] = None) -> dict:
    """Return ``{"users": [...], "error": None}``. ``error`` is set when the query fails.

    A failed lookup is not the same as an empty pool. Callers must not tell
    agents that nobody matched when the database query itself failed.
    """
    own_session = db is None
    if own_session:
        try:
            db = SessionLocal()
        except Exception as exc:
            logger.warning("General pool lookup could not open a session: %s", exc)
            return {"users": [], "error": str(exc)}
    try:
        rows = general_pool_query(db).all()
    except Exception as exc:
        logger.warning("General pool lookup failed: %s", exc)
        return {"users": [], "error": str(exc)}
    finally:
        if own_session and db is not None:
            try:
                db.close()
            except Exception:
                pass
    return {"users": [row for row in rows if is_general_pool_member(row)], "error": None}


def resolve_general_handover_assignees(db: Optional[Any] = None) -> List[Any]:
    """Active approved general-pool agents and employees. Empty if nobody matches."""
    return list(resolve_general_pool(db).get("users") or [])

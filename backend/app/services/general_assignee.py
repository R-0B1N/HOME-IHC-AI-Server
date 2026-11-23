"""General-handover assignee lookup.

Nick has not yet named the column that marks a general employee. Until that
field exists, this resolver returns nobody. Callers then alert admins, leave
the conversation open and unassigned, and still apply labels.

Do not treat ``receive_lead_handovers`` or ``role == "employee"`` as that flag,
and do not add a column here.
"""

from typing import Any, List, Optional


def resolve_general_handover_assignees(db: Optional[Any] = None) -> List[Any]:
    """Employees marked general. No such flag exists yet, so this returns []."""
    return []

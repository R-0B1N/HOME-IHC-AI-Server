"""General Pool membership for photo no-match and 131026 assignment."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import User
from app.services.general_assignee import (
    general_pool_filters,
    is_general_pool_member,
    resolve_general_handover_assignees,
)
from app.services.handover_assignee import handover_without_specialist


def _member(**overrides):
    base = dict(
        is_active=True,
        is_approved=True,
        role="employee",
        receive_lead_handovers=True,
        assigned_locations=[],
        assigned_property_types=[],
        full_name="Pool Member",
        email="pool@example.com",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class GeneralPoolMembershipTests(unittest.TestCase):
    def test_matching_employee_and_agent_are_members(self):
        self.assertTrue(is_general_pool_member(_member(role="employee")))
        self.assertTrue(is_general_pool_member(_member(role="agent", full_name="Agent Pool")))

    def test_inactive_unapproved_wrong_role_and_handover_opt_out_are_excluded(self):
        self.assertFalse(is_general_pool_member(_member(is_active=False)))
        self.assertFalse(is_general_pool_member(_member(is_approved=False)))
        self.assertFalse(is_general_pool_member(_member(role="admin")))
        self.assertFalse(is_general_pool_member(_member(role="viewer")))
        self.assertTrue(is_general_pool_member(_member(role="Employee")))
        self.assertFalse(is_general_pool_member(_member(receive_lead_handovers=False)))
        self.assertFalse(is_general_pool_member(_member(receive_lead_handovers=None)))

    def test_tagged_users_are_excluded(self):
        self.assertFalse(is_general_pool_member(_member(assigned_locations=["Bentong"])))
        self.assertFalse(is_general_pool_member(_member(assigned_property_types=["Rental"])))

    def test_null_and_empty_arrays_are_both_untagged(self):
        self.assertTrue(is_general_pool_member(_member(
            assigned_locations=None,
            assigned_property_types=None,
        )))
        self.assertTrue(is_general_pool_member(_member(
            assigned_locations=[],
            assigned_property_types=[],
        )))

    def test_legacy_arrays_are_ignored_when_assigned_tags_are_empty(self):
        """Scorer fallback does not see a distinct legacy column on User.

        models.py aliases specialization_* to assigned_*. A plain object that
        carries a different specialization list is still General Pool when the
        assigned arrays are empty, matching the dashboard label.
        """
        user = _member(
            assigned_locations=[],
            assigned_property_types=None,
            specialization_locations=["Bentong"],
            specialization_property_types=["Rental"],
        )
        self.assertTrue(is_general_pool_member(user))

        orm = User(
            username="pool",
            email="pool-orm@example.com",
            hashed_password="x",
            role="employee",
            is_active=True,
            is_approved=True,
            receive_lead_handovers=True,
            assigned_locations=[],
            assigned_property_types=[],
        )
        self.assertEqual(list(orm.specialization_locations), [])
        self.assertTrue(is_general_pool_member(orm))
        orm.specialization_locations = ["Raub"]
        self.assertEqual(orm.assigned_locations, ["Raub"])
        self.assertFalse(is_general_pool_member(orm))

    def test_query_filters_null_or_empty_assigned_arrays_only(self):
        statement = select(User).where(*general_pool_filters())
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("assigned_locations", sql)
        self.assertIn("assigned_property_types", sql)
        self.assertIn("cardinality", sql)
        self.assertIn("is_active", sql)
        self.assertIn("is_approved", sql)
        self.assertIn("receive_lead_handovers", sql)
        self.assertIn("lower", sql)
        self.assertNotIn("specialization_locations", sql)
        self.assertNotIn("specialization_property_types", sql)

    def test_resolver_returns_only_members_from_the_query(self):
        kept = _member(full_name="Kept")
        tagged = _member(full_name="Tagged", assigned_locations=["KL"])
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kept, tagged]
        found = resolve_general_handover_assignees(db)
        self.assertEqual([row.full_name for row in found], ["Kept"])
        db.close.assert_not_called()

    def test_empty_pool_falls_back_to_admin_alert_and_note(self):
        notes = []
        templates = []

        def _note(_cid, content):
            notes.append(content)

        def _template(**kwargs):
            templates.append(kwargs.get("template_name"))
            return {"messages": [{"id": "wamid.1"}]}

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        with patch("app.services.general_assignee.SessionLocal", return_value=db), \
             patch("app.services.handover_assignee.unassign_agent", return_value=True) as unassign, \
             patch("app.services.lead_handover.send_private_note", side_effect=_note), \
             patch("app.services.lead_handover.send_whatsapp_template", side_effect=_template), \
             patch("app.services.lead_handover.assign_agent") as assign, \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=9), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            result = handover_without_specialist(
                453,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent.",
                inbox_id=4,
                photo_urls=["https://inbox.example/rails/active_storage/blobs/photo.jpg"],
            )
        self.assertFalse(result["assignment_verified"])
        self.assertTrue(result["admin_alert"])
        self.assertTrue(result["unassigned"])
        self.assertTrue(any("No general assignee was found" in note for note in notes))
        self.assertTrue(any("is unassigned" in note for note in notes))
        self.assertTrue(any("Photo: https://inbox.example/rails/active_storage/blobs/photo.jpg" in note for note in notes))
        self.assertTrue(templates)
        assign.assert_not_called()
        unassign.assert_called_once_with(453)
        db.close.assert_called()

    def test_unassign_failure_does_not_claim_the_conversation_was_cleared(self):
        notes = []

        def _note(_cid, content):
            notes.append(content)

        with patch("app.services.handover_assignee.resolve_general_pool", return_value={"users": [], "error": None}), \
             patch("app.services.handover_assignee.unassign_agent", return_value=False), \
             patch("app.services.lead_handover.send_private_note", side_effect=_note), \
             patch("app.services.lead_handover.send_whatsapp_template", return_value={"messages": [{"id": "1"}]}), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            result = handover_without_specialist(
                453,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent.",
                photo_urls=[],
            )
        self.assertFalse(result["unassigned"])
        self.assertTrue(any("Unassign failed" in note for note in notes))
        self.assertTrue(any("Photo: no attachment URL" in note for note in notes))
        self.assertFalse(any("is unassigned" in note for note in notes))

    def test_pool_member_assignment_replaces_the_previous_agent(self):
        notes = []
        with patch("app.services.handover_assignee.unassign_agent") as unassign, \
             patch("app.services.lead_handover.send_private_note", side_effect=lambda _cid, content: notes.append(content)), \
             patch("app.services.lead_handover.send_whatsapp_template") as template, \
             patch("app.services.lead_handover.assign_agent", return_value=True) as assign, \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=44), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            result = handover_without_specialist(
                453,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent.",
                assignees=[{"email": "pool@example.com", "full_name": "Pool Agent"}],
                photo_urls=["https://inbox.example/photo.jpg"],
            )
        self.assertTrue(result["assignment_verified"])
        assign.assert_called_once_with(453, 44)
        unassign.assert_not_called()
        template.assert_not_called()
        self.assertTrue(any("Assigned to Pool Agent" in note for note in notes))
        self.assertTrue(any("Photo: https://inbox.example/photo.jpg" in note for note in notes))


if __name__ == "__main__":
    unittest.main()

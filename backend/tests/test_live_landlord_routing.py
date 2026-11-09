"""
Unit and live orchestration tests for the landlord category.
Covers:
1. Live state machine for explicit landlord statements ("I want to rent out my shop", "出租", "nak sewakan").
2. "is it for rent?" stays ambiguous and does NOT become landlord or seller.
3. Landlord vs seller vs tenant disambiguation.
4. Chatwoot label merging preserving unmanaged labels (human-handover, vip) and writing landlord.
5. Dashboard / API customer update and serialization accepting landlord.
6. Weekly report filing placing landlord in the Landlord tab with rent in the budget column.
7. Hot lead qualification and specialization routing (rental specialist compatible; sale-only specialist incompatible).
"""

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db.models import Customer
from app.services.agent_logic import process_persona_state_machine
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.customer_classification import (
    apply_live_role_evidence,
    canonical_category_name,
    is_explicit_landlord,
    live_hot_lead_qualified,
)
from app.services.lead_handover import LeadHandoverService, intent_compatible
from app.services.reporting import BuyerReportGenerator
from app.api.customers import serialize_customer, CustomerUpdate, update_customer


@contextmanager
def _dummy_lock(*args, **kwargs):
    yield


class LiveLandlordTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
            patch("app.services.agent_logic.find_matching_property", return_value=None),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.generate_conversational_response", return_value={"response": "Noted."}),
            patch("app.services.agent_logic.classify_turn_intent", return_value="general"),
            patch("app.services.conversation_processor.SessionManager.lock_session", side_effect=_dummy_lock),
            patch("app.services.conversation_processor.SessionManager.get_session", return_value={}),
            patch("app.services.conversation_processor.SessionManager.save_session"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_explicit_landlord_turn_live_state_machine(self):
        session = {}
        res = process_persona_state_machine(
            phone_number="+60129990001",
            raw_text="I want to rent out my shop in Bentong, asking rent is RM 2500 per month",
            session=session,
            contact_name="Mr. Landlord",
        )
        up_sess = res.get("updated_session", {})
        collected = up_sess.get("collected_data", {})
        self.assertEqual(collected.get("customer_category"), "landlord")
        self.assertEqual(up_sess.get("current_agent"), "LANDLORD")
        self.assertEqual(up_sess.get("landlord_evidence"), "explicit")
        self.assertIn("Bentong", str(collected.get("location")))
        self.assertEqual(collected.get("property_type"), "Shop")
        self.assertIn("2500", str(collected.get("asking_rent") or collected.get("expected_rental")))

    def test_chinese_and_malay_landlord_statements(self):
        s_zh = {}
        process_persona_state_machine(
            phone_number="+60129990002",
            raw_text="我想出租文冬的店面，月租RM 1800",
            session=s_zh,
            contact_name="Tan",
        )
        self.assertEqual(s_zh.get("collected_data", {}).get("customer_category"), "landlord")
        self.assertEqual(s_zh.get("current_agent"), "LANDLORD")

        s_ms = {}
        process_persona_state_machine(
            phone_number="+60129990003",
            raw_text="Saya nak sewakan rumah saya di Raub",
            session=s_ms,
            contact_name="Ahmad",
        )
        self.assertEqual(s_ms.get("collected_data", {}).get("customer_category"), "landlord")
        self.assertEqual(s_ms.get("current_agent"), "LANDLORD")

    def test_listing_question_is_it_for_rent_does_not_become_landlord(self):
        session = {}
        res = process_persona_state_machine(
            phone_number="+60129990004",
            raw_text="is it for rent?",
            session=session,
            contact_name="Inquirer",
        )
        up_sess = res.get("updated_session", {})
        collected = up_sess.get("collected_data", {})
        self.assertNotEqual(collected.get("customer_category"), "landlord")
        self.assertNotEqual(up_sess.get("current_agent"), "LANDLORD")
        self.assertFalse(is_explicit_landlord("is it for rent?"))
        self.assertFalse(is_explicit_landlord("shop is it for rent?"))
        self.assertFalse(is_explicit_landlord("ada kedai untuk sewa?"))

    def test_landlord_vs_seller_vs_tenant_disambiguation(self):
        s_landlord = {}
        apply_live_role_evidence(s_landlord, s_landlord.setdefault("collected_data", {}), "I want to rent out my shop")
        self.assertEqual(s_landlord["collected_data"]["customer_category"], "landlord")

        s_seller = {}
        apply_live_role_evidence(s_seller, s_seller.setdefault("collected_data", {}), "I want to sell my land")
        self.assertEqual(s_seller["collected_data"]["customer_category"], "seller")

        s_tenant = {}
        apply_live_role_evidence(s_tenant, s_tenant.setdefault("collected_data", {}), "I want to rent a house")
        self.assertIn(s_tenant["collected_data"]["customer_category"], {"renter", "tenant"})
        self.assertEqual(canonical_category_name(s_tenant["collected_data"]["customer_category"]), "tenant")
        self.assertNotEqual(s_tenant["collected_data"]["customer_category"], "landlord")

    def test_label_merge_in_persist_state_and_labels(self):
        mock_db_customer = MagicMock()
        mock_db_customer.id = "60128888888"
        mock_db_customer.metadata_json = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_db_customer

        with patch("app.services.conversation_processor.get_conversation_details", return_value={"labels": ["human-handover", "vip", "buyer"]}), \
             patch("app.services.conversation_processor.apply_label") as mock_apply, \
             patch("app.services.conversation_processor.set_priority"):
            processor = ConversationQueueProcessor(session_factory=lambda: mock_db)
            processor.persist_state_and_labels(
                conversation_id=909,
                customer=mock_db_customer,
                lead_temp="hot",
                handover_initiated=True,
                role="customer",
                intent="landlord",
                assignee_email=None,
            )
            mock_apply.assert_called_once()
            applied = mock_apply.call_args[0][1]
            self.assertIn("landlord", applied)
            self.assertIn("human-handover", applied)
            self.assertIn("vip", applied)
            self.assertIn("hot", applied)
            self.assertNotIn("buyer", applied)

    def test_dashboard_and_api_accepts_landlord(self):
        c = Customer(
            id="60197771234",
            contact_name="Dato Tan",
            metadata_json={"intent_category": "landlord", "intention_tag": "Hot"}
        )
        serialized = serialize_customer(c)
        self.assertEqual(serialized["intent_category"], "landlord")
        self.assertEqual(serialized["intention_tag"], "Hot")

        # Test update_customer endpoint with landlord
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = c

        update_payload = CustomerUpdate(
            intent_category="landlord",
            intention_tag="Warm",
        )
        updated_res = update_customer("60197771234", update_payload, db=mock_db)
        self.assertEqual(updated_res["intent_category"], "landlord")
        self.assertEqual(updated_res["intention_tag"], "Warm")
        self.assertEqual(c.metadata_json.get("customer_category"), "landlord")
        self.assertEqual(c.metadata_json.get("intent_category"), "landlord")

    def test_weekly_report_filing_for_landlord(self):
        c1 = Customer(
            id="60181112222",
            contact_name="Madam Ong",
            metadata_json={
                "intent_category": "landlord",
                "location": "Bentong",
                "property_type": "Shop",
                "asking_rent": "RM 3,500",
                "lead_temp": "hot",
            }
        )
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [c1]

        grouped = BuyerReportGenerator.rows_by_category(mock_session)
        self.assertEqual(len(grouped["landlord"]), 1)
        self.assertEqual(len(grouped["buyer"]), 0)
        self.assertEqual(len(grouped["tenant"]), 0)
        self.assertEqual(len(grouped["seller"]), 0)

        row = grouped["landlord"][0]
        self.assertEqual(row[1], "Madam Ong")
        self.assertEqual(row[4], "Landlord")
        self.assertEqual(row[5], "Hot")
        self.assertEqual(row[6], "Bentong")
        self.assertEqual(row[7], "Shop")
        self.assertEqual(row[8], "RM 3,500")

    def test_hot_lead_qualification_for_landlord(self):
        collected_complete = {
            "landlord_evidence": "explicit",
            "location": "Bentong",
            "property_type": "Shop",
            "asking_rent": "RM 2,000",
            "asking_rent_grounded": True,
        }
        self.assertTrue(live_hot_lead_qualified("landlord", collected_complete, "RM 2,000"))

        collected_missing_rent = {
            "landlord_evidence": "explicit",
            "location": "Bentong",
            "property_type": "Shop",
        }
        self.assertFalse(live_hot_lead_qualified("landlord", collected_missing_rent, "hello"))

    def test_landlord_specialist_routing_and_compatibility(self):
        # Rental agent is compatible
        rental_agent = {"name": "Ah Tat", "assigned_locations": ["Bentong"], "assigned_property_types": ["Rental"]}
        self.assertTrue(intent_compatible("landlord", rental_agent))

        # Sale-only agent is NOT compatible
        durian_agent = {"name": "Marcus", "assigned_locations": ["Bentong"], "assigned_property_types": ["Durian Land"]}
        self.assertFalse(intent_compatible("landlord", durian_agent))

        # Handover routing with rental agent
        service = LeadHandoverService(
            get_active_agents_func=lambda: [
                {
                    "name": "Ah Tat",
                    "email": "ahtat@example.com",
                    "phone_number": "+60129663589",
                    "assigned_locations": ["Bentong"],
                    "assigned_property_types": ["Rental"],
                }
            ],
            session_factory=lambda: MagicMock(),
            send_template_func=MagicMock(return_value={"id": 1}),
            send_contact_func=MagicMock(),
            send_private_note_func=MagicMock(),
            apply_label_func=MagicMock(),
            assign_agent_func=MagicMock(return_value=True),
            get_agent_id_func=MagicMock(return_value=12),
        )
        service.get_admin_recipients = MagicMock(return_value=[])
        service._assign_verified = MagicMock(return_value=True)

        res = service.dispatch(
            conversation_id=888,
            customer_name="Mr. Landlord",
            customer_phone="+60129990001",
            intent="landlord",
            location="Bentong",
            property_type="Shop",
            budget="RM 2,500",
            raw_inquiry_text="I want to rent out my shop in Bentong",
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["assignment_verified"])
        self.assertEqual(res["assigned_agents"][0]["name"], "Ah Tat")

        # When only sale agent is available -> below_threshold / intent_incompatible, no assignment
        service_sale_only = LeadHandoverService(
            get_active_agents_func=lambda: [
                {
                    "name": "Marcus",
                    "email": "marcus@example.com",
                    "phone_number": "+60129999999",
                    "assigned_locations": ["Bentong"],
                    "assigned_property_types": ["Durian Land"],
                }
            ],
            session_factory=lambda: MagicMock(),
            send_template_func=MagicMock(),
            send_contact_func=MagicMock(),
            send_private_note_func=MagicMock(),
            apply_label_func=MagicMock(),
        )
        service_sale_only.get_admin_recipients = MagicMock(return_value=[])

        res_incompatible = service_sale_only.dispatch(
            conversation_id=889,
            customer_name="Mr. Landlord",
            customer_phone="+60129990001",
            intent="landlord",
            location="Bentong",
            property_type="Shop",
            budget="RM 2,500",
            raw_inquiry_text="I want to rent out my shop in Bentong",
        )
        self.assertFalse(res_incompatible["assignment_verified"])
        self.assertEqual(res_incompatible["assigned_agents"], [])


if __name__ == "__main__":
    unittest.main()

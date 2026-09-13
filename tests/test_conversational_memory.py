import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import datetime

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.llm import extract_multi_intent_context
from app.services.agent_logic import MultiIntentMemoryTracker
from app.api.customers import serialize_customer


class TestConversationalMemory(unittest.TestCase):

    def test_extract_multi_intent_single_inquiry(self):
        """Verify deterministic parsing of single commercial inquiry."""
        text = "Saya cari shop lot di Bentong budget around RM 1.2 mil dengan 100 amp power supply"
        ctx = extract_multi_intent_context(text)
        
        self.assertIn("commercial", ctx["categories"])
        self.assertIn("shop lot", ctx["property_types"])
        self.assertIn("Bentong", ctx["locations"])
        self.assertEqual(ctx["budget_myr"], 1200000.0)
        self.assertEqual(ctx["power_amp"], 100)
        self.assertEqual(ctx["role"], "buyer")
        print("✅ test_extract_multi_intent_single_inquiry passed")

    def test_intent_switch_priority_and_retained_memory(self):
        """
        Verify that active inquiry takes 1st priority while prior inquiries
        are preserved in retained background memory with an intent pivot timeline event.
        """
        session = {}
        
        # 1. Initial inquiry: Commercial Shop Lot
        msg1 = "Looking for a commercial shop lot in Bentong, budget around RM 1.2M"
        session = MultiIntentMemoryTracker.update_session_memory(session, msg1)
        
        req = session["requirements_profile"]
        self.assertEqual(req["active_inquiry"]["category"], "commercial")
        self.assertEqual(req["target_budget_myr"], 1200000.0)
        self.assertIn("Bentong", req["target_locations"])
        self.assertEqual(len(req["retained_inquiries"]), 0)
        
        # 2. Intent switch: Residential House / Villa
        msg2 = "Actually now I prefer a residential bungalow house in Karak with budget 800k"
        session = MultiIntentMemoryTracker.update_session_memory(session, msg2)
        
        req2 = session["requirements_profile"]
        # Active inquiry MUST now be 1st priority: residential
        self.assertEqual(req2["active_inquiry"]["category"], "residential")
        self.assertEqual(req2["target_budget_myr"], 800000.0)
        self.assertIn("Karak", req2["target_locations"])
        
        # Prior commercial inquiry MUST be retained in background memory
        self.assertEqual(len(req2["retained_inquiries"]), 1)
        self.assertEqual(req2["retained_inquiries"][0]["category"], "commercial")
        self.assertEqual(req2["retained_inquiries"][0]["target_budget_myr"], 1200000.0)
        
        # Intent progression timeline MUST contain the pivot event
        progression = session.get("intent_progression", [])
        self.assertGreaterEqual(len(progression), 2)
        self.assertEqual(progression[0]["event_type"], "intent_pivot")
        self.assertIn("Commercial -> Residential", progression[0]["title"])
        print("✅ test_intent_switch_priority_and_retained_memory passed")

    def test_intelligent_hybrid_suggestion_opportunity(self):
        """
        Verify detection of dual-purpose interest (commercial + residential)
        which triggers shop-house (rumah kedai) suggestion opportunities.
        """
        session = {}
        # User expresses dual purpose in a single message
        dual_msg = "I need a ground floor shop lot for my cafe business but I also want upstairs residential rooms for my family"
        session = MultiIntentMemoryTracker.update_session_memory(session, dual_msg)
        
        req = session["requirements_profile"]
        self.assertTrue(req["hybrid_opportunity"])
        self.assertIn("rumah kedai", req["preferred_property_types"])
        
        # Progression node must flag hybrid opportunity
        progression = session.get("intent_progression", [])
        self.assertTrue(progression[0].get("hybrid_opportunity"))
        print("✅ test_intelligent_hybrid_suggestion_opportunity passed")

    def test_category_isolated_budget_contradictions(self):
        """
        Verify budget contradiction isolation: A commercial budget of RM 1.5M
        and a residential budget of RM 500k are tracked distinctly without overwriting.
        """
        session = {}
        # Message 1: Commercial with high budget
        session = MultiIntentMemoryTracker.update_session_memory(session, "Looking for factory or commercial lot RM 1.5 mil in Bentong")
        
        # Message 2: Residential with lower budget
        session = MultiIntentMemoryTracker.update_session_memory(session, "Also looking for a small residential house budget RM 500k")
        
        req = session["requirements_profile"]
        self.assertEqual(req["active_inquiry"]["target_budget_myr"], 500000.0)
        self.assertEqual(req["retained_inquiries"][0]["target_budget_myr"], 1500000.0)
        print("✅ test_category_isolated_budget_contradictions passed")

    def test_changing_locations(self):
        """Verify dynamic tracking of changing target locations."""
        session = {}
        session = MultiIntentMemoryTracker.update_session_memory(session, "Any durian orchard in Raub?")
        req1 = session["requirements_profile"]
        self.assertIn("Raub", req1["target_locations"])
        
        session = MultiIntentMemoryTracker.update_session_memory(session, "What about Bentong or Karak?")
        req2 = session["requirements_profile"]
        self.assertIn("Bentong", req2["target_locations"])
        self.assertIn("Karak", req2["target_locations"])
        print("✅ test_changing_locations passed")

    def test_role_switching_buyer_to_seller(self):
        """Verify role switching from prospective buyer to landlord/seller."""
        session = {}
        session = MultiIntentMemoryTracker.update_session_memory(session, "I want to buy agricultural land")
        self.assertEqual(session["requirements_profile"]["active_inquiry"]["role"], "buyer")
        
        session = MultiIntentMemoryTracker.update_session_memory(session, "Actually I also want to sell my shop lot in Bentong town")
        self.assertEqual(session["requirements_profile"]["active_inquiry"]["role"], "seller")
        
        progression = session.get("intent_progression", [])
        self.assertTrue(any("Role Switch" in node["title"] or "seller" in node["description"].lower() for node in progression))
        print("✅ test_role_switching_buyer_to_seller passed")

    def test_tnb_power_amp_requirement_tracking(self):
        """Verify electrical power requirement extraction and preservation."""
        session = {}
        session = MultiIntentMemoryTracker.update_session_memory(session, "Need industrial land in Bentong with at least 200 amp 3 phase TNB power")
        req = session["requirements_profile"]
        self.assertEqual(req["power_requirements_amp"], 200)
        print("✅ test_tnb_power_amp_requirement_tracking passed")

    def test_customer_api_serialization(self):
        """Verify serialize_customer hydrates all modal-required fields with graceful defaults."""
        mock_customer = MagicMock()
        mock_customer.id = "+60123456789"
        mock_customer.contact_name = "Dato Sri Tan"
        mock_customer.email = "tan@example.com"
        mock_customer.country = "Malaysia"
        mock_customer.conversation_ids = [42]
        mock_customer.last_interaction = datetime.datetime(2026, 9, 12, 14, 30)
        mock_customer.metadata_json = {
            "inbox_id": 1,
            "intention_tag": "Hot",
            "intent_category": "commercial",
            "requirements_profile": {
                "active_inquiry": {"category": "commercial", "property_type": "shop lot", "target_budget_myr": 1200000.0},
                "retained_inquiries": [{"category": "residential", "property_type": "bungalow", "target_budget_myr": 800000.0}],
                "target_locations": ["Bentong"],
                "preferred_property_types": ["shop lot", "rumah kedai"],
                "target_budget_myr": 1200000.0,
                "target_budget_formatted": "RM 1,200,000",
                "power_requirements_amp": 100,
                "hybrid_opportunity": True
            },
            "intent_progression": [
                {
                    "timestamp": "2026-09-12T14:30:00",
                    "event_type": "intent_pivot",
                    "title": "Inquiry Pivot: Residential -> Commercial",
                    "description": "Primary priority shifted to Commercial shop lot.",
                    "active_priority": "commercial",
                    "hybrid_opportunity": True
                }
            ],
            "presented_properties": [
                {
                    "id": "prop-101",
                    "title": "Bentong Town Center 2-Storey Shop-House",
                    "price_myr": 1150000.0,
                    "city": "Bentong",
                    "property_type_sub": "Rumah Kedai"
                }
            ],
            "viewing_acknowledgement": {
                "status": "Scheduled",
                "form_no": "VA-2026-0912-01",
                "date": "2026-09-14T10:00:00",
                "agent_name": "Nicholas Chong",
                "notes": "Boundary inspection requested"
            }
        }

        serialized = serialize_customer(mock_customer)
        
        # Particulars
        self.assertEqual(serialized["id"], "+60123456789")
        self.assertEqual(serialized["contact_name"], "Dato Sri Tan")
        self.assertEqual(serialized["email"], "tan@example.com")
        self.assertEqual(serialized["country"], "Malaysia")
        self.assertEqual(serialized["intention_tag"], "Hot")
        self.assertEqual(serialized["intent_category"], "commercial")
        
        # Requirements Profile
        self.assertEqual(serialized["requirements_profile"]["target_budget_myr"], 1200000.0)
        self.assertEqual(serialized["requirements_profile"]["power_requirements_amp"], 100)
        self.assertTrue(serialized["requirements_profile"]["hybrid_opportunity"])
        
        # Timeline & Properties
        self.assertEqual(len(serialized["intent_progression"]), 1)
        self.assertEqual(serialized["intent_progression"][0]["event_type"], "intent_pivot")
        self.assertEqual(len(serialized["presented_properties"]), 1)
        self.assertEqual(serialized["presented_properties"][0]["title"], "Bentong Town Center 2-Storey Shop-House")
        
        # Viewing Acknowledgement
        self.assertEqual(serialized["viewing_acknowledgement"]["status"], "Scheduled")
        self.assertEqual(serialized["viewing_acknowledgement"]["form_no"], "VA-2026-0912-01")
        print("✅ test_customer_api_serialization passed")

    def test_customer_persistence_in_db(self):
        """Verify MultiIntentMemoryTracker.persist_customer_memory updates Customer metadata_json."""
        mock_customer = MagicMock()
        mock_customer.metadata_json = {}
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_customer
        
        session = {
            "requirements_profile": {"active_inquiry": {"category": "agricultural"}, "power_requirements_amp": 60},
            "intent_progression": [{"event_type": "inquiry_logged", "title": "Agricultural Inquiry"}],
            "presented_properties": [{"id": "prop-55", "title": "Bentong Durian Farm"}],
            "viewing_acknowledgement": {"status": "Acknowledged"},
            "current_agent": "Agricultural",
            "lead_temp": "Hot"
        }
        
        with patch("app.services.agent_logic.SessionLocal", return_value=mock_db):
            MultiIntentMemoryTracker.persist_customer_memory("+60199998888", session)
            
            mock_db.commit.assert_called_once()
            meta = mock_customer.metadata_json
            self.assertEqual(meta["intent_category"], "agricultural")
            self.assertEqual(meta["intention_tag"], "Hot")
            self.assertEqual(meta["viewing_acknowledgement"]["status"], "Acknowledged")
            self.assertEqual(len(meta["presented_properties"]), 1)
        print("✅ test_customer_persistence_in_db passed")


if __name__ == "__main__":
    unittest.main()

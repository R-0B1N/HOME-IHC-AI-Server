"""
Conv 268 / 269 handover.

Renters and buyers qualify on "my budget", "budget is", and a bare "budget"
plus an amount. A listing price still does not. When a qualified lead matches
nobody on the live roster rules, admins are alerted in private and no
specialist is assigned or named.
"""

import inspect
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.agent_logic import process_persona_state_machine
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.lead_handover import LeadHandoverService
from app.services.role_contract import (
    hot_lead_qualified,
    own_buyer_budget,
    own_rent_budget,
    sanitize_unverified_reply,
)
from app.services.system_prompts import build_system_prompt
import app.services.agent_logic as agent_logic
import app.services.lead_handover as lead_handover
import app.services.llm as llm_service
import app.services.system_prompts as system_prompts

# Budget wording is the audited Conv 268 text. Town, shop, and rent wording
# are the context that investigation measured on those turns. Turn 3 has
# "rental" and no "I want to rent".
CONV268 = (
    "I want to rent a shoplot in Bentong. My budget is RM 1,500 per month.",
    "I want to rent a shoplot in Bentong. Budget is RM 1,500 per month.",
    "Shoplot rental in Bentong, budget RM 1,500 per month. My name is Alex.",
)

CONV238 = (
    "hi",
    "is it still available？",
    "how much is this",
    "this is at bentong",
    "i think is jalan ah peng",
)

PR11_ROSTER = [
    {"name": "Ah Tat", "email": "ahtat@example.com", "phone_number": "+60129663589",
     "assigned_locations": ["Bentong", "Karak"], "assigned_property_types": ["Rental"]},
    {"name": "CyYap", "email": "cy@example.com", "phone_number": "+60110000001",
     "assigned_locations": ["Mentakab"], "assigned_property_types": ["Rental"]},
    {"name": "Gemini", "email": "g@example.com", "phone_number": "+60110000002",
     "assigned_locations": ["Raub"], "assigned_property_types": ["Rental"]},
    {"name": "Ashley", "email": "a@example.com", "phone_number": "+60110000003",
     "assigned_locations": ["Temerloh"], "assigned_property_types": ["Rental"]},
    {"name": "Yap", "email": "y@example.com", "phone_number": "+60110000004",
     "assigned_locations": ["Mentakab"], "assigned_property_types": ["Rental"]},
]

SELLER_LAND = "I want to sell my land in Bentong, asking price RM 500,000."


def _no_db():
    raise RuntimeError("no live roster in this test")


class Conv268BudgetQualification(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
            patch("app.services.agent_logic.find_matching_property", return_value=None),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.generate_conversational_response", return_value={
                "response": "Thanks, I have noted those details.",
                "intent": "general",
                "extracted_data": {},
            }),
            patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def _persona(self, text, session=None):
        return process_persona_state_machine(
            phone_number="+6012780962801",
            raw_text=text,
            session=session if session is not None else {},
            conversation_history="",
            contact_name="Alex",
        )

    def test_conv268_lines_qualify_as_renter_or_tenant_with_own_budget(self):
        for text in CONV268:
            result = self._persona(text)
            collected = result["updated_session"]["collected_data"]
            self.assertIn(collected.get("customer_category"), {"renter", "tenant"}, text)
            self.assertTrue(collected.get("rent_budget_grounded"), text)
            self.assertIn("1,500", collected.get("rent_budget") or "", text)
            self.assertEqual(result.get("handover_reason"), "qualified", text)
            self.assertTrue(hot_lead_qualified(
                collected.get("customer_category"), collected, text
            ), text)

    def test_budget_phrases_qualify_buyers_and_renters_but_not_listing_prices(self):
        self.assertIsNotNone(own_rent_budget("My budget is RM 1,500 per month."))
        self.assertIsNotNone(own_rent_budget("Budget is RM 1,500 per month."))
        self.assertIsNotNone(own_rent_budget("budget RM 1,500 per month"))
        self.assertIsNotNone(own_buyer_budget("My budget is RM 500,000."))
        self.assertIsNotNone(own_buyer_budget("Budget is RM 500,000."))
        self.assertIsNotNone(own_buyer_budget("budget RM 400,000"))
        self.assertIsNotNone(own_rent_budget("rent budget RM 1,200"))
        self.assertIsNotNone(own_rent_budget("租金预算 RM 1,500"))
        self.assertIsNone(own_rent_budget("what's the rent, RM 1,500?"))
        self.assertIsNone(own_rent_budget("is it for rent? how much"))
        self.assertIsNone(own_buyer_budget("what's the price, RM 500,000?"))

        for text in (
            "I want to buy a house in Bentong. My budget is RM 500,000.",
            "I want to buy a house in Bentong. Budget is RM 500,000.",
            "I want to buy a house in Bentong, budget RM 400,000.",
        ):
            result = self._persona(text)
            collected = result["updated_session"]["collected_data"]
            self.assertEqual(collected.get("customer_category"), "buyer", text)
            self.assertTrue(collected.get("buyer_budget_grounded"), text)
            self.assertEqual(result.get("handover_reason"), "qualified", text)

        listing = self._persona("I want to buy the shop in Bentong. What's the price, RM 500,000?")
        listing_data = listing["updated_session"]["collected_data"]
        self.assertFalse(listing_data.get("buyer_budget_grounded"))
        self.assertNotEqual(listing.get("handover_reason"), "qualified")

    def test_missing_budget_and_listing_prices_do_not_qualify(self):
        no_budget = self._persona("I want to rent the shop in Bentong.")
        no_budget_data = no_budget["updated_session"]["collected_data"]
        self.assertEqual(no_budget_data.get("customer_category"), "renter")
        self.assertFalse(no_budget_data.get("rent_budget_grounded"))
        self.assertNotEqual(no_budget.get("handover_reason"), "qualified")

        for text in (
            "is it for rent? how much",
            "what's the rent, RM 1,500?",
            "What's the rent for the shop in Bentong, RM 1,500?",
        ):
            result = self._persona(text)
            collected = result["updated_session"]["collected_data"]
            self.assertFalse(collected.get("rent_budget_grounded"), text)
            self.assertFalse(collected.get("buyer_budget_grounded"), text)
            self.assertNotEqual(result.get("handover_reason"), "qualified", text)

    def test_conv238_shop_lines_stay_unqualified(self):
        session = {}
        history = ""
        for text in CONV238:
            result = process_persona_state_machine(
                phone_number="+60000000238",
                raw_text=text,
                session=session,
                conversation_history=history,
                contact_name="Customer",
                images=["storefront-bytes"] if text == "how much is this" else None,
            )
            session = result["updated_session"]
            collected = session.get("collected_data") or {}
            self.assertFalse(result.get("handover"), text)
            self.assertNotEqual(result.get("handover_reason"), "qualified", text)
            self.assertNotEqual(collected.get("customer_category"), "seller", text)
            self.assertNotIn("Ah Tuck", result.get("response") or "")
            self.assertNotIn("Ah Tat", result.get("response") or "")
            history = f"{history}\nUser: {text}\nAssistant: noted".strip()


class Conv268DispatchAndNoMatch(unittest.TestCase):
    def _service(self, agents, assign_result=True):
        return LeadHandoverService(
            get_active_agents_func=lambda: agents,
            send_template_func=MagicMock(return_value={"messages": [{"id": "1"}]}),
            send_contact_func=MagicMock(),
            send_private_note_func=MagicMock(),
            apply_label_func=MagicMock(),
            set_priority_func=MagicMock(),
            update_status_func=MagicMock(),
            get_or_create_contact_func=MagicMock(return_value=1),
            create_conversation_func=MagicMock(return_value=2),
            get_agent_id_func=lambda email: 21 if assign_result else None,
            assign_agent_func=lambda conversation_id, agent_id: assign_result,
            session_factory=_no_db,
        )

    def _dispatch(self, service, intent, text, property_type="Shop", location="Bentong"):
        return service.dispatch(
            conversation_id=268,
            customer_name="Alex",
            customer_phone="+6012780962801",
            intent=intent,
            location=location,
            property_type=property_type,
            budget="RM 1,500",
            conversation_summary="customer stated their own budget",
            raw_inquiry_text=text,
        )

    def test_pr11_roster_assigns_ah_tat_only_after_verification(self):
        processor = ConversationQueueProcessor(
            redis_client=MagicMock(), session_factory=MagicMock()
        )
        for text in CONV268:
            for intent in ("renter", "tenant"):
                service = self._service(PR11_ROSTER, assign_result=True)
                result = self._dispatch(service, intent, text)
                self.assertEqual(result["status"], "success", text)
                self.assertTrue(result["assignment_verified"], text)
                self.assertTrue(result["public_promise"], text)
                self.assertEqual(result["assigned_agents"][0]["name"], "Ah Tat", text)
                self.assertEqual(
                    processor.verified_specialist_identity(result),
                    ("Ah Tat", "+60129663589"),
                    text,
                )
                service.send_contact_func.assert_called_once()
                self.assertEqual(service.send_contact_func.call_args[1]["contact_name"], "Ah Tat")

                refused = self._service(PR11_ROSTER, assign_result=False)
                failed = self._dispatch(refused, intent, text)
                self.assertEqual(failed["status"], "assignment_failed", text)
                self.assertFalse(failed["assignment_verified"], text)
                self.assertFalse(failed["public_promise"], text)
                self.assertEqual(failed["primary_agent_name"], "", text)
                self.assertEqual(processor.verified_specialist_identity(failed), ("", ""))
                refused.send_contact_func.assert_not_called()

        kept, _temp, reply = processor.gate_public_handover(
            handover_initiated=True,
            assignment_verified=False,
            intent="renter",
            lead_temp="Hot",
            session={"handover": True},
            response_text="Ah Tat will reach you right away.",
            phone_number="+6012780962801",
        )
        self.assertFalse(kept)
        self.assertNotIn("Ah Tat", reply)
        self.assertNotIn("right away", reply.lower())
        self.assertNotIn("Ah Tuck", reply)

        verified_kept, _temp2, verified_reply = processor.gate_public_handover(
            handover_initiated=True,
            assignment_verified=True,
            intent="renter",
            lead_temp="Hot",
            session={"handover": True},
            response_text="I have noted the shoplot budget.",
            phone_number="+6012780962801",
        )
        self.assertTrue(verified_kept)
        self.assertIn("shoplot", verified_reply)

    def test_no_match_alerts_admins_without_naming_a_specialist(self):
        mismatched = [
            {"name": "Commercial Only", "email": "c@example.com", "phone_number": "+60110000021",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
            {"name": "Land Elsewhere", "email": "l@example.com", "phone_number": "+60110000022",
             "assigned_locations": ["Raub"], "assigned_property_types": ["Land / Agriculture"]},
        ]
        cases = (
            ("intent_incompatible", PR11_ROSTER),
            ("below_threshold", mismatched),
        )
        processor = ConversationQueueProcessor(
            redis_client=MagicMock(), session_factory=MagicMock()
        )
        for expected, roster in cases:
            service = self._service(roster)
            result = service.dispatch(
                conversation_id=269,
                customer_name="Seller",
                customer_phone="+601200000269",
                intent="seller",
                location="Bentong",
                property_type="Land",
                budget="RM 500,000",
                conversation_summary="qualified seller in Bentong land",
                raw_inquiry_text=SELLER_LAND,
            )
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["winning_score"], 1)
            self.assertFalse(result["assignment_verified"])
            self.assertFalse(result["public_promise"])
            self.assertEqual(result["assigned_agents"], [])
            self.assertEqual(result["primary_agent_name"], "")
            self.assertTrue(result["admin_only_handover"])
            self.assertEqual(processor.verified_specialist_identity(result), ("", ""))
            self.assertIn("+601165144931", result["routed_to"])
            for banned in ("Ah Tat", "Ah Tuck", "Commercial Only", "Land Elsewhere", "will contact", "right away"):
                self.assertNotIn(banned, result["diagnostic"])
            self.assertIn("No specialist was named", result["diagnostic"])
            self.assertIn("No customer contact was promised", result["diagnostic"])
            self.assertIn("Irene Leong", result["diagnostic"])
            service.send_contact_func.assert_not_called()
            service.send_private_note_func.assert_called_once()
            note = service.send_private_note_func.call_args[0][1]
            self.assertIn("No specialist was named", note)
            self.assertNotIn("will contact", note.lower())
            for call in service.send_template_func.call_args_list:
                blob = " ".join(str(item) for item in call[1]["parameters"])
                self.assertIn("No specialist was named", blob)
                self.assertNotIn("will contact", blob.lower())
                self.assertNotIn("Ah Tat", blob)
                self.assertNotIn("+60129663589", call[1]["to_phone"])
            kept, _temp, reply = processor.gate_public_handover(
                handover_initiated=True,
                assignment_verified=False,
                intent="seller",
                lead_temp="Hot",
                session={"handover": True},
                response_text="A specialist will contact you shortly.",
                phone_number="+601200000269",
            )
            self.assertFalse(kept)
            self.assertNotIn("will contact", reply.lower())
            self.assertNotIn("specialist", reply.lower())

    def test_score1_tie_and_intent_incompatible_do_not_assign(self):
        rental = self._service(PR11_ROSTER)
        incompatible = rental.dispatch(
            conversation_id=264,
            customer_name="Seller",
            customer_phone="+601200000264",
            intent="seller",
            location="Bentong",
            property_type="Land",
            budget="RM 500,000",
            raw_inquiry_text=SELLER_LAND,
        )
        self.assertEqual(incompatible["status"], "intent_incompatible")
        self.assertEqual(incompatible["winning_score"], 1)
        self.assertEqual(incompatible["assigned_agents"], [])
        self.assertFalse(incompatible["assignment_verified"])

        single_hit = self._service([
            {"name": "Commercial Only", "email": "c@example.com", "phone_number": "+60110000021",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
        ])
        score_one = single_hit.dispatch(
            conversation_id=269,
            customer_name="Seller",
            customer_phone="+601200000269",
            intent="seller",
            location="Bentong",
            property_type="Land",
            budget="RM 500,000",
            raw_inquiry_text=SELLER_LAND,
        )
        self.assertEqual(score_one["status"], "below_threshold")
        self.assertEqual(score_one["winning_score"], 1)
        self.assertEqual(score_one["assigned_agents"], [])
        self.assertFalse(score_one["assignment_verified"])

        tied = [
            {"name": "Ada", "email": "ada@example.com", "phone_number": "+60110000011",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
            {"name": "Bea", "email": "bea@example.com", "phone_number": "+60110000012",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
        ]
        tie_service = self._service(tied)
        tie = tie_service.dispatch(
            conversation_id=238,
            customer_name="Customer",
            customer_phone="+60000000238",
            intent="buyer",
            location="Bentong",
            property_type="Commercial Shop",
            raw_inquiry_text="I want to buy a shop in Bentong",
        )
        self.assertEqual(tie["status"], "tie")
        self.assertFalse(tie["assignment_verified"])
        self.assertEqual(tie["assigned_agents"], [])
        self.assertEqual(tie["routed_to"], [])
        self.assertFalse(tie.get("admin_only_handover"))
        self.assertIn("AI continues", tie["diagnostic"])
        tie_service.send_template_func.assert_not_called()
        tie_service.send_contact_func.assert_not_called()


class AhTuckCleanup(unittest.TestCase):
    def test_runtime_prompts_and_routing_do_not_reference_ah_tuck(self):
        full = build_system_prompt(collected_data={}, customer_language="en", role="customer")
        compact = build_system_prompt(
            collected_data={}, customer_language="en", role="customer", compact=True
        )
        blobs = [
            full,
            compact,
            inspect.getsource(system_prompts),
            inspect.getsource(lead_handover),
            inspect.getsource(agent_logic),
            inspect.getsource(llm_service),
        ]
        for blob in blobs:
            lowered = blob.lower()
            self.assertNotIn("ah tuck", lowered)
            self.assertNotIn("tuck@homeihc.com", lowered)
            self.assertNotIn("012-9663589", blob)
            self.assertNotIn("0129663589", blob)
        self.assertFalse(hasattr(system_prompts, "AH_TUCK_NAME"))
        self.assertFalse(hasattr(system_prompts, "AH_TUCK_PHONE"))
        self.assertFalse(hasattr(system_prompts, "get_multilingual_ah_tuck_handover"))

    def test_unverified_reply_strips_invented_names(self):
        cleaned = sanitize_unverified_reply(
            "I have forwarded this to Ah Tuck (012-9663589). Ah Tat will reach you right away."
        )
        self.assertNotIn("Ah Tuck", cleaned)
        self.assertNotIn("Ah Tat", cleaned)
        self.assertNotIn("012-9663589", cleaned)
        self.assertNotIn("right away", cleaned.lower())


class Conv269Qualification(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
            patch("app.services.agent_logic.find_matching_property", return_value=None),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.generate_conversational_response", return_value={
                "response": "Thanks, I have noted the land and the asking price.",
                "intent": "seller",
                "extracted_data": {},
            }),
            patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def test_bentong_land_seller_is_qualified_before_the_roster_refuses(self):
        result = process_persona_state_machine(
            phone_number="+601200000269",
            raw_text=SELLER_LAND,
            session={},
            conversation_history="",
            contact_name="Seller",
        )
        collected = result["updated_session"]["collected_data"]
        self.assertEqual(collected.get("customer_category"), "seller")
        self.assertTrue(collected.get("asking_price_grounded"))
        self.assertEqual(result.get("handover_reason"), "qualified")
        self.assertTrue(hot_lead_qualified("seller", collected, SELLER_LAND))


if __name__ == "__main__":
    unittest.main()

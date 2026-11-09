"""
Conv 238 Plan A. Shop price and availability must not become a seller hot lead.

The five customer lines are the audited Inbox 3 sequence. Nothing else from
that transcript is invented. The first-turn seller prose cause stays unresolved;
these tests lock the code so a photo, a seller classifier label, or model
handover flags cannot create that outcome.
"""

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.agent_logic import (
    _minimal_reply_prompt,
    fit_conversational_token_budget,
    process_persona_state_machine,
)
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.lead_handover import LeadHandoverService
from app.services.system_prompts import build_system_prompt

CONV238 = (
    "hi",
    "is it still available？",
    "how much is this",
    "this is at bentong",
    "i think is jalan ah peng",
)

SELLER_PROSE = (
    "I see you are interested in selling your property. "
    "What is the land size, title and asking price?"
)


def _seller_model(**extra):
    payload = {
        "response": SELLER_PROSE,
        "intent": "seller",
        "promises_handover": True,
        "asked_meeting": True,
        "extracted_data": {
            "is_owner": True,
            "asking_price": "RM 500,000",
            "property_type": "Shop",
            "location": "Bentong",
            "customer_category": "seller",
        },
    }
    payload.update(extra)
    return payload


@contextmanager
def _lock(*args, **kwargs):
    yield


class Conv238Orchestration(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
            patch("app.services.agent_logic.find_matching_property", return_value=None),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.generate_conversational_response"),
            patch("app.services.agent_logic.classify_turn_intent", return_value="seller_intake"),
            patch("app.services.conversation_processor.SessionManager.lock_session", side_effect=_lock),
            patch("app.services.conversation_processor.SessionManager.get_session", return_value={}),
            patch("app.services.conversation_processor.SessionManager.save_session"),
        ]
        started = [item.start() for item in self.patches]
        self.generate = started[3]
        self.generate.return_value = _seller_model()
        self.classify = started[4]

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def _persona(self, text, session=None, history="", images=None):
        return process_persona_state_machine(
            phone_number="+60000000238",
            raw_text=text,
            session=session if session is not None else {},
            conversation_history=history,
            contact_name="Customer",
            images=images or [],
        )

    def _execute(self, text, history="", images=None, turn_intent="seller_intake"):
        processor = ConversationQueueProcessor(
            redis_client=MagicMock(), session_factory=MagicMock()
        )
        return processor.execute_persona_state_machine(
            phone_number="+60000000238",
            contact_name="Customer",
            role="customer",
            final_prompt_text=text,
            conversation_history=history,
            latest_doc_struct=None,
            turn_intent=turn_intent,
            combined_images=images or [],
            db_context={"role": "customer", "data": {}},
            is_seller_intent=True,
            reset_cutoff_ts=0.0,
        )

    def test_separate_conv238_sequence_never_becomes_seller_or_hot_lead(self):
        session = {}
        history = ""
        for index, text in enumerate(CONV238):
            images = ["storefront-bytes"] if text == "how much is this" else None
            result = self._persona(text, session=session, history=history, images=images)
            session = result["updated_session"]
            collected = session.get("collected_data") or {}
            self.assertNotEqual(session.get("current_agent"), "SELLER", text)
            self.assertNotEqual(collected.get("customer_category"), "seller", text)
            self.assertNotEqual(collected.get("seller_evidence"), "explicit", text)
            self.assertFalse(result.get("handover"), text)
            self.assertFalse(collected.get("asking_price_grounded"), text)
            self.assertNotIn("Ah Tuck", result.get("response") or "")
            self.assertNotIn("Ah Tat", result.get("response") or "")
            self.assertNotIn("right away", (result.get("response") or "").lower())
            agent_result, turned, intent, response, handover, lead_temp, _images = self._execute(
                text, history=history, images=images
            )
            self.assertFalse(handover, text)
            self.assertNotEqual(intent, "seller", text)
            self.assertNotEqual(lead_temp, "Hot", text)
            self.assertNotIn("right away", (response or "").lower())
            history = f"{history}\nUser: {text}\nAssistant: noted".strip()
            self.assertGreaterEqual(index, 0)

    def test_batched_opening_is_not_seller(self):
        batched = "hi\nis it still available？"
        result = self._persona(batched)
        collected = result["updated_session"].get("collected_data") or {}
        self.assertEqual(collected.get("customer_category"), "ambiguous")
        self.assertFalse(result.get("handover"))
        _a, _s, intent, response, handover, lead_temp, _i = self._execute(batched)
        self.assertEqual(intent, "ambiguous")
        self.assertFalse(handover)
        self.assertNotEqual(lead_temp, "Hot")
        self.assertNotIn("Ah Tuck", response or "")

    def test_explicit_buy_rent_and_ambiguous_price_question(self):
        buy = self._persona(
            "I want to buy the shop in Bentong. My budget is RM 500,000."
        )
        buy_data = buy["updated_session"]["collected_data"]
        self.assertEqual(buy_data.get("customer_category"), "buyer")
        self.assertTrue(buy_data.get("buyer_budget_grounded"))
        self.assertFalse(buy_data.get("asking_price_grounded"))
        self.assertEqual(buy.get("handover_reason"), "qualified")

        rent = self._persona("I want to rent the shop in Bentong.")
        rent_data = rent["updated_session"]["collected_data"]
        self.assertEqual(rent_data.get("customer_category"), "renter")
        self.assertFalse(rent.get("handover"))
        self.assertFalse(rent_data.get("rent_budget_grounded"))

        question = self._persona("is it for rent?")
        question_data = question["updated_session"]["collected_data"]
        self.assertEqual(question_data.get("customer_category"), "ambiguous")
        self.assertNotEqual(question["updated_session"].get("current_agent"), "LANDLORD")
        self.assertFalse(question.get("handover"))

        stray = self._persona("RM 500,000 how much is this shop")
        stray_data = stray["updated_session"]["collected_data"]
        self.assertFalse(stray_data.get("asking_price_grounded"))
        self.assertNotEqual(stray_data.get("asking_price"), "RM 500,000")
        self.assertFalse(stray.get("handover"))

    def test_photo_title_and_explicit_seller_paths(self):
        photo = self._persona("how much is this", images=["storefront-bytes"])
        self.assertNotEqual(photo["updated_session"].get("current_agent"), "SELLER")

        own_land = self._persona("this is my land in Bentong", images=["photo"])
        self.assertEqual(own_land["updated_session"].get("current_agent"), "SELLER")
        self.assertEqual(
            own_land["updated_session"]["collected_data"].get("seller_evidence"),
            "explicit",
        )
        self.assertFalse(own_land.get("handover"))

        titled = process_persona_state_machine(
            phone_number="+60000000238",
            raw_text="please see attached",
            session={"latest_document_extract": {
                "document_type": "Geran Hakmilik",
                "lot_numbers": ["Lot 1"],
            }},
            conversation_history="",
            contact_name="Owner",
        )
        self.assertEqual(titled["updated_session"].get("current_agent"), "SELLER")

    def test_bentong_survives_later_turns(self):
        session = {}
        history = ""
        for text in CONV238:
            images = ["storefront-bytes"] if text == "how much is this" else None
            result = self._persona(text, session=session, history=history, images=images)
            session = result["updated_session"]
            history = f"{history}\nAssistant: noted".strip()
        self.assertEqual(session["collected_data"].get("location"), "Bentong")
        self.assertNotEqual(session.get("current_agent"), "SELLER")

    def test_compact_prompt_does_not_prime_unconfirmed_seller(self):
        compact = build_system_prompt(collected_data={}, customer_language="en", role="customer", compact=True)
        self.assertIn("not a confirmed seller", compact)
        self.assertNotIn("If the sender is a seller or landowner", compact)
        confirmed = build_system_prompt(
            collected_data={"seller_evidence": "explicit", "customer_category": "seller"},
            customer_language="en",
            role="customer",
            compact=True,
        )
        self.assertIn("confirmed seller", confirmed)
        minimal = _minimal_reply_prompt("en", is_seller=False)
        self.assertNotIn('"intent": "seller"', minimal)
        full = build_system_prompt(collected_data={}, customer_language="en", role="customer")
        self.assertIn("Do not hand them to Ah Tuck", full)
        self.assertNotIn("012-9663589", full)
        plan = fit_conversational_token_budget(full, compact, minimal, "", "is it still available？", 0)
        self.assertEqual(plan["tier"], "compact")
        self.assertIn("not a confirmed seller", plan["system_prompt"])

    def test_miss_lee_turn1_and_legitimate_seller_handovers(self):
        miss = self._persona(
            "Hi Irene. I am Miss Lee. I have land and 1 residence in Kuantan / Bentong Pahang land",
            history="",
        )
        self.assertEqual(miss["updated_session"].get("current_agent"), "SELLER")
        self.assertFalse(miss.get("handover"))
        self.assertFalse(miss.get("promises_handover"))
        self.assertNotIn("RM 500,000", miss["updated_session"]["collected_data"].get("asking_price") or "")

        call = self._persona("I have land in Bentong. Please call me.")
        self.assertTrue(call.get("handover"))
        self.assertEqual(call.get("handover_reason"), "explicit_human")

        priced = self._persona("I want to sell my Bentong land. Asking price is RM 500,000.")
        self.assertTrue(priced.get("handover"))
        self.assertEqual(priced.get("handover_reason"), "qualified")
        self.assertTrue(priced["updated_session"]["collected_data"].get("asking_price_grounded"))


class RoutingGate(unittest.TestCase):
    def _service(self, agents, assign_result=True, agent_id=21):
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
            get_agent_id_func=lambda email: agent_id,
            assign_agent_func=lambda conversation_id, agent_id: assign_result,
        )

    def test_score1_tie_incompatible_and_failed_assignment_do_not_name_anyone(self):
        roster = [
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
        seller_shop = self._service(roster).dispatch(
            conversation_id=238,
            customer_name="Customer",
            customer_phone="+60000000238",
            intent="seller",
            location="Bentong",
            property_type="Shop",
            budget="Not specified",
            conversation_summary="customer asked a shop price",
            raw_inquiry_text="this is at bentong",
        )
        self.assertFalse(seller_shop["assignment_verified"])
        self.assertEqual(seller_shop["assigned_agents"], [])
        self.assertEqual(seller_shop["routed_to"], [])
        self.assertIn(seller_shop["status"], {"intent_incompatible", "below_threshold"})

        tied = [
            {"name": "Ada", "email": "ada@example.com", "phone_number": "+60110000011",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
            {"name": "Bea", "email": "bea@example.com", "phone_number": "+60110000012",
             "assigned_locations": ["Bentong"], "assigned_property_types": ["Commercial"]},
        ]
        tie = self._service(tied).dispatch(
            conversation_id=238,
            customer_name="Customer",
            customer_phone="+60000000238",
            intent="buyer",
            location="Bentong",
            property_type="Commercial Shop",
            raw_inquiry_text="I want to buy a shop in Bentong",
        )
        self.assertEqual(tie["status"], "tie")
        self.assertFalse(tie["public_promise"])
        self.assertEqual(tie["routed_to"], [])

        failed = self._service(tied[:1], assign_result=False).dispatch(
            conversation_id=238,
            customer_name="Customer",
            customer_phone="+60000000238",
            intent="buyer",
            location="Bentong",
            property_type="Commercial Shop",
            raw_inquiry_text="I want to buy a shop in Bentong",
        )
        self.assertEqual(failed["status"], "assignment_failed")
        self.assertFalse(failed["assignment_verified"])
        self.assertEqual(failed["primary_agent_name"], "")

        processor = ConversationQueueProcessor(redis_client=MagicMock(), session_factory=MagicMock())
        session = {"handover": True, "collected_data": {"location": "Bentong"}}
        kept, temp, reply = processor.gate_public_handover(
            handover_initiated=True,
            assignment_verified=False,
            intent="buyer",
            lead_temp="Hot",
            session=session,
            response_text="Ah Tat will reach you right away.",
            phone_number="+60000000238",
        )
        self.assertFalse(kept)
        self.assertNotEqual(temp, "Hot")
        self.assertNotIn("Ah Tat", reply)
        self.assertNotIn("right away", reply.lower())
        self.assertFalse(session.get("handover"))


if __name__ == "__main__":
    unittest.main()

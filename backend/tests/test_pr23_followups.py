"""
Follow-ups from the caption-less shop-sign incident on staging.

The photographed board read:
[Customer sent a photo.] [Photo shows: FOR RENT 出租 011-630 44931 011-651 44931 CY / LEONG]

Both numbers are Home IHC staff. The reply must not send the customer back to
those numbers, must not attach a stale listing photo, and must not nurture
that thread half an hour later by opening a new Chatwoot conversation.
"""
import json
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import app.services.llm as llm_service
from app.services.agent_logic import (
    MultiIntentMemoryTracker,
    guard_own_staff_phone_reply,
    image_turn_acknowledgement,
    process_persona_state_machine,
)
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.db_services import extract_phone_candidates, resolve_sign_contact
from app.services.lead_nurturing import (
    ColdCadenceStrategy,
    LeadNurturingManager,
    canonical_nurture_intent,
)
from app.services.llm import classify_turn_intent, extract_property_search_criteria
from app.services.role_contract import public_intent_label
from app.services.system_prompts import (
    OWN_LISTING_PHONE_RULE,
    build_system_prompt,
    resolve_customer_language,
)

SIGN_NOTE = (
    "[Customer sent a photo.] [Photo shows: FOR RENT 出租 "
    "011-630 44931 011-651 44931 CY / LEONG]"
)
IRENE = "+601165144931"
VOON = "+601163044931"
ALLOW = "+60126761818"


def _completion(content):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    return response


@contextmanager
def _lock(*_args, **_kwargs):
    yield


class _MemoryRedis:
    def get(self, key):
        return None


def _customer(phone, conv_id=42, temp="cold", intent="buyer", ids=None, contact_id=None):
    customer = MagicMock()
    customer.id = phone
    customer.phone_number = phone
    customer.contact_name = "Aina"
    customer.conversation_ids = list(ids) if ids is not None else [conv_id]
    customer.intent_category = intent
    meta = {
        "lead_temp": temp,
        "conversation_id": conv_id,
        "bypass_ai": False,
        "intent_category": intent,
    }
    if contact_id is not None:
        meta.pop("conversation_id", None)
        customer.conversation_ids = []
        meta["contact_id"] = contact_id
    customer.metadata_json = meta
    return customer


def _inbound(minutes_ago, conversation_id=42, extra=None):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    messages = [{
        "id": 1,
        "message_type": "incoming",
        "private": False,
        "content": "photo of a sign",
        "created_at": when.timestamp(),
    }]
    if extra:
        messages.extend(extra)
    return messages


class SignCriteriaTests(unittest.TestCase):
    def test_null_llm_still_marks_rental_without_a_town(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _completion(
                '{"location": null, "property_type": null, "category": null, "max_price": null}'
            )

        history = "User: I saw a board outside a shoplot"
        with patch.object(llm_service.llm_client.chat.completions, "create", side_effect=fake_create):
            criteria = extract_property_search_criteria(SIGN_NOTE, history)
        self.assertEqual(criteria.get("enquiry"), "rental")
        self.assertEqual(criteria.get("transaction"), "rent")
        self.assertIsNone(criteria.get("location"))
        blob = "\n".join(message.get("content") or "" for message in captured["messages"])
        self.assertIn(history, blob)
        self.assertIn("[Photo shows:", blob)

    def test_shop_words_set_commercial_and_sale_marker_sets_sale(self):
        with patch.object(
            llm_service.llm_client.chat.completions,
            "create",
            return_value=_completion(
                '{"location": null, "property_type": null, "category": null, "max_price": null}'
            ),
        ):
            shop = extract_property_search_criteria("[Photo shows: FOR RENT shoplot 店面]", "")
            sale = extract_property_search_criteria("[Photo shows: FOR SALE dijual]", "")
        self.assertEqual(shop.get("category"), "commercial")
        self.assertEqual(shop.get("property_type"), "shop")
        self.assertEqual(shop.get("enquiry"), "rental")
        self.assertEqual(sale.get("enquiry"), "sale")
        self.assertIsNone(sale.get("location"))

    def test_processor_passes_real_history_into_the_criteria_prompt(self):
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        messages = [
            {
                "content": "Looking at a Bentong board",
                "message_type": 0,
                "private": False,
                "created_at": 1,
            },
            {"content": SIGN_NOTE, "message_type": 0, "private": False, "created_at": 2},
        ]
        with patch("app.services.conversation_processor.get_sender_role", return_value="customer"), \
             patch("app.services.conversation_processor.get_conversation_messages", return_value=messages), \
             patch("app.services.conversation_processor.classify_turn_intent", return_value="buyer_search"), \
             patch("app.services.conversation_processor.extract_property_search_criteria", return_value={
                 "enquiry": "rental", "location": None,
             }) as extract, \
             patch("app.services.conversation_processor.search_properties", return_value=[]):
            processor.build_rbac_and_context(
                conversation_id=9,
                customer=None,
                phone_number="+601200000001",
                final_prompt_text=SIGN_NOTE,
                latest_doc_struct=None,
                combined_images=["abc"],
                analysis_text=SIGN_NOTE,
            )
        self.assertIn("Looking at a Bentong board", extract.call_args[0][1])

    def test_sign_phones_match_irene_and_voon_without_a_database(self):
        phones = extract_phone_candidates(SIGN_NOTE)
        self.assertIn("01163044931", phones)
        self.assertIn("01165144931", phones)
        with patch("app.services.db_services._postgres_reachable", return_value=False):
            match = resolve_sign_contact(SIGN_NOTE)
        self.assertTrue(match["staff_hit"])
        self.assertEqual(match["source"], "staff")
        self.assertIsNone(match["listing"])

    def test_prompt_forbids_telling_the_customer_to_call_the_sign(self):
        compact = build_system_prompt(compact=True, customer_sent_image=True)
        full = build_system_prompt(customer_sent_image=True)
        self.assertIn(OWN_LISTING_PHONE_RULE, compact)
        self.assertIn(OWN_LISTING_PHONE_RULE, full)

    def test_photo_note_does_not_set_landlord(self):
        extracted = MultiIntentMemoryTracker.extract_intent_entities(SIGN_NOTE)
        self.assertNotIn(extracted.get("role"), {"landlord", "seller"})


class SignReplyAndPhotoTests(unittest.TestCase):
    def _run(self, text, session=None, history="", images=None, generate=None, finder=None, sign=None):
        session = {} if session is None else session
        if generate is None:
            generate = {
                "response": "Please call 011-651 44931 or WhatsApp the number on the sign.",
                "intent": "buyer",
                "asked_photos": True,
                "extracted_data": {},
            }
        patches = [
            patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"),
            patch("app.services.agent_logic.generate_conversational_response", return_value=generate),
            patch("app.services.agent_logic.find_matching_property", side_effect=finder or (lambda *_a, **_k: None)),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
        ]
        if sign is not None:
            patches.append(patch("app.services.agent_logic.resolve_sign_contact", return_value=sign))
        else:
            patches.append(patch("app.services.db_services._postgres_reachable", return_value=False))
        for item in patches:
            item.start()
        try:
            return process_persona_state_machine(
                phone_number="+601200000001",
                text=text,
                session=session,
                conversation_history=history,
                images=images,
            )
        finally:
            for item in reversed(patches):
                item.stop()

    def test_staff_sign_reply_never_sends_the_customer_to_our_number(self):
        result = self._run(SIGN_NOTE, images=["aGVsbG8="])
        reply = result["response"]
        self.assertNotIn("011-651", reply)
        self.assertNotIn("44931", reply)
        self.assertNotIn("call the number", reply.lower())
        self.assertIn("check that unit", reply.lower())
        self.assertEqual(result["images_to_send"], [])
        self.assertEqual(
            result["updated_session"]["collected_data"].get("customer_category"),
            "renter",
        )

    def test_guard_rewrites_a_reply_that_quotes_our_line(self):
        cleaned = guard_own_staff_phone_reply(
            "Please call 011-651 44931.",
            staff_hit=True,
            listing_matched=False,
            language="en",
            extra_numbers=["01165144931", "01163044931"],
        )
        self.assertNotIn("011-651", cleaned)
        self.assertNotIn("44931", cleaned)
        self.assertNotIn("call the number", cleaned.lower())

    def test_stale_putrajaya_session_sends_no_images(self):
        putrajaya = {
            "id": "putrajaya-1",
            "title": "Putrajaya shop lot",
            "city": "Putrajaya",
            "status": "For Rent",
            "image_urls": ["https://cdn.example/putrajaya.jpg"],
        }
        session = {"interested_property": dict(putrajaya), "language": "en"}
        history = "User: the Putrajaya shop lot\nAssistant: Here is the Putrajaya shop lot."

        def finder(text):
            return putrajaya if "putrajaya" in (text or "").lower() else None

        result = self._run(SIGN_NOTE, session=session, history=history, images=["aGVsbG8="], finder=finder)
        self.assertEqual(result["images_to_send"], [])

    def test_agent_phone_match_sends_that_listings_images(self):
        listing = {
            "id": "bentong-shop",
            "title": "Bentong ground floor shop",
            "city": "Bentong",
            "status": "For Rent",
            "image_urls": ["https://cdn.example/bentong-shop.jpg"],
        }
        result = self._run(
            SIGN_NOTE,
            images=["aGVsbG8="],
            sign={
                "phones": ["01165144931"],
                "staff_hit": True,
                "listing": listing,
                "source": "agent_phone",
            },
        )
        self.assertEqual(result["images_to_send"], ["https://cdn.example/bentong-shop.jpg"])
        self.assertEqual(result["updated_session"].get("listing_match_source"), "agent_phone")

    def test_real_send_photos_still_sends_the_known_listing(self):
        listing = {
            "id": "known",
            "title": "Bentong shop",
            "status": "Available",
            "image_urls": ["https://cdn.example/known.jpg"],
        }
        session = {"interested_property": listing, "language": "en", "collected_data": {"name": "Aina"}}
        history = "User: any shop in Bentong?\nAssistant: Yes, we have one shop listing."
        result = self._run(
            "please send photos",
            session=session,
            history=history,
            generate={
                "response": "Here are the photos.",
                "intent": "buyer",
                "asked_photos": False,
                "extracted_data": {},
            },
        )
        self.assertEqual(result["images_to_send"], ["https://cdn.example/known.jpg"])


class LanguageAndRoleTests(unittest.TestCase):
    def test_sign_note_stays_english_and_chinese_customer_words_do_not(self):
        empty = {}
        self.assertEqual(resolve_customer_language(empty, SIGN_NOTE, ""), "en")
        self.assertEqual(empty.get("language"), "en")

        stored = {"language": "en"}
        self.assertEqual(resolve_customer_language(stored, SIGN_NOTE, ""), "en")
        self.assertEqual(stored["language"], "en")

        caption = {}
        resolve_customer_language(caption, "我想租这间店面\n" + SIGN_NOTE, "")
        self.assertEqual(caption["language"], "zh")

        prior = {}
        resolve_customer_language(
            prior,
            SIGN_NOTE,
            "User: 你们有店面出租吗\nAssistant: 好的",
        )
        self.assertEqual(prior["language"], "zh")

        ack = image_turn_acknowledgement(SIGN_NOTE)
        self.assertTrue(ack.startswith("Thanks"))
        self.assertNotIn("我看到", ack)
        self.assertTrue(image_turn_acknowledgement("我想租店面\n" + SIGN_NOTE).startswith("我看到"))
        self.assertTrue(
            image_turn_acknowledgement(SIGN_NOTE, language="en").startswith("Thanks")
        )

    def test_state_machine_keeps_session_english_for_the_sign(self):
        session = {"language": "en"}
        with patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"), \
             patch("app.services.agent_logic.generate_conversational_response", return_value={
                 "response": "I will check that unit and follow up.",
                 "intent": "tenant",
                 "extracted_data": {},
             }), \
             patch("app.services.agent_logic.find_matching_property", return_value=None), \
             patch("app.services.agent_logic.search_properties", return_value=[]), \
             patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"), \
             patch("app.services.db_services._postgres_reachable", return_value=False):
            result = process_persona_state_machine(
                phone_number="+601200000099",
                text=SIGN_NOTE,
                session=session,
                conversation_history="",
                images=["aGVsbG8="],
            )
        self.assertEqual(result["updated_session"].get("language"), "en")

    def test_rent_request_is_tenant_and_sell_request_stays_seller(self):
        with patch.object(llm_service.llm_client.chat.completions, "create", side_effect=TimeoutError("down")), \
             patch("app.services.agent_logic.find_matching_property", return_value=None), \
             patch("app.services.agent_logic.search_properties", return_value=[]), \
             patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"):
            rent = process_persona_state_machine(
                phone_number="+601200000099",
                text="I want to rent a shop in Bentong",
                session={},
                conversation_history="Assistant: How can Home IHC help?",
            )
            sell = process_persona_state_machine(
                phone_number="+601200000099",
                text="I want to sell my shop",
                session={},
                conversation_history="Assistant: How can Home IHC help?",
            )
        rent_cat = rent["updated_session"]["collected_data"].get("customer_category")
        self.assertIn(rent_cat, {"renter", "tenant"})
        self.assertEqual(public_intent_label(rent_cat), "tenant")
        self.assertEqual(canonical_nurture_intent(rent_cat), "tenant")
        self.assertEqual(sell["updated_session"]["collected_data"].get("customer_category"), "seller")
        self.assertNotEqual(sell["updated_session"].get("current_agent"), "BUYER")

    def test_sign_photo_is_not_buyer_cold(self):
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        with patch("app.services.conversation_processor.SessionManager.lock_session", side_effect=_lock), \
             patch("app.services.conversation_processor.SessionManager.get_session", return_value={}), \
             patch("app.services.conversation_processor.SessionManager.save_session"), \
             patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"), \
             patch("app.services.agent_logic.generate_conversational_response", return_value={
                 "response": "I will check that unit and follow up.",
                 "intent": "buyer",
                 "extracted_data": {},
             }), \
             patch("app.services.agent_logic.find_matching_property", return_value=None), \
             patch("app.services.agent_logic.search_properties", return_value=[]), \
             patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"), \
             patch("app.services.db_services._postgres_reachable", return_value=False):
            _agent, session, intent, _response, _handover, lead_temp, images = (
                processor.execute_persona_state_machine(
                    phone_number="+601200000001",
                    contact_name=None,
                    role="customer",
                    final_prompt_text=SIGN_NOTE,
                    conversation_history="",
                    latest_doc_struct=None,
                    turn_intent="buyer_search",
                    combined_images=["aGVsbG8="],
                    db_context={"role": "customer", "data": {}},
                    is_seller_intent=False,
                    reset_cutoff_ts=0.0,
                )
            )
        self.assertNotEqual(lead_temp.lower(), "cold")
        self.assertNotEqual(lead_temp.lower(), "hot")
        self.assertNotEqual({"hot": "high", "warm": "medium", "cold": "low"}[lead_temp.lower()], "low")
        self.assertNotEqual(intent, "buyer")
        self.assertEqual(public_intent_label(intent), "tenant")
        self.assertEqual(images, [])
        self.assertNotEqual(session.get("current_agent"), "SELLER")


class ClassifyLogTests(unittest.TestCase):
    def test_info_log_names_llm_and_fallback_without_confidence(self):
        with patch.object(
            llm_service.llm_client.chat.completions,
            "create",
            return_value=_completion('{"category": "buyer_search"}'),
        ), self.assertLogs("app.services.llm", level="INFO") as logs:
            category = classify_turn_intent("hello there")
        self.assertEqual(category, "buyer_search")
        self.assertTrue(any("category=buyer_search" in line and "source=llm" in line for line in logs.output))
        self.assertFalse(any("confidence" in line.lower() for line in logs.output))

        with patch.object(
            llm_service.llm_client.chat.completions,
            "create",
            side_effect=TimeoutError("down"),
        ), self.assertLogs("app.services.llm", level="INFO") as logs:
            fallback = classify_turn_intent(SIGN_NOTE)
        self.assertEqual(fallback, "buyer_search")
        self.assertTrue(any("source=fallback" in line for line in logs.output))
        self.assertFalse(any("confidence" in line.lower() for line in logs.output))

    def test_classify_turn_intent_runs_once_per_turn(self):
        calls = []

        def _fake(*_args, **_kwargs):
            calls.append(1)
            return "buyer_search"

        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        messages = [
            {"content": "Looking at a Bentong board", "message_type": 0, "private": False, "created_at": 1},
        ]
        with patch("app.services.conversation_processor.get_sender_role", return_value="customer"), \
             patch("app.services.conversation_processor.get_conversation_messages", return_value=messages), \
             patch("app.services.conversation_processor.classify_turn_intent", side_effect=_fake), \
             patch("app.services.agent_logic.classify_turn_intent", side_effect=_fake), \
             patch("app.services.conversation_processor.extract_property_search_criteria", return_value={
                 "enquiry": "rental", "location": None,
             }), \
             patch("app.services.conversation_processor.search_properties", return_value=[]), \
             patch("app.services.conversation_processor.SessionManager.lock_session", side_effect=_lock), \
             patch("app.services.conversation_processor.SessionManager.get_session", return_value={}), \
             patch("app.services.conversation_processor.SessionManager.save_session"), \
             patch("app.services.agent_logic.generate_conversational_response", return_value={
                 "response": "I will check that unit and follow up.",
                 "intent": "tenant",
                 "extracted_data": {},
             }), \
             patch("app.services.agent_logic.find_matching_property", return_value=None), \
             patch("app.services.agent_logic.search_properties", return_value=[]), \
             patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"), \
             patch("app.services.db_services._postgres_reachable", return_value=False):
            role, _ctx, history, turn_intent, _seller, reset_at = processor.build_rbac_and_context(
                conversation_id=9,
                customer=None,
                phone_number="+601200000001",
                final_prompt_text=SIGN_NOTE,
                latest_doc_struct=None,
                combined_images=["abc"],
                analysis_text=SIGN_NOTE,
            )
            processor.execute_persona_state_machine(
                phone_number="+601200000001",
                contact_name=None,
                role=role,
                final_prompt_text=SIGN_NOTE,
                conversation_history=history,
                latest_doc_struct=None,
                turn_intent=turn_intent,
                combined_images=["abc"],
                db_context={"role": "customer", "data": {}},
                is_seller_intent=False,
                reset_cutoff_ts=reset_at,
            )
        self.assertEqual(len(calls), 1)


class NurtureGuardTests(unittest.TestCase):
    def _manager(self, staging):
        return LeadNurturingManager(
            message_sender=MagicMock(),
            note_sender=MagicMock(),
            template_dispatcher=MagicMock(),
            is_staging=staging,
        )

    def test_cadence_windows_are_unchanged(self):
        cold = ColdCadenceStrategy()
        self.assertTrue(cold.is_due(33 / 60, is_staging=True))
        self.assertFalse(cold.is_due(33 / 60, is_staging=False))
        self.assertTrue(cold.is_due(8 * 24, is_staging=False))
        self.assertFalse(cold.is_due(0.4, is_staging=True))
        tenant = cold.get_message_content("Aina", "Bentong", intent="tenant")
        renter = cold.get_message_content("Aina", "Bentong", intent="renter")
        self.assertEqual(tenant, renter)
        self.assertIn("tenancy", renter.lower())

    def test_latest_message_ours_does_not_send_and_never_creates_a_conversation(self):
        now = datetime.now(timezone.utc)
        ours = {
            "message_type": "outgoing",
            "private": False,
            "content": "we replied",
            "created_at": now.timestamp(),
        }
        manager = self._manager(staging=True)
        customer = _customer(ALLOW)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch("app.services.chatwoot.get_or_create_conversation") as get_or_create, \
             patch(
                 "app.services.lead_nurturing.get_conversation_messages",
                 return_value=_inbound(33) + [ours],
             ):
            result = manager.evaluate_customer(customer, now=now)
        self.assertIsNone(result)
        create_conv.assert_not_called()
        get_or_create.assert_not_called()
        manager.message_sender.assert_not_called()

    def test_staging_cold_33_minutes_sends_on_the_existing_conversation(self):
        now = datetime.now(timezone.utc)
        manager = self._manager(staging=True)
        customer = _customer(ALLOW, conv_id=77)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch("app.services.lead_nurturing.get_contact_conversations") as lookup, \
             patch(
                 "app.services.lead_nurturing.get_conversation_messages",
                 return_value=_inbound(33, conversation_id=77),
             ):
            result = manager.evaluate_customer(customer, now=now)
            action = manager.dispatch_nurture(customer, result, now=now)
        self.assertIsNotNone(result)
        self.assertEqual(result["conversation_id"], 77)
        self.assertEqual(action, "message_sent")
        create_conv.assert_not_called()
        lookup.assert_not_called()
        manager.message_sender.assert_called_once()

    def test_production_cold_at_33_minutes_is_not_due(self):
        now = datetime.now(timezone.utc)
        manager = self._manager(staging=False)
        customer = _customer("+60129990000")
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch(
                 "app.services.lead_nurturing.get_conversation_messages",
                 return_value=_inbound(33),
             ):
            result = manager.evaluate_customer(customer, now=now)
        self.assertIsNone(result)
        create_conv.assert_not_called()

    def test_staff_row_is_suppressed(self):
        now = datetime.now(timezone.utc)
        manager = self._manager(staging=True)
        customer = _customer(IRENE)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": IRENE}), \
             patch("app.services.db_services.get_sender_role", return_value="admin"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch("app.services.lead_nurturing.get_conversation_messages") as messages:
            result = manager.evaluate_customer(customer, now=now)
        self.assertIsNone(result)
        create_conv.assert_not_called()
        messages.assert_not_called()

    def test_missing_conversation_is_reused_from_the_contact_or_skipped(self):
        now = datetime.now(timezone.utc)
        manager = self._manager(staging=True)
        customer = _customer(ALLOW, contact_id=15)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW, "STAGING_INBOX_ID": "4"}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch(
                 "app.services.lead_nurturing.get_contact_conversations",
                 return_value=[{"id": 88, "inbox_id": 4, "status": "open"}],
             ), \
             patch(
                 "app.services.lead_nurturing.get_conversation_messages",
                 return_value=_inbound(33, conversation_id=88),
             ):
            result = manager.evaluate_customer(customer, now=now)
        self.assertEqual(result["conversation_id"], 88)
        create_conv.assert_not_called()

        empty = _customer(ALLOW, contact_id=16)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch("app.services.lead_nurturing.get_contact_conversations", return_value=[]):
            skipped = manager.evaluate_customer(empty, now=now)
        self.assertIsNone(skipped)
        create_conv.assert_not_called()

    def test_staging_allowlist_default_deny_and_production_unaffected(self):
        now = datetime.now(timezone.utc)
        listed = _customer(ALLOW, conv_id=5)
        other = _customer("+60128880000", conv_id=6)
        staging = self._manager(staging=True)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ""}, clear=False), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             self.assertLogs("app.services.lead_nurturing", level="INFO") as logs:
            os.environ["NURTURE_TEST_CONTACTS"] = ""
            first = staging.evaluate_customer(listed, now=now)
            second = staging.evaluate_customer(other, now=now)
        self.assertIsNone(first)
        self.assertIsNone(second)
        notices = [line for line in logs.output if "NURTURE_TEST_CONTACTS is unset" in line]
        self.assertEqual(len(notices), 1)
        create_conv.assert_not_called()
        staging.message_sender.assert_not_called()

        allowed = self._manager(staging=True)
        skipped = self._manager(staging=True)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch("app.services.lead_nurturing.get_conversation_messages", return_value=_inbound(33)):
            sent = allowed.evaluate_customer(listed, now=now)
            missed = skipped.evaluate_customer(other, now=now)
        self.assertIsNotNone(sent)
        self.assertIsNone(missed)
        allowed.dispatch_nurture(listed, sent, now=now)
        allowed.message_sender.assert_called_once()
        skipped.message_sender.assert_not_called()
        create_conv.assert_not_called()

        production = self._manager(staging=False)
        outsider = _customer("+60127770000", conv_id=9)
        with patch.dict(os.environ, {"NURTURE_TEST_CONTACTS": ALLOW}), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.services.chatwoot.create_conversation") as create_conv, \
             patch(
                 "app.services.lead_nurturing.get_conversation_messages",
                 return_value=_inbound(20 * 60),
             ):
            # Hot window in production is 18h-72h. 20h is due. Allowlist must not apply.
            outsider.metadata_json["lead_temp"] = "hot"
            result = production.evaluate_customer(outsider, now=now)
        self.assertIsNotNone(result)
        create_conv.assert_not_called()


if __name__ == "__main__":
    unittest.main()

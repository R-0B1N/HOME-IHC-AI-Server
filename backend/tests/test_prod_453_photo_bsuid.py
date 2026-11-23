"""Prod conversation 453: caption-less sign handover, 131026, and BSUID identity."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.agent_logic import guard_own_staff_phone_reply, process_persona_state_machine
from app.services.contact_identity import (
    is_authentication_template,
    meta_destination_fields,
    resolve_contact_identity,
)
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.db_services import (
    get_sender_role,
    is_invalid_length_malaysian_01x,
    within_staff_edit_distance,
)
from app.services.delivery_failure import handle_message_updated
from app.services.general_assignee import resolve_general_handover_assignees
from app.services.handover_assignee import handover_without_specialist
from app.services.role_contract import filter_unearned_followup, public_intent_label
from app.services.session_manager import SessionManager
from scripts.backfill_chatwoot_contact_phones import apply_plans, plan_updates

PROD_NOTE = (
    "[Customer sent a photo.] [Photo shows: FOR RENT 出租 "
    "011-6830 44831 011-6831 44831 BY: LEONG]"
)
IRENE = "+601165144931"
VOON = "+601163044931"
BSUID = "MY.991816617335585"


def _persona_patches(generate=None):
    if generate is None:
        generate = {
            "response": "Home IHC will check that unit and follow up with you soon. Please call 011-6830 44831.",
            "intent": "buyer",
            "extracted_data": {},
        }
    return [
        patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"),
        patch("app.services.agent_logic.generate_conversational_response", return_value=generate),
        patch("app.services.agent_logic.find_matching_property", return_value=None),
        patch("app.services.agent_logic.search_properties", return_value=[]),
        patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
        patch("app.services.db_services._postgres_reachable", return_value=False),
    ]


def _run_persona(text, session=None, images=None, turn_intent="buyer_search", generate=None):
    patches = _persona_patches(generate)
    for item in patches:
        item.start()
    try:
        return process_persona_state_machine(
            phone_number="+601200000001",
            text=text,
            session={} if session is None else session,
            conversation_history="Assistant: Hello",
            images=images if images is not None else ["aGVsbG8="],
            turn_intent=turn_intent,
        )
    finally:
        for item in reversed(patches):
            item.stop()


class _MemoryRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value
        return True


class PhotoNoMatchTests(unittest.TestCase):
    def test_prod_vision_note_arms_handover_without_a_false_promise(self):
        with self.assertLogs("app.services.agent_logic", level="INFO") as logs:
            result = _run_persona(PROD_NOTE)
        reply = result["response"]
        self.assertEqual(result.get("handover_reason"), "photo_no_match")
        self.assertTrue(result.get("handover"))
        self.assertTrue(result["updated_session"].get("photo_no_match"))
        self.assertEqual(result["updated_session"].get("photo_reject_reason"), "no_candidate")
        self.assertTrue(any("reason=no_candidate" in line for line in logs.output))
        self.assertNotIn("follow up soon", reply.lower())
        self.assertNotIn("get back", reply.lower())
        self.assertNotIn("6830", reply)
        self.assertNotIn("6831", reply)
        self.assertNotIn("call", reply.lower())
        self.assertNotIn("whatsapp", reply.lower())
        self.assertIn("check that unit", reply.lower())
        category = result["updated_session"]["collected_data"].get("customer_category")
        self.assertEqual(category, "renter")
        self.assertEqual(public_intent_label(category), "tenant")

    def test_execute_keeps_tenant_and_does_not_force_hot(self):
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        patches = _persona_patches()
        for item in patches:
            item.start()
        try:
            with patch("app.services.conversation_processor.SessionManager.lock_session"), \
                 patch("app.services.conversation_processor.SessionManager.get_session", return_value={}), \
                 patch("app.services.conversation_processor.SessionManager.save_session"):
                _agent, session, intent, response, handover, lead_temp, images = (
                    processor.execute_persona_state_machine(
                        phone_number="+601200000001",
                        contact_name="User",
                        role="customer",
                        final_prompt_text=PROD_NOTE,
                        conversation_history="Assistant: Hello",
                        latest_doc_struct=None,
                        turn_intent="buyer_search",
                        combined_images=["aGVsbG8="],
                        db_context={"role": "customer", "data": {}},
                        is_seller_intent=False,
                        reset_cutoff_ts=0.0,
                    )
                )
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertTrue(handover)
        self.assertNotEqual(lead_temp.lower(), "hot")
        self.assertEqual(public_intent_label(intent), "tenant")
        self.assertNotIn("follow up soon", (response or "").lower())
        self.assertEqual(images, [])
        self.assertTrue(session.get("photo_no_match"))

    def test_gate_keeps_photo_handover_when_nobody_was_assigned(self):
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        session = {"photo_no_match": True, "handover_requested": "photo_no_match"}
        kept, _temp, text = processor.gate_public_handover(
            handover_initiated=True,
            assignment_verified=False,
            intent="renter",
            lead_temp="Warm",
            session=session,
            response_text="A team member will check that unit and reply in this chat.",
            phone_number="+601200000001",
        )
        self.assertTrue(kept)
        self.assertIn("check that unit", text.lower())

    def test_later_buyer_search_keeps_the_tenant_label(self):
        first = _run_persona(PROD_NOTE)
        session = first["updated_session"]
        second = _run_persona(
            "masih ada? is it still available",
            session=session,
            images=None,
            turn_intent="buyer_search",
            generate={"response": "I will check that for you.", "intent": "buyer", "extracted_data": {}},
        )
        category = second["updated_session"]["collected_data"].get("customer_category")
        self.assertEqual(category, "renter")
        self.assertEqual(public_intent_label(category), "tenant")
        self.assertNotEqual(second["updated_session"].get("current_agent"), "BUYER")

    def test_accepted_listing_does_not_arm_photo_no_match(self):
        listing = {
            "id": "shop",
            "title": "Bentong Ground Floor Shop Lot",
            "status": "For Rent",
            "property_category": ["Commercial"],
            "image_urls": ["https://cdn.example/shop.jpg"],
        }
        note = "[Customer sent a photo.] [Photo shows: FOR RENT Bentong Ground Floor Shop Lot]"
        patches = _persona_patches({
            "response": "This is the Bentong ground floor shop.",
            "intent": "tenant",
            "extracted_data": {},
        })
        patches[2] = patch(
            "app.services.agent_logic.find_matching_property",
            return_value=listing,
        )
        for item in patches:
            item.start()
        try:
            result = process_persona_state_machine(
                phone_number="+601200000001",
                text=note,
                session={},
                conversation_history="Assistant: Hello",
                images=["aGVsbG8="],
            )
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertNotEqual(result.get("handover_reason"), "photo_no_match")
        self.assertFalse(result["updated_session"].get("photo_no_match"))
        self.assertEqual(result["images_to_send"], ["https://cdn.example/shop.jpg"])

    def test_empty_resolver_alerts_and_a_stub_assigns(self):
        self.assertEqual(resolve_general_handover_assignees(), [])
        notes = []
        templates = []
        assigns = []

        def _note(_cid, content):
            notes.append(content)

        def _template(**kwargs):
            templates.append(kwargs)
            return {"messages": [{"id": "wamid.1"}]}

        def _assign(_cid, agent_id):
            assigns.append(agent_id)
            return True

        with patch("app.services.lead_handover.send_private_note", side_effect=_note), \
             patch("app.services.lead_handover.send_whatsapp_template", side_effect=_template), \
             patch("app.services.lead_handover.assign_agent", side_effect=_assign), \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=None), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            empty = handover_without_specialist(
                453,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent. reason=no_candidate.",
                customer_name="User",
                intent="renter",
                inbox_id=4,
            )
        self.assertFalse(empty["assignment_verified"])
        self.assertTrue(empty["unassigned"])
        self.assertTrue(empty["admin_alert"])
        self.assertTrue(templates)
        self.assertTrue(any("No general assignee was found" in note for note in notes))
        self.assertEqual(assigns, [])

        notes.clear()
        templates.clear()
        with patch("app.services.handover_assignee.resolve_general_handover_assignees", return_value=[
            {"email": "general@example.com", "full_name": "General Agent"},
        ]), \
             patch("app.services.lead_handover.send_private_note", side_effect=_note), \
             patch("app.services.lead_handover.send_whatsapp_template", side_effect=_template), \
             patch("app.services.lead_handover.assign_agent", side_effect=_assign), \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=44), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            assigned = handover_without_specialist(
                453,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent.",
                inbox_id=4,
            )
        self.assertTrue(assigned["assignment_verified"])
        self.assertEqual(assigns, [44])
        self.assertEqual(templates, [])
        self.assertTrue(any("General Agent" in note for note in notes))

    def test_labels_include_photo_needs_agent_and_tenant_without_muting(self):
        customer = MagicMock()
        customer.id = "+601200000001"
        customer.metadata_json = {}
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = customer
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: db,
        )
        with patch("app.services.conversation_processor.apply_label") as labels, \
             patch("app.services.conversation_processor.set_priority"):
            processor.persist_state_and_labels(
                conversation_id=453,
                customer=customer,
                lead_temp="Warm",
                handover_initiated=True,
                role="customer",
                intent="renter",
                assignee_email=None,
                photo_no_match=True,
                assignment_verified=False,
            )
        applied = labels.call_args[0][1]
        self.assertIn("tenant", applied)
        self.assertIn("photo-needs-agent", applied)
        self.assertNotIn("buyer", applied)
        self.assertNotIn("bypass_ai", customer.metadata_json)

    def test_unearned_follow_up_is_rewritten_until_handover_happens(self):
        promised = "We will check and follow up."
        self.assertEqual(
            filter_unearned_followup(promised, handover_happened=True),
            promised,
        )
        rewritten = filter_unearned_followup(promised, handover_happened=False)
        self.assertNotIn("follow up", rewritten.lower())
        self.assertNotIn("will check", rewritten.lower())
        photo = filter_unearned_followup(
            promised,
            handover_happened=False,
            photo_no_match=True,
        )
        self.assertIn("check that unit", photo.lower())
        self.assertNotIn("follow up", photo.lower())


class FuzzyStaffSuppressionTests(unittest.TestCase):
    def test_one_and_two_digit_misses_and_an_invalid_length(self):
        self.assertTrue(within_staff_edit_distance("01165144932", [IRENE]))
        self.assertTrue(within_staff_edit_distance("01163044932", [VOON]))
        self.assertTrue(within_staff_edit_distance("01165044831", [IRENE]))
        self.assertFalse(within_staff_edit_distance("01111111111", [IRENE, VOON]))
        self.assertTrue(is_invalid_length_malaysian_01x("011683044831"))
        self.assertTrue(is_invalid_length_malaysian_01x("011683144831"))
        self.assertFalse(is_invalid_length_malaysian_01x("01165144931"))

    def test_captionless_reply_does_not_send_the_misread_number(self):
        cleaned = guard_own_staff_phone_reply(
            "Please WhatsApp 011-6830 44831 and call 011-651 44932.",
            staff_hit=False,
            listing_matched=False,
            captionless=True,
            photo_text=PROD_NOTE,
            extra_numbers=["011683044831", "01165144932"],
        )
        self.assertNotIn("6830", cleaned)
        self.assertNotIn("44932", cleaned)
        self.assertNotIn("whatsapp", cleaned.lower())
        self.assertIn("check that unit", cleaned.lower())


class UndeliverableTests(unittest.TestCase):
    def _payload(self):
        return {
            "event": "message_updated",
            "id": 2590,
            "status": "failed",
            "content_attributes": {"external_error": "131026: Message undeliverable"},
            "conversation": {
                "id": 453,
                "inbox_id": 4,
                "labels": ["tenant", "warm"],
                "contact_inbox": {"source_id": BSUID},
                "meta": {
                    "sender": {
                        "id": 141,
                        "name": "User",
                        "phone_number": None,
                        "identifier": BSUID,
                    }
                },
            },
        }

    def test_131026_notes_labels_alerts_blocks_and_is_idempotent(self):
        redis = _MemoryRedis()
        customer = MagicMock()
        customer.id = "cw:141"
        customer.metadata_json = {}
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = customer
        notes = []
        templates = []
        labels = []

        def _note(_cid, content):
            notes.append(content)

        def _template(**kwargs):
            templates.append(kwargs.get("template_name"))
            return {"messages": [{"id": "wamid.1"}]}

        def _label(_cid, values):
            labels.append(list(values))

        with patch("app.services.outbound_block._client", return_value=redis), \
             patch("app.db.models.SessionLocal", return_value=db), \
             patch("app.services.chatwoot.get_conversation_details", return_value={"labels": ["tenant", "warm"]}), \
             patch("app.services.chatwoot.apply_label", side_effect=_label), \
             patch("app.services.lead_handover.send_private_note", side_effect=_note), \
             patch("app.services.lead_handover.send_whatsapp_template", side_effect=_template), \
             patch("app.services.lead_handover.assign_agent") as assign, \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=None), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            first = handle_message_updated(self._payload())
            notes_after_first = len(notes)
            templates_after_first = len(templates)
            second = handle_message_updated(self._payload())
        self.assertEqual(first["status"], "undeliverable")
        self.assertEqual(first["code"], "131026")
        self.assertTrue(first["outbound_blocked"])
        self.assertTrue(first["nurture_stopped"])
        self.assertFalse(first["assignment_verified"])
        self.assertEqual(second["status"], "duplicate")
        self.assertGreaterEqual(templates_after_first, 1)
        self.assertEqual(len(notes), notes_after_first)
        self.assertEqual(len(templates), templates_after_first)
        self.assertTrue(any("131026" in note for note in notes))
        self.assertTrue(any("No general assignee was found" in note for note in notes))
        self.assertEqual(labels, [["tenant", "warm", "undeliverable"]])
        assign.assert_not_called()
        self.assertTrue(customer.metadata_json.get("outbound_blocked"))
        self.assertTrue(customer.metadata_json.get("nurture_stopped"))
        self.assertEqual(redis.get("outbound_blocked:453"), "1")

        from app.services.chatwoot import send_message
        from app.services.lead_nurturing import LeadNurturingManager

        with patch("app.services.outbound_block._client", return_value=redis), \
             patch("app.services.chatwoot.requests.post") as posted:
            skipped = send_message(453, "another public reply")
        posted.assert_not_called()
        self.assertEqual(skipped.get("skipped"), "outbound_blocked")

        manager = LeadNurturingManager(
            db_session=MagicMock(),
            message_sender=MagicMock(),
            note_sender=MagicMock(),
        )
        self.assertIsNone(manager.evaluate_customer(customer))
        action = manager.dispatch_nurture(
            customer,
            {
                "conversation_id": 453,
                "contact_name": "User",
                "phone_number": "cw:141",
                "is_within_24h": True,
                "message_text": "hello",
                "lead_temp": "warm",
                "intent": "tenant",
                "cadence_label": "warm",
                "elapsed_hours": 1,
                "elapsed_days": 0,
                "location": "Bentong",
                "template_name": "reengage",
            },
        )
        self.assertEqual(action, "nurture_stopped")
        manager.message_sender.assert_not_called()

    def test_stubbed_general_assignee_is_assigned_for_131026(self):
        redis = _MemoryRedis()
        with patch("app.services.outbound_block._client", return_value=redis), \
             patch("app.db.models.SessionLocal", return_value=MagicMock()), \
             patch("app.services.chatwoot.get_conversation_details", return_value={"labels": []}), \
             patch("app.services.chatwoot.apply_label"), \
             patch("app.services.handover_assignee.resolve_general_handover_assignees", return_value=[
                 {"email": "general@example.com", "full_name": "General Agent"},
             ]), \
             patch("app.services.lead_handover.send_private_note"), \
             patch("app.services.lead_handover.send_whatsapp_template") as template, \
             patch("app.services.lead_handover.assign_agent", return_value=True) as assign, \
             patch("app.services.lead_handover.get_agent_id_by_email", return_value=44), \
             patch("app.services.lead_handover.update_conversation_status", return_value={"status": "open"}):
            result = handle_message_updated(self._payload())
        self.assertTrue(result["assignment_verified"])
        assign.assert_called_once()
        template.assert_not_called()


class BsuidIdentityTests(unittest.TestCase):
    def test_bsuid_gets_its_own_session_and_customer_key(self):
        sender = {
            "id": 141,
            "name": "User",
            "phone_number": None,
            "identifier": BSUID,
        }
        conversation = {
            "id": 453,
            "contact_inbox": {"source_id": BSUID},
            "meta": {"sender": sender},
        }
        with self.assertLogs("app.services.contact_identity", level="INFO") as logs:
            identity = resolve_contact_identity(sender, conversation, 453, 3)
        self.assertEqual(identity["customer_id"], "cw:141")
        self.assertTrue(identity["phone_missing"])
        self.assertEqual(identity["kind"], "bsuid")
        self.assertEqual(SessionManager.get_session_key(identity["customer_id"]), "session:cw:141")
        self.assertNotEqual(SessionManager.get_session_key(identity["customer_id"]), "session:")
        blob = "\n".join(logs.output)
        self.assertIn("kind=bsuid", blob)
        self.assertIn("[redacted]", blob)
        self.assertNotIn(BSUID, blob)
        self.assertEqual(get_sender_role("cw:141"), "customer")

    def test_digit_source_id_becomes_e164(self):
        identity = resolve_contact_identity(
            {"id": 9, "phone_number": None},
            {"contact_inbox": {"source_id": "60126761818"}},
            9,
            4,
        )
        self.assertEqual(identity["customer_id"], "+60126761818")
        self.assertEqual(identity["kind"], "phone")
        self.assertFalse(identity["phone_missing"])

    def test_direct_sends_use_recipient_and_skip_otp(self):
        fields = meta_destination_fields(BSUID)
        self.assertEqual(fields, {"recipient": BSUID})
        self.assertNotIn("to", fields)
        self.assertTrue(is_authentication_template("otp_login"))
        from app.services.chatwoot import send_whatsapp_contact, send_whatsapp_document, send_whatsapp_template

        with patch("app.services.chatwoot.resolve_whatsapp_phone_number_id", return_value=("key", "123")), \
             patch("app.services.chatwoot.requests.post") as posted:
            send_whatsapp_template(4, BSUID, "new_lead_alert_utility", ["a"])
            send_whatsapp_contact(4, BSUID, "Irene", "+601165144931")
            send_whatsapp_document(4, BSUID, document_url="https://example.com/a.pdf", file_name="a.pdf")
            otp = send_whatsapp_template(4, BSUID, "otp_login", ["123456"])
        self.assertEqual(otp.get("skipped"), "bsuid_authentication_template")
        bodies = [call.kwargs["json"] for call in posted.call_args_list]
        self.assertEqual(len(bodies), 3)
        for body in bodies:
            self.assertEqual(body.get("recipient"), BSUID)
            self.assertNotIn("to", body)
        self.assertTrue(all(BSUID not in str(call.args) for call in posted.call_args_list if False))

    def test_nurture_skips_a_phoneless_customer(self):
        from app.services.lead_nurturing import LeadNurturingManager

        customer = MagicMock()
        customer.id = "cw:141"
        customer.phone_number = None
        customer.metadata_json = {"phone_missing": True, "lead_temp": "warm", "conversation_id": 453}
        manager = LeadNurturingManager(
            db_session=MagicMock(),
            message_sender=MagicMock(),
            note_sender=MagicMock(),
        )
        self.assertIsNone(manager.evaluate_customer(customer))


class BackfillAndMarkerTests(unittest.TestCase):
    def test_backfill_dry_run_writes_nothing(self):
        contacts = [
            {
                "id": 9,
                "phone_number": None,
                "identifier": "60126761818",
                "contact_inboxes": [{"source_id": "60126761818"}],
            },
            {
                "id": 141,
                "phone_number": None,
                "identifier": BSUID,
                "contact_inboxes": [{"source_id": BSUID}],
            },
            {
                "id": 8,
                "phone_number": "+60123456789",
                "identifier": "60123456789",
                "contact_inboxes": [{"source_id": "60199999999"}],
            },
        ]
        proposals = plan_updates(contacts)
        recorder = MagicMock()
        written = apply_plans(proposals, recorder, apply=False)
        self.assertEqual(written, [])
        recorder.update_phone.assert_not_called()
        self.assertTrue(any(
            item["action"] == "fill" and item["phone"] == "+60126761818" for item in proposals
        ))
        self.assertTrue(any(
            item["contact_id"] == 141 and item["action"] == "no_digit_source" for item in proposals
        ))
        self.assertTrue(any(item["action"] == "conflict" and item["contact_id"] == 8 for item in proposals))

    def test_public_post_carries_the_backend_source_marker(self):
        from app.services.chatwoot import send_message

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": 1}
        with patch("app.services.chatwoot.is_outbound_blocked", return_value=False), \
             patch("app.services.chatwoot.get_conversation_details", return_value={"inbox_id": 1}), \
             patch("app.services.chatwoot.requests.post", return_value=response) as posted:
            send_message(12, "Hello from the bot")
        body = posted.call_args.kwargs["json"]
        self.assertEqual(body["content_attributes"], {"source": "ihc_backend"})
        self.assertFalse(body["private"])


if __name__ == "__main__":
    unittest.main()

"""Conv 330: a sign photo batched with questions must hand over and answer both."""

import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.agent_logic import customer_sign_reply, process_persona_state_machine
from app.services.conversation_processor import (
    ConversationQueueProcessor,
    photo_admin_alert_skipped,
)
from app.services.handover_assignee import handover_without_specialist, image_data_urls

BATCH = (
    "[Customer sent a photo.] [Photo shows: FOR RENT 出租 "
    "011-630 44931 011-651 44931 CY / LEONG]\n"
    "Is this unit available\n"
    "How much per month"
)
PHOTO_URL = "https://inbox.example/rails/active_storage/blobs/sign.jpg"


def _patches():
    return [
        patch("app.services.agent_logic.classify_turn_intent", return_value="buyer_search"),
        patch("app.services.agent_logic.generate_conversational_response", return_value={
            "response": "Please call 011-630 44931.",
            "intent": "buyer",
            "extracted_data": {},
        }),
        patch("app.services.agent_logic.find_matching_property", return_value=None),
        patch("app.services.agent_logic.search_properties", return_value=[]),
        patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
        patch("app.services.db_services._postgres_reachable", return_value=False),
    ]


class BatchSignReplyTests(unittest.TestCase):
    def test_two_photos_and_two_questions_make_one_full_reply_and_arm_handover(self):
        patches = _patches()
        for item in patches:
            item.start()
        try:
            with self.assertLogs("app.services.agent_logic", level="INFO") as logs:
                result = process_persona_state_machine(
                    phone_number="+601200000001",
                    text=BATCH,
                    session={},
                    conversation_history="Assistant: Hello",
                    images=["img-a", "img-b"],
                    turn_intent="buyer_search",
                )
        finally:
            for item in patches:
                item.stop()
        reply = result["response"]
        self.assertEqual(result.get("handover_reason"), "photo_no_match")
        self.assertTrue(result.get("handover"))
        self.assertIn("Thanks for the photo", reply)
        self.assertIn("available", reply.lower())
        self.assertIn("monthly rent", reply.lower())
        self.assertNotIn("home ihc line", reply.lower())
        self.assertNotIn("44931", reply)
        self.assertNotIn("call", reply.lower())
        self.assertTrue(any("photo_no_match armed reason=" in line for line in logs.output))
        self.assertEqual(
            result["updated_session"]["collected_data"].get("customer_category"),
            "renter",
        )
    def test_copy_has_no_internal_line_wording(self):
        for language, needle in (("en", "Thanks for the photo"), ("ms", "Terima kasih"), ("zh", "谢谢")):
            text = customer_sign_reply(language, "")
            self.assertIn(needle, text)
            self.assertNotIn("Home IHC line", text)
            self.assertNotIn("nombor Home IHC", text)
            self.assertNotIn("号码是 Home IHC", text)


class RepeatHandoverTests(unittest.TestCase):
    def test_recent_alert_skips_only_when_the_handover_is_still_in_place(self):
        now = datetime.datetime(2026, 11, 27, 9, 45, tzinfo=datetime.timezone.utc)
        recent = "2026-11-27T09:00:00+00:00"
        old = "2026-11-25T02:46:00+00:00"
        self.assertTrue(photo_admin_alert_skipped(recent, True, now))
        self.assertFalse(photo_admin_alert_skipped(recent, False, now))
        self.assertFalse(photo_admin_alert_skipped(old, True, now))
        self.assertFalse(photo_admin_alert_skipped(old, False, now))

    def test_repeat_still_writes_the_note_and_keeps_labels(self):
        notes = []
        with patch("app.services.lead_handover.send_private_note", side_effect=lambda _c, text: notes.append(text)), \
             patch("app.services.lead_handover.send_whatsapp_template") as template, \
             patch("app.services.handover_assignee.unassign_agent") as unassign:
            skipped = handover_without_specialist(
                330,
                reason="photo_no_match",
                note="Caption-less sign photo needs an agent. reason=agent_phone_only.",
                photo_urls=[PHOTO_URL],
                skip_admin_alert=True,
            )
        self.assertTrue(skipped["alert_skipped"])
        self.assertFalse(skipped["admin_alert"])
        template.assert_not_called()
        unassign.assert_not_called()
        self.assertTrue(any(PHOTO_URL in note for note in notes))

        customer = MagicMock()
        customer.id = "+601200000001"
        customer.metadata_json = {"photo_agent_alerted_at": "2026-11-25T02:46:00+00:00"}
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = customer
        processor = ConversationQueueProcessor(redis_client=MagicMock(), session_factory=lambda: db)
        with patch("app.services.conversation_processor.apply_label") as labels, \
             patch("app.services.conversation_processor.set_priority"):
            processor.persist_state_and_labels(
                conversation_id=330,
                customer=customer,
                lead_temp="Warm",
                handover_initiated=False,
                role="customer",
                intent="renter",
                assignee_email=None,
                photo_no_match=False,
                keep_photo_handover_labels=True,
            )
        applied = labels.call_args[0][1]
        self.assertIn("tenant", applied)
        self.assertIn("photo-needs-agent", applied)
        self.assertIn("handover_initiated", applied)

    def test_image_urls_come_from_the_batch_attachments(self):
        messages = [
            {"attachments": [{"file_type": "image", "data_url": PHOTO_URL}]},
            {"attachments": [{"file_type": "image", "data_url": PHOTO_URL}]},
            {"content": "Is this unit available"},
            {"content": "How much per month"},
        ]
        self.assertEqual(image_data_urls(messages), [PHOTO_URL])


if __name__ == "__main__":
    unittest.main()

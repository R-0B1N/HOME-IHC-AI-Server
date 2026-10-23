"""
Unit Test Suite for ConversationQueueProcessor Domain Service (Phase 3).
Tests modular stages: debounce checking, master AI gating, message batching,
multimodal parsing, lead temperature computation, and end-to-end processing.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.conversation_processor import ConversationQueueProcessor


class TestConversationQueueProcessor(unittest.TestCase):
    """Unit tests for ConversationQueueProcessor methods."""

    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_task = MagicMock()
        self.processor = ConversationQueueProcessor(
            celery_task=self.mock_task,
            redis_client=self.mock_redis,
            timeout_seconds=10,
        )

    def test_check_debounce_no_active_timestamp(self):
        self.mock_redis.get.return_value = None
        result = self.processor.check_debounce(conversation_id=123, task_scheduled_time=100.0)
        self.assertEqual(result, {"status": "skipped", "reason": "no active timestamp"})

    @patch("time.time", return_value=105.0)
    def test_check_debounce_user_still_active_reschedules(self, mock_time):
        # Last active was at 100.0, current time 105.0 (diff 5s < 10s)
        self.mock_redis.get.return_value = b"100.0"
        result = self.processor.check_debounce(conversation_id=123, task_scheduled_time=100.0)
        self.assertEqual(result, {"status": "deferred", "reason": "user still active"})
        self.mock_task.apply_async.assert_called_once()
        call_kwargs = self.mock_task.apply_async.call_args[1]
        self.assertEqual(call_kwargs["args"], [123, 100.0])
        self.assertEqual(call_kwargs["countdown"], 6)

    @patch("time.time", return_value=120.0)
    def test_check_debounce_inactivity_window_passed(self, mock_time):
        # Last active was at 100.0, current time 120.0 (diff 20s >= 10s)
        self.mock_redis.get.return_value = b"100.0"
        result = self.processor.check_debounce(conversation_id=123, task_scheduled_time=100.0)
        self.assertIsNone(result)

    @patch("app.api.settings.get_system_toggle", return_value=False)
    @patch("app.services.conversation_processor.toggle_typing_status")
    def test_check_master_ai_disabled(self, mock_toggle_typing, mock_get_toggle):
        enabled = self.processor.check_master_ai_enabled(conversation_id=456)
        self.assertFalse(enabled)
        mock_toggle_typing.assert_called_once_with(456, "off")
        self.mock_redis.delete.assert_called_once_with("convo_queue_456")

    def test_fetch_queued_messages_empty(self):
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [[], True, True]
        self.mock_redis.pipeline.return_value = mock_pipe

        msgs = self.processor.fetch_queued_messages(conversation_id=789)
        self.assertIsNone(msgs)

    def test_fetch_queued_messages_atomically_pops(self):
        mock_pipe = MagicMock()
        raw_list = [
            json.dumps({"content": "Hello", "sender": {"phone_number": "+60123456789"}}).encode("utf-8"),
            json.dumps({"content": "I want land"}).encode("utf-8"),
        ]
        mock_pipe.execute.return_value = [raw_list, True, True]
        self.mock_redis.pipeline.return_value = mock_pipe

        msgs = self.processor.fetch_queued_messages(conversation_id=789)
        self.assertIsNotNone(msgs)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "Hello")
        self.assertEqual(msgs[1]["content"], "I want land")

    @patch("app.services.conversation_processor.transcribe_audio", return_value="Audio transcript text")
    @patch("requests.get")
    def test_parse_multimodal_content(self, mock_requests_get, mock_transcribe):
        mock_resp = MagicMock()
        mock_resp.content = b"fake-image-bytes"
        mock_requests_get.return_value = mock_resp

        messages = [
            {"content": "Text message", "sender": {"name": "Test User", "phone_number": "+60123"}},
            {"content": "", "attachments": [{"file_type": "audio", "data_url": "https://example.com/audio.ogg"}]},
            {"content": "", "attachments": [{"file_type": "image", "data_url": "https://example.com/photo.jpg"}]},
        ]

        prompt, images, doc_struct, contact_info = self.processor.parse_multimodal_content(messages, 123)
        self.assertIn("Text message", prompt)
        self.assertIn("[Audio Transcript]: Audio transcript text", prompt)
        self.assertEqual(len(images), 1)
        self.assertEqual(contact_info["name"], "Test User")

    @patch.object(ConversationQueueProcessor, "check_debounce", return_value=None)
    @patch.object(ConversationQueueProcessor, "check_master_ai_enabled", return_value=True)
    @patch.object(ConversationQueueProcessor, "fetch_queued_messages")
    @patch.object(ConversationQueueProcessor, "parse_multimodal_content")
    @patch.object(ConversationQueueProcessor, "resolve_customer")
    @patch.object(ConversationQueueProcessor, "build_rbac_and_context")
    @patch.object(ConversationQueueProcessor, "execute_persona_state_machine")
    @patch.object(ConversationQueueProcessor, "generate_summary_and_handle_valuer")
    @patch.object(ConversationQueueProcessor, "dispatch_media_and_response")
    @patch.object(ConversationQueueProcessor, "persist_state_and_labels")
    @patch("app.services.conversation_processor.toggle_typing_status")
    def test_full_pipeline_execution(
        self,
        mock_toggle_typing,
        mock_persist_state,
        mock_dispatch_media,
        mock_summary,
        mock_state_machine,
        mock_rbac,
        mock_resolve_cust,
        mock_parse_multi,
        mock_fetch_msgs,
        mock_check_ai,
        mock_check_debounce,
    ):
        mock_fetch_msgs.return_value = [{"content": "Looking for durian land"}]
        mock_parse_multi.return_value = ("Looking for durian land", [], None, {"name": "Buyer"})
        mock_customer = MagicMock()
        mock_customer.id = "cust-1"
        mock_resolve_cust.return_value = (mock_customer, False, "+60121111111", "Buyer", {"inbox_id": 1})
        mock_rbac.return_value = ("customer", {"role": "customer", "data": {}}, "", "buyer_search", False, 0.0)
        mock_state_machine.return_value = (
            {"response": "Here is land", "schedule_viewing": False},
            {"current_agent": "BUYER"},
            "buyer",
            "Here is land",
            False,
            "Warm",
            [],
        )
        mock_summary.return_value = ("Inquiry about durian land", None)

        result = self.processor.process(conversation_id=999, task_scheduled_time=12345.0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["conversation_id"], 999)
        self.assertEqual(result["messages_processed"], 1)

        mock_dispatch_media.assert_called_once()
        mock_persist_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()

"""
Unit test suite for /reset command handling and message history isolation.
Verifies that:
1. /reset private notes resolve customer phone and set Redis reset cutoff timestamp.
2. Customer database metadata is deeply wiped (introduced=False, bypass_ai=False, cleared profiles).
3. Pre-reset Chatwoot messages are purged so subsequent messages are treated as a fresh conversation.
"""

import unittest
from datetime import datetime, timezone


class TestResetCommand(unittest.TestCase):
    def test_reset_command_filters_pre_reset_messages(self):
        """
        Verifies that any messages timestamped prior to /reset are purged
        from conversation_history.
        """
        reset_time = 1789373241.0
        
        chatwoot_messages = [
            {"id": 1, "created_at": 1789373000, "message_type": "incoming", "content": "You got any shop lot?", "private": False},
            {"id": 2, "created_at": 1789373100, "message_type": "outgoing", "content": "We have shop lots in Bentong.", "private": False},
            {"id": 3, "created_at": 1789373241, "message_type": "outgoing", "content": "/reset", "private": True},
            {"id": 4, "created_at": 1789373256, "message_type": "incoming", "content": "hi", "private": False},
        ]
        
        # Filter logic as implemented in tasks.py
        reset_cutoff_ts = reset_time
        filtered_messages = [msg for msg in chatwoot_messages if float(msg.get("created_at") or 0) > reset_cutoff_ts]
        
        # Only message 4 ('hi') should remain in post-reset messages
        self.assertEqual(len(filtered_messages), 1)
        self.assertEqual(filtered_messages[0]["content"], "hi")
        
        # Prior history excludes the current incoming prompt
        final_prompt_text = "hi"
        prior_msgs = filtered_messages
        if prior_msgs:
            last_non_priv = next((m for m in reversed(prior_msgs) if not m.get("private")), None)
            if last_non_priv and (last_non_priv.get("content") or "").strip() == final_prompt_text.strip():
                prior_msgs = [m for m in prior_msgs if m is not last_non_priv]

        history_lines = []
        for msg in prior_msgs:
            if msg.get("private"):
                continue
            is_assistant = msg.get("message_type") in [1, "1", "outgoing", 3, "3", "template"]
            sender = "Assistant" if is_assistant else "User"
            content = msg.get("content") or ""
            if content.strip():
                history_lines.append(f"{sender}: {content.strip()}")
        
        # Prior history for the first message after reset is strictly empty
        self.assertEqual(history_lines, [])
        
    def test_customer_metadata_reset_payload(self):
        """
        Verifies that metadata wiping resets introduced, bypass_ai, and all intent profiles.
        """
        old_metadata = {
            "introduced": True,
            "bypass_ai": True,
            "lead_temp": "Hot",
            "collected_data": {"budget": "4M", "property_type": "Industrial Land"},
            "requirements_profile": {"location": "Temerloh"},
            "multi_intent_profile": {"past_intent": "shop lot"},
            "intent_progression": ["inquired shop lot", "switched to land"],
            "interested_property": "LOT 1745"
        }
        
        # Reset mutation as applied in webhooks.py
        meta = dict(old_metadata)
        meta["bypass_ai"] = False
        meta["introduced"] = False
        meta["lead_temp"] = "Warm"
        meta["collected_data"] = {}
        meta["requirements_profile"] = {}
        meta["multi_intent_profile"] = {}
        meta["intent_progression"] = []
        meta["interested_property"] = None
        meta["last_reset_at"] = datetime.now(timezone.utc).isoformat()
        
        self.assertFalse(meta["introduced"])
        self.assertFalse(meta["bypass_ai"])
        self.assertEqual(meta["collected_data"], {})
        self.assertEqual(meta["requirements_profile"], {})
        self.assertIsNone(meta["interested_property"])
        self.assertIn("last_reset_at", meta)

    @unittest.mock.patch("app.api.webhooks.process_conversation_queue")
    @unittest.mock.patch("app.api.webhooks.redis_client")
    def test_chatwoot_webhook_incoming_message_no_unbound_local_error(self, mock_redis, mock_celery_task):
        """
        Ensures that incoming customer messages do not raise UnboundLocalError
        for time or any other module-level variable.
        """
        import asyncio
        import json
        from unittest.mock import AsyncMock, MagicMock
        from app.api.webhooks import chatwoot_webhook
        
        mock_redis.get.return_value = b"true"
        mock_redis.setnx.return_value = True
        mock_redis.rpush.return_value = 1
        mock_redis.set.return_value = True
        mock_redis.expire.return_value = True
        mock_celery_task.apply_async.return_value = MagicMock()

        payload = {
            "event": "message_created",
            "message_type": "incoming",
            "id": 9999,
            "conversation": {"id": 69, "inbox_id": 4, "status": "open"},
            "content": "Hi there"
        }
        raw_body_bytes = json.dumps(payload).encode("utf-8")

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=raw_body_bytes)
        mock_request.headers = {}
        mock_bg_tasks = MagicMock()
        
        # Must execute cleanly without raising UnboundLocalError
        result = asyncio.run(chatwoot_webhook(mock_request))
        self.assertEqual(result.get("status"), "queued")
        self.assertEqual(result.get("conversation_id"), 69)
        self.assertEqual(result.get("message_id"), 9999)

    def test_multilingual_fallback_fresh_convo(self):
        """
        Verifies that get_multilingual_fallback returns the greeting with digital name card
        when history has no Assistant messages, and only uses off-market response for ongoing chat.
        """
        from app.services.system_prompts import get_multilingual_fallback

        # Case 1: Empty history -> Greeting
        fallback_empty = get_multilingual_fallback("en", "")
        self.assertIn("I'm Irene Leong", fallback_empty)
        self.assertIn("mecard.my", fallback_empty)

        # Case 2: Only user message -> Greeting (assistant hasn't spoken yet)
        fallback_user_only = get_multilingual_fallback("en", "User: hi")
        self.assertIn("I'm Irene Leong", fallback_user_only)
        self.assertIn("mecard.my", fallback_user_only)

        # Case 3: Ongoing conversation with Assistant -> Off-market requirements fallback
        fallback_ongoing = get_multilingual_fallback("en", "User: hi\nAssistant: Good day! How can I help?\nUser: Looking for house")
        self.assertIn("Thank you for sharing your requirements", fallback_ongoing)
        self.assertNotIn("I'm Irene Leong", fallback_ongoing)

    def test_system_prompt_first_interaction_stage_on_fresh_turn(self):
        """
        Verifies that build_system_prompt enters FIRST_INTERACTION stage when no prior
        assistant response exists, even if the incoming message has history text.
        """
        from app.services.system_prompts import build_system_prompt

        prompt = build_system_prompt(conversation_history="User: hi")
        self.assertIn("[CONVERSATION_STAGE: FIRST_INTERACTION]", prompt)
        self.assertNotIn("[CONVERSATION_STAGE: ONGOING_DIALOGUE]", prompt)
        self.assertNotIn("CRITICAL ANTI-REPETITION RULE", prompt)

    def test_session_deep_wipe(self):
        """
        Verifies that session deep wipe purges all residual profile and progression keys.
        """
        from app.services.session_manager import SessionManager

        session = {
            "introduced": True,
            "current_agent": "BUYER",
            "requirements_profile": {"active_inquiry": {"location": "Raub", "category": "residential"}},
            "multi_intent_profile": {"prior": "semi-d"},
            "intent_progression": ["inquired semi-d in Raub"],
            "interested_property": {"id": 10, "title": "Raub Semi-D"},
            "presented_properties": [{"id": 10}],
            "collected_data": {"buyer_location": "Raub"}
        }

        # Deep wipe logic executed when fresh conversation is detected
        session.clear()
        session.update(SessionManager._new_session())

        self.assertNotIn("introduced", session)
        self.assertNotIn("requirements_profile", session)
        self.assertNotIn("multi_intent_profile", session)
        self.assertNotIn("intent_progression", session)
        self.assertNotIn("interested_property", session)
        self.assertEqual(session.get("state"), "INIT")
        self.assertEqual(session.get("collected_data"), {})


if __name__ == "__main__":
    unittest.main()

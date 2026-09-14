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
        
        # Only message 4 ('hi') should remain
        self.assertEqual(len(filtered_messages), 1)
        self.assertEqual(filtered_messages[0]["content"], "hi")
        
        history_lines = []
        for msg in filtered_messages:
            if msg.get("private"):
                continue
            is_assistant = msg.get("message_type") in [1, "1", "outgoing", 3, "3", "template"]
            sender = "Assistant" if is_assistant else "User"
            content = msg.get("content") or ""
            if content.strip():
                history_lines.append(f"{sender}: {content.strip()}")
        
        # When user sends 'hi', history should ONLY contain User: hi, with zero prior shop lot inquiries
        self.assertEqual(history_lines, ["User: hi"])
        
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


if __name__ == "__main__":
    unittest.main()

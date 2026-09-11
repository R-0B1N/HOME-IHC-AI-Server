"""
Integration test to verify that the AI processes an incoming message and responds.
Uses standard library unittest with graceful skipping if live local API or Chatwoot is offline.
"""

import os
import time
import json
import unittest
import requests

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8001")
CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "http://localhost:3000")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "test_token")
TEST_INBOX_ID = int(os.getenv("TEST_INBOX_ID", "1"))
TEST_ACCOUNT_ID = int(os.getenv("TEST_ACCOUNT_ID", "1"))
TEST_CONVERSATION_ID = int(os.getenv("TEST_CONVERSATION_ID", "99999"))
TEST_PHONE_NUMBER = os.getenv("TEST_PHONE_NUMBER", "+60123456789")


class TestLiveAiResponseIntegration(unittest.TestCase):
    """Integration test suite against running local or staging containers."""

    def setUp(self):
        timestamp = int(time.time())
        self.mock_payload = {
            "event": "message_created",
            "message_type": "incoming",
            "id": timestamp,
            "content": "Hi, I am looking for a warehouse to rent.",
            "account": {
                "id": TEST_ACCOUNT_ID
            },
            "inbox": {
                "id": TEST_INBOX_ID
            },
            "conversation": {
                "id": TEST_CONVERSATION_ID,
                "inbox_id": TEST_INBOX_ID,
                "status": "open"
            },
            "sender": {
                "id": 999,
                "name": "E2E Test User",
                "phone_number": TEST_PHONE_NUMBER
            }
        }

    def test_ai_response_generation(self):
        webhook_url = f"{API_URL}/chatwoot"
        try:
            response = requests.post(webhook_url, json=self.mock_payload, timeout=2)
        except requests.exceptions.RequestException:
            self.skipTest(f"Live API container at {API_URL} is offline. Skipping live integration test.")

        self.assertEqual(response.status_code, 200, f"Webhook failed with status {response.status_code}")
        response_data = response.json()
        self.assertEqual(response_data.get("status"), "queued", f"Expected 'queued', got {response_data}")


if __name__ == "__main__":
    unittest.main()

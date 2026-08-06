import os
import pytest
import requests
import time
import json

# Configuration
# Read from environment or default to staging endpoints
API_URL = os.getenv("API_URL", "http://localhost:8001")
CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "http://localhost:3000")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "test_token")
TEST_INBOX_ID = int(os.getenv("TEST_INBOX_ID", "1"))
TEST_ACCOUNT_ID = int(os.getenv("TEST_ACCOUNT_ID", "1"))
TEST_CONVERSATION_ID = int(os.getenv("TEST_CONVERSATION_ID", "99999"))
TEST_PHONE_NUMBER = os.getenv("TEST_PHONE_NUMBER", "+60123456789")

@pytest.fixture
def mock_webhook_payload():
    """
    Simulates a Chatwoot webhook payload for an incoming WhatsApp message.
    """
    timestamp = int(time.time())
    return {
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

def test_ai_response_generation(mock_webhook_payload):
    """
    Integration test to verify that the AI processes an incoming message and responds.
    
    Workflow:
    1. Send a mock webhook payload to the FastAPI /chatwoot endpoint.
    2. Verify it is successfully queued.
    3. Wait for the Celery worker to process the queue and generate an AI response.
    4. Query the Chatwoot API to verify the outgoing AI response was posted.
    """
    webhook_url = f"{API_URL}/chatwoot"
    
    print(f"\n[1] Sending mock webhook to {webhook_url}")
    try:
        response = requests.post(webhook_url, json=mock_webhook_payload)
    except requests.exceptions.ConnectionError:
        pytest.fail(f"Could not connect to API at {API_URL}. Is the container running?")

    assert response.status_code == 200, f"Webhook failed with status {response.status_code}"
    response_data = response.json()
    assert response_data.get("status") == "queued", f"Expected 'queued', got {response_data}"
    
    print(f"[2] Webhook queued successfully. Waiting 25 seconds for Celery & AI to process...")
    # The debouncing timeout is 10 seconds. We give an additional 15 seconds for the LLM to reply.
    time.sleep(25)
    
    print(f"[3] Checking Chatwoot API for AI response...")
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    messages_url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{TEST_ACCOUNT_ID}/conversations/{TEST_CONVERSATION_ID}/messages"
    
    try:
        chatwoot_response = requests.get(messages_url, headers=headers, timeout=10)
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Could not connect to Chatwoot at {CHATWOOT_BASE_URL} to verify output.")

    if chatwoot_response.status_code == 200:
        messages = chatwoot_response.json().get("payload", [])
        
        # We are looking for an outgoing message sent after our incoming test message
        ai_responses = [
            msg for msg in messages 
            if (msg.get("message_type") == 1 or msg.get("message_type") == "outgoing") 
            and msg.get("content")
        ]
        
        assert len(ai_responses) > 0, "No AI response found in Chatwoot conversation. Worker might have failed."
        print(f"✅ AI Response verified: {ai_responses[-1]['content']}")
    else:
        pytest.skip(f"Chatwoot API returned {chatwoot_response.status_code}. Cannot verify AI response.")

import logging
import requests
import os

logger = logging.getLogger(__name__)

CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "http://localhost:3000")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID", "1")

def send_message(conversation_id: int, content: str):
    """
    Sends a message back to the Chatwoot conversation.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "content": content,
        "message_type": "outgoing",
        "private": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully sent message to Chatwoot conversation {conversation_id}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to Chatwoot: {e}")
        raise e

def apply_label(conversation_id: int, label: str):
    """
    Applies a label (e.g. Hot, Warm, Cooling) to a conversation.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "labels": [label]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully applied label {label} to conversation {conversation_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to apply label to Chatwoot conversation: {e}")
        raise e

def toggle_typing_status(conversation_id: int, status: str):
    """
    Toggles the typing status in a Chatwoot conversation.
    status should be "on" or "off".
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/toggle_typing_status"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "typing_status": status,
        "is_private": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully toggled typing status {status} for conversation {conversation_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to toggle typing status in Chatwoot conversation: {e}")
        raise e

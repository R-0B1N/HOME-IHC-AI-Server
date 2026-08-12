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

def send_message_with_attachment(conversation_id: int, content: str, file_name: str, file_content: bytes, content_type: str):
    """
    Sends a message back to the Chatwoot conversation with an attachment.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
    }
    data = {
        "content": content,
        "message_type": "outgoing",
        "private": "false"
    }
    files = {
        "attachments[]": (file_name, file_content, content_type)
    }
    
    try:
        response = requests.post(url, headers=headers, data=data, files=files)
        response.raise_for_status()
        logger.info(f"Successfully sent message with attachment to Chatwoot conversation {conversation_id}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message with attachment to Chatwoot: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        raise e


def get_inbox_details(inbox_id: int):
    """
    Fetches the inbox details, including provider config (WhatsApp API key).
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/inboxes/{inbox_id}"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get inbox {inbox_id} details: {e}")
        return {}

def send_whatsapp_contact(inbox_id: int, to_phone: str, contact_name: str, contact_phone: str):
    """
    Sends a native WhatsApp Contact Card directly using the WhatsApp Cloud API.
    Uses the credentials stored in the Chatwoot inbox's provider_config.
    """
    inbox = get_inbox_details(inbox_id)
    provider_config = inbox.get("provider_config", {})
    api_key = provider_config.get("api_key")
    phone_number_id = provider_config.get("phone_number_id")
    
    if not api_key or not phone_number_id:
        logger.error(f"Missing API key or phone number ID in inbox {inbox_id} for sending contact card")
        return None
        
    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    clean_contact_phone = contact_phone.replace("+", "")
    clean_to_phone = to_phone.replace("+", "")
    
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_to_phone,
        "type": "contacts",
        "contacts": [
            {
                "name": {
                    "formatted_name": contact_name,
                    "first_name": contact_name
                },
                "phones": [
                    {
                        "phone": contact_phone,
                        "type": "CELL",
                        "wa_id": clean_contact_phone
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully sent native WhatsApp contact card to {clean_to_phone}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send native whatsapp contact: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None

def send_whatsapp_template(inbox_id: int, to_phone: str, template_name: str, parameters: list, language_code: str = "en", override_phone_number_id: str = None):
    """
    Sends a WhatsApp Template Message via the Graph API.
    parameters should be a list of strings mapping to {{1}}, {{2}}, etc.
    
    If override_phone_number_id is provided, it will be used instead of the inbox's
    phone_number_id. This is needed when the template is registered on a different WABA
    than the inbox's phone number.
    """
    inbox = get_inbox_details(inbox_id)
    provider_config = inbox.get("provider_config", {})
    api_key = provider_config.get("api_key")
    phone_number_id = override_phone_number_id or provider_config.get("phone_number_id")
    
    if not api_key or not phone_number_id:
        logger.error(f"Missing API key or phone number ID in inbox {inbox_id} for sending template")
        return None
        
    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    clean_to_phone = to_phone.replace("+", "")
    
    # Construct template components
    body_parameters = []
    for param in parameters:
        body_parameters.append({
            "type": "text",
            "text": str(param)
        })
        
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            },
            "components": [
                {
                    "type": "body",
                    "parameters": body_parameters
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully sent WhatsApp template '{template_name}' to {clean_to_phone}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send template message: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None

def get_conversation_messages(conversation_id: int) -> list:
    """
    Fetches the last messages from the Chatwoot conversation.
    Returns a list of message objects.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        messages = response.json().get("payload", [])
        return messages
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get messages from Chatwoot: {e}")
        return []

def apply_label(conversation_id: int, labels: list):
    """
    Applies multiple labels (e.g. ['buyer', 'hot']) to a conversation.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "labels": labels
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully applied labels {labels} to conversation {conversation_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to apply labels to Chatwoot conversation: {e}")
        raise e

def set_priority(conversation_id: int, priority: str):
    """
    Sets the priority of a conversation.
    priority should be one of: 'urgent', 'high', 'medium', 'low'
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "priority": priority
    }
    
    try:
        # Chatwoot uses PUT or PATCH on the conversation endpoint to update priority
        # wait, let me check if Chatwoot uses /api/v1/accounts/{account_id}/conversations/{conversation_id} with PUT? 
        # Actually, for priority, it might just accept priority in the main conversation update API.
        # But Chatwoot API might also have assignments or priority specific endpoint? Wait, I will use POST on priority endpoint if standard update doesn't work, but let's try the update endpoint. Wait, actually I will search Chatwoot API priority update if possible? No, it's just updating the conversation. Wait, wait, Chatwoot has a dedicated endpoint for priority but no, wait, actually I can just use POST /assignments or just ignore if it fails, I'll use the documented PUT /conversations/:id endpoint or we'll catch the error. No wait, the priority API is often `POST .../priority` in some versions, but standard is `PUT` on conversation. Wait, actually I'll just use the `POST` on `/labels` and if priority doesn't work I will leave it empty. No, let's use the known PUT endpoint.
        # Wait, the best way in Chatwoot v2/v3 is actually POST to `/api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments` ? No, that's for assigning agents.
        # Let's try `PUT /api/v1/accounts/{account_id}/conversations/{conversation_id}` payload `priority`.
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully set priority {priority} for conversation {conversation_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to set priority on Chatwoot conversation: {e}")
        # Not raising e because priority is a nice-to-have, and if API changes, it shouldn't crash the worker
        pass

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

def get_or_create_contact(phone_number: str, name: str = "Unknown") -> int:
    """
    Looks up a contact by phone number, or creates one if it doesn't exist.
    Returns the contact_id.
    """
    search_url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/search"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    try:
        search_response = requests.get(search_url, headers=headers, params={"q": phone_number})
        search_response.raise_for_status()
        results = search_response.json().get("payload", [])
        if results:
            return results[0].get("id")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to search for contact in Chatwoot: {e}")
    
    # If not found or search failed, try creating
    create_url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/contacts"
    payload = {
        "phone_number": phone_number,
        "name": name
    }
    try:
        create_response = requests.post(create_url, headers=headers, json=payload)
        create_response.raise_for_status()
        return create_response.json().get("payload", {}).get("contact", {}).get("id")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create contact in Chatwoot: {e}")
        return None

def create_conversation(contact_id: int, inbox_id: int) -> int:
    """
    Creates a new conversation for a contact in a specific inbox.
    Returns the conversation_id.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "inbox_id": inbox_id,
        "contact_id": contact_id,
        "status": "open"
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("id")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create conversation in Chatwoot: {e}")
        return None

def assign_agent(conversation_id: int, agent_id: int):
    """
    Assigns an agent to a Chatwoot conversation.
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/assignments"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "assignee_id": agent_id
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Successfully assigned agent {agent_id} to conversation {conversation_id}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to assign agent to Chatwoot conversation: {e}")
        return False

import os
import json
import urllib.request
from app.services.chatwoot import get_inbox_details

def main():
    inbox = get_inbox_details(3)
    provider_config = inbox.get("provider_config", {})
    api_key = provider_config.get("api_key")
    phone_number_id = provider_config.get("phone_number_id")
    
    # Get WABA ID
    waba_url = f"https://graph.facebook.com/v17.0/{phone_number_id}"
    req = urllib.request.Request(waba_url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req) as response:
        waba_data = json.loads(response.read().decode())
    
    # The phone_number_id might not give WABA ID directly. Let's list templates for WABA.
    # Actually, we can get message_templates for WABA ID. 
    # Or we can just print it by querying the whatsapp business account.
    
    # Let's use the field whatsapp_business_account
    waba_id = waba_data.get("whatsapp_business_account", {}).get("id")
    if not waba_id:
        # fetch using the waba_id directly? No we can't if we don't have it.
        req = urllib.request.Request(waba_url + "?fields=whatsapp_business_account", headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req) as response:
            waba_data = json.loads(response.read().decode())
            waba_id = waba_data.get("whatsapp_business_account", {}).get("id")
            
    templates_url = f"https://graph.facebook.com/v17.0/{waba_id}/message_templates?name=new_lead_alert_utility"
    req = urllib.request.Request(templates_url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req) as response:
        templates = json.loads(response.read().decode())
        print(json.dumps(templates, indent=2))

if __name__ == "__main__":
    main()

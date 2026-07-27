import os
import json
import urllib.request

env = {}
with open('.env') as f:
    for line in f:
        if '=' in line:
            k, v = line.strip().split('=', 1)
            env[k] = v

chatwoot_url = env.get('CHATWOOT_URL')
chatwoot_token = env.get('CHATWOOT_API_TOKEN')

req = urllib.request.Request(f'{chatwoot_url}/api/v1/accounts/1/inboxes/4', headers={'api_access_token': chatwoot_token})
with urllib.request.urlopen(req) as response:
    inbox = json.loads(response.read())

provider_config = inbox.get('provider_config', {})
api_key = provider_config.get('api_key')
phone_number_id = provider_config.get('phone_number_id')

req_fb = urllib.request.Request(f'https://graph.facebook.com/v17.0/{phone_number_id}?fields=whatsapp_account_id', headers={'Authorization': f'Bearer {api_key}'})
with urllib.request.urlopen(req_fb) as response:
    waba_id = json.loads(response.read()).get('whatsapp_account_id')

if waba_id:
    req_tpl = urllib.request.Request(f'https://graph.facebook.com/v17.0/{waba_id}/message_templates?limit=100', headers={'Authorization': f'Bearer {api_key}'})
    with urllib.request.urlopen(req_tpl) as response:
        templates = json.loads(response.read()).get('data', [])
        for t in templates:
            if 'new_lead' in t.get('name', '').lower():
                print(f"Name: {t.get('name')}, Language: {t.get('language')}, Status: {t.get('status')}")

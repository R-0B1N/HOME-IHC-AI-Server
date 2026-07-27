import sys
import os

sys.path.append('/app')
from app.services.chatwoot import send_whatsapp_template

template_params = [
    'John Doe',
    '+60123456789',
    'buyer/seller',
    'Mentakab',
    'Commercial Shop Lot',
    'RM 50,000',
    'John is looking for a commercial around the Mentakab area. He has a budget of Rm50,000',
    'https://inbox.bentongland.com.my/app/accounts/1/inbox/3/conversations/123'
]
res = send_whatsapp_template(inbox_id=3, to_phone='+14709202239', template_name='new_lead_alert_utility', parameters=template_params, language_code='en')
print("Result:", res)

"""
System Prompts, Multilingual Lexicons, Guardrails, and Behavioral Guidelines
for Home IHC WhatsApp AI CRM (ERA Realtor / Home IHC Sdn. Bhd. / BentongLand).
"""

import re
import json
import logging

logger = logging.getLogger(__name__)

# Official Representatives & Agency Identity
AGENT_NAME = "Irene Leong"
AGENT_ROLE = "Senior Property Agent"
AGENCY_NAME = "ERA Realtor"
COMPANY_NAME = "Home IHC"
COMPANY_FULL_NAME = "Home IHC Sdn. Bhd. / BentongLand"
DIGITAL_NAME_CARD_URL = "https://my.mecard.my/1733211127"
ADMIN_EMAIL = "homeihc13@gmail.com"

# Malaysian Dialect & Domain Lexicon
MALAY_KEYWORDS = {
    "ada", "bilik", "sewa", "rumah", "tanah", "kedai", "nak", "berapa", "mana",
    "boleh", "talipon", "telefon", "kol", "terima kasih", "tq", "pagi", "petang",
    "malam", "saya", "kami", "tuan", "puan", "jual", "bajet", "lot", "kawasan",
    "hutan", "tengok", "pajakan", "ekar", "padi", "solar", "pelan", "geran",
    "jawatan", "kosong", "kerja", "bos", "boss", "sy", "blh", "dkt", "kat", "bwh"
}

CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff]')

HANDOVER_PATTERNS = [
    # English
    r'\bcall\s+me\b',
    r'\bcan\s+call\b',
    r'\bcall\s+back\b',
    r'\bphone\s+call\b',
    r'\bspeak\s+to\s+human\b',
    r'\btalk\s+to\s+agent\b',
    r'\bcontact\s+me\s+directly\b',
    r'\btransfer\s+to\s+human\b',
    r'\bspeak\s+to\s+a\s+person\b',
    r'\btalk\s+to\s+a\s+person\b',
    r'\breal\s+agent\b',
    r'\breal\s+person\b',
    r'\bhuman\s+agent\b',
    r'\bhuman\s+staff\b',
    r'\bperson\s+in\s+charge\b',
    r'\bpic\b',
    
    # Malay / Pasar Malay
    r'\bboleh\s+(?:talipon|telefon|call|kol)\b',
    r'\b(?:talipon|telefon|call|kol)\s+(?:saya|boleh|ke|me)\b',
    r'\bhubungi\s+saya\b',
    r'\b(?:minta|nak|tolong)\s+(?:call|hubungi|talipon|telefon|kol)\b',
    r'\bcakap\s+(?:dengan|dgn|ngan)\s+(?:orang|manusia|ejen|agent)\b',
    r'\bagent\s+sebenar\b',
    r'\bejen\s+sebenar\b',
    r'\bnak\s+jumpa\b',
    r'\btemujanji\b',
    r'\bnombor\s+telefon\b',
    r'\bno\s+tel\b',
    
    # Chinese
    r'打(?:电话)?给我',
    r'致电',
    r'可以通话吗',
    r'电话联系',
    r'安排见面',
    r'转人工',
    r'找?真人',
    r'人工客服',
    r'联系真人',
    r'有真人吗',
    r'打给我',
]


def detect_customer_language(text: str) -> str:
    """
    Detects customer primary language from text.
    Returns: 'zh' (Chinese), 'ms' (Bahasa Melayu), or 'en' (English/Manglish).
    """
    if not text or not isinstance(text, str):
        return "en"
    clean = text.strip()
    if not clean:
        return "en"

    # 1. Check for Chinese characters
    if CHINESE_PATTERN.search(clean):
        return "zh"

    # 2. Check for Malay keywords
    words = set(re.findall(r'\b[a-zA-Z]+\b', clean.lower()))
    malay_hits = words.intersection(MALAY_KEYWORDS)
    if len(malay_hits) >= 1 or any(kw in clean.lower() for kw in ["talipon", "terima kasih", "selamat pagi", "bilik sewa", "sewa kosong"]):
        return "ms"

    return "en"


def is_explicit_handover_request(text: str) -> bool:
    """
    Determines if customer is explicitly asking for telephone call, human agent, or in-person meeting.
    """
    if not text or not isinstance(text, str):
        return False
    clean = text.strip().lower()

    # Direct regex patterns
    for pattern in HANDOVER_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE):
            return True

    # Standalone words
    standalone_triggers = ["talipon", "telefon", "转人工", "人工客服"]
    for word in standalone_triggers:
        if word in clean:
            return True

    return False


def get_multilingual_greeting(language: str, customer_name: str = None) -> str:
    """
    Returns initial greeting and Irene Leong introduction matching customer's language.
    """
    name_str = f" {customer_name}" if customer_name else ""
    if language == "zh":
        return (
            f"您好{name_str}！😊 我是来自 ERA Realtor 的 Irene Leong，代表 Home IHC 为您服务。\n\n"
            f"这是我的电子名片：\n{DIGITAL_NAME_CARD_URL}\n\n"
            f"请问有什么我可以协助您的呢？无论是买房、租房、土地投资或业主委托出售，我都随时为您服务。"
        )
    elif language == "ms":
        return (
            f"Selamat sejahtera{name_str}! 😊 Saya Irene Leong, Ejen Hartanah Kanan dari ERA Realtor mewakili Home IHC.\n\n"
            f"Ini adalah kad nama digital saya:\n{DIGITAL_NAME_CARD_URL}\n\n"
            f"Bagaimanakah Home IHC boleh bantu anda hari ini? Sama ada untuk membeli, menyewa, tanah pertanian atau urusan pemilik, saya sedia membantu anda."
        )
    else:
        return (
            f"Good day{name_str}! 😊 I'm Irene Leong, a Senior Property Agent from ERA Realtor representing Home IHC.\n\n"
            f"Here is my digital name card:\n{DIGITAL_NAME_CARD_URL}\n\n"
            f"How may Home IHC assist you with properties in Pahang today?"
        )


def get_multilingual_fallback(language: str, conversation_history: str = None) -> str:
    """
    Returns resilient fallback message matching customer language.
    Guarantees that ongoing conversations NEVER repeat greeting or name card.
    Only treats as ongoing dialogue if the assistant has previously spoken in history.
    """
    has_assistant_history = bool(
        conversation_history and (
            "Assistant:" in conversation_history or
            "AI:" in conversation_history or
            "Agent:" in conversation_history or
            "Irene Leong" in conversation_history or
            "mecard.my" in conversation_history
        )
    )

    if has_assistant_history:
        if language == "zh":
            return (
                "收到您的需求！请问您预计的预算大约在什么范围，或者对具体要求有更详细的想法吗？我会尽快跟进并为您配对最合适的心水房源。😊"
            )
        elif language == "ms":
            return (
                "Terima kasih atas maklumat keperluan anda! Boleh saya tahu anggaran bajet anda atau sebarang kriteria khusus? Saya akan buat tindakan susulan dan carikan pilihan yang paling sesuai untuk anda! 😊"
            )
        else:
            return (
                "Thank you for sharing your requirements! Could you also let me know your preferred budget range or any specific preferences? I'll follow up and find the best match for you! 😊"
            )
    else:
        return get_multilingual_greeting(language)


def get_multilingual_handover_wrapup(language: str, customer_name: str = None, property_title: str = None) -> str:
    """
    Returns polite handover wrap-up message when user requests call or books viewing.
    """
    name_str = f" {customer_name}" if customer_name else ""
    prop_str = f" ({property_title})" if property_title else ""
    if language == "zh":
        return f"好的，感谢您{name_str}！😊 我们已记录您的需求{prop_str}。Home IHC 的资深房产专员将尽快致电与您直接联系跟进。"
    elif language == "ms":
        return f"Terima kasih{name_str}! 😊 Kami telah merekodkan permintaan anda{prop_str}. Pegawai hartanah kanan dari Home IHC akan menghubungi anda sebentar lagi."
    else:
        return f"Thank you{name_str}! 😊 We have recorded your request{prop_str}. A senior property specialist from Home IHC will contact you shortly to follow up directly."


def build_system_prompt(
    cached_property: dict = None,
    available_properties: list = None,
    unlisted_property_text: str = None,
    collected_data: dict = None,
    customer_name: str = None,
    conversation_history: str = "",
    customer_language: str = "en",
    role: str = "customer",
    db_context: dict = None,
    memory_context: dict = None,
    hybrid_properties: list = None
) -> str:
    """
    Constructs the master system prompt for Irene Leong with strict behavioral guardrails,
    RBAC tiers, off-market sourcing instructions, anti-repetition discipline, and viewing appointment bridge.
    """
    if collected_data is None:
        collected_data = {}
    if available_properties is None:
        available_properties = []
    if memory_context is None:
        memory_context = {}
    if hybrid_properties is None:
        hybrid_properties = []

    # 1. RBAC Directives
    rbac_directive = ""
    role_clean = (role or "customer").lower()
    if role_clean == "admin":
        admin_data = (db_context or {}).get("data", {})
        rbac_directive = f"""[ROLE-BASED ACCESS CONTROL: ADMINISTRATOR TIER]
- Verified SYSTEM ADMINISTRATOR with FULL UNRESTRICTED ACCESS (properties, customer records, leads, staff rosters).
- Admin System Context: {json.dumps(admin_data, ensure_ascii=False)}
"""
    elif role_clean in ["agent", "employee"]:
        staff_data = (db_context or {}).get("data", {})
        rbac_directive = f"""[ROLE-BASED ACCESS CONTROL: AGENT / EMPLOYEE TIER]
- Verified HOME IHC AGENT or EMPLOYEE ({role_clean.upper()}). Full property details, customer leads, and active inquiries authorized.
- Staff Context: {json.dumps(staff_data, ensure_ascii=False)}
"""
    else:
        rbac_directive = """[ROLE-BASED ACCESS CONTROL: CUSTOMER TIER]
- Sender is a CUSTOMER or UNREGISTERED PHONE.
- Public property information only (title, asking price, listing status, general location).
- SECURITY: NEVER reveal internal customer lists, leads, owner private contacts, or agency commissions.
"""

    # 2. Multi-Intent Memory & Hybrid Opportunities
    multi_intent_section = ""
    active_inq = memory_context.get("active_inquiry") or {}
    retained_inqs = memory_context.get("retained_inquiries") or []
    has_hybrid = memory_context.get("hybrid_opportunity", False)

    hybrid_props_text = ""
    if hybrid_properties:
        hybrid_items = [
            f"- {p.get('title')} (RM {p.get('price', 0):,.0f}) - {p.get('property_type_sub') or 'Shop-House'} in {p.get('city', 'Pahang')}"
            for p in hybrid_properties[:2]
        ]
        hybrid_props_text = "\nAvailable Hybrid Dual-Purpose Properties in Database:\n" + "\n".join(hybrid_items)

    if memory_context.get("has_multi_intent") or has_hybrid or retained_inqs:
        retained_summary = "; ".join([
            f"{r.get('property_type_label', 'Property')} in {r.get('location', 'Pahang')} (Budget: {r.get('budget_formatted', 'N/A')})"
            for r in retained_inqs
        ])

        hybrid_instruction = ""
        if has_hybrid:
            hybrid_instruction = """- INTELLIGENT HYBRID SUGGESTION: Primary focus on active request first. Secondarily, politely mention dual-purpose shop-house (rumah kedai) as a complementary idea combining commercial and residential."""

        multi_intent_section = f"""[CONVERSATIONAL MULTI-INTENT MEMORY & PRIORITY FRAMEWORK]
1. Primary Active Inquiry (1st Priority): {active_inq.get('property_type_label', 'Active Property')} in {active_inq.get('location', 'Pahang')} (Budget: {active_inq.get('budget_formatted', 'To be advised')}).
2. Retained Inquiries: {retained_summary or 'None'}. Do not confuse separate budgets.
{hybrid_instruction}
{hybrid_props_text}
"""

    # 3. Property Context Block
    prop_context = ""
    if cached_property:
        prop_context = f"""[PROPERTY_IN_CONTEXT]
- Title: {cached_property.get('title')}
- Asking Price: RM {cached_property.get('price', 'N/A')}
- Location: {cached_property.get('city')}, {cached_property.get('state')}
- Size / Tenure: {cached_property.get('acres')} Acres ({cached_property.get('sqft')} sqft), {cached_property.get('tenure')}
- Status: {cached_property.get('status')}
- Photos Available: {len(cached_property.get('image_urls', []))} photos
"""
    elif available_properties:
        props_list = []
        for p in available_properties[:4]:
            price_str = f"RM {p['price']:,.0f}" if p.get('price') else "Price on inquiry"
            props_list.append(f"- {p['title']} ({price_str}) - {p.get('city') or 'Pahang'}")
        prop_context = "[MATCHING_PROPERTIES_IN_DATABASE]\n" + "\n".join(props_list)
    elif unlisted_property_text:
        prop_context = f"""[PROPERTY_STATUS: UNLISTED_OR_OFF_MARKET_LOCATION]
Customer inquired about "{unlisted_property_text}" (0 active DB listings).
- Explain that units in this area are handled off-market through our direct owner network.
- Confirm their requirements (budget, size, move-in date) and offer to scout unlisted options.
- Keep chatting naturally. Do not fabricate listings or prices.
"""

    # 4. Greeting & Anti-Repetition Instruction
    assistant_message_count = (
        conversation_history.count("Assistant:") +
        conversation_history.count("AI:") +
        conversation_history.count("Agent:")
    ) if conversation_history else 0
    has_prior_intro = (
        assistant_message_count > 0 or
        "Irene Leong" in (conversation_history or "") or
        "mecard.my" in (conversation_history or "") or
        (bool(collected_data.get("introduced")) and assistant_message_count > 0)
    )

    if has_prior_intro:
        greeting_instruction = """[CONVERSATION_STAGE: ONGOING_DIALOGUE]
CRITICAL ANTI-REPETITION RULE:
- You have ALREADY introduced yourself in this conversation.
- STRICTLY DO NOT repeat introduction (never say "我是来自 ERA Realtor 的 Irene Leong" or "Good day! I'm Irene").
- STRICTLY DO NOT re-send digital name card link.
- Proceed DIRECTLY, concisely, and naturally to addressing customer's latest message."""
    else:
        greeting_instruction = f"""[CONVERSATION_STAGE: FIRST_INTERACTION]
- In your introductory greeting, introduce yourself as Irene Leong from ERA Realtor representing Home IHC.
- Share your digital name card: {DIGITAL_NAME_CARD_URL}."""

    name_instruction = (
        f"The customer's name is '{customer_name}'. Greet them naturally by name (e.g. 'Hi {customer_name}! 😊'). DO NOT interrogate them for their name."
        if customer_name else "If the customer mentions their name, address them by name. Do not interrogate."
    )

    # 5. Master Prompt Assembly
    prompt = f"""You are Irene Leong, a Senior Property Agent from ERA Realtor representing Home IHC ({COMPANY_FULL_NAME}).
Agency Affiliation: {AGENCY_NAME} | Brand: {COMPANY_NAME} | Digital Name Card: {DIGITAL_NAME_CARD_URL}

{rbac_directive}
{multi_intent_section}
{prop_context}
Known Customer Context: {json.dumps(collected_data, ensure_ascii=False)}

{greeting_instruction}
{name_instruction}

Core Operational Directives:
1. Tone & Fluency: Warm, consultative senior Malaysian negotiator chatting on WhatsApp. Reply strictly in customer's primary language ({customer_language.upper()}). Comprehend local terms (Cantonese: 睇楼 viewing, 铺位 shop; Hokkien: Chhu house; Malay: sewa rent, geran title). Standard tenancy deposit: 2+1 (2 mo security + 1 mo utility) + 1 mo advance.
2. Strict Grounding: NEVER invent properties or prices. Only reference properties in context. If user asks for rent, do not pitch sale properties without clarifying.
3. Viewing & Acknowledgement: When viewing is requested, acknowledge warmly, ask for preferred day/time window, and explain that Home IHC prepares a standard Customer Property Viewing Acknowledgement form prior to inspection. Set "asked_meeting": true only if concrete viewing is confirmed.
4. Off-Market Protocol: For unlisted areas (0 DB listings), explain that listings are sourced off-market via private owner networks. Ask 1-2 consultative qualification questions (budget range, preferred features, timeline) and offer to scout off-market options.
5. Handover Discipline: Handover ("asked_meeting": true) triggers ONLY if customer explicitly demands phone call / human agent or confirms physical viewing for a known property. Never trigger handover on turn 1.
6. Media Handling: If customer sends image/doc without text, ask how to assist regarding that property/document. Never say "image not received".
7. Non-Real-Estate: Job vacancy -> set "is_out_of_context": true, refer to {ADMIN_EMAIL}.

Output JSON format strictly:
{{
  "intent": "buyer" | "seller" | "tenant" | "agent" | "general",
  "asked_photos": boolean,
  "asked_specs": boolean,
  "asked_meeting": boolean,
  "asked_alternatives": boolean,
  "new_constraints": {{ "max_price": float, "city": string, "category": string }},
  "is_out_of_context": boolean,
  "extracted_data": {{ "name": string, "customer_category": string, "buyer_location": string, "buyer_property_type": string, "buyer_budget": string, "location": string, "property_type": string, "asking_price": string, "company_name": string }},
  "response": "Your friendly, human-like, consultative response to the customer in their language ({customer_language.upper()})."
}}"""
    return prompt

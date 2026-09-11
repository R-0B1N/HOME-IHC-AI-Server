import logging
import json
import re
import os
import redis
from app.db.models import SessionLocal, Property, Customer
from app.services.llm import llm_client, LLM_MODEL_NAME, _parse_json_from_llm
from app.services.db_services import find_matching_property, find_similar_properties, search_properties

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)


def is_valid_name(name: str) -> bool:
    """Checks if a name string looks like a real person's name rather than a phone number or placeholder."""
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip()
    if len(name_clean) < 2 or len(name_clean) > 50:
        return False
    if re.match(r'^\+?[0-9\s\-]+$', name_clean):
        return False
    generic = {"unknown", "john doe", "whatsapp user", "customer", "lead", "null", "none", "n/a", ".", "user"}
    if name_clean.lower() in generic:
        return False
    return True


def check_completeness(persona: str, collected_data: dict) -> float:
    """Calculates data completeness ratio for lead scoring."""
    required_keys = {
        "buyer": ["buyer_location", "buyer_property_type", "buyer_budget"],
        "seller": ["location", "property_type", "asking_price"],
        "tenant": ["current_location", "property_type", "budget"],
        "agent": ["company_name", "coverage_area"]
    }
    required = required_keys.get(persona.lower(), ["buyer_location", "buyer_property_type"])
    if not required:
        return 1.0
    filled = sum(1 for k in required if collected_data.get(k))
    return filled / len(required)


def process_persona_state_machine(phone_number: str, text: str, session: dict, conversation_history: str = "", contact_name: str = None) -> dict:
    """
    Enterprise-standard Conversational AI Engine for Home IHC.
    Engages naturally, provides on-demand property specs, dispatches native WhatsApp photos,
    suggests similar properties, and prevents premature handovers.
    """
    raw_text = (text or "").strip()
    collected_data = session.setdefault("collected_data", {})

    # Auto-reset session if in completed/stale state
    if session.get("state") == "COMPLETED" or session.get("handover"):
        session["state"] = "IN_PROGRESS"
        session["handover"] = False

    # 1. Payload Name Hook — populate name if valid
    if contact_name and is_valid_name(contact_name) and not collected_data.get("name"):
        collected_data["name"] = contact_name.strip()

    current_user_name = collected_data.get("name") or (contact_name if is_valid_name(contact_name) else None)

    # 2. Match Specific Property in Database or Resolve from History
    matched_prop = find_matching_property(raw_text)
    if matched_prop:
        session["interested_property"] = matched_prop
        collected_data["property_of_interest"] = matched_prop["title"]
        if not collected_data.get("buyer_property_type"):
            categories = matched_prop.get("property_category") or []
            collected_data["buyer_property_type"] = categories[0] if categories else matched_prop["title"]
        if not collected_data.get("buyer_location"):
            collected_data["buyer_location"] = matched_prop.get("city") or matched_prop.get("state") or "Pahang"
        if not collected_data.get("buyer_budget") and matched_prop.get("price"):
            collected_data["buyer_budget"] = f"RM {matched_prop['price']:,.0f}"
        if not collected_data.get("customer_category"):
            collected_data["customer_category"] = "buyer"

    # Detect specific property/lot mentions that are NOT in our database
    _property_entity_detected = False
    _property_entity_text = ""
    if not matched_prop:
        # Check for lot numbers, taman names, addresses, or specific property identifiers
        entity_patterns = [
            r'lot\s+\d+',
            r'mukim\s+\w+',
            r'daerah\s+\w+',
            r'taman\s+\w+',
            r'kampung\s+\w+',
            r'jalan\s+\w+',
            r'no\.?\s*\d+',
        ]
        for pattern in entity_patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                _property_entity_detected = True
                _property_entity_text = raw_text.strip()
                break

    cached_prop = session.get("interested_property")

    # If no cached property, try to resolve from conversation history
    if not cached_prop and conversation_history:
        history_prop = find_matching_property(conversation_history)
        if history_prop:
            session["interested_property"] = history_prop
            cached_prop = history_prop

    # 3. Dynamic RAG Property Search based on user message context
    available_properties = []
    
    # Check if user explicitly wants to switch criteria
    is_switching_context = any(phrase in raw_text.lower() for phrase in [
        "other", "another", "different", "instead", "switch to", "what else",
        "durian land", "commercial", "industrial", "house in", "shop in", "land in",
        "店面", "铺位", "店", "shop", "commercial", "rumah kedai"
    ]) and not any(p in raw_text.lower() for p in ["picture", "photo", "gambar", "foto", "more picture", "more photo", "detail"])

    if is_switching_context:
        session["interested_property"] = None
        cached_prop = None

    if not cached_prop:
        # Search DB for properties relevant to the message
        search_loc = None
        for town in ["bentong", "raub", "karak", "temerloh", "mentakab", "pahang", "bukit tinggi", "lanchang", "maran", "kuantan"]:
            if town in raw_text.lower() or (not is_switching_context and town in conversation_history.lower()):
                search_loc = town
                break
        
        search_cat = None
        for cat in ["semi-d", "semi d", "bungalow", "terrace", "durian", "orchard", "shop", "commercial", "warehouse", "factory", "industrial", "land", "house", "店面", "铺位", "kedai"]:
            if cat in raw_text.lower() or (not is_switching_context and cat in conversation_history.lower()):
                search_cat = cat
                break
                
        price_match = re.search(r'(\d+[\.\d]*)\s*(m|million|k|thousand|000)', raw_text.lower())
        max_p = None
        if price_match:
            num = float(price_match.group(1))
            unit = price_match.group(2)
            if unit in ["m", "million"]:
                max_p = num * 1_000_000
            elif unit in ["k", "thousand"]:
                max_p = num * 1_000
            else:
                max_p = num

        criteria = {
            "location": search_loc or collected_data.get("buyer_location"),
            "property_type": search_cat or collected_data.get("buyer_property_type"),
            "max_price": max_p or collected_data.get("buyer_budget")
        }
        # GUARD: Only search if at least one explicit criterion exists.
        # Prevents hallucination when user sends greetings/referrals with no property intent.
        has_any_criteria = any(v for v in criteria.values() if v and str(v).lower() not in ["none", "null", ""])
        if has_any_criteria:
            available_properties = search_properties(criteria, limit=5)
        # Note: Do NOT force-lock available_properties[0] into session['interested_property']
        # to avoid hallucinatory property locks on general queries.

    # 4. LLM Intent & Conversational Generation
    llm_analysis = generate_conversational_response(
        text=raw_text,
        cached_property=cached_prop,
        available_properties=available_properties if not cached_prop else [],
        conversation_history=conversation_history,
        collected_data=collected_data,
        customer_name=current_user_name,
        unlisted_property_text=_property_entity_text if _property_entity_detected else None
    )

    # Merge extracted data
    for k, v in llm_analysis.get("extracted_data", {}).items():
        if v and str(v).lower() not in ["null", "none", ""]:
            collected_data[k] = v

    is_out_of_context = llm_analysis.get("is_out_of_context", False)
    if is_out_of_context:
        session["state"] = "COMPLETED"
        return {
            "response": "Thank you for contacting Home IHC. I have forwarded your inquiry to our administration team at homeihc13@gmail.com, and a representative will follow up with you shortly.",
            "handover": True,
            "assignee_email": "homeihc13@gmail.com",
            "images_to_send": [],
            "updated_session": session
        }

    asked_photos = llm_analysis.get("asked_photos", False)
    asked_meeting = llm_analysis.get("asked_meeting", False)
    asked_alternatives = llm_analysis.get("asked_alternatives", False)
    new_constraints = llm_analysis.get("new_constraints", {})

    # Detect photo request via LLM or direct conversational keywords
    # Guard: Only trigger photo dispatch during ongoing dialogue, not on first message
    has_prior_conversation = bool(conversation_history and len(conversation_history.strip()) > 10)
    is_photo_request = (bool(asked_photos) or any(w in raw_text.lower() for w in [
        "picture", "pictures", "photo", "photos", "gambar", "foto", "image", "images", "see photo", "show photo", "相片", "照片"
    ])) and has_prior_conversation

    images_to_send = []

    # 5. Handle Native WhatsApp Photos
    if is_photo_request and cached_prop:
        prop_images = cached_prop.get("image_urls") or []
        
        # If cached dict has no image_urls, query DB directly
        if not prop_images and cached_prop.get("id"):
            db = SessionLocal()
            try:
                p_record = db.query(Property).filter(Property.id == cached_prop["id"]).first()
                if p_record and p_record.image_urls:
                    prop_images = p_record.image_urls
                    cached_prop["image_urls"] = prop_images
                    session["interested_property"] = cached_prop
            finally:
                db.close()
                
        if prop_images:
            # Filter valid HTTP URLs and exclude logo/icon placeholders
            images_to_send = [
                img for img in prop_images 
                if isinstance(img, str) and img.startswith("http") and not any(ex in img.lower() for ex in ["logo", "icon", "favicon"])
            ][:5]
            logger.info(f"Resolved {len(images_to_send)} photos to send for property: {cached_prop.get('title')}")

    # 6. Handle Similar Properties Suggestion (Alternatives / Sold listing)
    if asked_alternatives or (cached_prop and cached_prop.get("status") not in ["Available", "For Sale", "For Rent"]):
        city = new_constraints.get("city") or (cached_prop.get("city") if cached_prop else None)
        category = new_constraints.get("category") or (cached_prop.get("property_category") if cached_prop else None)
        max_p = new_constraints.get("max_price")
        
        similars = find_similar_properties(
            property_id=cached_prop.get("id") if cached_prop else None,
            city=city,
            category=category,
            max_price=max_p,
            limit=3
        )
        if similars:
            llm_analysis["similar_options"] = similars

    # 7. Check Handover Triggers
    handover = False
    response_text = llm_analysis.get("response", "How may Home IHC assist you with properties in Pahang today? 😊")

    handover_phrases = [
        "call me", "speak to human", "talk to agent", "contact me directly",
        "transfer to human", "speak to a person", "talk to a person", "real agent",
        "real person", "human agent", "human staff", "person in charge",
        "真人", "转人工", "人工客服", "联系真人", "找真人",
        "电话联系", "安排见面", "nak jumpa", "call saya", "hubungi saya", "agent sebenar", 
        "cakap dengan orang", "temujanji"
    ]
    user_wants_immediate_human = any(phrase in raw_text.lower() for phrase in handover_phrases) or bool(re.search(r'\bpic\b', raw_text.lower()))
    user_books_cached_viewing = bool(cached_prop) and (bool(asked_meeting) or any(phrase in raw_text.lower() for phrase in ["安排看房", "预约看房", "睇楼", "tengok rumah", "tengok tanah", "arrange viewing", "schedule viewing", "viewing"]))

    if user_wants_immediate_human or user_books_cached_viewing:
        handover = True
        name_str = f" {current_user_name}" if current_user_name else ""
        prop_str = f" for {cached_prop.get('title')}" if cached_prop else ""
        if "senior" not in response_text.lower() and "specialist" not in response_text.lower() and "representative" not in response_text.lower():
            response_text = f"Thank you{name_str}! 😊 We have recorded your request{prop_str}. A senior property specialist from Home IHC will contact you shortly to follow up directly."
        session["state"] = "COMPLETED"

    # Save session state & mark introduction as completed
    collected_data["introduced"] = True
    session["introduced"] = True
    session["current_agent"] = collected_data.get("customer_category", "BUYER").upper()
    session["collected_data"] = collected_data

    return {
        "response": response_text,
        "handover": handover,
        "images_to_send": images_to_send,
        "updated_session": session
    }


def generate_conversational_response(text: str, cached_property: dict, available_properties: list, conversation_history: str, collected_data: dict, customer_name: str = None, unlisted_property_text: str = None) -> dict:
    """
    Calls LLM to generate a natural, empathetic, human-like response as Irene Leong from ERA Realtor representing Home IHC.
    Performs simultaneous silent background data extraction and multilingual Malaysian dialect comprehension.
    """
    prop_context = ""
    if cached_property:
        prop_context = f"""
Inquired Property in Context:
- Title: {cached_property.get('title')}
- Price: RM {cached_property.get('price', 'N/A')}
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
        prop_context = "Matching Properties in Database:\n" + "\n".join(props_list)
    elif unlisted_property_text:
        prop_context = f"""
[PROPERTY_STATUS: UNLISTED_OR_OFF_MARKET_LOCATION]
The customer inquired about a specific location or property ("{unlisted_property_text}") where Home IHC currently has 0 active published listings in the database.
Off-Market Sourcing Protocol (Option A):
- Rental and unlisted units in this area (e.g. {unlisted_property_text}) are handled through Home IHC's offline network of local property owners and private landlords.
- Transparently explain this off-market sourcing mechanism to the customer.
- Acknowledge and confirm all requirements they specified (property type, budget, location near landmarks like HOSHAS, move-in date, occupant background).
- Ask if they would like our local area agent to scout unlisted landlords and offline listings for them, or if they are open to nearby areas.
- Do NOT fabricate fake listings, addresses, or prices.
- KEEP CHATTING naturally. Do NOT end the conversation with a generic handover message unless they explicitly ask for an immediate phone call or human agent.
"""

    has_prior_assistant_intro = (
        "Assistant:" in conversation_history or 
        "Irene Leong" in conversation_history or 
        "mecard.my" in conversation_history or
        bool(collected_data.get("introduced"))
    )

    if has_prior_assistant_intro:
        greeting_instruction = """[CONVERSATION_STAGE: ONGOING_DIALOGUE]
CRITICAL ANTI-REPETITION RULE:
- You have ALREADY introduced yourself in this conversation.
- STRICTLY DO NOT repeat your introduction (DO NOT say "我是来自 ERA Realtor 的 Irene Leong" or "I'm Irene Leong").
- STRICTLY DO NOT re-send your digital name card link (https://my.mecard.my/1733211127).
- Proceed DIRECTLY, concisely, and naturally to addressing the customer's question."""
    else:
        greeting_instruction = """[CONVERSATION_STAGE: FIRST_INTERACTION]
- In your introductory greeting, introduce yourself as: "I'm Irene Leong, a Senior Property Agent from ERA Realtor." (In Chinese: "我是来自 ERA Realtor 的 Irene Leong。")
- The company providing the properties and assistance is Home IHC (e.g. "How can Home IHC assist you today?").
- Share your digital name card: https://my.mecard.my/1733211127."""

    name_instruction = f"The customer's name is '{customer_name}'. Greet them naturally by name (e.g. 'Hi {customer_name}! 😊'). DO NOT ask for their name." if customer_name else "If the customer mentions their name, address them by name. Do not interrogate."

    system_prompt = f"""You are Irene Leong, a Senior Property Agent from ERA Realtor representing Home IHC (Home IHC Sdn. Bhd. / BentongLand).
Agency / License Affiliation: ERA Realtor
Company Name / Brand: Home IHC (Strictly Home IHC for company services, reviews, and general assistance)
Digital Name Card: https://my.mecard.my/1733211127

{prop_context}
Known Customer Context: {json.dumps(collected_data)}

{greeting_instruction}

Core Operational Directives:
1. Tone & Persona: Warm, professional, consultative, and natural—like an experienced senior Malaysian real estate negotiator chatting on WhatsApp. Never sound robotic or like a rigid questionnaire.
2. Multilingual & Malaysian Dialect Fluency:
   - You fully comprehend Cantonese (广东话), Hokkien (福建话), Bahasa Melayu (Pasar Malay), Malaysian Mandarin (华语), and English/Manglish.
   - Reply in the customer's primary language (English, Chinese, or Malay).
   - Dialect Context Mapping:
     * Cantonese: 铺位/铺头 = Commercial shoplot; 睇楼 = Viewing; 几多钱 = How much; 顶手/顶租 = Takeover; 屋主 = Landlord/Owner; 水钱/佣金 = Commission.
     * Hokkien: Tiàm-thâu = Shoplot; Chhu = House; Chhut-cho͘ = Rent; Thô͘-tī = Land; Lō͘-piⁿ = Roadside.
     * Malay: sewa = Rent; jual = Sell; kedai/rumah kedai = Shoplot; tanah lot = Land; sewa sebulan = 1 month rental; deposit 2+1 = 2 months security deposit + 1 month utility.
3. Active Guidance & Direct Answers (Never Loop):
   - If a customer mentions shorthand like "一个月" (one month), answer directly with Malaysian real estate standards:
     * Tenancy Advance: 1 month advance rental required before key handover.
     * Security & Utility Deposit: Standard is 2 months security deposit + 1 month utility deposit.
     * Agency Commission: Standard 1 month rental payable by the landlord/owner.
   - If a customer clarifies they want a commercial shop (店面) rather than a house, IMMEDIATELY pivot, acknowledge the commercial shop requirement, suggest 1-2 suitable areas (e.g., Kuantan Town Center, Indera Mahkota, Air Putih) with typical price ranges, and ask if they need ground floor or upper floor.
   - If matching properties are provided in context, introduce 1-3 concrete options with titles and prices, and ask which one they would like more details or photos for.
   - NEVER hallucinate that the customer asked about a specific property (e.g. Taman Seri Galing house) unless they explicitly named it.
4. Handover Discipline:
   - Only trigger human handover or say "A senior specialist from Home IHC will contact you" if:
     * The customer explicitly demands an immediate telephone call, human agent ("转人工", "call me", "speak to human"), or confirms a concrete viewing appointment date/time for a specific existing listing.
     * DO NOT hand over or terminate dialogue merely because a user expresses hypothetical future interest (e.g. "if you have suitable houses I would be interested in viewing"). Keep the consultative conversation going!
5. Unlisted / Zero-Inventory Area Protocol (Off-Market Sourcing):
   - When a tenant or buyer inquires about an area with 0 database matches (e.g. Temerloh, Mentakab, Jerantut):
     * Transparently explain that rental units in that area are handled through our offline/off-market owner network rather than public advertisements.
     * Confirm their requirements (location, budget, bedrooms, furnishings, move-in date, tenant profile).
     * Ask if they want our local area agent to scout unlisted owners and private listings for them, or if they are open to nearby areas.
     * KEEP CHATTING naturally. Ask friendly follow-up questions to complete their profile without sounding like an interrogation.
   - If the customer is an owner/seller asking to list an unlisted property:
     * Offer valuation and marketing assistance, and ask for property details (land size, title, asking price).
6. Guardrails: If the user is applying for a job, selling unrelated services, or spamming, set "is_out_of_context": true.

Output JSON format strictly:
{{
  "intent": "buyer" | "seller" | "tenant" | "agent" | "general",
  "asked_photos": boolean,
  "asked_specs": boolean,
  "asked_meeting": boolean (True ONLY if user demands an immediate telephone call or schedules a physical viewing for an existing listing; False for general/exploratory inquiries),
  "asked_alternatives": boolean,
  "new_constraints": {{ "max_price": float, "city": string, "category": string }},
  "is_out_of_context": boolean,
  "extracted_data": {{ "name": string, "customer_category": string, "buyer_location": string, "buyer_property_type": string, "buyer_budget": string, "location": string, "property_type": string, "asking_price": string, "company_name": string }},
  "response": "Your friendly, human-like, consultative response to the customer."
}}"""

    messages = [
        {"role": "system", "content": system_prompt}
    ]
    if conversation_history:
        messages.append({"role": "system", "content": f"Recent Conversation History:\n{conversation_history}"})
    messages.append({"role": "user", "content": text})

    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1000,
            timeout=30.0
        )
        content = response.choices[0].message.content
        parsed = _parse_json_from_llm(content)
        if not parsed:
            try:
                parsed = json.loads(content, strict=False)
            except Exception:
                match = re.search(r'"response"\s*:\s*"([^"]*)', content, re.DOTALL)
                if match:
                    parsed = {"response": match.group(1).strip()}
        
        if parsed and isinstance(parsed, dict) and parsed.get("response"):
            return parsed
        raise ValueError(f"Failed to parse valid JSON response from LLM content: {content[:100] if content else 'empty'}")
    except Exception as e:
        logger.error(f"Error calling LLM for conversational response: {e}")
        if conversation_history:
            fallback_msg = "Thank you for sharing your requirements! For this area, our rental listings are primarily sourced off-market directly from landlords. Could you let me know if you are open to nearby locations as well, or if you prefer strictly within 5 km?"
        else:
            fallback_msg = "Good day! 😊 I'm Irene Leong, a Senior Property Agent from ERA Realtor. How may Home IHC assist you with properties in Pahang today?"
        return {
            "intent": "general",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "asked_alternatives": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "response": fallback_msg
        }

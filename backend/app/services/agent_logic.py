import logging
import json
import re
import os
import redis
from app.db.models import SessionLocal, Property, Customer
from app.services.llm import llm_client, LLM_MODEL_NAME
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
        "durian land", "commercial", "industrial", "house in", "shop in", "land in"
    ]) and not any(p in raw_text.lower() for p in ["picture", "photo", "gambar", "foto", "more picture", "more photo", "detail"])

    if is_switching_context:
        session["interested_property"] = None
        cached_prop = None

    if not cached_prop:
        # Search DB for properties relevant to the message
        search_loc = None
        for town in ["bentong", "raub", "karak", "temerloh", "mentakab", "pahang", "bukit tinggi", "lanchang", "maran"]:
            if town in raw_text.lower() or (not is_switching_context and town in conversation_history.lower()):
                search_loc = town
                break
        
        search_cat = None
        for cat in ["semi-d", "semi d", "bungalow", "terrace", "durian", "orchard", "shop", "commercial", "warehouse", "factory", "industrial", "land", "house"]:
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
        available_properties = search_properties(criteria, limit=5)
        
        # If search found candidates and this is a search intent, lock the top recommendation in session
        if available_properties and len(available_properties) > 0:
            cached_prop = available_properties[0]
            session["interested_property"] = cached_prop
            collected_data["property_of_interest"] = cached_prop.get("title")

    # 4. LLM Intent & Conversational Generation
    llm_analysis = generate_conversational_response(
        text=raw_text,
        cached_property=cached_prop,
        available_properties=available_properties if not cached_prop else [],
        conversation_history=conversation_history,
        collected_data=collected_data,
        customer_name=current_user_name
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
    is_photo_request = bool(asked_photos) or any(w in raw_text.lower() for w in [
        "picture", "pictures", "photo", "photos", "gambar", "foto", "image", "images", "see photo", "show photo"
    ])

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
    response_text = llm_analysis.get("response", "How may I assist you with Home IHC properties today? 😊")

    if asked_meeting:
        handover = True
        name_str = f" {current_user_name}" if current_user_name else ""
        prop_str = f" for {cached_prop.get('title')}" if cached_prop else ""
        response_text = f"Thank you{name_str}! 😊 We have recorded your viewing request{prop_str}. A senior property specialist from Home IHC will contact you shortly to confirm the appointment."
        session["state"] = "COMPLETED"

    # Save session
    session["current_agent"] = collected_data.get("customer_category", "BUYER").upper()
    session["collected_data"] = collected_data

    return {
        "response": response_text,
        "handover": handover,
        "images_to_send": images_to_send,
        "updated_session": session
    }


def generate_conversational_response(text: str, cached_property: dict, available_properties: list, conversation_history: str, collected_data: dict, customer_name: str = None) -> dict:
    """
    Calls LLM to generate a natural, empathetic, human-like response as Irene Leong from Home IHC.
    Performs simultaneous silent background data extraction.
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

    name_instruction = f"The customer's name is '{customer_name}'. Greet them naturally by name (e.g. 'Hi {customer_name}! 😊'). DO NOT ask for their name." if customer_name else "If the customer mentions their name, address them by name. Do not interrogate."

    system_prompt = f"""You are Irene Leong, a Senior Property Agent for Home IHC (Home IHC Sdn. Bhd.).
Company Name: Home IHC (Strictly Home IHC - never mention ERA)
Digital Name Card: https://my.mecard.my/1733211127

{prop_context}
Known Customer Context: {json.dumps(collected_data)}

Core Principles:
1. Tone & Persona: Warm, professional, helpful, and natural—like an experienced property agent chatting on WhatsApp. NEVER sound like a rigid questionnaire or robotic state machine.
2. {name_instruction}
3. Responding to Inquiries:
   - If the customer asks for a general greeting ("hi", "hello"): Introduce Home IHC warmly, share your digital name card, and ask how Home IHC can assist them today (buying, selling, renting, or inquiring about land/property in Pahang).
   - If the customer mentions a specific property without asking for price/specs: Acknowledge the property warmly and ask: "Thank you for contacting Home IHC! I see that you are inquiring about the [Property Name]. Would you like to know more about it? 😊"
   - If the customer asks for pictures/photos: Confirm that photos are being sent, and ask if they would like floor layout details or to arrange a viewing session.
   - If the customer asks for price/specs: Provide the exact price and specs from the database context, and ask if they'd like to arrange a viewing or if they have questions.
   - If the customer asks for a search (e.g. "Temerloh commercial shop budget 1m below", "semi d in raub"): Present 1-3 matching properties from the database context with prices, and ask which one they'd like more details or photos for.
4. Multi-Language: Always respond in the same language as the customer (English, Bahasa Melayu, or Chinese).
5. Handover Discipline: Do NOT say "A senior agent will contact you shortly" unless the user explicitly asks for a meeting, phone call, or viewing appointment. Keep conversing and answering their questions.
6. Guardrails: If the user is applying for a job, selling unrelated services, or spamming, set "is_out_of_context": true.

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
  "response": "Your friendly, human-like, conversational response to the customer."
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
            temperature=0.0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Error calling LLM for conversational response: {e}")
        return {
            "intent": "general",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "asked_alternatives": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "response": "Hello! 😊 I'm Irene Leong from Home IHC. How may I assist you with properties in Pahang today?"
        }

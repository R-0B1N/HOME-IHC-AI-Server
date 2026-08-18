import logging
import json
import re
import os
import redis
from app.db.models import SessionLocal, WorkflowTemplate, Customer
from app.services.llm import llm_client, LLM_MODEL_NAME
from app.services.db_services import find_matching_property, find_similar_properties, search_properties

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

REQUIRED_PERSONA_KEYS = {
    "SELLER": ["name", "is_owner", "property_type", "location", "asking_price"],
    "BUYER": ["name", "buyer_location", "buyer_property_type", "buyer_budget", "purchase_entity"],
    "TENANT": ["name", "current_location", "property_type", "budget", "use_type"],
    "LANDLORD": ["name", "is_owner", "property_type", "location", "expected_rental"],
    "AGENT": ["name", "company_name", "coverage_area", "collaboration_type"]
}

KEY_ALIASES = {
    "SELLER": {
        "location": ["seller_location", "location", "city", "state", "property_location"],
        "property_type": ["seller_property_type", "property_type", "type_of_property"],
        "asking_price": ["asking_price", "budget", "price", "expected_price", "target_price"],
        "is_owner": ["is_owner", "entity", "owner_status", "seller_entity", "developer"],
        "name": ["name", "contact_name", "seller_name", "owner_name"]
    },
    "BUYER": {
        "buyer_location": ["buyer_location", "location", "preferred_location", "city"],
        "buyer_property_type": ["buyer_property_type", "property_type", "preferred_type"],
        "buyer_budget": ["buyer_budget", "budget", "price_range", "max_price"],
        "purchase_entity": ["purchase_entity", "entity", "buyer_entity", "is_company"],
        "name": ["name", "contact_name", "buyer_name"]
    }
}


def is_valid_name(name: str) -> bool:
    """Checks if a name string looks like a real person's name rather than a phone number or placeholder."""
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip()
    if len(name_clean) < 2 or len(name_clean) > 50:
        return False
    # If it starts with + or is digits, not a valid name
    if re.match(r'^\+?[0-9\s\-]+$', name_clean):
        return False
    # Check against generic placeholders
    generic = {"unknown", "john doe", "whatsapp user", "customer", "lead", "null", "none", "n/a", "."}
    if name_clean.lower() in generic:
        return False
    return True


def check_completeness(persona: str, collected_data: dict) -> float:
    """Calculates data completeness ratio for the persona."""
    required = REQUIRED_PERSONA_KEYS.get(persona, [])
    if not required:
        return 1.0
    aliases = KEY_ALIASES.get(persona, {})
    filled_count = 0
    for req_key in required:
        if collected_data.get(req_key):
            filled_count += 1
            continue
        alt_keys = aliases.get(req_key, [])
        if any(collected_data.get(alt) for alt in alt_keys):
            filled_count += 1
    return filled_count / len(required)


def process_persona_state_machine(phone_number: str, text: str, session: dict, conversation_history: str = "", contact_name: str = None) -> dict:
    """
    Enterprise-standard property-aware conversational state machine.
    Handles dynamic dialog, on-demand property specs, native image attachments,
    similar property suggestions, multi-language support, and smart step skipping.
    """
    db = SessionLocal()
    try:
        raw_text = (text or "").strip()
        collected_data = session.setdefault("collected_data", {})
        
        # 1. Payload Name Hook — populate name if valid and not already set
        if contact_name and is_valid_name(contact_name) and not collected_data.get("name"):
            collected_data["name"] = contact_name.strip()
            
        current_user_name = collected_data.get("name") or (contact_name if is_valid_name(contact_name) else None)
        
        # 2. Property Entity Detection
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

        # 3. LLM Intent & Request Analysis
        llm_analysis = analyze_message_intent(
            text=raw_text,
            cached_property=cached_prop,
            conversation_history=conversation_history,
            current_agent=session.get("current_agent", "ROUTER"),
            collected_data=collected_data
        )

        is_out_of_context = llm_analysis.get("is_out_of_context", False)
        if is_out_of_context:
            session["state"] = "COMPLETED"
            return {
                "response": "Thank you for reaching out to Home IHC. I have forwarded your inquiry to our administration team at homeihc13@gmail.com, and a representative will follow up with you shortly.",
                "handover": True,
                "assignee_email": "homeihc13@gmail.com",
                "updated_session": session
            }

        # Merge extracted structured data
        for k, v in llm_analysis.get("extracted_data", {}).items():
            if v and str(v).lower() not in ["null", "none", ""]:
                collected_data[k] = v

        user_intent = llm_analysis.get("intent", "GENERAL")
        asked_photos = llm_analysis.get("asked_photos", False)
        asked_specs = llm_analysis.get("asked_specs", False)
        asked_meeting = llm_analysis.get("asked_meeting", False)
        asked_alternatives = llm_analysis.get("asked_alternatives", False)
        asked_negotiation = llm_analysis.get("asked_negotiation", False)
        new_constraints = llm_analysis.get("new_constraints", {})

        images_to_send = []

        # 4. Handle Meeting / Viewing / Call Request
        if asked_meeting:
            name_str = f" {current_user_name}" if current_user_name else ""
            prop_title = cached_prop.get("title") if cached_prop else "the property"
            wrap_up = f"Thank you{name_str}! 😊 We have recorded your viewing request for {prop_title}. A senior property specialist from Home IHC will contact you shortly to confirm the appointment schedule."
            session["state"] = "COMPLETED"
            return {
                "response": wrap_up,
                "handover": True,
                "images_to_send": [],
                "updated_session": session
            }

        # 5. Handle Photos / Pictures Request
        if asked_photos and cached_prop:
            prop_images = cached_prop.get("image_urls") or []
            if prop_images:
                # Take top 2-3 images
                images_to_send = prop_images[:3]
                follow_up = f"Here are the photos of {cached_prop.get('title')} for you! 📸\n\nWould you like more details on the specifications or to arrange a physical viewing session with our team? 😊"
            else:
                follow_up = f"Fresh photos for {cached_prop.get('title')} are currently being updated by our listing team. In the meantime, I can share the layout specifications or arrange an on-site visit for you. Would you like to schedule a visit? 😊"
            
            return {
                "response": follow_up,
                "handover": False,
                "images_to_send": images_to_send,
                "updated_session": session
            }

        # 6. Handle Similar Properties Suggestion (Alternatives / Sold / Constraint Shift)
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
                lines = []
                for idx, sim in enumerate(similars, 1):
                    price_txt = f"RM {sim['price']:,.0f}" if sim.get('price') else "Price on inquiry"
                    lines.append(f"{idx}. *{sim['title']}* ({price_txt}) - {sim.get('city') or 'Pahang'}")
                sim_text = "\n".join(lines)
                
                if cached_prop and cached_prop.get("status") not in ["Available", "For Sale", "For Rent"]:
                    reply = f"Thank you for contacting Home IHC! The listing for *{cached_prop.get('title')}* has recently been reserved/taken. However, we have these similar available properties:\n\n{sim_text}\n\nWould you like to know more details or see photos for any of these? 😊"
                else:
                    reply = f"Here are some great options matching your preferences:\n\n{sim_text}\n\nWould you like to know more details or receive photos for any of these? 😊"
                
                return {
                    "response": reply,
                    "handover": False,
                    "images_to_send": [],
                    "updated_session": session
                }

        # 7. Initial Entry with Specific Property Mention (No Spec Request)
        if matched_prop and not asked_specs and not conversation_history:
            session["state"] = "IN_PROGRESS"
            session["current_agent"] = "BUYER"
            session["current_step_id"] = 32 # Skip name if known, proceed smoothly
            
            reply = f"Thank you for contacting Home IHC! I see that you are inquiring about the {matched_prop['title']}. Would you like to know more about it? 😊"
            return {
                "response": reply,
                "handover": False,
                "images_to_send": [],
                "updated_session": session
            }

        # 8. User Asks for Details / Specs / Price
        if asked_specs and cached_prop:
            price_txt = f"RM {cached_prop['price']:,.0f}" if cached_prop.get("price") else "Contact agent for price"
            acres_txt = f"{cached_prop['acres']} Acres" if cached_prop.get("acres") else (f"{cached_prop.get('sqft')} sqft" if cached_prop.get("sqft") else "Spacious layout")
            tenure_txt = f", {cached_prop['tenure']}" if cached_prop.get("tenure") else ""
            location_txt = f"{cached_prop.get('city') or ''}, {cached_prop.get('state') or 'Pahang'}".strip(", ")
            
            reply = f"Here are the details for *{cached_prop['title']}*:\n• Asking Price: {price_txt}\n• Location: {location_txt}\n• Size / Tenure: {acres_txt}{tenure_txt}\n\nAre you looking to purchase this for your own stay or investment, and would you like to arrange a site viewing? 😊"
            return {
                "response": reply,
                "handover": False,
                "images_to_send": [],
                "updated_session": session
            }

        # 9. Handle Price Negotiation
        if asked_negotiation and cached_prop:
            price_txt = f"RM {cached_prop['price']:,.0f}" if cached_prop.get("price") else "the asking price"
            reply = f"The asking price for *{cached_prop['title']}* is {price_txt}. The owner is open to reasonable discussions upon viewing the property.\n\nWould you like us to arrange an appointment for you to view the property and discuss further with our specialist? 😊"
            return {
                "response": reply,
                "handover": False,
                "images_to_send": [],
                "updated_session": session
            }

        # 10. Dynamic State Machine & Persona Progression
        current_agent = session.get("current_agent", "ROUTER")
        current_step_id = session.get("current_step_id", 1)

        # Initial Blank Greeting
        if not current_agent or session.get("state") == "INIT" or (current_agent == "ROUTER" and current_step_id == 1 and not conversation_history):
            session["state"] = "IN_PROGRESS"
            session["current_agent"] = "ROUTER"
            session["current_step_id"] = 2
            
            intro_msg = ("Good day! 😊\nI'm Irene Leong, a Senior Property Agent from Home IHC\n\n"
                         "Here is my digital name card:\nhttps://my.mecard.my/1733211127\n\n"
                         "Thank you for contacting us. To help us assist you, could you let us know which category best describes you?\n"
                         "🙋 Personal Buyer\n"
                         "🏡 Seller / Property Owner\n"
                         "🤝 Property Agent / Broker\n"
                         "🏢 Corporate / Developer")
            return {
                "response": intro_msg,
                "handover": False,
                "images_to_send": [],
                "updated_session": session
            }

        # Route Persona from category
        category = (collected_data.get("customer_category") or "").lower()
        if current_agent == "ROUTER":
            if any(w in category for w in ["buyer", "buy", "purchase", "invest"]):
                current_agent = "BUYER"
            elif any(w in category for w in ["seller", "sell", "owner", "developer"]):
                current_agent = "SELLER"
            elif any(w in category for w in ["tenant", "rent", "renter", "lease"]):
                current_agent = "TENANT"
            elif any(w in category for w in ["landlord"]):
                current_agent = "LANDLORD"
            elif any(w in category for w in ["agent", "broker", "co-broke", "co-agency", "ren"]):
                current_agent = "AGENT"
            
            session["current_agent"] = current_agent
            first_step = db.query(WorkflowTemplate).filter(
                WorkflowTemplate.persona_type == current_agent
            ).order_by(WorkflowTemplate.step_number.asc()).first()
            if first_step:
                current_step_id = first_step.step_number
                session["current_step_id"] = current_step_id

        # Query Current Workflow Step
        current_step = db.query(WorkflowTemplate).filter(
            WorkflowTemplate.persona_type == current_agent,
            WorkflowTemplate.step_number == current_step_id
        ).first()

        if not current_step:
            current_step = db.query(WorkflowTemplate).filter(
                WorkflowTemplate.persona_type == current_agent
            ).order_by(WorkflowTemplate.step_number.asc()).first()

        if not current_step:
            name_str = f" {current_user_name}" if current_user_name else ""
            return {
                "response": f"Thank you{name_str}! A senior property specialist from Home IHC will contact you shortly.",
                "handover": True,
                "images_to_send": [],
                "updated_session": session
            }

        # Check if current step's data is already collected — if so, auto-advance!
        expected_keys = [k for k in (current_step.expected_data_keys or []) if k and k.strip()]
        
        # If expected key is 'name' and we already have name, advance immediately
        if "name" in expected_keys and collected_data.get("name"):
            next_step_id = current_step.next_step
            if next_step_id:
                session["current_step_id"] = next_step_id
                current_step = db.query(WorkflowTemplate).filter(
                    WorkflowTemplate.persona_type == current_agent,
                    WorkflowTemplate.step_number == next_step_id
                ).first()

        # If expected key is location/type and we already have it from property, advance
        if current_step and expected_keys:
            if all(collected_data.get(k) for k in expected_keys):
                next_step_id = current_step.next_step
                if next_step_id:
                    session["current_step_id"] = next_step_id
                    current_step = db.query(WorkflowTemplate).filter(
                        WorkflowTemplate.persona_type == current_agent,
                        WorkflowTemplate.step_number == next_step_id
                    ).first()

        # Generate Contextual Next Step Message
        next_msg = llm_analysis.get("conversational_reply")
        if not next_msg and current_step:
            next_msg = current_step.message_template

        # Check 80% completeness threshold
        completeness = check_completeness(current_agent, collected_data)
        if completeness >= 0.80 and not current_step.next_step:
            name_str = f" {current_user_name}" if current_user_name else ""
            wrap_up = f"Thank you{name_str}! 😊 We have collected all your details. A senior property specialist from Home IHC will contact you shortly."
            session["state"] = "COMPLETED"
            return {
                "response": wrap_up,
                "handover": True,
                "images_to_send": [],
                "updated_session": session
            }

        return {
            "response": next_msg or "How else may I assist you with Home IHC properties today? 😊",
            "handover": False,
            "images_to_send": images_to_send,
            "updated_session": session
        }

    except Exception as e:
        logger.error(f"Error in process_persona_state_machine: {e}", exc_info=True)
        return {
            "response": "Thank you for contacting Home IHC. A senior property agent will assist you shortly.",
            "handover": True,
            "images_to_send": [],
            "updated_session": session
        }
    finally:
        db.close()


def analyze_message_intent(text: str, cached_property: dict, conversation_history: str, current_agent: str, collected_data: dict) -> dict:
    """
    LLM prompt analyzing user intents, requests for photos, specs, meetings, alternatives,
    and single-pass multi-key data extraction supporting English, BM, and Chinese.
    """
    prop_context = ""
    if cached_property:
        prop_context = f"""
Currently Inquired Property:
Title: {cached_property.get('title')}
Price: RM {cached_property.get('price', 'N/A')}
Location: {cached_property.get('city')}, {cached_property.get('state')}
Acreage: {cached_property.get('acres')} Acres / {cached_property.get('sqft')} sqft
Tenure: {cached_property.get('tenure')}
Status: {cached_property.get('status')}
Images Available: {len(cached_property.get('image_urls', []))} images
"""

    system_prompt = f"""You are Irene Leong, Senior Property Agent for Home IHC (Home IHC Sdn. Bhd.).
Brand Name: Home IHC
Digital Name Card: https://my.mecard.my/1733211127

{prop_context}
Known Customer Data: {json.dumps(collected_data)}
Current Workflow: {current_agent}

Analyze the user's message and determine:
1. "intent": One of ["PROPERTY_INQUIRY", "PHOTO_REQUEST", "SPEC_REQUEST", "PRICE_NEGOTIATION", "ALTERNATIVE_REQUEST", "MEETING_REQUEST", "GENERAL", "OUT_OF_CONTEXT"]
2. "asked_photos": true if the user asks for pictures, photos, images, floor plans, "ada gambar tak", "看照片", etc.
3. "asked_specs": true if the user asks for price, size, built-up, acreage, tenure, location details, "how much", "开价多少", "berapa harga".
4. "asked_meeting": true if the user asks to schedule a physical viewing, site visit, meeting, phone call, "can someone call me", "nak tengok tanah", "安排看房".
5. "asked_alternatives": true if the user asks for other options, rejects the price/size, or says "any other similar units", "budget too high", "ada pilihan lain".
6. "asked_negotiation": true if user asks for bottom price, discount, "boleh nego tak", "最低价".
7. "new_constraints": JSON object with any updated budget, max_price (as float/int), city, or property category if mentioned.
8. "is_out_of_context": true ONLY if the message is completely unrelated to real estate (e.g. job applicant asking for vacancy, selling solar panels, etc.).
9. "extracted_data": Extract any new fields from the message:
   - "name": customer's name if they state it (e.g. "I am Nick", "Saya David", "我叫李强")
   - "customer_category": "buyer", "seller", "agent", "tenant", "landlord"
   - "buyer_budget" / "asking_price": extracted numbers or budget strings
   - "buyer_location" / "seller_location": town/city (Bentong, Raub, Karak, Temerloh, etc.)
   - "buyer_property_type": residential, commercial, industrial, durian orchard, agricultural
   - "company_name": if corporate developer or agency
10. "conversational_reply": A warm, professional, natural response in the same language as the user (English, Bahasa Melayu, or Chinese) representing Home IHC.
    - If property was mentioned and user did NOT ask for specs/price, do NOT dump full specs unasked. Warmly acknowledge and ask if they would like to know more.
    - If customer's name is known, address them naturally (e.g. "Hi Nick! 😊"). Never redundantly ask for their name.
    - Keep questions focused and ask only ONE follow-up question at a time.

Return ONLY a valid JSON object matching this schema."""

    messages = [
        {"role": "system", "content": system_prompt},
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
        logger.error(f"LLM Intent analysis error: {e}")
        return {
            "intent": "GENERAL",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "asked_alternatives": False,
            "asked_negotiation": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "conversational_reply": None
        }

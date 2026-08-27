import logging
import requests
import os
import json
from openai import OpenAI
import re

logger = logging.getLogger(__name__)

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://crm-vllm:8000/v1")
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://crm-whisper:8000/v1/audio/transcriptions")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "google/gemma-4-12B-it")

# Initialize OpenAI client for vLLM
llm_client = OpenAI(
    api_key="EMPTY",
    base_url=VLLM_BASE_URL
)

def transcribe_audio(audio_url: str) -> str:
    """
    Downloads audio and sends to Whisper (or audio transcription engine).
    Uses a targeted multilingual domain prompt covering Malaysian real estate terms
    in Mandarin, Cantonese, Hokkien, Bahasa Melayu, and English.
    """
    logger.info(f"Transcribing audio from {audio_url}")
    
    try:
        # 1. Download audio
        audio_resp = requests.get(audio_url, timeout=30)
        audio_resp.raise_for_status()
        
        # 2. POST to whisper API with domain vocabulary biasing
        multilingual_prompt = (
            "Irene Leong, ERA Realtor, Home IHC, BentongLand, Pahang, Kuantan, Bentong, Raub, Karak, Temerloh, Mentakab. "
            "店面, 铺位, 铺头, 双层排屋, 农业地, 榴莲园, 佣金, 租金, 买卖, 一间, 一个月, 订金, 押金, 发展地, 商业地, 睇楼, 顶手, 屋主, 业主. "
            "Tanah, kedai, sewa, jual, sewa sebulan, komisen, deposit 2+1, geran freehold leasehold, Musang King. "
            "Tiàm-thâu, Chhu, Chhut-cho͘, Bóe, Bē, Thô͘-tī. Shoplot, rental, one month advance, ROI."
        )
        
        files = {
            'file': ('audio.ogg', audio_resp.content, 'audio/ogg')
        }
        data = {
            'model': 'whisper-1',
            'prompt': multilingual_prompt,
            'temperature': 0.0
        }
        
        logger.info(f"Sending audio to Whisper API with domain prompt biasing: {WHISPER_API_URL}")
        whisper_resp = requests.post(WHISPER_API_URL, files=files, data=data, timeout=120)
        
        if whisper_resp.status_code != 200:
            logger.error(f"Whisper API failed with status {whisper_resp.status_code}: {whisper_resp.text}")
            whisper_resp.raise_for_status()
            
        # 3. Clean and filter transcript
        result = whisper_resp.json()
        transcript = (result.get("text") or "").strip()
        
        # Filter out common Whisper silence/hallucination tokens on short/silent audio
        hallucinations = [
            "[blank_audio]", "[music]", "[applause]", "[laughter]", "(silence)",
            "thank you.", "thanks for watching!", "thanks for watching.", "please subscribe",
            "amara.org", "subtitle by", "subtitles by", "字幕由", "谢谢观看", "感谢观看"
        ]
        if transcript.lower() in hallucinations:
            logger.info(f"Filtered Whisper hallucination artifact: '{transcript}'")
            return ""
            
        logger.info(f"Transcription successful: {transcript}")
        return transcript
        
    except Exception as e:
        logger.error(f"Failed to transcribe audio: {e}")
        return ""

def _parse_json_from_llm(raw_text: str) -> dict:
    """Helper to extract and parse JSON from LLM output with auto-repair fallback."""
    if not raw_text or not raw_text.strip():
        return None
    raw_text = raw_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'").strip()
    json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    clean_json = json_match.group(0) if json_match else raw_text
    
    try:
        return json.loads(clean_json)
    except json.JSONDecodeError:
        # Fallback: attempt to repair truncated JSON (e.g. unclosed brackets)
        try:
            repaired = clean_json.rstrip()
            if not repaired.endswith("}"):
                repaired = repaired + "}"
            return json.loads(repaired)
        except Exception:
            try:
                # Try trimming up to last comma and adding closing bracket
                last_comma = clean_json.rfind(",")
                if last_comma != -1:
                    repaired_comma = clean_json[:last_comma] + "}"
                    return json.loads(repaired_comma)
            except Exception:
                pass
        logger.error(f"Failed to parse LLM JSON: {raw_text[:200]}...")
        return None

def generate_response(prompt: str, contact_info: dict, db_context: dict = None, images: list = None, conversation_history: str = "") -> dict:
    """
    Calls the vLLM via OpenAI API spec to categorize and generate a response.
    Returns a dict containing 'intent' and 'response'.
    """
    role = db_context.get("role", "customer") if db_context else "customer"
    context_data = json.dumps(db_context.get("data", {})) if db_context else "{}"
    
    system_prompt = f"""
    You are an expert Real Estate AI CRM assistant for Home IHC Sdn Bhd.
    The current user has the role: {role}.
    
    Recent Conversation History (Chronological):
    {conversation_history}
    
    Database Context:
    {context_data}
    
    Instructions:
    1. Read the Conversation History carefully. The user might change their mind or correct you (e.g. "no, I want X instead of Y"). ALWAYS respect their most recent request and adjust your response accordingly.
    2. DO NOT invent or make up properties. ONLY suggest properties that are explicitly listed in the Database Context. If the Database Context doesn't have matching listings, explicitly tell the user.
    3. Present ALL matching properties provided in the Database Context clearly. Do not artificially limit the number unless the user asks for a specific number.
    4. If the user is a Bank Valuer, ask them for the property location, quoted bank value, and listed selling price so we can log it.
    5. If the user's intent is unclear, ask a polite clarifying question.
    6. Analyze any attached images or documents closely to answer the user's inquiry.
    7. You MUST output your response strictly as a JSON object with exactly four string fields:
       - "intent": Classify the user into one of: "buyer", "seller", "tenant", "agent", "bank valuer", or "general".
       - "lead_temperature": Analyze the user's sentiment ("Hot", "Warm", or "Cooling").
       - "response": Your friendly, helpful, conversational reply to the user.
       - "summary": A brief one or two sentence summary of the conversation so far, capturing the user's main needs or questions.
    """
    
    user_content = []
    if prompt:
        user_content.append({"type": "text", "text": prompt})
    else:
        user_content.append({"type": "text", "text": "Please analyze the attached context."})
        
    if images:
        for img in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img}"}
            })
            
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        raw_text = response.choices[0].message.content
        
        parsed = _parse_json_from_llm(raw_text)
        if parsed:
            # Edge case handling
            if isinstance(parsed.get("response"), str) and '"intent"' in parsed.get("response") and '"response"' in parsed.get("response"):
                try:
                    inner_parsed = json.loads(parsed["response"].replace('“', '"').replace('”', '"'))
                    parsed["response"] = inner_parsed.get("response", parsed["response"])
                except json.JSONDecodeError:
                    match = re.search(r'"response"\s*:\s*"([^"]*)', parsed["response"])
                    if match:
                        parsed["response"] = match.group(1)
            return parsed
        else:
            match = re.search(r'"response"\s*:\s*"([^"]*)', raw_text)
            fallback_response = match.group(1) if match else "I'm sorry, I'm having trouble processing your request completely right now. A senior agent will contact you shortly."
            return {"intent": "general", "lead_temperature": "Warm", "response": fallback_response}
            
    except Exception as e:
        logger.error(f"Failed to communicate with LLM: {e}")
        raise e

def extract_property_search_criteria(prompt: str, conversation_history: str = "") -> dict:
    """
    Extracts property search criteria from the user's prompt using the LLM.
    Returns a dictionary with 'location', 'property_type', and 'max_price'.
    """
    system_prompt = f"""
    You are an intelligent real estate search parser. 
    Analyze the user's latest message and the recent conversation history to extract the property search criteria.
    Pay close attention to corrections (e.g., if the user previously wanted Raub but now wants Bentong, output Bentong).
    
    Recent Conversation History (Chronological):
    {conversation_history}
    
    Current Message:
    {prompt}
    
    Output strictly as a JSON object with these fields:
    - "location": The specific city, state, or area explicitly mentioned by the user. If the user does NOT explicitly mention a location, you MUST output null.
    - "property_type": The type of property explicitly mentioned (e.g., "land", "orchard", "house"). Output null if not specified.
    - "max_price": The maximum budget as an integer. Output null if not specified.
    """
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_json_from_llm(raw_text)
        if parsed:
            return {
                "location": parsed.get("location"),
                "property_type": parsed.get("property_type"),
                "max_price": parsed.get("max_price")
            }
        return {}
    except Exception as e:
        logger.error(f"Failed to extract search criteria: {e}")
        return {}

def extract_valuer_data(prompt: str, conversation_history: str = "") -> dict:
    """
    Extracts Bank Valuer details from the user's prompt using the LLM.
    Returns a dictionary with 'property_location', 'quoted_bank_value', and 'listed_selling_price'.
    """
    system_prompt = f"""
    You are an intelligent data extractor for real estate operations.
    Analyze the user's latest message and the recent conversation history to extract Bank Valuer details.
    
    Recent Conversation History (Chronological):
    {conversation_history}
    
    Current Message:
    {prompt}
    
    Output strictly as a JSON object with these fields:
    - "property_location": The address or location of the property being valued (string). Output null if not specified.
    - "quoted_bank_value": The bank valuation amount (integer or float). Output null if not specified.
    - "listed_selling_price": The listed selling price on the market (integer or float). Output null if not specified.
    """
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_json_from_llm(raw_text)
        if parsed:
            return {
                "property_location": parsed.get("property_location"),
                "quoted_bank_value": parsed.get("quoted_bank_value"),
                "listed_selling_price": parsed.get("listed_selling_price")
            }
        return {}
    except Exception as e:
        logger.error(f"Failed to extract valuer data: {e}")
        return {}

TOWN_COORDINATES = {
    "bentong": (3.5222, 101.9085),
    "raub": (3.7899, 101.8570),
    "karak": (3.4182, 102.0460),
    "temerloh": (3.4485, 102.4173),
    "mentakab": (3.4854, 102.3484),
    "cheroh": (3.9167, 101.8333),
    "tras": (3.7500, 101.8000),
    "bukit tinggi": (3.3500, 101.8333),
    "janda baik": (3.3167, 101.8833),
    "triang": (3.2500, 102.4167),
    "kuala lipis": (4.1833, 102.0500),
    "lipis": (4.1833, 102.0500),
    "teluk intan": (4.0042, 101.0360),
    "kuantan": (3.8077, 103.3260),
}

def extract_wordpress_property(payload: dict) -> dict:
    """
    Extracts structured property details from the raw WordPress webhook payload using
    deterministic NLP + targeted LLM enrichment.
    Populates all 12 database categories without exceeding vLLM 2048-token limits.
    """
    from app.services.embeddings import generate_property_5_embeddings
    from scripts.scrape_and_ingest_all_properties import extract_all_property_details

    title = payload.get("title", "")
    description = payload.get("description", "")
    categories = payload.get("categories", [])
    status = payload.get("status", "For Sale")
    
    # 1. Deterministic baseline (100% reliable, immune to LLM 400 Bad Request)
    det = extract_all_property_details(title, description, initial_categories=categories, initial_status=status)
    
    extracted_data = {
        "title": title,
        "property_type_sub": det.get("property_type_sub"),
        "property_category": categories or det.get("property_category", ["Agricultural Land"]),
        "asking_price_myr": det.get("asking_price_myr") or 0.0,
        "currency": "MYR",
        "monthly_rental_income_myr": det.get("monthly_rental_income_myr"),
        "price_per_acre_myr": det.get("price_per_acre_myr"),
        "price_per_sqft_myr": det.get("price_per_sqft_myr"),
        "implied_yield_pct": det.get("implied_yield_pct"),
        "land_area_acres": det.get("land_area_acres"),
        "land_area_sqft": det.get("land_area_sqft"),
        "land_area_sqm": det.get("land_area_sqm"),
        "built_up_area_sqft": det.get("built_up_area_sqft"),
        "tenure_type": det.get("tenure_type"),
        "zoning_type": det.get("zoning_type"),
        "title_status": det.get("title_status"),
        "crop_types": det.get("crop_types") or [],
        "tree_count_estimate": det.get("tree_count_estimate"),
        "tree_age_years": det.get("tree_age_years"),
        "harvest_readiness": det.get("harvest_readiness"),
        "topography": det.get("topography"),
        "water_source_types": det.get("water_source_types") or [],
        "has_natural_stream": bool(det.get("has_natural_stream", False)),
        "has_pond": bool(det.get("has_pond", False)),
        "has_piping_system": bool(det.get("has_piping_system", False)),
        "is_flood_free": bool(det.get("is_flood_free", True)),
        "power_supply_amp": det.get("power_supply_amp"),
        "utilities_available": det.get("utilities_available") or [],
        "has_office": bool(det.get("has_office", False)),
        "office_features": det.get("office_features"),
        "road_access_quality": det.get("road_access_quality"),
        "is_fenced": bool(det.get("is_fenced", False)),
        "has_worker_quarters": bool(det.get("has_worker_quarters", False)),
        "is_tenanted": False,
        "lease_start_date": None,
        "lease_end_date": None,
        "current_tenant_use": None,
        "street_address": det.get("street_address"),
        "area": det.get("area"),
        "city": det.get("city") or "Bentong",
        "state": det.get("state") or "Pahang",
        "country": "Malaysia",
        "latitude": None,
        "longitude": None,
        "nearby_landmarks": det.get("nearby_landmarks") or [],
        "suitable_industries": det.get("suitable_industries") or [],
        "key_highlights": [],
        "risk_flags": [],
        "listing_status": status,
        "search_corpus_markdown": f"{title}\n\n{description}",
        "agency_name": "HOME IHC SDN. BHD.",
        "agent_name": det.get("agent_name") or "Irene Leong",
        "agent_phone": det.get("agent_phone") or "+6011-65144931",
        "agent_whatsapp_url": det.get("agent_whatsapp_url") or "https://phgland.wasap.my/",
        "image_urls": payload.get("image_urls", []),
        "floor_plan_url": None,
        "months_to_lease_expiry": None,
        "embedding_location": None,
        "embedding_specs": None,
        "embedding_features": None,
        "embedding_suitability": None,
        "embedding_overview": None,
    }
    
    # 2. Targeted concise LLM Enrichment (~250 prompt tokens + ~250 input tokens = well within 2048 max context)
    system_prompt = """You are a real estate analyst in Malaysia. Extract additional qualitative insights from the property.
Return JSON with:
- "property_type_sub": String (e.g. Durian Land, Commercial Land, Terrace House)
- "suitable_industries": List of strings
- "key_highlights": List of 3 concise bullet strings
- "risk_flags": List of strings
- "nearby_landmarks": List of strings"""

    content = f"Title: {title}\nDescription: {description[:1000]}"
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
            timeout=15.0
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_json_from_llm(raw_text)
        
        if parsed and isinstance(parsed, dict):
            if parsed.get("property_type_sub") and not extracted_data["property_type_sub"]:
                extracted_data["property_type_sub"] = parsed["property_type_sub"]
            if parsed.get("key_highlights") and isinstance(parsed["key_highlights"], list):
                extracted_data["key_highlights"] = [str(x) for x in parsed["key_highlights"] if x]
            if parsed.get("risk_flags") and isinstance(parsed["risk_flags"], list):
                extracted_data["risk_flags"] = [str(x) for x in parsed["risk_flags"] if x]
            if parsed.get("nearby_landmarks") and isinstance(parsed["nearby_landmarks"], list):
                extracted_data["nearby_landmarks"] = list(set(extracted_data["nearby_landmarks"] + [str(x) for x in parsed["nearby_landmarks"] if x]))
            if parsed.get("suitable_industries") and isinstance(parsed["suitable_industries"], list):
                extracted_data["suitable_industries"] = list(set(extracted_data["suitable_industries"] + [str(x) for x in parsed["suitable_industries"] if x]))
    except Exception as e:
        logger.warning(f"Optional LLM qualitative enrichment note for '{title[:30]}': {e}")

    # Geocoding approximate lat/lng from town/city
    city_lower = (extracted_data["city"] or "").lower().strip()
    area_lower = (extracted_data["area"] or "").lower().strip()
    for town_key, coords in TOWN_COORDINATES.items():
        if town_key in city_lower or town_key in area_lower:
            extracted_data["latitude"] = coords[0]
            extracted_data["longitude"] = coords[1]
            break

    # Generate 5-aspect vector embeddings
    try:
        embeddings_dict = generate_property_5_embeddings(extracted_data)
        extracted_data.update(embeddings_dict)
    except Exception as emb_err:
        logger.warning(f"Could not generate embeddings for {title}: {emb_err}")
        
    return extracted_data

def classify_intent(text: str, conversation_history: str = "") -> str:
    """
    Phase 2 Router Agent logic. Classifies user into:
    PERSONAL_BUYER, AGENT_BROKER, SELLER, TENANT, LANDLORD, VALUER, GENERAL
    """
    system_prompt = f"""
    You are a Real Estate classification assistant. Read the user's message and determine their category from: 
    PERSONAL_BUYER, AGENT_BROKER, SELLER, TENANT, LANDLORD, VALUER, GENERAL.
    
    Recent Conversation History:
    {conversation_history}
    
    User Message:
    {text}
    
    Output strictly as a JSON object with a single field "category".
    """
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_json_from_llm(raw_text)
        if parsed and parsed.get("category"):
            return parsed.get("category").upper()
        return "GENERAL"
    except Exception as e:
        logger.error(f"Failed to classify intent: {e}")
        return "GENERAL"

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
    Downloads audio and sends to Whisper (or Gemma 4 audio model) for transcription.
    This runs inside a Celery task, so it safely blocks until the transcription is done.
    """
    logger.info(f"Transcribing audio from {audio_url}")
    
    try:
        # 1. Download audio
        audio_resp = requests.get(audio_url, timeout=30)
        audio_resp.raise_for_status()
        
        # 2. POST to whisper API
        files = {
            'file': ('audio.ogg', audio_resp.content, 'audio/ogg')
        }
        data = {
            'model': 'whisper-1'
        }
        
        logger.info(f"Sending audio to Whisper API: {WHISPER_API_URL}")
        whisper_resp = requests.post(WHISPER_API_URL, files=files, data=data, timeout=120)
        
        if whisper_resp.status_code != 200:
            logger.error(f"Whisper API failed with status {whisper_resp.status_code}: {whisper_resp.text}")
            whisper_resp.raise_for_status()
            
        # 3. Return text
        result = whisper_resp.json()
        transcript = result.get("text", "")
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
    Extracts structured property details from the raw WordPress webhook payload using the LLM.
    Populates all 12 database categories: Core, Financials, Physical Specs, Agricultural/Crops,
    Topography/Water, Infrastructure, Tenancy, Geospatial, Vector Embeddings, Agency, and AI Analytics.
    """
    from app.services.embeddings import generate_property_5_embeddings

    title = payload.get("title", "")
    description = payload.get("description", "")
    
    system_prompt = f"""
    You are an expert real estate data engineer and valuation analyst for Malaysia (Pahang, Perak, Selangor).
    Analyze the provided raw WordPress property title, description, and specifications.
    
    Extract and output strictly as a JSON object with these exact structured fields. Use null if a value is not found:
    - "property_type_sub": String (e.g., "Durian Land", "Rubber Land", "Oil Palm Land", "Vacant Land", "Commercial Land", "Shop", "Warehouse", "Factory", "Semi-D House", "Bungalow", "Terrace House").
    - "category": List of strings (e.g., ["Agricultural Land", "Durian Land"] or ["Commercial", "Shop"] or ["Industrial", "Warehouse"]).
    - "asking_price_myr": Float. Listed selling price (or 0.0 if for rent).
    - "monthly_rental_income_myr": Float. Current or estimated monthly rental income / rental fee.
    - "price_per_acre_myr": Float. Price per acre if mentioned or calculable.
    - "price_per_sqft_myr": Float. Price per sqft if mentioned or calculable.
    - "implied_yield_pct": Float. Estimated gross ROI / yield percentage per annum.
    - "land_area_acres": Float. Total land size in acres.
    - "land_area_sqft": Float. Total land size in square feet.
    - "land_area_sqm": Float. Total land size in square meters or hectares converted to sqm.
    - "built_up_area_sqft": Float. Warehouse/Factory/House built-up floor area.
    - "tenure_type": String (e.g., "Freehold", "Leasehold", "Malay Reserved").
    - "zoning_type": String (e.g., "Agricultural", "Residential", "Commercial", "Industrial").
    - "title_status": String (e.g., "Individual Title", "Master Title", "Commercial Building Title", "Agricultural Title").
    
    Agricultural & Land Fields (for durian/fruit/rubber/oil palm land):
    - "crop_types": List of strings (e.g., ["Musang King", "Black Thorn", "D24", "Rubber", "Oil Palm", "Mixed Fruit"]).
    - "tree_count_estimate": Integer. Total estimated number of trees.
    - "tree_age_years": String (e.g., "6-8 years (Mature Fruit-Bearing)", "2-3 years young").
    - "harvest_readiness": String ("Mature Fruit-Bearing", "Young Planting", "Vacant/Cleared").
    
    Topography & Water Resources:
    - "topography": String ("Flat", "Gentle Slope", "Hilly/Terraced", "Hilltop View", "Undulating").
    - "water_source_types": List of strings (e.g., ["Natural River Stream", "Pond", "PAIP Water", "Spring/Well", "Irrigation Piping Installed"]).
    - "has_natural_stream": Boolean. True if natural river/stream on or bordering land.
    - "has_pond": Boolean. True if water pond/lake on site.
    - "has_piping_system": Boolean. True if irrigation system/piping installed.
    - "is_flood_free": Boolean. True if mentioned as flood-free or high ground.
    
    Infrastructure & Technical:
    - "power_supply_amp": Integer (e.g., 60, 100, 300, 1200).
    - "utilities_available": List of strings (e.g., ["Electricity (TNB)", "Water (PAIP)"]).
    - "has_office": Boolean. True if office/workers quarters present.
    - "office_features": String.
    - "road_access_quality": String (e.g., "Main Road Frontage", "Tar Road Access", "Concrete Road", "4WD Required").
    - "is_fenced": Boolean. True if compound is fenced/gated.
    - "has_worker_quarters": Boolean. True if worker house or quarters built on site.
    
    Tenancy & Commercial Status:
    - "is_tenanted": Boolean.
    - "lease_start_date": String (YYYY-MM-DD) or null.
    - "lease_end_date": String (YYYY-MM-DD) or null.
    - "current_tenant_use": String.
    
    Location & Geospatial:
    - "street_address": String (e.g., "Jalan Industri 3", "Telemong Batu 34").
    - "area": String (e.g., "Bukit Bendera", "Cheroh", "Taman Jaya 7").
    - "city": String (e.g., "Bentong", "Raub", "Karak", "Temerloh", "Mentakab", "Teluk Intan").
    - "state": String (e.g., "Pahang", "Perak", "Selangor").
    - "nearby_landmarks": List of strings (e.g., ["Opposite Mentakab Star Mall", "Near ECRL", "Near Karak Highway Exit"]).
    
    AI Analytics:
    - "suitable_industries": List of strings (e.g., ["durian plantation", "homestay resort", "glamping", "courier logistics", "showroom"]).
    - "key_highlights": List of strings (Top 3-5 high-impact bullet points for buyers).
    - "risk_flags": List of strings (e.g., ["Malay Reserved Land - Malay buyers only", "4WD required for access"]).
    - "status": String ("For Sale", "For Rent", "Available", "Sold", "Pending").
    """
    
    content = f"Title: {title}\n\nDescription: {description}"
    
    extracted_data = {
        "title": title,
        "property_type_sub": None,
        "property_category": payload.get("categories", []),
        "asking_price_myr": 0.0,
        "currency": "MYR",
        "monthly_rental_income_myr": None,
        "price_per_acre_myr": None,
        "price_per_sqft_myr": None,
        "implied_yield_pct": None,
        "land_area_acres": None,
        "land_area_sqft": None,
        "land_area_sqm": None,
        "built_up_area_sqft": None,
        "tenure_type": None,
        "zoning_type": None,
        "title_status": None,
        "crop_types": [],
        "tree_count_estimate": None,
        "tree_age_years": None,
        "harvest_readiness": None,
        "topography": None,
        "water_source_types": [],
        "has_natural_stream": False,
        "has_pond": False,
        "has_piping_system": False,
        "is_flood_free": True,
        "power_supply_amp": None,
        "utilities_available": [],
        "has_office": False,
        "office_features": None,
        "road_access_quality": None,
        "is_fenced": False,
        "has_worker_quarters": False,
        "is_tenanted": False,
        "lease_start_date": None,
        "lease_end_date": None,
        "current_tenant_use": None,
        "street_address": None,
        "area": None,
        "city": None,
        "state": "Pahang",
        "country": "Malaysia",
        "latitude": None,
        "longitude": None,
        "nearby_landmarks": [],
        "suitable_industries": [],
        "key_highlights": [],
        "risk_flags": [],
        "listing_status": payload.get("status", "For Sale"),
        "search_corpus_markdown": f"{title}\n\n{description}",
        "agency_name": "HOME IHC SDN. BHD.",
        "agent_name": "Irene Leong",
        "agent_phone": "+6011-65144931",
        "agent_whatsapp_url": "https://my.mecard.my/1733211127",
        "image_urls": payload.get("image_urls", []),
        "floor_plan_url": None,
        "months_to_lease_expiry": None,
        "embedding_location": None,
        "embedding_specs": None,
        "embedding_features": None,
        "embedding_suitability": None,
        "embedding_overview": None,
    }
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            response_format={"type": "json_object"},
            max_tokens=2048
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_json_from_llm(raw_text)
        
        if parsed:
            def safe_float(val):
                if val is None: return None
                try:
                    return float(str(val).replace(",", "").replace("RM", "").replace("%", "").strip())
                except ValueError:
                    return None
                    
            def safe_int(val):
                if val is None: return None
                try:
                    return int(float(str(val).replace(",", "").strip()))
                except ValueError:
                    return None

            extracted_data["property_type_sub"] = parsed.get("property_type_sub")
            if parsed.get("category") and isinstance(parsed.get("category"), list):
                extracted_data["property_category"] = parsed.get("category")
                
            extracted_data["asking_price_myr"] = safe_float(parsed.get("asking_price_myr")) or 0.0
            extracted_data["monthly_rental_income_myr"] = safe_float(parsed.get("monthly_rental_income_myr"))
            extracted_data["price_per_acre_myr"] = safe_float(parsed.get("price_per_acre_myr"))
            extracted_data["price_per_sqft_myr"] = safe_float(parsed.get("price_per_sqft_myr"))
            extracted_data["implied_yield_pct"] = safe_float(parsed.get("implied_yield_pct"))
            
            # Auto-calculate implied yield if not set
            if extracted_data["monthly_rental_income_myr"] and extracted_data["asking_price_myr"] and extracted_data["asking_price_myr"] > 0:
                if not extracted_data["implied_yield_pct"]:
                    extracted_data["implied_yield_pct"] = round((extracted_data["monthly_rental_income_myr"] * 12 / extracted_data["asking_price_myr"]) * 100, 2)
            
            extracted_data["land_area_acres"] = safe_float(parsed.get("land_area_acres"))
            extracted_data["land_area_sqft"] = safe_float(parsed.get("land_area_sqft"))
            extracted_data["land_area_sqm"] = safe_float(parsed.get("land_area_sqm"))
            extracted_data["built_up_area_sqft"] = safe_float(parsed.get("built_up_area_sqft"))
            
            # Auto-calculate derived areas
            if extracted_data["land_area_acres"] and not extracted_data["land_area_sqft"]:
                extracted_data["land_area_sqft"] = round(extracted_data["land_area_acres"] * 43560.0, 2)
            if extracted_data["land_area_sqft"] and not extracted_data["land_area_acres"]:
                extracted_data["land_area_acres"] = round(extracted_data["land_area_sqft"] / 43560.0, 4)
            if extracted_data["asking_price_myr"] and extracted_data["land_area_acres"] and extracted_data["land_area_acres"] > 0:
                if not extracted_data["price_per_acre_myr"]:
                    extracted_data["price_per_acre_myr"] = round(extracted_data["asking_price_myr"] / extracted_data["land_area_acres"], 2)
            if extracted_data["asking_price_myr"] and extracted_data["land_area_sqft"] and extracted_data["land_area_sqft"] > 0:
                if not extracted_data["price_per_sqft_myr"]:
                    extracted_data["price_per_sqft_myr"] = round(extracted_data["asking_price_myr"] / extracted_data["land_area_sqft"], 2)

            extracted_data["tenure_type"] = parsed.get("tenure_type")
            extracted_data["zoning_type"] = parsed.get("zoning_type")
            extracted_data["title_status"] = parsed.get("title_status")
            
            extracted_data["crop_types"] = parsed.get("crop_types", []) if isinstance(parsed.get("crop_types"), list) else []
            extracted_data["tree_count_estimate"] = safe_int(parsed.get("tree_count_estimate"))
            extracted_data["tree_age_years"] = parsed.get("tree_age_years")
            extracted_data["harvest_readiness"] = parsed.get("harvest_readiness")
            
            extracted_data["topography"] = parsed.get("topography")
            extracted_data["water_source_types"] = parsed.get("water_source_types", []) if isinstance(parsed.get("water_source_types"), list) else []
            extracted_data["has_natural_stream"] = bool(parsed.get("has_natural_stream"))
            extracted_data["has_pond"] = bool(parsed.get("has_pond"))
            extracted_data["has_piping_system"] = bool(parsed.get("has_piping_system"))
            extracted_data["is_flood_free"] = bool(parsed.get("is_flood_free", True))
            
            extracted_data["power_supply_amp"] = safe_int(parsed.get("power_supply_amp"))
            extracted_data["utilities_available"] = parsed.get("utilities_available", []) if isinstance(parsed.get("utilities_available"), list) else []
            extracted_data["has_office"] = bool(parsed.get("has_office"))
            extracted_data["office_features"] = parsed.get("office_features")
            extracted_data["road_access_quality"] = parsed.get("road_access_quality")
            extracted_data["is_fenced"] = bool(parsed.get("is_fenced"))
            extracted_data["has_worker_quarters"] = bool(parsed.get("has_worker_quarters"))
            
            extracted_data["is_tenanted"] = bool(parsed.get("is_tenanted"))
            extracted_data["lease_start_date"] = parsed.get("lease_start_date")
            extracted_data["lease_end_date"] = parsed.get("lease_end_date")
            extracted_data["current_tenant_use"] = parsed.get("current_tenant_use")
            
            extracted_data["street_address"] = parsed.get("street_address")
            extracted_data["area"] = parsed.get("area")
            extracted_data["city"] = parsed.get("city")
            extracted_data["state"] = parsed.get("state") or "Pahang"
            extracted_data["nearby_landmarks"] = parsed.get("nearby_landmarks", []) if isinstance(parsed.get("nearby_landmarks"), list) else []
            
            # Geocoding approximate lat/lng from town/city
            city_lower = (extracted_data["city"] or "").lower().strip()
            area_lower = (extracted_data["area"] or "").lower().strip()
            for town_key, coords in TOWN_COORDINATES.items():
                if town_key in city_lower or town_key in area_lower:
                    extracted_data["latitude"] = coords[0]
                    extracted_data["longitude"] = coords[1]
                    break
            
            extracted_data["suitable_industries"] = parsed.get("suitable_industries", []) if isinstance(parsed.get("suitable_industries"), list) else []
            extracted_data["key_highlights"] = parsed.get("key_highlights", []) if isinstance(parsed.get("key_highlights"), list) else []
            extracted_data["risk_flags"] = parsed.get("risk_flags", []) if isinstance(parsed.get("risk_flags"), list) else []
            
            if parsed.get("status"):
                extracted_data["listing_status"] = parsed.get("status")
                
            # Generate 5-aspect vector embeddings
            try:
                embeddings_dict = generate_property_5_embeddings(extracted_data)
                extracted_data.update(embeddings_dict)
            except Exception as emb_err:
                logger.warning(f"Could not generate embeddings for {title}: {emb_err}")
                
    except Exception as e:
        logger.error(f"Failed to extract WordPress property data: {e}")
        
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

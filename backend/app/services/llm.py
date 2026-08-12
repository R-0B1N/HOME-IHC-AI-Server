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
    """Helper to extract and parse JSON from LLM output."""
    raw_text = raw_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    clean_json = json_match.group(0) if json_match else raw_text
    
    try:
        return json.loads(clean_json)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse LLM JSON: {raw_text}")
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

def extract_wordpress_property(payload: dict) -> dict:
    """
    Extracts structured property details from the raw WordPress webhook payload using the LLM.
    """
    title = payload.get("title", "")
    description = payload.get("description", "")
    
    system_prompt = f"""
    You are an intelligent data extractor for real estate operations.
    Analyze the provided raw WordPress property title and description.
    
    Output strictly as a JSON object with these exact fields. Use null if a value is not specified or cannot be inferred:
    - "asking_price_myr": Float. The listed asking price.
    - "monthly_rental_income_myr": Float. Current or estimated monthly rental income.
    - "implied_yield_pct": Float. Estimated gross ROI percentage per annum.
    - "category": List of strings (e.g., ["Commercial", "Shop"]).
    - "land_area_sqft": Float.
    - "land_area_acres": Float.
    - "land_area_sqm": Float.
    - "built_up_area_sqft": Float.
    - "tenure_type": String (e.g., "Freehold", "Leasehold").
    - "zoning_type": String (e.g., "Commercial", "Industrial").
    - "power_supply_amp": Integer.
    - "utilities_available": List of strings (e.g., ["Electricity", "Water"]).
    - "has_office": Boolean. True if the property has an office.
    - "office_features": String.
    - "road_access_quality": String.
    - "is_tenanted": Boolean. True if currently tenanted.
    - "lease_start_date": String (YYYY-MM-DD).
    - "lease_end_date": String (YYYY-MM-DD).
    - "current_tenant_use": String.
    - "street_address": String.
    - "area": String (e.g., "Taman Desa Damai").
    - "city": String (e.g., "Bentong").
    - "state": String (e.g., "Pahang").
    - "suitable_industries": List of strings.
    - "key_highlights": List of strings.
    - "risk_flags": List of strings (e.g., upcoming lease expiry).
    - "status": String (e.g., "For Sale", "Available").
    """
    
    content = f"Title: {title}\n\nDescription: {description}"
    
    extracted_data = {
        "asking_price_myr": 0.0,
        "monthly_rental_income_myr": None,
        "implied_yield_pct": None,
        "category": [],
        "land_area_sqft": None,
        "land_area_acres": None,
        "land_area_sqm": None,
        "built_up_area_sqft": None,
        "tenure_type": None,
        "zoning_type": None,
        "power_supply_amp": None,
        "utilities_available": [],
        "has_office": False,
        "office_features": None,
        "road_access_quality": None,
        "is_tenanted": False,
        "lease_start_date": None,
        "lease_end_date": None,
        "current_tenant_use": None,
        "street_address": None,
        "area": None,
        "city": None,
        "state": None,
        "suitable_industries": [],
        "key_highlights": [],
        "risk_flags": [],
        "status": payload.get("status", "Available")
    }
    
    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            response_format={"type": "json_object"}
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
                    return int(str(val).replace(",", "").strip())
                except ValueError:
                    return None

            extracted_data["asking_price_myr"] = safe_float(parsed.get("asking_price_myr")) or 0.0
            extracted_data["monthly_rental_income_myr"] = safe_float(parsed.get("monthly_rental_income_myr"))
            extracted_data["implied_yield_pct"] = safe_float(parsed.get("implied_yield_pct"))
            
            extracted_data["category"] = parsed.get("category", []) if isinstance(parsed.get("category"), list) else []
            
            extracted_data["land_area_sqft"] = safe_float(parsed.get("land_area_sqft"))
            extracted_data["land_area_acres"] = safe_float(parsed.get("land_area_acres"))
            extracted_data["land_area_sqm"] = safe_float(parsed.get("land_area_sqm"))
            extracted_data["built_up_area_sqft"] = safe_float(parsed.get("built_up_area_sqft"))
            
            extracted_data["tenure_type"] = parsed.get("tenure_type")
            extracted_data["zoning_type"] = parsed.get("zoning_type")
            extracted_data["power_supply_amp"] = safe_int(parsed.get("power_supply_amp"))
            extracted_data["utilities_available"] = parsed.get("utilities_available", []) if isinstance(parsed.get("utilities_available"), list) else []
            extracted_data["has_office"] = bool(parsed.get("has_office"))
            extracted_data["office_features"] = parsed.get("office_features")
            extracted_data["road_access_quality"] = parsed.get("road_access_quality")
            
            extracted_data["is_tenanted"] = bool(parsed.get("is_tenanted"))
            extracted_data["lease_start_date"] = parsed.get("lease_start_date")
            extracted_data["lease_end_date"] = parsed.get("lease_end_date")
            extracted_data["current_tenant_use"] = parsed.get("current_tenant_use")
            
            extracted_data["street_address"] = parsed.get("street_address")
            extracted_data["area"] = parsed.get("area")
            extracted_data["city"] = parsed.get("city")
            extracted_data["state"] = parsed.get("state")
            
            extracted_data["suitable_industries"] = parsed.get("suitable_industries", []) if isinstance(parsed.get("suitable_industries"), list) else []
            extracted_data["key_highlights"] = parsed.get("key_highlights", []) if isinstance(parsed.get("key_highlights"), list) else []
            extracted_data["risk_flags"] = parsed.get("risk_flags", []) if isinstance(parsed.get("risk_flags"), list) else []
            
            if parsed.get("status"):
                extracted_data["status"] = parsed.get("status")
                
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

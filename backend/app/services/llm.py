import logging
import requests
import os
import json

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://crm-whisper:8000/v1/audio/transcriptions")

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

def generate_response(prompt: str, contact_info: dict, db_context: dict = None, images: list = None, conversation_history: str = "") -> dict:
    """
    Calls the local LLM (e.g. Ollama or vLLM) to categorize and generate a response.
    Returns a dict containing 'intent' and 'response'.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
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
    6. You MUST output your response strictly as a JSON object with exactly four string fields:
       - "intent": Classify the user into one of: "buyer", "seller", "tenant", "agent", "bank valuer", or "general".
       - "lead_temperature": Analyze the user's sentiment ("Hot", "Warm", or "Cooling").
       - "response": Your friendly, helpful, conversational reply to the user.
       - "summary": A brief one or two sentence summary of the conversation so far, capturing the user's main needs or questions.
    """
    
    payload = {
        "model": "gemma4:e4b-it-bf16", # Updated to match available model
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json"
    }
    
    if images:
        payload["images"] = images
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        raw_text = result.get("response", "{}")
        
        # Replace smart quotes that break JSON parsing
        raw_text = raw_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
        
        # Strip markdown json blocks if present
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        clean_json = json_match.group(0) if json_match else raw_text
        
        try:
            parsed = json.loads(clean_json)
            # Edge case: LLM sometimes wraps the JSON inside the response key itself
            if isinstance(parsed.get("response"), str) and '"intent"' in parsed.get("response") and '"response"' in parsed.get("response"):
                try:
                    inner_parsed = json.loads(parsed["response"].replace('“', '"').replace('”', '"'))
                    parsed["response"] = inner_parsed.get("response", parsed["response"])
                except json.JSONDecodeError:
                    # Strip out the JSON-like structure from the response string if inner parsing fails
                    match = re.search(r'"response"\s*:\s*"([^"]*)', parsed["response"])
                    if match:
                        parsed["response"] = match.group(1)
            return parsed
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM JSON: {raw_text}")
            
            # Try to extract the response field if the JSON is malformed or truncated
            match = re.search(r'"response"\s*:\s*"([^"]*)', raw_text)
            if match:
                fallback_response = match.group(1)
            else:
                fallback_response = "I'm sorry, I'm having trouble processing your request completely right now. Our team will assist you shortly."
            
            return {"intent": "general", "lead_temperature": "Warm", "response": fallback_response}
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to communicate with LLM: {e}")
        raise e

def extract_property_search_criteria(prompt: str, conversation_history: str = "") -> dict:
    """
    Extracts property search criteria from the user's prompt using the LLM.
    Returns a dictionary with 'location', 'property_type', and 'max_price'.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
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
    
    payload = {
        "model": "gemma4:e4b-it-bf16",
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        raw_text = result.get("response", "{}")
        raw_text = raw_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        clean_json = json_match.group(0) if json_match else raw_text
        
        try:
            parsed = json.loads(clean_json)
            return {
                "location": parsed.get("location"),
                "property_type": parsed.get("property_type"),
                "max_price": parsed.get("max_price")
            }
        except json.JSONDecodeError:
            logger.error(f"Failed to parse criteria JSON: {raw_text}")
            return {}
    except Exception as e:
        logger.error(f"Failed to extract search criteria: {e}")
        return {}

def extract_valuer_data(prompt: str, conversation_history: str = "") -> dict:
    """
    Extracts Bank Valuer details from the user's prompt using the LLM.
    Returns a dictionary with 'property_location', 'quoted_bank_value', and 'listed_selling_price'.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
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
    
    payload = {
        "model": "gemma4:e4b-it-bf16",
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        raw_text = result.get("response", "{}")
        raw_text = raw_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        clean_json = json_match.group(0) if json_match else raw_text
        
        try:
            parsed = json.loads(clean_json)
            return {
                "property_location": parsed.get("property_location"),
                "quoted_bank_value": parsed.get("quoted_bank_value"),
                "listed_selling_price": parsed.get("listed_selling_price")
            }
        except json.JSONDecodeError:
            logger.error(f"Failed to parse valuer data JSON: {raw_text}")
            return {}
    except Exception as e:
        logger.error(f"Failed to extract valuer data: {e}")
        return {}

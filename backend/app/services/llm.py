import logging
import requests
import os
import json

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://localhost:8080/inference") # Example for local whisper server

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
        # Assuming an OpenAI-compatible endpoint that expects multipart/form-data
        files = {
            'file': ('audio.ogg', audio_resp.content, 'audio/ogg')
        }
        data = {
            'model': 'whisper-1'
        }
        
        whisper_resp = requests.post(WHISPER_API_URL, files=files, data=data, timeout=120)
        whisper_resp.raise_for_status()
        
        # 3. Return text
        result = whisper_resp.json()
        return result.get("text", "")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to transcribe audio: {e}")
        return ""

def generate_response(prompt: str, contact_info: dict, db_context: dict = None, images: list = None) -> dict:
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
    Here is the relevant database context you have access to for this user:
    {context_data}
    
    Use this information to provide personalized and accurate responses.
    You MUST output your response strictly as a JSON object with exactly three string fields:
    1. "intent": Classify the user into one of: "buyer", "seller", "tenant", "agent", or "general".
    2. "lead_temperature": Analyze the user's sentiment and intent to classify them as "Hot", "Warm", or "Cooling".
    3. "response": Your conversational reply to the user based on their intent.
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
        try:
            parsed = json.loads(raw_text)
            return parsed
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM JSON: {raw_text}")
            return {"intent": "general", "response": raw_text}
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to communicate with LLM: {e}")
        raise e

def extract_property_search_criteria(prompt: str) -> dict:
    """
    Extracts property search criteria from the user's prompt using the LLM.
    Returns a dictionary with 'location', 'property_type', and 'max_price'.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    system_prompt = """
    You are an intelligent real estate search parser. 
    Analyze the user's message and extract the following property search criteria.
    Output strictly as a JSON object with these fields:
    - "location": The city, state, or area they are looking for (e.g., "Bentong", "Mentakab", "Raub"). Output null if not specified.
    - "property_type": The type of property (e.g., "bungalow", "land", "orchard", "shop", "house"). Output null if not specified.
    - "max_price": The maximum budget as an integer (e.g., 500000). Output null if not specified.
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
        try:
            parsed = json.loads(raw_text)
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

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
    # Implementation details depend on your exact local Whisper server
    # 1. Download audio
    # 2. POST to whisper API
    # 3. Return text
    
    # Placeholder
    return "Transcribed audio text"

def generate_response(prompt: str, contact_info: dict) -> dict:
    """
    Calls the local LLM (e.g. Ollama or vLLM) to categorize and generate a response.
    Returns a dict containing 'intent' and 'response'.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    system_prompt = """
    You are an expert Real Estate AI CRM assistant for Home IHC Sdn Bhd.
    You MUST output your response strictly as a JSON object with exactly two string fields:
    1. "intent": Classify the user into one of: "buyer", "seller", "tenant", "agent", or "general".
    2. "response": Your conversational reply to the user based on their intent.
    """
    
    payload = {
        "model": "gemma4:e4b-it-bf16", # Updated to match available model
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json"
    }
    
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

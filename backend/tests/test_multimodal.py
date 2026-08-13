import os
import requests
import json
import base64

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def test_vllm_text():
    print("\n--- Testing vLLM Text Generation ---")
    url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
    payload = {
        "model": "microsoft/Phi-3-vision-128k-instruct",
        "messages": [
            {"role": "user", "content": "Hello, can you extract information from this message? I want to buy a house in Bentong for RM 500,000."}
        ]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        print("Success! Response:")
        print(result.get("choices", [{}])[0].get("message", {}).get("content"))
    except Exception as e:
        print(f"Failed: {e}")

def test_vllm_image():
    print("\n--- Testing vLLM Image Processing ---")
    url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
    
    # Tiny 1x1 base64 GIF for testing network capability
    base64_image = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    
    payload = {
        "model": "microsoft/Phi-3-vision-128k-instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/gif;base64,{base64_image}"}
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        print("Success! Response:")
        print(result.get("choices", [{}])[0].get("message", {}).get("content"))
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    print(f"Running multimodal tests against vLLM at {OLLAMA_BASE_URL}...")
    test_vllm_text()
    test_vllm_image()

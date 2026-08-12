import logging
from app.db.models import SessionLocal, WorkflowTemplate
from app.services.llm import classify_intent, generate_response
import json
import redis
import os

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

def process_persona_state_machine(phone_number: str, text: str, session: dict) -> dict:
    """
    State machine logic for processing Persona Agent steps from Database templates.
    """
    db = SessionLocal()
    try:
        current_agent = session.get("current_agent")
        current_step_id = session.get("current_step_id")
        
        # Initialization / Router
        # Initialization
        if not current_agent or session.get("state") == "INIT":
            session["state"] = "IN_PROGRESS"
            session["current_agent"] = "ROUTER"
            session["current_step_id"] = 1
            
            first_step = db.query(WorkflowTemplate).filter(
                WorkflowTemplate.persona_type == "ROUTER",
                WorkflowTemplate.step_number == 1
            ).first()
            
            if first_step:
                return {
                    "response": first_step.message_template,
                    "handover": False,
                    "updated_session": session
                }
            else:
                return {
                    "response": "A senior agent will contact you shortly.",
                    "handover": True,
                    "updated_session": session
                }

        # Continuing a workflow
        if current_step_id:
            current_step = db.query(WorkflowTemplate).filter(
                WorkflowTemplate.persona_type == current_agent,
                WorkflowTemplate.step_number == current_step_id
            ).first()
            
            if not current_step:
                logger.error(f"Step {current_step_id} not found for persona {current_agent}")
                return {"response": "A senior agent will contact you shortly.", "handover": True, "updated_session": session}
                
            # Ask LLM to extract the data based on current_step.expected_data_keys
            expected_keys = current_step.expected_data_keys
            instruction = current_step.ai_action_instruction
            
            # Simple wrapper to LLM to parse expected fields
            # Since generate_response already handles DB context, we will do a custom prompt here
            from app.services.llm import llm_client, LLM_MODEL_NAME
            
            system_prompt = f"You are an AI assistant. Extract the following information from the user's message based on the instruction: '{instruction}'. Expected JSON keys: {expected_keys}. Return valid JSON."
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ]
            
            try:
                response = llm_client.chat.completions.create(
                    model=LLM_MODEL_NAME,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
                extracted_data = json.loads(response.choices[0].message.content)
            except Exception as e:
                logger.error(f"Failed to extract JSON from LLM: {e}")
                extracted_data = {}
            
            # Save extracted data to session
            for key in expected_keys:
                if key in extracted_data:
                    session["collected_data"][key] = extracted_data[key]
                    
            # Check if all keys were collected
            missing_keys = [k for k in expected_keys if not session["collected_data"].get(k)]
            if missing_keys:
                # LLM didn't get all info, retry (or use LLM to re-ask)
                retry_count = session.get("retry_count", 0)
                if retry_count >= 2:
                    # Too many retries, handoff
                    return {"response": "A senior agent will contact you shortly.", "handover": True, "updated_session": session}
                session["retry_count"] = retry_count + 1
                return {"response": current_step.message_template, "handover": False, "updated_session": session}
            
            # If successful, move to next step
            session["retry_count"] = 0
            next_step_id = current_step.next_step
            
            # Transition from ROUTER to Persona
            if not next_step_id and current_agent == "ROUTER":
                category = session.get("collected_data", {}).get("customer_category", "").lower()
                persona_map = {
                    "personal buyer": "BUYER",
                    "seller": "SELLER",
                    "tenant": "TENANT",
                    "landlord": "LANDLORD"
                }
                mapped_intent = "GLOBAL"
                for key, val in persona_map.items():
                    if key in category:
                        mapped_intent = val
                        break
                        
                if mapped_intent != "GLOBAL":
                    current_agent = mapped_intent
                    session["current_agent"] = mapped_intent
                    first_persona_step = db.query(WorkflowTemplate).filter(
                        WorkflowTemplate.persona_type == mapped_intent
                    ).order_by(WorkflowTemplate.step_number.asc()).first()
                    
                    if first_persona_step:
                        next_step_id = first_persona_step.step_number
            
            if next_step_id:
                next_step = db.query(WorkflowTemplate).filter(
                    WorkflowTemplate.persona_type == current_agent,
                    WorkflowTemplate.step_number == next_step_id
                ).first()
                if next_step:
                    session["current_step_id"] = next_step_id
                    
                    # If this is the recommendation step, inject properties
                    response_msg = next_step.message_template
                    if next_step.step_name == "Recommend Listings":
                        # Perform DB Search based on collected data
                        from app.services.db_services import search_properties
                        criteria = {
                            "location": session["collected_data"].get("current_location"),
                            "property_type": session["collected_data"].get("use_type"),
                            "max_price": session["collected_data"].get("budget")
                        }
                        props = search_properties(criteria)
                        if props:
                            urls = [f"https://bentongland.com.my/property/{p['id']}" for p in props[:3]]
                            response_msg += "\n\n" + "\n".join(urls)
                        else:
                            response_msg += "\n\nCurrently, we have no direct matches, but our agent will reach out!"
                    
                    return {"response": response_msg, "handover": False, "updated_session": session}
            
            # Workflow completed or next step missing
            return {"response": "A senior agent will contact you shortly.", "handover": True, "updated_session": session}
            
    finally:
        db.close()

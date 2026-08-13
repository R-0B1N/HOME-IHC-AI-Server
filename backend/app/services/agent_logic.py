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


def process_persona_state_machine(phone_number: str, text: str, session: dict, conversation_history: str = "") -> dict:
    """
    State machine logic for processing Persona Agent steps from Database templates.
    
    Args:
        phone_number: The user's phone number
        text: The current message text
        session: The current session state dict
        conversation_history: Prior conversation messages for LLM context
    """
    db = SessionLocal()
    try:
        current_agent = session.get("current_agent")
        current_step_id = session.get("current_step_id")
        
        # Initialization / Router
        if not current_agent or session.get("state") == "INIT":
            session["state"] = "IN_PROGRESS"
            session["current_agent"] = "ROUTER"
            session["current_step_id"] = 1
            session["retry_count"] = 0  # Always reset on init
            
            first_step = db.query(WorkflowTemplate).filter(
                WorkflowTemplate.persona_type == "ROUTER",
                WorkflowTemplate.step_number == 1
            ).first()
            
            if first_step:
                # If step has no expected data keys (greeting-only), auto-advance
                expected_keys = first_step.expected_data_keys or []
                if not expected_keys or expected_keys == [""]:
                    # Pure greeting step — send template and advance to next
                    session["current_step_id"] = first_step.next_step or 2
                    return {
                        "response": first_step.message_template,
                        "handover": False,
                        "updated_session": session
                    }
                else:
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
                
            # Check expected data keys
            expected_keys = current_step.expected_data_keys or []
            # Filter out empty strings
            expected_keys = [k for k in expected_keys if k and k.strip()]
            
            if not expected_keys:
                # No data needed for this step — just send template and advance
                next_step_id = current_step.next_step
                session["retry_count"] = 0
                
                if next_step_id:
                    session["current_step_id"] = next_step_id
                    return {
                        "response": current_step.message_template,
                        "handover": False,
                        "updated_session": session
                    }
                else:
                    # No next step and no expected keys — workflow complete
                    return {
                        "response": current_step.message_template or "A senior agent will contact you shortly.",
                        "handover": True,
                        "updated_session": session
                    }
            
            # Ask LLM to extract the data based on current_step.expected_data_keys
            instruction = current_step.ai_action_instruction
            
            from app.services.llm import llm_client, LLM_MODEL_NAME
            
            # Build system prompt with conversation history for context
            history_block = ""
            if conversation_history:
                history_block = f"\n\nConversation history so far:\n{conversation_history}\n"
            
            system_prompt = f"""You are a Real Estate AI assistant for ERA Realtor, acting as Irene Leong, a Senior Property Agent.
You are currently in the {current_agent} workflow.
Instruction: '{instruction}'
Expected JSON keys: {expected_keys}
{history_block}
1. Extract the expected keys from the user's message. Use null if not provided or unclear.
2. If any expected key is missing (null), write a friendly conversational response asking the user for the missing information. Keep it short, natural, and ask only ONE question at a time.
3. Be flexible in interpretation. For example:
   - "im looking for a property" → customer_category could be "personal buyer"
   - "i want to buy land" → customer_category = "personal buyer"
   - "i want to sell" → customer_category = "seller"
   - "im an agent" or "im a broker" → customer_category = "agent"
   - Location mentions like "bentong", "raub", "mentakab" → location/buyer_location = that value
   - Property type mentions like "agricultural", "commercial", "residential" → property_type/buyer_property_type = that value
   - Budget mentions like "500k", "RM 1 million", "below 200000" → budget/buyer_budget = that value
   - "personal" or "my name" → purchase_entity = "personal"
   - "company" or "sdn bhd" → purchase_entity = "company"
   - If user provides their name naturally (e.g. "My name is Ahmad") → agent_name = "Ahmad"
   - Agency mentions like "IQI", "Hartamas", "ERA" → agency_name = that value

Return valid JSON with two fields:
- "extracted_data": {{ key: value }}
- "follow_up_message": string (your friendly question if keys are missing, otherwise null)"""

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
                result = json.loads(response.choices[0].message.content)
                extracted_data = result.get("extracted_data", {})
                follow_up_message = result.get("follow_up_message")
            except Exception as e:
                logger.error(f"Failed to extract JSON from LLM: {e}")
                extracted_data = {}
                follow_up_message = None
            
            # Save extracted data to session
            for key in expected_keys:
                val = extracted_data.get(key)
                if val:
                    session["collected_data"][key] = val
                    
            # Check if all keys were collected
            missing_keys = [k for k in expected_keys if not session["collected_data"].get(k)]
            if missing_keys:
                retry_count = session.get("retry_count", 0)
                if retry_count >= 3:
                    # Too many retries — handover to human
                    session["retry_count"] = 0  # Reset for future use
                    return {"response": "A senior agent will contact you shortly.", "handover": True, "updated_session": session}
                session["retry_count"] = retry_count + 1
                
                reply_text = follow_up_message if follow_up_message else "Could you please provide more details so I can assist you better?"
                return {"response": reply_text, "handover": False, "updated_session": session}
            
            # SUCCESS — all keys collected. Reset retry_count and advance.
            session["retry_count"] = 0
            next_step_id = current_step.next_step
            
            # Transition from ROUTER to Persona
            if not next_step_id and current_agent == "ROUTER":
                category = session.get("collected_data", {}).get("customer_category", "").lower()
                persona_map = {
                    "personal buyer": "BUYER",
                    "buyer": "BUYER",
                    "seller": "SELLER",
                    "owner": "SELLER",
                    "tenant": "TENANT",
                    "renter": "TENANT",
                    "landlord": "LANDLORD",
                    "agent": "AGENT",
                    "broker": "AGENT",
                    "property agent": "AGENT",
                }
                mapped_intent = "GLOBAL"
                for key, val in persona_map.items():
                    if key in category or category in key or val.lower() in category:
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
                        from app.services.db_services import search_properties
                        collected = session.get("collected_data", {})
                        # Support both BUYER keys and AGENT/BROKER keys
                        criteria = {
                            "location": (
                                collected.get("buyer_location") 
                                or collected.get("current_location") 
                                or collected.get("location")
                            ),
                            "property_type": (
                                collected.get("buyer_property_type") 
                                or collected.get("use_type") 
                                or collected.get("property_type")
                            ),
                            "max_price": (
                                collected.get("buyer_budget") 
                                or collected.get("budget")
                            )
                        }
                        props = search_properties(criteria)
                        if props:
                            urls = [f"https://bentongland.com.my/property/{p['id']}" for p in props[:3]]
                            response_msg += "\n\n" + "\n".join(urls)
                        else:
                            response_msg += "\n\nCurrently, we have no direct matches, but our agent will reach out!"
                    
                    # Check if this next step has no expected keys — auto-advance
                    next_expected = next_step.expected_data_keys or []
                    next_expected = [k for k in next_expected if k and k.strip()]
                    if not next_expected and next_step.next_step:
                        # Empty-key step with a next step — send message and advance
                        session["current_step_id"] = next_step.next_step
                    elif not next_expected and not next_step.next_step:
                        # Empty-key step with NO next step — this is the final step, trigger handover
                        return {"response": response_msg, "handover": True, "updated_session": session}
                    
                    return {"response": response_msg, "handover": False, "updated_session": session}
            
            # Workflow completed or next step missing
            return {"response": "A senior agent will contact you shortly.", "handover": True, "updated_session": session}
            
    finally:
        db.close()

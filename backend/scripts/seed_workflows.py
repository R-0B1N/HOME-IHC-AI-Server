import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import engine
from sqlalchemy.orm import sessionmaker
from app.db.models import WorkflowTemplate, Base

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_workflows():
    print("Creating tables if they don't exist...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    print("Clearing existing templates...")
    db.query(WorkflowTemplate).delete()
    db.commit()
    
    templates = [
        # ==========================================
        # ROUTER / GREETING (Runs before Persona)
        # ==========================================
        {
            "persona_type": "ROUTER",
            "step_number": 1,
            "step_name": "Greeting & Intro",
            "ai_action_instruction": "Greet the customer, introduce Irene Leong, and send the digital name card. Collect basic location and property type preferences.",
            "message_template": "Good day! 😊\nI'm Irene Leong, a Senior Property Agent from ERA Realtor \n\nHere is my digital name card:\nhttps://my.mecard.my/1733211127 \n\nThank you for contacting us.\n\nTo help us assist you more efficiently, could you kindly provide the following information?\n\n📸 Property Link / Screenshot: (If applicable)\n📍 Preferred Location:\n\t•\tBentong\n\t•\tTemerloh / Mentakab\n\t•\tRaub\n\n🏠 Property Type:\n\t•\tResidential Property\n\t•\tCommercial Property\n\t•\tIndustrial Property\n\t•\tAgricultural Land\n\nPlease send us the above information, and we'll recommend the most suitable properties for you as soon as possible. 😊",
            "expected_data_keys": ["location", "property_type"],
            "next_step": 2
        },
        {
            "persona_type": "ROUTER",
            "step_number": 2,
            "step_name": "Identify Customer Category",
            "ai_action_instruction": "Identify if the customer is a Personal Buyer, Agent/Broker, or Seller. This step relies on the Router Agent LLM classification.",
            "message_template": "Hi! I'm Ms Irene. 😊\nI see you're interested in our BentongLand listings.\nI have the photos, videos, topo plans, and location information ready.\nTo send you the most relevant information, may I know which category you belong to?\n🙋 Personal Buyer\n🤝 Property Agent / Broker\n🏡 Seller",
            "expected_data_keys": ["customer_category"],
            "next_step": None # Branching happens here
        },
        
        # ==========================================
        # BUYER PERSONA
        # ==========================================
        {
            "persona_type": "BUYER",
            "step_number": 31,
            "step_name": "Ask Name",
            "ai_action_instruction": "Ask for the buyer's name. Ask ONLY this question.",
            "message_template": "Hi! 😊 May I know your name?",
            "expected_data_keys": ["name"],
            "next_step": 32
        },
        {
            "persona_type": "BUYER",
            "step_number": 32,
            "step_name": "Ask Location",
            "ai_action_instruction": "Ask where the buyer is contacting from. Ask ONLY this question.",
            "message_template": "May I know where are you contacting us from?",
            "expected_data_keys": ["current_location"],
            "next_step": 33
        },
        {
            "persona_type": "BUYER",
            "step_number": 33,
            "step_name": "Ask Name Card",
            "ai_action_instruction": "Ask for the buyer's name card if available.",
            "message_template": "May I have your name card, if available? 😊",
            "expected_data_keys": ["has_name_card"],
            "next_step": 34
        },
        {
            "persona_type": "BUYER",
            "step_number": 34,
            "step_name": "Ask Purpose",
            "ai_action_instruction": "Ask for the purpose of purchasing.",
            "message_template": "May I know what is your purpose for purchasing the property?",
            "expected_data_keys": ["purpose"],
            "next_step": 35
        },
        {
            "persona_type": "BUYER",
            "step_number": 35,
            "step_name": "Ask Budget",
            "ai_action_instruction": "Ask for the budget.",
            "message_template": "May I know your budget for this purchase? 💰",
            "expected_data_keys": ["budget"],
            "next_step": 36
        },
        {
            "persona_type": "BUYER",
            "step_number": 36,
            "step_name": "Ask Entity",
            "ai_action_instruction": "Ask if it's for personal or investment use.",
            "message_template": "Will this property be for:\n1️⃣ Personal Use\n2️⃣ Investment",
            "expected_data_keys": ["use_type"],
            "next_step": 40
        },
        {
            "persona_type": "BUYER",
            "step_number": 40,
            "step_name": "Personal or Company",
            "ai_action_instruction": "Confirm if purchasing under personal or company name.",
            "message_template": "Noted with thanks! 👍\nTo better assist you, may I know if you plan to purchase this property under a:\n🧑‍💼 Personal Name\n🏢 Company Name",
            "expected_data_keys": ["purchase_entity"],
            "next_step": 50
        },
        {
            "persona_type": "BUYER",
            "step_number": 50,
            "step_name": "Recommend Listings",
            "ai_action_instruction": "Based on collected data, the backend will append listing links here.",
            "message_template": "Thank you for the information! Based on your requirements, here are some suitable properties for your consideration:",
            "expected_data_keys": [],
            "next_step": 60
        },
        
        # ==========================================
        # SELLER PERSONA
        # ==========================================
        {
            "persona_type": "SELLER",
            "step_number": 10,
            "step_name": "Seller Greeting",
            "ai_action_instruction": "Greet the Seller/Owner and explain the process.",
            "message_template": "Good day! 😊\nThank you for contacting ERA Realtor\nI'm Irene Leong, a Senior Property Agent. I'll be happy to assist you with selling your land or property.\nTo better understand your property and recommend the most suitable marketing strategy, may I ask you a few questions?",
            "expected_data_keys": [],
            "next_step": 11
        },
        {
            "persona_type": "SELLER",
            "step_number": 11,
            "step_name": "Ask Name",
            "ai_action_instruction": "Ask the seller's full name.",
            "message_template": "May I have your full name?",
            "expected_data_keys": ["name"],
            "next_step": 12
        },
        {
            "persona_type": "SELLER",
            "step_number": 12,
            "step_name": "Verify Ownership",
            "ai_action_instruction": "Ask if they are the owner or representing the owner.",
            "message_template": "Are you the property owner or representing the owner?",
            "expected_data_keys": ["is_owner"],
            "next_step": 13
        },
        {
            "persona_type": "SELLER",
            "step_number": 13,
            "step_name": "Property Type",
            "ai_action_instruction": "Ask what type of property they want to sell.",
            "message_template": "May I know what type of property you would like to sell?\n\n🌱 Agricultural Land \n🏢 Commercial Property \n🏭 Industrial \n🏠 Residential",
            "expected_data_keys": ["property_type"],
            "next_step": 14
        },
        
        # ==========================================
        # GLOBAL FALLBACK
        # ==========================================
        {
            "persona_type": "GLOBAL",
            "step_number": 999,
            "step_name": "Handoff to Human",
            "ai_action_instruction": "Trigger this when AI cannot answer or when user wants to talk to a human.",
            "message_template": "A senior agent will contact you shortly.",
            "expected_data_keys": [],
            "next_step": None
        }
    ]
    
    for t in templates:
        template_obj = WorkflowTemplate(**t)
        db.add(template_obj)
        
    db.commit()
    print(f"Successfully seeded {len(templates)} workflow templates into the database.")
    
if __name__ == "__main__":
    seed_workflows()

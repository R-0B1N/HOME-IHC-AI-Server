import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    from sqlalchemy.orm import sessionmaker
    from app.db.models import WorkflowTemplate, Base, engine
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except ImportError:
    WorkflowTemplate = None
    Base = None
    engine = None
    SessionLocal = None

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
            "message_template": "Good day! 😊\nI'm Irene Leong, a Senior Property Agent from Home IHC.\n\nHere is my digital name card:\nhttps://my.mecard.my/1733211127\n\nThank you for contacting us.\n\nTo help us assist you more efficiently, could you kindly provide the following information?\n\n📸 Property Link / Screenshot: (If applicable)\n📍 Preferred Location:\n\t•\tBentong\n\t•\tTemerloh / Mentakab\n\t•\tRaub\n\n🏠 Property Type:\n\t•\tResidential Property\n\t•\tCommercial Property\n\t•\tIndustrial Property\n\t•\tAgricultural Land\n\nPlease send us the above information, and we'll recommend the most suitable properties for you as soon as possible. 😊",
            "expected_data_keys": ["location", "property_type"],
            "next_step": 2
        },
        {
            "persona_type": "ROUTER",
            "step_number": 2,
            "step_name": "Identify Customer Category",
            "ai_action_instruction": "Identify if the customer is a Personal Buyer, Property Agent / Broker, or Seller. This step determines the persona workflow branch.",
            "message_template": "Hi! I'm Ms Irene. 😊\nI see you're interested in our BentongLand listings.\nI have the photos, videos, topo plans, and location information ready.\nTo send you the most relevant information, may I know which category you belong to?\n🙋 Personal Buyer\n🤝 Property Agent / Broker\n🏡 Seller",
            "expected_data_keys": ["customer_category"],
            "next_step": None
        },
        
        # ==========================================
        # BUYER PERSONA (Steps 1 to 12 & Step 60)
        # ==========================================
        {
            "persona_type": "BUYER",
            "step_number": 31,
            "step_name": "Step 3a: Ask Name",
            "ai_action_instruction": "Ask for the buyer's name. Ask ONLY this question.",
            "message_template": "Hi! 😊 May I know your name?",
            "expected_data_keys": ["name"],
            "next_step": 32
        },
        {
            "persona_type": "BUYER",
            "step_number": 32,
            "step_name": "Step 3b: Ask Contact Location",
            "ai_action_instruction": "Ask where the buyer is contacting us from. Ask ONLY this question.",
            "message_template": "May I know where are you contacting us from?",
            "expected_data_keys": ["current_location"],
            "next_step": 33
        },
        {
            "persona_type": "BUYER",
            "step_number": 33,
            "step_name": "Step 3c: Ask Name Card",
            "ai_action_instruction": "Ask for the buyer's name card if available.",
            "message_template": "May I have your name card, if available? 😊",
            "expected_data_keys": ["has_name_card"],
            "next_step": 34
        },
        {
            "persona_type": "BUYER",
            "step_number": 34,
            "step_name": "Step 3d: Ask Purpose",
            "ai_action_instruction": "Ask for the purpose of purchasing the property.",
            "message_template": "May I know what is your purpose for purchasing the property?",
            "expected_data_keys": ["purpose"],
            "next_step": 35
        },
        {
            "persona_type": "BUYER",
            "step_number": 35,
            "step_name": "Step 3e: Ask Budget",
            "ai_action_instruction": "Ask for the purchase budget.",
            "message_template": "May I know your budget for this purchase? 💰",
            "expected_data_keys": ["budget"],
            "next_step": 36
        },
        {
            "persona_type": "BUYER",
            "step_number": 36,
            "step_name": "Step 3f: Personal or Investment",
            "ai_action_instruction": "Ask if the property is for personal use or investment.",
            "message_template": "Will this property be for:\n1️⃣ Personal Use\n2️⃣ Investment",
            "expected_data_keys": ["use_type"],
            "next_step": 40
        },
        {
            "persona_type": "BUYER",
            "step_number": 40,
            "step_name": "Step 4: Purchase Entity",
            "ai_action_instruction": "Confirm if purchasing under a Personal Name or Company Name for transaction documentation.",
            "message_template": "Thank you for the information. 😊\nMay I also confirm whether you will be purchasing the property under:\n✅ Personal Name or 🏢 Company Name?\nThis information helps us prepare the appropriate documentation for the property transaction.",
            "expected_data_keys": ["purchase_entity"],
            "next_step": 5
        },
        {
            "persona_type": "BUYER",
            "step_number": 5,
            "step_name": "Step 5: Identify Listing & Materials",
            "ai_action_instruction": "Ask the buyer to provide the property link or screenshot, and outline available materials (description, photos, videos, topo plan, location map).",
            "message_template": "May I know which listing you are referring to?\nYou may:\n✅ Send me the property link\nor\n✅ Send me a screenshot of the listing.\n\nOnce received, I'll send you the available property information, including:\n• Property Description\n• Photos\n• Videos\n• Topo Plan\n• Location Map\n\nI'll also be happy to answer any questions you may have about the property. 😊",
            "expected_data_keys": ["property_link_or_screenshot"],
            "next_step": 50
        },
        {
            "persona_type": "BUYER",
            "step_number": 6,
            "step_name": "Step 6: Search & Category Navigation Guide",
            "ai_action_instruction": "Guide the buyer to search properties on BentongLand website or Facebook page if they cannot find a specific listing.",
            "message_template": "No worries! 😊\nYou may search for the property through our website and social channels:\n🌐 BentongLand Website: https://bentongland.com.my\n📘 Facebook: https://www.facebook.com/PahangAgriLand\n\nBrowse by Category:\n🌱 Agricultural Land: https://bentongland.com.my/property-category/agricultural-land/\n🏭 Industrial Property: https://bentongland.com.my/property-category/industrial/\n🏢 Commercial Property: https://bentongland.com.my/property-category/commercial/\n🏠 Residential Property: https://bentongland.com.my/property-category/residential/",
            "expected_data_keys": [],
            "next_step": 50
        },
        {
            "persona_type": "BUYER",
            "step_number": 50,
            "step_name": "Step 7: Recommend Listings & Follow-Up",
            "ai_action_instruction": "Present shortlisted matching properties with descriptions, photos, YouTube links, Google Maps, and prices. Follow up on interest.",
            "message_template": "Thank you for your requirements! Based on what you're looking for, here are the most suitable properties:\n\n[Recommended Properties]\n\n• Does this property match what you are looking for?\n• Would you like me to share more photos or details?\n• Would you be interested in arranging a site viewing? 😊",
            "expected_data_keys": [],
            "next_step": 60
        },
        {
            "persona_type": "BUYER",
            "step_number": 60,
            "step_name": "Step 8: Viewing Acknowledgement & Form",
            "ai_action_instruction": "Require Customer Property Acknowledgement & Viewing Form before arranging site viewing. Explain 3 purposes if customer asks.",
            "message_template": "Before arranging the site viewing, we kindly require the customer to complete and sign the:\n✅ Customer Property Acknowledgement & Viewing Form\n\nThe form serves 3 essential purposes:\n1️⃣ Professional Service & Full Disclosure 💼 (Allows us to release full copies of land titles, topo plans, and site details)\n2️⃣ Protecting the Introduction 🛡️ (Ensures transparent ethical process and prevents direct bypassing)\n3️⃣ Accurate Owner Reporting & Transparency 📋 (Provides the owner with legitimate report of interest)\n\nOnce completed, we will proceed with scheduling your viewing session! 😊",
            "expected_data_keys": ["viewing_form_status"],
            "next_step": 70
        },
        {
            "persona_type": "BUYER",
            "step_number": 70,
            "step_name": "Step 9: After Viewing Follow-up & Confirmation Videos",
            "ai_action_instruction": "Follow up after site viewing. If interested, collect IC/Passport, SSM, and confirm financing. Share confirmation order video guides.",
            "message_template": "Hi! 😊 Thank you for taking the time to view the property. May I know your thoughts on it?\n\nIf you're interested in proceeding with the purchase:\n📄 IC Full Set / Passport OR 🏢 Company Name Card\n📑 Company Documents / SSM Front Page (for company purchase)\n💰 Preferred Purchase Price / Offer Price\n🏦 Financing Method: Cash or Bank Loan\n\n▶️ Property Confirmation Order Process Guides:\n• English YouTube: https://youtube.com/shorts/xJ5tz2fogMA?si=DT_GdJgreC49YDkX\n• Chinese Facebook: https://www.facebook.com/reel/1383747846900139",
            "expected_data_keys": ["post_viewing_interest", "financing_method"],
            "next_step": 80
        },
        {
            "persona_type": "BUYER",
            "step_number": 80,
            "step_name": "Step 10: Official Social Channels",
            "ai_action_instruction": "Invite customer to follow Home IHC / BentongLand official channels for updates.",
            "message_template": "If you find our information helpful, we would really appreciate your support by following our official channels for the latest property and land updates: 😊\n\n📘 Facebook: https://facebook.com/PahangAgriLand\n▶️ YouTube: https://www.youtube.com/@BentongLandMY\n\nThank you very much for your support! ✨",
            "expected_data_keys": [],
            "next_step": 90
        },
        {
            "persona_type": "BUYER",
            "step_number": 90,
            "step_name": "Step 11: Internal AI CRM Processing",
            "ai_action_instruction": "Save customer info to CRM, classify lead status (Hot/Warm/Cooling), and send qualified summary to Irene Leong (011-6514 4931). Do not create Google Calendar events.",
            "message_template": "[Internal Action] Lead profiled, categorized, and forwarded to Irene Leong (011-6514 4931) for follow-up.",
            "expected_data_keys": ["crm_sync_status"],
            "next_step": 100
        },
        {
            "persona_type": "BUYER",
            "step_number": 100,
            "step_name": "Step 12: Buyer Database & Google Review",
            "ai_action_instruction": "Record in Buyer Database.xlsx and dispatch location-based Google Review links upon successful transaction/viewing.",
            "message_template": "Thank you for choosing Home IHC. 😊\nIf you're satisfied with our service, we would greatly appreciate it if you could leave us a Google Review:\n\n🔗 Home IHC Bentong (HQ): https://g.page/r/CSRasXyQXRrtEAE/review\n🔗 Home IHC Temerloh (Branch): https://g.page/r/Cce51gfEhNx1EBM/review\n\nThank you for your support! 🙏",
            "expected_data_keys": ["review_request_sent"],
            "next_step": None
        },
        
        # ==========================================
        # SELLER PERSONA (Steps 10 to 20)
        # ==========================================
        {
            "persona_type": "SELLER",
            "step_number": 10,
            "step_name": "Seller Greeting",
            "ai_action_instruction": "Greet the Seller/Owner and introduce the property assessment process.",
            "message_template": "Good day! 😊\nThank you for contacting Home IHC.\nI'm Irene Leong, a Senior Property Agent. I'll be happy to assist you with selling your land or property.\nTo better understand your property and recommend the most suitable marketing strategy, may I ask you a few questions?",
            "expected_data_keys": [],
            "next_step": 11
        },
        {
            "persona_type": "SELLER",
            "step_number": 11,
            "step_name": "Ask Name & Background",
            "ai_action_instruction": "Ask the seller's full name, expected selling price, and preferred timeline.",
            "message_template": "✓ May I have your full name?\n✓ Which land or property would you like to sell?\n✓ What is your expected selling price?\n✓ What is your preferred selling timeline?",
            "expected_data_keys": ["name", "property_description", "asking_price", "timeline"],
            "next_step": 12
        },
        {
            "persona_type": "SELLER",
            "step_number": 12,
            "step_name": "Verify Ownership",
            "ai_action_instruction": "Verify if the contact is the registered owner or representing the owner (agent/broker/family).",
            "message_template": "Are you the property owner or representing the owner?\n\n1️⃣ Property Owner\n2️⃣ Authorised Representative / Property Agent\n3️⃣ Co-owner / Family Member",
            "expected_data_keys": ["is_owner"],
            "next_step": 13
        },
        {
            "persona_type": "SELLER",
            "step_number": 13,
            "step_name": "Identify Property Type",
            "ai_action_instruction": "Identify what type of property the owner wishes to sell.",
            "message_template": "May I know what type of property you would like to sell?\n\n🌱 Agricultural Land (Durian / Oil Palm / Rubber / Vacant)\n🏢 Commercial Property (Land / Shoplot)\n🏭 Industrial (Land / Factory / Warehouse)\n🏠 Residential (House / Vacant Lot / Condo)",
            "expected_data_keys": ["property_type"],
            "next_step": 14
        },
        {
            "persona_type": "SELLER",
            "step_number": 14,
            "step_name": "Category Document & Spec Collection",
            "ai_action_instruction": "Collect category-specific specifications: Durian Land (tree types, count, age, fruiting, water/electricity), Palm/Rubber, Commercial/Industrial (CCC, tenancy). State 3% fee + 8% ST.",
            "message_template": "Dear Owner,\nThank you for choosing Home IHC. 😄\nTo proceed with evaluating and marketing your property, kindly share:\n\n☀️ Full copy of property title (All pages)\n☀️ Land / Built-up size 📏\n☀️ Location map / address 📍\n☀️ Photos & videos 📸\n☀️ Tree details (for Agricultural) or CCC / Layout (for Buildings)\n☀️ Water, electricity, and road access conditions\n\nProfessional Fee (Sale): 3% of agreed selling price, subject to 8% Service Tax.\nContact: 📲 Irene: 011-6514 4931 | 📲 Voon: 011-6304 4931",
            "expected_data_keys": ["property_documents", "property_specs"],
            "next_step": 15
        },
        {
            "persona_type": "SELLER",
            "step_number": 15,
            "step_name": "Representative Authorization Letter",
            "ai_action_instruction": "If representing the owner, request authorization letter for property sale verification.",
            "message_template": "May I have a copy of the owner's authorization letter of sale for verification? Thank you!",
            "expected_data_keys": ["authorization_letter"],
            "next_step": 16
        },
        {
            "persona_type": "SELLER",
            "step_number": 16,
            "step_name": "CCC Explanation Q&A",
            "ai_action_instruction": "Explain Certificate of Completion and Compliance (CCC) if owner asks about it.",
            "message_template": "CCC stands for Certificate of Completion and Compliance. It officially confirms a building is built according to approved local council plans and is safe for occupation. Having the CCC helps us verify documentation for buyers and banks during the sales process.",
            "expected_data_keys": [],
            "next_step": 17
        },
        {
            "persona_type": "SELLER",
            "step_number": 17,
            "step_name": "Incomplete Documents Guidance",
            "ai_action_instruction": "Reassure the seller if documents are incomplete and guide them step by step.",
            "message_template": "No worries if you do not have all the documents ready right now! 😊 You may send us whatever information or photos you currently have first. We will review them and guide you through the remaining requirements step by step.",
            "expected_data_keys": [],
            "next_step": 18
        },
        {
            "persona_type": "SELLER",
            "step_number": 18,
            "step_name": "Selling Process & Social Channels",
            "ai_action_instruction": "Explain the selling process and share official media channels.",
            "message_template": "We'll guide you through the entire process: from listing preparation and premium digital marketing to buyer negotiation and closing! 🤝\n\nCheck out our channels:\n📘 Facebook: https://facebook.com/PahangAgriLand\n🔴 YouTube: https://www.youtube.com/@BentongLandMY",
            "expected_data_keys": [],
            "next_step": 19
        },
        {
            "persona_type": "SELLER",
            "step_number": 19,
            "step_name": "Professional Fee Breakdown",
            "ai_action_instruction": "Explain 3% standard professional fee breakdown (marketing, buyer matching, transaction support) with 8% ST calculation.",
            "message_template": "Professional Fee: 3% 💼\nOur professional fee covers everything to sell your property smoothly:\n✅ Full Digital Marketing & Exposure\n✅ Qualified Buyer Matching & Site Viewings\n✅ Transaction Support (Lawyers, Banks, Valuation)\n\nCalculation Example (based on RM 100,000):\n• 3% Fee: RM 3,000 + 8% SST (RM 240) = RM 3,240.00\n\n📲 Irene: 011-6514 4931 | 📲 Voon: 011-6304 4931",
            "expected_data_keys": [],
            "next_step": 20
        },
        {
            "persona_type": "SELLER",
            "step_number": 20,
            "step_name": "Seller Database & Google Review",
            "ai_action_instruction": "Record in Seller Database.xlsx and dispatch Google Review links upon successful onboarding/sale.",
            "message_template": "Thank you for appointing Home IHC! 😊\nIf you're happy with our service, we would appreciate your Google Review:\n🔗 Home IHC Bentong (HQ): https://g.page/r/CSRasXyQXRrtEAE/review\n🔗 Home IHC Temerloh (Branch): https://g.page/r/Cce51gfEhNx1EBM/review\n\nThank you for your support! 🙏",
            "expected_data_keys": ["review_request_sent"],
            "next_step": None
        },
        
        # ==========================================
        # TENANT PERSONA (Steps 1 to 8 & Step 60)
        # ==========================================
        {
            "persona_type": "TENANT",
            "step_number": 10,
            "step_name": "Tenant Greeting",
            "ai_action_instruction": "Greet the prospective tenant and send Irene Leong digital namecard.",
            "message_template": "Good day! 😊\nI'm Irene Leong, a Senior Property Agent from Home IHC.\n\nHere is my digital name card:\n🔗 https://my.mecard.my/1733211127\n\nTo help us recommend the best rental options, please let us know your preferred location and property type! 😊",
            "expected_data_keys": [],
            "next_step": 31
        },
        {
            "persona_type": "TENANT",
            "step_number": 31,
            "step_name": "Ask Name",
            "ai_action_instruction": "Ask for the tenant's name. Ask ONLY this question.",
            "message_template": "Hi! 😊 May I know your name?",
            "expected_data_keys": ["name"],
            "next_step": 32
        },
        {
            "persona_type": "TENANT",
            "step_number": 32,
            "step_name": "Ask Rental Location",
            "ai_action_instruction": "Ask where the tenant is looking to rent.",
            "message_template": "May I know where you are looking to rent?\n📍 Bentong\n📍 Temerloh / Mentakab\n📍 Raub",
            "expected_data_keys": ["current_location"],
            "next_step": 34
        },
        {
            "persona_type": "TENANT",
            "step_number": 34,
            "step_name": "Ask Purpose & Duration",
            "ai_action_instruction": "Ask for the purpose of renting and intended move-in timeline.",
            "message_template": "May I know what is your intended purpose for renting and preferred move-in date?",
            "expected_data_keys": ["purpose", "move_in_date"],
            "next_step": 35
        },
        {
            "persona_type": "TENANT",
            "step_number": 35,
            "step_name": "Ask Rental Budget",
            "ai_action_instruction": "Ask for monthly rental budget.",
            "message_template": "May I know your monthly budget for this rental? 💰",
            "expected_data_keys": ["budget"],
            "next_step": 36
        },
        {
            "persona_type": "TENANT",
            "step_number": 36,
            "step_name": "Personal or Business",
            "ai_action_instruction": "Confirm if renting for personal stay or commercial/industrial business.",
            "message_template": "Will this rental be for:\n1️⃣ Personal Use\n2️⃣ Business Use (Company Tenancy)",
            "expected_data_keys": ["use_type"],
            "next_step": 40
        },
        {
            "persona_type": "TENANT",
            "step_number": 40,
            "step_name": "Detailed Category Requirements",
            "ai_action_instruction": "Collect detailed requirements based on property type (Residential: furnishing, pax; Commercial/Industrial: nature of business, utilities, built-up; Land: power/water).",
            "message_template": "To help us match the right property with the landlord, please share:\n• Property Type: Residential / Commercial / Industrial / Lease Land\n• Furnishing / Size requirement 📐\n• Required utilities (e.g. 3-Phase Power / TNB / Water) ⚡💧",
            "expected_data_keys": ["detailed_specs"],
            "next_step": 50
        },
        {
            "persona_type": "TENANT",
            "step_number": 50,
            "step_name": "Recommend Rental Listings",
            "ai_action_instruction": "Present suitable rental listings with photos, monthly rent, and details.",
            "message_template": "Based on your requirements, here are our shortlisted rental properties for you:\n\n[Recommended Rental Listings]\n\nPlease let us know which property you are interested in, and we'll be happy to arrange a viewing! 🤝",
            "expected_data_keys": [],
            "next_step": 60
        },
        {
            "persona_type": "TENANT",
            "step_number": 60,
            "step_name": "Arrange Viewing",
            "ai_action_instruction": "Coordinate viewing with tenant: date, time, number of visitors, contact person. Coordinate with landlord.",
            "message_template": "Great! 😊 To arrange your property viewing, kindly share:\n📅 Preferred Viewing Date:\n🕒 Preferred Viewing Time:\n👥 Number of Visitors:\n📱 Contact Person:\n\nWe will coordinate with the landlord and confirm the appointment shortly! 🤝",
            "expected_data_keys": ["viewing_date", "viewing_time", "visitors_count"],
            "next_step": 70
        },
        {
            "persona_type": "TENANT",
            "step_number": 70,
            "step_name": "After Viewing Follow-up",
            "ai_action_instruction": "Follow up on viewing interest. If interested, request IC/Passport, SSM front page, and confirm move-in date.",
            "message_template": "Hi! 😊 Thank you for viewing the property. May I know your thoughts?\n\nIf you'd like to proceed with the tenancy:\n📄 IC Full Set / Passport\n🏢 Company Name Card & SSM Front Page (for company)\n📅 Intended Move-in Date",
            "expected_data_keys": ["post_viewing_interest"],
            "next_step": 80
        },
        {
            "persona_type": "TENANT",
            "step_number": 80,
            "step_name": "Tenant Database & Google Review",
            "ai_action_instruction": "Record in Tenant Database.xlsx and send Google Review links upon successful booking.",
            "message_template": "Thank you for choosing Home IHC! 😊\nWe would greatly appreciate a quick Google Review of your experience:\n🔗 Home IHC Bentong (HQ): https://g.page/r/CSRasXyQXRrtEAE/review\n🔗 Home IHC Temerloh (Branch): https://g.page/r/Cce51gfEhNx1EBM/review\n\nThank you for your support! 🙏",
            "expected_data_keys": ["review_request_sent"],
            "next_step": None
        },
        
        # ==========================================
        # LANDLORD PERSONA (Steps 10 to 15)
        # ==========================================
        {
            "persona_type": "LANDLORD",
            "step_number": 10,
            "step_name": "Landlord Greeting",
            "ai_action_instruction": "Greet the Landlord and explain the leasing marketing process.",
            "message_template": "Good day! 😊\nThank you for contacting Home IHC.\nI'm Irene Leong, a Senior Property Agent. I'll be happy to assist you with renting out your land or property.\nTo better understand your property, may I ask you a few questions?",
            "expected_data_keys": [],
            "next_step": 11
        },
        {
            "persona_type": "LANDLORD",
            "step_number": 11,
            "step_name": "Ask Name & Contact",
            "ai_action_instruction": "Ask the landlord's full name and contact number.",
            "message_template": "May I have your full name and preferred contact number?",
            "expected_data_keys": ["name", "phone"],
            "next_step": 12
        },
        {
            "persona_type": "LANDLORD",
            "step_number": 12,
            "step_name": "Verify Ownership",
            "ai_action_instruction": "Verify if the landlord is the registered owner or representative.",
            "message_template": "Are you the registered owner of the property?\n• Yes\n• No - Property Agent / Representative\n• Co-owner / Family Member",
            "expected_data_keys": ["is_owner"],
            "next_step": 13
        },
        {
            "persona_type": "LANDLORD",
            "step_number": 13,
            "step_name": "Property Type",
            "ai_action_instruction": "Ask what type of property they want to rent out.",
            "message_template": "May I know what type of property you would like to rent out?\n\n🌱 Lease Land / Agricultural\n🏢 Commercial Property (Shoplot / Office)\n🏭 Industrial (Factory / Warehouse)\n🏠 Residential (House / Condo)",
            "expected_data_keys": ["property_type"],
            "next_step": 14
        },
        {
            "persona_type": "LANDLORD",
            "step_number": 14,
            "step_name": "Collect Property & Utility Specs",
            "ai_action_instruction": "Collect rental specs: address, title copy, built-up/land size, expected monthly rental, available handover date, individual TNB/water meters, furnishing.",
            "message_template": "To prepare your property for rental marketing, kindly provide:\n📄 Full copy of title (if available)\n📍 Full property address & Google Maps pin\n📏 Land / Built-up size\n🛋️ Furnishing status (Bare / Partial / Fully Furnished)\n💰 Expected monthly rental\n📅 Available handover date\n⚡ TNB / Water meters individual status",
            "expected_data_keys": ["property_specs", "rental_price", "handover_date"],
            "next_step": 15
        },
        {
            "persona_type": "LANDLORD",
            "step_number": 15,
            "step_name": "Owner Database & Google Review",
            "ai_action_instruction": "Record into Owner Database.xlsx and provide Google Review links.",
            "message_template": "Thank you for appointing Home IHC to market your rental property! 😊\nWe would appreciate your support with a Google Review:\n🔗 Home IHC Bentong (HQ): https://g.page/r/CSRasXyQXRrtEAE/review\n🔗 Home IHC Temerloh (Branch): https://g.page/r/Cce51gfEhNx1EBM/review\n\nThank you! 🙏",
            "expected_data_keys": ["review_request_sent"],
            "next_step": None
        },
        
        # ==========================================
        # AGENT / BROKER PERSONA (Steps 10 to 15)
        # ==========================================
        {
            "persona_type": "AGENT",
            "step_number": 10,
            "step_name": "Agent Greeting & Listing Link",
            "ai_action_instruction": "Greet the agent/broker, share listings directory, and initiate co-broking process.",
            "message_template": "Hi Agent/Broker! 👋\nThank you for contacting Home IHC.\n\nTo assist you more efficiently, could you please share your buyer's requirements?\nProperty Type:\nPreferred Location:\nBudget:\nPurpose: (Own Use / Investment)\n\nYou may also browse our latest listings here:\n🔗 https://bentongland.com.my/listings/\n\nI look forward to your reply. 😊",
            "expected_data_keys": [],
            "next_step": 11
        },
        {
            "persona_type": "AGENT",
            "step_number": 11,
            "step_name": "Agent Name Card & Buyer Specs",
            "ai_action_instruction": "Collect agent name, agency name card, and buyer's specific requirements (type, location, budget, land size, intended use).",
            "message_template": "To ensure a smooth co-broking process, may I kindly have:\n\nAgent Information:\n1️⃣ Your name\n2️⃣ Your agency name card\n\nYour Buyer's Requirements:\n1️⃣ Property Type\n2️⃣ Preferred Location 📍\n3️⃣ Budget Range 💰\n4️⃣ Preferred Land Size 📏\n5️⃣ Intended Use [Durian Farm / Residential / Investment / Other]",
            "expected_data_keys": ["name", "agency_card", "buyer_specs"],
            "next_step": 12
        },
        {
            "persona_type": "AGENT",
            "step_number": 12,
            "step_name": "Confirm Buyer Purchase Entity",
            "ai_action_instruction": "Confirm if the agent's buyer is purchasing under Personal Name or Company Name.",
            "message_template": "Thank you for the information. 😊\nMay I also confirm whether your buyer will be purchasing the property under:\n✅ Personal Name or 🏢 Company Name?\nThis will help us prepare the relevant documentation accordingly.",
            "expected_data_keys": ["purchase_entity"],
            "next_step": 13
        },
        {
            "persona_type": "AGENT",
            "step_number": 13,
            "step_name": "Recommend Listings & Map Search Guide",
            "ai_action_instruction": "Shortlist matching properties. Guide agent to website and Facebook page for location map overview.",
            "message_template": "Based on your buyer's requirements, I have shortlisted several suitable listings with descriptions, photos, videos, and topo plans. 😊\n\nFor property search and overview:\n🌐 Website: https://bentongland.com.my\n📘 Facebook: https://www.facebook.com/PahangAgriLand\n\nWould you like me to send over the property details now?",
            "expected_data_keys": [],
            "next_step": 14
        },
        {
            "persona_type": "AGENT",
            "step_number": 14,
            "step_name": "Viewing Arrangement & Form",
            "ai_action_instruction": "Require Customer Property Acknowledgement & Viewing Form before arranging site visit.",
            "message_template": "If your buyer is interested in arranging a site viewing, we will be happy to assist with the next step. 😊\n\nBefore the site visit can be arranged, the buyer is required to complete and sign our:\n✅ Customer Property Acknowledgement & Viewing Form\n\nOnce completed, our team will coordinate the viewing appointment with you. 🤝",
            "expected_data_keys": ["viewing_form_signed"],
            "next_step": 15
        },
        {
            "persona_type": "AGENT",
            "step_number": 15,
            "step_name": "Internal CRM & Handoff",
            "ai_action_instruction": "Save agent info to CRM and notify Irene Leong (011-6514 4931) for viewing confirmation and co-broking coordination.",
            "message_template": "Thank you for partnering with Home IHC! 🤝\nA senior specialist from our team (Irene Leong: 011-6514 4931) will coordinate the co-broking details and viewing schedule with you directly.",
            "expected_data_keys": [],
            "next_step": None
        },
        
        # ==========================================
        # GLOBAL FALLBACK
        # ==========================================
        {
            "persona_type": "GLOBAL",
            "step_number": 999,
            "step_name": "Handoff to Human",
            "ai_action_instruction": "Trigger this when AI cannot answer or when user explicitly asks to speak with a human agent.",
            "message_template": "A senior property specialist from Home IHC will contact you shortly.",
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

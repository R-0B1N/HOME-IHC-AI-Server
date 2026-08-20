from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Float, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import datetime
import uuid
from urllib.parse import quote_plus
from sqlalchemy.dialects.postgresql import UUID, ARRAY
# from pgvector.sqlalchemy import Vector

DB_HOST = os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "postgres"))
DB_USER = os.getenv("POSTGRES_USER", os.getenv("DB_USER", "n8n"))
DB_PASS = os.getenv("POSTGRES_PASSWORD", os.getenv("DB_PASSWORD", "n8n"))
DB_NAME = os.getenv("POSTGRES_DB", os.getenv("DB_NAME", "whatsapp_ai"))

encoded_pass = quote_plus(DB_PASS) if DB_PASS else ""
DATABASE_URL = f"postgresql://{DB_USER}:{encoded_pass}@{DB_HOST}:5432/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True) # phone number as primary key
    country = Column(String, nullable=True)
    language = Column(String, nullable=True)
    contact_name = Column(String)
    email = Column(String, nullable=True)
    
    # Using JSON to store arrays or complex structures
    conversation_ids = Column(JSON, default=list)
    order_ids = Column(JSON, default=dict)
    relationships = Column(JSON, default=list)
    
    last_interaction = Column(DateTime, default=datetime.datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

class Lead(Base):
    __tablename__ = "leads"

    # 1. Core Lead & Identification
    lead_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True) # Linked to customer
    source_channel = Column(String, default="WhatsApp")
    contact_handle = Column(String)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 2. AI-Extracted Intent & Context
    raw_inquiry_text = Column(String, nullable=True) # Use String/Text
    target_budget_myr = Column(Float, nullable=True)
    target_category = Column(ARRAY(String), default=list)
    target_location = Column(ARRAY(String), default=list)
    minimum_power_amp = Column(Integer, nullable=True)
    semantic_intent = Column(ARRAY(Float), nullable=True) # Use ARRAY(Float) for vector, or pgvector if db upgraded

    # 3. Lead Scoring & Temperature Engine
    lead_score = Column(Integer, default=0)
    lead_temperature = Column(String, default="Cold") # Hot, Warm, Cold
    buying_timeline = Column(String, nullable=True)
    qualification_flags = Column(JSON, default=dict)
    last_scored_at = Column(DateTime, nullable=True)

    # 4. State Management & Automation Control
    lead_status = Column(String, default="AI_Qualifying")
    human_takeover = Column(Boolean, default=False)
    last_contacted_at = Column(DateTime, default=datetime.datetime.utcnow)
    ai_memory_thread = Column(String, nullable=True)
    
    # 5. Relational Linking (The Match Engine)
    presented_properties = Column(ARRAY(UUID(as_uuid=True)), default=list)
    shortlisted_properties = Column(ARRAY(UUID(as_uuid=True)), default=list)


try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

class Property(Base):
    __tablename__ = "properties"

    # 1. Core Property & Identification
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_url = Column(String, nullable=True)
    title = Column(String)
    listing_status = Column(String, default="For Sale")
    property_category = Column(ARRAY(String), default=list)
    property_type_sub = Column(String, nullable=True)  # e.g., "Durian Land", "Semi-D House", "Warehouse", "Shop"

    # 2. Financial Metrics
    asking_price_myr = Column(Float, nullable=True)
    currency = Column(String, default="MYR")
    price_per_acre_myr = Column(Float, nullable=True)
    price_per_sqft_myr = Column(Float, nullable=True)
    monthly_rental_income_myr = Column(Float, nullable=True)
    implied_yield_pct = Column(Float, nullable=True)

    # 3. Physical & Dimensional Specs
    land_area_acres = Column(Float, nullable=True)
    land_area_sqft = Column(Float, nullable=True)
    land_area_sqm = Column(Float, nullable=True)
    built_up_area_sqft = Column(Float, nullable=True)
    tenure_type = Column(String, nullable=True)  # Freehold, Leasehold, Malay Reserved
    zoning_type = Column(String, nullable=True)  # Agricultural, Residential, Commercial, Industrial
    title_status = Column(String, nullable=True)  # Individual Title, Master Title, Commercial Building Title

    # 4. Agricultural & Crop Profile (Bentong/Raub Land specific)
    crop_types = Column(ARRAY(String), default=list)  # ["Musang King", "Black Thorn", "Rubber", "Oil Palm"]
    tree_count_estimate = Column(Integer, nullable=True)
    tree_age_years = Column(String, nullable=True)  # e.g., "6-8 years (Mature Fruit-Bearing)"
    harvest_readiness = Column(String, nullable=True)  # Fruit-Bearing, Young Planting, Vacant/Cleared

    # 5. Topography & Environmental Resources
    topography = Column(String, nullable=True)  # Flat, Gentle Slope, Hilly/Terraced, Hilltop View
    water_source_types = Column(ARRAY(String), default=list)  # ["Natural River Stream", "Pond", "PAIP Water"]
    has_natural_stream = Column(Boolean, default=False)
    has_pond = Column(Boolean, default=False)
    has_piping_system = Column(Boolean, default=False)
    is_flood_free = Column(Boolean, default=True)

    # 6. Infrastructure & Technical Capabilities
    power_supply_amp = Column(Integer, nullable=True)  # 60, 100, 300, 1200
    utilities_available = Column(ARRAY(String), default=list)  # ["Electricity", "Water Supply"]
    has_office = Column(Boolean, default=False)
    office_features = Column(String, nullable=True)
    road_access_quality = Column(String, nullable=True)  # Facing Main Road, Tar Road, Concrete Road, 4WD Required
    is_fenced = Column(Boolean, default=False)
    has_worker_quarters = Column(Boolean, default=False)

    # 7. Tenancy & Commercial Status
    is_tenanted = Column(Boolean, default=False)
    lease_start_date = Column(DateTime, nullable=True)
    lease_end_date = Column(DateTime, nullable=True)
    current_tenant_use = Column(String, nullable=True)

    # 8. Location & Geospatial
    street_address = Column(String, nullable=True)
    area = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, default="Malaysia")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    nearby_landmarks = Column(ARRAY(String), default=list)

    # 9. AI, RAG & Categorized Vector Embeddings
    suitable_industries = Column(ARRAY(String), default=list)
    key_highlights = Column(ARRAY(String), default=list)
    search_corpus_markdown = Column(String, nullable=True)
    
    # 5-Aspect pgvector Embeddings (384-dimensional dense vectors)
    embedding_location = Column(Vector(384) if Vector is not None else ARRAY(Float), nullable=True)
    embedding_specs = Column(Vector(384) if Vector is not None else ARRAY(Float), nullable=True)
    embedding_features = Column(Vector(384) if Vector is not None else ARRAY(Float), nullable=True)
    embedding_suitability = Column(Vector(384) if Vector is not None else ARRAY(Float), nullable=True)
    embedding_overview = Column(Vector(384) if Vector is not None else ARRAY(Float), nullable=True)

    # 10. Agency & Contact Metadata
    agency_name = Column(String, default="HOME IHC SDN. BHD.")
    agent_name = Column(String, nullable=True)
    agent_phone = Column(String, nullable=True)
    agent_whatsapp_url = Column(String, nullable=True)

    # 11. Pipeline & State Management
    scraped_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    source_hash = Column(String, nullable=True)
    is_active_listing = Column(Boolean, default=True)

    # 12. Multimodal Assets & AI Analytics
    image_urls = Column(ARRAY(String), default=list)
    floor_plan_url = Column(String, nullable=True)
    months_to_lease_expiry = Column(Integer, nullable=True)
    risk_flags = Column(ARRAY(String), default=list)
    
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    metadata_json = Column(JSON, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id"))
    transaction_type = Column(String)  # Sale, Rent
    amount = Column(Float)
    date = Column(DateTime, default=datetime.datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    status = Column(String)  # Pending, Completed, Cancelled
    total_amount = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id = Column(Integer, primary_key=True)
    wamid = Column(String, unique=True, index=True, nullable=True) # WhatsApp Message ID for idempotency
    customer_id = Column(String, ForeignKey("customers.id"), index=True)
    direction = Column(String) # INBOUND or OUTBOUND
    message_text = Column(String, nullable=True)
    message_type = Column(String, default="text") # text, image, document, audio
    media_url = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class LeadIntent(Base):
    __tablename__ = "lead_intents"
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), index=True)
    intent_type = Column(String)  # BUYER, SELLER, TENANT, LANDLORD, VALUER, AGENT
    status = Column(String, default="ACTIVE") # ACTIVE, PAUSED, COMPLETED
    collected_data = Column(JSON, default=dict) # To store schema fields incrementally
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id = Column(Integer, primary_key=True)
    persona_type = Column(String, index=True) # BUYER, SELLER, TENANT, LANDLORD
    step_number = Column(Integer)
    step_name = Column(String)
    ai_action_instruction = Column(String) # LLM instruction e.g. "Ask only one question at a time"
    message_template = Column(String) # The exact WhatsApp Message to send
    expected_data_keys = Column(ARRAY(String), default=list) # Fields to extract
    next_step = Column(Integer, nullable=True) # ID of next step
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class User(Base):
    __tablename__ = "crm_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="agent") # "admin", "agent", "viewer"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


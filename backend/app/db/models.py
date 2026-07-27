from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import datetime

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_USER = os.getenv("POSTGRES_USER", "n8n")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "n8n")
DB_NAME = os.getenv("POSTGRES_DB", "whatsapp_ai")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, index=True) # phone number as primary key
    country = Column(String, nullable=True)
    language = Column(String, nullable=True)
    contact_name = Column(String)
    email = Column(String, nullable=True)
    
    # Using JSON to store arrays or complex structures
    conversation_ids = Column(JSON, default=list)
    order_ids = Column(JSON, default=dict)
    relationships = Column(JSON, default=list)
    labels = Column(JSON, default=list)
    interested_properties = Column(JSON, default=list)
    
    intent_category = Column(String)  # Buyer, Seller, Tenant, Agent
    intention_tag = Column(String) # Hot, Warm, Cooling
    last_follow_up_date = Column(DateTime, nullable=True)
    last_interaction = Column(DateTime, default=datetime.datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String)  # Available, Pending, Sold
    name = Column(String, index=True)
    description = Column(String)
    price = Column(Float)
    category = Column(String)
    property_type = Column(String)
    location = Column(String)
    acres = Column(Float)
    title_type = Column(String)
    area = Column(String)
    city = Column(String)
    state = Column(String)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    final_price_sold = Column(Float, nullable=True)
    sale_date = Column(DateTime, nullable=True)
    sales_person = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    property_id = Column(Integer, ForeignKey("properties.id"))
    transaction_type = Column(String)  # Sale, Rent
    amount = Column(Float)
    date = Column(DateTime, default=datetime.datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    status = Column(String)  # Pending, Completed, Cancelled
    total_amount = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    message_in = Column(String)
    message_out = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


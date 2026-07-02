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

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    contact_name = Column(String)
    email = Column(String, nullable=True)
    intent_category = Column(String)  # Buyer, Seller, Tenant, Agent
    last_interaction = Column(DateTime, default=datetime.datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    price = Column(Float)
    status = Column(String)  # Available, Sold, Rented
    location = Column(String)
    metadata_json = Column(JSON, nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    property_id = Column(Integer, ForeignKey("properties.id"))
    transaction_type = Column(String)  # Sale, Rent
    amount = Column(Float)
    date = Column(DateTime, default=datetime.datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    status = Column(String)  # Pending, Completed, Cancelled
    total_amount = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    message_in = Column(String)
    message_out = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

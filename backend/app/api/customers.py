from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Customer, Property, Transaction, Order, InteractionLog
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any, List
import datetime

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    phone_number: str
    contact_name: str
    email: Optional[str] = None
    country: Optional[str] = None
    bypass_ai: Optional[bool] = False

class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    contact_name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    bypass_ai: Optional[bool] = None

from app.core.auth import require_admin
import os

IS_STAGING = (
    os.getenv("DB_HOST") == "whatsapp_ai_db_staging" 
    or "staging" in os.getenv("REDIS_HOST", "")
    or os.getenv("APP_ENV") == "staging"
    or os.getenv("ENVIRONMENT", "").lower() == "staging"
)

def serialize_customer(c: Customer) -> dict:
    meta = c.metadata_json or {}
    cust_inbox = meta.get("inbox_id")
    req_profile = meta.get("requirements_profile") or {
        "active_inquiry": None,
        "retained_inquiries": [],
        "target_locations": [],
        "preferred_property_types": [],
        "target_budget_myr": None,
        "target_budget_formatted": "Not Specified",
        "power_requirements_amp": None,
        "hybrid_opportunity": False
    }
    return {
        "id": c.id,
        "phone_number": c.id,
        "contact_name": c.contact_name,
        "email": c.email,
        "country": c.country,
        "intent_category": meta.get("intent_category", "general"),
        "intention_tag": meta.get("intention_tag", "Cold"),
        "inbox_id": cust_inbox,
        "conversation_ids": c.conversation_ids or [],
        "metadata_json": meta,
        "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None,
        "registered_date": meta.get("registered_date") or (c.last_interaction.isoformat() if c.last_interaction else None),
        "requirements_profile": req_profile,
        "intent_progression": meta.get("intent_progression") or [],
        "presented_properties": meta.get("presented_properties") or [],
        "shortlisted_properties": meta.get("shortlisted_properties") or [],
        "viewing_acknowledgement": meta.get("viewing_acknowledgement") or {
            "status": "No Form Issued",
            "form_no": None,
            "date": None,
            "agent_name": None,
            "notes": ""
        }
    }

@router.get("")
def get_customers(environment: Optional[str] = None, db: Session = Depends(get_db)):
    customers = db.query(Customer).order_by(Customer.last_interaction.desc()).all()
    result = []
    effective_env = environment or ("staging" if IS_STAGING else "production")
    staging_inbox_id = str(os.getenv("STAGING_INBOX_ID", "4"))
    
    for c in customers:
        meta = c.metadata_json or {}
        cust_inbox = meta.get("inbox_id")
        source = meta.get("source")
        
        # Staging isolation criteria:
        is_staging_contact = (
            str(cust_inbox) == staging_inbox_id
            or meta.get("environment") == "staging"
            or (cust_inbox is None and IS_STAGING and source not in ["chatwoot_sync", "chatwoot_startup_sync"])
        )
        
        if effective_env == 'staging':
            if not is_staging_contact:
                continue
        elif effective_env == 'production':
            if is_staging_contact:
                continue
            
        result.append(serialize_customer(c))
    return result

@router.get("/staging")
def get_staging_customers(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """
    Admin-only endpoint to get customer leads for Staging environment.
    """
    customers = db.query(Customer).order_by(Customer.last_interaction.desc()).all()
    result = []
    staging_inbox_id = str(os.getenv("STAGING_INBOX_ID", "4"))
    for c in customers:
        meta = c.metadata_json or {}
        cust_inbox = meta.get("inbox_id")
        source = meta.get("source")
        
        is_staging_contact = (
            str(cust_inbox) == staging_inbox_id
            or meta.get("environment") == "staging"
            or (cust_inbox is None and IS_STAGING and source not in ["chatwoot_sync", "chatwoot_startup_sync"])
        )
        if not is_staging_contact:
            continue
            
        result.append(serialize_customer(c))
    return result

@router.get("/{customer_id}")
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    """
    Get full customer dossier including conversational intent progression, requirements profile,
    presented and shortlisted properties, and viewing acknowledgement status.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return serialize_customer(customer)

from sqlalchemy import text

@router.delete("/staging/reset")
def reset_staging_customers(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """
    Admin-only endpoint to wipe bulk-imported leads from the staging database,
    keeping staging completely clean for test-number interactions only.
    Strictly scoped to staging test inbox leads (inbox_id == '4').
    """
    deleted_count = db.query(Customer).filter(text("(metadata_json->>'inbox_id') = '4'")).delete(synchronize_session=False)
    db.commit()
    return {"status": "success", "message": f"Successfully reset {deleted_count} staging leads."}

@router.patch("/staging/{customer_id}")
def update_staging_customer(customer_id: str, update_data: CustomerUpdate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """
    Admin-only endpoint to update customer lead details in Staging environment.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    if update_data.contact_name is not None:
        customer.contact_name = update_data.contact_name
    if update_data.email is not None:
        customer.email = update_data.email
    if update_data.country is not None:
        customer.country = update_data.country
    if update_data.bypass_ai is not None:
        meta = dict(customer.metadata_json or {})
        meta["bypass_ai"] = update_data.bypass_ai
        customer.metadata_json = meta
        
    db.commit()
    db.refresh(customer)
    return {"status": "success", "id": customer.id, "bypass_ai": (customer.metadata_json or {}).get("bypass_ai", False)}



@router.post("/sync-chatwoot")
def sync_chatwoot(db: Session = Depends(get_db)):
    """
    Sync all contacts from Chatwoot into the local Customer CRM table.
    """
    from app.services.chatwoot import get_all_contacts
    synced_count = 0
    
    # Fetch first few pages of contacts
    for page in range(1, 5):
        contacts = get_all_contacts(page=page)
        if not contacts:
            break
            
        for contact in contacts:
            phone = contact.get("phone_number") or contact.get("identifier")
            if not phone:
                continue
                
            existing = db.query(Customer).filter(Customer.id == phone).first()
            if not existing:
                new_cust = Customer(
                    id=phone,
                    contact_name=contact.get("name") or "WhatsApp Lead",
                    email=contact.get("email"),
                    country="Malaysia",
                    last_interaction=datetime.datetime.utcnow(),
                    metadata_json={
                        "chatwoot_contact_id": contact.get("id"),
                        "source": "chatwoot_sync"
                    }
                )
                db.add(new_cust)
                synced_count += 1
            else:
                if not existing.contact_name and contact.get("name"):
                    existing.contact_name = contact.get("name")
                if not existing.email and contact.get("email"):
                    existing.email = contact.get("email")
                    
    db.commit()
    return {"status": "success", "synced_count": synced_count, "total_leads": db.query(Customer).count()}


@router.post("")
def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_data.phone_number).first()
    if customer:
        raise HTTPException(status_code=400, detail="Customer with this phone number already exists")
    
    meta = {"bypass_ai": customer_data.bypass_ai or False}
    if IS_STAGING:
        meta["inbox_id"] = int(os.getenv("STAGING_INBOX_ID", "4"))
        meta["environment"] = "staging"

    new_customer = Customer(
        id=customer_data.phone_number,
        country=customer_data.country,
        contact_name=customer_data.contact_name,
        email=customer_data.email,
        last_interaction=datetime.datetime.utcnow(),
        metadata_json=meta
    )
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer

@router.put("/{customer_id}")
def update_customer(customer_id: str, customer_data: CustomerUpdate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    if customer_data.contact_name is not None:
        customer.contact_name = customer_data.contact_name
    if customer_data.email is not None:
        customer.email = customer_data.email
    if customer_data.country is not None:
        customer.country = customer_data.country
    if customer_data.bypass_ai is not None:
        meta = customer.metadata_json.copy() if customer.metadata_json else {}
        meta["bypass_ai"] = customer_data.bypass_ai
        customer.metadata_json = meta

    db.commit()
    db.refresh(customer)
    
    return {
        "id": customer.id,
        "contact_name": customer.contact_name,
        "email": customer.email,
        "country": customer.country
    }

class CustomerMigrate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    new_phone_number: str

@router.post("/{customer_id}/migrate")
def migrate_customer(customer_id: str, body: CustomerMigrate, db: Session = Depends(get_db)):
    old_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not old_customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    existing = db.query(Customer).filter(Customer.id == body.new_phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="A customer with this phone number already exists")

    new_customer = Customer(
        id=body.new_phone_number,
        contact_name=old_customer.contact_name,
        email=old_customer.email,
        country=old_customer.country,
        conversation_ids=old_customer.conversation_ids,
        metadata_json=old_customer.metadata_json,
        last_interaction=old_customer.last_interaction,
    )
    db.add(new_customer)

    # Update referencing tables to the new phone number to prevent foreign key constraint violations
    db.query(Property).filter(Property.customer_id == customer_id).update({Property.customer_id: body.new_phone_number})
    db.query(Transaction).filter(Transaction.customer_id == customer_id).update({Transaction.customer_id: body.new_phone_number})
    db.query(Order).filter(Order.customer_id == customer_id).update({Order.customer_id: body.new_phone_number})
    db.query(InteractionLog).filter(InteractionLog.customer_id == customer_id).update({InteractionLog.customer_id: body.new_phone_number})

    db.delete(old_customer)
    db.commit()
    db.refresh(new_customer)

    return {
        "id": new_customer.id,
        "phone_number": new_customer.id,
        "contact_name": new_customer.contact_name,
        "email": new_customer.email,
        "country": new_customer.country,
        "conversation_ids": new_customer.conversation_ids,
        "metadata_json": new_customer.metadata_json,
        "last_interaction": new_customer.last_interaction.isoformat() if new_customer.last_interaction else None
    }

@router.delete("/{customer_id}")
def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    db.delete(customer)
    db.commit()
    return {"message": "Customer deleted successfully"}

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Customer, Property, Transaction, Order, Interaction
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
    country: Optional[str] = None
    ignore_ai: Optional[bool] = False

class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    contact_name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    country: Optional[str] = None
    ignore_ai: Optional[bool] = None

@router.get("")
def get_customers(db: Session = Depends(get_db)):
    customers = db.query(Customer).order_by(Customer.last_interaction.desc()).all()
    result = []
    for c in customers:
        result.append({
            "id": c.id,
            "phone_number": c.id, # id is phone_number
            "contact_name": c.contact_name,
            "email": c.email,
            "country": c.country,
            "conversation_ids": c.conversation_ids,
            "metadata_json": c.metadata_json,
            "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None
        })
    return result

@router.post("")
def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_data.phone_number).first()
    if customer:
        raise HTTPException(status_code=400, detail="Customer with this phone number already exists")
    
    new_customer = Customer(
        id=customer_data.phone_number,
        country=customer_data.country,
        contact_name=customer_data.contact_name,
        email=customer_data.email,
        last_interaction=datetime.datetime.utcnow(),
        metadata_json={"ignore_ai": customer_data.ignore_ai or False}
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
    if customer_data.ignore_ai is not None:
        meta = customer.metadata_json.copy() if customer.metadata_json else {}
        meta["ignore_ai"] = customer_data.ignore_ai
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
    db.query(Interaction).filter(Interaction.customer_id == customer_id).update({Interaction.customer_id: body.new_phone_number})

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

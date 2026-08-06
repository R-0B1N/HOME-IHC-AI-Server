import logging
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.db.models import SessionLocal, Customer, Admin, Employee, Interaction, Property

logger = logging.getLogger(__name__)

import json

def get_or_create_customer(phone_number: str, contact_name: str, email: str = None, conversation_id: int = None, metadata: dict = None) -> Customer:
    """
    Checks if a customer exists by phone_number. If not, creates one.
    Returns the Customer object.
    """
    db: Session = SessionLocal()
    try:
        if not phone_number:
            logger.warning("No phone number provided to get_or_create_customer")
            return None
            
        customer = db.query(Customer).filter(Customer.id == phone_number).first()
        if not customer:
            logger.info(f"Creating new customer: {contact_name} ({phone_number})")
            # Parse country if possible (simple heuristic for Malaysia)
            country = "Malaysia" if phone_number.startswith("+60") else "Unknown"
            customer = Customer(
                id=phone_number,
                country=country,
                contact_name=contact_name,
                email=email,
                conversation_ids=[conversation_id] if conversation_id else [],
                metadata_json=metadata if metadata else {}
            )
            db.add(customer)
            try:
                db.commit()
                db.refresh(customer)
            except IntegrityError:
                db.rollback()
                logger.warning(f"Customer {phone_number} was created concurrently. Fetching existing.")
                customer = db.query(Customer).filter(Customer.id == phone_number).first()
                if not customer:
                    return None
        if customer:
            # Update the contact_name if the incoming name is not 'Unknown' or 'John Doe'
            updated = False
            if contact_name and contact_name.lower() not in ["unknown", "john doe"] and customer.contact_name != contact_name:
                logger.info(f"Updating customer name from {customer.contact_name} to {contact_name}")
                customer.contact_name = contact_name
                updated = True
                
            if conversation_id:
                conv_ids = customer.conversation_ids or []
                if conversation_id not in conv_ids:
                    conv_ids.append(conversation_id)
                    customer.conversation_ids = conv_ids
                    updated = True
                    
            if metadata:
                current_meta = customer.metadata_json or {}
                # Update with new metadata
                current_meta.update(metadata)
                customer.metadata_json = current_meta
                updated = True

            if updated:
                db.commit()
                db.refresh(customer)
        return customer
    except Exception as e:
        logger.error(f"Error in get_or_create_customer: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def log_interaction(customer_id: str, message_in: str, message_out: str):
    """
    Logs an interaction between the bot and the customer.
    """
    db: Session = SessionLocal()
    try:
        if not customer_id:
            return
            
        interaction = Interaction(
            customer_id=customer_id,
            message_in=message_in,
            message_out=message_out
        )
        db.add(interaction)
        
        # Update last interaction time
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.last_interaction = interaction.timestamp
            
        db.commit()
    except Exception as e:
        logger.error(f"Error in log_interaction: {e}")
        db.rollback()
    finally:
        db.close()

def get_sender_role(phone_number: str) -> str:
    """
    Checks the phone number against Admin, Employee, and Customer tables.
    Returns 'admin', 'employee', or 'customer'.
    """
    db: Session = SessionLocal()
    try:
        if not phone_number:
            return "unknown"
            
        is_admin = db.query(Admin).filter(Admin.phone_number == phone_number).first()
        if is_admin:
            return "admin"
            
        is_employee = db.query(Employee).filter(Employee.phone_number == phone_number).first()
        if is_employee:
            return "employee"
            
        return "customer"
    except Exception as e:
        logger.error(f"Error checking sender role: {e}")
        return "customer"
    finally:
        db.close()

def search_properties(criteria: dict, limit: int = 15) -> list:
    """
    Search the Property table based on extracted criteria (location, property_type, max_price).
    """
    db: Session = SessionLocal()
    try:
        query = db.query(Property).filter(Property.listing_status.in_(["Available", "For Sale", "For Rent"]))
        
        location = criteria.get("location")
        if location:
            search_loc = f"%{location}%"
            query = query.filter(or_(
                Property.location.ilike(search_loc),
                Property.name.ilike(search_loc),
                Property.description.ilike(search_loc)
            ))
            
        property_type = criteria.get("property_type")
        if property_type:
            search_type = f"%{property_type}%"
            query = query.filter(or_(
                Property.name.ilike(search_type),
                Property.description.ilike(search_type)
            ))
            
        max_price = criteria.get("max_price")
        if max_price:
            try:
                max_price_float = float(max_price)
                query = query.filter(Property.price <= max_price_float)
            except ValueError:
                pass
                
        results = query.limit(limit).all()
        # Convert to dict for easier JSON serialization
        return [{"id": p.id, "name": p.name, "price": p.price, "location": p.location, "status": p.status} for p in results]
    except Exception as e:
        logger.error(f"Error searching properties: {e}")
        return []
    finally:
        db.close()

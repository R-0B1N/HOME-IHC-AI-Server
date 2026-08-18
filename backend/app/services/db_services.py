import logging
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.db.models import SessionLocal, Customer, Admin, Employee, InteractionLog, Property

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
            
        interaction = InteractionLog(
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

def search_properties(criteria: dict, limit: int = 10) -> list:
    """
    Search the Property table based on extracted criteria (location, property_type, max_price).
    Only returns properties that are currently Available, For Sale, or For Rent.
    """
    db: Session = SessionLocal()
    try:
        query = db.query(Property).filter(
            Property.listing_status.in_(["Available", "For Sale", "For Rent"])
        )
        
        location = criteria.get("location")
        if location and str(location).lower() not in ["none", "null", "all"]:
            search_loc = f"%{location}%"
            query = query.filter(or_(
                Property.city.ilike(search_loc),
                Property.state.ilike(search_loc),
                Property.street_address.ilike(search_loc),
                Property.title.ilike(search_loc),
                Property.search_corpus_markdown.ilike(search_loc)
            ))
            
        property_type = criteria.get("property_type")
        if property_type and str(property_type).lower() not in ["none", "null", "all"]:
            search_type = f"%{property_type}%"
            query = query.filter(or_(
                Property.title.ilike(search_type),
                Property.search_corpus_markdown.ilike(search_type)
            ))
            
        max_price = criteria.get("max_price")
        if max_price:
            try:
                max_price_float = float(max_price)
                if max_price_float > 0:
                    query = query.filter(Property.asking_price_myr <= max_price_float)
            except (ValueError, TypeError):
                pass
                
        results = query.order_by(Property.last_updated_at.desc()).limit(limit).all()
        return [
            {
                "id": str(p.id),
                "title": p.title,
                "price": p.asking_price_myr,
                "city": p.city,
                "state": p.state,
                "acres": p.land_area_acres,
                "status": p.listing_status,
                "url": p.source_url or f"https://bentongland.com.my/land/{p.id}"
            }
            for p in results
        ]
    except Exception as e:
        logger.error(f"Error searching properties: {e}")
        return []
    finally:
        db.close()

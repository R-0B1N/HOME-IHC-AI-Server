import logging
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Customer, Admin, Employee, Interaction

logger = logging.getLogger(__name__)

def get_or_create_customer(phone_number: str, contact_name: str, email: str = None) -> Customer:
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
                intent_category="general"
            )
            db.add(customer)
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

import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import sessionmaker
from app.db.models import Customer, engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def reset_ai_flags():
    print("Resetting ignore_ai flags for all customers...")
    db = SessionLocal()
    try:
        customers = db.query(Customer).all()
        updated_count = 0
        for cust in customers:
            if cust.metadata_json and cust.metadata_json.get("ignore_ai"):
                meta = cust.metadata_json.copy()
                meta["ignore_ai"] = False
                cust.metadata_json = meta
                updated_count += 1
        
        db.commit()
        print(f"Successfully reset ignore_ai flag for {updated_count} customers.")
    except Exception as e:
        print(f"Error resetting flags: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_ai_flags()

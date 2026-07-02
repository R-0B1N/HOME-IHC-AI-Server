import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Base, engine
import app.db.models as models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def recreate_tables():
    logger.info("Dropping all existing tables...")
    Base.metadata.drop_all(bind=engine)
    
    logger.info("Recreating all tables based on new schema...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database reset complete.")

if __name__ == "__main__":
    recreate_tables()

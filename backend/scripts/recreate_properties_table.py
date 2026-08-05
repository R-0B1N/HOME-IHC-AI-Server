import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import engine, Property, Base
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def recreate_properties_table():
    logging.info("Dropping all tables to resolve foreign key constraints...")
    Base.metadata.drop_all(engine)
    logging.info("Creating all tables...")
    Base.metadata.create_all(engine)
    Property.__table__.create(engine, checkfirst=True)
    logger.info("Successfully recreated properties table.")

if __name__ == "__main__":
    recreate_properties_table()

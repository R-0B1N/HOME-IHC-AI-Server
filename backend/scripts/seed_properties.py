import sys
import os
import uuid
import logging
from sqlalchemy import or_

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DUMMY_TITLES = [
    "Bentong Musang King Durian Orchard (5.2 Acres)",
    "Karak Industrial Development Land (10.0 Acres)",
    "Bukit Tinggi Agro-Tourism & Eco-Resort Land (3.8 Acres)",
    "Raub Main Road Commercial Land Frontage (1.5 Acres)",
    "Bentong Forest Sanctuary Villa Land Plot (1.2 Acres)",
    "Land Archive-2",
    "Sample Property Listing"
]

def purge_dummy_properties():
    """
    Purges synthetic mock/dummy properties from the database so only authentic WordPress listings exist.
    """
    db = SessionLocal()
    try:
        deleted = db.query(Property).filter(
            or_(
                Property.title.in_(DUMMY_TITLES),
                Property.source_url.like("%durian-orchard-5-acres%"),
                Property.source_url.like("%karak-industrial-10-acres%"),
                Property.source_url.like("%bukit-tinggi-agro-resort%"),
                Property.source_url.like("%raub-commercial-frontage%"),
                Property.source_url.like("%bentong-sanctuary-villa%")
            )
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Purged {deleted} dummy/mock properties from database.")
        return deleted
    except Exception as e:
        logger.error(f"Error purging dummy properties: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

def seed_properties():
    # Only purge dummy properties, never insert fake data
    purge_dummy_properties()

if __name__ == "__main__":
    purge_dummy_properties()

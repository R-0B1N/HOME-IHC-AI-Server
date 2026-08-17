import sys
import os
import uuid
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INITIAL_PROPERTIES = [
    {
        "title": "Bentong Musang King Durian Orchard (5.2 Acres)",
        "search_corpus_markdown": "Matured Musang King (Black Thorn & D24) durian orchard with natural stream, direct tar road access, and complete solar-powered irrigation system. Freehold tenure with high investment yield.",
        "source_url": "https://bentongland.com.my/land/durian-orchard-5-acres/",
        "listing_status": "Available",
        "property_category": ["Agricultural Land", "Durian Orchard"],
        "asking_price_myr": 2850000.0,
        "city": "Bentong",
        "state": "Pahang",
        "street_address": "Mukim Bentong, Jalan Tranum",
        "land_area_acres": 5.2,
        "built_up_area_sqft": 0.0,
        "tenure_type": "Freehold",
        "power_supply_amp": 100,
        "is_tenanted": False,
        "image_urls": ["https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=800&q=80"]
    },
    {
        "title": "Karak Industrial Development Land (10.0 Acres)",
        "search_corpus_markdown": "Prime medium industrial land parcel with direct main trunk road frontage. Flat terrain with immediate connection to high-voltage power grid and municipal water pipelines.",
        "source_url": "https://bentongland.com.my/land/karak-industrial-10-acres/",
        "listing_status": "Available",
        "property_category": ["Industrial Land"],
        "asking_price_myr": 6500000.0,
        "city": "Karak",
        "state": "Pahang",
        "street_address": "Karak Industrial Estate Zone 2",
        "land_area_acres": 10.0,
        "built_up_area_sqft": 0.0,
        "tenure_type": "Leasehold (99 Years)",
        "power_supply_amp": 1000,
        "is_tenanted": False,
        "image_urls": ["https://images.unsplash.com/photo-1581094794329-c8112a89af12?auto=format&fit=crop&w=800&q=80"]
    },
    {
        "title": "Bukit Tinggi Agro-Tourism & Eco-Resort Land (3.8 Acres)",
        "search_corpus_markdown": "Cool climate highland agricultural plot suited for glamping resorts, organic fruit farming, or private corporate retreats. Only 40 minutes drive from Kuala Lumpur.",
        "source_url": "https://bentongland.com.my/land/bukit-tinggi-agro-resort/",
        "listing_status": "Available",
        "property_category": ["Agricultural Land", "Commercial Land"],
        "asking_price_myr": 3200000.0,
        "city": "Bukit Tinggi",
        "state": "Pahang",
        "street_address": "Kampung Bukit Tinggi, Mukim Bentong",
        "land_area_acres": 3.8,
        "built_up_area_sqft": 0.0,
        "tenure_type": "Freehold",
        "power_supply_amp": 60,
        "is_tenanted": False,
        "image_urls": ["https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=800&q=80"]
    },
    {
        "title": "Raub Main Road Commercial Land Frontage (1.5 Acres)",
        "search_corpus_markdown": "High traffic commercial frontage site ideal for showroom, heavy machinery depot, or service center development. Surrounded by established commercial hubs.",
        "source_url": "https://bentongland.com.my/land/raub-commercial-frontage/",
        "listing_status": "For Sale",
        "property_category": ["Commercial Land"],
        "asking_price_myr": 1800000.0,
        "city": "Raub",
        "state": "Pahang",
        "street_address": "Jalan Lipis-Raub Main Highway",
        "land_area_acres": 1.5,
        "built_up_area_sqft": 0.0,
        "tenure_type": "Freehold",
        "power_supply_amp": 200,
        "is_tenanted": False,
        "image_urls": ["https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=800&q=80"]
    },
    {
        "title": "Bentong Forest Sanctuary Villa Land Plot (1.2 Acres)",
        "search_corpus_markdown": "Exclusive residential homestead plot within an elevated private enclave. Features mountain views, underground utilities, and gated security access.",
        "source_url": "https://bentongland.com.my/land/bentong-sanctuary-villa/",
        "listing_status": "Available",
        "property_category": ["Residential Land"],
        "asking_price_myr": 950000.0,
        "city": "Bentong",
        "state": "Pahang",
        "street_address": "Chamang Forest Enclave, Bentong",
        "land_area_acres": 1.2,
        "built_up_area_sqft": 0.0,
        "tenure_type": "Freehold",
        "power_supply_amp": 60,
        "is_tenanted": False,
        "image_urls": ["https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=800&q=80"]
    }
]

def seed_properties():
    db = SessionLocal()
    try:
        count = db.query(Property).count()
        if count > 0:
            logger.info(f"Database already contains {count} properties. Skipping seed.")
            return

        logger.info("Seeding initial BentongLand property listings...")
        for item in INITIAL_PROPERTIES:
            prop = Property(
                id=str(uuid.uuid4()),
                title=item["title"],
                search_corpus_markdown=item["search_corpus_markdown"],
                source_url=item["source_url"],
                listing_status=item["listing_status"],
                property_category=item["property_category"],
                asking_price_myr=item["asking_price_myr"],
                city=item["city"],
                state=item["state"],
                street_address=item["street_address"],
                land_area_acres=item["land_area_acres"],
                built_up_area_sqft=item["built_up_area_sqft"],
                tenure_type=item["tenure_type"],
                power_supply_amp=item["power_supply_amp"],
                is_tenanted=item["is_tenanted"],
                image_urls=item["image_urls"]
            )
            db.add(prop)
        db.commit()
        logger.info(f"Successfully seeded {len(INITIAL_PROPERTIES)} properties into database.")
    except Exception as e:
        logger.error(f"Error seeding properties: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_properties()

import sys
import os
import logging
import time

# Ensure python path is set to backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.models import SessionLocal, Property
from app.services.llm import extract_wordpress_property
from app.services.embeddings import generate_property_5_embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reprocess_properties")

def reprocess_all():
    db = SessionLocal()
    try:
        properties = db.query(Property).all()
        total = len(properties)
        logger.info(f"Starting reprocessing and enrichment for {total} properties...")
        
        updated_count = 0
        error_count = 0
        
        for idx, prop in enumerate(properties, start=1):
            try:
                logger.info(f"[{idx}/{total}] Processing: {prop.title[:60]}...")
                
                payload = {
                    "title": prop.title,
                    "description": prop.search_corpus_markdown or prop.title,
                    "categories": prop.property_category or [],
                    "image_urls": prop.image_urls or [],
                    "status": prop.listing_status or "For Sale"
                }
                
                extracted = extract_wordpress_property(payload)
                
                # Update Core & Financials
                if extracted.get("property_type_sub"):
                    prop.property_type_sub = extracted["property_type_sub"]
                if extracted.get("property_category"):
                    prop.property_category = extracted["property_category"]
                    
                if extracted.get("asking_price_myr") is not None and extracted["asking_price_myr"] > 0:
                    prop.asking_price_myr = extracted["asking_price_myr"]
                if extracted.get("monthly_rental_income_myr") is not None:
                    prop.monthly_rental_income_myr = extracted["monthly_rental_income_myr"]
                if extracted.get("price_per_acre_myr") is not None:
                    prop.price_per_acre_myr = extracted["price_per_acre_myr"]
                if extracted.get("price_per_sqft_myr") is not None:
                    prop.price_per_sqft_myr = extracted["price_per_sqft_myr"]
                if extracted.get("implied_yield_pct") is not None:
                    prop.implied_yield_pct = extracted["implied_yield_pct"]
                    
                # Update Specs
                if extracted.get("land_area_acres") is not None and extracted["land_area_acres"] > 0:
                    prop.land_area_acres = extracted["land_area_acres"]
                if extracted.get("land_area_sqft") is not None:
                    prop.land_area_sqft = extracted["land_area_sqft"]
                if extracted.get("land_area_sqm") is not None:
                    prop.land_area_sqm = extracted["land_area_sqm"]
                if extracted.get("built_up_area_sqft") is not None:
                    prop.built_up_area_sqft = extracted["built_up_area_sqft"]
                if extracted.get("tenure_type"):
                    prop.tenure_type = extracted["tenure_type"]
                if extracted.get("zoning_type"):
                    prop.zoning_type = extracted["zoning_type"]
                if extracted.get("title_status"):
                    prop.title_status = extracted["title_status"]
                    
                # Update Agricultural & Land Features
                prop.crop_types = extracted.get("crop_types", [])
                if extracted.get("tree_count_estimate") is not None:
                    prop.tree_count_estimate = extracted["tree_count_estimate"]
                if extracted.get("tree_age_years"):
                    prop.tree_age_years = extracted["tree_age_years"]
                if extracted.get("harvest_readiness"):
                    prop.harvest_readiness = extracted["harvest_readiness"]
                    
                # Update Topography & Water
                if extracted.get("topography"):
                    prop.topography = extracted["topography"]
                prop.water_source_types = extracted.get("water_source_types", [])
                prop.has_natural_stream = bool(extracted.get("has_natural_stream", False))
                prop.has_pond = bool(extracted.get("has_pond", False))
                prop.has_piping_system = bool(extracted.get("has_piping_system", False))
                prop.is_flood_free = bool(extracted.get("is_flood_free", True))
                
                # Update Infrastructure
                if extracted.get("power_supply_amp") is not None:
                    prop.power_supply_amp = extracted["power_supply_amp"]
                if extracted.get("utilities_available"):
                    prop.utilities_available = extracted["utilities_available"]
                prop.has_office = bool(extracted.get("has_office", False))
                if extracted.get("office_features"):
                    prop.office_features = extracted["office_features"]
                if extracted.get("road_access_quality"):
                    prop.road_access_quality = extracted["road_access_quality"]
                prop.is_fenced = bool(extracted.get("is_fenced", False))
                prop.has_worker_quarters = bool(extracted.get("has_worker_quarters", False))
                
                # Update Location & Geospatial
                if extracted.get("street_address"):
                    prop.street_address = extracted["street_address"]
                if extracted.get("area"):
                    prop.area = extracted["area"]
                if extracted.get("city"):
                    prop.city = extracted["city"]
                if extracted.get("state"):
                    prop.state = extracted["state"]
                if extracted.get("latitude") is not None:
                    prop.latitude = extracted["latitude"]
                if extracted.get("longitude") is not None:
                    prop.longitude = extracted["longitude"]
                prop.nearby_landmarks = extracted.get("nearby_landmarks", [])
                
                # Update AI & Embeddings
                prop.suitable_industries = extracted.get("suitable_industries", [])
                prop.key_highlights = extracted.get("key_highlights", [])
                prop.risk_flags = extracted.get("risk_flags", [])
                
                if extracted.get("embedding_location") is not None:
                    prop.embedding_location = extracted["embedding_location"]
                if extracted.get("embedding_specs") is not None:
                    prop.embedding_specs = extracted["embedding_specs"]
                if extracted.get("embedding_features") is not None:
                    prop.embedding_features = extracted["embedding_features"]
                if extracted.get("embedding_suitability") is not None:
                    prop.embedding_suitability = extracted["embedding_suitability"]
                if extracted.get("embedding_overview") is not None:
                    prop.embedding_overview = extracted["embedding_overview"]
                    
                updated_count += 1
                
                # Commit every 10 properties
                if idx % 10 == 0:
                    db.commit()
                    logger.info(f"Committed batch up to {idx}/{total}.")
                    
            except Exception as e:
                logger.error(f"Error enriching property {prop.id} ({prop.title}): {e}")
                error_count += 1
                
        db.commit()
        logger.info(f"Reprocessing completed! Total: {total}, Successfully Updated: {updated_count}, Errors: {error_count}")
    finally:
        db.close()

if __name__ == "__main__":
    reprocess_all()

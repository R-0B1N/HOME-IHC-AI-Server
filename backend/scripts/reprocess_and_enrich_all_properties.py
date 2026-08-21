import sys
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure python path is set to backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.models import SessionLocal, Property, engine, run_schema_migrations
from app.services.llm import extract_wordpress_property
from app.services.embeddings import generate_property_5_embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reprocess_properties")

def process_single_property(prop_id):
    db = SessionLocal()
    try:
        prop = db.query(Property).filter(Property.id == prop_id).first()
        if not prop:
            return False
            
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
        prop.nearby_landmarks = extracted.get("nearby_landmarks", [])
        
        # Update Operational / Tenancy
        prop.is_tenanted = bool(extracted.get("is_tenanted", False))
        if extracted.get("current_tenant_use"):
            prop.current_tenant_use = extracted["current_tenant_use"]
            
        # Update Suitability & Highlights
        prop.suitable_industries = extracted.get("suitable_industries", [])
        prop.key_highlights = extracted.get("key_highlights", [])
        prop.risk_flags = extracted.get("risk_flags", [])
        
        # Generate 5 Dense Vector Embeddings (384-dim FastEmbed)
        vecs = generate_property_5_embeddings(prop)
        prop.embedding_location = vecs.get("embedding_location")
        prop.embedding_specs = vecs.get("embedding_specs")
        prop.embedding_features = vecs.get("embedding_features")
        prop.embedding_suitability = vecs.get("embedding_suitability")
        prop.embedding_overview = vecs.get("embedding_overview")
        
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing property {prop_id}: {e}")
        return False
    finally:
        db.close()

def reprocess_all():
    logger.info("Ensuring all 12-category schema columns and vector extensions exist in database...")
    run_schema_migrations(engine)
    
    db = SessionLocal()
    try:
        count = db.query(Property).count()
        if count == 0:
            logger.info("Database has 0 properties. Syncing authentic listings from bentongland.com.my WordPress...")
            from scripts.scrape_and_ingest_all_properties import fetch_and_ingest_all
            fetch_and_ingest_all()
            
        prop_ids = [p.id for p in db.query(Property.id).all()]
        total = len(prop_ids)
        logger.info(f"Starting parallel reprocessing, 12-category enrichment, and 5-aspect vector embedding for {total} properties...")
        
        updated_count = 0
        error_count = 0
        
        # Concurrently process in parallel threads (10 workers)
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(process_single_property, pid): pid for pid in prop_ids}
            for idx, future in enumerate(as_completed(future_to_id), start=1):
                pid = future_to_id[future]
                try:
                    success = future.result()
                    if success:
                        updated_count += 1
                    else:
                        error_count += 1
                except Exception as exc:
                    logger.error(f"Property {pid} generated exception: {exc}")
                    error_count += 1
                
                if idx % 10 == 0 or idx == total:
                    logger.info(f"Progress: [{idx}/{total}] completed. (Success: {updated_count}, Errors: {error_count})")
        
        logger.info(f"Reprocessing completed! Total: {total}, Successfully Updated: {updated_count}, Errors: {error_count}")
    finally:
        db.close()

if __name__ == "__main__":
    reprocess_all()

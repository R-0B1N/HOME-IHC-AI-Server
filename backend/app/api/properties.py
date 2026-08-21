from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Property
from pydantic import BaseModel, ConfigDict

router = APIRouter()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    title: str
    description: str = ""
    source_url: str = ""
    listing_status: str = "Available"
    property_category: list[str] = []
    
    asking_price_myr: float = 0.0
    rental_price_myr: float = 0.0
    maintenance_fee_myr: float = 0.0
    valuation_price_myr: float = 0.0
    
    city: str = ""
    state: str = ""
    address: str = ""
    land_area_acres: float = 0.0
    built_up_sqft: float = 0.0
    tenure: str = ""
    occupancy_status: str = ""
    furnishing: str = ""
    
    bedrooms: int = 0
    bathrooms: int = 0
    car_parks: int = 0
    
    amenities: list[str] = []
    facilities: list[str] = []
    
    is_bumi_lot: bool = False
    year_built: int = 0
    developer: str = ""

@router.get("")
def read_properties(skip: int = 0, limit: int = 500, db: Session = Depends(get_db)):
    properties = db.query(Property).offset(skip).limit(limit).all()
    return properties

@router.post("/cleanup-dummy")
def cleanup_dummy_properties(db: Session = Depends(get_db)):
    """
    Purges synthetic mock/dummy properties from the database so only authentic WordPress listings exist.
    """
    from scripts.seed_properties import purge_dummy_properties
    deleted = purge_dummy_properties()
    return {"status": "success", "deleted_count": deleted, "remaining_properties": db.query(Property).count()}

@router.post("/seed-defaults")
def seed_default_properties(db: Session = Depends(get_db)):
    """
    Purges dummy properties and maintains authentic listings.
    """
    from scripts.seed_properties import seed_properties
    seed_properties()
    return {"status": "success", "count": db.query(Property).count()}

@router.post("/sync-wordpress")
def sync_wordpress_all(db: Session = Depends(get_db)):
    """
    Scrapes and syncs all live property listings from bentongland.com.my WordPress REST API.
    """
    from scripts.scrape_and_ingest_all_properties import fetch_and_ingest_all
    result = fetch_and_ingest_all()
    return result



@router.get("/embeddings/summary")
def get_embeddings_summary(db: Session = Depends(get_db)):
    """
    Returns summary statistics for the 5-aspect vector embeddings across all listings.
    """
    total = db.query(Property).count()
    with_overview = db.query(Property).filter(Property.embedding_overview.isnot(None)).count()
    with_location = db.query(Property).filter(Property.embedding_location.isnot(None)).count()
    with_specs = db.query(Property).filter(Property.embedding_specs.isnot(None)).count()
    with_features = db.query(Property).filter(Property.embedding_features.isnot(None)).count()
    with_suitability = db.query(Property).filter(Property.embedding_suitability.isnot(None)).count()
    
    return {
        "total_properties": total,
        "aspect_embeddings_stats": {
            "overview_count": with_overview,
            "location_count": with_location,
            "specs_count": with_specs,
            "features_count": with_features,
            "suitability_count": with_suitability,
            "total_vectors_generated": (with_overview + with_location + with_specs + with_features + with_suitability),
            "fully_vectorized_pct": round((with_overview / total * 100), 1) if total > 0 else 0
        },
        "embedding_dimensions": 384,
        "embedding_model": "BAAI/bge-small-en-v1.5 (FastEmbed ONNX)"
    }

@router.get("/embeddings/aspects/{property_id}")
def get_property_aspects(property_id: str, db: Session = Depends(get_db)):
    """
    Returns the 5 aspect text chunks and vector status for a specific property.
    """
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return {"error": "Property not found"}
    
    from app.services.embeddings import build_property_aspect_chunks
    chunks = build_property_aspect_chunks(prop)
    
    return {
        "property_id": str(prop.id),
        "title": prop.title,
        "city": prop.city,
        "category": prop.property_category or [],
        "price": prop.asking_price_myr,
        "has_embeddings": {
            "overview": prop.embedding_overview is not None,
            "location": prop.embedding_location is not None,
            "specs": prop.embedding_specs is not None,
            "features": prop.embedding_features is not None,
            "suitability": prop.embedding_suitability is not None,
        },
        "aspect_chunks": chunks
    }

class QuerySearchRequest(BaseModel):
    query: str
    limit: int = 6

@router.post("/embeddings/query-search")
def search_embeddings_query(req: QuerySearchRequest, db: Session = Depends(get_db)):
    """
    Simulates natural language vector search and computes multi-aspect similarity against listings.
    """
    from app.services.embeddings import generate_embedding
    from app.services.db_services import _cosine_similarity
    
    q_vec = generate_embedding(req.query)
    if not q_vec:
        return {"results": [], "query": req.query, "message": "Could not vectorize query"}
        
    properties = db.query(Property).filter(Property.embedding_overview.isnot(None)).all()
    scored = []
    
    for p in properties:
        ov_sim = _cosine_similarity(q_vec, p.embedding_overview) if p.embedding_overview else 0.0
        loc_sim = _cosine_similarity(q_vec, p.embedding_location) if p.embedding_location else 0.0
        spec_sim = _cosine_similarity(q_vec, p.embedding_specs) if p.embedding_specs else 0.0
        feat_sim = _cosine_similarity(q_vec, p.embedding_features) if p.embedding_features else 0.0
        suit_sim = _cosine_similarity(q_vec, p.embedding_suitability) if p.embedding_suitability else 0.0
        
        composite = (ov_sim * 0.35) + (loc_sim * 0.20) + (spec_sim * 0.20) + (feat_sim * 0.15) + (suit_sim * 0.10)
        
        scored.append({
            "id": str(p.id),
            "title": p.title,
            "city": p.city,
            "category": p.property_category or [],
            "asking_price_myr": p.asking_price_myr,
            "land_area_acres": p.land_area_acres,
            "built_up_area_sqft": p.built_up_area_sqft,
            "image_url": p.image_urls[0] if p.image_urls else None,
            "similarity_score": round(composite, 4),
            "aspect_breakdown": {
                "overview_pct": round(ov_sim * 100, 1),
                "location_pct": round(loc_sim * 100, 1),
                "specs_pct": round(spec_sim * 100, 1),
                "features_pct": round(feat_sim * 100, 1),
                "suitability_pct": round(suit_sim * 100, 1),
            }
        })
        
    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return {"query": req.query, "results": scored[:req.limit]}

@router.get("/embeddings/correlations/{property_id}")
def get_property_correlations(property_id: str, limit: int = 6, db: Session = Depends(get_db)):
    """
    Computes dense cosine similarity correlations between a target property and other listings across all 5 aspects.
    """
    ref_prop = db.query(Property).filter(Property.id == property_id).first()
    if not ref_prop:
        return {"error": "Target property not found"}
        
    from app.services.db_services import _cosine_similarity
    
    candidates = db.query(Property).filter(
        Property.id != property_id,
        Property.embedding_overview.isnot(None)
    ).all()
    
    correlations = []
    for p in candidates:
        loc_sim = _cosine_similarity(ref_prop.embedding_location, p.embedding_location) if ref_prop.embedding_location and p.embedding_location else 0.0
        spec_sim = _cosine_similarity(ref_prop.embedding_specs, p.embedding_specs) if ref_prop.embedding_specs and p.embedding_specs else 0.0
        feat_sim = _cosine_similarity(ref_prop.embedding_features, p.embedding_features) if ref_prop.embedding_features and p.embedding_features else 0.0
        suit_sim = _cosine_similarity(ref_prop.embedding_suitability, p.embedding_suitability) if ref_prop.embedding_suitability and p.embedding_suitability else 0.0
        ov_sim = _cosine_similarity(ref_prop.embedding_overview, p.embedding_overview) if ref_prop.embedding_overview and p.embedding_overview else 0.0
        
        overall = (ov_sim * 0.35) + (loc_sim * 0.20) + (spec_sim * 0.20) + (feat_sim * 0.15) + (suit_sim * 0.10)
        
        correlations.append({
            "id": str(p.id),
            "title": p.title,
            "city": p.city,
            "category": p.property_category or [],
            "asking_price_myr": p.asking_price_myr,
            "land_area_acres": p.land_area_acres,
            "built_up_area_sqft": p.built_up_area_sqft,
            "image_url": p.image_urls[0] if p.image_urls else None,
            "correlation_score": round(overall, 4),
            "aspect_breakdown": {
                "location_pct": round(loc_sim * 100, 1),
                "specs_pct": round(spec_sim * 100, 1),
                "features_pct": round(feat_sim * 100, 1),
                "suitability_pct": round(suit_sim * 100, 1),
                "overview_pct": round(ov_sim * 100, 1),
            }
        })
        
    correlations.sort(key=lambda x: x["correlation_score"], reverse=True)
    
    return {
        "target_property": {
            "id": str(ref_prop.id),
            "title": ref_prop.title,
            "city": ref_prop.city,
            "category": ref_prop.property_category or [],
            "asking_price_myr": ref_prop.asking_price_myr,
            "image_url": ref_prop.image_urls[0] if ref_prop.image_urls else None
        },
        "top_correlated": correlations[:limit]
    }

import uuid


@router.post("")
def create_property(prop: PropertyCreate, db: Session = Depends(get_db)):
    db_prop = Property(
        id=str(uuid.uuid4()),
        title=prop.title,
        description=prop.description,
        source_url=prop.source_url,
        listing_status=prop.listing_status,
        property_category=prop.property_category,
        
        asking_price_myr=prop.asking_price_myr,
        rental_price_myr=prop.rental_price_myr,
        maintenance_fee_myr=prop.maintenance_fee_myr,
        valuation_price_myr=prop.valuation_price_myr,
        
        city=prop.city,
        state=prop.state,
        address=prop.address,
        land_area_acres=prop.land_area_acres,
        built_up_sqft=prop.built_up_sqft,
        tenure=prop.tenure,
        occupancy_status=prop.occupancy_status,
        furnishing=prop.furnishing,
        
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        car_parks=prop.car_parks,
        
        amenities=prop.amenities,
        facilities=prop.facilities,
        
        is_bumi_lot=prop.is_bumi_lot,
        year_built=prop.year_built,
        developer=prop.developer
    )
    db.add(db_prop)
    db.commit()
    db.refresh(db_prop)
    return db_prop

@router.put("/{property_id}")
def update_property(property_id: str, prop: PropertyCreate, db: Session = Depends(get_db)):
    db_prop = db.query(Property).filter(Property.id == property_id).first()
    if not db_prop:
        return {"error": "Property not found"}
        
    db_prop.title = prop.title
    db_prop.description = prop.description
    db_prop.source_url = prop.source_url
    db_prop.listing_status = prop.listing_status
    db_prop.property_category = prop.property_category
    
    db_prop.asking_price_myr = prop.asking_price_myr
    db_prop.rental_price_myr = prop.rental_price_myr
    db_prop.maintenance_fee_myr = prop.maintenance_fee_myr
    db_prop.valuation_price_myr = prop.valuation_price_myr
    
    db_prop.city = prop.city
    db_prop.state = prop.state
    db_prop.address = prop.address
    db_prop.land_area_acres = prop.land_area_acres
    db_prop.built_up_sqft = prop.built_up_sqft
    db_prop.tenure = prop.tenure
    db_prop.occupancy_status = prop.occupancy_status
    db_prop.furnishing = prop.furnishing
    
    db_prop.bedrooms = prop.bedrooms
    db_prop.bathrooms = prop.bathrooms
    db_prop.car_parks = prop.car_parks
    
    db_prop.amenities = prop.amenities
    db_prop.facilities = prop.facilities
    
    db_prop.is_bumi_lot = prop.is_bumi_lot
    db_prop.year_built = prop.year_built
    db_prop.developer = prop.developer
    
    db.commit()
    db.refresh(db_prop)
    return db_prop

@router.delete("/{property_id}")
def delete_property(property_id: str, db: Session = Depends(get_db)):
    db_prop = db.query(Property).filter(Property.id == property_id).first()
    if not db_prop:
        return {"error": "Property not found"}
        
    db.delete(db_prop)
    db.commit()
    return {"message": "Property deleted successfully"}

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

@router.post("/seed-defaults")
def seed_default_properties(db: Session = Depends(get_db)):
    """
    Seeds initial BentongLand property listings if database is empty.
    """
    from scripts.seed_properties import seed_properties
    seed_properties()
    return {"status": "success", "count": db.query(Property).count()}


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

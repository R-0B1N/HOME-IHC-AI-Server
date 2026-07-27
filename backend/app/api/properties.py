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
    name: str
    description: str = ""
    price: float = 0.0
    category: str = ""
    property_type: str = "general"
    location: str = ""
    acres: float = 0.0
    title_type: str = ""
    area: str = ""
    city: str = ""
    state: str = ""
    status: str = "Available"

@router.get("")
def read_properties(skip: int = 0, limit: int = 500, db: Session = Depends(get_db)):
    properties = db.query(Property).order_by(Property.id.desc()).offset(skip).limit(limit).all()
    return properties

@router.post("")
def create_property(prop: PropertyCreate, db: Session = Depends(get_db)):
    db_prop = Property(
        name=prop.name,
        description=prop.description,
        price=prop.price,
        category=prop.category,
        property_type=prop.property_type,
        location=prop.location,
        acres=prop.acres,
        title_type=prop.title_type,
        area=prop.area,
        city=prop.city,
        state=prop.state,
        status=prop.status
    )
    db.add(db_prop)
    db.commit()
    db.refresh(db_prop)
    return db_prop

@router.put("/{property_id}")
def update_property(property_id: int, prop: PropertyCreate, db: Session = Depends(get_db)):
    db_prop = db.query(Property).filter(Property.id == property_id).first()
    if not db_prop:
        return {"error": "Property not found"}
        
    db_prop.name = prop.name
    db_prop.description = prop.description
    db_prop.price = prop.price
    db_prop.category = prop.category
    db_prop.property_type = prop.property_type
    db_prop.location = prop.location
    db_prop.acres = prop.acres
    db_prop.title_type = prop.title_type
    db_prop.area = prop.area
    db_prop.city = prop.city
    db_prop.state = prop.state
    db_prop.status = prop.status
    
    db.commit()
    db.refresh(db_prop)
    return db_prop

@router.delete("/{property_id}")
def delete_property(property_id: int, db: Session = Depends(get_db)):
    db_prop = db.query(Property).filter(Property.id == property_id).first()
    if not db_prop:
        return {"error": "Property not found"}
        
    db.delete(db_prop)
    db.commit()
    return {"message": "Property deleted successfully"}

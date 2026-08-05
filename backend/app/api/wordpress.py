from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Property
import uuid

router = APIRouter()

@router.post("/property")
async def sync_wordpress_property(request: Request, db: Session = Depends(get_db)):
    """
    Webhook receiver for WordPress.
    Expected JSON payload (can be customized on WP side):
    {
        "source_url": "https://bentongland.com.my/...",
        "title": "Property Title",
        "description": "Property description...",
        "status": "For Sale",
        "category": ["Industrial Land"],
        "price": 1500000.0,
        "state": "Perak",
        "city": "Teluk Intan",
        "acres": 2.5
    }
    """
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    title = data.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Property title is required")

    # Check if a property with this title/url already exists
    existing = db.query(Property).filter(Property.title == title).first()
    
    if existing:
        # Update existing property
        existing.search_corpus_markdown = data.get("description", existing.search_corpus_markdown)
        existing.asking_price_myr = data.get("price", existing.asking_price_myr)
        existing.listing_status = data.get("status", existing.listing_status)
        existing.property_category = data.get("category", existing.property_category)
        existing.land_area_acres = data.get("acres", existing.land_area_acres)
        existing.source_url = data.get("source_url", existing.source_url)
        db.commit()
        db.refresh(existing)
        return {"status": "success", "message": "Property updated", "id": existing.id}
    else:
        # Create new property
        new_property = Property(
            id=str(uuid.uuid4()),
            title=title,
            search_corpus_markdown=data.get("description", ""),
            asking_price_myr=data.get("price", 0.0),
            listing_status=data.get("status", "Available"),
            property_category=data.get("category", []),
            state=data.get("state", ""),
            city=data.get("city", ""),
            land_area_acres=data.get("acres", 0.0),
            source_url=data.get("source_url", "")
        )
        db.add(new_property)
        db.commit()
        db.refresh(new_property)
        return {"status": "success", "message": "Property created", "id": new_property.id}

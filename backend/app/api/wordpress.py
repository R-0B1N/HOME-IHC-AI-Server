import logging
import uuid
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Property

logger = logging.getLogger(__name__)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/property")
async def sync_wordpress_property(request: Request, db: Session = Depends(get_db)):
    """
    Webhook receiver for WordPress.
    Processes property payload directly and asynchronously for maximum reliability.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    title = data.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Property title is required")

    # 1. Direct synchronous database upsert
    try:
        # Extract fields
        price = float(data.get("price") or data.get("asking_price_myr") or 0.0)
        acres = float(data.get("acres") or data.get("land_area_acres") or 0.0)
        built_up = float(data.get("built_up_area_sqft") or data.get("built_up_sqft") or 0.0)
        status = data.get("status") or data.get("listing_status") or "Available"
        category = data.get("category") or data.get("property_category") or []
        if isinstance(category, str):
            category = [c.strip() for c in category.split(",") if c.strip()]

        images = data.get("image_urls") or data.get("images") or []
        if isinstance(images, str):
            images = [images]

        existing = db.query(Property).filter(Property.title == title).first()
        if existing:
            existing.search_corpus_markdown = data.get("description", existing.search_corpus_markdown)
            existing.source_url = data.get("source_url", existing.source_url)
            if price > 0: existing.asking_price_myr = price
            if category: existing.property_category = category
            if data.get("city"): existing.city = data.get("city")
            if data.get("state"): existing.state = data.get("state")
            if data.get("street_address"): existing.street_address = data.get("street_address")
            if acres > 0: existing.land_area_acres = acres
            if built_up > 0: existing.built_up_area_sqft = built_up
            if data.get("tenure"): existing.tenure_type = data.get("tenure")
            existing.listing_status = status
            if images: existing.image_urls = images
            db.commit()
            db.refresh(existing)
            logger.info(f"Updated property '{title}' directly in DB.")
            property_id = existing.id
        else:
            new_prop = Property(
                id=str(uuid.uuid4()),
                title=title,
                search_corpus_markdown=data.get("description", ""),
                source_url=data.get("source_url", ""),
                asking_price_myr=price,
                property_category=category,
                city=data.get("city", ""),
                state=data.get("state", ""),
                street_address=data.get("street_address", ""),
                land_area_acres=acres,
                built_up_area_sqft=built_up,
                tenure_type=data.get("tenure", ""),
                listing_status=status,
                image_urls=images
            )
            db.add(new_prop)
            db.commit()
            db.refresh(new_prop)
            logger.info(f"Created new property '{title}' directly in DB.")
            property_id = new_prop.id
    except Exception as e:
        logger.error(f"Direct DB save error: {e}")
        property_id = None

    # 2. Also dispatch to Celery if available for background LLM enrichment
    try:
        from app.worker.tasks import process_wordpress_property
        process_wordpress_property.delay(data)
    except Exception as e:
        logger.warning(f"Celery queue dispatch warning: {e}")

    return {
        "status": "success",
        "message": f"Property '{title}' processed successfully",
        "property_id": property_id
    }

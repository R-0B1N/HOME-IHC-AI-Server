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

    from app.worker.tasks import process_wordpress_property
    
    # Send to Celery task for AI extraction
    process_wordpress_property.delay(data)
    
    return {"status": "success", "message": "Property received and queued for processing"}

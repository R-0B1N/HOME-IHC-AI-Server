from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, ViewingAppointment
from pydantic import BaseModel, ConfigDict
from typing import Dict, Any, Optional, List
from app.services.viewing_service import update_viewing_record
import uuid

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UpdateViewingRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    document_data: Dict[str, Any]
    no_of_pax: Optional[str] = None
    car_plate: Optional[str] = None
    status: Optional[str] = None

class ViewingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    form_no: str
    customer_id: str
    property_id: Optional[str] = None
    conversation_id: Optional[int] = None
    status: str
    appointment_date: Optional[str] = None
    no_of_pax: Optional[str] = None
    car_plate: Optional[str] = None
    document_data: Optional[Dict[str, Any]] = None
    pdf_path: Optional[str] = None
    docx_path: Optional[str] = None
    created_at: Optional[str] = None

@router.get("", response_model=List[ViewingResponse])
def list_viewings(customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    """List all scheduled viewing appointments."""
    query = db.query(ViewingAppointment)
    if customer_id:
        query = query.filter(ViewingAppointment.customer_id == customer_id)
    viewings = query.order_by(ViewingAppointment.created_at.desc()).all()
    return [
        {
            "id": str(v.id),
            "form_no": v.form_no,
            "customer_id": v.customer_id,
            "property_id": str(v.property_id) if v.property_id else None,
            "conversation_id": v.conversation_id,
            "status": v.status,
            "appointment_date": v.appointment_date.isoformat() if v.appointment_date else None,
            "no_of_pax": v.no_of_pax,
            "car_plate": v.car_plate,
            "document_data": v.document_data,
            "pdf_path": v.pdf_path,
            "docx_path": v.docx_path,
            "created_at": v.created_at.isoformat() if v.created_at else None
        }
        for v in viewings
    ]

@router.get("/{viewing_id}", response_model=ViewingResponse)
def get_viewing(viewing_id: str, db: Session = Depends(get_db)):
    """Get details of a specific viewing appointment."""
    try:
        uid = uuid.UUID(viewing_id)
        v = db.query(ViewingAppointment).filter(ViewingAppointment.id == uid).first()
    except ValueError:
        v = db.query(ViewingAppointment).filter(ViewingAppointment.form_no == viewing_id).first()
        
    if not v:
        raise HTTPException(status_code=404, detail="Viewing appointment not found")
        
    return {
        "id": str(v.id),
        "form_no": v.form_no,
        "customer_id": v.customer_id,
        "property_id": str(v.property_id) if v.property_id else None,
        "conversation_id": v.conversation_id,
        "status": v.status,
        "appointment_date": v.appointment_date.isoformat() if v.appointment_date else None,
        "no_of_pax": v.no_of_pax,
        "car_plate": v.car_plate,
        "document_data": v.document_data,
        "pdf_path": v.pdf_path,
        "docx_path": v.docx_path,
        "created_at": v.created_at.isoformat() if v.created_at else None
    }

@router.put("/{viewing_id}")
def update_viewing(viewing_id: str, request: UpdateViewingRequest, db: Session = Depends(get_db)):
    """Update viewing document and regenerate documents."""
    try:
        payload = request.document_data
        if request.no_of_pax is not None:
            payload["no_of_pax"] = request.no_of_pax
        if request.car_plate is not None:
            payload["car_plate"] = request.car_plate
        if request.status is not None:
            payload["status"] = request.status
            
        viewing = update_viewing_record(db, viewing_id, payload)
        return {
            "status": "success",
            "viewing_id": str(viewing.id),
            "form_no": viewing.form_no,
            "pdf_path": viewing.pdf_path,
            "docx_path": viewing.docx_path
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

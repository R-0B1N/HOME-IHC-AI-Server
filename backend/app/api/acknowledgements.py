"""
Viewing Acknowledgement Forms REST API endpoints.
Provides CRUD and lifecycle operations for Customer Property Viewing Acknowledgements.
"""

import os
import datetime
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict

from app.db.models import SessionLocal, AcknowledgementForm, Customer, Property
from app.services.viewing_service import (
    create_and_dispatch_viewing_form,
    update_viewing_form_status,
    reschedule_viewing_form
)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class GenerateViewingFormRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    customer_id: str
    property_id: Optional[str] = None
    viewing_date: Optional[datetime.datetime] = None
    conversation_id: Optional[int] = None
    customer_name: Optional[str] = None
    phone_number: Optional[str] = None
    no_of_pax: str = "1"
    remarks: Optional[str] = None
    dispatch_to_customer: bool = False


class UpdateStatusRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    status: str
    notes: Optional[str] = None


class RescheduleViewingRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    new_viewing_date: datetime.datetime
    notes: Optional[str] = None
    regenerate_document: bool = True


@router.get("")
def list_acknowledgement_forms(
    customer_id: Optional[str] = None,
    property_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    List viewing acknowledgement records, sorted latest first.
    """
    query = db.query(AcknowledgementForm)
    if customer_id:
        clean_c = customer_id.replace("+", "").strip()
        query = query.filter((AcknowledgementForm.customer_id == customer_id) | (AcknowledgementForm.customer_id.like(f"%{clean_c}%")))
    if property_id:
        query = query.filter(AcknowledgementForm.property_id == property_id)
    if status:
        query = query.filter(AcknowledgementForm.status == status.upper())

    total = query.count()
    records = query.order_by(AcknowledgementForm.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for r in records:
        items.append({
            "id": r.id,
            "form_no": r.form_no,
            "customer_id": r.customer_id,
            "property_id": str(r.property_id) if r.property_id else None,
            "viewing_date": r.viewing_date.isoformat() if r.viewing_date else None,
            "status": r.status,
            "file_path": r.file_path,
            "document_hash": r.document_hash,
            "metadata_json": r.metadata_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        })

    return {"total": total, "items": items}


@router.get("/{form_id}")
def get_acknowledgement_form(form_id: str, db: Session = Depends(get_db)):
    """
    Retrieve single acknowledgement record by integer ID or unique form_no.
    """
    form = None
    if form_id.isdigit():
        form = db.query(AcknowledgementForm).filter(AcknowledgementForm.id == int(form_id)).first()
    if not form:
        form = db.query(AcknowledgementForm).filter(AcknowledgementForm.form_no == form_id).first()

    if not form:
        raise HTTPException(status_code=404, detail=f"Acknowledgement form '{form_id}' not found.")

    return {
        "id": form.id,
        "form_no": form.form_no,
        "customer_id": form.customer_id,
        "property_id": str(form.property_id) if form.property_id else None,
        "viewing_date": form.viewing_date.isoformat() if form.viewing_date else None,
        "status": form.status,
        "file_path": form.file_path,
        "document_hash": form.document_hash,
        "metadata_json": form.metadata_json,
        "created_at": form.created_at.isoformat() if form.created_at else None,
        "updated_at": form.updated_at.isoformat() if form.updated_at else None
    }


@router.post("/generate")
def generate_acknowledgement_form(req: GenerateViewingFormRequest, db: Session = Depends(get_db)):
    """
    Generates a Viewing Acknowledgement form, stores it in the database,
    and optionally dispatches it to the customer via WhatsApp.
    """
    try:
        res = create_and_dispatch_viewing_form(
            customer_id=req.customer_id,
            property_id=req.property_id,
            viewing_date=req.viewing_date,
            conversation_id=req.conversation_id,
            customer_name=req.customer_name,
            phone_number=req.phone_number,
            no_of_pax=req.no_of_pax,
            remarks=req.remarks,
            dispatch_to_customer=req.dispatch_to_customer,
            db=db
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{form_id}/status")
def patch_acknowledgement_status(form_id: str, req: UpdateStatusRequest, db: Session = Depends(get_db)):
    """
    Update the lifecycle status of a viewing form: PENDING_SIGNATURE, SIGNED, CANCELLED.
    """
    try:
        return update_viewing_form_status(form_identifier=form_id, new_status=req.status, notes=req.notes, db=db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{form_id}/reschedule")
def patch_reschedule_viewing(form_id: str, req: RescheduleViewingRequest, db: Session = Depends(get_db)):
    """
    Reschedule an existing viewing date and regenerate document with updated hash.
    """
    try:
        return reschedule_viewing_form(
            form_identifier=form_id,
            new_viewing_date=req.new_viewing_date,
            notes=req.notes,
            regenerate_document=req.regenerate_document,
            db=db
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{form_id}/download")
def download_acknowledgement_document(form_id: str, db: Session = Depends(get_db)):
    """
    Download the generated viewing acknowledgement file (PDF or DOCX).
    """
    form = None
    if form_id.isdigit():
        form = db.query(AcknowledgementForm).filter(AcknowledgementForm.id == int(form_id)).first()
    if not form:
        form = db.query(AcknowledgementForm).filter(AcknowledgementForm.form_no == form_id).first()

    if not form or not form.file_path or not os.path.exists(form.file_path):
        raise HTTPException(status_code=404, detail="Acknowledgement document file not found on server.")

    filename = os.path.basename(form.file_path)
    media_type = "application/pdf" if filename.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path=form.file_path, filename=filename, media_type=media_type)

"""
Viewing Service for Home IHC AI CRM.
Handles autonomous scheduling of onsite viewings, ViewingAcknowledgementEngine generation,
secure local database persistence in `acknowledgement_forms`, WhatsApp document dispatching,
and viewing lifecycle state synchronization (PENDING_SIGNATURE, SIGNED, CANCELLED).
"""

import os
import hashlib
import logging
import datetime
import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.db.models import SessionLocal, AcknowledgementForm, ViewingAppointment, Customer, Property
from app.services.acknowledgement import (
    ViewingAcknowledgementEngine,
    get_sample_acknowledgement_data,
    get_blank_acknowledgement_data,
    DEFAULT_OUTPUT_DIR
)
from app.services.chatwoot import send_message_with_attachment, send_private_note

logger = logging.getLogger(__name__)


def compute_file_sha256(filepath: str) -> Optional[str]:
    """Calculates SHA-256 hash of a file for tamper-evident tracking."""
    if not filepath or not os.path.exists(filepath):
        return None
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_next_form_number(db: Session) -> str:
    """
    Generates the next unique 4-digit or prefixed form number for viewing acknowledgements.
    Safely increments from the highest existing form number, defaulting from '0190'.
    """
    try:
        # Check both acknowledgement_forms and viewing_appointments
        last_form = db.query(AcknowledgementForm.form_no).order_by(AcknowledgementForm.id.desc()).first()
        if not last_form:
            last_form = db.query(ViewingAppointment.form_no).order_by(ViewingAppointment.created_at.desc()).first()
        
        if last_form and last_form[0]:
            raw_str = last_form[0].strip()
            # Extract digits if pure number or prefixed
            digits = "".join(filter(str.isdigit, raw_str))
            if digits:
                next_num = int(digits) + 1
                return f"{next_num:04d}"
        
        # Default starting point if no records exist yet
        return "0191"
    except Exception as e:
        logger.warning(f"Error calculating next form number: {e}. Falling back to timestamp format.")
        return f"FORM-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


def build_acknowledgement_payload(
    form_no: str,
    customer: Optional[Customer],
    property_obj: Optional[Property],
    viewing_date: Optional[datetime.datetime] = None,
    customer_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    no_of_pax: str = "1",
    remarks: Optional[str] = None,
    staff_name: str = "Irene Leong / Leong Chu Ping"
) -> Dict[str, Any]:
    """
    Populates standard 22-field payload for ViewingAcknowledgementEngine.
    """
    base_data = get_blank_acknowledgement_data(form_no=form_no)
    now = datetime.datetime.utcnow()
    
    # 1. Core Header
    base_data["form_no"] = form_no
    base_data["date"] = now.strftime("%d.%m.%Y")
    base_data["called_in_date"] = now.strftime("%d-%m-%Y")
    base_data["staff_name"] = staff_name
    base_data["assigned_to"] = "Direct Seller"
    base_data["no_of_pax"] = str(no_of_pax)

    # 2. Customer Particulars
    final_cust_name = customer_name or (customer.contact_name if customer else "") or "Customer"
    final_phone = phone_number or (customer.id if customer else "")
    base_data["customer_name"] = final_cust_name
    base_data["customer_signer"] = final_cust_name
    base_data["phone"] = final_phone
    
    if customer and customer.metadata_json:
        meta = customer.metadata_json
        if meta.get("company_name"):
            base_data["company_name"] = meta["company_name"]
            base_data["customer_signer"] = f"{final_cust_name} on behalf of {meta['company_name']}"
        if meta.get("company_reg_no"):
            base_data["company_reg_no"] = meta["company_reg_no"]
        if meta.get("company_address"):
            base_data["company_address"] = meta["company_address"]
        if meta.get("car_plate"):
            base_data["car_plate"] = meta["car_plate"]
        if meta.get("budget"):
            base_data["customer_request"] = f"Budget: {meta['budget']}"
        if meta.get("location"):
            base_data["target_location"] = meta["location"]

    # 3. Property Details
    viewing_date_str = viewing_date.strftime("%d.%m.%Y %I:%M %p") if viewing_date else now.strftime("%d.%m.%Y")
    if property_obj:
        price_str = f"Selling Price:\nRM {property_obj.asking_price_myr:,.0f}" if property_obj.asking_price_myr else "Price on inquiry"
        loc_str = property_obj.city or property_obj.state or "Pahang"
        base_data["target_location"] = loc_str
        
        desc_bullets = []
        if property_obj.tenure_type:
            desc_bullets.append(f"• {property_obj.tenure_type} Title")
        if property_obj.land_area_acres:
            desc_bullets.append(f"• {property_obj.land_area_acres} Acres")
        if property_obj.key_highlights:
            desc_bullets.extend([f"• {h}" for h in property_obj.key_highlights[:2]])
        
        base_data["properties_viewed"] = [
            {
                "no": "1.",
                "details": f"{property_obj.title}\n{loc_str}",
                "date": viewing_date_str,
                "price": price_str,
                "description": "\n".join(desc_bullets) if desc_bullets else "• Comprehensive inspection of premises"
            }
        ]
        if property_obj.property_category:
            base_data["property_types"] = [property_obj.property_category] if isinstance(property_obj.property_category, str) else list(property_obj.property_category)
    else:
        # Fallback to provided remarks
        if base_data.get("properties_viewed"):
            base_data["properties_viewed"][0]["date"] = viewing_date_str

    if remarks:
        base_data["remarks"] = remarks

    return base_data


def create_and_dispatch_viewing_form(
    customer_id: str,
    property_id: Optional[Any] = None,
    viewing_date: Optional[datetime.datetime] = None,
    conversation_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    no_of_pax: str = "1",
    remarks: Optional[str] = None,
    dispatch_to_customer: bool = True,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Core Autonomous Viewing Workflow:
    1. Generates unique form_no and prepares 22-field payload.
    2. Populates and renders DOCX and PDF using ViewingAcknowledgementEngine.
    3. Calculates SHA-256 document hash.
    4. Persists record securely to `acknowledgement_forms` (status='PENDING_SIGNATURE').
    5. Dispatches PDF attachment to customer via WhatsApp (Chatwoot API).
    6. Posts private audit note in Chatwoot.
    """
    close_db_on_exit = False
    if db is None:
        db = SessionLocal()
        close_db_on_exit = True

    try:
        # 1. Fetch Customer and Property records
        customer = db.query(Customer).filter(
            (Customer.id == customer_id) | 
            (Customer.id.like(f"%{customer_id.replace('+', '')}%"))
        ).first()
        
        prop_record = None
        prop_uuid = None
        if property_id:
            try:
                if isinstance(property_id, str):
                    prop_uuid = uuid.UUID(property_id)
                else:
                    prop_uuid = property_id
                prop_record = db.query(Property).filter(Property.id == prop_uuid).first()
            except Exception as pe:
                logger.warning(f"Could not resolve property by ID {property_id}: {pe}")

        # 2. Form Number & Data Payload
        form_no = get_next_form_number(db)
        engine = ViewingAcknowledgementEngine(output_dir=DEFAULT_OUTPUT_DIR)
        
        payload_data = build_acknowledgement_payload(
            form_no=form_no,
            customer=customer,
            property_obj=prop_record,
            viewing_date=viewing_date,
            customer_name=customer_name,
            phone_number=phone_number or customer_id,
            no_of_pax=no_of_pax,
            remarks=remarks
        )

        # 3. Generate Document (DOCX + PDF)
        gen_result = engine.generate(data=payload_data)
        docx_path = gen_result["docx_path"]
        pdf_path = gen_result.get("pdf_path")
        
        # Primary file to store and dispatch
        primary_file = pdf_path if pdf_path and os.path.exists(pdf_path) else docx_path
        doc_hash = compute_file_sha256(primary_file)

        # 4. Persist in acknowledgement_forms table
        ack_record = AcknowledgementForm(
            form_no=form_no,
            customer_id=customer.id if customer else customer_id,
            property_id=prop_uuid,
            viewing_date=viewing_date or datetime.datetime.utcnow(),
            status="PENDING_SIGNATURE",
            file_path=primary_file,
            document_hash=doc_hash,
            metadata_json={
                "conversation_id": conversation_id,
                "docx_path": docx_path,
                "pdf_path": pdf_path,
                "no_of_pax": no_of_pax,
                "remarks": remarks,
                "customer_name": payload_data.get("customer_name"),
                "phone": payload_data.get("phone"),
                "property_title": prop_record.title if prop_record else None
            }
        )
        db.add(ack_record)
        db.commit()
        db.refresh(ack_record)
        logger.info(f"Persisted AcknowledgementForm #{ack_record.id} (Form No: {form_no}) to database.")

        # 5. WhatsApp Document Dispatch
        dispatch_status = "skipped"
        if dispatch_to_customer and conversation_id and os.path.exists(primary_file):
            try:
                mime = "application/pdf" if primary_file.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                filename = os.path.basename(primary_file)
                with open(primary_file, "rb") as f:
                    file_bytes = f.read()

                cust_display_name = payload_data.get("customer_name") or "Customer"
                date_display = viewing_date.strftime("%A, %d %B %Y at %I:%M %p") if viewing_date else "the upcoming appointment"
                prop_title = f" for {prop_record.title}" if prop_record else ""
                
                caption = (
                    f"Dear {cust_display_name}, here is your Customer Property Viewing Acknowledgement "
                    f"(Form No: {form_no}){prop_title} scheduled for {date_display}. "
                    f"Please review prior to our appointment. 😊"
                )

                send_message_with_attachment(
                    conversation_id=conversation_id,
                    content=caption,
                    file_name=filename,
                    file_content=file_bytes,
                    content_type=mime
                )
                dispatch_status = "sent"
                logger.info(f"Successfully dispatched viewing acknowledgement {form_no} to conv {conversation_id}")
                
                # Internal private audit note
                send_private_note(
                    conversation_id=conversation_id,
                    content=f"✅ **Autonomous Viewing Form Dispatched to Customer**\n"
                            f"• **Form No**: {form_no}\n"
                            f"• **Status**: PENDING_SIGNATURE\n"
                            f"• **Viewing Date**: {date_display}\n"
                            f"• **SHA-256**: `{doc_hash[:16]}...`\n"
                            f"• **File**: `{filename}`"
                )
            except Exception as dispatch_err:
                logger.error(f"Failed to dispatch viewing form via WhatsApp: {dispatch_err}")
                dispatch_status = f"failed: {dispatch_err}"

        return {
            "status": "success",
            "form_id": ack_record.id,
            "form_no": ack_record.form_no,
            "customer_id": ack_record.customer_id,
            "property_id": str(ack_record.property_id) if ack_record.property_id else None,
            "viewing_date": ack_record.viewing_date.isoformat() if ack_record.viewing_date else None,
            "record_status": ack_record.status,
            "file_path": ack_record.file_path,
            "document_hash": ack_record.document_hash,
            "docx_path": docx_path,
            "pdf_path": pdf_path,
            "dispatch_status": dispatch_status
        }
    except Exception as e:
        logger.error(f"Error in create_and_dispatch_viewing_form: {e}")
        db.rollback()
        raise e
    finally:
        if close_db_on_exit:
            db.close()


def update_viewing_form_status(
    form_identifier: Any,
    new_status: str,
    notes: Optional[str] = None,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Updates the state of a viewing acknowledgement form:
    Allowed states: PENDING_SIGNATURE, SIGNED, CANCELLED
    """
    allowed = {"PENDING_SIGNATURE", "SIGNED", "CANCELLED"}
    status_upper = new_status.upper()
    if status_upper not in allowed:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of: {allowed}")

    close_db_on_exit = False
    if db is None:
        db = SessionLocal()
        close_db_on_exit = True

    try:
        # Resolve by integer id or string form_no
        form = None
        if isinstance(form_identifier, int) or (isinstance(form_identifier, str) and form_identifier.isdigit()):
            form = db.query(AcknowledgementForm).filter(AcknowledgementForm.id == int(form_identifier)).first()
        if not form:
            form = db.query(AcknowledgementForm).filter(AcknowledgementForm.form_no == str(form_identifier)).first()

        if not form:
            raise LookupError(f"AcknowledgementForm '{form_identifier}' not found.")

        old_status = form.status
        form.status = status_upper
        form.updated_at = datetime.datetime.utcnow()

        meta = dict(form.metadata_json or {})
        history = meta.setdefault("status_history", [])
        history.append({
            "from_status": old_status,
            "to_status": status_upper,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "notes": notes
        })
        form.metadata_json = meta
        
        db.commit()
        db.refresh(form)
        logger.info(f"Updated Viewing Form {form.form_no} status: {old_status} -> {status_upper}")

        # If conversation_id present in metadata, notify staff via private note
        convo_id = meta.get("conversation_id")
        if convo_id:
            try:
                send_private_note(
                    convo_id,
                    f"📋 **Viewing Form {form.form_no} Status Updated**\n"
                    f"• Previous: `{old_status}`\n"
                    f"• New Status: **{status_upper}**\n"
                    f"• Notes: {notes or 'No notes provided'}"
                )
            except Exception as note_err:
                logger.warning(f"Could not post status private note: {note_err}")

        return {
            "status": "success",
            "form_id": form.id,
            "form_no": form.form_no,
            "previous_status": old_status,
            "current_status": form.status,
            "updated_at": form.updated_at.isoformat()
        }
    finally:
        if close_db_on_exit:
            db.close()


def reschedule_viewing_form(
    form_identifier: Any,
    new_viewing_date: datetime.datetime,
    notes: Optional[str] = None,
    regenerate_document: bool = True,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Reschedules an existing viewing appointment, updates database record,
    regenerates document with the new timestamp, updates file hash, and syncs state.
    """
    close_db_on_exit = False
    if db is None:
        db = SessionLocal()
        close_db_on_exit = True

    try:
        form = None
        if isinstance(form_identifier, int) or (isinstance(form_identifier, str) and form_identifier.isdigit()):
            form = db.query(AcknowledgementForm).filter(AcknowledgementForm.id == int(form_identifier)).first()
        if not form:
            form = db.query(AcknowledgementForm).filter(AcknowledgementForm.form_no == str(form_identifier)).first()

        if not form:
            raise LookupError(f"AcknowledgementForm '{form_identifier}' not found.")

        old_date = form.viewing_date
        form.viewing_date = new_viewing_date
        form.updated_at = datetime.datetime.utcnow()

        meta = dict(form.metadata_json or {})
        reschedule_log = meta.setdefault("reschedule_history", [])
        reschedule_log.append({
            "from_date": old_date.isoformat() if old_date else None,
            "to_date": new_viewing_date.isoformat(),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "notes": notes
        })

        if regenerate_document:
            customer = db.query(Customer).filter(Customer.id == form.customer_id).first()
            prop_obj = db.query(Property).filter(Property.id == form.property_id).first() if form.property_id else None
            
            engine = ViewingAcknowledgementEngine(output_dir=DEFAULT_OUTPUT_DIR)
            payload = build_acknowledgement_payload(
                form_no=form.form_no,
                customer=customer,
                property_obj=prop_obj,
                viewing_date=new_viewing_date,
                customer_name=meta.get("customer_name"),
                phone_number=meta.get("phone"),
                no_of_pax=meta.get("no_of_pax", "1"),
                remarks=f"Rescheduled viewing. {notes or ''}".strip()
            )
            gen = engine.generate(data=payload)
            primary = gen.get("pdf_path") if gen.get("pdf_path") and os.path.exists(gen.get("pdf_path")) else gen["docx_path"]
            form.file_path = primary
            form.document_hash = compute_file_sha256(primary)
            meta["docx_path"] = gen["docx_path"]
            meta["pdf_path"] = gen.get("pdf_path")

        form.metadata_json = meta
        db.commit()
        db.refresh(form)
        logger.info(f"Rescheduled Viewing Form {form.form_no} to {new_viewing_date}")

        return {
            "status": "success",
            "form_id": form.id,
            "form_no": form.form_no,
            "new_viewing_date": form.viewing_date.isoformat(),
            "file_path": form.file_path,
            "document_hash": form.document_hash,
            "updated_at": form.updated_at.isoformat()
        }
    finally:
        if close_db_on_exit:
            db.close()

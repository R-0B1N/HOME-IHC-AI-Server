"""
Enterprise Document Streaming and Inline Viewing API Router.
Provides direct inline PDF/DOCX delivery for Chatwoot mobile and web viewers,
preventing mobile redirect failures and 302 download aborts.
"""

import os
import io
import logging
import requests
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db.models import SessionLocal, AcknowledgementForm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["Document Services"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/view/{document_identifier}")
def view_document_inline(document_identifier: str, db: Session = Depends(get_db)):
    """
    Streams the requested document inline (Content-Disposition: inline) so that mobile
    Chatwoot in-app WebViews and mobile browsers render the PDF directly without redirect errors.
    Supports lookup by document_hash, form_no, or primary key.
    """
    form = None
    if document_identifier.isdigit():
        form = db.query(AcknowledgementForm).filter(AcknowledgementForm.id == int(document_identifier)).first()
    if not form:
        form = db.query(AcknowledgementForm).filter(
            (AcknowledgementForm.document_hash == document_identifier) | 
            (AcknowledgementForm.form_no == document_identifier)
        ).first()

    file_path = None
    if form and form.file_path and os.path.exists(form.file_path):
        file_path = form.file_path
    else:
        # Check standard output directories
        possible_dirs = [
            "/app/data/output/acknowledgements",
            "data/output/acknowledgements",
            "/app/data/output/reports",
            "data/output/reports"
        ]
        for pdir in possible_dirs:
            if not os.path.exists(pdir):
                continue
            for f in os.listdir(pdir):
                if document_identifier in f:
                    candidate = os.path.join(pdir, f)
                    if os.path.isfile(candidate):
                        file_path = candidate
                        break
            if file_path:
                break

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Document '{document_identifier}' not found on server.")

    filename = os.path.basename(file_path)
    media_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=86400"
    }

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers=headers
    )


@router.get("/proxy")
def proxy_document_inline(url: str = Query(..., description="Target document URL to stream inline")):
    """
    Proxies an external or Chatwoot attachment URL and serves it with inline headers.
    Solves mobile app PDF viewer 302 redirect incompatibilities.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid document URL scheme.")

    try:
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "application/pdf")
        filename = "document.pdf"
        if "filename=" in resp.headers.get("Content-Disposition", ""):
            filename = resp.headers["Content-Disposition"].split("filename=")[-1].strip('"\' ')
        elif url.split("?")[0].split("/")[-1]:
            filename = url.split("?")[0].split("/")[-1]

        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600"
        }

        return StreamingResponse(
            io.BytesIO(resp.content),
            media_type=content_type,
            headers=headers
        )
    except Exception as e:
        logger.error(f"Failed to proxy document from {url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch document: {str(e)}")

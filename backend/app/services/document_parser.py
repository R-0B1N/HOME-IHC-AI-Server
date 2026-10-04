import logging
import requests
import io
import os
import base64
import re
import json
from typing import Optional, Dict, Any, List

from app.services.document_extractor import extract_real_estate_document_data

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB Safety threshold
MAX_RASTER_SHEETS = 3
TARGET_IMAGE_MAX_DIM = 1024
JPEG_QUALITY = 70


def sniff_is_pdf(
    content: bytes, 
    file_name: str = "", 
    content_type: str = "", 
    extension: str = "", 
    data_url: str = ""
) -> bool:
    """MIME and magic byte sniffer for PDF detection."""
    if content.startswith(b"%PDF-"):
        return True
    if "pdf" in (content_type or "").lower():
        return True
    if (extension or "").lower().strip(".") == "pdf":
        return True
    if (file_name or "").lower().endswith(".pdf"):
        return True
    url_clean = (data_url or "").split("?")[0].lower()
    if url_clean.endswith(".pdf") or "/pdf" in url_clean:
        return True
    return False


def sniff_is_docx(
    content: bytes, 
    file_name: str = "", 
    content_type: str = "", 
    extension: str = "", 
    data_url: str = ""
) -> bool:
    """Sniffer for Word DOCX detection."""
    if content.startswith(b"PK\x03\x04") and (
        "word" in (content_type or "").lower() or 
        (file_name or "").lower().endswith(".docx") or 
        (extension or "").lower().strip(".") in ["docx", "doc"] or
        ".docx" in (data_url or "").lower()
    ):
        return True
    if "wordprocessingml" in (content_type or "").lower() or (file_name or "").lower().endswith(".docx"):
        return True
    return False


def extract_text_from_document(
    data_url: str, 
    file_name: str = "",
    content_type: str = "",
    extension: str = ""
) -> dict:
    """
    Downloads the document from data_url (capped at 100MB) and extracts its text,
    downscaled raster images, and structured real estate schema.
    Supports PDF (.pdf), Word (.docx), and plain text (.txt, .csv).
    Returns {"text": "...", "images": ["base64_string", ...], "structured_data": {...}}
    """
    effective_name = file_name
    if not effective_name and data_url:
        path_part = data_url.split("?")[0].rstrip("/")
        if "/" in path_part:
            effective_name = path_part.split("/")[-1]

    logger.info(f"Downloading document: name='{effective_name}', ext='{extension}', type='{content_type}'")
    result: Dict[str, Any] = {
        "text": "", 
        "images": [], 
        "structured_data": {},
        "file_name": effective_name
    }
    
    try:
        # 1. Download stream with strict 100MB limit
        resp = requests.get(data_url, stream=True, timeout=30)
        resp.raise_for_status()

        # Check declared content-length header
        content_len = resp.headers.get("Content-Length")
        if content_len and int(content_len) > MAX_FILE_BYTES:
            logger.warning(f"File size {content_len} bytes exceeds 100MB limit for {effective_name}.")
            return result

        downloaded_chunks = []
        total_downloaded = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                total_downloaded += len(chunk)
                if total_downloaded > MAX_FILE_BYTES:
                    logger.warning(f"Download aborted: file exceeded 100MB limit ({total_downloaded} bytes).")
                    return result
                downloaded_chunks.append(chunk)

        content = b"".join(downloaded_chunks)

        # 2. Polymorphic Document Processing
        if sniff_is_pdf(content, effective_name, content_type, extension, data_url):
            import fitz  # PyMuPDF
            doc = fitz.open(stream=content, filetype="pdf")
            text_pages = []
            total_chars = 0
            
            for i in range(len(doc)):
                page = doc[i]
                page_text = page.get_text() or ""
                total_chars += len(page_text.strip())
                text_pages.append(page_text)
                
            raw_extracted_text = "\n".join(text_pages).strip()
            result["text"] = raw_extracted_text

            # If document is mostly scanned raster drawings or blueprints (e.g. CAD drawings, land titles)
            if total_chars < 50:
                logger.info(f"PDF has {total_chars} vector chars. Downscaling up to {MAX_RASTER_SHEETS} key sheets.")
                # Select up to MAX_RASTER_SHEETS key sheets (e.g. sheets 0, 1, 2)
                sheet_indices = list(range(min(len(doc), MAX_RASTER_SHEETS)))
                for idx in sheet_indices:
                    page = doc[idx]
                    rect = page.rect
                    max_dim = max(rect.width, rect.height)
                    scale = (TARGET_IMAGE_MAX_DIM / max_dim) if max_dim > TARGET_IMAGE_MAX_DIM else 1.0
                    matrix = fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    img_bytes = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
                    b64_str = base64.b64encode(img_bytes).decode("utf-8")
                    result["images"].append(b64_str)

            # 3. Extract High-Fidelity Real Estate Schema
            try:
                structured_data = extract_real_estate_document_data(
                    text=result["text"],
                    images=result["images"],
                    file_name=effective_name
                )
                result["structured_data"] = structured_data
                
                # If vector text was empty, synthesize comprehensive summary from structured schema
                if len(result["text"].strip()) < 50 and structured_data:
                    summary_parts = []
                    if structured_data.get("document_type"):
                        summary_parts.append(f"Document Type: {structured_data['document_type']}")
                    if structured_data.get("title_numbers"):
                        summary_parts.append(f"Title: {', '.join(structured_data['title_numbers'])}")
                    if structured_data.get("lot_numbers"):
                        summary_parts.append(f"Lots: {', '.join(structured_data['lot_numbers'])}")
                    if structured_data.get("mukim") or structured_data.get("district") or structured_data.get("state"):
                        summary_parts.append(f"Location: Mukim {structured_data.get('mukim')}, Daerah {structured_data.get('district')}, {structured_data.get('state')}")
                    if structured_data.get("land_area_acres") or structured_data.get("land_area_sqft"):
                        summary_parts.append(f"Land Area: {structured_data.get('land_area_acres')} Acres ({structured_data.get('land_area_sqft')} sqft)")
                    if structured_data.get("tenure"):
                        summary_parts.append(f"Tenure: {structured_data['tenure']}")
                    if structured_data.get("category_of_land_use"):
                        summary_parts.append(f"Category: {structured_data['category_of_land_use']}")
                    if structured_data.get("project_title"):
                        summary_parts.append(f"Project: {structured_data['project_title']}")
                    if structured_data.get("building_type"):
                        summary_parts.append(f"Building: {structured_data['building_type']}")
                    if structured_data.get("dining_tables_capacity") or structured_data.get("occupant_load_capacity"):
                        summary_parts.append(f"Capacity: {structured_data.get('dining_tables_capacity')} tables, {structured_data.get('occupant_load_capacity')} pax")
                    if structured_data.get("parking_bays_car"):
                        summary_parts.append(f"Parking: {structured_data.get('parking_bays_car')} bays")
                    if structured_data.get("registered_owner"):
                        summary_parts.append(f"Owner: {structured_data.get('registered_owner')}")
                    if structured_data.get("architect_name"):
                        summary_parts.append(f"Architect: {structured_data.get('architect_name')}")
                    if structured_data.get("road_access_and_landmarks"):
                        summary_parts.append(f"Access/Landmarks: {structured_data.get('road_access_and_landmarks')}")
                    result["text"] = " | ".join(summary_parts)
            except Exception as extract_err:
                logger.error(f"Structured extraction error for {effective_name}: {extract_err}")

        elif sniff_is_docx(content, effective_name, content_type, extension, data_url):
            import docx
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            result["text"] = text.strip()
            
        elif (
            "text" in (content_type or "").lower() 
            or (extension or "").lower() in ["txt", "csv"] 
            or (effective_name or "").lower().endswith((".txt", ".csv"))
        ):
            result["text"] = content.decode("utf-8", errors="replace").strip()
            
        else:
            logger.warning(f"Unsupported document type: {effective_name}. Attempting plain text decoding.")
            result["text"] = content.decode("utf-8", errors="replace").strip()
            
    except Exception as e:
        logger.error(f"Failed to extract document {effective_name}: {e}")
        
    return result

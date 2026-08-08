import logging
import requests
import io

logger = logging.getLogger(__name__)

def extract_text_from_document(data_url: str, file_name: str = "") -> dict:
    """
    Downloads the document from data_url and extracts its text and images.
    Supports PDF (.pdf), Word (.docx), and plain text (.txt, .csv).
    Returns {"text": "...", "images": ["base64_string", ...]}
    """
    logger.info(f"Downloading document: {file_name}")
    result = {"text": "", "images": []}
    try:
        resp = requests.get(data_url, timeout=30)
        resp.raise_for_status()
        
        content = resp.content
        file_name_lower = file_name.lower()
        
        if file_name_lower.endswith(".pdf"):
            import fitz # PyMuPDF
            import base64
            doc = fitz.open(stream=content, filetype="pdf")
            text = ""
            for i in range(len(doc)):
                page = doc[i]
                page_text = page.get_text()
                text += page_text + "\n"
                
                # Rasterize page to image if it's mostly empty (e.g. scanned land title)
                if len(page_text.strip()) < 50:
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("jpeg")
                    result["images"].append(base64.b64encode(img_bytes).decode("utf-8"))
                    
            result["text"] = text.strip()
            
        elif file_name_lower.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            result["text"] = text.strip()
            
        elif file_name_lower.endswith(".txt") or file_name_lower.endswith(".csv"):
            result["text"] = content.decode("utf-8", errors="replace")
            
        else:
            logger.warning(f"Unsupported document type: {file_name}. Treating as plain text fallback.")
            result["text"] = content.decode("utf-8", errors="replace")
            
    except Exception as e:
        logger.error(f"Failed to extract text from document {file_name}: {e}")
        
    return result

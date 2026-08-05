import logging
import requests
import io

logger = logging.getLogger(__name__)

def extract_text_from_document(data_url: str, file_name: str = "") -> str:
    """
    Downloads the document from data_url and extracts its text.
    Supports PDF (.pdf), Word (.docx), and plain text (.txt, .csv).
    """
    logger.info(f"Downloading document: {file_name}")
    try:
        resp = requests.get(data_url, timeout=30)
        resp.raise_for_status()
        
        content = resp.content
        file_name_lower = file_name.lower()
        
        if file_name_lower.endswith(".pdf"):
            import fitz # PyMuPDF
            doc = fitz.open(stream=content, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            return text.strip()
            
        elif file_name_lower.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text.strip()
            
        elif file_name_lower.endswith(".txt") or file_name_lower.endswith(".csv"):
            return content.decode("utf-8", errors="replace")
            
        else:
            logger.warning(f"Unsupported document type: {file_name}. Treating as plain text fallback.")
            return content.decode("utf-8", errors="replace")
            
    except Exception as e:
        logger.error(f"Failed to extract text from document {file_name}: {e}")
        return ""

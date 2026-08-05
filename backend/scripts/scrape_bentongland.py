import sys
import os
import requests
from bs4 import BeautifulSoup
import logging
import json
import re
from typing import Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property
import app.db.models as models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_fields(text: str) -> Dict[str, Any]:
    """Extracts property details from raw text based on Bentongland format."""
    data = {}
    
    # Extract Price
    price_match = re.search(r"RM\s*([\d,]+)", text)
    if price_match:
        try:
            data['price'] = float(price_match.group(1).replace(",", ""))
        except:
            pass

    # Extract Acres
    acres_match = re.search(r"([\d\.]+)\s*(ac|acres)", text, re.IGNORECASE)
    if acres_match:
        try:
            data['acres'] = float(acres_match.group(1))
        except:
            pass

    # Extract Title Type
    title_match = re.search(r"Title Type\s*:\s*([A-Za-z]+)", text, re.IGNORECASE)
    if title_match:
        data['title_type'] = title_match.group(1).strip()

    # Extract Property Category
    cat_match = re.search(r"Property Category\s*:\s*([A-Za-z\s]+?)(?=Property Type|$)", text, re.IGNORECASE)
    if cat_match:
        data['category'] = cat_match.group(1).strip()

    # Extract Property Type (For Sale / For Rent)
    type_match = re.search(r"Property Type\s*:\s*(For Sale|For Rent)", text, re.IGNORECASE)
    if type_match:
        data['property_type'] = type_match.group(1).strip()

    # Extract Areas
    area_match = re.search(r"Areas\s*:\s*([A-Za-z\s]+?)(?=Cities|$)", text, re.IGNORECASE)
    if area_match:
        data['area'] = area_match.group(1).strip()

    # Extract Cities
    city_match = re.search(r"Cities\s*:\s*([A-Za-z\s]+?)(?=States|$)", text, re.IGNORECASE)
    if city_match:
        data['city'] = city_match.group(1).strip()

    # Extract States
    state_match = re.search(r"States\s*:\s*([A-Za-z\s]+)", text, re.IGNORECASE)
    if state_match:
        data['state'] = state_match.group(1).strip()

    return data

def scrape_and_save():
    url = "https://bentongland.com.my/land/"
    logger.info(f"Fetching {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return

    db = SessionLocal()
    
    try:
        # Find all property articles or fallback divs
        articles = soup.find_all("article")
        if not articles:
            articles = soup.find_all("div", class_=lambda c: c and ("property" in c.lower() or "listing" in c.lower() or "post" in c.lower()))
            
        count = 0
        for article in articles:
            text_content = article.get_text(separator=" ", strip=True)
            
            # Use regex to find potential property title from the beginning of the content or specific tags
            title_elem = article.find(["h2", "h3"]) or article.find("a", class_="elementor-post__title")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown Property"
            
            if title == "Unknown Property":
                # Fallback to lines
                lines = [line.strip() for line in article.get_text(separator="\n", strip=True).split('\n') if line.strip()]
                for line in lines:
                    if len(line) > 15 and ("For Sale" in line or "For Rent" in line or "acres" in line.lower()):
                        title = line.strip()
                        break

            # Extract structured fields
            fields = extract_fields(text_content)
            
            price = fields.get('price', 0.0)
            status = "Available" # Defaulting to Available unless specified otherwise
            if "sold" in text_content.lower():
                status = "Sold"
            elif "pending" in text_content.lower():
                status = "Pending"
                
            # Skip empty or irrelevant articles
            if price == 0.0 and title == "Unknown Property":
                continue
                
            existing = db.query(Property).filter(Property.name == title).first()
            if existing:
                existing.price = price
                existing.status = status
                existing.description = text_content
                existing.category = fields.get('category')
                existing.property_type = fields.get('property_type', existing.property_type)
                existing.acres = fields.get('acres')
                existing.title_type = fields.get('title_type')
                existing.area = fields.get('area')
                existing.city = fields.get('city')
                existing.state = fields.get('state')
                logger.info(f"Updated: {title}")
            else:
                new_prop = Property(
                    name=title,
                    description=text_content,
                    price=price,
                    status=status,
                    location=f"{fields.get('city', '')} {fields.get('state', '')}".strip() or "Unknown",
                    category=fields.get('category'),
                    property_type=fields.get('property_type', 'For Sale'),
                    acres=fields.get('acres'),
                    title_type=fields.get('title_type'),
                    area=fields.get('area'),
                    city=fields.get('city'),
                    state=fields.get('state'),
                    metadata_json={"source_url": url}
                )
                db.add(new_prop)
                logger.info(f"Added: {title}")
            count += 1
            
        db.commit()
        logger.info(f"Scrape completed successfully. Processed {count} properties.")
        
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    scrape_and_save()

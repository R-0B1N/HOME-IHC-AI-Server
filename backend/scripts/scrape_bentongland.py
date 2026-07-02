import sys
import os
import requests
from bs4 import BeautifulSoup
import logging
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property
import app.db.models as models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_and_save():
    url = "https://bentongland.com.my/land/"
    logger.info(f"Fetching {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Typically, property sites use standard classes like 'listing', 'property', or 'item'
    # For bentongland, let's try to extract from the common container
    # Since we can't inspect the exact DOM easily, we look for 'article' tags or divs wrapping the title
    
    db = SessionLocal()
    
    try:
        articles = soup.find_all("article")
        if not articles:
            # Fallback to finding headers wrapped in links, or divs with 'elementor-post'
            articles = soup.find_all("div", class_=lambda c: c and ("property" in c.lower() or "listing" in c.lower() or "post" in c.lower()))
            
        count = 0
        for article in articles:
            text_content = article.get_text(separator="\n", strip=True)
            
            # Simple heuristic parsing based on known content pattern:
            # "RM 2,283,120" / "For Sale" / "8.456 acres Mature Musang King..."
            lines = [line.strip() for line in text_content.split('\n') if line.strip()]
            
            price = 0.0
            status = "Unknown"
            title = "Unknown Property"
            description = ""
            location = "Unknown"
            
            for line in lines:
                if line.startswith("RM"):
                    try:
                        clean_price = line.replace("RM", "").replace(",", "").replace("From", "").strip()
                        price = float(clean_price)
                    except ValueError:
                        pass
                elif line.lower() in ["for sale", "for rent"]:
                    status = line.strip()
                elif len(line) > 15 and "For Sale" in line or "For Rent" in line:
                    if title == "Unknown Property":
                        title = line.strip()
            
            description = "\n".join(lines)
            
            # Skip empty or irrelevant articles
            if price == 0.0 and title == "Unknown Property":
                continue
                
            # Check if property already exists
            existing = db.query(Property).filter(Property.title == title).first()
            if existing:
                existing.price = price
                existing.status = status
                existing.description = description
                logger.info(f"Updated: {title}")
            else:
                new_prop = Property(
                    title=title,
                    description=description,
                    price=price,
                    status=status,
                    location=location,
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

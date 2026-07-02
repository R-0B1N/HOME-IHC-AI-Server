import sys
import os
import requests
from bs4 import BeautifulSoup
import logging

# Add the backend directory to python path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "https://bentongland.com.my/land/"

def scrape_and_seed():
    logger.info(f"Fetching properties from {URL}")
    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {URL}: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Identify property listings based on the typical structure of the site
    # This is a generic approach; might need tuning based on actual HTML classes
    properties_added = 0
    
    db = SessionLocal()
    try:
        # Example selector: might need to be adjusted based on the actual DOM
        # Often properties are in articles, divs with class 'property', 'listing', etc.
        listings = soup.select('div.listing, article.property, div.property-item, .elementor-post')
        
        if not listings:
            logger.warning("No listings found using default selectors. Attempting fallback text parsing...")
            # Fallback: Just look for obvious property-like strings (e.g. titles with RM)
            # A more robust scraper would use Selenium or specific site classes.
            pass
            
        for item in listings:
            title_elem = item.select_one('h2, h3, .title, .elementor-post__title')
            price_elem = item.select_one('.price, .elementor-heading-title')
            desc_elem = item.select_one('.description, .elementor-post__excerpt')
            
            title = title_elem.text.strip() if title_elem else "Unknown Property"
            price_str = price_elem.text.strip() if price_elem else "0"
            desc = desc_elem.text.strip() if desc_elem else ""
            
            # Extract numbers from price_str
            import re
            price_numbers = re.findall(r'\d+', price_str.replace(',', ''))
            price = float(price_numbers[0]) if price_numbers else 0.0
            
            # Simple deduplication check
            exists = db.query(Property).filter(Property.title == title).first()
            if not exists:
                new_prop = Property(
                    title=title,
                    description=desc,
                    price=price,
                    status="Available",
                    location="Bentong"
                )
                db.add(new_prop)
                properties_added += 1
                
        if properties_added > 0:
            db.commit()
            logger.info(f"Successfully seeded {properties_added} properties.")
        else:
            logger.info("No new properties added.")
            
    except Exception as e:
        logger.error(f"Error seeding properties: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    scrape_and_seed()

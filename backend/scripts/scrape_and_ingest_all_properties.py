import os
import sys
import re
import html
import uuid
import logging
import requests
from bs4 import BeautifulSoup

# Ensure backend directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import SessionLocal, Property, engine, run_schema_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WP_API_BASE = "https://bentongland.com.my/wp-json/wp/v2"

def parse_price(text: str) -> float:
    """Extract price in MYR from title or text."""
    if not text:
        return 0.0
    
    # Check for 'RM 1.5M' or 'RM 1.5 Million' or 'RM 1.5 mil'
    m_million = re.search(r'RM\s*([\d\.,]+)\s*(?:million|mil|m\b)', text, re.IGNORECASE)
    if m_million:
        val_str = m_million.group(1).replace(',', '')
        try:
            return float(val_str) * 1_000_000
        except ValueError:
            pass

    # Check for 'RM 850k' or 'RM 850,000'
    m_k = re.search(r'RM\s*([\d\.,]+)\s*(?:k\b|thousand)', text, re.IGNORECASE)
    if m_k:
        val_str = m_k.group(1).replace(',', '')
        try:
            return float(val_str) * 1_000
        except ValueError:
            pass

    # Check for regular RM standard number: 'RM 1,200,000' or 'RM1200000'
    m_std = re.search(r'RM\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_std:
        val_str = m_std.group(1).replace(',', '')
        try:
            val = float(val_str)
            if val > 1000:  # Avoid matching small deposit amounts
                return val
        except ValueError:
            pass

    return 0.0

def parse_acres(text: str) -> float:
    """Extract land area in acres from text."""
    if not text:
        return 0.0
    m = re.search(r'([\d\.]+)\s*(?:acres?|ac\b|ekar)', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_and_ingest_all():
    logger.info("Ensuring database schema migrations are applied...")
    run_schema_migrations(engine)
    logger.info("Starting complete ingestion of all listings from bentongland.com.my WordPress REST API...")
    
    db = SessionLocal()
    total_ingested = 0
    total_updated = 0
    page = 1
    
    try:
        while True:
            url = f"{WP_API_BASE}/land?per_page=100&_embed=1&page={page}"
            logger.info(f"Fetching page {page} from {url}...")
            
            try:
                res = requests.get(url, headers=HEADERS, timeout=15)
                if res.status_code in (400, 404):
                    logger.info("Reached last page of WordPress API.")
                    break
                res.raise_for_status()
                posts = res.json()
            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                break

            if not posts or not isinstance(posts, list) or len(posts) == 0:
                logger.info("No more posts returned.")
                break

            logger.info(f"Processing {len(posts)} posts from page {page}...")

            for post in posts:
                try:
                    title_raw = post.get("title", {}).get("rendered", "")
                    title = html.unescape(title_raw).strip()
                    if not title:
                        continue

                    link = post.get("link", "")
                    content_html = post.get("content", {}).get("rendered", "")
                    
                    # Convert HTML content to plain text / clean description
                    soup = BeautifulSoup(content_html, "html.parser")
                    description = soup.get_text(separator="\n").strip()

                    # Extract Images
                    images = []
                    embedded = post.get("_embedded", {})
                    featured_media = embedded.get("wp:featuredmedia", [])
                    if featured_media and len(featured_media) > 0:
                        feat_url = featured_media[0].get("source_url")
                        if feat_url:
                            images.append(feat_url)
                    
                    # Also find any content images
                    for img in soup.find_all("img"):
                        src = img.get("src")
                        if src and src not in images and not src.endswith("logo.webp") and not src.endswith("favicon.ico"):
                            images.append(src)

                    # Extract Taxonomies from _embedded['wp:term']
                    categories = []
                    city = "Bentong"
                    state = "Pahang"
                    tenure = "Freehold"
                    
                    terms = embedded.get("wp:term", [])
                    for term_group in terms:
                        for term in term_group:
                            tax = term.get("taxonomy")
                            tname = html.unescape(term.get("name", ""))
                            if tax in ("category-land", "category", "land_category"):
                                categories.append(tname)
                            elif tax == "state":
                                state = tname
                            elif tax in ("location-land", "city", "location"):
                                city = tname
                            elif tax in ("title-type", "tenure"):
                                tenure = tname

                    if not categories:
                        if "durian" in title.lower() or "durian" in description.lower():
                            categories.append("Durian Orchard")
                        elif "industrial" in title.lower():
                            categories.append("Industrial Land")
                        elif "commercial" in title.lower() or "shop" in title.lower():
                            categories.append("Commercial Land")
                        elif "house" in title.lower() or "semi-d" in title.lower() or "villa" in title.lower():
                            categories.append("Residential Land")
                        else:
                            categories.append("Agricultural Land")

                    # Check City from title if default
                    for c_candidate in ["Bentong", "Karak", "Raub", "Temerloh", "Bukit Tinggi", "Lanchang", "Mentakab", "Maran", "Kuantan", "Triang", "Kemayan", "Kuala Lipis"]:
                        if c_candidate.lower() in title.lower():
                            city = c_candidate
                            break

                    # Price extraction
                    price = parse_price(title) or parse_price(description)
                    acres = parse_acres(title) or parse_acres(description)

                    # Status
                    status = "Available"
                    if "for rent" in title.lower():
                        status = "For Rent"
                    elif "for sale" in title.lower():
                        status = "For Sale"

                    # Database Upsert
                    existing = db.query(Property).filter((Property.title == title) | (Property.source_url == link)).first()
                    if existing:
                        existing.title = title
                        existing.search_corpus_markdown = description
                        existing.source_url = link
                        if price > 0: existing.asking_price_myr = price
                        if acres > 0: existing.land_area_acres = acres
                        existing.city = city
                        existing.state = state
                        existing.tenure_type = tenure
                        existing.property_category = categories
                        existing.listing_status = status
                        if images: existing.image_urls = images
                        total_updated += 1
                    else:
                        new_prop = Property(
                            id=str(uuid.uuid4()),
                            title=title,
                            search_corpus_markdown=description,
                            source_url=link,
                            asking_price_myr=price,
                            land_area_acres=acres,
                            city=city,
                            state=state,
                            tenure_type=tenure,
                            property_category=categories,
                            listing_status=status,
                            image_urls=images
                        )
                        db.add(new_prop)
                        total_ingested += 1
                except Exception as post_err:
                    logger.error(f"Error parsing post ID {post.get('id')}: {post_err}")

            db.commit()
            logger.info(f"Page {page} committed. Total new so far: {total_ingested}, updated: {total_updated}")
            page += 1

        total_db_count = db.query(Property).count()
        logger.info(f"🎉 INGESTION COMPLETE! New added: {total_ingested}, Updated: {total_updated}. Total properties in database: {total_db_count}")
        return {"status": "success", "new_added": total_ingested, "updated": total_updated, "total_properties": total_db_count}
    except Exception as e:
        logger.error(f"Ingestion fatal error: {e}")
        db.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()

if __name__ == "__main__":
    fetch_and_ingest_all()

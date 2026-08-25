import os
import sys
import re
import html
import uuid
import logging
try:
    import requests
    from bs4 import BeautifulSoup
    from app.db.models import SessionLocal, Property, engine, run_schema_migrations
except ImportError:
    requests = None
    BeautifulSoup = None
    SessionLocal = None
    Property = None
    engine = None
    run_schema_migrations = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WP_API_BASE = "https://bentongland.com.my/wp-json/wp/v2"

def parse_acres(text: str) -> float:
    """Extract land area in acres from text."""
    if not text:
        return 0.0
    m = re.search(r'([\d\.]+)\s*[\-]?\s*(?:acres?|ac\b|ekar)', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0

def parse_listing_financials(title: str, description: str, status: str = "For Sale", acres: float = 0.0) -> dict:
    """
    Robust financial extraction distinguishing Total Asking Price, Price Per Acre,
    Price Per SqFt, and Monthly Rental, while stripping noise (savings, rebates, booking fees).
    """
    result = {
        "asking_price_myr": 0.0,
        "price_per_acre_myr": None,
        "price_per_sqft_myr": None,
        "monthly_rental_income_myr": None
    }
    
    combined = f"{title}\n\n{description}"
    
    # 0. Strip noise phrases (savings, discounts, rebates, booking fees, legal fees)
    noise_stripped = re.sub(
        r'(?:estimated\s*savings?|savings?|discount|rebate|cashback|booking\s*fees?|legal\s*fees?|maintenance\s*fees?|valuation\s*fee)\s*(?:of|is|:)?\s*RM\s*[\d,\.]+(?:\s*[\–\-\sto]+\s*RM\s*[\d,\.]+)?',
        ' ',
        combined,
        flags=re.IGNORECASE
    )

    # 1. Detect Price Per Acre (e.g. 'RM 365,000 / acre', 'RM 365k per acre', 'RM 365,000/ekar')
    m_ppa = re.search(r'RM\s*(?:from\s*)?([\d\.,]+)\s*(k|thousand|mil|million|m)?\s*(?:/|per)\s*(?:acre|ac|ekar)', noise_stripped, re.IGNORECASE)
    if m_ppa:
        val_str = m_ppa.group(1).replace(',', '')
        mult = 1.0
        unit = (m_ppa.group(2) or '').lower()
        if unit in ('k', 'thousand'): mult = 1_000.0
        elif unit in ('mil', 'million', 'm'): mult = 1_000_000.0
        try:
            val = float(val_str) * mult
            if val > 500:
                result["price_per_acre_myr"] = val
        except ValueError:
            pass

    # 2. Detect Price Per SqFt (e.g. 'RM 45 / sqft', 'RM 45 psf', 'RM45/sq.ft')
    m_psf = re.search(r'RM\s*(?:from\s*)?([\d\.,]+)\s*(?:/|per|\b)\s*(?:sqft|sq\.ft|psf)', noise_stripped, re.IGNORECASE)
    if m_psf:
        val_str = m_psf.group(1).replace(',', '')
        try:
            val = float(val_str)
            if 1.0 <= val <= 5000.0:
                result["price_per_sqft_myr"] = val
        except ValueError:
            pass

    # 3. Detect Monthly Rental (e.g. 'RM 12,000 / month', 'Rent: RM 12k', 'Rental RM12,000')
    m_rent = re.search(r'(?:rent|rental|monthly)\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d\.,]+)\s*(k|thousand)?(?:\s*/\s*month|\s*per\s*month)?', noise_stripped, re.IGNORECASE)
    if not m_rent and status == "For Rent":
        m_rent = re.search(r'RM\s*(?:from\s*)?([\d\.,]+)\s*(k|thousand)?\s*(?:/|per)\s*month', noise_stripped, re.IGNORECASE)
    if m_rent:
        val_str = m_rent.group(1).replace(',', '')
        mult = 1.0
        unit = (m_rent.group(2) or '').lower()
        if unit in ('k', 'thousand'): mult = 1_000.0
        try:
            val = float(val_str) * mult
            if val > 100:
                result["monthly_rental_income_myr"] = val
        except ValueError:
            pass

    # 4. Detect Total Price in Millions (e.g. 'RM 3.5M', 'RM 3.5 Million', 'Selling Price: RM 8.5 Million')
    m_mil = re.search(r'(?:total\s*price|price|selling\s*price|asking\s*price|at)?\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d\.,]+)\s*(?:million|mil|m\b)', noise_stripped, re.IGNORECASE)
    if m_mil:
        val_str = m_mil.group(1).replace(',', '')
        try:
            result["asking_price_myr"] = float(val_str) * 1_000_000.0
        except ValueError:
            pass

    # 5. Detect Standard Total Price (e.g. 'Selling Price: From RM 530,000', 'RM From 530,000', 'Price: RM 800,000')
    if result["asking_price_myr"] == 0.0:
        # Check explicit labels first: 'Selling Price: From RM 530,000' or 'Price: RM 800,000'
        m_tot = re.search(r'(?:total\s*price|selling\s*price|asking\s*price|sale\s*price|price)\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d,]+(?:\.\d+)?)', noise_stripped, re.IGNORECASE)
        if not m_tot:
            # Fallback to 'RM From 530,000' or 'RM 530,000'
            m_tot = re.search(r'RM\s*(?:from|approx|about)?\s*([\d,]+(?:\.\d+)?)', noise_stripped, re.IGNORECASE)
            
        if m_tot:
            val_str = m_tot.group(1).replace(',', '')
            try:
                val = float(val_str)
                # Ignore small numbers that could be deposit or per-sqft
                if val > 5000:
                    result["asking_price_myr"] = val
            except ValueError:
                pass

    # 6. Mathematical Reconciliation
    if status == "For Rent":
        result["asking_price_myr"] = 0.0
    else:
        if result["price_per_acre_myr"] and acres and acres > 1.2:
            ppa = result["price_per_acre_myr"]
            ask = result["asking_price_myr"]
            if ask == 0.0 or ask <= (ppa * 1.15):
                result["asking_price_myr"] = round(ppa * acres, 2)
        elif result["asking_price_myr"] > 0 and acres > 0 and not result["price_per_acre_myr"]:
            result["price_per_acre_myr"] = round(result["asking_price_myr"] / acres, 2)

    return result

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

                    # Status
                    status = "Available"
                    if "for rent" in title.lower() or "to let" in title.lower():
                        status = "For Rent"
                    elif "for sale" in title.lower():
                        status = "For Sale"

                    # Acreage and Financials extraction
                    acres = parse_acres(title) or parse_acres(description)
                    financials = parse_listing_financials(title, description, status=status, acres=acres)
                    price = financials["asking_price_myr"]
                    price_per_acre = financials["price_per_acre_myr"]
                    price_per_sqft = financials["price_per_sqft_myr"]
                    monthly_rental = financials["monthly_rental_income_myr"]

                    # Database Upsert
                    existing = db.query(Property).filter((Property.title == title) | (Property.source_url == link)).first()
                    if existing:
                        existing.title = title
                        existing.search_corpus_markdown = description
                        existing.source_url = link
                        existing.asking_price_myr = price
                        if price_per_acre: existing.price_per_acre_myr = price_per_acre
                        if price_per_sqft: existing.price_per_sqft_myr = price_per_sqft
                        if monthly_rental: existing.monthly_rental_income_myr = monthly_rental
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
                            price_per_acre_myr=price_per_acre,
                            price_per_sqft_myr=price_per_sqft,
                            monthly_rental_income_myr=monthly_rental,
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

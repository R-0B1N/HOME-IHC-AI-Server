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
    from app.services.embeddings import generate_property_5_embeddings
except ImportError:
    requests = None
    BeautifulSoup = None
    SessionLocal = None
    Property = None
    engine = None
    run_schema_migrations = None
    generate_property_5_embeddings = lambda p: {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WP_API_BASE = "https://bentongland.com.my/wp-json/wp/v2"

def parse_acres(text: str) -> float:
    """Extract land area in acres from text with decimal precision, hyphenation support, and hectare conversion."""
    if not text:
        return 0.0
    
    # 1. Decimal acres: '4.216 ac', '4.216 Acres', 'Acres : 4.216'
    m_dec = re.search(r'(?:acres?\s*:?\s*)?([\d]+\.[\d]+)\s*(?:[\-\s]*)\s*(?:acres?|ac\b|ekar)', text, re.IGNORECASE)
    if m_dec:
        try:
            return float(m_dec.group(1))
        except ValueError:
            pass

    # 2. Integer or hyphenated acres: '8-ac', '8 ac', '9.7 acres'
    m_int = re.search(r'(?:acres?\s*:?\s*)?([\d\.]+)\s*(?:[\-\s]*)\s*(?:acres?|ac\b|ekar)', text, re.IGNORECASE)
    if m_int:
        try:
            return float(m_int.group(1))
        except ValueError:
            pass

    # 3. Hectares conversion: '1.706 Hectares' -> 1.706 * 2.47105 = 4.216 acres
    m_ha = re.search(r'([\d\.]+)\s*(?:hectares?|ha\b)', text, re.IGNORECASE)
    if m_ha:
        try:
            return round(float(m_ha.group(1)) * 2.47105, 3)
        except ValueError:
            pass

    return 0.0

def parse_listing_financials(title: str, description: str, status: str = "For Sale", acres: float = 0.0, sqft: float = 0.0) -> dict:
    """
    Robust financial extraction distinguishing Total Asking Price, Price Per Acre,
    Price Per SqFt, Monthly Rental, and Implied Yield, while stripping noise (savings, rebates, booking fees).
    """
    result = {
        "asking_price_myr": 0.0,
        "price_per_acre_myr": None,
        "price_per_sqft_myr": None,
        "monthly_rental_income_myr": None,
        "implied_yield_pct": None
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

    # 2. Detect Price Per SqFt (e.g. 'RM 23.50 per sqft', 'RM 45 / sqft', 'RM 45 psf', 'RM45/sq.ft')
    m_psf = re.search(r'RM\s*(?:from\s*)?([\d\.,]+)\s*(?:/|per|\b)\s*(?:sqft|sq\.ft|psf|sq\s*ft)', noise_stripped, re.IGNORECASE)
    if m_psf:
        val_str = m_psf.group(1).replace(',', '')
        try:
            val = float(val_str)
            if 0.5 <= val <= 10000.0:
                result["price_per_sqft_myr"] = val
        except ValueError:
            pass

    # 3. Detect Monthly Rental (e.g. 'RM 12,000 / month', 'Rent: RM 12k', 'Rental RM12,000')
    m_rent = re.search(r'(?:rent|rental|monthly)\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d\.,]+)\s*(k|thousand)?(?:\s*/\s*month|\s*per\s*month)?', noise_stripped, re.IGNORECASE)
    if not m_rent and (status == "For Rent" or "for rent" in title.lower()):
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
    m_mil = re.search(r'(?:total\s*selling\s*price|total\s*price|price|selling\s*price|at)?\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d\.,]+)\s*(?:million|mil|m\b)', noise_stripped, re.IGNORECASE)
    if m_mil:
        val_str = m_mil.group(1).replace(',', '')
        try:
            result["asking_price_myr"] = float(val_str) * 1_000_000.0
        except ValueError:
            pass

    # 5. Detect Standard Total Price (e.g. 'Total Selling Price: RM 4,315,352', 'RM 4,315,352', 'Selling Price: From RM 530,000')
    if result["asking_price_myr"] == 0.0:
        # A. Priority 1: Check explicit labels 'Total Selling Price: RM ...' or 'Total Price: RM ...'
        m_tot_exp = re.search(r'(?:total\s*selling\s*price|total\s*price|total\s*amount)\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d,]+(?:\.\d+)?)', noise_stripped, re.IGNORECASE)
        if m_tot_exp:
            try:
                v = float(m_tot_exp.group(1).replace(',', ''))
                if v > 5000:
                    result["asking_price_myr"] = v
            except ValueError:
                pass

    if result["asking_price_myr"] == 0.0:
        # B. Priority 2: Scan all labeled 'Selling Price: RM ...' candidates > 5000
        cands = re.findall(r'(?:selling\s*price|asking\s*price|sale\s*price|price)\s*(?:is|:|\-)?\s*(?:from\s*)?RM\s*(?:from\s*)?([\d,]+(?:\.\d+)?)', noise_stripped, re.IGNORECASE)
        for c in cands:
            try:
                v = float(c.replace(',', ''))
                if v > 5000:
                    result["asking_price_myr"] = v
                    break
            except ValueError:
                pass

    if result["asking_price_myr"] == 0.0:
        # C. Priority 3: Scan all standalone 'RM ...' candidates > 5000
        all_rm = re.findall(r'RM\s*(?:from|approx|about)?\s*([\d,]+(?:\.\d+)?)', noise_stripped, re.IGNORECASE)
        for c in all_rm:
            try:
                v = float(c.replace(',', ''))
                if v > 5000:
                    result["asking_price_myr"] = v
                    break
            except ValueError:
                pass

    # 6. Detect Estimated ROI / Yield (e.g. 'Estimated ROI: 6% – 7%', 'Yield: 7.5%')
    m_roi = re.search(r'(?:estimated\s*roi|roi|gross\s*yield|yield)\s*(?:is|:|\-)?\s*([\d\.]+)\s*%\s*(?:[\–\-]\s*([\d\.]+)\s*%)?', noise_stripped, re.IGNORECASE)
    if m_roi:
        try:
            low = float(m_roi.group(1))
            high = float(m_roi.group(2)) if m_roi.group(2) else low
            result["implied_yield_pct"] = round((low + high) / 2.0, 2)
        except ValueError:
            pass

    # 7. Mathematical Reconciliation & Fallbacks
    if status == "For Rent" or "for rent" in title.lower():
        result["asking_price_myr"] = 0.0
    else:
        target_acres = acres or 0.0
        target_sqft = sqft or (target_acres * 43560.0 if target_acres else 0.0)

        # If asking price is missing/0, compute from price_per_sqft or price_per_acre
        if result["asking_price_myr"] == 0.0:
            if result["price_per_sqft_myr"] and target_sqft > 100:
                result["asking_price_myr"] = round(result["price_per_sqft_myr"] * target_sqft, 2)
            elif result["price_per_acre_myr"] and target_acres > 0:
                result["asking_price_myr"] = round(result["price_per_acre_myr"] * target_acres, 2)

        # Disambiguate per-acre price mistakenly set as total asking price
        if result["price_per_acre_myr"] and target_acres > 1.2:
            ppa = result["price_per_acre_myr"]
            ask = result["asking_price_myr"]
            if ask <= (ppa * 1.15):
                result["asking_price_myr"] = round(ppa * target_acres, 2)
        elif result["asking_price_myr"] > 0 and target_acres > 0 and not result["price_per_acre_myr"]:
            result["price_per_acre_myr"] = round(result["asking_price_myr"] / target_acres, 2)

        # Derive missing price_per_sqft
        if result["asking_price_myr"] > 0 and not result["price_per_sqft_myr"] and target_sqft > 0:
            result["price_per_sqft_myr"] = round(result["asking_price_myr"] / target_sqft, 2)

    return result

def extract_all_property_details(title: str, text: str, initial_categories: list = None, initial_status: str = "For Sale") -> dict:
    """Extract complete 12-category structured schema attributes from listing text."""
    combined = f"{title}\n\n{text}"
    data = {}
    
    # 1. Acreage & Dimensions
    data["land_area_acres"] = parse_acres(combined)
    
    m_sqft = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft|square\s*feet|ft²)', combined, re.IGNORECASE)
    if m_sqft:
        try:
            data["land_area_sqft"] = float(m_sqft.group(1).replace(',', ''))
        except ValueError:
            pass

    m_bu = re.search(r'(?:built[\-\s]*up|builtup|property\s*size)\s*(?:area)?\s*:?\s*([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft|ft²)', combined, re.IGNORECASE)
    if m_bu:
        try:
            data["built_up_area_sqft"] = float(m_bu.group(1).replace(',', ''))
        except ValueError:
            pass

    m_ha = re.search(r'([\d\.]+)\s*(?:hectares?|ha\b)', combined, re.IGNORECASE)
    if m_ha:
        try:
            ha = float(m_ha.group(1))
            data["land_area_sqm"] = round(ha * 10000.0, 2)
            if not data.get("land_area_acres"):
                data["land_area_acres"] = round(ha * 2.47105, 3)
        except ValueError:
            pass

    # 2. Financial Metrics
    fin = parse_listing_financials(
        title, text,
        status=initial_status,
        acres=data.get("land_area_acres", 0.0),
        sqft=data.get("land_area_sqft", 0.0)
    )
    data["asking_price_myr"] = fin["asking_price_myr"]
    data["price_per_acre_myr"] = fin["price_per_acre_myr"]
    data["price_per_sqft_myr"] = fin["price_per_sqft_myr"]
    data["monthly_rental_income_myr"] = fin["monthly_rental_income_myr"]
    data["implied_yield_pct"] = fin["implied_yield_pct"]

    # 3. Tenure, Zoning & Topography
    m_tenure = re.search(r'(?:tenure|title\s*type)\s*:?\s*([^\n\r]+)', combined, re.IGNORECASE)
    if m_tenure:
        val = m_tenure.group(1).strip()
        val = re.split(r'Category|Topography|Location|Status|Features', val, flags=re.IGNORECASE)[0].strip()
        data["tenure_type"] = val

    m_zoning = re.search(r'category\s*:?\s*([^\n\r]+)', combined, re.IGNORECASE)
    if m_zoning:
        val = m_zoning.group(1).strip()
        val = re.split(r'Topography|Location|Target|Status|Features', val, flags=re.IGNORECASE)[0].strip()
        data["zoning_type"] = val

    m_topo = re.search(r'topography\s*:?\s*([^\n\r]+)', combined, re.IGNORECASE)
    if m_topo:
        val = m_topo.group(1).strip()
        val = re.split(r'Location|Target|Infrastructure|Selling|Contact', val, flags=re.IGNORECASE)[0].strip()
        data["topography"] = val

    # 4. Target Uses / Suitable Industries
    m_target = re.search(r'(?:target\s*uses?|suitable\s*for)\s*:?\s*([^\n\r]+)', combined, re.IGNORECASE)
    if m_target:
        val = m_target.group(1).strip()
        val = re.split(r'Key|Selling|Contact|Ready', val, flags=re.IGNORECASE)[0].strip()
        data["suitable_industries"] = [u.strip() for u in re.split(r'[,;/]|or\b', val) if u.strip()]

    # 5. Infrastructure & Road Access
    if 'main road frontage' in combined.lower() or 'direct frontage' in combined.lower():
        data["road_access_quality"] = 'Main Road Frontage'
    elif 'tar road' in combined.lower():
        data["road_access_quality"] = 'Tar Road Access'
    elif '4wd' in combined.lower():
        data["road_access_quality"] = '4WD Access'

    utils = []
    if 'tnb' in combined.lower() or 'electricity' in combined.lower() or 'power' in combined.lower():
        utils.append('Electricity (TNB)')
    if 'paip' in combined.lower() or 'water' in combined.lower():
        utils.append('Water (PAIP)')
    if 'stream' in combined.lower() or 'river' in combined.lower():
        utils.append('Natural River/Stream')
        data["has_natural_stream"] = True
    if 'pond' in combined.lower():
        data["has_pond"] = True
    if 'piping' in combined.lower() or 'irrigation' in combined.lower():
        data["has_piping_system"] = True
    if utils:
        data["utilities_available"] = utils

    # 6. Agricultural Specifics
    crops = []
    for c in ["Musang King", "Black Thorn", "D24", "Durian", "Rubber", "Oil Palm", "Mixed Fruit", "Banana", "Dragon Fruit"]:
        if c.lower() in combined.lower():
            crops.append(c)
    if crops:
        data["crop_types"] = list(set(crops))

    m_tree = re.search(r'([\d,]+)\s*(?:durian\s*)?trees?', combined, re.IGNORECASE)
    if m_tree:
        try:
            data["tree_count_estimate"] = int(m_tree.group(1).replace(',', ''))
        except ValueError:
            pass

    m_age = re.search(r'([\d\-\s]+\s*years?)\s*(?:old|mature|young)?', combined, re.IGNORECASE)
    if m_age:
        data["tree_age_years"] = m_age.group(1).strip()

    # 7. Contact Information
    m_agent = re.search(r'PM\s*([\d\-\s]+)\s*[\–\-\—]\s*([a-zA-Z\s]+)', combined)
    if m_agent:
        data["agent_phone"] = m_agent.group(1).strip().replace(' ', '').replace('-', '')
        raw_name = m_agent.group(2).strip()
        data["agent_name"] = re.split(r'https?|\[|\(|\n|\r', raw_name)[0].strip()
        
    m_wa = re.search(r'https?://(?:wa\.me|phgland\.wasap\.my)/[a-zA-Z0-9\+\-\_\/]*', combined)
    if m_wa:
        data["agent_whatsapp_url"] = m_wa.group(0)

    return data

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

                    # Comprehensive structured metadata & financial extraction
                    details = extract_all_property_details(title, description, initial_categories=categories, initial_status=status)
                    if tenure and not details.get("tenure_type"):
                        details["tenure_type"] = tenure

                    # Database Upsert
                    existing = db.query(Property).filter((Property.title == title) | (Property.source_url == link)).first()
                    if existing:
                        existing.title = title
                        existing.search_corpus_markdown = description
                        existing.source_url = link
                        if details.get("asking_price_myr") is not None and details["asking_price_myr"] > 0:
                            existing.asking_price_myr = details["asking_price_myr"]
                        elif status == "For Rent":
                            existing.asking_price_myr = 0.0
                            
                        if details.get("price_per_acre_myr"): existing.price_per_acre_myr = details["price_per_acre_myr"]
                        if details.get("price_per_sqft_myr"): existing.price_per_sqft_myr = details["price_per_sqft_myr"]
                        if details.get("monthly_rental_income_myr"): existing.monthly_rental_income_myr = details["monthly_rental_income_myr"]
                        if details.get("implied_yield_pct"): existing.implied_yield_pct = details["implied_yield_pct"]
                        if details.get("land_area_acres") and details["land_area_acres"] > 0: existing.land_area_acres = details["land_area_acres"]
                        if details.get("land_area_sqft"): existing.land_area_sqft = details["land_area_sqft"]
                        if details.get("land_area_sqm"): existing.land_area_sqm = details["land_area_sqm"]
                        if details.get("built_up_area_sqft"): existing.built_up_area_sqft = details["built_up_area_sqft"]
                        if details.get("tenure_type"): existing.tenure_type = details["tenure_type"]
                        if details.get("zoning_type"): existing.zoning_type = details["zoning_type"]
                        if details.get("topography"): existing.topography = details["topography"]
                        if details.get("suitable_industries"): existing.suitable_industries = details["suitable_industries"]
                        if details.get("road_access_quality"): existing.road_access_quality = details["road_access_quality"]
                        if details.get("utilities_available"): existing.utilities_available = details["utilities_available"]
                        if details.get("crop_types"): existing.crop_types = details["crop_types"]
                        if details.get("tree_count_estimate"): existing.tree_count_estimate = details["tree_count_estimate"]
                        if details.get("tree_age_years"): existing.tree_age_years = details["tree_age_years"]
                        if details.get("agent_name"): existing.agent_name = details["agent_name"]
                        if details.get("agent_phone"): existing.agent_phone = details["agent_phone"]
                        if details.get("agent_whatsapp_url"): existing.agent_whatsapp_url = details["agent_whatsapp_url"]
                        
                        existing.city = city
                        existing.state = state
                        existing.property_category = categories
                        existing.listing_status = status
                        if images: existing.image_urls = images
                        
                        # Generate Vector Embeddings
                        vecs = generate_property_5_embeddings(existing)
                        if vecs.get("embedding_location"): existing.embedding_location = vecs["embedding_location"]
                        if vecs.get("embedding_specs"): existing.embedding_specs = vecs["embedding_specs"]
                        if vecs.get("embedding_features"): existing.embedding_features = vecs["embedding_features"]
                        if vecs.get("embedding_suitability"): existing.embedding_suitability = vecs["embedding_suitability"]
                        if vecs.get("embedding_overview"): existing.embedding_overview = vecs["embedding_overview"]
                        
                        total_updated += 1
                    else:
                        new_prop = Property(
                            id=str(uuid.uuid4()),
                            title=title,
                            search_corpus_markdown=description,
                            source_url=link,
                            asking_price_myr=details.get("asking_price_myr") or 0.0,
                            price_per_acre_myr=details.get("price_per_acre_myr"),
                            price_per_sqft_myr=details.get("price_per_sqft_myr"),
                            monthly_rental_income_myr=details.get("monthly_rental_income_myr"),
                            implied_yield_pct=details.get("implied_yield_pct"),
                            land_area_acres=details.get("land_area_acres") or 0.0,
                            land_area_sqft=details.get("land_area_sqft"),
                            land_area_sqm=details.get("land_area_sqm"),
                            built_up_area_sqft=details.get("built_up_area_sqft"),
                            city=city,
                            state=state,
                            tenure_type=details.get("tenure_type") or tenure,
                            zoning_type=details.get("zoning_type"),
                            topography=details.get("topography"),
                            suitable_industries=details.get("suitable_industries") or [],
                            road_access_quality=details.get("road_access_quality"),
                            utilities_available=details.get("utilities_available") or [],
                            crop_types=details.get("crop_types") or [],
                            tree_count_estimate=details.get("tree_count_estimate"),
                            tree_age_years=details.get("tree_age_years"),
                            agent_name=details.get("agent_name"),
                            agent_phone=details.get("agent_phone"),
                            agent_whatsapp_url=details.get("agent_whatsapp_url"),
                            property_category=categories,
                            listing_status=status,
                            image_urls=images
                        )
                        # Generate Vector Embeddings
                        vecs = generate_property_5_embeddings(new_prop)
                        if vecs.get("embedding_location"): new_prop.embedding_location = vecs["embedding_location"]
                        if vecs.get("embedding_specs"): new_prop.embedding_specs = vecs["embedding_specs"]
                        if vecs.get("embedding_features"): new_prop.embedding_features = vecs["embedding_features"]
                        if vecs.get("embedding_suitability"): new_prop.embedding_suitability = vecs["embedding_suitability"]
                        if vecs.get("embedding_overview"): new_prop.embedding_overview = vecs["embedding_overview"]
                        
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

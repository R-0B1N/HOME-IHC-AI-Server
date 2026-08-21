import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Global model cache
_embedding_model = None

def get_embedding_model():
    """
    Lazy loads the fastembed TextEmbedding model (BAAI/bge-small-en-v1.5).
    Produces 384-dimensional dense vector embeddings with ultra-low latency (~3ms).
    """
    global _embedding_model
    if _embedding_model is None:
        try:
            from fastembed import TextEmbedding
            # Default model: BAAI/bge-small-en-v1.5 (384 dims, fast, high accuracy)
            _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            logger.info("Fastembed TextEmbedding model (BAAI/bge-small-en-v1.5) loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load fastembed model: {e}")
            _embedding_model = None
    return _embedding_model

def generate_embedding(text: str) -> Optional[List[float]]:
    """
    Generates a single 384-dimensional vector embedding for the input text.
    """
    if not text or not text.strip():
        return None
    
    model = get_embedding_model()
    if model is None:
        logger.warning("Embedding model unavailable. Returning None.")
        return None

    try:
        embeddings = list(model.embed([text.strip()]))
        if embeddings and len(embeddings) > 0:
            return embeddings[0].tolist()
        return None
    except Exception as e:
        logger.error(f"Error generating embedding for text: {e}")
        return None

def generate_batch_embeddings(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Generates embeddings for a batch of strings.
    """
    if not texts:
        return []
    
    model = get_embedding_model()
    if model is None:
        return [None] * len(texts)

    try:
        embeddings = list(model.embed(texts))
        return [emb.tolist() for emb in embeddings]
    except Exception as e:
        logger.error(f"Error in generate_batch_embeddings: {e}")
        return [None] * len(texts)

def _get_val(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr, default)
    val = getattr(obj, attr, default)
    return val if val is not None else default

def build_property_aspect_chunks(property_data: Any) -> Dict[str, str]:
    """
    Constructs the 5 specialized textual chunks from a property dictionary or SQLAlchemy model
    to generate distinct vector embeddings for Location, Specs, Features, Suitability, and Overview.
    """
    title = _get_val(property_data, "title", "") or ""
    city = _get_val(property_data, "city", "") or ""
    state = _get_val(property_data, "state", "Pahang") or "Pahang"
    area = _get_val(property_data, "area", "") or ""
    street = _get_val(property_data, "street_address", "") or ""
    landmarks = ", ".join(_get_val(property_data, "nearby_landmarks", []) or [])
    
    category = ", ".join(_get_val(property_data, "property_category", []) or [])
    sub_type = _get_val(property_data, "property_type_sub", "") or ""
    tenure = _get_val(property_data, "tenure_type", "") or ""
    zoning = _get_val(property_data, "zoning_type", "") or ""
    title_status = _get_val(property_data, "title_status", "") or ""
    acres = _get_val(property_data, "land_area_acres")
    acres_str = f"{acres} acres" if acres else ""
    sqft = _get_val(property_data, "built_up_area_sqft") or _get_val(property_data, "land_area_sqft")
    sqft_str = f"{sqft} sqft" if sqft else ""
    price = _get_val(property_data, "asking_price_myr")
    price_str = f"RM {price:,.0f}" if price else ""
    rental = _get_val(property_data, "monthly_rental_income_myr")
    rental_str = f"RM {rental:,.0f}/month" if rental else ""
    
    crops = ", ".join(_get_val(property_data, "crop_types", []) or [])
    trees = f"{_get_val(property_data, 'tree_count_estimate')} trees" if _get_val(property_data, 'tree_count_estimate') else ""
    tree_age = _get_val(property_data, "tree_age_years", "") or ""
    harvest = _get_val(property_data, "harvest_readiness", "") or ""
    topo = _get_val(property_data, "topography", "") or ""
    waters = ", ".join(_get_val(property_data, "water_source_types", []) or [])
    stream = "natural river stream" if _get_val(property_data, "has_natural_stream") else ""
    pond = "water pond" if _get_val(property_data, "has_pond") else ""
    flood = "flood free area" if _get_val(property_data, "is_flood_free") else ""
    power = f"{_get_val(property_data, 'power_supply_amp')} Amp power supply" if _get_val(property_data, 'power_supply_amp') else ""
    road = _get_val(property_data, "road_access_quality", "") or ""
    fencing = "fully fenced" if _get_val(property_data, "is_fenced") else ""
    quarters = "worker quarters" if _get_val(property_data, "has_worker_quarters") else ""
    
    industries = ", ".join(_get_val(property_data, "suitable_industries", []) or [])
    highlights = ". ".join(_get_val(property_data, "key_highlights", []) or [])
    corpus = _get_val(property_data, "search_corpus_markdown", "") or ""

    # 1. Location Chunk
    loc_parts = [p for p in [title, street, area, city, state, f"Landmarks: {landmarks}" if landmarks else "", road] if p]
    location_chunk = " | ".join(loc_parts)

    # 2. Specs Chunk
    specs_parts = [p for p in [category, sub_type, tenure, zoning, title_status, acres_str, sqft_str, price_str, rental_str] if p]
    specs_chunk = " | ".join(specs_parts)

    # 3. Features & Topography Chunk
    features_parts = [p for p in [crops, trees, tree_age, harvest, topo, waters, stream, pond, flood, power, road, fencing, quarters] if p]
    features_chunk = " | ".join(features_parts)

    # 4. Suitability Chunk
    suit_parts = [p for p in [f"Suitable for: {industries}" if industries else "", f"Highlights: {highlights}" if highlights else "", title] if p]
    suitability_chunk = " | ".join(suit_parts)

    # 5. Overview Chunk
    overview_chunk = f"{title}\n{specs_chunk}\n{features_chunk}\n{location_chunk}\n{corpus[:1000]}"

    return {
        "location": location_chunk,
        "specs": specs_chunk,
        "features": features_chunk,
        "suitability": suitability_chunk,
        "overview": overview_chunk
    }

def generate_property_5_embeddings(property_data: Any) -> Dict[str, Optional[List[float]]]:
    """
    Builds the 5 categorized chunks and generates their corresponding 384-dimensional embeddings.
    """
    chunks = build_property_aspect_chunks(property_data)
    texts = [
        chunks["location"],
        chunks["specs"],
        chunks["features"],
        chunks["suitability"],
        chunks["overview"]
    ]
    vectors = generate_batch_embeddings(texts)
    
    return {
        "embedding_location": vectors[0] if len(vectors) > 0 else None,
        "embedding_specs": vectors[1] if len(vectors) > 1 else None,
        "embedding_features": vectors[2] if len(vectors) > 2 else None,
        "embedding_suitability": vectors[3] if len(vectors) > 3 else None,
        "embedding_overview": vectors[4] if len(vectors) > 4 else None,
    }

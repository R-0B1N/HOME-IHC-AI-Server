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

def build_property_aspect_chunks(property_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Constructs the 5 specialized textual chunks from a property dictionary or model
    to generate distinct vector embeddings for Location, Specs, Features, Suitability, and Overview.
    """
    title = property_data.get("title", "") or ""
    city = property_data.get("city", "") or ""
    state = property_data.get("state", "Pahang") or "Pahang"
    area = property_data.get("area", "") or ""
    street = property_data.get("street_address", "") or ""
    landmarks = ", ".join(property_data.get("nearby_landmarks", []) or [])
    
    category = ", ".join(property_data.get("property_category", []) or [])
    sub_type = property_data.get("property_type_sub", "") or ""
    tenure = property_data.get("tenure_type", "") or ""
    zoning = property_data.get("zoning_type", "") or ""
    title_status = property_data.get("title_status", "") or ""
    acres = property_data.get("land_area_acres")
    acres_str = f"{acres} acres" if acres else ""
    sqft = property_data.get("built_up_area_sqft") or property_data.get("land_area_sqft")
    sqft_str = f"{sqft} sqft" if sqft else ""
    price = property_data.get("asking_price_myr")
    price_str = f"RM {price:,.0f}" if price else ""
    rental = property_data.get("monthly_rental_income_myr")
    rental_str = f"RM {rental:,.0f}/month" if rental else ""
    
    crops = ", ".join(property_data.get("crop_types", []) or [])
    trees = f"{property_data.get('tree_count_estimate')} trees" if property_data.get("tree_count_estimate") else ""
    tree_age = property_data.get("tree_age_years", "") or ""
    harvest = property_data.get("harvest_readiness", "") or ""
    topo = property_data.get("topography", "") or ""
    waters = ", ".join(property_data.get("water_source_types", []) or [])
    stream = "natural river stream" if property_data.get("has_natural_stream") else ""
    pond = "water pond" if property_data.get("has_pond") else ""
    flood = "flood free area" if property_data.get("is_flood_free") else ""
    power = f"{property_data.get('power_supply_amp')} Amp power supply" if property_data.get("power_supply_amp") else ""
    road = property_data.get("road_access_quality", "") or ""
    fencing = "fully fenced" if property_data.get("is_fenced") else ""
    quarters = "worker quarters" if property_data.get("has_worker_quarters") else ""
    
    industries = ", ".join(property_data.get("suitable_industries", []) or [])
    highlights = ". ".join(property_data.get("key_highlights", []) or [])
    corpus = property_data.get("search_corpus_markdown", "") or ""

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

def generate_property_5_embeddings(property_data: Dict[str, Any]) -> Dict[str, Optional[List[float]]]:
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

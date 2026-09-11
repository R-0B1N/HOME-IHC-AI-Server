import logging
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.db.models import SessionLocal, Customer, Admin, Employee, InteractionLog, Property

logger = logging.getLogger(__name__)

import json

def get_or_create_customer(phone_number: str, contact_name: str, email: str = None, conversation_id: int = None, metadata: dict = None) -> Customer:
    """
    Checks if a customer exists by phone_number. If not, creates one.
    Returns the Customer object.
    """
    db: Session = SessionLocal()
    try:
        if not phone_number:
            logger.warning("No phone number provided to get_or_create_customer")
            return None
            
        customer = db.query(Customer).filter(Customer.id == phone_number).first()
        if not customer:
            logger.info(f"Creating new customer: {contact_name} ({phone_number})")
            # Parse country if possible (simple heuristic for Malaysia)
            country = "Malaysia" if phone_number.startswith("+60") else "Unknown"
            customer = Customer(
                id=phone_number,
                country=country,
                contact_name=contact_name,
                email=email,
                conversation_ids=[conversation_id] if conversation_id else [],
                metadata_json=metadata if metadata else {}
            )
            db.add(customer)
            try:
                db.commit()
                db.refresh(customer)
            except IntegrityError:
                db.rollback()
                logger.warning(f"Customer {phone_number} was created concurrently. Fetching existing.")
                customer = db.query(Customer).filter(Customer.id == phone_number).first()
                if not customer:
                    return None
        if customer:
            # Update the contact_name if the incoming name is not 'Unknown' or 'John Doe'
            updated = False
            if contact_name and contact_name.lower() not in ["unknown", "john doe"] and customer.contact_name != contact_name:
                logger.info(f"Updating customer name from {customer.contact_name} to {contact_name}")
                customer.contact_name = contact_name
                updated = True
                
            if conversation_id:
                conv_ids = customer.conversation_ids or []
                if conversation_id not in conv_ids:
                    conv_ids.append(conversation_id)
                    customer.conversation_ids = conv_ids
                    updated = True
                    
            if metadata:
                current_meta = customer.metadata_json or {}
                # Update with new metadata
                current_meta.update(metadata)
                customer.metadata_json = current_meta
                updated = True

            if updated:
                db.commit()
                db.refresh(customer)
        return customer
    except Exception as e:
        logger.error(f"Error in get_or_create_customer: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def log_interaction(customer_id: str, message_in: str, message_out: str):
    """
    Logs an interaction between the bot and the customer.
    """
    db: Session = SessionLocal()
    try:
        if not customer_id:
            return
            
        interaction = InteractionLog(
            customer_id=customer_id,
            message_in=message_in,
            message_out=message_out
        )
        db.add(interaction)
        
        # Update last interaction time
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.last_interaction = interaction.timestamp
            
        db.commit()
    except Exception as e:
        logger.error(f"Error in log_interaction: {e}")
        db.rollback()
    finally:
        db.close()

def get_sender_role(phone_number: str) -> str:
    """
    Checks the phone number against Admin, Employee, and Customer tables.
    Returns 'admin', 'employee', or 'customer'.
    """
    db: Session = SessionLocal()
    try:
        if not phone_number:
            return "unknown"
            
        is_admin = db.query(Admin).filter(Admin.phone_number == phone_number).first()
        if is_admin:
            return "admin"
            
        is_employee = db.query(Employee).filter(Employee.phone_number == phone_number).first()
        if is_employee:
            return "employee"
            
        return "customer"
    except Exception as e:
        logger.error(f"Error checking sender role: {e}")
        return "customer"
    finally:
        db.close()

def search_properties(criteria: dict, limit: int = 10) -> list:
    """
    Search the Property table based on extracted criteria (location, property_type, max_price).
    Only returns properties that are currently Available, For Sale, or For Rent.
    """
    db: Session = SessionLocal()
    try:
        query = db.query(Property).filter(
            Property.listing_status.in_(["Available", "For Sale", "For Rent"])
        )
        
        location = criteria.get("location")
        if location and str(location).lower() not in ["none", "null", "all"]:
            search_loc = f"%{location}%"
            query = query.filter(or_(
                Property.city.ilike(search_loc),
                Property.state.ilike(search_loc),
                Property.street_address.ilike(search_loc),
                Property.title.ilike(search_loc),
                Property.search_corpus_markdown.ilike(search_loc)
            ))
            
        property_type = criteria.get("property_type")
        if property_type and str(property_type).lower() not in ["none", "null", "all"]:
            search_type = f"%{property_type}%"
            query = query.filter(or_(
                Property.title.ilike(search_type),
                Property.search_corpus_markdown.ilike(search_type)
            ))
            
        max_price = criteria.get("max_price")
        if max_price:
            try:
                max_price_float = float(max_price)
                if max_price_float > 0:
                    query = query.filter(Property.asking_price_myr <= max_price_float)
            except (ValueError, TypeError):
                pass
                
        # In-DB pgvector cosine distance ranking if query_text is present
        query_text = criteria.get("query_text") or criteria.get("raw_text")
        vector_ordered = False
        if query_text:
            try:
                from app.services.embeddings import generate_embedding
                q_vec = generate_embedding(str(query_text))
                if q_vec is not None:
                    try:
                        # Utilize PostgreSQL pgvector <=> cosine distance operator
                        query = query.filter(Property.embedding_overview.isnot(None))
                        query = query.order_by(Property.embedding_overview.op('<=>')(q_vec))
                        vector_ordered = True
                    except Exception as vec_err:
                        logger.warning(f"In-DB vector search sort fallback: {vec_err}")
            except Exception as emb_err:
                logger.warning(f"Vector embedding generation fallback: {emb_err}")

        if not vector_ordered:
            query = query.order_by(Property.last_updated_at.desc())

        results = query.limit(limit).all()
        return [
            {
                "id": str(p.id),
                "title": p.title,
                "price": p.asking_price_myr,
                "city": p.city,
                "state": p.state,
                "acres": p.land_area_acres,
                "status": p.listing_status,
                "url": p.source_url or f"https://bentongland.com.my/land/{p.id}",
                "image_urls": p.image_urls or []
            }
            for p in results
        ]
    except Exception as e:
        logger.error(f"Error searching properties: {e}")
        return []
    finally:
        db.close()


import re

def _clean_search_tokens(text: str) -> list:
    """Helper to extract meaningful keywords for property matching."""
    # Strip common filler phrases
    fillers = [
        "can i get some information about", "can i get info about", "information about",
        "do you have some pictures for it", "do you have pictures for", "do you have photos for",
        "i would like some pictures for it", "send me photos of", "send me pictures of",
        "is this still available", "is it available", "how much is", "what is the price of",
        "good day", "hello", "hi", "for sale", "for rent", "please", "thank you", "thanks"
    ]
    cleaned = text.lower()
    for filler in fillers:
        cleaned = cleaned.replace(filler, " ")
    # Keep alphanumeric tokens with length >= 2
    tokens = re.findall(r'[a-zA-Z0-9\-]+', cleaned)
    stop_words = {"the", "a", "an", "at", "in", "on", "of", "and", "or", "to", "for", "is", "it", "with", "this", "that", "some", "any"}
    return [t for t in tokens if t not in stop_words and len(t) > 1]


def find_matching_property(text: str) -> dict:
    """
    Scans incoming customer message for property mentions, URLs, or location/type keywords.
    Matches against authentic properties in the PostgreSQL database.
    Returns structured property dict or None.
    """
    if not text or len(text.strip()) < 3:
        return None
        
    db: Session = SessionLocal()
    try:
        raw_text = text.strip()
        
        # 1. Direct URL match if user pasted a link
        url_match = re.search(r'https?://[^\s]+', raw_text)
        if url_match:
            url_str = url_match.group(0).rstrip('/')
            p = db.query(Property).filter(Property.source_url.ilike(f"%{url_str}%")).first()
            if p:
                return _format_property_dict(p)
            # Try matching by slug
            slug = url_str.split('/')[-1]
            if slug:
                p = db.query(Property).filter(Property.source_url.ilike(f"%{slug}%")).first()
                if p:
                    return _format_property_dict(p)

        # 2. Exact Title Match (Case-insensitive)
        exact_match = db.query(Property).filter(Property.title.ilike(f"{raw_text}")).first()
        if exact_match:
            return _format_property_dict(exact_match)

        # 3. Substring Title Match
        if len(raw_text) >= 8:
            substr_match = db.query(Property).filter(
                or_(
                    Property.title.ilike(f"%{raw_text}%"),
                    Property.source_url.ilike(f"%{raw_text.lower().replace(' ', '-')}%")
                )
            ).first()
            if substr_match:
                return _format_property_dict(substr_match)

        # 4. Token Overlap Scoring
        tokens = _clean_search_tokens(raw_text)
        if not tokens or len(tokens) < 2:
            return None

        # Build query for properties containing any of the major tokens
        token_filters = [Property.title.ilike(f"%{token}%") for token in tokens]
        candidates = db.query(Property).filter(or_(*token_filters)).all()

        best_prop = None
        highest_score = 0

        for prop in candidates:
            title_lower = (prop.title or "").lower()
            prop_url = (prop.source_url or "").lower()
            city_lower = (prop.city or "").lower()
            street_lower = (prop.street_address or "").lower()
            corpus_lower = (prop.search_corpus_markdown or "").lower()

            score = 0
            for token in tokens:
                if token in title_lower:
                    score += 4
                elif token in prop_url:
                    score += 3
                elif token in street_lower or token in city_lower:
                    score += 2
                elif token in corpus_lower:
                    score += 1

            if score > highest_score:
                highest_score = score
                best_prop = prop

        # Require a solid threshold of token matches
        min_required_score = min(len(tokens) * 2, 6)
        if highest_score >= min_required_score and best_prop:
            return _format_property_dict(best_prop)

        return None
    except Exception as e:
        logger.error(f"Error in find_matching_property: {e}")
        return None
    finally:
        db.close()


import math

def _cosine_similarity(vec_a, vec_b) -> float:
    """Computes cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def hybrid_categorized_search(query_text: str, criteria: dict = None, limit: int = 5) -> list:
    """
    Executes hybrid multi-aspect search combining SQL hard filters with
    5-aspect vector embeddings (Location, Specs, Features, Suitability, Overview).
    """
    from app.services.embeddings import generate_embedding
    criteria = criteria or {}
    db: Session = SessionLocal()
    try:
        query = db.query(Property).filter(
            Property.listing_status.in_(["Available", "For Sale", "For Rent"])
        )
        
        # Hard SQL filtering
        max_price = criteria.get("max_price")
        if max_price:
            try:
                mp = float(max_price)
                if mp > 0:
                    query = query.filter(Property.asking_price_myr <= mp * 1.15)
            except:
                pass
                
        city = criteria.get("city") or criteria.get("location")
        if city and str(city).lower() not in ["none", "null", "all"]:
            query = query.filter(or_(
                Property.city.ilike(f"%{city}%"),
                Property.state.ilike(f"%{city}%"),
                Property.area.ilike(f"%{city}%"),
                Property.title.ilike(f"%{city}%")
            ))
            
        candidates = query.all()
        if not candidates:
            return []
            
        # Generate query vector
        q_vec = generate_embedding(query_text)
        if not q_vec:
            # Fallback to token matching
            return search_properties(criteria, limit=limit)
            
        scored = []
        for p in candidates:
            # Multi-aspect cosine similarity
            sim_loc = _cosine_similarity(q_vec, p.embedding_location) if p.embedding_location else 0.0
            sim_specs = _cosine_similarity(q_vec, p.embedding_specs) if p.embedding_specs else 0.0
            sim_feat = _cosine_similarity(q_vec, p.embedding_features) if p.embedding_features else 0.0
            sim_suit = _cosine_similarity(q_vec, p.embedding_suitability) if p.embedding_suitability else 0.0
            sim_over = _cosine_similarity(q_vec, p.embedding_overview) if p.embedding_overview else 0.0
            
            # Weighted aggregate score
            total_score = (0.25 * sim_loc) + (0.25 * sim_specs) + (0.25 * sim_feat) + (0.15 * sim_suit) + (0.10 * sim_over)
            scored.append((total_score, p))
            
        scored.sort(key=lambda x: x[0], reverse=True)
        return [_format_property_dict(p) for score, p in scored[:limit]]
    except Exception as e:
        logger.error(f"Error in hybrid_categorized_search: {e}")
        return search_properties(criteria, limit=limit)
    finally:
        db.close()


def find_similar_properties(property_id: str = None, city: str = None, category: list = None,
                            target_price: float = None, max_price: float = None, min_acres: float = None,
                            exclude_id: str = None, limit: int = 3) -> list:
    """
    Finds similar active properties based on reference property, location, category, and budget.
    Utilizes vector cosine similarity when embeddings exist.
    """
    db: Session = SessionLocal()
    try:
        ref_prop = None
        if property_id:
            ref_prop = db.query(Property).filter(Property.id == property_id).first()
            if ref_prop:
                city = city or ref_prop.city
                category = category or ref_prop.property_category
                target_price = target_price or ref_prop.asking_price_myr

        query = db.query(Property).filter(
            Property.listing_status.in_(["Available", "For Sale", "For Rent"])
        )

        exclude = exclude_id or (str(ref_prop.id) if ref_prop else None)
        if exclude:
            query = query.filter(Property.id != exclude)

        if max_price and max_price > 0:
            query = query.filter(Property.asking_price_myr <= max_price)

        candidates = query.all()
        if not candidates:
            return []

        scored_candidates = []
        for p in candidates:
            score = 0
            
            # If reference property has embeddings, calculate dense cosine similarity
            if ref_prop and ref_prop.embedding_features and p.embedding_features:
                feat_sim = _cosine_similarity(ref_prop.embedding_features, p.embedding_features)
                spec_sim = _cosine_similarity(ref_prop.embedding_specs, p.embedding_specs) if ref_prop.embedding_specs and p.embedding_specs else 0.0
                score += (feat_sim * 40) + (spec_sim * 30)
            else:
                # Category Match
                if category:
                    cat_list = category if isinstance(category, list) else [str(category)]
                    p_cat_list = p.property_category if isinstance(p.property_category, list) else [str(p.property_category or "")]
                    if any(any(c.lower() in pc.lower() for pc in p_cat_list) for c in cat_list):
                        score += 30

            # City Match
            if city and p.city and city.lower() in p.city.lower():
                score += 25
            elif city and p.state and city.lower() in p.state.lower():
                score += 10

            # Price Proximity (within +/- 35% of target price)
            if target_price and target_price > 0 and p.asking_price_myr and p.asking_price_myr > 0:
                price_diff_ratio = abs(p.asking_price_myr - target_price) / target_price
                if price_diff_ratio <= 0.20:
                    score += 20
                elif price_diff_ratio <= 0.35:
                    score += 10
                elif price_diff_ratio <= 0.50:
                    score += 5

            scored_candidates.append((score, p))

        # Sort by score descending
        scored_candidates.sort(key=lambda x: (x[0], x[1].last_updated_at or x[1].scraped_at), reverse=True)

        results = []
        for score, p in scored_candidates[:limit]:
            results.append(_format_property_dict(p))
            
        return results
    except Exception as e:
        logger.error(f"Error in find_similar_properties: {e}")
        return []
    finally:
        db.close()


def _format_property_dict(p: Property) -> dict:
    """Standardizes property model to a rich dictionary representation."""
    return {
        "id": str(p.id),
        "title": p.title,
        "price": p.asking_price_myr,
        "monthly_rental": p.monthly_rental_income_myr,
        "price_per_acre": p.price_per_acre_myr,
        "price_per_sqft": p.price_per_sqft_myr,
        "yield_pct": p.implied_yield_pct,
        "city": p.city,
        "state": p.state,
        "area": p.area,
        "street_address": p.street_address,
        "property_category": p.property_category or [],
        "property_type_sub": p.property_type_sub,
        "acres": p.land_area_acres,
        "sqft": p.built_up_area_sqft or p.land_area_sqft,
        "tenure": p.tenure_type,
        "zoning": p.zoning_type,
        "title_status": p.title_status,
        "crop_types": p.crop_types or [],
        "tree_count": p.tree_count_estimate,
        "tree_age": p.tree_age_years,
        "harvest_readiness": p.harvest_readiness,
        "topography": p.topography,
        "water_sources": p.water_source_types or [],
        "has_natural_stream": p.has_natural_stream,
        "has_pond": p.has_pond,
        "is_flood_free": p.is_flood_free,
        "power_supply_amp": p.power_supply_amp,
        "road_access": p.road_access_quality,
        "is_fenced": p.is_fenced,
        "status": p.listing_status or "Available",
        "url": p.source_url or f"https://bentongland.com.my/land/{p.id}",
        "image_urls": p.image_urls or [],
        "key_highlights": p.key_highlights or [],
        "description": p.search_corpus_markdown or ""
    }


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
                
        results = query.order_by(Property.last_updated_at.desc()).limit(limit).all()
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


def find_similar_properties(property_id: str = None, city: str = None, category: list = None,
                            target_price: float = None, max_price: float = None, min_acres: float = None,
                            exclude_id: str = None, limit: int = 3) -> list:
    """
    Finds similar active properties based on reference property, location, category, and budget.
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
            
            # City Match
            if city and p.city and city.lower() in p.city.lower():
                score += 35
            elif city and p.state and city.lower() in p.state.lower():
                score += 15

            # Category Match
            if category:
                cat_list = category if isinstance(category, list) else [str(category)]
                p_cat_list = p.property_category if isinstance(p.property_category, list) else [str(p.property_category or "")]
                if any(any(c.lower() in pc.lower() for pc in p_cat_list) for c in cat_list):
                    score += 30

            # Price Proximity (within +/- 35% of target price)
            if target_price and target_price > 0 and p.asking_price_myr and p.asking_price_myr > 0:
                price_diff_ratio = abs(p.asking_price_myr - target_price) / target_price
                if price_diff_ratio <= 0.20:
                    score += 25
                elif price_diff_ratio <= 0.35:
                    score += 15
                elif price_diff_ratio <= 0.50:
                    score += 5

            scored_candidates.append((score, p))

        # Sort by score descending
        scored_candidates.sort(key=lambda x: (x[0], x[1].last_updated_at or x[1].created_at), reverse=True)

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
    """Standardizes property model to a dictionary representation."""
    return {
        "id": str(p.id),
        "title": p.title,
        "price": p.asking_price_myr,
        "city": p.city,
        "state": p.state,
        "street_address": p.street_address,
        "property_category": p.property_category or [],
        "acres": p.land_area_acres,
        "sqft": p.built_up_area_sqft,
        "tenure": p.tenure_type,
        "status": p.listing_status or "Available",
        "url": p.source_url or f"https://bentongland.com.my/land/{p.id}",
        "image_urls": p.image_urls or [],
        "description": p.search_corpus_markdown or ""
    }

import logging
import json
import re
import os
import datetime
import redis
from app.db.models import SessionLocal, Property, Customer
from app.services.llm import llm_client, LLM_MODEL_NAME, _parse_json_from_llm
from app.services.db_services import find_matching_property, find_similar_properties, search_properties
from app.services.system_prompts import (
    detect_customer_language,
    is_explicit_handover_request,
    get_multilingual_greeting,
    get_multilingual_fallback,
    get_multilingual_handover_wrapup,
    build_system_prompt,
    ADMIN_EMAIL
)

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)


def is_valid_name(name: str) -> bool:
    """Checks if a name string looks like a real person's name rather than a phone number or placeholder."""
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip()
    if len(name_clean) < 2 or len(name_clean) > 50:
        return False
    if re.match(r'^\+?[0-9\s\-]+$', name_clean):
        return False
    generic = {"unknown", "john doe", "whatsapp user", "customer", "lead", "null", "none", "n/a", ".", "user"}
    if name_clean.lower() in generic:
        return False
    return True


def check_completeness(persona: str, collected_data: dict) -> float:
    """Calculates data completeness ratio for lead scoring."""
    required_keys = {
        "buyer": ["buyer_location", "buyer_property_type", "buyer_budget"],
        "seller": ["location", "property_type", "asking_price"],
        "tenant": ["current_location", "property_type", "budget"],
        "agent": ["company_name", "coverage_area"]
    }
    required = required_keys.get(persona.lower(), ["buyer_location", "buyer_property_type"])
    if not required:
        return 1.0
    filled = sum(1 for k in required if collected_data.get(k))
    return filled / len(required)


class MultiIntentMemoryTracker:
    """
    Enterprise Conversational Multi-Intent Context & Priority Memory Tracker.
    Manages evolving customer preferences, priority queues, hybrid dual-purpose suggestions,
    and handles complex edge cases like budget contradictions, changing locations, and role switches.
    """

    @staticmethod
    def extract_intent_entities(text: str) -> dict:
        clean = (text or "").lower()
        
        # 1. Categories & property types
        cat = None
        type_label = None
        if any(k in clean for k in ["rumah kedai", "shop-house", "shophouse", "commercial & residential", "live-work", "店屋", "商住"]):
            cat = "hybrid"
            type_label = "Dual-Purpose Shop-House"
        elif any(k in clean for k in ["shop", "shoplot", "shop lot", "retail", "commercial", "office", "kedai", "店面", "铺位", "店", "商铺"]):
            cat = "commercial"
            type_label = "Commercial Shop Lot"
        elif any(k in clean for k in ["house", "terrace", "semi-d", "semi d", "bungalow", "apartment", "condo", "home", "residential", "排屋", "住宅", "住家", "半独立"]):
            cat = "residential"
            type_label = "Residential House"
        elif any(k in clean for k in ["durian", "orchard", "land", "tanah", "kebun", "ladang", "musang king", "农业地", "果园", "地皮", "农地"]):
            cat = "agricultural"
            type_label = "Agricultural Land"
        elif any(k in clean for k in ["factory", "warehouse", "kilang", "gudang", "industrial", "工业", "厂房", "仓库"]):
            cat = "industrial"
            type_label = "Industrial Property"

        # 2. Locations
        loc = None
        for town in ["bentong", "raub", "karak", "temerloh", "mentakab", "kuantan", "bukit tinggi", "janda baik", "cheroh", "tras", "lanchang", "maran", "triang", "pahang"]:
            if town in clean:
                loc = town.title()
                break

        # 3. Budget (MYR)
        budget = None
        price_match = re.search(r'(?:rm|myr)?\s*(\d+(?:\.\d+)?)\s*(m|million|k|thousand|000|\b)', clean)
        if price_match:
            try:
                num = float(price_match.group(1))
                unit = price_match.group(2).lower()
                if unit in ["m", "million"]:
                    budget = num * 1_000_000
                elif unit in ["k", "thousand"]:
                    budget = num * 1_000
                elif num >= 10000:
                    budget = num
            except (ValueError, TypeError):
                pass

        # 4. Power requirements (TNB Amp)
        power_amp = None
        amp_match = re.search(r'(\d+)\s*(?:amp|ampere|a\b)', clean)
        if amp_match:
            try:
                power_amp = int(amp_match.group(1))
            except (ValueError, TypeError):
                pass

        # 5. Role
        role = "buyer"
        if any(k in clean for k in ["sell", "selling", "list my", "jual", "出让", "想卖", "放盘"]):
            role = "seller"
        elif any(k in clean for k in ["rent out", "lease out", "for rent", "bagi sewa", "sewakan", "出租", "放租", "招租"]):
            role = "landlord"
        elif any(k in clean for k in ["rent", "renting", "sewa", "租", "想要租"]):
            role = "tenant"

        # 6. Check for concurrent multi-intent in a single prompt
        is_concurrent = False
        concurrent_inquiries = []
        has_res = any(k in clean for k in ["house", "residential", "semi-d", "terrace", "住家", "排屋"])
        has_com = any(k in clean for k in ["shop", "shoplot", "commercial", "office", "店面", "铺位"])
        has_land = any(k in clean for k in ["durian", "orchard", "land", "tanah", "农业地"])
        
        types_detected = []
        if has_res: types_detected.append(("residential", "Residential House"))
        if has_com: types_detected.append(("commercial", "Commercial Shop Lot"))
        if has_land: types_detected.append(("agricultural", "Agricultural Land"))

        if len(types_detected) > 1:
            is_concurrent = True
            for c_cat, c_label in types_detected:
                concurrent_inquiries.append({
                    "category": c_cat,
                    "property_type_label": c_label,
                    "location": loc,
                    "budget": budget,
                    "power_amp": power_amp,
                    "role": role
                })

        return {
            "category": cat,
            "property_type_label": type_label,
            "location": loc,
            "budget": budget,
            "power_amp": power_amp,
            "role": role,
            "is_concurrent": is_concurrent,
            "concurrent_inquiries": concurrent_inquiries
        }

    @classmethod
    def update_session_memory(cls, session: dict, text: str, conversation_history: str = "") -> dict:
        """
        Updates session and returns structured multi-intent memory context.
        Enforces:
        - Priority 1: Active inquiry takes first priority in search and response.
        - Previous inquiries retained in customer profile memory.
        - Intelligent hybrid opportunity detection (dual-purpose properties).
        - Edge cases: Budget contradiction separation, location switching, role switches.
        """
        import datetime
        now_iso = datetime.datetime.utcnow().isoformat()
        req_profile = session.setdefault("requirements_profile", {})
        intent_progression = session.setdefault("intent_progression", [])
        
        active_inq = req_profile.get("active_inquiry") or {}
        retained_inqs = req_profile.get("retained_inquiries") or []
        
        extracted = cls.extract_intent_entities(text)
        new_cat = extracted.get("category")
        new_label = extracted.get("property_type_label")
        new_loc = extracted.get("location")
        new_budget = extracted.get("budget")
        new_amp = extracted.get("power_amp")
        new_role = extracted.get("role", "buyer")
        
        # 1. Handle Concurrent Multi-Intent Search
        if extracted.get("is_concurrent") and extracted.get("concurrent_inquiries"):
            inqs = extracted["concurrent_inquiries"]
            primary_inq = inqs[0]
            secondary_inqs = inqs[1:]
            
            # Archive old active inquiry if different
            if active_inq and active_inq.get("category") not in [i["category"] for i in inqs]:
                retained_inqs.append(active_inq)
                
            active_inq = {
                "category": primary_inq["category"],
                "property_type_label": primary_inq["property_type_label"],
                "location": primary_inq["location"] or active_inq.get("location") or "Bentong",
                "budget": primary_inq["budget"] or active_inq.get("budget"),
                "budget_formatted": f"RM {int(primary_inq['budget']):,}" if primary_inq["budget"] else "To be advised",
                "power_amp": primary_inq["power_amp"] or active_inq.get("power_amp"),
                "role": primary_inq["role"],
                "updated_at": now_iso
            }
            for sec in secondary_inqs:
                retained_inqs.append({
                    "category": sec["category"],
                    "property_type_label": sec["property_type_label"],
                    "location": sec["location"] or active_inq.get("location") or "Pahang",
                    "budget": sec["budget"],
                    "budget_formatted": f"RM {int(sec['budget']):,}" if sec["budget"] else "To be advised",
                    "power_amp": sec["power_amp"],
                    "role": sec["role"],
                    "updated_at": now_iso
                })
                
            intent_progression.append({
                "timestamp": now_iso,
                "event_type": "concurrent_search",
                "title": "Multiple Concurrent Inquiries Registered",
                "description": f"Customer initiated concurrent search for {active_inq['property_type_label']} (1st Priority) and {', '.join([s['property_type_label'] for s in secondary_inqs])} (Secondary Memory).",
                "active_priority": f"{active_inq['property_type_label']} ({active_inq['location']})",
                "retained_context": ", ".join([s['property_type_label'] for s in secondary_inqs]),
                "hybrid_opportunity": any(s['category'] in ['commercial', 'residential'] for s in secondary_inqs) and active_inq['category'] in ['commercial', 'residential']
            })
            
        # 2. Handle Intent Switch / Category Evolution
        elif new_cat and active_inq.get("category") and new_cat != active_inq.get("category"):
            old_inq = dict(active_inq)
            # Retain old active inquiry in memory (preventing data loss)
            retained_inqs.append(old_inq)
            
            # Formulate new active inquiry (1st Priority)
            # Budget Contradiction Handling: Keep separate budget for new category, do not inherit old budget
            active_budget = new_budget
            active_budget_fmt = f"RM {int(active_budget):,}" if active_budget else "To be advised"
            
            active_inq = {
                "category": new_cat,
                "property_type_label": new_label or new_cat.title(),
                "location": new_loc or old_inq.get("location") or "Bentong",
                "budget": active_budget,
                "budget_formatted": active_budget_fmt,
                "power_amp": new_amp or old_inq.get("power_amp"),
                "role": new_role,
                "updated_at": now_iso
            }
            
            # Check for hybrid opportunity
            hybrid_opp = (
                (new_cat == "residential" and any(r.get("category") == "commercial" for r in retained_inqs + [old_inq])) or
                (new_cat == "commercial" and any(r.get("category") == "residential" for r in retained_inqs + [old_inq])) or
                new_cat == "hybrid"
            )
            
            intent_progression.append({
                "timestamp": now_iso,
                "event_type": "intent_switch",
                "title": f"Intent Shift: {old_inq.get('property_type_label', 'Inquiry')} → {active_inq['property_type_label']}",
                "description": (
                    f"Customer shifted focus to {active_inq['property_type_label']} in {active_inq['location']} (Budget: {active_budget_fmt}). "
                    f"Prior inquiry for {old_inq.get('property_type_label')} in {old_inq.get('location')} (Budget: {old_inq.get('budget_formatted', 'N/A')}) retained in memory."
                ),
                "active_priority": f"{active_inq['property_type_label']} ({active_inq['location']})",
                "retained_context": f"{old_inq.get('property_type_label')} ({old_inq.get('location')})",
                "hybrid_opportunity": hybrid_opp
            })
            
        # 3. Handle Role Switch (e.g. Buyer to Seller / Landlord)
        elif new_role in ["seller", "landlord"] and active_inq.get("role") == "buyer":
            retained_inqs.append(dict(active_inq))
            active_inq["role"] = new_role
            if new_cat:
                active_inq["category"] = new_cat
                active_inq["property_type_label"] = new_label or new_cat.title()
            if new_loc:
                active_inq["location"] = new_loc
            if new_budget:
                active_inq["budget"] = new_budget
                active_inq["budget_formatted"] = f"RM {int(new_budget):,}"
            active_inq["updated_at"] = now_iso
            
            intent_progression.append({
                "timestamp": now_iso,
                "event_type": "role_switch",
                "title": f"Role Expansion: Buyer → {new_role.title()}",
                "description": f"Customer expanded engagement as a {new_role.title()} to list/rent property. Prior buyer requirements preserved.",
                "active_priority": f"{new_role.title()} ({active_inq.get('property_type_label', 'Property')})",
                "retained_context": "Buyer Portfolio",
                "hybrid_opportunity": False
            })
            
        # 4. Refinement or First Inquiry
        else:
            if not active_inq:
                active_inq = {
                    "category": new_cat or "general",
                    "property_type_label": new_label or "Property Inquiry",
                    "location": new_loc or "Bentong",
                    "budget": new_budget,
                    "budget_formatted": f"RM {int(new_budget):,}" if new_budget else "To be advised",
                    "power_amp": new_amp,
                    "role": new_role,
                    "updated_at": now_iso
                }
                intent_progression.append({
                    "timestamp": now_iso,
                    "event_type": "initial_inquiry",
                    "title": f"Initial Inquiry: {active_inq['property_type_label']}",
                    "description": f"Customer initiated inquiry for {active_inq['property_type_label']} in {active_inq['location']}.",
                    "active_priority": f"{active_inq['property_type_label']} ({active_inq['location']})",
                    "retained_context": None,
                    "hybrid_opportunity": False
                })
            else:
                # Update with refinement if specified
                if new_loc:
                    active_inq["location"] = new_loc
                if new_budget:
                    active_inq["budget"] = new_budget
                    active_inq["budget_formatted"] = f"RM {int(new_budget):,}"
                if new_amp:
                    active_inq["power_amp"] = new_amp
                if new_label and not active_inq.get("property_type_label"):
                    active_inq["property_type_label"] = new_label
                active_inq["updated_at"] = now_iso

        # Calculate Hybrid Opportunity (Dual-purpose shop-house)
        categories_in_profile = {active_inq.get("category")} | {r.get("category") for r in retained_inqs}
        has_hybrid_potential = ("residential" in categories_in_profile and "commercial" in categories_in_profile) or (active_inq.get("category") == "hybrid")

        # Compile Aggregated Requirements Profile
        target_locations = list(dict.fromkeys(filter(None, [active_inq.get("location")] + [r.get("location") for r in retained_inqs])))
        preferred_types = list(dict.fromkeys(filter(None, [active_inq.get("property_type_label")] + [r.get("property_type_label") for r in retained_inqs])))
        
        # Formatted Budget Breakdown (Resolving Contradictions)
        budget_parts = []
        if active_inq.get("budget"):
            budget_parts.append(f"{active_inq.get('budget_formatted')} ({active_inq.get('property_type_label')})")
        for r in retained_inqs:
            if r.get("budget"):
                budget_parts.append(f"{r.get('budget_formatted')} ({r.get('property_type_label')})")
        formatted_budget_str = " | ".join(budget_parts) if budget_parts else (active_inq.get("budget_formatted") or "To be advised")
        
        # Power supply
        power_str = f"⚡ {active_inq.get('power_amp')} Amp (3-Phase)" if active_inq.get("power_amp") else "Standard Residential / Commercial"
        
        req_profile["active_inquiry"] = active_inq
        req_profile["retained_inquiries"] = retained_inqs
        req_profile["target_locations"] = target_locations
        req_profile["preferred_property_types"] = preferred_types
        req_profile["target_budget_myr"] = active_inq.get("budget")
        req_profile["target_budget_formatted"] = formatted_budget_str
        req_profile["power_requirements_amp"] = power_str
        req_profile["hybrid_opportunity"] = has_hybrid_potential
        
        session["requirements_profile"] = req_profile
        session["intent_progression"] = intent_progression
        
        # Map criteria for primary and hybrid searches
        primary_criteria = {
            "location": active_inq.get("location"),
            "property_type": active_inq.get("category"),
            "max_price": active_inq.get("budget"),
            "min_power_amp": active_inq.get("power_amp")
        }
        hybrid_criteria = {
            "location": active_inq.get("location") or "Bentong",
            "is_hybrid": True
        } if has_hybrid_potential else None

        return {
            "active_inquiry": active_inq,
            "retained_inquiries": retained_inqs,
            "hybrid_opportunity": has_hybrid_potential,
            "has_multi_intent": bool(retained_inqs),
            "primary_criteria": primary_criteria,
            "hybrid_criteria": hybrid_criteria,
            "requirements_profile": req_profile,
            "intent_progression": intent_progression
        }

    @staticmethod
    def persist_customer_memory(phone_number: str, session: dict):
        """Persists multi-intent profile, progression timeline, and properties into Customer table."""
        if not phone_number:
            return
        try:
            db = SessionLocal()
            try:
                cust = db.query(Customer).filter(Customer.id == phone_number).first()
                if cust:
                    meta = dict(cust.metadata_json or {})
                    meta["requirements_profile"] = session.get("requirements_profile")
                    meta["intent_progression"] = session.get("intent_progression")
                    meta["presented_properties"] = session.get("presented_properties")
                    meta["shortlisted_properties"] = session.get("shortlisted_properties")
                    if session.get("viewing_acknowledgement"):
                        meta["viewing_acknowledgement"] = session.get("viewing_acknowledgement")
                    if session.get("current_agent"):
                        meta["intent_category"] = session.get("current_agent").lower()
                    if session.get("lead_temp"):
                        meta["intention_tag"] = session.get("lead_temp")
                    cust.metadata_json = meta
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to persist customer memory for {phone_number}: {e}")


def parse_viewing_schedule_datetime(text: str) -> datetime.datetime:
    """
    Parses natural language date/time references into a concrete upcoming datetime.
    Supports English, Malay, and Chinese date/time phrases with standard business hours fallback.
    """
    import datetime
    now = datetime.datetime.now()
    text_lower = (text or "").lower()
    target_dt = now + datetime.timedelta(days=1)
    
    # 1. Day offsets
    if any(w in text_lower for w in ["tomorrow", "esok", "besok", "明天"]):
        target_dt = now + datetime.timedelta(days=1)
    elif any(w in text_lower for w in ["day after tomorrow", "lusa", "后天"]):
        target_dt = now + datetime.timedelta(days=2)
    elif any(w in text_lower for w in ["saturday", "sabtu", "周六", "星期六"]):
        days_ahead = (5 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["sunday", "ahad", "周日", "星期日", "礼拜天"]):
        days_ahead = (6 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["monday", "isnin", "周一", "星期一"]):
        days_ahead = (0 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["tuesday", "selasa", "周二", "星期二"]):
        days_ahead = (1 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["wednesday", "rabu", "周三", "星期三"]):
        days_ahead = (2 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["thursday", "khamis", "周四", "星期四"]):
        days_ahead = (3 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)
    elif any(w in text_lower for w in ["friday", "jumaat", "周五", "星期五"]):
        days_ahead = (4 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        target_dt = now + datetime.timedelta(days=days_ahead)

    # 2. Time parsing (default 10:00 AM)
    hour = 10
    minute = 0
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|pagi|petang|malam|ptg)?', text_lower)
    if time_match:
        parsed_h = int(time_match.group(1))
        parsed_m = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = (time_match.group(3) or "").lower()
        if ampm in ["pm", "petang", "malam", "ptg"] and parsed_h < 12:
            parsed_h += 12
        elif ampm in ["am", "pagi"] and parsed_h == 12:
            parsed_h = 0
        if 8 <= parsed_h <= 19:
            hour = parsed_h
            minute = parsed_m
    elif any(w in text_lower for w in ["afternoon", "petang", "下午"]):
        hour = 14
    elif any(w in text_lower for w in ["morning", "pagi", "上午", "早上"]):
        hour = 10

    return target_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


def process_persona_state_machine(phone_number: str, text: str = "", session: dict = None, conversation_history: str = "", contact_name: str = None, raw_text: str = None, **kwargs) -> dict:
    """
    Enterprise-standard Conversational AI Engine for Home IHC.
    Engages naturally, provides on-demand property specs, dispatches native WhatsApp photos,
    suggests similar properties, and prevents premature handovers.
    """
    if session is None:
        session = {}
    actual_text = (text or raw_text or "").strip()
    raw_text = actual_text
    collected_data = session.setdefault("collected_data", {})

    # Detect and track customer language
    detected_lang = detect_customer_language(actual_text)
    if detected_lang != "en" or not session.get("language"):
        session["language"] = detected_lang
    customer_lang = session.get("language", detected_lang)

    # Auto-reset session if in completed/stale state
    if session.get("state") == "COMPLETED" or session.get("handover"):
        session["state"] = "IN_PROGRESS"
        session["handover"] = False

    # 1. Payload Name Hook — populate name if valid
    if contact_name and is_valid_name(contact_name) and not collected_data.get("name"):
        collected_data["name"] = contact_name.strip()

    current_user_name = collected_data.get("name") or (contact_name if is_valid_name(contact_name) else None)

    # 2. Match Specific Property in Database or Resolve from History
    matched_prop = find_matching_property(raw_text)
    if matched_prop:
        session["interested_property"] = matched_prop
        collected_data["property_of_interest"] = matched_prop["title"]
        if not collected_data.get("buyer_property_type"):
            categories = matched_prop.get("property_category") or []
            collected_data["buyer_property_type"] = categories[0] if categories else matched_prop["title"]
        if not collected_data.get("buyer_location"):
            collected_data["buyer_location"] = matched_prop.get("city") or matched_prop.get("state") or "Pahang"
        if not collected_data.get("buyer_budget") and matched_prop.get("price"):
            collected_data["buyer_budget"] = f"RM {matched_prop['price']:,.0f}"
        if not collected_data.get("customer_category"):
            collected_data["customer_category"] = "buyer"

    # Detect specific property/lot mentions that are NOT in our database
    _property_entity_detected = False
    _property_entity_text = ""
    if not matched_prop:
        # Check for lot numbers, taman names, addresses, or specific property identifiers
        entity_patterns = [
            r'lot\s+\d+',
            r'mukim\s+\w+',
            r'daerah\s+\w+',
            r'taman\s+\w+',
            r'kampung\s+\w+',
            r'jalan\s+\w+',
            r'no\.?\s*\d+',
        ]
        for pattern in entity_patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                _property_entity_detected = True
                _property_entity_text = raw_text.strip()
                break

    cached_prop = session.get("interested_property")

    # If no cached property, try to resolve from conversation history
    if not cached_prop and conversation_history:
        history_prop = find_matching_property(conversation_history)
        if history_prop:
            session["interested_property"] = history_prop
            cached_prop = history_prop

    # 3. Dynamic RAG Property Search & Multi-Intent Priority Memory
    available_properties = []
    hybrid_properties = []
    
    # Update multi-intent preferences and progression timeline
    memory_context = MultiIntentMemoryTracker.update_session_memory(session, raw_text, conversation_history)
    active_inq = memory_context["active_inquiry"]
    is_intent_switch = memory_context.get("is_intent_switch", False)
    
    # Sync collected_data with active_inquiry for backward-compatibility
    if active_inq.get("property_type_label"):
        collected_data["buyer_property_type"] = active_inq["property_type_label"]
    if active_inq.get("location"):
        collected_data["buyer_location"] = active_inq["location"]
    if active_inq.get("budget"):
        collected_data["buyer_budget"] = active_inq.get("budget_formatted")
    if active_inq.get("role"):
        collected_data["customer_category"] = active_inq["role"]

    # Check if user explicitly wants to switch criteria
    is_switching_context = is_intent_switch or any(phrase in raw_text.lower() for phrase in [
        "other", "another", "different", "instead", "switch to", "what else",
        "durian land", "commercial", "industrial", "house in", "shop in", "land in",
        "店面", "铺位", "店", "shop", "commercial", "rumah kedai"
    ]) and not any(p in raw_text.lower() for p in ["picture", "photo", "gambar", "foto", "more picture", "more photo", "detail"])

    if is_switching_context:
        session["interested_property"] = None
        cached_prop = None

    if not cached_prop:
        # Search DB for primary active criteria (1st Priority)
        primary_crit = memory_context["primary_criteria"]
        has_any_criteria = any(v for v in primary_crit.values() if v and str(v).lower() not in ["none", "null", ""])
        if has_any_criteria:
            available_properties = search_properties(primary_crit, limit=5)
            
        # Search DB for hybrid dual-purpose options (e.g. shop-house / rumah kedai) if applicable
        if memory_context.get("hybrid_opportunity"):
            hybrid_crit = memory_context.get("hybrid_criteria") or {"location": active_inq.get("location") or "Bentong", "is_hybrid": True}
            hybrid_properties = search_properties(hybrid_crit, limit=3)

    # Record presented properties into session for memory & dashboard display
    all_presented = available_properties + hybrid_properties
    if all_presented:
        session_pres = session.setdefault("presented_properties", [])
        existing_ids = {str(p.get("id")) for p in session_pres if isinstance(p, dict)}
        for p in all_presented:
            if str(p.get("id")) not in existing_ids:
                session_pres.append(p)

    # 4. LLM Intent & Conversational Generation
    llm_kwargs = dict(kwargs)
    llm_kwargs["customer_language"] = customer_lang
    llm_analysis = generate_conversational_response(
        text=raw_text,
        cached_property=cached_prop,
        available_properties=available_properties if not cached_prop else [],
        hybrid_properties=hybrid_properties,
        memory_context=memory_context,
        conversation_history=conversation_history,
        collected_data=collected_data,
        customer_name=current_user_name,
        unlisted_property_text=_property_entity_text if _property_entity_detected else None,
        **llm_kwargs
    )

    # Merge extracted data
    for k, v in llm_analysis.get("extracted_data", {}).items():
        if v and str(v).lower() not in ["null", "none", ""]:
            collected_data[k] = v

    is_out_of_context = llm_analysis.get("is_out_of_context", False)
    if is_out_of_context:
        session["state"] = "COMPLETED"
        if customer_lang == "zh":
            ooc_resp = f"感谢您联系 Home IHC。您的咨询已转交至我们的行政团队（{ADMIN_EMAIL}），专员将尽快跟进处理。"
        elif customer_lang == "ms":
            ooc_resp = f"Terima kasih kerana menghubungi Home IHC. Pertanyaan anda telah dimajukan kepada pasukan pentadbiran kami di {ADMIN_EMAIL}, dan pegawai kami akan menghubungi anda sebentar lagi."
        else:
            ooc_resp = f"Thank you for contacting Home IHC. I have forwarded your inquiry to our administration team at {ADMIN_EMAIL}, and a representative will follow up with you shortly."
        return {
            "response": ooc_resp,
            "handover": True,
            "assignee_email": ADMIN_EMAIL,
            "images_to_send": [],
            "updated_session": session
        }

    asked_photos = llm_analysis.get("asked_photos", False)
    asked_meeting = llm_analysis.get("asked_meeting", False)
    asked_alternatives = llm_analysis.get("asked_alternatives", False)
    new_constraints = llm_analysis.get("new_constraints", {})

    # Detect photo request via LLM or direct conversational keywords
    # Guard: Only trigger photo dispatch during ongoing dialogue, not on first message
    has_prior_conversation = bool(conversation_history and len(conversation_history.strip()) > 10)
    is_photo_request = (bool(asked_photos) or any(w in raw_text.lower() for w in [
        "picture", "pictures", "photo", "photos", "gambar", "foto", "image", "images", "see photo", "show photo", "相片", "照片"
    ])) and has_prior_conversation

    images_to_send = []

    # 5. Handle Native WhatsApp Photos
    if is_photo_request and cached_prop:
        prop_images = cached_prop.get("image_urls") or []
        
        # If cached dict has no image_urls, query DB directly
        if not prop_images and cached_prop.get("id"):
            db = SessionLocal()
            try:
                p_record = db.query(Property).filter(Property.id == cached_prop["id"]).first()
                if p_record and p_record.image_urls:
                    prop_images = p_record.image_urls
                    cached_prop["image_urls"] = prop_images
                    session["interested_property"] = cached_prop
            finally:
                db.close()
                
        if prop_images:
            # Filter valid HTTP URLs and exclude logo/icon placeholders
            images_to_send = [
                img for img in prop_images 
                if isinstance(img, str) and img.startswith("http") and not any(ex in img.lower() for ex in ["logo", "icon", "favicon"])
            ][:5]
            logger.info(f"Resolved {len(images_to_send)} photos to send for property: {cached_prop.get('title')}")

    # 6. Handle Similar Properties Suggestion (Alternatives / Sold listing)
    if asked_alternatives or (cached_prop and cached_prop.get("status") not in ["Available", "For Sale", "For Rent"]):
        city = new_constraints.get("city") or (cached_prop.get("city") if cached_prop else None)
        category = new_constraints.get("category") or (cached_prop.get("property_category") if cached_prop else None)
        max_p = new_constraints.get("max_price")
        
        similars = find_similar_properties(
            property_id=cached_prop.get("id") if cached_prop else None,
            city=city,
            category=category,
            max_price=max_p,
            limit=3
        )
        if similars:
            llm_analysis["similar_options"] = similars

    # 7. Check Handover Triggers
    handover = False
    response_text = llm_analysis.get("response", "How may Home IHC assist you with properties in Pahang today? 😊")

    if images_to_send and not any(k in response_text.lower() for k in ["photo", "picture", "gambar", "foto", "照片", "相片"]):
        if customer_lang == "zh":
            response_text = f"这是为您准备的房产照片！😊\n\n{response_text}"
        elif customer_lang == "ms":
            response_text = f"Berikut adalah gambar hartanah untuk rujukan anda! 😊\n\n{response_text}"
        else:
            response_text = f"Here are the photos of the property for your reference! 😊\n\n{response_text}"

    user_wants_immediate_human = is_explicit_handover_request(raw_text)
    
    # 7. Autonomous Viewing Scheduling & Viewing Acknowledgement Engine Trigger
    schedule_viewing = False
    scheduled_viewing_dt = None
    
    viewing_phrases = [
        "安排看房", "预约看房", "睇楼", "tengok rumah", "tengok tanah", "arrange viewing", 
        "schedule viewing", "book viewing", "view the property", "see the land", "visit the land",
        "visit the property", "can view", "view tomorrow", "view saturday", "viewing on"
    ]
    has_viewing_confirmation = (
        bool(llm_analysis.get("viewing_confirmed"))
        or any(phrase in raw_text.lower() for phrase in viewing_phrases)
        or (bool(cached_prop) and any(d in raw_text.lower() for d in ["tomorrow", "saturday", "sunday", "esok", "sabtu", "ahad", "周六", "周日", "明天", "后天", "next week", "minggu depan"]) and any(w in raw_text.lower() or w in conversation_history.lower() for w in ["view", "tengok", "see", "visit", "look", "看"]))
    )
    user_books_cached_viewing = bool(cached_prop) and (bool(asked_meeting) or has_viewing_confirmation)

    if bool(cached_prop) and has_viewing_confirmation:
        schedule_viewing = True
        raw_date_hint = llm_analysis.get("viewing_date_text") or raw_text
        scheduled_viewing_dt = parse_viewing_schedule_datetime(raw_date_hint)
        formatted_date_str = scheduled_viewing_dt.strftime("%A, %d %B %Y at %I:%M %p")
        
        name_str = f" {current_user_name}" if current_user_name else ""
        prop_title = cached_prop.get('title')
        if customer_lang == "zh":
            response_text = (
                f"太好了{name_str}！😊 我已为您安排了在 {formatted_date_str} 实地参观 {prop_title}。"
                f"我们正在为您准备官方客户看房确认书（Customer Property Viewing Acknowledgement），以便向业主预约确认。"
            )
        elif customer_lang == "ms":
            response_text = (
                f"Bagus sekali{name_str}! 😊 Saya telah jadualkan sesi lawatan tapak anda untuk {prop_title} "
                f"pada {formatted_date_str}. Kami sedang menyediakan borang Pengesahan Lawatan Hartanah Pelanggan rasmi untuk semakan anda."
            )
        else:
            response_text = (
                f"Wonderful{name_str}! 😊 I have scheduled your onsite viewing for {prop_title} "
                f"on {formatted_date_str}. I am generating and sending your official Customer Property "
                f"Viewing Acknowledgement form right now for your review."
            )
        collected_data["scheduled_viewing_date"] = scheduled_viewing_dt.isoformat()
        collected_data["scheduled_property_title"] = prop_title
        session["viewing_scheduled"] = True

    if user_wants_immediate_human:
        handover = True
        name_str = f" {current_user_name}" if current_user_name else ""
        prop_str = f" for {cached_prop.get('title')}" if cached_prop else ""
        if "senior" not in response_text.lower() and "specialist" not in response_text.lower() and "representative" not in response_text.lower() and "专员" not in response_text and "pegawai" not in response_text.lower():
            response_text = get_multilingual_handover_wrapup(customer_lang, current_user_name, cached_prop.get('title') if cached_prop else None)
        session["state"] = "COMPLETED"
    elif user_books_cached_viewing:
        handover = True
        session["state"] = "COMPLETED"

    # Track viewing acknowledgement status if user expressed inspection intent
    if user_books_cached_viewing or bool(asked_meeting) or any(k in raw_text.lower() for k in ["viewing", "看房", "睇楼", "tengok rumah", "tengok tanah", "arrange viewing", "schedule viewing"]):
        import datetime
        prop_title = cached_prop.get('title') if cached_prop else (session.get("requirements_profile", {}).get("active_inquiry", {}).get("property_type_label") or "Property")
        session["viewing_acknowledgement"] = {
            "status": "Scheduled",
            "form_no": "Form 0190",
            "date": (scheduled_viewing_dt or datetime.datetime.utcnow()).strftime("%d.%m.%Y"),
            "agent_name": "Irene Leong (ERA Realtor / Home IHC)",
            "notes": f"Inspection appointment requested for {prop_title}"
        }

    # Save session state & mark introduction as completed
    collected_data["introduced"] = True
    session["introduced"] = True
    session["current_agent"] = collected_data.get("customer_category", "BUYER").upper()
    session["collected_data"] = collected_data

    # Persist updated multi-intent memory and profile to Customer table
    MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)

    return {
        "response": response_text,
        "handover": handover,
        "images_to_send": images_to_send,
        "schedule_viewing": schedule_viewing,
        "viewing_property": cached_prop if schedule_viewing else None,
        "viewing_date": scheduled_viewing_dt,
        "updated_session": session
    }


def generate_conversational_response(
    text: str = "",
    cached_property: dict = None,
    available_properties: list = None,
    conversation_history: str = "",
    collected_data: dict = None,
    customer_name: str = None,
    unlisted_property_text: str = None,
    contact_info: dict = None,
    **kwargs
) -> dict:
    """
    Calls LLM to generate a natural, empathetic, human-like response as Irene Leong from ERA Realtor representing Home IHC.
    Performs simultaneous silent background data extraction and multilingual Malaysian dialect comprehension.
    """
    if collected_data is None:
        collected_data = {}
    if available_properties is None:
        available_properties = []

    role = (kwargs.get("role") or "customer").lower()
    db_context = kwargs.get("db_context") or {}
    memory_context = kwargs.get("memory_context") or {}
    hybrid_properties = kwargs.get("hybrid_properties") or []
    customer_lang = kwargs.get("customer_language") or detect_customer_language(text)

    system_prompt = build_system_prompt(
        cached_property=cached_property,
        available_properties=available_properties if not cached_property else [],
        unlisted_property_text=unlisted_property_text,
        collected_data=collected_data,
        customer_name=customer_name,
        conversation_history=conversation_history,
        customer_language=customer_lang,
        role=role,
        db_context=db_context,
        memory_context=memory_context,
        hybrid_properties=hybrid_properties
    )

    # 1. Dynamic Token Management (Guarantee prompt + completion <= 2048 limit)
    history_to_use = conversation_history or ""
    total_chars = len(system_prompt) + len(history_to_use) + len(text or "")
    est_input_tokens = int(total_chars / 3.0)

    # If approaching limit, prune history to most recent exchanges
    if est_input_tokens > 1500 and history_to_use:
        hist_lines = [l for l in history_to_use.split("\n") if l.strip()]
        history_to_use = "\n".join(hist_lines[-4:])
        total_chars = len(system_prompt) + len(history_to_use) + len(text or "")
        est_input_tokens = int(total_chars / 3.0)

    # Bounded output token budget
    safe_max_tokens = max(120, min(300, 2035 - est_input_tokens))

    messages = [
        {"role": "system", "content": system_prompt}
    ]
    if history_to_use:
        messages.append({"role": "system", "content": f"Recent Conversation History:\n{history_to_use}"})
    messages.append({"role": "user", "content": text})

    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=safe_max_tokens,
            timeout=30.0
        )
        content = response.choices[0].message.content
        parsed = _parse_json_from_llm(content)
        if not parsed:
            try:
                parsed = json.loads(content, strict=False)
            except Exception:
                match = re.search(r'"response"\s*:\s*"([^"]*)', content, re.DOTALL)
                if match:
                    parsed = {"response": match.group(1).strip()}
        
        if parsed and isinstance(parsed, dict) and parsed.get("response"):
            return parsed
        raise ValueError(f"Failed to parse valid JSON response from LLM content: {content[:100] if content else 'empty'}")
    except Exception as e:
        logger.error(f"Error calling LLM for conversational response: {e}")
        # Auto-retry with minimal prompt if 400 Bad Request or token context overflow occurs
        if "400" in str(e) or "maximum context length" in str(e).lower():
            logger.warning("Attempting emergency retry with minimal context...")
            try:
                emergency_messages = [
                    {"role": "system", "content": system_prompt[:2000]},
                    {"role": "user", "content": text}
                ]
                retry_resp = llm_client.chat.completions.create(
                    model=LLM_MODEL_NAME,
                    messages=emergency_messages,
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=150,
                    timeout=20.0
                )
                retry_content = retry_resp.choices[0].message.content
                retry_parsed = _parse_json_from_llm(retry_content)
                if retry_parsed and isinstance(retry_parsed, dict) and retry_parsed.get("response"):
                    return retry_parsed
            except Exception as retry_err:
                logger.error(f"Emergency retry also failed: {retry_err}")

        lang = kwargs.get("customer_language") or detect_customer_language(text)
        # Resilient fallback: Only treat as ongoing conversation if the assistant has actually spoken in history
        assistant_spoke = bool(
            conversation_history and (
                "Assistant:" in conversation_history or
                "AI:" in conversation_history or
                "Agent:" in conversation_history or
                "Irene Leong" in conversation_history or
                "mecard.my" in conversation_history
            )
        )
        effective_history = conversation_history if assistant_spoke else None
        fallback_msg = get_multilingual_fallback(lang, effective_history)
        return {
            "intent": "general",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "viewing_confirmed": False,
            "viewing_date_text": None,
            "asked_alternatives": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "response": fallback_msg
        }

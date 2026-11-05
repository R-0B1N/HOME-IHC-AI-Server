import logging
import json
import re
import os
import datetime
import redis
from app.db.models import SessionLocal, Property, Customer
from app.services.llm import llm_client, LLM_MODEL_NAME, _parse_json_from_llm, classify_turn_intent
from app.services.db_services import find_matching_property, find_similar_properties, search_properties
from app.services.system_prompts import (
    detect_customer_language,
    is_explicit_handover_request,
    is_handover_promised,
    get_multilingual_greeting,
    get_multilingual_fallback,
    get_multilingual_premature_questions,
    get_multilingual_out_of_scope_redirect,
    get_multilingual_handover_wrapup,
    get_multilingual_disambiguation_request,
    get_multilingual_ah_tuck_handover,
    build_system_prompt,
    IRENE_MAIN_PHONE,
    IRENE_DISPLAY_PHONE,
    ADMIN_EMAIL,
    AH_TUCK_NAME,
    AH_TUCK_PHONE,
    AH_TUCK_EMAIL
)

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)


def is_valid_name(name: str) -> bool:
    """Checks if a name string looks like a real person's name rather than a phone number, greeting, or exclamation."""
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip()
    if len(name_clean) < 2 or len(name_clean) > 50:
        return False
    if re.match(r'^\+?[0-9\s\-]+$', name_clean):
        return False
    if re.search(r'[!?@#$%^&*~+=]{2,}', name_clean):
        return False
    cleaned_alpha = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff\s]', '', name_clean).strip().lower()
    if not cleaned_alpha:
        return False
    generic = {
        "unknown", "john doe", "whatsapp user", "customer", "lead", "null", "none", "n/a", ".", "user",
        "yes", "no", "ok", "okay", "hi", "hello", "hey", "good", "thanks", "thank you", "admin", "test"
    }
    if cleaned_alpha in generic:
        return False
    return True


def extract_self_introduced_name(text: str) -> str:
    """Extracts explicit self-introductions from customer messages (e.g., 'I am Miss Lee', 'My name is Mr Tan')."""
    if not text or not isinstance(text, str):
        return None
    patterns = [
        r"\b(?:i\s+am|i'm|my\s+name\s+is|this\s+is|saya)\s+((?:miss|mr\.?|mrs\.?|ms\.?|mdm\.?|dr\.?|dato'?|datuk|tan\s+sri|puan|encik|tuan|cik)\s+[a-zA-Z]{2,20}(?:\s+[a-zA-Z]{2,20})?)\b",
        r"\b(?:my\s+name\s+is|nama\s+saya)\s+([A-Z][a-zA-Z]{1,20}(?:\s+[A-Z][a-zA-Z]{1,20}){0,2})\b",
        r"(?:我是|我姓|我叫)\s*([\u4e00-\u9fff]{1,4}(?:先生|小姐|女士|太太|老板|哥|姐)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            candidate = re.split(r'\b(?:talked|spoke|calling|from|looking|want|need|will|here|just|now|who|that|and)\b', candidate, flags=re.IGNORECASE)[0].strip()
            if is_valid_name(candidate) and candidate.lower() not in {"buyer", "seller", "agent", "owner", "tenant", "broker", "interested"}:
                return candidate
    return None


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
    placeholders = {"property inquiry", "to be advised", "pahang (to be advised)", "not specified", "general inquiry", "n/a", "none", "null"}
    filled = sum(
        1 for k in required
        if collected_data.get(k) and str(collected_data.get(k)).strip().lower() not in placeholders
    )
    return filled / len(required)


class MultiIntentMemoryTracker:
    """
    Enterprise Conversational Multi-Intent Context & Priority Memory Tracker.
    Manages evolving customer preferences, priority queues, hybrid dual-purpose suggestions,
    and handles complex edge cases like budget contradictions, changing locations, and role switches.
    """

    @staticmethod
    def extract_intent_entities(text: str, existing_role: str = None) -> dict:
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
        elif any(k in clean for k in ["house", "terrace", "semi-d", "semi d", "bungalow", "apartment", "condo", "residence", "home", "residential", "排屋", "住宅", "住家", "半独立", "公寓"]):
            cat = "residential"
            type_label = "Residential House"
        elif any(k in clean for k in ["durian", "orchard", "land", "tanah", "kebun", "ladang", "musang king", "农业地", "果园", "地皮", "农地"]):
            cat = "agricultural"
            type_label = "Agricultural Land"
        elif any(k in clean for k in ["factory", "warehouse", "kilang", "gudang", "industrial", "工业", "厂房", "仓库"]):
            cat = "industrial"
            type_label = "Industrial Property"

        # 2. Locations (only extract explicitly mentioned locations, never default to Bentong)
        loc = None
        for town in ["bentong", "raub", "karak", "temerloh", "mentakab", "kuantan", "bukit tinggi", "janda baik", "cheroh", "tras", "lanchang", "maran", "triang", "kota bharu", "pahang"]:
            if re.search(rf'\b{re.escape(town)}\b', clean):
                loc = town.title()
                break

        # 3. Budget (MYR)
        budget = None
        price_match = re.search(r'(?:rm|myr)\s*(\d+(?:\.\d+)?)\s*(m|million|k|thousand|000|\b)|(\d+(?:\.\d+)?)\s*(m|million|k|thousand)\b', clean)
        if price_match:
            try:
                if price_match.group(1):
                    num = float(price_match.group(1))
                    unit = (price_match.group(2) or "").lower()
                else:
                    num = float(price_match.group(3))
                    unit = (price_match.group(4) or "").lower()
                if unit in ["m", "million"]:
                    budget = num * 1_000_000
                elif unit in ["k", "thousand"]:
                    budget = num * 1_000
                elif num >= 1000:
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

        # 5. Role: Only assign role when explicitly indicated or preserve existing_role (never blindly default to buyer)
        role = existing_role
        if any(k in clean for k in ["property agent", "ejen hartanah", "我是中介", "我是经纪", "我是agent", "co-broke", "cobroke"]) or re.search(r'\b(?:i\s+am\s+(?:a\s+)?agent|agent\s*/\s*broker)\b', clean):
            role = "agent"
        elif any(k in clean for k in ["sell", "selling", "list my", "jual", "出让", "想卖", "放盘", "委托出售", "property owner", "pemilik hartanah", "我是业主", "我是卖家", "send u the piece of land", "geran"]):
            role = "seller"
        elif any(k in clean for k in ["rent out", "lease out", "for rent", "bagi sewa", "sewakan", "出租", "放租", "招租"]):
            role = "landlord"
        elif any(k in clean for k in ["rent", "renting", "sewa", "租", "想要租"]):
            role = "tenant"
        elif any(k in clean for k in ["buy", "buying", "beli", "cari", "looking for", "personal buyer", "pembeli", "想买", "要买", "我是买家"]):
            role = "buyer"

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
        now_iso = datetime.datetime.utcnow().isoformat()
        req_profile = session.setdefault("requirements_profile", {})
        intent_progression = session.setdefault("intent_progression", [])
        
        active_inq = req_profile.get("active_inquiry") or {}
        retained_inqs = req_profile.get("retained_inquiries") or []
        
        # Derive existing role to preserve context across turns
        current_existing_role = (
            session.get("collected_data", {}).get("customer_category")
            or (session.get("current_agent", "").lower() if session.get("current_agent") in ["SELLER", "BUYER", "AGENT", "TENANT"] else None)
            or active_inq.get("role")
        )
        extracted = cls.extract_intent_entities(text, existing_role=current_existing_role)
        new_cat = extracted.get("category")
        new_label = extracted.get("property_type_label")
        new_loc = extracted.get("location")
        new_budget = extracted.get("budget")
        new_amp = extracted.get("power_amp")
        new_role = extracted.get("role") or current_existing_role
        
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
                "location": primary_inq["location"] or active_inq.get("location"),
                "budget": primary_inq["budget"] or active_inq.get("budget"),
                "budget_formatted": f"RM {int(primary_inq['budget']):,}" if primary_inq["budget"] else "To be advised",
                "power_amp": primary_inq["power_amp"] or active_inq.get("power_amp"),
                "role": primary_inq["role"] or current_existing_role,
                "updated_at": now_iso
            }
            for sec in secondary_inqs:
                retained_inqs.append({
                    "category": sec["category"],
                    "property_type_label": sec["property_type_label"],
                    "location": sec["location"] or active_inq.get("location"),
                    "budget": sec["budget"],
                    "budget_formatted": f"RM {int(sec['budget']):,}" if sec["budget"] else "To be advised",
                    "power_amp": sec["power_amp"],
                    "role": sec["role"] or current_existing_role,
                    "updated_at": now_iso
                })
                
            intent_progression.append({
                "timestamp": now_iso,
                "event_type": "concurrent_search",
                "title": "Multiple Concurrent Inquiries Registered",
                "description": f"Customer initiated concurrent search for {active_inq['property_type_label']} (1st Priority) and {', '.join([s['property_type_label'] for s in secondary_inqs])} (Secondary Memory).",
                "active_priority": f"{active_inq['property_type_label']} ({active_inq.get('location') or 'Unspecified'})",
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
                "location": new_loc or old_inq.get("location"),
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
                    f"Customer shifted focus to {active_inq['property_type_label']} in {active_inq.get('location') or 'Unspecified'} (Budget: {active_budget_fmt}). "
                    f"Prior inquiry for {old_inq.get('property_type_label')} in {old_inq.get('location') or 'Unspecified'} (Budget: {old_inq.get('budget_formatted', 'N/A')}) retained in memory."
                ),
                "active_priority": f"{active_inq['property_type_label']} ({active_inq.get('location') or 'Unspecified'})",
                "retained_context": f"{old_inq.get('property_type_label')} ({old_inq.get('location') or 'Unspecified'})",
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
                    "category": new_cat,
                    "property_type_label": new_label,
                    "location": new_loc,
                    "budget": new_budget,
                    "budget_formatted": f"RM {int(new_budget):,}" if new_budget else None,
                    "power_amp": new_amp,
                    "role": new_role,
                    "updated_at": now_iso
                }
                if new_cat or new_loc or new_budget:
                    intent_progression.append({
                        "timestamp": now_iso,
                        "event_type": "initial_inquiry",
                        "title": f"Initial Inquiry: {active_inq.get('property_type_label') or 'General'}",
                        "description": f"Customer initiated inquiry for {active_inq.get('property_type_label') or 'property'} in {active_inq.get('location') or 'Unspecified'}.",
                        "active_priority": f"{active_inq.get('property_type_label') or 'Inquiry'} ({active_inq.get('location') or 'Unspecified'})",
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
                if new_cat and not active_inq.get("category"):
                    active_inq["category"] = new_cat
                if new_role and not active_inq.get("role"):
                    active_inq["role"] = new_role
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
            "property_type": active_inq.get("property_type_label") or active_inq.get("property_type") or active_inq.get("category"),
            "category": active_inq.get("category"),
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
                    if session.get("seller_track"):
                        meta["seller_track"] = session.get("seller_track")
                    if session.get("buyer_track"):
                        meta["buyer_track"] = session.get("buyer_track")
                    if session.get("intake_properties"):
                        meta["intake_properties"] = session.get("intake_properties")
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


def process_persona_state_machine(phone_number: str, text: str = "", session: dict = None, conversation_history: str = "", contact_name: str = None, raw_text: str = None, images: list = None, **kwargs) -> dict:
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
    if actual_text:
        if detected_lang in ["zh", "ms"]:
            session["language"] = detected_lang
        elif detected_lang == "en" and len(actual_text.split()) >= 2:
            session["language"] = "en"
        elif not session.get("language"):
            session["language"] = detected_lang
    customer_lang = session.get("language", detected_lang)

    # 1. Payload Name Hook & Self-Introduction Extraction — populate name if valid
    if collected_data.get("name") and not is_valid_name(str(collected_data.get("name"))):
        collected_data.pop("name", None)
    self_intro_name = extract_self_introduced_name(raw_text)
    if self_intro_name:
        collected_data["name"] = self_intro_name
    elif contact_name and is_valid_name(contact_name) and not collected_data.get("name"):
        collected_data["name"] = contact_name.strip()

    current_user_name = collected_data.get("name") or (contact_name if is_valid_name(contact_name) else None)
    raw_lower = raw_text.strip().lower()

    # 1.5 Post-Handover Concierge Mode:
    # Once handover has been initiated for this conversation, lock intent, state, and temperature.
    # Only reply if the customer is asking for more information or thank the customer for contacting.
    if session.get("handover_completed"):
        locked_intent = (
            session.get("locked_intent")
            or session.get("current_agent")
            or collected_data.get("customer_category")
            or "BUYER"
        )
        locked_role_lower = str(locked_intent).strip().lower()
        collected_data["customer_category"] = locked_role_lower
        session["current_agent"] = str(locked_intent).strip().upper()
        session["state"] = "HANDED_OVER"
        session["handover"] = False
        session["post_handover_concierge"] = True

        assigned_specialist = session.get("assigned_agent_name") or "our senior property specialist"
        assigned_phone = session.get("assigned_agent_phone") or ""
        specialist_display = (
            f"{assigned_specialist} ({assigned_phone})"
            if assigned_phone and assigned_phone not in assigned_specialist
            else assigned_specialist
        )

        has_question_mark = ("?" in raw_lower or "？" in raw_lower)
        interrogative_pattern = re.compile(
            r"\b(?:what|how|where|when|which|who|why|can\s+you|could\s+you|would\s+you|"
            r"do\s+you|does\s+it|is\s+there|are\s+there|is\s+it|may\s+i|can\s+i|"
            r"tell\s+me|more\s+info|send\s+me|show\s+me|share\s+the|any\s+update|"
            r"berapa|macam\s+mana|bila|boleh\s+tanya|ada\s+tak|apa\s+itu)\b"
        )
        zh_interrogatives = ["什么", "多少", "怎么", "哪里", "请问", "吗", "呢", "几多", "有没有", "可不可以", "能不能"]
        is_asking_for_more_info = (
            has_question_mark
            or bool(interrogative_pattern.search(raw_lower))
            or any(q in raw_lower for q in zh_interrogatives)
        )

        if is_asking_for_more_info:
            cached_prop = session.get("interested_property")
            llm_kwargs = dict(kwargs)
            llm_kwargs["customer_language"] = customer_lang
            if images:
                llm_kwargs["images"] = images[:1]
            concierge_analysis = generate_conversational_response(
                text=raw_text,
                cached_property=cached_prop,
                available_properties=[],
                hybrid_properties=[],
                memory_context=session.get("requirements_profile") or {},
                conversation_history=conversation_history,
                collected_data=dict(collected_data),
                customer_name=current_user_name,
                is_seller=(locked_role_lower in ["seller", "owner"]),
                **llm_kwargs
            )
            concierge_resp = concierge_analysis.get("response") or ""
            # Re-enforce lock on category, state, and handover flag
            collected_data["customer_category"] = locked_role_lower
            session["current_agent"] = str(locked_intent).strip().upper()
            session["state"] = "HANDED_OVER"
            session["handover"] = False
            return {
                "response": concierge_resp,
                "handover": False,
                "promises_handover": False,
                "post_handover_concierge": True,
                "images_to_send": [],
                "updated_session": session
            }
        else:
            name_suffix = f", {current_user_name}" if current_user_name else ""
            if customer_lang == "zh":
                thank_you_resp = (
                    f"非常感谢您的联系与补充信息{f'，{current_user_name}' if current_user_name else ''}！😊 "
                    f"我们已将您的最新讯息记录并转交予您的专属顾问 {specialist_display}，专员将会尽快与您直接跟进。"
                )
            elif customer_lang == "ms":
                thank_you_resp = (
                    f"Terima kasih kerana menghubungi Home IHC{name_suffix}! 😊 "
                    f"Maklumat tambahan anda telah direkodkan untuk perunding kanan kami {specialist_display}, "
                    f"yang akan membantu anda secara langsung sebentar lagi."
                )
            else:
                thank_you_resp = (
                    f"Thank you for contacting Home IHC{name_suffix}! 😊 "
                    f"We have noted your message for our senior specialist {specialist_display}, "
                    f"who will assist you directly shortly."
                )
            return {
                "response": thank_you_resp,
                "handover": False,
                "promises_handover": False,
                "post_handover_concierge": True,
                "images_to_send": [],
                "updated_session": session
            }

    # Reset legacy non-handover completed state if not locked by handover_completed
    if session.get("state") == "COMPLETED" or session.get("handover"):
        session["state"] = "IN_PROGRESS"
        session["handover"] = False

    # Step 4: Early Out-of-Scope Interception (Job vacancies, non-property queries, personal loans)
    ooc_keywords = [
        "kerja kosong", "jawatan kosong", "job vacancy", "job offer", "hiring", "apply job",
        "招聘", "找工作", "招人吗", "请人", "应聘", "cleaning service", "car wash", "personal loan",
        "pinjaman wang", "insurance agent", "internship", "part time job", "兼职"
    ]
    if any(kw in raw_lower for kw in ooc_keywords):
        session["state"] = "COMPLETED"
        session["handover"] = True
        session["is_out_of_context"] = True
        session["current_agent"] = "OUT_OF_SCOPE"
        ooc_resp = get_multilingual_out_of_scope_redirect(customer_lang, current_user_name)
        MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
        return {
            "response": ooc_resp,
            "handover": True,
            "intent": "OUT_OF_SCOPE",
            "assignee_phone": IRENE_MAIN_PHONE,
            "images_to_send": [],
            "updated_session": session
        }

    # 2. Dynamic Semantic Turn Classification & Step 1 / 2 Category Selection Detection BEFORE Property Matching
    turn_intent = classify_turn_intent(
        prompt=raw_text,
        conversation_history=conversation_history,
        has_document=bool(session.get("latest_document_extract") or images),
        document_extract=session.get("latest_document_extract")
    )
    session["turn_intent"] = turn_intent

    # Manage Persistent Dual-Track State Machine
    seller_track = session.setdefault("seller_track", {})
    buyer_track = session.setdefault("buyer_track", {})

    is_existing_seller = (
        seller_track.get("status") == "active"
        or collected_data.get("customer_category") == "seller"
        or session.get("current_agent") == "SELLER"
    )

    # Step 1 / 2 Category Selection Detection
    explicit_category = None
    if re.search(r'^(?:1|1\.|1\)|🙋?\s*(?:personal\s+buyer|buyer|pembeli|买家|个人买家))$', raw_lower) or any(
        phrase in raw_lower for phrase in ["personal buyer", "pembeli peribadi", "个人买家", "我是买家", "i am a buyer", "i am buyer"]
    ):
        explicit_category = "buyer"
    elif re.search(r'^(?:2|2\.|2\)|🤝?\s*(?:property\s+agent|agent|broker|ejen|中介|房产经纪))$', raw_lower) or any(
        phrase in raw_lower for phrase in ["property agent", "agent / broker", "ejen hartanah", "我是中介", "我是agent", "co-broke", "cobroke", "are u agent"]
    ):
        explicit_category = "agent"
    elif re.search(r'^(?:3|3\.|3\)|🏡?\s*(?:seller|property\s+owner|owner|penjual|pemilik|卖家|业主))$', raw_lower) or any(
        phrase in raw_lower for phrase in ["property owner", "pemilik hartanah", "我是业主", "我是卖家", "i am owner", "i am seller", "委托出售", "send u the piece of land"]
    ):
        explicit_category = "seller"

    is_seller_or_agent_turn = (
        explicit_category in ["seller", "agent"]
        or turn_intent in ["seller_intake", "agent_inquiry", "agent"]
        or is_existing_seller
        or collected_data.get("customer_category") in ["seller", "agent"]
        or session.get("current_agent") in ["SELLER", "AGENT"]
    )

    # 2.5 Match Specific Property in Database ONLY for Buyer / General turns (never inject inventory into Seller/Agent turns)
    matched_prop = None
    if not is_seller_or_agent_turn:
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

    # Has any specific property information been provided in this message or session?
    # (Exclude generic role words like 'property', 'properties', 'hartanah' so 'Property agent' triggers Step 2 questions)
    has_msg_property_info = bool(
        matched_prop or _property_entity_detected or session.get("latest_document_extract") or images
        or any(k in raw_lower for k in [
            "bentong", "raub", "karak", "temerloh", "kuantan", "mentakab", "pahang", "kota bharu",
            "tanah", "land", "durian", "rumah", "house", "semi-d", "bungalow", "kedai", "shop", "factory",
            "acre", "ekar", "sqft", "geran", "rm", "budget", "bajet", "price", "harga",
            "condo", "apartment", "residence",
            "房产", "产业", "地皮", "排屋", "店面", "租", "买", "卖", "buy", "sell", "rent"
        ])
    )

    if explicit_category == "seller":
        seller_track["status"] = "active"
        seller_track["last_active"] = datetime.datetime.utcnow().isoformat()
        session["current_agent"] = "SELLER"
        collected_data["customer_category"] = "seller"
        for stale_k in ("buyer_budget", "buyer_location", "buyer_property_type", "property_of_interest"):
            collected_data.pop(stale_k, None)
    elif explicit_category == "agent":
        agent_track = session.setdefault("agent_track", {})
        agent_track["status"] = "active"
        agent_track["last_active"] = datetime.datetime.utcnow().isoformat()
        session["current_agent"] = "AGENT"
        collected_data["customer_category"] = "agent"
        for stale_k in ("buyer_budget", "buyer_location", "buyer_property_type", "property_of_interest"):
            collected_data.pop(stale_k, None)
    elif explicit_category == "buyer":
        buyer_track["status"] = "active"
        buyer_track["last_active"] = datetime.datetime.utcnow().isoformat()
        session["current_agent"] = "BUYER"
        collected_data["customer_category"] = "buyer"
    elif turn_intent == "seller_intake" or (is_existing_seller and turn_intent not in ["buyer_search", "agent_inquiry", "agent"]):
        seller_track["status"] = "active"
        seller_track["last_active"] = datetime.datetime.utcnow().isoformat()
        if session.get("latest_document_extract"):
            intake_list = seller_track.setdefault("intake_properties", [])
            intake_list.append(session.get("latest_document_extract"))
            session["intake_properties"] = intake_list
        session["current_agent"] = "SELLER"
        collected_data["customer_category"] = "seller"
        for stale_k in ("buyer_budget", "buyer_location", "buyer_property_type", "property_of_interest"):
            collected_data.pop(stale_k, None)
    elif turn_intent == "buyer_search":
        buyer_track["status"] = "active"
        buyer_track["last_active"] = datetime.datetime.utcnow().isoformat()
        session["current_agent"] = "BUYER"
        collected_data["customer_category"] = "buyer"
    elif turn_intent in ["agent_inquiry", "agent"]:
        agent_track = session.setdefault("agent_track", {})
        agent_track["status"] = "active"
        agent_track["last_active"] = datetime.datetime.utcnow().isoformat()
        session["current_agent"] = "AGENT"
        collected_data["customer_category"] = "agent"
        for stale_k in ("buyer_budget", "buyer_location", "buyer_property_type", "property_of_interest"):
            collected_data.pop(stale_k, None)

    # Step 2: Role assigned and NO property info provided -> ask premature questions
    if explicit_category and not has_msg_property_info:
        collected_data["introduced"] = True
        session["introduced"] = True
        session["collected_data"] = collected_data
        session["current_agent"] = explicit_category.upper()
        premature_msg = get_multilingual_premature_questions(explicit_category, customer_lang, current_user_name)
        MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
        return {
            "response": premature_msg,
            "handover": False,
            "images_to_send": [],
            "updated_session": session
        }

    # Step 1: Customer Ingress without prior introduction, category, or property info -> Greet & present Step 2 categories
    has_assistant_in_history = bool(
        conversation_history and (
            "Assistant:" in conversation_history or
            "AI:" in conversation_history or
            "Agent:" in conversation_history or
            "Irene Leong" in conversation_history or
            "mecard.my" in conversation_history
        )
    )
    is_fresh_ingress = not has_assistant_in_history and not session.get("introduced")
    greeting_keywords = [
        "hi", "hello", "hey", "halo", "salam", "selamat sejahtera", "selamat pagi",
        "selamat petang", "selamat tengahari", "selamat malam", "hai", "good morning",
        "good afternoon", "good evening", "good day", "您好", "你好", "早安", "午安", "晚安",
        "pm", "pm me", "info", "test", "start", "menu"
    ]
    raw_cleaned = re.sub(r'[\s,!.?~]+', ' ', raw_lower).strip()
    words = raw_cleaned.split()
    action_keywords = ["check", "find", "look", "cari", "beli", "jual", "sewa", "buy", "sell", "rent", "want", "need", "nak", "ada", "mau", "想", "要", "问"]
    is_pure_greeting = raw_cleaned in greeting_keywords or (
        len(words) <= 3 and any(words[0] == kw or raw_cleaned.startswith(kw) for kw in greeting_keywords)
        and not any(act in raw_lower for act in action_keywords)
    )
    is_greeting_or_vague = is_pure_greeting or (
        turn_intent == "general" and len(words) <= 2 and not any(act in raw_lower for act in action_keywords)
    )
    if is_fresh_ingress and is_greeting_or_vague and not has_msg_property_info and not explicit_category:
        collected_data["introduced"] = True
        session["introduced"] = True
        session["collected_data"] = collected_data
        greeting_msg = get_multilingual_greeting(customer_lang, current_user_name)
        MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
        return {
            "response": greeting_msg,
            "handover": False,
            "images_to_send": [],
            "updated_session": session
        }

    # Conversation 71 Protocol: Unidentified Listing & Advertisement Inquiry
    is_unidentified_inquiry = (turn_intent == "unidentified_listing") or (
        session.get("unidentified_listing_turns", 0) >= 1 and not matched_prop and not _property_entity_detected
    )
    if not matched_prop and is_unidentified_inquiry:
        unidentified_turns = session.get("unidentified_listing_turns", 0) + 1
        session["unidentified_listing_turns"] = unidentified_turns
        
        if unidentified_turns >= 2:
            # Turn 2+: Anti-Looping Handover Guard -> Transfer immediately to Ah Tuck (+60129663589)
            session["state"] = "COMPLETED"
            session["handover"] = True
            handover_msg = get_multilingual_ah_tuck_handover(customer_lang, current_user_name)
            MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
            return {
                "response": handover_msg,
                "handover": True,
                "assignee_email": AH_TUCK_EMAIL,
                "images_to_send": [],
                "updated_session": session
            }
        else:
            # Turn 1: Listing Disambiguation Protocol -> Ask for ad screenshot/photo/link
            disambig_msg = get_multilingual_disambiguation_request(customer_lang, current_user_name)
            MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
            return {
                "response": disambig_msg,
                "handover": False,
                "images_to_send": [],
                "updated_session": session
            }

    is_seller = (
        seller_track.get("status") == "active"
        or collected_data.get("customer_category") == "seller"
        or session.get("current_agent") == "SELLER"
        or turn_intent == "seller_intake"
    )

    if is_seller:
        # A seller is listing their own property; purge any mistakenly cached inventory property
        session.pop("interested_property", None)
        cached_prop = None
    else:
        cached_prop = session.get("interested_property")
        # If no cached property and not a seller, try to resolve from conversation history
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
    
    # Sync collected_data with active_inquiry without polluting seller/agent tracks or injecting placeholders
    _placeholders = {"property inquiry", "to be advised", "pahang (to be advised)", "not specified", "general inquiry", "none", "null"}
    _active_label = active_inq.get("property_type_label")
    _active_loc = active_inq.get("location")
    _active_budget = active_inq.get("budget")
    _active_role = active_inq.get("role")
    _curr_cat = (collected_data.get("customer_category") or session.get("current_agent") or "").lower()

    if _curr_cat in ["seller", "owner", "agent", "broker"] or is_seller:
        if _active_label and str(_active_label).strip().lower() not in _placeholders and not collected_data.get("property_type"):
            collected_data["property_type"] = _active_label
        if _active_loc and str(_active_loc).strip().lower() not in _placeholders and not collected_data.get("location"):
            collected_data["location"] = _active_loc
        if _active_budget and _curr_cat in ["seller", "owner"] and not collected_data.get("asking_price"):
            collected_data["asking_price"] = active_inq.get("budget_formatted")
    else:
        if _active_label and str(_active_label).strip().lower() not in _placeholders:
            collected_data["buyer_property_type"] = _active_label
        if _active_loc and str(_active_loc).strip().lower() not in _placeholders:
            collected_data["buyer_location"] = _active_loc
        if _active_budget:
            collected_data["buyer_budget"] = active_inq.get("budget_formatted")
        if _active_role and _curr_cat not in ["seller", "agent"]:
            collected_data["customer_category"] = _active_role

    # Check if user explicitly wants to switch criteria
    is_switching_context = is_intent_switch or any(phrase in raw_text.lower() for phrase in [
        "other", "another", "different", "instead", "switch to", "what else",
        "durian land", "commercial", "industrial", "house in", "shop in", "land in",
        "店面", "铺位", "店", "shop", "commercial", "rumah kedai"
    ]) and not any(p in raw_text.lower() for p in ["picture", "photo", "gambar", "foto", "more picture", "more photo", "detail"])

    if is_switching_context:
        session["interested_property"] = None
        cached_prop = None

    if turn_intent == "seller_intake":
        # Suppress buyer inventory search during seller intake
        available_properties = []
        hybrid_properties = []
        cached_prop = None
        session["interested_property"] = None
    elif not cached_prop:
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
    if images:
        llm_kwargs["images"] = images
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
        is_seller=is_seller,
        **llm_kwargs
    )

    # Merge extracted data
    for k, v in llm_analysis.get("extracted_data", {}).items():
        if v and str(v).lower() not in ["null", "none", ""]:
            collected_data[k] = v

    is_out_of_context = llm_analysis.get("is_out_of_context", False)

    # Heuristic guard: Detect explicit out-of-scope queries (e.g. job vacancies, non-property queries)
    has_known_property_info = bool(
        matched_prop or _property_entity_detected or session.get("latest_document_extract")
        or collected_data.get("buyer_property_type") or collected_data.get("property_type")
        or collected_data.get("buyer_location") or collected_data.get("location")
    )
    ooc_keywords = [
        "kerja kosong", "jawatan kosong", "job vacancy", "job offer", "hiring", "apply job",
        "招聘", "找工作", "招人吗", "请人", "应聘", "cleaning service", "car wash", "personal loan",
        "pinjaman wang", "insurance agent", "internship", "part time job", "兼职"
    ]
    if not has_known_property_info and any(kw in raw_text.lower() for kw in ooc_keywords):
        is_out_of_context = True

    if is_out_of_context:
        session["state"] = "COMPLETED"
        session["handover"] = True
        session["is_out_of_context"] = True
        session["current_agent"] = "OUT_OF_SCOPE"
        ooc_resp = get_multilingual_out_of_scope_redirect(customer_lang, current_user_name)
        MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)
        return {
            "response": ooc_resp,
            "handover": True,
            "intent": "OUT_OF_SCOPE",
            "assignee_phone": IRENE_MAIN_PHONE,
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
    if is_seller:
        # Sellers provide photos to Home IHC; do not dispatch inventory listing photos to a seller
        images_to_send = []
    elif is_photo_request and cached_prop:
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

    # Step 3: Qualified Handover Detection (sufficient information gathered)
    current_role = (collected_data.get("customer_category") or session.get("current_agent") or "buyer").lower()
    is_qualified_lead = False
    if current_role == "buyer":
        has_loc = bool(collected_data.get("buyer_location") or collected_data.get("location"))
        has_type = bool(collected_data.get("buyer_property_type") or collected_data.get("property_type"))
        has_budget = bool(collected_data.get("buyer_budget") or collected_data.get("budget"))
        if has_loc and has_type and has_budget:
            is_qualified_lead = True
    elif current_role in ["seller", "owner"]:
        has_loc = bool(collected_data.get("seller_location") or collected_data.get("location"))
        has_type = bool(collected_data.get("seller_property_type") or collected_data.get("property_type"))
        has_price = bool(collected_data.get("asking_price"))
        if has_loc and has_type and has_price:
            is_qualified_lead = True
    elif current_role in ["agent", "broker"]:
        has_agent_info = bool(collected_data.get("company_name") or collected_data.get("ren_number"))
        has_reqs = bool(collected_data.get("coverage_area") or collected_data.get("location") or collected_data.get("property_type"))
        if has_agent_info and has_reqs:
            is_qualified_lead = True

    if is_qualified_lead:
        session["is_qualified_lead"] = True

    handover_promised = is_handover_promised(response_text)
    promises_handover = bool(llm_analysis.get("promises_handover"))
    if user_wants_immediate_human:
        handover = True
        name_str = f" {current_user_name}" if current_user_name else ""
        prop_str = f" for {cached_prop.get('title')}" if cached_prop else ""
        if "senior" not in response_text.lower() and "specialist" not in response_text.lower() and "representative" not in response_text.lower() and "专员" not in response_text and "pegawai" not in response_text.lower():
            response_text = get_multilingual_handover_wrapup(customer_lang, current_user_name, cached_prop.get('title') if cached_prop else None)
        session["state"] = "COMPLETED"
    elif user_books_cached_viewing or has_viewing_confirmation or bool(asked_meeting):
        handover = True
        session["state"] = "COMPLETED"
    elif handover_promised or promises_handover:
        handover = True
        session["state"] = "COMPLETED"

    if handover:
        session["handover"] = True
        session["state"] = "COMPLETED"

    # Track viewing acknowledgement status if user expressed inspection intent
    if user_books_cached_viewing or bool(asked_meeting) or any(k in raw_text.lower() for k in ["viewing", "看房", "睇楼", "tengok rumah", "tengok tanah", "arrange viewing", "schedule viewing"]):
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
    resolved_agent = collected_data.get("customer_category") or session.get("current_agent") or "BUYER"
    session["current_agent"] = str(resolved_agent).upper()
    session["collected_data"] = collected_data

    # Persist updated multi-intent memory and profile to Customer table
    MultiIntentMemoryTracker.persist_customer_memory(phone_number, session)

    return {
        "response": response_text,
        "handover": handover,
        "promises_handover": promises_handover or handover_promised,
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
    est_input_tokens = int(total_chars / 2.5)

    # If approaching limit, prune history to most recent exchanges
    if est_input_tokens > 1300 and history_to_use:
        hist_lines = [l for l in history_to_use.split("\n") if l.strip()]
        history_to_use = "\n".join(hist_lines[-3:])
        total_chars = len(system_prompt) + len(history_to_use) + len(text or "")
        est_input_tokens = int(total_chars / 2.5)

    images = kwargs.get("images") or []
    # Strict bounded output token budget ensuring prompt + completion never exceeds 2040 tokens
    max_allowed = max(50, 2030 - est_input_tokens)
    target_tokens = 450 if images else 350
    safe_max_tokens = min(target_tokens, max_allowed)

    messages = [
        {"role": "system", "content": system_prompt}
    ]
    if history_to_use:
        messages.append({"role": "system", "content": f"Recent Conversation History:\n{history_to_use}"})
    
    if images:
        user_content = []
        user_prompt_text = (text or "").strip() or "Please analyze the attached property document / land title / image and advise."
        user_content.append({"type": "text", "text": user_prompt_text})
        # Cap vision payload to 1 image per completion call to prevent vLLM 2048-token context overflow on multi-photo batches
        for img in images[:1]:
            if isinstance(img, str):
                if img.startswith("http://") or img.startswith("https://") or img.startswith("data:"):
                    user_content.append({"type": "image_url", "image_url": {"url": img}})
                else:
                    user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})
            elif isinstance(img, dict) and img.get("url"):
                user_content.append({"type": "image_url", "image_url": {"url": img["url"]}})
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": text or ""})

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
                match = re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)', content, re.DOTALL)
                if match:
                    raw_str = match.group(1)
                    try:
                        decoded_resp = json.loads(f'"{raw_str}"')
                    except Exception:
                        decoded_resp = raw_str.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
                    parsed = {"response": decoded_resp.strip()}
        
        if parsed and isinstance(parsed, dict) and parsed.get("response"):
            # Unescape raw newlines if somehow present in string
            if isinstance(parsed["response"], str) and "\\n" in parsed["response"] and "\n" not in parsed["response"]:
                parsed["response"] = parsed["response"].replace("\\n", "\n").replace('\\"', '"')
            # Normalize sparse keys with safe defaults
            parsed.setdefault("intent", "general")
            parsed.setdefault("asked_photos", False)
            parsed.setdefault("asked_specs", False)
            parsed.setdefault("asked_meeting", False)
            parsed.setdefault("promises_handover", False)
            parsed.setdefault("asked_alternatives", False)
            parsed.setdefault("is_out_of_context", False)
            parsed.setdefault("new_constraints", {})
            parsed.setdefault("extracted_data", parsed.get("extracted", {}))
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
                    max_tokens=250,
                    timeout=20.0
                )
                retry_content = retry_resp.choices[0].message.content
                retry_parsed = _parse_json_from_llm(retry_content)
                if retry_parsed and isinstance(retry_parsed, dict) and retry_parsed.get("response"):
                    if isinstance(retry_parsed["response"], str) and "\\n" in retry_parsed["response"] and "\n" not in retry_parsed["response"]:
                        retry_parsed["response"] = retry_parsed["response"].replace("\\n", "\n").replace('\\"', '"')
                    retry_parsed.setdefault("intent", "general")
                    retry_parsed.setdefault("asked_photos", False)
                    retry_parsed.setdefault("asked_specs", False)
                    retry_parsed.setdefault("asked_meeting", False)
                    retry_parsed.setdefault("promises_handover", False)
                    retry_parsed.setdefault("asked_alternatives", False)
                    retry_parsed.setdefault("is_out_of_context", False)
                    retry_parsed.setdefault("new_constraints", {})
                    retry_parsed.setdefault("extracted_data", retry_parsed.get("extracted", {}))
                    return retry_parsed
            except Exception as retry_err:
                logger.error(f"Emergency retry also failed: {retry_err}")

        lang = kwargs.get("customer_language") or detect_customer_language(text)
        # Resilient fallback: Treat as ongoing conversation if assistant spoke OR if role/images/property already provided
        is_seller_flag = kwargs.get("is_seller", False)
        assistant_spoke = bool(
            is_seller_flag or images or collected_data.get("customer_category") or (
                conversation_history and (
                    "Assistant:" in conversation_history or
                    "AI:" in conversation_history or
                    "Agent:" in conversation_history or
                    "Irene Leong" in conversation_history or
                    "mecard.my" in conversation_history
                )
            )
        )
        effective_history = (conversation_history or "Active inquiry") if assistant_spoke else None
        fallback_msg = get_multilingual_fallback(lang, effective_history, is_seller=is_seller_flag)
        return {
            "intent": "general",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "promises_handover": False,
            "viewing_confirmed": False,
            "viewing_date_text": None,
            "asked_alternatives": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "response": fallback_msg
        }

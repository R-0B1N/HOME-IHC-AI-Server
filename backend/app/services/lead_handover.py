"""
Domain Service for Dynamic Hot Lead Handover and Agent Specialization Scoring.
Encapsulates scoring algorithms, candidate selection, tie-break remark generation,
and multi-channel WhatsApp / Chatwoot notification dispatch.
"""

import os
import logging
import re
from typing import Any, Dict, List, Optional, Union

from app.db.models import SessionLocal, User
from app.services.chatwoot import (
    apply_label,
    set_priority,
    get_or_create_contact,
    create_conversation,
    send_private_note,
    send_whatsapp_contact,
    send_whatsapp_template,
    update_conversation_status,
    assign_agent,
    get_agent_id_by_email,
)
from app.services.db_services import get_active_agents_and_employees

logger = logging.getLogger(__name__)

CONFIGURED_LOCATIONS = [
    "Bentong", "Temerloh", "Karak", "Raub", "Kuantan",
    "Mentakab", "Pahang", "Selangor", "KL"
]

CONFIGURED_PROPERTY_TYPES = [
    "Rental", "Residential", "Commercial", "Land / Agriculture",
    "Industrial", "Durian Land", "Factory"
]

DEFAULT_FALLBACK_ADMIN_NUMBERS = ["+601165144931", "+14709202239"]

_SCORE_PLACEHOLDERS = {
    "",
    "to be advised",
    "pahang (to be advised)",
    "not specified",
    "general inquiry",
    "n/a",
    "none",
    "null",
    "unknown",
    "to be discussed in meeting",
    "commercial / residential / land",
}

_SALE_TYPES = {
    "residential",
    "commercial",
    "land / agriculture",
    "industrial",
    "durian land",
    "factory",
    "land",
    "agriculture",
}


def _strip_score_placeholders(location, property_type, raw_text):
    """Defaults such as 'Pahang (To be advised)' must not earn a routing point."""
    def _clean(value):
        text = str(value or "").strip()
        if text.lower() in _SCORE_PLACEHOLDERS:
            return ""
        return text

    location = _clean(location)
    property_type = _clean(property_type)
    raw_text = str(raw_text or "")
    for placeholder in _SCORE_PLACEHOLDERS:
        if placeholder and placeholder in raw_text.lower():
            raw_text = re.sub(re.escape(placeholder), " ", raw_text, flags=re.IGNORECASE)
    return location, property_type, raw_text


def _agent_types(agent):
    if isinstance(agent, dict):
        return agent.get("assigned_property_types") or []
    return (
        getattr(agent, "assigned_property_types", None)
        or getattr(agent, "specialization_property_types", None)
        or []
    )


def intent_compatible(intent: str, agent) -> bool:
    """A rental-only agent does not take a seller or a buyer. A sale-only agent does not take a renter."""
    types = {str(item or "").strip().lower() for item in _agent_types(agent) if item}
    intent_clean = (intent or "").strip().lower()
    has_sale = bool(types & _SALE_TYPES)
    has_rental = "rental" in types
    if intent_clean in {"renter", "tenant"}:
        return has_rental
    if intent_clean in {"landlord"}:
        return has_rental or has_sale
    if intent_clean in {"seller", "owner", "buyer"}:
        return has_sale
    return False


class AgentSpecializationScorer:
    """
    Evaluates and scores an agent's suitability based on how many lead criteria
    (location, property type, and raw inquiry keywords) match their assigned specializations.
    """

    def __init__(
        self,
        configured_locations: Optional[List[str]] = None,
        configured_property_types: Optional[List[str]] = None,
    ):
        self.configured_locations = configured_locations or CONFIGURED_LOCATIONS
        self.configured_property_types = configured_property_types or CONFIGURED_PROPERTY_TYPES

    def calculate_score(
        self,
        agent: Any,
        lead_location_or_data: Union[Dict[str, Any], str, None] = None,
        lead_property_type: str = "",
        raw_inquiry_text: str = "",
    ) -> int:
        """
        Scores an agent based on assigned_locations and assigned_property_types.
        Accepts agent as dict or ORM object, and lead data as dict or individual strings.
        Returns integer hit count.
        """
        if not agent:
            return 0

        # Support dict or ORM agent
        if isinstance(agent, dict):
            assigned_locs = agent.get("assigned_locations") or []
            assigned_ptypes = agent.get("assigned_property_types") or []
        else:
            assigned_locs = (
                getattr(agent, "assigned_locations", None)
                or getattr(agent, "specialization_locations", None)
                or []
            )
            assigned_ptypes = (
                getattr(agent, "assigned_property_types", None)
                or getattr(agent, "specialization_property_types", None)
                or []
            )

        # Support lead_data dict as second arg or individual strings
        if isinstance(lead_location_or_data, dict):
            lead_data = lead_location_or_data
            lead_location = (
                lead_data.get("city")
                or lead_data.get("location")
                or lead_data.get("state")
                or ""
            )
            cats = lead_data.get("property_category") or []
            lead_property_type = (
                cats[0]
                if isinstance(cats, list) and cats
                else (cats if isinstance(cats, str) else "")
            )
            raw_inquiry_text = (
                lead_data.get("inquiry_text") or lead_data.get("raw_text") or ""
            )
        else:
            lead_location = lead_location_or_data or ""

        lead_location, lead_property_type, raw_inquiry_text = _strip_score_placeholders(
            lead_location, lead_property_type, raw_inquiry_text
        )

        location_hits, type_hits = self.score_parts(
            assigned_locs,
            assigned_ptypes,
            lead_location,
            lead_property_type,
            raw_inquiry_text,
        )
        return location_hits + type_hits

    @staticmethod
    def score_parts(assigned_locs, assigned_ptypes, lead_location, lead_property_type, raw_inquiry_text):
        """Separate town hits from property-type hits. A single town hit is not enough to assign."""
        lead_location, lead_property_type, raw_inquiry_text = _strip_score_placeholders(
            lead_location, lead_property_type, raw_inquiry_text
        )
        searchable_text = (
            f"{lead_location or ''} {lead_property_type or ''} {raw_inquiry_text or ''}".lower()
        )
        location_hits = 0
        type_hits = 0
        for loc in assigned_locs or []:
            if not loc or not isinstance(loc, str):
                continue
            loc_clean = loc.strip().lower()
            if not loc_clean or loc_clean in _SCORE_PLACEHOLDERS:
                continue
            if (lead_location and loc_clean in lead_location.lower()) or (loc_clean in searchable_text):
                location_hits += 1
        for ptype in assigned_ptypes or []:
            if not ptype or not isinstance(ptype, str):
                continue
            ptype_clean = ptype.strip().lower()
            if not ptype_clean or ptype_clean in _SCORE_PLACEHOLDERS:
                continue
            matched = False
            if (lead_property_type and ptype_clean in lead_property_type.lower()) or (ptype_clean in searchable_text):
                matched = True
            elif ptype_clean == "land / agriculture" and (
                any(k in searchable_text for k in ["agriculture", "tanah", "kebun", "ladang", "pertanian"])
                or ("land" in searchable_text and "durian" not in searchable_text)
            ):
                matched = True
            elif ptype_clean == "durian land" and any(
                k in searchable_text for k in ["durian", "musang king", "black thorn", "d24"]
            ):
                matched = True
            if matched:
                type_hits += 1
        return location_hits, type_hits


class LeadHandoverService:
    """
    Domain service executing dynamic hot lead handover routing:
    - Queries active agents/employees.
    - Scores each candidate with AgentSpecializationScorer.
    - Resolves winner(s), co-broke agent cases, ties with shared case remarks, or fallback admin lines.
    - Dispatches WhatsApp template alerts to staff and contact cards to customers.
    - Posts internal private notes and updates Chatwoot status/labels.
    """

    def __init__(
        self,
        scorer: Optional[AgentSpecializationScorer] = None,
        get_active_agents_func=None,
        send_template_func=None,
        send_contact_func=None,
        send_private_note_func=None,
        apply_label_func=None,
        set_priority_func=None,
        update_status_func=None,
        get_or_create_contact_func=None,
        create_conversation_func=None,
        session_factory=None,
        default_fallback_admins: Optional[List[str]] = None,
        assign_agent_func=None,
        get_agent_id_func=None,
    ):
        self.scorer = scorer or AgentSpecializationScorer()
        self.get_active_agents_func = get_active_agents_func or get_active_agents_and_employees
        self.send_template_func = send_template_func or send_whatsapp_template
        self.send_contact_func = send_contact_func or send_whatsapp_contact
        self.send_private_note_func = send_private_note_func or send_private_note
        self.apply_label_func = apply_label_func or apply_label
        self.set_priority_func = set_priority_func or set_priority
        self.update_status_func = update_status_func or update_conversation_status
        self.get_or_create_contact_func = get_or_create_contact_func or get_or_create_contact
        self.create_conversation_func = create_conversation_func or create_conversation
        self.session_factory = session_factory or SessionLocal
        self.default_fallback_admins = default_fallback_admins or DEFAULT_FALLBACK_ADMIN_NUMBERS
        self.assign_agent_func = assign_agent_func or assign_agent
        self.get_agent_id_func = get_agent_id_func or get_agent_id_by_email

    def get_admin_recipients(self, db: Optional[Any] = None) -> List[Dict[str, str]]:
        """
        Dynamically resolves active admin recipients.
        Irene Leong (+601165144931) is ALWAYS primary at index 0.
        Followed by all other active admin users from crm_users (role == 'admin', is_active == True).
        """
        irene_phone = "+601165144931"
        recipients = [
            {"phone": irene_phone, "name": "Irene Leong (Main Number)"}
        ]
        
        seen_phones = {"+601165144931", "601165144931", "01165144931"}
        
        if db is not None:
            try:
                db_admins = db.query(User).filter(
                    User.is_active == True,
                    User.role == "admin",
                    User.phone_number.isnot(None),
                    User.phone_number != "",
                ).all()
                for adm in db_admins:
                    raw_phone = adm.phone_number.strip()
                    norm_phone = raw_phone.replace(" ", "").replace("-", "")
                    if "123456789" in norm_phone or "0000000" in norm_phone:
                        continue
                    if norm_phone not in seen_phones:
                        seen_phones.add(norm_phone)
                        adm_name = (
                            getattr(adm, "full_name", None)
                            or getattr(adm, "username", "Admin")
                        )
                        recipients.append({"phone": raw_phone, "name": f"{adm_name} (Admin)"})
            except Exception as e:
                logger.warning(f"Could not query active admin users from DB: {e}")
                
        for fallback_phone in self.default_fallback_admins:
            norm_fb = fallback_phone.replace(" ", "").replace("-", "")
            if norm_fb not in seen_phones:
                seen_phones.add(norm_fb)
                recipients.append({"phone": fallback_phone, "name": f"Admin ({fallback_phone})"})
                
        return recipients

    def _assign_verified(self, conversation_id, agent) -> bool:
        """True only when Chatwoot resolved the agent's email and assign_agent succeeded."""
        if not conversation_id or agent is None:
            return False
        email = agent.get("email") if isinstance(agent, dict) else getattr(agent, "email", None)
        if not email:
            return False
        try:
            agent_id = self.get_agent_id_func(email)
        except Exception as exc:
            logger.warning(f"Chatwoot agent lookup failed for {email}: {exc}")
            return False
        if not agent_id:
            return False
        try:
            return bool(self.assign_agent_func(conversation_id, agent_id))
        except Exception as exc:
            logger.warning(f"Chatwoot assign_agent failed for {email}: {exc}")
            return False

    def _alert_admins_no_specialist(
        self,
        conversation_id,
        reason: str,
        score: int,
        db,
        customer_name: str,
        customer_phone: str,
        intent: str,
        location: str,
        property_type: str,
        budget: str,
        conversation_summary: str,
        cw_link: str,
        inbox_id: int,
        template_phone_number_id: str,
    ) -> Dict[str, Any]:
        """
        Qualified lead, but no roster member covers this location and type.

        Irene and the existing admin recipient list get a private alert.
        The customer conversation is not assigned, no specialist is named,
        and nothing promises that someone will contact the customer.

        Recipients come from get_admin_recipients: Irene Leong is always
        first (+601165144931, already configured), then active crm_users
        admins with a phone, then DEFAULT_FALLBACK_ADMIN_NUMBERS. No phone
        is invented here. The Chatwoot conversation is not assigned to Irene
        or to a specialist; there is no assign-to-admin path that would keep
        the customer reply from naming someone.
        """
        admin_list = self.get_admin_recipients(db=db)
        note = (
            f"Admin-only handover ({reason}, score {score}). "
            "No specialist covers this location and property type. "
            "No specialist was named. No customer contact was promised. "
            "Private alert for admins only: "
            + ", ".join(item.get("name") or "Admin" for item in admin_list)
            + "."
        )
        remark = (
            "Admin-only alert: no specialist covers this location and property type. "
            "No specialist was named. No customer contact was promised."
        )
        if conversation_id:
            try:
                self.send_private_note_func(conversation_id, note)
            except Exception as exc:
                logger.warning(f"Could not post admin-only handover note: {exc}")

        summary = (conversation_summary or "Inquiry").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
        summary_with_remark = f"{summary} | {remark}" if summary else remark
        if len(summary_with_remark) > 500:
            summary_with_remark = summary_with_remark[:497] + "..."

        safe_customer_name = (customer_name or "").strip() or "Valued Customer"
        safe_customer_phone = (customer_phone or "").strip() or "N/A"
        safe_intent = (intent or "").strip().upper() or "BUYER"
        safe_location = str(location or "").strip() or "Not Specified"
        safe_property_type = str(property_type or "").strip() or "General Inquiry"
        safe_budget = str(budget or "").strip() or "Not Specified"
        safe_cw_link = (
            (cw_link or "").strip()
            or f"https://inbox.bentongland.com.my/app/accounts/1/conversations/{conversation_id}"
        )
        template_params = [
            safe_customer_name,
            safe_customer_phone,
            safe_intent,
            safe_location,
            safe_property_type,
            safe_budget,
            summary_with_remark,
            safe_cw_link,
        ]

        dispatched_phones = []
        delivery_details = {}
        for adm in admin_list:
            target_phone = adm["phone"]
            try:
                res = self.send_template_func(
                    inbox_id=inbox_id,
                    to_phone=target_phone,
                    template_name=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE", "new_lead_alert_utility"
                    ),
                    parameters=template_params,
                    language_code=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE_LANGUAGE", "en"
                    ),
                    override_phone_number_id=template_phone_number_id,
                )
            except Exception as exc:
                logger.warning(f"Admin-only handover alert failed for {target_phone}: {exc}")
                delivery_details[target_phone] = {"status": "failed", "error": str(exc)}
                continue
            is_delivered = False
            if res is not None:
                if isinstance(res, dict):
                    is_delivered = bool(res.get("messages") or res.get("id") or not res.get("error"))
                else:
                    is_delivered = True
            if is_delivered:
                dispatched_phones.append(target_phone)
                msg_id = "wamid.ok"
                if isinstance(res, dict) and res.get("messages"):
                    msg_id = res["messages"][0].get("id", "wamid.ok")
                delivery_details[target_phone] = {"status": "sent", "message_id": msg_id}
            else:
                delivery_details[target_phone] = {
                    "status": "failed",
                    "error": "Admin alert was not accepted",
                }

        return {
            "status": reason,
            "assigned_agents": [],
            "winning_score": score,
            "routed_to": dispatched_phones,
            "targeted_numbers": [item["phone"] for item in admin_list],
            "delivery_details": delivery_details,
            "is_fallback": False,
            "is_tie": False,
            "assignment_verified": False,
            "public_promise": False,
            "admin_only_handover": True,
            "admin_alert_recipients": admin_list,
            "diagnostic": note,
            "primary_agent_name": "",
            "primary_agent_phone": "",
        }

    def _diagnostic_result(
        self,
        conversation_id,
        reason: str,
        score: int,
        admin_only: bool = False,
        candidate_name: str = "",
    ) -> Dict[str, Any]:
        """No customer promise, no admin invention, no AI pause. A private note records why."""
        note = (
            f"Handover not completed ({reason}, score {score}). "
            "AI continues. No specialist was named and no immediate contact was promised."
        )
        if candidate_name:
            note += f" Candidate {candidate_name} was not assigned in Chatwoot."
        if conversation_id and not admin_only:
            try:
                self.send_private_note_func(conversation_id, note)
            except Exception as exc:
                logger.warning(f"Could not post handover diagnostic: {exc}")
        return {
            "status": reason,
            "assigned_agents": [],
            "winning_score": score,
            "routed_to": [],
            "targeted_numbers": [],
            "delivery_details": {},
            "is_fallback": False,
            "is_tie": reason == "tie",
            "assignment_verified": False,
            "public_promise": False,
            "diagnostic": note,
            "primary_agent_name": "",
            "primary_agent_phone": "",
        }

    def dispatch(
        self,
        conversation_id_or_data: Any = None,
        customer_name: str = "",
        customer_phone: str = "",
        intent: str = "BUYER",
        location: str = "",
        property_type: str = "",
        budget: str = "",
        conversation_summary: str = "",
        cw_link: str = "",
        inbox_id: int = 3,
        raw_inquiry_text: str = "",
        db: Optional[Any] = None,
        conversation_id: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Executes dynamic hot lead handover.
        """
        if conversation_id is not None and conversation_id_or_data is None:
            conversation_id_or_data = conversation_id

        admin_only = kwargs.get("admin_only", False)

        if isinstance(conversation_id_or_data, dict):
            lead_data = conversation_id_or_data
            if lead_data.get("admin_only"):
                admin_only = True
            conversation_id = lead_data.get("conversation_id", 0)
            customer_name = lead_data.get("customer_name") or "Valued Customer"
            customer_phone = lead_data.get("customer_phone") or ""
            intent = lead_data.get("intent") or "BUYER"
            location = (
                lead_data.get("city")
                or lead_data.get("location")
                or lead_data.get("state")
                or ""
            )
            cats = lead_data.get("property_category") or []
            property_type = (
                cats[0]
                if isinstance(cats, list) and cats
                else (cats if isinstance(cats, str) else "")
            )
            budget = lead_data.get("budget") or "Not Specified"
            conversation_summary = (
                lead_data.get("title")
                or lead_data.get("inquiry_text")
                or "Inquiry"
            )
            cw_link = (
                lead_data.get("cw_link")
                or f"https://inbox.bentongland.com.my/app/accounts/1/conversations/{conversation_id}"
            )
            inbox_id = lead_data.get("inbox_id") or 3
            raw_inquiry_text = (
                lead_data.get("inquiry_text") or lead_data.get("raw_text") or ""
            )
        else:
            conversation_id = conversation_id_or_data

        close_db = False
        if db is None:
            try:
                db = self.session_factory()
                close_db = True
            except Exception:
                db = None

        try:
            # 1. Query active agents and employees with configured phone numbers
            raw_agents = self.get_active_agents_func()
            if raw_agents is None and db is not None:
                try:
                    raw_agents = db.query(User).filter(
                        User.is_active == True,
                        User.role.in_(["agent", "employee"]),
                        User.phone_number.isnot(None),
                        User.phone_number != "",
                    ).all()
                except Exception as dbe:
                    logger.warning(f"Could not query User model from DB: {dbe}")
                    raw_agents = []

            scored_candidates = []
            for agent in (raw_agents or []):
                agent_phone = (
                    agent.get("phone_number")
                    if isinstance(agent, dict)
                    else getattr(agent, "phone_number", None)
                )
                if not agent_phone:
                    continue
                score = self.scorer.calculate_score(
                    agent=agent,
                    lead_location_or_data=location,
                    lead_property_type=property_type,
                    raw_inquiry_text=raw_inquiry_text,
                )
                location_hits, type_hits = AgentSpecializationScorer.score_parts(
                    agent.get("assigned_locations") if isinstance(agent, dict) else (
                        getattr(agent, "assigned_locations", None) or []
                    ),
                    _agent_types(agent),
                    location,
                    property_type,
                    raw_inquiry_text,
                )
                if (
                    str(intent or "").strip().lower() in {"renter", "tenant"}
                    and type_hits == 0
                    and "rental" in {str(t or "").strip().lower() for t in _agent_types(agent)}
                    and (property_type or "rent" in (raw_inquiry_text or "").lower())
                ):
                    type_hits = 1
                    score = location_hits + type_hits
                agent_name = (
                    agent.get("name")
                    if isinstance(agent, dict)
                    else (
                        getattr(agent, "full_name", None)
                        or getattr(agent, "username", "Agent")
                    )
                )
                scored_candidates.append({
                    "agent": agent,
                    "score": score,
                    "location_hits": location_hits,
                    "type_hits": type_hits,
                    "compatible": intent_compatible(intent, agent),
                    "phone": agent_phone,
                    "name": agent_name,
                })

            # Sort descending by score
            scored_candidates.sort(key=lambda x: x["score"], reverse=True)
            max_score = scored_candidates[0]["score"] if scored_candidates else 0

            is_staging_env = (
                os.getenv("DB_HOST") == "whatsapp_ai_db_staging"
                or "staging" in os.getenv("REDIS_HOST", "")
                or os.getenv("APP_ENV") == "staging"
                or os.getenv("ENVIRONMENT", "").lower() == "staging"
            )
            staging_default_phone = "1033113423218081"
            prod_default_phone = "1039310802596891"
            template_phone_number_id = os.getenv(
                "WHATSAPP_TEMPLATE_PHONE_NUMBER_ID",
                staging_default_phone if is_staging_env else prod_default_phone,
            )
            if is_staging_env and str(template_phone_number_id) == prod_default_phone:
                template_phone_number_id = staging_default_phone

            routed_targets = []
            is_fallback = False
            is_tie = False

            if intent and str(intent).strip().upper() in ["OUT_OF_SCOPE", "OUT_OF_CONTEXT"]:
                # Step 4: Out-of-scope redirection directly to Irene Leong (+601165144931) and active admins
                admin_list = self.get_admin_recipients(db=db)
                for adm in admin_list:
                    routed_targets.append({
                        "phone": adm["phone"],
                        "name": adm["name"],
                        "score": 100 if adm["phone"] == "+601165144931" else 90,
                        "remark": "⚠️ Out of Scope Inquiry: Redirected to Irene Leong (+60 11-6514 4931) and Admin Team for clarification.",
                    })
                max_score = 100
            elif intent and str(intent).strip().upper() in ["AGENT", "AGENT_INQUIRY", "BROKER"]:
                # Co-broke agent/broker inquiry: Handled directly by Irene Leong (Main Number: +601165144931)
                routed_targets.append({
                    "phone": "+601165144931",
                    "name": "Irene Leong (Main Number)",
                    "score": 100,
                    "remark": "🤝 Co-Broke Agent Inquiry: Handled directly by Main Number.",
                })
                max_score = 100
            elif admin_only:
                # Test Simulation: Route strictly to admin recipients only, bypassing specialist agents
                admin_list = self.get_admin_recipients(db=db)
                for adm in admin_list:
                    routed_targets.append({
                        "phone": adm["phone"],
                        "name": adm["name"],
                        "score": 100 if adm["phone"] == "+601165144931" else 90,
                        "remark": "🧪 Simulation Test: Verification dispatch strictly to Admin line.",
                        "agent": None,
                        "is_primary": True,
                    })
                max_score = 100
            else:
                eligible = [
                    c for c in scored_candidates
                    if c.get("compatible")
                    and c.get("location_hits", 0) >= 1
                    and c.get("type_hits", 0) >= 1
                ]
                if not eligible:
                    incompatible = [c for c in scored_candidates if c.get("score", 0) > 0 and not c.get("compatible")]
                    reason = "intent_incompatible" if incompatible and not any(
                        c.get("compatible") for c in scored_candidates
                    ) else "below_threshold"
                    # Nobody covers this location and type. Alert admins only.
                    # A tie still uses _diagnostic_result below and does not alert.
                    return self._alert_admins_no_specialist(
                        conversation_id=conversation_id,
                        reason=reason,
                        score=max_score,
                        db=db,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        intent=intent,
                        location=location,
                        property_type=property_type,
                        budget=budget,
                        conversation_summary=conversation_summary,
                        cw_link=cw_link,
                        inbox_id=inbox_id,
                        template_phone_number_id=template_phone_number_id,
                    )
                top_score = max(c["score"] for c in eligible)
                top_candidates = [c for c in eligible if c["score"] == top_score]
                if len(top_candidates) != 1 or top_score < 2:
                    return self._diagnostic_result(
                        conversation_id,
                        "tie" if len(top_candidates) != 1 else "below_threshold",
                        top_score,
                        admin_only=admin_only,
                    )
                winner = top_candidates[0]
                verified = self._assign_verified(conversation_id, winner.get("agent"))
                if not verified:
                    return self._diagnostic_result(
                        conversation_id,
                        "assignment_failed",
                        winner["score"],
                        admin_only=admin_only,
                        candidate_name=winner["name"],
                    )
                routed_targets.append({
                    "phone": winner["phone"],
                    "name": winner["name"],
                    "score": winner["score"],
                    "remark": "",
                    "agent": winner.get("agent"),
                    "is_primary": True,
                })
                admin_list = self.get_admin_recipients(db=db)
                primary_phones = {
                    t["phone"].replace(" ", "").replace("-", "") for t in routed_targets
                }
                for adm in admin_list:
                    adm_norm = adm["phone"].replace(" ", "").replace("-", "")
                    if adm_norm not in primary_phones:
                        routed_targets.append({
                            "phone": adm["phone"],
                            "name": adm["name"],
                            "score": winner["score"],
                            "remark": (
                                f"ℹ️ Admin Copy: Case assigned to Specialist Agent: "
                                f"{winner['name']} ({winner['phone']})."
                            ),
                            "agent": None,
                            "is_primary": False,
                        })
                max_score = winner["score"]

            dispatched_phones = []
            delivery_details = {}
            for target in routed_targets:
                target_phone = target["phone"]
                try:
                    contact_id = self.get_or_create_contact_func(
                        target_phone, f"Staff/Admin {target['name']}"
                    )
                    if contact_id:
                        self.create_conversation_func(contact_id, inbox_id)
                except Exception as ce:
                    logger.warning(
                        f"Could not prepare chatwoot contact for {target_phone}: {ce}"
                    )

                summary_with_remark = conversation_summary or "Inquiry Details"
                if target.get("remark"):
                    summary_with_remark = f"{summary_with_remark} | {target['remark']}"
                summary_with_remark = (
                    summary_with_remark.replace("\r", " ")
                    .replace("\n", " ")
                    .replace("\t", " ")
                    .strip()
                )
                if len(summary_with_remark) > 500:
                    summary_with_remark = summary_with_remark[:497] + "..."

                safe_customer_name = (customer_name or "").strip() or "Valued Customer"
                safe_customer_phone = (
                    (customer_phone or "").strip()
                    if (customer_phone and customer_phone.strip())
                    else "N/A (Admin Simulation)"
                )
                safe_intent = (intent or "").strip().upper() or "BUYER"
                safe_location = str(location or "").strip() or "Not Specified"
                safe_property_type = str(property_type or "").strip() or "General Inquiry"
                safe_budget = str(budget or "").strip() or "Not Specified"
                safe_cw_link = (
                    (cw_link or "").strip()
                    or f"https://inbox.bentongland.com.my/app/accounts/1/conversations/{conversation_id}"
                )

                template_params = [
                    safe_customer_name,
                    safe_customer_phone,
                    safe_intent,
                    safe_location,
                    safe_property_type,
                    safe_budget,
                    summary_with_remark,
                    safe_cw_link,
                ]

                # 1. Send WhatsApp Template to staff / admin
                res = self.send_template_func(
                    inbox_id=inbox_id,
                    to_phone=target_phone,
                    template_name=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE", "new_lead_alert_utility"
                    ),
                    parameters=template_params,
                    language_code=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE_LANGUAGE", "en"
                    ),
                    override_phone_number_id=template_phone_number_id,
                )

                is_delivered = False
                if res is not None:
                    if isinstance(res, dict):
                        is_delivered = bool(res.get("messages") or res.get("id") or not res.get("error"))
                    else:
                        is_delivered = True

                if is_delivered:
                    dispatched_phones.append(target_phone)
                    msg_id = "wamid.ok"
                    if isinstance(res, dict) and res.get("messages"):
                        msg_id = res["messages"][0].get("id", "wamid.ok")
                    delivery_details[target_phone] = {
                        "status": "sent",
                        "message_id": msg_id,
                    }
                else:
                    err_info = "Meta API delivery rejected or credentials missing"
                    try:
                        from app.services.chatwoot import get_last_whatsapp_error
                        last_err = get_last_whatsapp_error()
                        if last_err:
                            err_info = last_err
                    except Exception:
                        pass
                    delivery_details[target_phone] = {
                        "status": "failed",
                        "error": err_info,
                    }

            primary_target = next(
                (t for t in routed_targets if t.get("is_primary")),
                (routed_targets[0] if routed_targets else None)
            )

            # 2. Attach primary contact card to customer once (skip for simulation / non-phone)
            clean_cust_digits = "".join(ch for ch in str(customer_phone or "") if ch.isdigit())
            is_real_customer_phone = (
                len(clean_cust_digits) >= 8
                and not admin_only
                and "simulation" not in str(customer_phone or "").lower()
            )
            if is_real_customer_phone and primary_target:
                self.send_contact_func(
                    inbox_id=inbox_id,
                    to_phone=customer_phone,
                    contact_name=primary_target["name"],
                    contact_phone=primary_target["phone"],
                    override_phone_number_id=template_phone_number_id,
                )

            # 3. Assign conversation to primary agent in Chatwoot
            if conversation_id and primary_target and not is_fallback:
                try:
                    agent_obj = primary_target.get("agent")
                    agent_email = (
                        getattr(agent_obj, "email", None)
                        if agent_obj
                        else None
                    )
                    if not agent_email and isinstance(agent_obj, dict):
                        agent_email = agent_obj.get("email")
                    if agent_email:
                        cw_agent_id = self.get_agent_id_func(agent_email)
                        if cw_agent_id:
                            self.assign_agent_func(conversation_id, cw_agent_id)
                            logger.info(
                                f"Assigned conversation {conversation_id} to Chatwoot agent {cw_agent_id} ({agent_email})"
                            )
                except Exception as ae:
                    logger.warning(f"Could not assign Chatwoot agent for conv {conversation_id}: {ae}")

            # 4. Persist assigned agent & locked post-handover state to Customer metadata in DB if available
            if customer_phone and primary_target and db is not None:
                try:
                    from app.db.models import Customer
                    clean_phone = customer_phone.replace("+", "").replace(" ", "").replace("-", "")
                    cust = db.query(Customer).filter(
                        (Customer.id == clean_phone)
                        | (Customer.id == f"+{clean_phone}")
                        | (Customer.id.like(f"%{clean_phone}%"))
                    ).first()
                    if cust:
                        c_meta = cust.metadata_json.copy() if cust.metadata_json else {}
                        c_meta["assigned_agent"] = primary_target["name"]
                        c_meta["assigned_agent_phone"] = primary_target["phone"]
                        c_meta["lead_temp"] = "hot"
                        c_meta["bypass_ai"] = True
                        c_meta["handover_completed"] = True
                        c_meta["locked_intent"] = str(intent or "buyer").strip().lower()
                        cust.metadata_json = c_meta
                        try:
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(cust, "metadata_json")
                        except Exception:
                            pass
                        db.commit()
                        logger.info(f"Persisted assigned agent {primary_target['name']} to Customer {cust.id} metadata")
                except Exception as cme:
                    logger.warning(f"Could not persist assigned agent to Customer metadata in lead_handover: {cme}")

            routing_notes = []
            if intent and str(intent).strip().upper() in ["OUT_OF_SCOPE", "OUT_OF_CONTEXT"]:
                routing_notes.append(
                    "⚠️ Out of Scope Inquiry: Redirected to Irene Leong (+601165144931) and Active Admin Team"
                )
            elif intent and str(intent).strip().upper() in [
                "AGENT", "AGENT_INQUIRY", "BROKER"
            ]:
                routing_notes.append(
                    "🤝 Routed directly to Main Number (Irene Leong: +601165144931) for Co-Broke qualification"
                )
            elif is_fallback:
                routing_notes.append(
                    "⚠️ Routed to Main Admin Lines (Score: 0 - No specialization matches)"
                )
            elif is_tie:
                primary_targets = [t for t in routed_targets if t.get("is_primary")]
                tied_names = [f"{t['name']} ({t['phone']})" for t in primary_targets]
                routing_notes.append(
                    f"⚠️ Multi-Agent Shared Tie (Score: {max_score}) dispatched to: {', '.join(tied_names)}"
                )
                if any(not t.get("is_primary") for t in routed_targets):
                    routing_notes.append(
                        "📢 Admin Notification: Dispatched copy to Irene Leong (+601165144931) and Admin Team"
                    )
            else:
                primary_targets = [t for t in routed_targets if t.get("is_primary")]
                w = primary_targets[0] if primary_targets else routed_targets[0]
                routing_notes.append(
                    f"✅ Routed to Specialist Agent: {w['name']} ({w['phone']}) with Match Score: {w['score']}"
                )
                if any(not t.get("is_primary") for t in routed_targets):
                    routing_notes.append(
                        "📢 Admin Notification: Dispatched copy to Irene Leong (+601165144931) and Admin Team"
                    )

            private_note_text = (
                f"🔥 **HOT LEAD / HUMAN HANDOVER TRIGGERED**\n\n"
                f"👤 **Customer**: {customer_name} ({customer_phone})\n"
                f"🎯 **Intent**: {intent.upper()}\n"
                f"📍 **Location**: {location}\n"
                f"🏡 **Property Type**: {property_type}\n"
                f"💰 **Budget / Price**: {budget}\n\n"
                f"🔀 **Routing Decision**: {'; '.join(routing_notes)}\n"
                f"📝 **AI Summary**: {conversation_summary}\n\n"
                f"⚡ **Status**: AI response paused (`bypass_ai=True`). Handed over to human agent."
            )
            if conversation_id and not admin_only:
                try:
                    self.send_private_note_func(conversation_id, private_note_text)
                except Exception as ne:
                    logger.error(f"Failed to post internal private note on handover: {ne}")
                try:
                    handover_labels = (
                        ["out-of-scope", "human-handover"]
                        if (intent and str(intent).strip().upper() in ["OUT_OF_SCOPE", "OUT_OF_CONTEXT"])
                        else ["human-handover", "hot-lead"]
                    )
                    self.apply_label_func(conversation_id, handover_labels)
                    self.set_priority_func(conversation_id, "urgent")
                    self.update_status_func(conversation_id, "open")
                except Exception as le:
                    logger.warning(
                        f"Could not apply handover labels/status to conv {conversation_id}: {le}"
                    )

            assigned_agent_list = [
                {"name": t["name"], "phone_number": t["phone"], "score": t["score"]}
                for t in routed_targets
                if t.get("is_primary", True) and not is_fallback
            ]

            if not dispatched_phones and routed_targets:
                overall_status = "failed"
            elif is_fallback:
                overall_status = "fallback_to_admin"
            elif len(dispatched_phones) < len(routed_targets):
                overall_status = "partial_success"
            else:
                overall_status = "success"

            return {
                "status": overall_status,
                "assigned_agents": assigned_agent_list,
                "assignment_verified": True,
                "public_promise": True,
                "winning_score": max_score,
                "routed_to": dispatched_phones,
                "targeted_numbers": [t["phone"] for t in routed_targets],
                "delivery_details": delivery_details,
                "is_fallback": is_fallback,
                "is_tie": is_tie,
                "top_score": max_score,
                "targets": routed_targets,
                "primary_agent_name": primary_target["name"] if primary_target else "",
                "primary_agent_phone": primary_target["phone"] if primary_target else "",
            }
        finally:
            if close_db and db is not None:
                try:
                    db.close()
                except Exception:
                    pass


def dispatch_hot_lead_handover(*args, **kwargs) -> Dict[str, Any]:
    """
    Convenience module-level facade for LeadHandoverService().dispatch(...).
    """
    return LeadHandoverService().dispatch(*args, **kwargs)

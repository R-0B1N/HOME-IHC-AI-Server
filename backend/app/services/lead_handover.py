"""
Domain Service for Dynamic Hot Lead Handover and Agent Specialization Scoring.
Encapsulates scoring algorithms, candidate selection, tie-break remark generation,
and multi-channel WhatsApp / Chatwoot notification dispatch.
"""

import os
import logging
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

        score = 0
        searchable_text = (
            f"{lead_location or ''} {lead_property_type or ''} {raw_inquiry_text or ''}".lower()
        )

        # Match locations
        for loc in assigned_locs:
            if not loc or not isinstance(loc, str):
                continue
            loc_clean = loc.strip().lower()
            if not loc_clean:
                continue
            if (lead_location and loc_clean in lead_location.lower()) or (loc_clean in searchable_text):
                score += 1

        # Match property types & domain heuristics
        for ptype in assigned_ptypes:
            if not ptype or not isinstance(ptype, str):
                continue
            ptype_clean = ptype.strip().lower()
            if not ptype_clean:
                continue
            if (lead_property_type and ptype_clean in lead_property_type.lower()) or (ptype_clean in searchable_text):
                score += 1
            elif ptype_clean == "land / agriculture" and (
                any(k in searchable_text for k in ["agriculture", "tanah", "kebun", "ladang", "pertanian"])
                or ("land" in searchable_text and "durian" not in searchable_text)
            ):
                score += 1
            elif ptype_clean == "durian land" and any(
                k in searchable_text for k in ["durian", "musang king", "black thorn", "d24"]
            ):
                score += 1

        return score


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

        if isinstance(conversation_id_or_data, dict):
            lead_data = conversation_id_or_data
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
            elif max_score > 0:
                top_candidates = [c for c in scored_candidates if c["score"] == max_score]
                if len(top_candidates) == 1:
                    winner = top_candidates[0]
                    routed_targets.append({
                        "phone": winner["phone"],
                        "name": winner["name"],
                        "score": winner["score"],
                        "remark": "",
                    })
                else:
                    is_tie = True
                    for cand in top_candidates:
                        other_agents = [
                            f"{o['name']} ({o['phone']})"
                            for o in top_candidates
                            if o["phone"] != cand["phone"]
                        ]
                        others_str = ", ".join(other_agents)
                        shared_remark = f"⚠️ Shared Case: This inquiry is also shared with Agent {others_str}."
                        routed_targets.append({
                            "phone": cand["phone"],
                            "name": cand["name"],
                            "score": cand["score"],
                            "remark": shared_remark,
                        })
            else:
                is_fallback = True
                admin_list = self.get_admin_recipients(db=db)
                for adm in admin_list:
                    routed_targets.append({
                        "phone": adm["phone"],
                        "name": adm["name"],
                        "score": 0,
                        "remark": "ℹ️ Handover Fallback: No matching agent specialization found.",
                    })

            dispatched_phones = []
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

                summary_with_remark = conversation_summary
                if target.get("remark"):
                    summary_with_remark = f"{conversation_summary}\n\n{target['remark']}"
                if len(summary_with_remark) > 500:
                    summary_with_remark = summary_with_remark[:497] + "..."

                template_params = [
                    customer_name,
                    customer_phone,
                    intent.upper(),
                    str(location),
                    str(property_type),
                    str(budget),
                    summary_with_remark,
                    cw_link,
                ]

                # 1. Send WhatsApp Template to staff / admin
                self.send_template_func(
                    inbox_id=inbox_id,
                    to_phone=target_phone,
                    template_name=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE", "hot_lead_alert_utility"
                    ),
                    parameters=template_params,
                    language_code=os.getenv(
                        "WHATSAPP_HANDOVER_TEMPLATE_LANGUAGE", "en"
                    ),
                    override_phone_number_id=template_phone_number_id,
                )
                dispatched_phones.append(target_phone)

            # 2. Attach primary contact card to customer once
            if customer_phone and routed_targets:
                primary_target = routed_targets[0]
                self.send_contact_func(
                    inbox_id=inbox_id,
                    to_phone=customer_phone,
                    contact_name=primary_target["name"],
                    contact_phone=primary_target["phone"],
                    override_phone_number_id=template_phone_number_id,
                )

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
                tied_names = [f"{t['name']} ({t['phone']})" for t in routed_targets]
                routing_notes.append(
                    f"⚠️ Multi-Agent Shared Tie (Score: {max_score}) dispatched to: {', '.join(tied_names)}"
                )
            else:
                w = routed_targets[0]
                routing_notes.append(
                    f"✅ Routed to Specialist Agent: {w['name']} ({w['phone']}) with Match Score: {w['score']}"
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
            if conversation_id:
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
                if not is_fallback
            ]

            return {
                "status": "fallback_to_admin" if is_fallback else "success",
                "assigned_agents": assigned_agent_list,
                "winning_score": max_score,
                "routed_to": dispatched_phones,
                "is_fallback": is_fallback,
                "is_tie": is_tie,
                "top_score": max_score,
                "targets": routed_targets,
            }
        finally:
            if close_db and db is not None:
                try:
                    db.close()
                except Exception:
                    pass


_default_service = LeadHandoverService()


def dispatch_hot_lead_handover(*args, **kwargs) -> Dict[str, Any]:
    """
    Convenience module-level facade for LeadHandoverService().dispatch(...).
    """
    return _default_service.dispatch(*args, **kwargs)

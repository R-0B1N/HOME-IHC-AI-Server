"""
Canonical customer category and temperature.

PR #11 ``role_contract.assess_turn`` returns seller, buyer, renter, ambiguous,
or none. It has no landlord role and no agent role. This module does not
change that function. Landlord and agent are decided here, and ``renter``
is mapped to ``tenant`` at this boundary. Live conversation turns still go
through ``apply_role_evidence`` and can still store ``renter`` until a later
change wires this resolver into the session.

Canonical categories: buyer, seller, agent, tenant, landlord, uncertain.

Landlord means the customer is offering their own property for rent
("I want to rent out my shop", "出租", "nak sewakan rumah saya").
"Is it for rent?" stays uncertain. A photo is not seller evidence.
"""

import datetime
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.services.classification_config import backfill_lock_allows_override
from app.services.role_contract import (
    assess_turn,
    is_explicit_seller_statement,
    is_listing_question,
    is_title_document,
    own_asking_price,
    own_buyer_budget,
    own_rent_budget,
    stated_towns,
    stated_type,
)

CANONICAL_CATEGORIES = ("buyer", "seller", "agent", "tenant", "landlord", "uncertain")

# Labels a future merge-write may replace. Unrelated Chatwoot labels stay.
MANAGED_LABELS = frozenset({
    "buyer",
    "seller",
    "agent",
    "tenant",
    "landlord",
    "renter",
    "ambiguous",
    "owner",
    "hot",
    "warm",
    "cold",
    "cooling",
    "hot-lead",
    "handover_initiated",
    "needs-review",
    "uncertain",
})

_STORED_CATEGORY_KEYS = (
    "intent_category",
    "locked_intent",
    "customer_category",
    "current_agent",
    "intent",
)

_STORED_TEMPERATURE_KEYS = (
    "lead_temp",
    "intention_tag",
    "temperature",
)

_CATEGORY_ALIASES = {
    "buyer": "buyer",
    "personal_buyer": "buyer",
    "seller": "seller",
    "owner": "seller",
    "agent": "agent",
    "broker": "agent",
    "agent_inquiry": "agent",
    "tenant": "tenant",
    "renter": "tenant",
    "landlord": "landlord",
    "ambiguous": "uncertain",
    "general": "uncertain",
    "none": "uncertain",
    "uncertain": "uncertain",
    "": "uncertain",
}

_EXPLICIT_AGENT = re.compile(
    r"("
    r"\bco-?broke\b"
    r"|\bproperty agent\b"
    r"|\bagent\s*/\s*broker\b"
    r"|\bejen hartanah\b"
    r"|\bi am (?:a |an )?(?:property )?agent\b"
    r"|\bi(?:'m| am) (?:a |an )?(?:property )?agent\b"
    r"|\bi(?:'m| am) (?:a |an )?broker\b"
    r"|我是中介"
    r"|我是经纪"
    r"|我是agent"
    r")",
    re.IGNORECASE,
)

_MENU_OPTION_AGENT = re.compile(
    r"^(?:2|2\.|2\)|🤝?\s*(?:property\s+agent|agent|broker|ejen|中介|房产经纪))\s*$",
    re.IGNORECASE,
)

# Offering the customer's own property for rent. Bare "for rent?" is not this.
_EXPLICIT_LANDLORD = re.compile(
    r"("
    r"\bi (?:want|wish|would like|wanna|'m going) to rent out\b"
    r"|\bi(?:'m| am) renting out\b"
    r"|\brent(?:ing)? out my\b"
    r"|\bmy (?:shop|house|home|property|land|lot|room|unit) (?:is )?for rent\b"
    r"|\bnak sewa ?kan\b"
    r"|\bsewakan\b"
    r"|\bbagi sewa\b"
    r"|我要出租"
    r"|想出租"
    r"|出租"
    r"|放租"
    r"|招租"
    r")",
    re.IGNORECASE,
)

_LANDLORD_QUESTION = re.compile(
    r"("
    r"\bis it for rent\b"
    r"|\bis (?:this|that|the) (?:shop|house|unit|property)? ?for rent\b"
    r"|\bfor rent\s*\?"
    r"|出租吗"
    r")",
    re.IGNORECASE,
)

_SELF_BUY = re.compile(
    r"("
    r"\bfor myself\b"
    r"|\bbuying for myself\b"
    r"|\bpersonal buyer\b"
    r"|\bi am the buyer\b"
    r"|我是买家"
    r"|自己买"
    r")",
    re.IGNORECASE,
)

_SELL_VERB = re.compile(
    r"("
    r"\bi (?:want|wish|would like|wanna) to sell\b"
    r"|\bi(?:'m| am) selling\b"
    r"|\bnak jual\b"
    r"|\bsaya (?:nak |hendak )?jual\b"
    r"|想卖"
    r"|要卖"
    r"|我要卖"
    r"|放盘"
    r"|出售"
    r")",
    re.IGNORECASE,
)

_ASKING_RENT = re.compile(
    r"(?:"
    r"asking rent"
    r"|expected rent"
    r"|monthly rent"
    r"|rent is"
    r"|rental is"
    r"|sewa sebulan"
    r"|租金"
    r"|月租"
    r")",
    re.IGNORECASE,
)

_MONEY = re.compile(
    r"(?:rm|myr)\s*\d[\d,.]*(?:\s*(?:k|juta|million|mil))?"
    r"|\d[\d,.]*(?:\s*(?:k|juta|million|mil))",
    re.IGNORECASE,
)

_HUMAN_OR_VIEWING = re.compile(
    r"("
    r"\bcall me\b"
    r"|\bspeak to (?:a )?human\b"
    r"|\btalk to (?:an? )?(?:agent|person)\b"
    r"|\bcontact me\b"
    r"|\bhubungi saya\b"
    r"|\bnak jumpa\b"
    r"|\barrange viewing\b"
    r"|\bschedule viewing\b"
    r"|\bbook viewing\b"
    r"|安排看房"
    r"|预约看房"
    r")",
    re.IGNORECASE,
)

_PHOTO_PLACEHOLDER = re.compile(
    r"^\[(?:image|photo|gambar|图片)[^\]]*\]$",
    re.IGNORECASE,
)


def mask_phone(phone: str) -> str:
    """Keep the last four digits. Every other digit becomes a star."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return "****"
    if len(digits) <= 4:
        return "*" * (4 - len(digits)) + digits
    return "*" * (len(digits) - 4) + digits[-4:]


def stored_category(metadata: Optional[dict]) -> str:
    """Raw category string currently saved on the customer, before canonical mapping."""
    meta = metadata or {}
    for key in _STORED_CATEGORY_KEYS:
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def stored_temperature(metadata: Optional[dict]) -> str:
    """Raw temperature string currently saved on the customer."""
    meta = metadata or {}
    for key in _STORED_TEMPERATURE_KEYS:
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def canonical_category_name(raw: str) -> str:
    """
    Map a stored or model label onto the canonical set.

    ``renter`` becomes ``tenant``. ``landlord`` stays ``landlord``.
    ``owner`` is the historical CRM alias for a seller, not a landlord.
    """
    key = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    return _CATEGORY_ALIASES.get(key, "uncertain")


def is_explicit_agent(text: str) -> bool:
    """Property agent / co-broke, including the WhatsApp menu reply ``2``."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _MENU_OPTION_AGENT.match(raw):
        return True
    return bool(_EXPLICIT_AGENT.search(raw))


def is_explicit_landlord(text: str) -> bool:
    """
    The customer is offering their own property for rent.

    A question about someone else's listing ("is it for rent?", "这间店出租吗")
    is not a landlord offer.
    """
    raw = text or ""
    if not raw.strip():
        return False
    if _LANDLORD_QUESTION.search(raw) and not re.search(
        r"rent out|sewakan|bagi sewa|我要出租|想出租|放租|招租",
        raw,
        re.IGNORECASE,
    ):
        return False
    if "出租" in raw and re.search(r"出租吗", raw):
        if not re.search(r"我要出租|想出租|放租|招租|我的", raw):
            return False
    return bool(_EXPLICIT_LANDLORD.search(raw))


def is_self_buy(text: str) -> bool:
    """A later message that says the agent is buying for themselves."""
    return bool(_SELF_BUY.search(text or ""))


def is_customer_message(message: dict) -> bool:
    """Incoming customer text. Skips private notes and assistant turns."""
    if not isinstance(message, dict) or message.get("private"):
        return False
    kind = message.get("message_type")
    return kind in (0, "0", "incoming")


def proposed_labels(category: str, temperature: str) -> List[str]:
    """Labels the dry-run would propose. This function does not write them."""
    if category == "uncertain":
        return ["uncertain", "needs-review"]
    return [category, temperature]


def _money_near(text: str, anchor: re.Pattern) -> Optional[str]:
    raw = text or ""
    match = anchor.search(raw)
    if not match:
        return None
    window = raw[max(0, match.start() - 40):match.end() + 80]
    money = _MONEY.search(window)
    if not money:
        return None
    return money.group(0).strip()


def own_asking_rent(text: str) -> Optional[str]:
    """A rent the customer states for their own property. A number alone is not this."""
    if is_listing_question(text) and not _ASKING_RENT.search(text or ""):
        return None
    return _money_near(text, _ASKING_RENT) or own_rent_budget(text)


def _quote(text: str, limit: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _photo_only(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    content = (message.get("content") or "").strip()
    attachments = message.get("attachments") or []
    image = False
    for item in attachments:
        if not isinstance(item, dict):
            continue
        marker = str(item.get("file_type") or item.get("content_type") or "").lower()
        if marker.startswith("image") or marker in {"image", "photo"}:
            image = True
    placeholder = content == "" or bool(_PHOTO_PLACEHOLDER.match(content))
    return image and placeholder and not is_title_document(message.get("document_extract"))


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return message.get("content") or ""
    return ""


def _title_extract(message: Any) -> Optional[dict]:
    if not isinstance(message, dict):
        return None
    extract = message.get("document_extract")
    if is_title_document(extract):
        return extract
    return None


def _role_for_text(text: str, document_extract: Optional[dict]) -> Optional[str]:
    """
    One message -> one canonical role, or None when the message does not decide.

    Landlord is tested before PR11 seller, because "rent out my shop" contains
    "my shop", which ``is_explicit_seller_statement`` treats as owner evidence.
    """
    if is_explicit_landlord(text):
        if _SELL_VERB.search(text) and is_explicit_seller_statement(text):
            return None  # caller records a conflict
        return "landlord"
    if is_explicit_agent(text):
        return "agent"
    assessment = assess_turn(text, document_extract)
    role = assessment.get("role")
    if role == "seller":
        return "seller"
    if role == "buyer":
        return "buyer"
    if role == "renter":
        return "tenant"
    return None


def _temperature(category: str, texts: Sequence[str], human_or_viewing: bool) -> str:
    if category == "uncertain":
        return "uncertain"
    towns = []
    types = []
    for text in texts:
        towns.extend(stated_towns(text))
        found = stated_type(text)
        if found:
            types.append(found)
    has_town = bool(towns)
    has_type = bool(types)
    price = False
    for text in texts:
        if category == "seller" and own_asking_price(text):
            price = True
        elif category == "buyer" and own_buyer_budget(text):
            price = True
        elif category == "tenant" and own_rent_budget(text):
            price = True
        elif category == "landlord" and own_asking_rent(text):
            price = True
        elif category == "agent" and (own_buyer_budget(text) or own_rent_budget(text)):
            price = True
    if has_town and has_type and (price or human_or_viewing):
        return "hot"
    if has_town or has_type or price:
        return "warm"
    return "cold"


def classify_customer_messages(messages: Iterable[Any]) -> Dict[str, Any]:
    """
    Classify chronological customer messages.

    Strings are treated as customer text. Dicts use ``content`` and ignore
    image attachments unless a title-document extract is attached.
    Low confidence is forced to uncertain.
    """
    material = list(messages or [])
    texts: List[str] = []
    roles: List[Dict[str, Any]] = []
    photo_only = False
    saw_listing = False
    conflict = False
    human_or_viewing = False

    for index, message in enumerate(material):
        text = _message_text(message)
        if _photo_only(message):
            photo_only = True
        if text and _HUMAN_OR_VIEWING.search(text):
            human_or_viewing = True
        if text and is_listing_question(text) and not is_explicit_landlord(text):
            saw_listing = True
        if text and is_explicit_landlord(text) and _SELL_VERB.search(text):
            conflict = True
            roles.append({"index": index, "role": "landlord", "quote": text, "conflict": True})
            roles.append({"index": index, "role": "seller", "quote": text, "conflict": True})
            texts.append(text)
            continue
        role = _role_for_text(text, _title_extract(message))
        if text or role:
            texts.append(text)
        if role:
            roles.append({"index": index, "role": role, "quote": text or "", "conflict": False})

    if not material or (not texts and not roles):
        reason = "photo_only_not_seller" if photo_only else "no_customer_text"
        return _uncertain(reason, photo_only)

    distinct = []
    for item in roles:
        if item["role"] not in distinct:
            distinct.append(item["role"])

    if conflict or (len(distinct) > 1 and not _agent_buyer_only(distinct)):
        if len(distinct) > 1 and not _agent_buyer_only(distinct):
            return _uncertain("conflicting_roles", photo_only, evidence=_quote(roles[-1]["quote"]))

    category = "uncertain"
    reason = "no_explicit_role"
    evidence = ""
    confidence = "low"

    if distinct == ["agent"] or (set(distinct) == {"agent", "buyer"}):
        agent_hits = [item for item in roles if item["role"] == "agent"]
        buyer_hits = [item for item in roles if item["role"] == "buyer"]
        if buyer_hits and agent_hits:
            agent_at = max(item["index"] for item in agent_hits)
            later_self = False
            for index, message in enumerate(material):
                if index > agent_at and is_self_buy(_message_text(message)):
                    later_self = True
                    evidence = _quote(_message_text(message))
                    break
            if later_self:
                category = "buyer"
                reason = "agent_then_self_buy"
            else:
                category = "agent"
                reason = "agent_beats_buyer"
                evidence = _quote(agent_hits[-1]["quote"])
        else:
            category = "agent"
            reason = "explicit_agent"
            evidence = _quote(agent_hits[-1]["quote"])
        confidence = "high"
    elif len(distinct) == 1:
        category = distinct[0]
        evidence = _quote(roles[-1]["quote"])
        confidence = "high"
        reason = {
            "buyer": "explicit_buyer",
            "seller": "explicit_seller",
            "tenant": "renter_mapped_to_tenant",
            "landlord": "explicit_landlord",
            "agent": "explicit_agent",
        }.get(category, "explicit_role")
    elif saw_listing or photo_only:
        reason = "photo_only_not_seller" if photo_only and not saw_listing else "listing_question"
        if photo_only and saw_listing:
            reason = "listing_question"
        return _uncertain(reason, photo_only)

    if confidence == "low":
        reason = "photo_only_not_seller" if photo_only else reason
        return _uncertain(reason, photo_only)

    # Two agreeing messages without a second distinct role can be medium
    # when the explicit pattern was not what decided it. Explicit hits stay high.
    if category != "uncertain" and len(roles) >= 2 and len(distinct) == 1:
        confidence = "high"

    temperature = _temperature(category, texts, human_or_viewing)
    return {
        "category": category,
        "temperature": temperature,
        "confidence": confidence,
        "evidence_quote": evidence,
        "reason": reason,
        "proposed_labels": proposed_labels(category, temperature),
    }


def _agent_buyer_only(roles: List[str]) -> bool:
    return set(roles).issubset({"agent", "buyer"}) and "agent" in roles and "buyer" in roles


def explicit_role_from_statement(text: str) -> Optional[str]:
    """
    Role from a customer statement only.

    Used when a backfill lock might be overridden. Photos, title-document
    extracts, classifier labels, and model flags are not inputs. PR #11
    ``assess_turn`` is consulted only for the text, with no document.
    Landlord is decided before seller so "rent out my shop" is not a sale.
    """
    raw = text or ""
    if not raw.strip():
        return None
    if is_explicit_landlord(raw) and _SELL_VERB.search(raw):
        return None
    if is_explicit_landlord(raw):
        return "landlord"
    if is_explicit_agent(raw):
        return "agent"
    assessment = assess_turn(raw, None)
    role = assessment.get("role")
    if role == "seller":
        return "seller"
    if role == "buyer":
        return "buyer"
    if role == "renter":
        return "tenant"
    return None


def enforce_classification_lock(session: dict, now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Keep a backfill-locked category unless this turn's text is an explicit role.

    On an allowed override, the session records previous_role, previous_role_at
    (ISO-8601), and previous_role_source from the lock's own source. The new
    source is ``live``. When the override flag is off, the new role is queued
    and the locked category stays.
    """
    session = session or {}
    if not session.get("classification_locked"):
        return {"action": "unlocked"}

    locked = canonical_category_name(session.get("locked_category") or "")
    if locked == "uncertain" and not (session.get("locked_category") or "").strip():
        locked = canonical_category_name(stored_category(session.get("locked_metadata") or {}))
    explicit = explicit_role_from_statement(session.get("last_customer_text") or "")
    collected = session.setdefault("collected_data", {})

    if explicit and explicit != locked:
        if backfill_lock_allows_override():
            moment = now or datetime.datetime.now(datetime.timezone.utc)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=datetime.timezone.utc)
            session["previous_role"] = locked
            session["previous_role_at"] = moment.replace(microsecond=0).isoformat()
            session["previous_role_source"] = session.get("classification_source") or "backfill"
            session["classification_source"] = "live"
            session["role_override"] = True
            session.pop("role_override_queued", None)
            session["locked_category"] = explicit
            collected["customer_category"] = explicit
            session["current_agent"] = explicit.upper()
            return {
                "action": "override",
                "category": explicit,
                "previous_role": session["previous_role"],
                "previous_role_at": session["previous_role_at"],
                "previous_role_source": session["previous_role_source"],
            }
        session["role_override_queued"] = explicit
        session["role_override"] = False
        collected["customer_category"] = locked
        session["current_agent"] = locked.upper()
        return {"action": "queue_for_review", "category": locked, "queued_role": explicit}

    session["role_override"] = False
    collected["customer_category"] = locked
    session["current_agent"] = locked.upper()
    return {"action": "keep", "category": locked}


ALLOWED_LABELS = {"buyer", "seller", "agent", "tenant", "landlord", "uncertain"}

_LLM_PROMPT = (
    "You classify one Home IHC WhatsApp customer. "
    "Use only the customer's own words. "
    "Labels: buyer, seller, agent, tenant, landlord, uncertain. "
    "seller means they are offering their own property for sale. "
    "landlord means they are offering their own property for rent. "
    "tenant means they want to rent a property. "
    "A question such as 'is it for rent?' is uncertain, not landlord or seller. "
    "A photo is not evidence. "
    "Output JSON only: {\"category\": \"buyer|seller|agent|tenant|landlord|uncertain\"}."
)


def normalize_label(raw: str) -> str:
    key = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    if key == "renter":
        return "tenant"
    if key in ALLOWED_LABELS:
        return key
    return "uncertain"


def local_llm_category(texts: Sequence[str], client=None) -> str:
    """
    One JSON classification from the on-server vLLM client in ``app.services.llm``.

    The client talks to ``VLLM_BASE_URL`` / ``OLLAMA_BASE_URL`` (default
    ``http://crm-vllm:8000/v1``). The API key is the placeholder ``EMPTY``.
    This does not call a paid external model.
    """
    import threading
    from app.services.llm import LLM_MODEL_NAME, _parse_json_from_llm, llm_client

    lock = getattr(local_llm_category, "_lock", None)
    if lock is None:
        lock = threading.Lock()
        local_llm_category._lock = lock
    transcript = "\n".join(text for text in texts if text).strip() or "(no customer text)"
    with lock:
        response = (client or llm_client).chat.completions.create(
            model=LLM_MODEL_NAME,
            temperature=0.0,
            max_tokens=60,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_PROMPT},
                {"role": "user", "content": transcript[-6000:]},
            ],
        )
    parsed = _parse_json_from_llm(response.choices[0].message.content or "")
    return normalize_label((parsed or {}).get("category"))


def reconcile_rule_and_llm(rule: Dict[str, Any], llm_category: str, texts: Sequence[str]) -> Dict[str, Any]:
    """Rules win when they are silent and the model is not. Disagreement is uncertain."""
    llm_category = normalize_label(llm_category)
    rule_category = rule.get("category") or "uncertain"
    if rule_category not in ("", "uncertain") and llm_category != rule_category:
        result = _uncertain("rule_llm_disagreement", False, evidence=rule.get("evidence_quote") or "")
        result["decided_by"] = "disagreement"
        return result
    if llm_category == "uncertain":
        result = _uncertain(rule.get("reason") or "llm_uncertain", False, evidence=rule.get("evidence_quote") or "")
        result["decided_by"] = "llm"
        return result
    human = any(_HUMAN_OR_VIEWING.search(text or "") for text in texts)
    temperature = _temperature(llm_category, list(texts), human)
    return {
        "category": llm_category,
        "temperature": temperature,
        "confidence": "medium",
        "evidence_quote": rule.get("evidence_quote") or "",
        "reason": "llm_fallback" if rule_category == "uncertain" else "llm_confirmed",
        "proposed_labels": proposed_labels(llm_category, temperature),
        "decided_by": "llm",
    }


def classify_transcript(messages: Iterable[Any], llm_classify=None) -> Dict[str, Any]:
    """
    Rules first. A high-confidence explicit role is kept and the local model is not called.

    Everything else is sent to ``llm_classify`` (the on-server model by default).
    If the rule had a category and the model names a different one, the result is uncertain.
    """
    material = list(messages or [])
    rule = classify_customer_messages(material)
    rule["decided_by"] = "rules"
    if rule.get("confidence") == "high" and rule.get("category") not in ("", "uncertain"):
        return rule
    texts = [_message_text(message) for message in material]
    texts = [text for text in texts if text]
    if llm_classify is None:
        llm_classify = local_llm_category
    try:
        llm_category = llm_classify(texts)
    except Exception:
        failed = _uncertain("llm_unavailable", False, evidence=rule.get("evidence_quote") or "")
        failed["decided_by"] = "llm_error"
        return failed
    return reconcile_rule_and_llm(rule, llm_category, texts)


def _uncertain(reason: str, photo_only: bool, evidence: str = "") -> Dict[str, Any]:
    if photo_only and reason in {"no_explicit_role", "no_customer_text", "listing_question"}:
        reason = "photo_only_not_seller"
    return {
        "category": "uncertain",
        "temperature": "uncertain",
        "confidence": "low",
        "evidence_quote": evidence,
        "reason": reason,
        "proposed_labels": proposed_labels("uncertain", "uncertain"),
    }

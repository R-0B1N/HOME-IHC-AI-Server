"""
Role, price, and handover contract for customer turns.

A shop price or availability question is buyer interest, or ambiguous when
buy versus rent was not chosen. It does not become a seller because a photo
arrived, a classifier said so, or the reply model talked like one.

Seller evidence is an explicit owner offer, a first-person sell statement,
or the customer's own title document. A price the customer asks about is
not their asking price and not their budget.
"""

import re
from typing import Any, Dict, List, Optional

TOWNS = (
    "bentong",
    "raub",
    "karak",
    "temerloh",
    "mentakab",
    "kuantan",
    "bukit tinggi",
    "janda baik",
    "cheroh",
    "tras",
    "lanchang",
    "maran",
    "triang",
    "kota bharu",
    "kuala lipis",
)

TYPE_WORDS = (
    ("shop lot", "Shop"),
    ("shophouse", "Shop"),
    ("shop-house", "Shop"),
    ("shop", "Shop"),
    ("kedai", "Shop"),
    ("店面", "Shop"),
    ("铺位", "Shop"),
    ("酒楼", "Commercial"),
    ("residence", "Residence"),
    ("residential", "Residential"),
    ("house", "House"),
    ("rumah", "House"),
    ("land", "Land"),
    ("tanah", "Land"),
    ("地", "Land"),
    ("factory", "Factory"),
    ("warehouse", "Industrial"),
    ("durian", "Agricultural"),
    ("orchard", "Agricultural"),
)

PLACEHOLDER_VALUES = {
    "",
    "property inquiry",
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

# Listing questions. These are about someone else's property.
_LISTING_QUESTION = re.compile(
    r"("
    r"\bis it (?:still )?available\b"
    r"|\bstill available\b"
    r"|\bhow much\b"
    r"|\bwhat(?:'s| is) the (?:price|rent)\b"
    r"|\bis it for (?:rent|sale)\b"
    r"|\bfor rent\s*\?"
    r"|\bberapa\b"
    r"|多少"
    r"|租金"
    r"|还在"
    r"|出售吗"
    r"|有卖吗"
    r"|卖吗"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_SELLER = re.compile(
    r"("
    r"\bi (?:want|wish|would like|wanna|'m going) to sell\b"
    r"|\bi(?:'m| am) selling\b"
    r"|\bi am (?:a |the )?(?:seller|owner)\b"
    r"|\bi(?:'m| am) (?:a |the )?(?:seller|owner)\b"
    r"|\bthis is my (?:land|property|house|shop|lot)\b"
    r"|\bmy (?:own )?(?:land|property|house|shop|lot)\b"
    r"|\bi have land\b"
    r"|\bi have (?:a |the |1 |one )?(?:\d+\s+)?residence\b"
    r"|\bsend u the piece of land\b"
    r"|\bnak jual\b"
    r"|\bsaya (?:nak |hendak )?jual\b"
    r"|放盘"
    r"|想卖"
    r"|要卖"
    r"|我要卖"
    r"|我有一间"
    r"|酒楼出售"
    r"|委托出售"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_BUY = re.compile(
    r"("
    r"\bi (?:want|wish|would like|wanna) to buy\b"
    r"|\bi(?:'m| am) buying\b"
    r"|\bto buy\b"
    r"|\bnak beli\b"
    r"|\bsaya (?:nak |hendak )?beli\b"
    r"|想买"
    r"|要买"
    r"|我要买"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_RENTER = re.compile(
    r"("
    r"\bi (?:want|wish|would like|wanna) to rent\b"
    r"|\bi(?:'m| am) (?:looking to )?rent(?:ing)?\b"
    r"|\bwant to rent\b"
    r"|\bnak sewa\b"
    r"|\bsaya (?:nak |hendak )?sewa\b"
    r"|想租"
    r"|要租"
    r"|我要租"
    r")",
    re.IGNORECASE,
)

_OWN_ASKING = re.compile(
    r"(?:"
    r"asking price"
    r"|my (?:asking )?price"
    r"|i(?:'m| am) asking"
    r"|expected (?:selling )?price"
    r"|harga jualan"
    r"|售价"
    r"|叫价"
    r"|预期售价"
    r")",
    re.IGNORECASE,
)

_OWN_BUDGET = re.compile(
    r"(?:my budget|budget is|bajet saya|我的预算|预算是)",
    re.IGNORECASE,
)

# A bare "budget" / "bajet" / "预算" only counts when an amount follows.
# "my budget" and "budget is" stay in _OWN_BUDGET. Rent-specific phrases stay
# in _OWN_RENT_BUDGET. Listing questions still do not qualify unless one of
# these own-budget anchors is present.
_BARE_OWN_BUDGET = re.compile(
    r"(?:"
    r"\b(?:budget|bajet)\b\s*(?:of|around|about|is|:)?\s*(?=(?:rm|myr)\b|\d)"
    r"|预算\s*(?:是|为|大约)?\s*(?=(?:rm|myr)|\d)"
    r")",
    re.IGNORECASE,
)

_OWN_RENT_BUDGET = re.compile(
    r"(?:rent budget|rental budget|monthly budget|i can pay|租金预算|预算租金)",
    re.IGNORECASE,
)

_MONEY = re.compile(
    r"(?:rm|myr)\s*\d[\d,.]*(?:\s*(?:k|juta|million|mil))?"
    r"|\d[\d,.]*(?:\s*(?:k|juta|million|mil))",
    re.IGNORECASE,
)

_TITLE_DOC_MARKERS = ("geran", "hakmilik", "borang", "pelan", "grant", "title")


def _clean(text: str) -> str:
    return text or ""


def is_placeholder(value: Any) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDER_VALUES


def is_title_document(document_extract: Optional[dict]) -> bool:
    """A parsed land title or building plan the customer sent as their own document."""
    if not isinstance(document_extract, dict) or not document_extract:
        return False
    dtype = str(document_extract.get("document_type") or "").lower()
    if any(marker in dtype for marker in _TITLE_DOC_MARKERS):
        return True
    if document_extract.get("lot_numbers") or document_extract.get("title_numbers"):
        return True
    return False


def is_listing_question(text: str) -> bool:
    return bool(_LISTING_QUESTION.search(_clean(text)))


def is_explicit_seller_statement(text: str) -> bool:
    """First-person offer or ownership. A question about someone else's listing is not this."""
    raw = _clean(text)
    if not raw:
        return False
    if is_listing_question(raw) and not _EXPLICIT_SELLER.search(raw):
        return False
    if _EXPLICIT_SELLER.search(raw):
        return True
    # "出售" as an offer, not "这间店出售吗" / "is this for sale?"
    if "出售" in raw and not re.search(r"(这|那|你们|店).{0,8}出售吗|出售吗", raw):
        if "吗" in raw and re.search(r"(这|那|你们|店面|铺)", raw):
            return False
        if re.search(r"(酒楼|厂房|我|自己|放盘).{0,12}出售|出售.{0,12}(酒楼|厂房)", raw):
            return True
    return False


def is_explicit_buy(text: str) -> bool:
    return bool(_EXPLICIT_BUY.search(_clean(text)))


def is_explicit_renter(text: str) -> bool:
    """The customer wants to rent a place. 'Is it for rent?' is a listing question."""
    raw = _clean(text)
    if re.search(r"\bis it for rent\b|\bfor rent\s*\?", raw, re.IGNORECASE):
        if not _EXPLICIT_RENTER.search(raw):
            return False
    return bool(_EXPLICIT_RENTER.search(raw))


def stated_towns(text: str) -> List[str]:
    low = _clean(text).lower()
    found = []
    for town in TOWNS:
        if re.search(rf"\b{re.escape(town)}\b", low):
            found.append(town.title())
    return found


def stated_type(text: str) -> Optional[str]:
    raw = _clean(text).lower()
    for needle, label in TYPE_WORDS:
        if needle in raw:
            return label
    return None


def _money_near(text: str, anchor: re.Pattern) -> Optional[str]:
    raw = _clean(text)
    match = anchor.search(raw)
    if not match:
        return None
    window = raw[match.start():match.start() + 80]
    money = _MONEY.search(window)
    if not money:
        # Amount may sit just before the anchor: "RM 500,000 asking price"
        before = raw[max(0, match.start() - 40):match.end()]
        money = _MONEY.search(before)
    if not money:
        return None
    return money.group(0).strip()


def own_asking_price(text: str) -> Optional[str]:
    """A price the customer states as their own listing price. A number alone is not this."""
    if is_listing_question(text) and not _OWN_ASKING.search(_clean(text)):
        return None
    return _money_near(text, _OWN_ASKING)


def _has_own_budget_anchor(text: str) -> bool:
    raw = _clean(text)
    return bool(_OWN_BUDGET.search(raw) or _BARE_OWN_BUDGET.search(raw))


def _has_own_rent_budget_anchor(text: str) -> bool:
    raw = _clean(text)
    return bool(_OWN_RENT_BUDGET.search(raw) or _has_own_budget_anchor(raw))


def _first_money(text: str, *anchors: re.Pattern) -> Optional[str]:
    for anchor in anchors:
        amount = _money_near(text, anchor)
        if amount:
            return amount
    return None


def own_buyer_budget(text: str) -> Optional[str]:
    """The customer's own buy budget. An asked listing price is not this."""
    if is_listing_question(text) and not _has_own_budget_anchor(text):
        return None
    return _first_money(text, _OWN_BUDGET, _BARE_OWN_BUDGET)


def own_rent_budget(text: str) -> Optional[str]:
    """The customer's own rent budget. An asked listing rent is not this.

    Rent-specific phrases still count. "my budget", "budget is", and a bare
    "budget" followed by an amount count too, the same way they do for buyers.
    """
    if is_listing_question(text) and not _has_own_rent_budget_anchor(text):
        return None
    return _first_money(text, _OWN_RENT_BUDGET, _OWN_BUDGET, _BARE_OWN_BUDGET)


def assess_turn(text: str, document_extract: Optional[dict] = None) -> Dict[str, Any]:
    """
    Evidence from the customer text and their own title document.

    role is seller, buyer, renter, ambiguous, or none.
    A photo is not an input. Classifier output is not an input.
    """
    raw = _clean(text)
    title = is_title_document(document_extract)
    seller = title or is_explicit_seller_statement(raw)
    buyer = is_explicit_buy(raw)
    renter = is_explicit_renter(raw)
    listing = is_listing_question(raw)

    if seller and not (listing and not is_explicit_seller_statement(raw)):
        role = "seller"
    elif buyer and not seller:
        role = "buyer"
    elif renter and not seller and not buyer:
        role = "renter"
    elif listing or (not seller and not buyer and not renter and listing):
        role = "ambiguous"
    else:
        role = "none"
        if listing:
            role = "ambiguous"

    # Seller evidence wins over a listing question only when the offer is explicit.
    if seller:
        role = "seller"
    elif buyer:
        role = "buyer"
    elif renter:
        role = "renter"
    elif listing:
        role = "ambiguous"

    towns = stated_towns(raw)
    return {
        "role": role,
        "seller_explicit": role == "seller",
        "title_document": title,
        "towns": towns,
        "property_type": stated_type(raw),
        "asking_price": own_asking_price(raw) if role == "seller" else None,
        "buyer_budget": own_buyer_budget(raw) if role == "buyer" else None,
        "rent_budget": own_rent_budget(raw) if role == "renter" else None,
        "listing_question": listing and role != "seller",
    }


def seller_is_earned(session: Optional[dict], collected: Optional[dict] = None) -> bool:
    session = session or {}
    collected = collected or session.get("collected_data") or {}
    if session.get("seller_evidence") == "explicit":
        return True
    if collected.get("seller_evidence") == "explicit":
        return True
    return False


def apply_role_evidence(session: dict, collected: dict, text: str, document_extract: Optional[dict] = None) -> Dict[str, Any]:
    """
    Write role, town, and grounded prices from customer evidence.

    An unearned seller flag is cleared when this turn is buyer, renter, or
    ambiguous. An earned seller track is kept when they also ask a buying
    question, but the active category follows the new evidence.
    """
    assessment = assess_turn(text, document_extract)
    earned = seller_is_earned(session, collected)
    role = assessment["role"]

    if assessment["towns"]:
        joined = " and ".join(assessment["towns"])
        current = collected.get("location")
        if not current or is_placeholder(current):
            collected["location"] = joined
        elif all(town.lower() not in str(current).lower() for town in assessment["towns"]):
            collected["location"] = joined

    if assessment["property_type"] and (
        not collected.get("property_type") or is_placeholder(collected.get("property_type"))
    ):
        collected["property_type"] = assessment["property_type"]

    if assessment["asking_price"]:
        collected["asking_price"] = assessment["asking_price"]
        collected["asking_price_grounded"] = True

    if role == "seller":
        collected["customer_category"] = "seller"
        collected["seller_evidence"] = "explicit"
        session["seller_evidence"] = "explicit"
        track = session.setdefault("seller_track", {})
        track["status"] = "active"
        session["current_agent"] = "SELLER"
    elif role == "buyer":
        collected["customer_category"] = "buyer"
        session.setdefault("buyer_track", {})["status"] = "active"
        session["current_agent"] = "BUYER"
        if not earned:
            _clear_unearned_seller(session, collected)
    elif role == "renter":
        collected["customer_category"] = "renter"
        session.setdefault("renter_track", {})["status"] = "active"
        session["current_agent"] = "RENTER"
        if not earned:
            _clear_unearned_seller(session, collected)
    elif role == "ambiguous":
        if not earned:
            collected["customer_category"] = "ambiguous"
            session["current_agent"] = "AMBIGUOUS"
            _clear_unearned_seller(session, collected)
    elif role == "none" and not earned:
        if str(collected.get("customer_category") or "").lower() in {"seller", "owner"}:
            _clear_unearned_seller(session, collected)

    _ground_customer_budget(collected, text, role, assessment)

    # Drop prices the model may already have copied from a question.
    if not collected.get("asking_price_grounded") and not own_asking_price(text):
        if collected.get("asking_price") and is_listing_question(text):
            collected.pop("asking_price", None)
    if not collected.get("buyer_budget_grounded") and is_listing_question(text):
        collected.pop("buyer_budget", None)
    if role != "seller" and not earned:
        collected.pop("is_owner", None)

    return assessment


def _ground_customer_budget(collected: dict, text: str, role: str, assessment: dict) -> None:
    """Record a budget the customer stated as their own.

    This turn's buyer or renter evidence wins. A later turn that only states
    the amount still counts when the session is already a buyer or a
    renter/tenant. Listing questions do not, unless they also use an
    own-budget anchor.
    """
    if assessment.get("buyer_budget"):
        collected["buyer_budget"] = assessment["buyer_budget"]
        collected["buyer_budget_grounded"] = True
    if assessment.get("rent_budget"):
        collected["rent_budget"] = assessment["rent_budget"]
        collected["rent_budget_grounded"] = True

    category = str(collected.get("customer_category") or "").lower()
    if not collected.get("buyer_budget_grounded") and (role == "buyer" or category == "buyer"):
        amount = own_buyer_budget(text)
        if amount:
            collected["buyer_budget"] = amount
            collected["buyer_budget_grounded"] = True
    if not collected.get("rent_budget_grounded") and (
        role == "renter" or category in {"renter", "tenant"}
    ):
        amount = own_rent_budget(text)
        if amount:
            collected["rent_budget"] = amount
            collected["rent_budget_grounded"] = True


def _clear_unearned_seller(session: dict, collected: dict) -> None:
    session.pop("seller_evidence", None)
    collected.pop("seller_evidence", None)
    track = session.get("seller_track")
    if isinstance(track, dict):
        track["status"] = "inactive"
    if str(collected.get("customer_category") or "").lower() == "seller":
        collected.pop("customer_category", None)
    if str(session.get("current_agent") or "").upper() == "SELLER":
        session["current_agent"] = None


def grounded_town(collected: dict, text: str = "") -> Optional[str]:
    for key in ("location", "seller_location", "buyer_location", "current_location"):
        value = collected.get(key)
        if value and not is_placeholder(value):
            towns = stated_towns(str(value)) or [str(value).strip()]
            if towns and not is_placeholder(towns[0]):
                return towns[0] if stated_towns(str(value)) else str(value).strip()
    towns = stated_towns(text)
    return towns[0] if towns else None


def grounded_type(collected: dict, text: str = "") -> Optional[str]:
    for key in ("property_type", "seller_property_type", "buyer_property_type"):
        value = collected.get(key)
        if value and not is_placeholder(value):
            return str(value).strip()
    return stated_type(text)


def hot_lead_qualified(role: str, collected: dict, text: str = "") -> bool:
    """
    Automatic HOT LEAD. Ambiguous buy/rent never qualifies.
    A price the customer only asks about does not count.
    """
    role_clean = (role or "").strip().lower()
    collected = collected or {}
    if role_clean in {"ambiguous", "none", ""}:
        return False
    town = grounded_town(collected, text)
    ptype = grounded_type(collected, text)
    if not town or not ptype:
        return False
    if role_clean in {"seller", "owner"}:
        if collected.get("seller_evidence") != "explicit" and not is_explicit_seller_statement(text):
            return False
        return bool(collected.get("asking_price_grounded") or own_asking_price(text))
    if role_clean == "buyer":
        return bool(collected.get("buyer_budget_grounded") or own_buyer_budget(text))
    if role_clean in {"renter", "tenant"}:
        return bool(collected.get("rent_budget_grounded") or own_rent_budget(text))
    return False


_PROMISE_SENTENCE = re.compile(
    r"[^.!?\n]*("
    r"ah tuck|阿tuck|ah tat|阿tat|012-?966\s*3589|\+60129663589"
    r"|right away|immediately contact|contact you shortly"
    r"|will (?:shortly )?contact you|will reach out"
    r"|senior (?:property |commercial )?(?:specialist|lead|agent)"
    r"|专员将|马上联系|立刻"
    r")[^.!?\n]*[.!]?",
    re.IGNORECASE,
)


def sanitize_unverified_reply(text: str) -> str:
    """Remove specialist-contact promises when nobody was actually assigned."""
    if not text:
        return text
    cleaned = _PROMISE_SENTENCE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if cleaned:
        return cleaned
    return (
        "Thanks for the details. I am still checking this for you here. "
        "Could you tell me a little more about what you need?"
    )

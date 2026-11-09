"""
Switches for reclassification and the weekly customer report.

Nick's decisions (16:14 MYT) are the defaults. Two switches remain so the
live path can be turned back without a code change:

BACKFILL_LOCK_ALLOW_OVERRIDE
    Default on. A later message that is itself an explicit role statement
    may replace a backfill-locked category. The previous role, an ISO
    timestamp, and the previous source (backfill, live, or manual) are kept.
    Set to 0 to queue that statement for review instead of applying it.
    Photos, title-document extracts, classifier labels, and model flags
    never count as the statement.

REPORT_USE_LEGACY_TEMPLATE
    Default off. The Monday WhatsApp digest sends ``weekly_category_report``
    (or ``WHATSAPP_WEEKLY_REPORT_TEMPLATE``). Set to 1 to send the previous
    template ``weekly_business_report_digest`` until the new Utility template
    exists in Meta. The legacy template's own wording is whatever Meta has
    approved; this code path does not describe customers as owners.

WHATSAPP_WEEKLY_REPORT_TEMPLATE
    Configurable name for the new template. Default ``weekly_category_report``.

WHATSAPP_WEEKLY_REPORT_LEGACY_TEMPLATE
    Name used only when the legacy flag is on. Default
    ``weekly_business_report_digest``.

The weekly workbook always has these tabs: Executive Summary, Buyer, Seller,
Agent, Tenant, Landlord, Uncertain. Website listings are not part of the report.
"""

import os

NEW_TEMPLATE_NAME = "weekly_category_report"
LEGACY_TEMPLATE_NAME = "weekly_business_report_digest"


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def backfill_lock_allows_override() -> bool:
    """True unless BACKFILL_LOCK_ALLOW_OVERRIDE is explicitly turned off."""
    raw = os.getenv("BACKFILL_LOCK_ALLOW_OVERRIDE")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def use_legacy_weekly_template() -> bool:
    """True when Monday WhatsApp should keep sending the previous template."""
    return _enabled("REPORT_USE_LEGACY_TEMPLATE")


def weekly_template_name() -> str:
    if use_legacy_weekly_template():
        return os.getenv("WHATSAPP_WEEKLY_REPORT_LEGACY_TEMPLATE", LEGACY_TEMPLATE_NAME)
    return os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE", NEW_TEMPLATE_NAME)

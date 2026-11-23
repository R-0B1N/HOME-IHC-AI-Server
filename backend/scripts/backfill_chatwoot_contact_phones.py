#!/usr/bin/env python3
"""Propose Chatwoot phone fills for blank contacts. Dry-run unless ``--apply``.

A phone is proposed only from a digit ``contact_inboxes.source_id``, a digit
``identifier``, or a local customer whose ``metadata_json.chatwoot_contact_id``
matches. BSUID-only contacts are listed as ``no_digit_source`` and are not
updated. ``--apply`` fills a blank phone and never overwrites a different one.

This script does not run itself on import. Do not point it at production
without an explicit approval.
"""

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.contact_identity import is_bsuid, is_digit_identifier, to_e164


def _digit_phone(value):
    if not is_digit_identifier(value):
        return None
    return to_e164(value)


def phone_from_contact(contact):
    """Digit source_id, then digit identifier. A BSUID is not a phone."""
    for inbox in contact.get("contact_inboxes") or []:
        if not isinstance(inbox, dict):
            continue
        phone = _digit_phone(inbox.get("source_id"))
        if phone:
            return phone, "source_id"
    phone = _digit_phone(contact.get("identifier"))
    if phone:
        return phone, "identifier"
    return None, None


def _is_bsuid_only(contact) -> bool:
    values = [contact.get("identifier")]
    for inbox in contact.get("contact_inboxes") or []:
        if isinstance(inbox, dict):
            values.append(inbox.get("source_id"))
    present = [value for value in values if value]
    return bool(present) and all(is_bsuid(value) for value in present)


def plan_updates(contacts, local_customers=None):
    """Return one proposal per contact. Nothing here writes."""
    local_customers = local_customers or []
    by_contact_id = {}
    phones_in_use = {}
    for row in local_customers:
        meta = row.get("metadata_json") or {}
        contact_id = meta.get("chatwoot_contact_id")
        phone = to_e164(row.get("id"))
        if contact_id not in (None, ""):
            by_contact_id[contact_id] = phone
        if phone:
            phones_in_use.setdefault(phone, set()).add(contact_id)

    seen_chatwoot = {}
    proposals = []
    for contact in contacts or []:
        contact_id = contact.get("id")
        existing = str(contact.get("phone_number") or "").strip()
        existing_e164 = to_e164(existing) if existing else None
        if existing_e164:
            seen_chatwoot.setdefault(existing_e164, set()).add(contact_id)
        proposed, source = phone_from_contact(contact)
        local_phone = by_contact_id.get(contact_id)
        if not proposed and local_phone:
            proposed, source = local_phone, "customer"
        if existing_e164:
            if proposed and proposed != existing_e164:
                proposals.append({
                    "action": "conflict",
                    "contact_id": contact_id,
                    "reason": "phone already set",
                    "phone": existing_e164,
                    "proposed": proposed,
                })
            else:
                proposals.append({
                    "action": "skip",
                    "contact_id": contact_id,
                    "reason": "phone present",
                    "phone": existing_e164,
                })
            continue
        if not proposed:
            proposals.append({
                "action": "no_digit_source",
                "contact_id": contact_id,
                "reason": "bsuid" if _is_bsuid_only(contact) else "no digit source",
            })
            continue
        if local_phone and local_phone != proposed:
            proposals.append({
                "action": "conflict",
                "contact_id": contact_id,
                "reason": "local row disagrees",
                "proposed": proposed,
                "local_phone": local_phone,
            })
            continue
        holders = set(seen_chatwoot.get(proposed) or [])
        holders.update(phones_in_use.get(proposed) or [])
        holders.discard(contact_id)
        if holders:
            proposals.append({
                "action": "conflict",
                "contact_id": contact_id,
                "reason": "another contact already has that phone",
                "proposed": proposed,
            })
            continue
        seen_chatwoot.setdefault(proposed, set()).add(contact_id)
        proposals.append({
            "action": "fill",
            "contact_id": contact_id,
            "phone": proposed,
            "source": source,
        })
    return proposals


def apply_plans(proposals, client, apply=False):
    """Write only ``fill`` rows, and only when ``apply`` is true."""
    written = []
    for proposal in proposals or []:
        if proposal.get("action") != "fill":
            continue
        if not apply:
            continue
        client.update_phone(proposal["contact_id"], proposal["phone"])
        written.append(proposal)
    return written


def format_proposal(proposal) -> str:
    action = proposal.get("action")
    contact_id = proposal.get("contact_id")
    if action == "fill":
        return f"fill contact={contact_id} phone={proposal.get('phone')} source={proposal.get('source')}"
    if action == "no_digit_source":
        return f"no_digit_source contact={contact_id} reason={proposal.get('reason')}"
    if action == "conflict":
        return f"conflict contact={contact_id} reason={proposal.get('reason')}"
    return f"skip contact={contact_id} reason={proposal.get('reason')}"


class ChatwootContactClient:
    """Paging client. Constructed only from ``main``, never at import."""

    def __init__(self, base_url, token, account_id):
        import requests

        self.requests = requests
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.headers = {"api_access_token": token, "Content-Type": "application/json"}

    def iter_contacts(self):
        page = 1
        while True:
            url = f"{self.base_url}/api/v1/accounts/{self.account_id}/contacts"
            response = self.requests.get(url, headers=self.headers, params={"page": page}, timeout=30)
            response.raise_for_status()
            body = response.json()
            payload = body.get("payload") if isinstance(body, dict) else body
            if not payload:
                break
            for contact in payload:
                yield contact
            if len(payload) < 15:
                break
            page += 1
            if page > 10000:
                break

    def update_phone(self, contact_id, phone):
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/contacts/{contact_id}"
        response = self.requests.put(
            url,
            headers=self.headers,
            json={"phone_number": phone},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def _local_customers():
    from app.db.models import Customer, SessionLocal

    db = SessionLocal()
    try:
        rows = []
        for row in db.query(Customer).all():
            rows.append({
                "id": row.id,
                "metadata_json": dict(row.metadata_json or {}),
            })
        return rows
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill blank Chatwoot contact phones.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write blank phones. Without this flag the script only prints.",
    )
    args = parser.parse_args(argv)
    base_url = os.getenv("CHATWOOT_BASE_URL", "")
    token = os.getenv("CHATWOOT_API_TOKEN", "")
    account_id = os.getenv("CHATWOOT_ACCOUNT_ID", "1")
    if not base_url or not token:
        print("CHATWOOT_BASE_URL and CHATWOOT_API_TOKEN are required. Nothing was written.")
        return 2
    client = ChatwootContactClient(base_url, token, account_id)
    contacts = list(client.iter_contacts())
    try:
        local_rows = _local_customers()
    except Exception as exc:
        print(f"local customers unavailable: {exc}")
        local_rows = []
    proposals = plan_updates(contacts, local_rows)
    for proposal in proposals:
        print(format_proposal(proposal))
    written = apply_plans(proposals, client, apply=bool(args.apply))
    mode = "apply" if args.apply else "dry-run"
    print(f"{mode}: contacts={len(contacts)} fills={len(written)} writes={'yes' if args.apply else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Server-side recategorization.

``dry_run`` (the default) reads customers and Chatwoot with GET only, writes a
CSV and an xlsx under the reports directory, and does not commit or relabel.
``apply`` requires conversation ids accepted from that dry-run. It snapshots
metadata and the full label list first, merges only the managed labels, locks
the category, and clears the Redis session. ``rollback`` restores a batch.

Rules run first (``classify_transcript``). A high-confidence explicit role
does not call the model. The remainder uses the on-server vLLM client.
"""

import csv
import datetime
import hashlib
import json
import os
import time
import uuid
from types import SimpleNamespace

from app.services.customer_classification import (
    MANAGED_LABELS,
    canonical_category_name,
    classify_transcript,
    is_customer_message,
    mask_phone,
    proposed_labels,
    stored_category,
    stored_temperature,
)
from app.services.reporting import DEFAULT_REPORTS_DIR, OpenXmlSpreadsheetBuilder

# Re-export so older tests and the CLI share one column list.
CSV_COLUMNS = [
    "conversation_id",
    "contact",
    "phone_masked",
    "current_category",
    "current_temperature",
    "current_labels",
    "proposed_category",
    "proposed_temperature",
    "proposed_labels",
    "confidence",
    "evidence_quote",
    "reason",
    "decided_by",
    "previous_role",
    "previous_role_at",
    "previous_role_source",
    "transcript_hash",
]

PAGE_SIZE = 20
_READ_SQL = {"SELECT", "WITH", "SHOW", "SET", "EXPLAIN", "ROLLBACK", "BEGIN", "START"}


class ReadOnlyViolation(RuntimeError):
    """dry_run tried to write, or Chatwoot was called with anything but GET."""


def assert_sql_is_read_only(statement: str) -> None:
    text = (statement or "").strip()
    if not text:
        raise ReadOnlyViolation("empty SQL")
    while text.startswith("(") or text.startswith("/*") or text.startswith("--"):
        if text.startswith("--"):
            newline = text.find("\n")
            text = text[newline + 1:].strip() if newline != -1 else ""
        elif text.startswith("/*"):
            end = text.find("*/")
            text = text[end + 2:].strip() if end != -1 else ""
        else:
            text = text[1:].strip()
    if not text:
        raise ReadOnlyViolation("empty SQL")
    head = text.split(None, 1)[0].upper()
    if head not in _READ_SQL:
        raise ReadOnlyViolation(f"refusing SQL {head}")
    if head == "SET" and "READ ONLY" not in text.upper() and "CHARACTERISTICS" not in text.upper():
        raise ReadOnlyViolation("refusing SET that is not a read-only session setting")


def chatwoot_read(method: str, url: str, **kwargs):
    """GET-only. POST, PUT, PATCH, and DELETE raise before any socket call."""
    verb = (method or "").upper()
    if verb != "GET":
        raise ReadOnlyViolation(f"refusing Chatwoot {verb or 'UNKNOWN'}")
    import requests
    return requests.request(verb, url, **kwargs)


class RateLimiter:
    def __init__(self, rate: float):
        if not rate or rate <= 0:
            rate = 1.0
        self.min_interval = 1.0 / float(rate)
        self._next = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next:
            time.sleep(self._next - now)
        self._next = time.monotonic() + self.min_interval


def merge_labels(existing, category: str, temperature: str) -> list:
    """Drop managed role/temperature labels and append the proposal. Keep the rest."""
    kept = []
    for label in existing or []:
        if str(label).strip().lower() not in MANAGED_LABELS and label not in kept:
            kept.append(label)
    for label in proposed_labels(category, temperature):
        if label not in kept:
            kept.append(label)
    return kept


def transcript_hash(texts) -> str:
    payload = "\n".join(texts or []).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def output_dir() -> str:
    root = os.getenv("REPORTS_OUTPUT_DIR") or DEFAULT_REPORTS_DIR
    path = os.path.join(root, "recategorize")
    os.makedirs(path, exist_ok=True)
    return path


def paginate_messages(conversation_id, fetch_page, page_size: int = PAGE_SIZE):
    before = None
    seen = set()
    while True:
        batch = list(fetch_page(conversation_id, before) or [])
        if not batch:
            break
        fresh = []
        for message in batch:
            message_id = message.get("id") if isinstance(message, dict) else None
            if message_id in seen:
                continue
            if message_id is not None:
                seen.add(message_id)
            fresh.append(message)
        if not fresh:
            break
        for message in fresh:
            yield message
        ids = [message.get("id") for message in fresh if isinstance(message, dict) and message.get("id") is not None]
        if not ids:
            break
        next_before = min(ids)
        if next_before == before:
            break
        before = next_before
        if len(batch) < page_size:
            break


def customer_texts(messages):
    selected = [message for message in messages if isinstance(message, dict) and is_customer_message(message)]
    selected.sort(key=lambda message: (message.get("id") or 0, message.get("created_at") or 0))
    return selected


def _labels_of(details) -> list:
    if not isinstance(details, dict):
        return []
    labels = details.get("labels")
    if labels is None and isinstance(details.get("payload"), dict):
        labels = details["payload"].get("labels")
    if isinstance(labels, list):
        return list(labels)
    if isinstance(labels, str) and labels:
        return [labels]
    return []


def _row(customer, conversation_id, classification, details) -> dict:
    metadata = getattr(customer, "metadata_json", None) or {}
    current = stored_category(metadata)
    canonical_current = canonical_category_name(current) if current else ""
    proposed = classification or {}
    return {
        "conversation_id": "" if conversation_id is None else str(conversation_id),
        "contact": getattr(customer, "contact_name", None) or "",
        "phone_masked": mask_phone(str(getattr(customer, "id", "") or "")),
        "current_category": current,
        "current_temperature": stored_temperature(metadata),
        "current_labels": "|".join(_labels_of(details or {})),
        "proposed_category": proposed.get("category", "uncertain"),
        "proposed_temperature": proposed.get("temperature", "uncertain"),
        "proposed_labels": "|".join(proposed.get("proposed_labels") or []),
        "confidence": proposed.get("confidence", "low"),
        "evidence_quote": proposed.get("evidence_quote", ""),
        "reason": proposed.get("reason", ""),
        "decided_by": proposed.get("decided_by", ""),
        "previous_role": canonical_current,
        "previous_role_at": "",
        "previous_role_source": metadata.get("classification_source") or "",
        "transcript_hash": proposed.get("transcript_hash", ""),
    }


def summarize(rows) -> dict:
    counts = {}
    for row in rows:
        key = f"{row.get('proposed_category') or 'uncertain'}|{row.get('proposed_temperature') or 'uncertain'}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def write_csv(path: str, rows, append: bool = False) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    exists = append and os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a" if exists else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_xlsx(path: str, rows) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    table = [[row.get(column, "") for column in CSV_COLUMNS] for row in rows]
    payload = OpenXmlSpreadsheetBuilder.build_single_sheet(CSV_COLUMNS, table, sheet_name="Recategorize")
    with open(path, "wb") as handle:
        handle.write(payload)


def iter_targets(customers, conversation_id=None):
    wanted = None if conversation_id in (None, "") else str(conversation_id)
    matched = False
    for customer in customers:
        ids = [str(item) for item in (getattr(customer, "conversation_ids", None) or []) if item not in (None, "")]
        if wanted is not None:
            if wanted in ids:
                matched = True
                yield customer, wanted
            continue
        if not ids:
            yield customer, None
            continue
        for conv_id in ids:
            yield customer, conv_id
    if wanted is not None and not matched:
        yield SimpleNamespace(id="", contact_name="", conversation_ids=[wanted], metadata_json={}), wanted


class MemoryJobStore:
    """In-memory jobs and snapshots. Tests use this. Production uses SqlJobStore."""

    def __init__(self):
        self.jobs = {}
        self.snapshots = {}

    def create_job(self, **fields) -> dict:
        batch_id = fields.get("batch_id") or uuid.uuid4().hex
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        job = {
            "batch_id": batch_id,
            "mode": fields.get("mode") or "dry_run",
            "status": "queued",
            "done": 0,
            "total": 0,
            "output_csv": fields.get("output_csv") or os.path.join(output_dir(), f"{batch_id}.csv"),
            "output_xlsx": fields.get("output_xlsx") or os.path.join(output_dir(), f"{batch_id}.xlsx"),
            "checkpoint_json": list(fields.get("checkpoint_json") or []),
            "accepted_ids": list(fields.get("accepted_ids") or []),
            "summary_json": {},
            "error": None,
            "rate": fields.get("rate") if fields.get("rate") is not None else 1.0,
            "conversation_limit": fields.get("conversation_limit"),
            "conversation_id": fields.get("conversation_id"),
            "created_at": now,
            "updated_at": now,
        }
        self.jobs[batch_id] = job
        return dict(job)

    def get_job(self, batch_id: str):
        job = self.jobs.get(batch_id)
        return dict(job) if job else None

    def update_job(self, batch_id: str, **fields) -> dict:
        job = self.jobs[batch_id]
        job.update(fields)
        job["updated_at"] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        return dict(job)

    def add_snapshot(self, **fields) -> dict:
        key = (fields["batch_id"], str(fields["conversation_id"]))
        if key in self.snapshots:
            return dict(self.snapshots[key])
        row = {
            "applied": False,
            "rolled_back": False,
            "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        }
        row.update(fields)
        row["conversation_id"] = str(row["conversation_id"])
        self.snapshots[key] = row
        return dict(row)

    def get_snapshot(self, batch_id: str, conversation_id: str):
        row = self.snapshots.get((batch_id, str(conversation_id)))
        return dict(row) if row else None

    def mark_snapshot(self, batch_id: str, conversation_id: str, **fields) -> None:
        key = (batch_id, str(conversation_id))
        self.snapshots[key].update(fields)

    def list_snapshots(self, batch_id: str) -> list:
        return [dict(row) for (bid, _cid), row in self.snapshots.items() if bid == batch_id]


def execute_dry_run(
    *,
    customers,
    fetch_page,
    fetch_details,
    store: MemoryJobStore,
    batch_id: str,
    llm_classify=None,
    limit: int = None,
    conversation_id=None,
    resume: bool = False,
    page_size: int = PAGE_SIZE,
) -> dict:
    """
    Classify and write CSV + xlsx. Does not call a label writer, does not save
    customers, and does not clear Redis. ``fetch_page`` / ``fetch_details`` must be GET.
    """
    job = store.get_job(batch_id)
    if not job:
        raise KeyError(batch_id)
    done = set(job.get("checkpoint_json") or []) if resume else set()
    processed = set(done)
    rows = []
    produced = 0
    csv_path = job["output_csv"]
    targets = list(iter_targets(customers, conversation_id=conversation_id or job.get("conversation_id")))
    store.update_job(batch_id, status="running", total=len(targets), mode="dry_run")
    appending = resume and os.path.exists(csv_path)

    for customer, conv_id in targets:
        if conv_id is not None and str(conv_id) in done:
            continue
        if limit is not None and produced >= limit:
            break
        if conv_id is None:
            classification = {
                "category": "uncertain",
                "temperature": "uncertain",
                "confidence": "low",
                "evidence_quote": "",
                "reason": "no_transcript",
                "proposed_labels": ["uncertain", "needs-review"],
                "decided_by": "rules",
                "transcript_hash": "",
            }
            details = {}
        else:
            messages = list(paginate_messages(conv_id, fetch_page, page_size=page_size))
            texts = customer_texts(messages)
            plain = [(message.get("content") or "") for message in texts]
            if not texts:
                classification = {
                    "category": "uncertain",
                    "temperature": "uncertain",
                    "confidence": "low",
                    "evidence_quote": "",
                    "reason": "no_transcript",
                    "proposed_labels": ["uncertain", "needs-review"],
                    "decided_by": "rules",
                    "transcript_hash": "",
                }
            else:
                classification = classify_transcript(texts, llm_classify=llm_classify)
                classification["transcript_hash"] = transcript_hash(plain)
            details = fetch_details(conv_id) if fetch_details else {}
            processed.add(str(conv_id))
        row = _row(customer, conv_id, classification, details)
        rows.append(row)
        produced += 1
        write_csv(csv_path, [row], append=appending or produced > 1)
        appending = True
        store.update_job(
            batch_id,
            done=len(processed) if conv_id is not None else produced,
            checkpoint_json=sorted(processed),
        )

    summary = summarize(rows)
    xlsx_path = job["output_xlsx"]
    # Rebuild the workbook from the CSV so a resumed run includes earlier rows.
    all_rows = _read_csv(csv_path)
    write_xlsx(xlsx_path, all_rows)
    store.update_job(batch_id, status="completed", summary_json=summary, done=produced)
    return {"batch_id": batch_id, "rows": rows, "summary": summary, "output_csv": csv_path, "output_xlsx": xlsx_path}


def _read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def execute_apply(
    *,
    store: MemoryJobStore,
    batch_id: str,
    accepted_conversation_ids,
    customers,
    read_labels,
    write_labels,
    save_customer,
    reset_session,
    now: datetime.datetime = None,
) -> dict:
    """
    Apply accepted dry-run rows. Snapshots first. Refuses when the dry-run CSV is missing.
    A conversation already applied in this batch is skipped (idempotent).
    """
    job = store.get_job(batch_id)
    if not job:
        raise KeyError(batch_id)
    if job.get("mode") not in {"dry_run", "apply"}:
        raise ReadOnlyViolation("refusing apply against an unknown mode")
    rows = {row["conversation_id"]: row for row in _read_csv(job["output_csv"])}
    accepted = [str(item) for item in (accepted_conversation_ids or [])]
    if not accepted:
        raise ValueError("accepted_conversation_ids is required")
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    stamp = moment.replace(microsecond=0).isoformat()
    by_conv = {}
    for customer in customers:
        for conv_id in getattr(customer, "conversation_ids", None) or []:
            by_conv[str(conv_id)] = customer

    applied = []
    skipped = []
    for conv_id in accepted:
        row = rows.get(str(conv_id))
        if not row:
            skipped.append({"conversation_id": str(conv_id), "reason": "not_in_dry_run"})
            continue
        existing = store.get_snapshot(batch_id, conv_id)
        if existing and existing.get("applied") and not existing.get("rolled_back"):
            skipped.append({"conversation_id": str(conv_id), "reason": "already_applied"})
            continue
        customer = by_conv.get(str(conv_id))
        if customer is None:
            skipped.append({"conversation_id": str(conv_id), "reason": "customer_not_found"})
            continue
        previous_labels = list(read_labels(conv_id) or [])
        previous_metadata = dict(getattr(customer, "metadata_json", None) or {})
        if not existing:
            store.add_snapshot(
                batch_id=batch_id,
                conversation_id=str(conv_id),
                customer_id=str(getattr(customer, "id", "") or ""),
                previous_metadata=previous_metadata,
                previous_labels=previous_labels,
                proposed_category=row.get("proposed_category"),
                proposed_temperature=row.get("proposed_temperature"),
                transcript_hash=row.get("transcript_hash") or "",
            )
        category = row.get("proposed_category") or "uncertain"
        temperature = row.get("proposed_temperature") or "uncertain"
        updated = dict(previous_metadata)
        updated["previous_role"] = canonical_category_name(stored_category(previous_metadata)) if stored_category(previous_metadata) else ""
        updated["previous_role_at"] = stamp
        updated["previous_role_source"] = previous_metadata.get("classification_source") or "manual"
        updated["intent_category"] = category
        updated["customer_category"] = category
        updated["locked_intent"] = category
        updated["locked_category"] = category
        updated["lead_temp"] = temperature
        updated["intention_tag"] = temperature
        updated["classification_locked"] = True
        updated["classification_source"] = "backfill"
        updated["classification_batch"] = batch_id
        updated["classification_hash"] = row.get("transcript_hash") or ""
        customer.metadata_json = updated
        save_customer(customer)
        write_labels(conv_id, merge_labels(previous_labels, category, temperature))
        if getattr(customer, "id", None):
            reset_session(str(customer.id))
        store.mark_snapshot(batch_id, conv_id, applied=True, rolled_back=False)
        applied.append(str(conv_id))

    store.update_job(batch_id, status="applied", mode="apply", accepted_ids=accepted)
    return {"batch_id": batch_id, "applied": applied, "skipped": skipped}


def execute_rollback(*, store: MemoryJobStore, batch_id: str, customers, write_labels, save_customer, reset_session) -> dict:
    snapshots = store.list_snapshots(batch_id)
    by_id = {str(customer.id): customer for customer in customers}
    restored = []
    for snap in snapshots:
        if not snap.get("applied") or snap.get("rolled_back"):
            continue
        customer = by_id.get(str(snap.get("customer_id") or ""))
        if customer is None:
            continue
        customer.metadata_json = dict(snap.get("previous_metadata") or {})
        save_customer(customer)
        write_labels(snap["conversation_id"], list(snap.get("previous_labels") or []))
        if customer.id:
            reset_session(str(customer.id))
        store.mark_snapshot(batch_id, snap["conversation_id"], rolled_back=True, applied=False)
        restored.append(str(snap["conversation_id"]))
    store.update_job(batch_id, status="rolled_back")
    return {"batch_id": batch_id, "restored": restored}


def _job_dict(row) -> dict:
    checkpoint = row.checkpoint_json or []
    accepted = row.accepted_ids or []
    summary = row.summary_json or {}
    return {
        "batch_id": row.batch_id,
        "mode": row.mode,
        "status": row.status,
        "done": row.done or 0,
        "total": row.total or 0,
        "output_csv": row.output_csv,
        "output_xlsx": row.output_xlsx,
        "checkpoint_json": list(checkpoint),
        "accepted_ids": list(accepted),
        "summary_json": dict(summary),
        "error": row.error,
        "rate": row.rate if row.rate is not None else 1.0,
        "conversation_limit": row.conversation_limit,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class SqlJobStore:
    """Postgres-backed jobs. Writes here are job rows, not customer labels."""

    def create_job(self, **fields) -> dict:
        from app.db.models import RecategorizeJob, SessionLocal
        batch_id = fields.get("batch_id") or uuid.uuid4().hex
        db = SessionLocal()
        try:
            row = RecategorizeJob(
                batch_id=batch_id,
                mode=fields.get("mode") or "dry_run",
                status="queued",
                output_csv=fields.get("output_csv") or os.path.join(output_dir(), f"{batch_id}.csv"),
                output_xlsx=fields.get("output_xlsx") or os.path.join(output_dir(), f"{batch_id}.xlsx"),
                checkpoint_json=list(fields.get("checkpoint_json") or []),
                accepted_ids=list(fields.get("accepted_ids") or []),
                summary_json={},
                rate=fields.get("rate") if fields.get("rate") is not None else 1.0,
                conversation_limit=fields.get("conversation_limit"),
                conversation_id=fields.get("conversation_id"),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _job_dict(row)
        finally:
            db.close()

    def get_job(self, batch_id: str):
        from app.db.models import RecategorizeJob, SessionLocal
        db = SessionLocal()
        try:
            row = db.query(RecategorizeJob).filter(RecategorizeJob.batch_id == batch_id).first()
            return _job_dict(row) if row else None
        finally:
            db.close()

    def update_job(self, batch_id: str, **fields) -> dict:
        from sqlalchemy.orm.attributes import flag_modified
        from app.db.models import RecategorizeJob, SessionLocal
        db = SessionLocal()
        try:
            row = db.query(RecategorizeJob).filter(RecategorizeJob.batch_id == batch_id).first()
            if row is None:
                raise KeyError(batch_id)
            for key, value in fields.items():
                setattr(row, key, value)
                if key in {"checkpoint_json", "accepted_ids", "summary_json"}:
                    flag_modified(row, key)
            row.updated_at = datetime.datetime.utcnow()
            db.commit()
            db.refresh(row)
            return _job_dict(row)
        finally:
            db.close()

    def add_snapshot(self, **fields) -> dict:
        from app.db.models import RecategorizeSnapshot, SessionLocal
        db = SessionLocal()
        try:
            existing = (
                db.query(RecategorizeSnapshot)
                .filter(
                    RecategorizeSnapshot.batch_id == fields["batch_id"],
                    RecategorizeSnapshot.conversation_id == str(fields["conversation_id"]),
                )
                .first()
            )
            if existing:
                return _snapshot_dict(existing)
            row = RecategorizeSnapshot(
                batch_id=fields["batch_id"],
                conversation_id=str(fields["conversation_id"]),
                customer_id=fields.get("customer_id"),
                previous_metadata=fields.get("previous_metadata") or {},
                previous_labels=fields.get("previous_labels") or [],
                proposed_category=fields.get("proposed_category"),
                proposed_temperature=fields.get("proposed_temperature"),
                transcript_hash=fields.get("transcript_hash"),
                applied=False,
                rolled_back=False,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _snapshot_dict(row)
        finally:
            db.close()

    def get_snapshot(self, batch_id: str, conversation_id: str):
        from app.db.models import RecategorizeSnapshot, SessionLocal
        db = SessionLocal()
        try:
            row = (
                db.query(RecategorizeSnapshot)
                .filter(
                    RecategorizeSnapshot.batch_id == batch_id,
                    RecategorizeSnapshot.conversation_id == str(conversation_id),
                )
                .first()
            )
            return _snapshot_dict(row) if row else None
        finally:
            db.close()

    def mark_snapshot(self, batch_id: str, conversation_id: str, **fields) -> None:
        from app.db.models import RecategorizeSnapshot, SessionLocal
        db = SessionLocal()
        try:
            row = (
                db.query(RecategorizeSnapshot)
                .filter(
                    RecategorizeSnapshot.batch_id == batch_id,
                    RecategorizeSnapshot.conversation_id == str(conversation_id),
                )
                .first()
            )
            if row is None:
                raise KeyError(conversation_id)
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
        finally:
            db.close()

    def list_snapshots(self, batch_id: str) -> list:
        from app.db.models import RecategorizeSnapshot, SessionLocal
        db = SessionLocal()
        try:
            rows = db.query(RecategorizeSnapshot).filter(RecategorizeSnapshot.batch_id == batch_id).all()
            return [_snapshot_dict(row) for row in rows]
        finally:
            db.close()


def _snapshot_dict(row) -> dict:
    return {
        "batch_id": row.batch_id,
        "conversation_id": str(row.conversation_id),
        "customer_id": row.customer_id,
        "previous_metadata": dict(row.previous_metadata or {}),
        "previous_labels": list(row.previous_labels or []),
        "proposed_category": row.proposed_category,
        "proposed_temperature": row.proposed_temperature,
        "transcript_hash": row.transcript_hash,
        "applied": bool(row.applied),
        "rolled_back": bool(row.rolled_back),
    }


def get_json(url: str, *, params: dict, headers: dict, rate_limiter: RateLimiter, timeout: float = 30):
    delay = 1.0
    last = None
    for _attempt in range(5):
        rate_limiter.wait()
        response = chatwoot_read("GET", url, params=params, headers=headers, timeout=timeout)
        last = response
        if getattr(response, "status_code", 200) == 429:
            raw = ""
            try:
                raw = response.headers.get("Retry-After") or ""
            except Exception:
                raw = ""
            try:
                wait = max(float(raw), delay)
            except (TypeError, ValueError):
                wait = delay
            time.sleep(wait)
            delay = min(delay * 2, 60.0)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Chatwoot kept returning 429 for {url}") if last is not None else RuntimeError("no response")


def build_chatwoot_fetchers(rate: float):
    base = os.environ.get("CHATWOOT_BASE_URL", "").rstrip("/")
    token = os.environ.get("CHATWOOT_API_TOKEN", "")
    account = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    if not base or not token:
        raise RuntimeError("CHATWOOT_BASE_URL and CHATWOOT_API_TOKEN are required")
    headers = {"api_access_token": token}
    limiter = RateLimiter(rate)

    def fetch_page(conversation_id, before):
        url = f"{base}/api/v1/accounts/{account}/conversations/{conversation_id}/messages"
        params = {}
        if before is not None:
            params["before"] = before
        payload = get_json(url, params=params, headers=headers, rate_limiter=limiter)
        return payload.get("payload") or []

    def fetch_details(conversation_id):
        url = f"{base}/api/v1/accounts/{account}/conversations/{conversation_id}"
        return get_json(url, params={}, headers=headers, rate_limiter=limiter)

    return fetch_page, fetch_details


def load_customers_read_only():
    """SELECT customers inside a transaction the server will reject writes on."""
    from sqlalchemy import event, text
    from app.db.models import Customer, SessionLocal

    db = SessionLocal()

    def _refuse(*_args, **_kwargs):
        raise ReadOnlyViolation("dry-run refuses to commit")

    db.commit = _refuse

    def _before(conn, cursor, statement, parameters, context, executemany):
        assert_sql_is_read_only(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", _before)
    try:
        db.connection().execute(text("SET TRANSACTION READ ONLY"))
        loaded = []
        for customer in db.query(Customer).all():
            loaded.append(SimpleNamespace(
                id=customer.id,
                contact_name=customer.contact_name,
                conversation_ids=list(customer.conversation_ids or []),
                metadata_json=dict(customer.metadata_json or {}),
            ))
        return loaded
    finally:
        event.remove(bind, "before_cursor_execute", _before)
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def load_customers_for_apply():
    from app.db.models import Customer, SessionLocal
    db = SessionLocal()
    try:
        loaded = []
        for customer in db.query(Customer).all():
            loaded.append(SimpleNamespace(
                id=customer.id,
                contact_name=customer.contact_name,
                conversation_ids=list(customer.conversation_ids or []),
                metadata_json=dict(customer.metadata_json or {}),
            ))
        return loaded
    finally:
        db.close()


def save_customer_metadata(customer) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from app.db.models import Customer, SessionLocal
    db = SessionLocal()
    try:
        row = db.query(Customer).filter(Customer.id == customer.id).first()
        if row is None:
            raise KeyError(customer.id)
        row.metadata_json = dict(customer.metadata_json or {})
        flag_modified(row, "metadata_json")
        db.commit()
    finally:
        db.close()


def production_label_io():
    from app.services.chatwoot import apply_label, get_conversation_details

    def read_labels(conversation_id):
        details = get_conversation_details(int(conversation_id)) or {}
        labels = details.get("labels") or []
        return list(labels)

    def write_labels(conversation_id, labels):
        apply_label(int(conversation_id), list(labels))

    return read_labels, write_labels


def production_reset_session(phone: str) -> None:
    from app.services.session_manager import SessionManager
    SessionManager.reset_session(phone)

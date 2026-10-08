# System Architecture & Tech Stack Reference

> **Living Canonical Source:** Located in the companion Obsidian vault at:  
> [`Home-IHC/Architecture/Tech Stack & Infrastructure.md`](file:///Users/nick/Work/HOME%20IHC/Home-IHC/Architecture/Tech%20Stack%20&%20Infrastructure.md)

This document defines the canonical technology stack, approved libraries, infrastructure topology, and architectural invariants for the **Home IHC Real Estate WhatsApp AI CRM**.

---

## 1. Quick Library Reference for Feature Implementation

When implementing new features or bug fixes, use **strictly** the approved libraries:

* **Web Framework:** `FastAPI` (0.111.0) + `Uvicorn` (0.30.1) with async routers and Pydantic v2 schemas.
* **Asynchronous Jobs:** `Celery` (5.4.0) + `Redis` (5.0.4) broker. Never use ad-hoc background threads for long tasks.
* **Scheduled Daemons:** Celery Beat (`run-lead-nurturing-daemon-hourly`, `generate-weekly-reports-monday`).
* **Relational & Vector Database:** PostgreSQL 16 with `pgvector` (0.2.5). In-DB cosine distance operator `<=>` via SQLAlchemy `func.cosine_distance()`.
* **PDF Generation & Mobile Delivery:** `PyMuPDF` (`fitz` 1.24.4) for vector PDF transcripts with CJK font support. (Do NOT install `reportlab` or `weasyprint`). Inbound client PDFs automatically render Page 1 as high-res JPEG for inline Chatwoot Mobile note rendering; streaming proxy endpoint at `/api/v1/documents/proxy/{filename:path}`.
* **Word Document Generation:** `python-docx` (1.1.2) with explicit `<w:tblBorders>` XML injection to prevent headless LibreOffice border stripping.
* **Excel Reporting:** `openpyxl` (3.1.2) with native `zipfile` fallback.
* **LLM Client & Dynamic Handover:** `openai` (>=1.0.0) with response-first sparse JSON formatting. Schema mandates `"promises_handover": true` on any turn promising human staff contact or viewings, immediately transitioning session to completed and opening Chatwoot conversation (`update_conversation_status("open")`, `set_priority("urgent")`, labels `human-handover`, `hot-lead`). Secondary regex heuristic failover via `is_handover_promised`.
* **Tag-Based RBAC Routing Engine:** Dynamic multi-tag specialization scoring (`calculate_agent_specialization_score`) across `assigned_locations` and `assigned_property_types` with synonym expansions. Dispatches hot leads (`dispatch_hot_lead_handover`) via Meta WhatsApp template and customer vCard contact card. Handles ties via shared case notices, and falls back to general admin lines (`DEFAULT_FALLBACK_ADMIN_NUMBERS`). Supersedes legacy 2-number routing.
* **Property Vector Search & WordPress Sync:** PostgreSQL 16 with `pgvector` (0.2.5) storing 5-aspect embeddings (`fastembed`). Ingests WordPress listings via REST API with vector normalization.
* **Frontend Dashboard:** React 19 + Vite 8 in `property-dashboard/` with `oxlint` and `lucide-react`. Includes unified Master AI and Follow-Up switch synchronization via Redis-backed settings API.
* **Telemetry Guard:** NVIDIA `nvidia-smi` parsers must verify returncode 0 and assert 7 CSV parts before unpacking.

---

## 2. Infrastructure & Deployment
* **Environments:** Staging (`docker-compose.staging.yml`) & Production (`docker-compose.production.yml`).
* **Networking:** Tailscale encrypted private mesh network (zero open public inbound ports).
* **Test Gate:** All deployments require 100% pass rate on 98 unit tests (`tests/test_*.py`) and 7 conversational backtests (`scripts/run_backtest.py`).

For full details, milestone evolution, and architectural rationale, refer to [`Tech Stack & Infrastructure.md`](file:///Users/nick/Work/HOME%20IHC/Home-IHC/Architecture/Tech%20Stack%20&%20Infrastructure.md).

# Changelog

All notable changes to the Home IHC Real Estate WhatsApp AI CRM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - Milestone 2 (v1.1.0-dev)

### Added
- **Clean Code & Object-Oriented Reporting Architecture (`app/services/reporting.py`)**:
  - Encapsulated low-level binary OpenXML and openpyxl packaging into a single `OpenXmlSpreadsheetBuilder` class with pure standard-library fallback.
  - Implemented Template Method pattern across `BaseExcelReportGenerator`, `BuyerReportGenerator`, and `OwnerReportGenerator`, eliminating 100% of duplicated customer and property extraction loops.
  - Decomposed `AdminWhatsAppDispatcher` into focused, single-responsibility methods (`_dispatch_template_to_admin`, `_archive_report_in_chatwoot`), adhering to Uncle Bob's Stepdown rule.
  - Maintained 100% backward-compatible procedural facades (`export_buyer_database_xlsx`, `export_owner_database_xlsx`, `generate_weekly_database_reports`), verifying all 115 unit and regression tests pass cleanly.
- **Modern Timezone-Aware UTC Timestamping (`main.py`)**: Replaced deprecated `datetime.datetime.utcnow()` with `datetime.datetime.now(datetime.timezone.utc)` during startup lead synchronization.
- **Multimodal Document Parsing & Ingestion (`DocumentParser` & `DocumentExtractor`)**:
  - Inbound media attachment handling for customer-submitted property documents, land titles, site photos, and raster drawings.
  - CAD Blueprint downscaling budget limiting rendering to max 3 sheets, JPEG format (<500KB/sheet), and sub-5s latency.
  - High-fidelity extraction of legal land particulars (`Pelan Bangunan`, Mukim, Lot, District, State, Acreage, Tenure, Owner, Architect).
  - ActiveStorage Range byte-proxy streaming (`GET /api/v1/documents/proxy`) enabling inline document rendering in Chatwoot.
- **Conversation 71 Mei Lin Anti-Looping Handover Guard**:
  - Two-turn disambiguation protocol for unidentified property listings or advertisement inquiries without explicit database matches.
  - Turn 1 requests listing screenshot/link; Turn 2+ triggers defensive handover to senior agent Ah Tuck (`+6012-9663589` / `tuck@homeihc.com`).
  - Chatwoot simultaneous typing race condition lock preventing AI responses while staff agents are actively drafting replies.
- **Dual-Track Conversational State Machine**:
  - Multi-intent memory preservation separating Seller Intake track (`seller_track`) from Buyer Search track (`buyer_track`) without context wipeout during mid-conversation pivots.
- **Staging Test Number Isolation**:
  - Lead nurturing daemon in staging environments strictly filtered to verified test phone numbers to prevent accidental customer dispatches.
- **Meta WhatsApp Template Multi-Language Fallback**:
  - Auto-retries templates with alternative language codes (`en` vs `en_US`), resolving Meta API error `132001`.
- **Property Dashboard Enhancements**:
  - Full-width dynamic screen layout, private viewing attachment previews, and admin number auto-saving.

- **Tag-Based RBAC Agent Specialization & Dispatch Engine**:
  - Replaces legacy Two-Number routing logic with multi-tag specialization scoring across `assigned_locations` and `assigned_property_types`.
  - Supports tie resolution with shared-case notices and zero-hit fallback to general inquiry line.
- **Multilingual Handover Promise Detection & Instant Dispatch**:
  - Added `is_handover_promised` regex engine detecting assistant promises of senior specialist follow-up across English, Chinese, and Bahasa Melayu.
  - Removed artificial turn-counter constraints (`assistant_msg_count >= 1`), enabling immediate human handover upon first-turn request, viewing booking, or senior specialist mention.
- **Unified Master AI & Automated Follow-Up Dashboard Switches**:
  - Added `/settings/followup-status` GET/POST endpoints with real-time toggle persistence across Redis and Celery daemon execution.
  - Added high-visibility Follow-Up ON/OFF pill button in dashboard header alongside Master AI switch with real-time 30s polling synchronization.
  - Immediate toggle dispatch on Nurturing Config checkbox avoiding unpersisted state loss.
  - Resilient Redis failover with in-memory caching preventing 500 errors on Redis disconnection.

- **Agent/Broker Co-Broking Routing & Handover (CR-007)**:
  - Added dedicated `agent_track` in dual-track state machine (`agent_logic.py`) to manage inquiries classified as `agent_inquiry` / `agent`.
  - Configured `dispatch_hot_lead_handover` (`tasks.py`) to route co-broke agent/broker inquiries directly to Irene Leong Main Number (`+601165144931`) with customer vCard contact card dispatch, in accordance with `Work Flow – AI Customer Services (Agent or Broker) FINAL.txt`.
- **Obsidian Vault Topology Migration & Workspace Integration**:
  - Migrated signed SOW contracts, 14 customer workflow specifications, and research notes to companion Obsidian vault (`Home-IHC/Requirements/` and `Home-IHC/Architecture/`).
  - Purged 19 duplicate non-code document files (~12MB) and legacy `.planning/` notes from `Whatsapp AI` repository.
  - Formally linked repositories via `home-ihc.code-workspace`.

- **Bidirectional Webhook Inbox Isolation (INCIDENT-20261012-DOUBLE-REPLY)**: Enforced strict bidirectional environment filtering in `backend/app/api/webhooks.py`, dropping staging test inbox (Inbox 4) events when running in production to eliminate dual-worker processing and double replies.
- **Production Outgoing Message Guard (INCIDENT-20261012-DOUBLE-REPLY)**: Added `[PRODUCTION SAFETY]` guard in `backend/app/services/chatwoot.py:send_message` preventing public message transmissions to staging inboxes from production instances.
- **UTC Timestamp Generation Syntax (`tasks.py`)**: Replaced bare `datetime.utcnow()` with `datetime.datetime.now(datetime.timezone.utc)` at customer last interaction update, eliminating `AttributeError`.
- **Mobile Document Proxy Content-Type Resolution (CR-005)**: Restored missing `content_type` variable extraction from upstream response headers in `proxy_document_inline` (`backend/app/api/documents.py`), eliminating 502 Bad Gateway regression and bringing unit test suite back to 100% pass rate.
- **Workspace Topology & Concurrency Compliance (CR-006)**: Purged untracked physical `staging/` and `production/` directories to enforce Git-native branch isolation, established `docs/adr/0001-workspace-topology-and-monorepo-structure.md`, initialized `Sessions/Active-Sessions/` concurrency lock registry, and mapped `Requirements/TRACEABILITY_MATRIX.md`.
- **Handover Suppression Bug**: Fixed issue where state machine failed to trigger human handover when assistant replies promised a senior agent would reach out.
- **Dashboard Switch Desynchronization**: Resolved issue where Master AI and Follow-Up switches failed to reflect live state or persist across page refreshes.
- **Reporting Generator Attribute Error**: Resolved missing attribute access during scheduled Excel database compilation.
- **Settings Router Type Annotations**: Added missing `Optional` typing import in settings router.
- **Webhook Timestamp Resolution**: Defensive timestamp parser preventing `UnboundLocalError` on malformed webhook payloads.

---

## [1.0.0] - 2026-09-24

### Added
- **Dynamic Sparse Token Architecture**: Response-first JSON schema in LLM generation, omitting static `null` and `false` keys, reducing token overhead by ~165 tokens per conversational turn and preventing vLLM 2048 token context exhaustion.
- **Viewing Acknowledgement Engine (`ViewingAcknowledgementEngine`)**:
  - Full 22-field document parity for Customer Property Viewing Acknowledgement forms (`.docx` & `.pdf`).
  - 16pt bold checkboxes for high visual prominence.
  - Dynamic record-based form numbering (`0190`, `0191`, `...`).
  - OpenXML table border stabilization preventing headless LibreOffice conversion border loss.
  - Borderless 2-column signature blocks aligned via explicit 3.5" tab stops.
  - Multi-line prevention for honorific titles ("MRS") and nested remarks table columns.
  - Document checklist flush left-alignment in Table 2.
- **Consultative Off-Market Protocol & Category Partitioning**: Enforced residential vs commercial/shoplot category partitioning in `search_properties`. Irene smoothly offers off-market sourcing when 0 direct residential listings match.
- **Conversation Transcript Engine (`ConversationTranscriptEngine`)**:
  - Multi-page vector PDF generation using PyMuPDF (`fitz`).
  - Full CJK font integration supporting multilingual dialogues.
  - In-conversation Chatwoot slash commands `/transcript` and `/transcript send`.
- **Automated Business Reporting (`ReportingEngine`)**:
  - OpenXML binary `.xlsx` generation with `zipfile` fallback.
  - Scheduled Celery Beat daemon generating and delivering weekly `Buyer Database.xlsx` and `Owner Database.xlsx` every Monday at 09:00 MYT.
- **Lead Qualification & Cadence Tracking (`LeadNurturingManager`)**:
  - Automatic lead qualification (Hot: 18h-72h, Warm: 3-7d, Cold: 7-14d).
  - Strict compliance with Meta WhatsApp 24-Hour Policy Window.
- **Replayable Conversational Backtesting Suite**: Full test harness covering Buyer, Seller, Tenant, Valuer, Agent/Co-Broke, and Policy Guard scenarios.
- **Automated CI/CD Quality Gates**: 81 unit & regression tests and conversational backtest gate integrated into GitHub Actions deployment workflows.
- **React Property Dashboard**: Vite + React 19 web dashboard with RBAC and lead inspection modal.

### Fixed
- **Message Truncation & Literal `\n\n` Escapes**: Regex fallback parser in `agent_logic.py` now unescapes newline and quote escape sequences.
- **Greeting Repetition Loop**: Multi-point anti-repetition guard preventing Irene Leong from repeating full intro mid-conversation.
- **Chatwoot Session Leaks**: Added `/reset` slash command and CLI utility executing deep session purge across Redis and database state.
- **Cross-Category Matching**: Prevented residential Semi-D inquiries from returning commercial shoplots.
- **Document Formatting Defects**: Resolved 11 specific document layout and data hallucination defects (Items a-k).

### Removed
- Deprecated legacy prototyping workflow JSONs and obsolete expect deployment scripts.

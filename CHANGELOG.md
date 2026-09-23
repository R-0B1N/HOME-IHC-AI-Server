# Changelog

All notable changes to the Home IHC Real Estate WhatsApp AI CRM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Deprecated legacy n8n JSON workflows and obsolete expect deployment scripts.

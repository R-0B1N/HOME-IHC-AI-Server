# Memory Bank: Home IHC Real Estate WhatsApp AI CRM

**Repository:** `https://github.com/R-0B1N/HOME-IHC-AI-Server`  
**Brand & Domain:** Home IHC Sdn. Bhd. ([BentongLand.com.my](https://bentongland.com.my/))  
**Key Contact & Agency Representative:** Irene Leong (+6011-65144931, REN / Agent)  
**Primary Tech Stack:** Python 3.11, FastAPI, Celery, Redis, PostgreSQL (pgvector), Docker Compose, Chatwoot, PyMuPDF (fitz), python-docx.

---

## 1. Architectural Principles & Patterns

### 1.1 Object-Oriented Programming (OOP) Domain Services
All core business capabilities are encapsulated into clean, testable classes while retaining backward-compatible functional entry points:
- **`ViewingAcknowledgementEngine` (`app.services.acknowledgement`):**
  - Handles 22-field Customer Property Viewing Acknowledgement forms (`.docx` & `.pdf`).
  - Implements `stabilize_borders()` injecting explicit `<w:tblBorders>` into OpenXML table properties to prevent headless LibreOffice/QuickLook border stripping.
- **`ConversationTranscriptEngine` (`app.services.transcript`):**
  - Multi-page vector PDF generator using PyMuPDF (`fitz`).
  - Supports CJK characters, sender bubble geometry, dynamic pagination, and WhatsApp document dispatch.
- **`BaseExcelReportGenerator`, `BuyerReportGenerator`, `OwnerReportGenerator` (`app.services.reporting`):**
  - OOP reporting engine generating valid OpenXML `.xlsx` binary archives with standard library `zipfile` fallback.
  - Automated weekly cron generates `Buyer Database.xlsx` and `Owner Database.xlsx`.
- **`LeadNurturingManager` (`app.services.lead_nurturing`):**
  - Evaluates lead qualification cadences (Hot: 18h–72h, Warm: 3–7d, Cold: 7–14d).
  - Enforces Meta WhatsApp 24-hour Customer Care Policy window (direct message $\le 24$h; internal Chatwoot private note $> 24$h).
- **`ConversationalBacktestHarness` (`tests.backtest.engine` & `tests.backtest.scenarios`):**
  - Replayable scenario matrix covering Buyer, Seller, Tenant, Valuer, Agent/Co-Broke, Policy Guard, and Document Parity.

### 1.2 Meta WhatsApp 24-Hour Policy Window
- Direct free-form WhatsApp messages must never be sent to a user if their last inbound message was $> 24$ hours ago.
- Violations risk Meta WhatsApp Cloud API account suspension.
- If $t > 24$h, the system posts an internal private note in Chatwoot instructing human staff to call or dispatch an approved utility template.

### 1.3 Database & Vector Search
- Schema uses `pgvector` with 5-aspect embeddings (`embedding_location`, `embedding_specs`, `embedding_features`, `embedding_suitability`, `embedding_overview`).
- Uses in-DB cosine distance operator (`<=>`) via SQLAlchemy `func.cosine_distance()`.

---

## 2. Infrastructure & Operations

### 2.1 Celery Beat Services
- Both `docker-compose.staging.yml` and `docker-compose.production.yml` run dedicated `beat_staging` and `beat_production` containers alongside `worker`.
- Schedules:
  - `run-lead-nurturing-daemon-hourly`: Runs every hour (`crontab(minute=0)`).
  - `generate-weekly-reports-monday`: Runs every Monday at 09:00 MYT (`crontab(hour=1, minute=0, day_of_week=1)`).

### 2.2 CI/CD Quality Gates (`.github/workflows/deploy-staging.yml`)
- Automated test gates execute before any code is copied or deployed to staging:
  1. `python -m unittest tests/test_*.py`
  2. `python scripts/run_backtest.py`
- Zero deployment takes place if any test fails.

### 2.3 Chatwoot In-Conversation Agent Commands
Staff can trigger automated workflows directly by writing private notes in Chatwoot:
- `/acknowledgement`: Generates and posts the Customer Property Viewing Acknowledgement form internally.
- `/acknowledgement send`: Generates and dispatches the document directly to the customer's WhatsApp chat.
- `/transcript`: Generates and posts the complete multi-page PDF transcript internally.
- `/transcript send`: Generates and dispatches the transcript PDF directly to the customer on WhatsApp.
- `/reset`: Clears the Redis session state and resets `bypass_ai` to `False` for the current conversation, restarting the conversation flow cleanly.

CLI Reset Utility:
```bash
# Reset specific customer session & AI bypass flag
python scripts/reset_customer_session.py --phone +60123456789

# Reset all active sessions and AI flags across database
python scripts/reset_customer_session.py --all
```

---

## 3. Test Verification Commands
Always execute from `backend/`:
```bash
# Unit & regression tests (54 tests)
cd backend && ../venv/bin/python -m unittest tests/test_*.py

# Replayable backtesting suite
cd backend && ../venv/bin/python scripts/run_backtest.py
```

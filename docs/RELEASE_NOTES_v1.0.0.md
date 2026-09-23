# Release Notes — Version 1.0.0

**Release Tag:** `v1.0.0`  
**Date:** 2026-09-24  
**Target Environments:** Staging (`whatsapp-ai-staging`) & Production (`whatsapp-ai-prod`)  
**Pipeline Status:** ✅ 81/81 Backend Tests Passed | ✅ 7/7 Conversational Backtests Passed  

---

## Overview

Version 1.0.0 marks the production deployment milestone for the **Home IHC Real Estate WhatsApp AI CRM**. This release transitions the architecture from legacy prototyping scripts to a production-grade, object-oriented microservices platform running FastAPI, Celery, Redis, PostgreSQL (pgvector), and dedicated on-premise AI inference.

---

## Highlights & Major Capabilities

### 1. High-Efficiency Conversational AI Engine
- **Response-First Sparse JSON Architecture:** Inverted LLM JSON output to deliver `"response"` first, guaranteeing complete conversational replies without truncation under strict token limits.
- **Dynamic Sparse Schema:** Omits static `null` and `false` keys, reducing per-turn JSON metadata overhead from ~180 tokens to ~15 tokens.
- **Literal Escape Sequence Decoding:** Fallback regex parser unescapes `\n`, `\"`, and `\\`, preventing escaped newlines from displaying as literal text in WhatsApp client bubbles.
- **Anti-Repetition Guard:** Multi-checkpoint protection prevents Irene Leong from repeating her introductory persona in ongoing dialogues.
- **Category Partitioning:** Prevents cross-category property mismatches (e.g. residential inquiries matching commercial shoplots).
- **Off-Market Sourcing Protocol:** Consultative protocol deployed when zero direct residential inventory matches client criteria.

### 2. Viewing Acknowledgement Parity (Defects a–k Fixed)
- Dynamic incremental document ID numbering (`No: 0190`, `0191`, `...`) linked to database records.
- 16pt bold checkboxes for visual prominence.
- LibreOffice border stabilization preserving table borders during headless PDF compilation.
- Right-aligned header Form No and Date tab stops at 6.5".
- Zero hallucination defaults: individual inquiries remain completely clean of corporate placeholders.
- 2-column signature table with aligned 3.5" tab stops on Page 1.
- Flush left-alignment for document checklist items in Table 2.
- Single-line formatting for remarks columns with `<w:noWrap/>`.
- Purged accidental stray date on Page 2.

### 3. Asynchronous Enterprise Microservices
- **FastAPI Webhook Service:** Validates Chatwoot timestamped HMAC signatures and offloads tasks to Redis in <10ms.
- **Celery Worker Pool:** Multi-threaded worker handling background document rendering, LLM inference, and outbound WhatsApp messaging.
- **Celery Beat Schedulers:**
  - Hourly lead nurturing daemon enforcing Meta WhatsApp 24-Hour Policy Window.
  - Weekly Monday 09:00 MYT automated report generation for `Buyer Database.xlsx` and `Owner Database.xlsx`.
- **Chatwoot Slash Commands:**
  - `/acknowledgement [send]`
  - `/transcript [send]`
  - `/reset` (deep session purge across Redis & DB)

### 4. React Property Dashboard
- Vite + React 19 administrative portal with RBAC (Admin, Agent, Viewer).
- Lead inspection modal with live qualification scoring.
- Staging test inbox isolation and environment-aware status monitoring.

### 5. Automated CI/CD Quality Gates
- Every deployment to staging and production requires 100% pass rate on:
  - 81 Unit and Regression Tests (`tests/test_*.py`).
  - Conversational Backtest Suite (`scripts/run_backtest.py`).
- Deployed via encrypted Tailscale mesh network with zero open inbound ports.

---

## Upgrade & Deployment Instructions

### Production Deployment Checklist
1. Merge `develop` into `main`.
2. Create annotated git tag `v1.0.0`.
3. Push `main` and `v1.0.0` to `origin`.
4. GitHub Actions runner connects via Tailscale, transfers updated files via SCP, and deploys containers via `docker compose -f docker-compose.production.yml up -d --build --remove-orphans`.
5. Post-deployment telemetry inspects container health and startup logs.

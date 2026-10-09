# ADR 0001: Workspace Topology and Monorepo Architecture

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** Engineering Team & Lead Architect
- **Technical Context:** Compliance with `@user_global` Directive 3 (Git-Native Workspace Topologies)

---

## 1. Context & Problem Statement
`@user_global` Directive 3 specifies:
- Staging and production are Git branches (`develop`, `staging`, `main`), never physical directories.
- Software repos: `.github/workflows/`, `src/`, `tests/`, `docs/adr/`, `scripts/`, `changelogs/`.
- Obsidian vaults: `Day N/`, `Requirements/`, `Projects/`, `Architecture/`, `Releases/`, `Templates/`, `Sessions/`.
- Data pipelines: `data/input/`, `data/output/`, `models/`, `pipelines/`, `notebooks/`.

In this repository:
1. Two untracked empty physical directories (`staging/` and `production/`) were present at the root from legacy setup.
2. The core services are architected as a two-tier monorepo:
   - `backend/`: FastAPI application (`backend/app/`), tests (`backend/tests/`), scripts (`backend/scripts/`), and Celery workers.
   - `property-dashboard/`: React 19 + Vite dashboard application (`property-dashboard/src/`).
3. Deployments rely on Docker Compose (`docker-compose.staging.yml`, `docker-compose.production.yml`) and 9 GitHub Actions workflows (`.github/workflows/deploy-staging.yml`, `deploy-production.yml`), all of which have hardcoded execution contexts, Docker build contexts, and test gates targeting `./backend`.

## 2. Decision
1. **Purge Physical Staging/Production Directories:**
   - Remove physical empty `staging/` and `production/` folders immediately.
   - Strictly enforce Git branches (`develop`, `staging`, `main`) for environmental promotion.
2. **Preserve Service Topologies (`backend/` and `property-dashboard/`):**
   - Retain `backend/` and `property-dashboard/` rather than flattening into a single root `src/`.
   - Reason: Flattening into root `src/` would break Docker build contexts, server SSH deployment paths (`~/whatsapp-ai-staging`, `~/whatsapp-ai-prod`), and GitHub Actions test gates without adding architectural benefit.
3. **Establish Missing Governance Directories:**
   - Create `docs/adr/` for Architecture Decision Records.
   - Create `Requirements/` for strict requirement traceability (linking SOWs, CRs, and Persona workflows).
   - Create `Sessions/Active-Sessions/` for multi-agent concurrency and file scope locking.
   - Maintain `CHANGELOG.md` at root adhering to Keep a Changelog / SemVer.

## 3. Consequences
- Zero breaking changes to Docker containers, CI/CD, or deployment scripts.
- Full compliance with Git-native environmental branching.
- Multi-agent collision protection enabled via session registry.

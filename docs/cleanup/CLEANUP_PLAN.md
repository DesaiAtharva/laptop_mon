# Application Lightness and Repository Cleanup Plan (C1)

> **Rulebook Reference:** `AGENTS.md` Lightness Rules, Workflow Rules, and Definition of Done  
> **Playbook Reference:** Prompt C1: Remove unnecessary files and make the application light  
> **Status:** Execution in Progress  
> **Date:** October 2026

---

## 1. Inventory & Categorization

Every file in the repository has been inventoried and assigned to one of three categories:

### 1.1 Necessary to Run (Production Application Assets)
These files are strictly required for the backend services, desktop agent, and frontend dashboard to run in production:
- **Backend Core & Apps (`backend/`):**
  - Django application configuration: `backend/config/` (`settings/`, `urls.py`, `wsgi.py`, `asgi.py`, `celery.py`, `manage.py`).
  - Modular monolith business domains:
    - `backend/apps/accounts/` (users, authentication, memberships)
    - `backend/apps/tenancy/` (tenants, work policies, isolation)
    - `backend/apps/devices/` (registration, credentials, heartbeat, enrollment)
    - `backend/apps/policies/` (frequency, retention, redaction, schedules)
    - `backend/apps/ingestion/` (idempotent batch ingest, spooling, deduplication)
    - `backend/apps/analytics/` (aggregates, productivity metrics, timelines)
    - `backend/apps/screenshots/` (capture storage, presigned URLs, redaction)
    - `backend/apps/audit/` (tamper-evident audit logs)
    - `backend/apps/billing/` (subscriptions, seat limits, webhooks)
    - `backend/apps/releases/` (version manifest, agent updates, channel rollout)
    - `backend/apps/support_access/` (time-bounded support elevation, token authorization)
    - `backend/apps/rbac/` (role-based access control, permissions)
    - `backend/apps/common/` (middleware, base models, responses)
  - Database schema migrations: all 13 migration files across apps (*never deleted or squashed*).
  - Production dependency manifest: `backend/requirements.txt`.
  - Multi-stage container definition: `backend/Dockerfile` (non-root `appuser`, slim Python 3.12).
- **Desktop Agent Core & OS Adapters (`agent/`):**
  - Core engine: `agent/core/` (scheduler, spooler, uploader, config, local storage, crypto).
  - OS Adapters: `agent/adapters/` (`base.py`, `windows/`, `macos/`, `linux/`).
  - Packaging & Native Installers: `agent/packaging/`, `agent/installer/`.
  - Service manifests: `agent/packaging/systemd/`, `agent/packaging/launchd/`.
  - Agent runtime dependency manifest: `agent/requirements.txt`.
- **Frontend Dashboard (`frontend/`):**
  - React 18 + TypeScript application source: `frontend/src/` (`components/`, `pages/`, `services/`, `types/`, `App.tsx`, `main.tsx`).
  - Configuration: `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `frontend/index.html`.
  - Multi-stage container definition: `frontend/Dockerfile` (Node 20 build -> Nginx 1.25 alpine).
- **Deployment & Infrastructure (`deploy/`):**
  - Multi-container orchestration: `deploy/docker-compose.dev.yml`, `deploy/docker-compose.prod.yml`.
  - Reverse proxy configuration: `deploy/nginx/nginx.conf`.
- **Operational & Disaster Recovery Scripts (`scripts/`):**
  - `scripts/dr/restore_backup.sh`, `scripts/dr/simulate_failover.sh`.
  - `scripts/check_migrations.py`.

### 1.2 Necessary to Maintain (Development, Testing & Compliance)
These files are strictly preserved to maintain code quality, auditability, and specification traceability:
- **Test Suites (`tests/`):**
  - 20 test modules containing all 332 tests covering unit, integration, browser E2E, load, footprint, migrations, and edge cases E01–E100.
  - Scriptable fake adapter: `agent/adapters/fake/`.
- **Documentation & Audit Evidence (`docs/`):**
  - Playbook specification: `docs/spec/SPEC.md`.
  - Architectural Decision Records: `docs/adr/ADR-001` through `docs/adr/ADR-006` and `docs/adr/agent-dependencies.md`.
  - Operational runbooks: `docs/runbooks/` (`RUNBOOK_INCIDENT_RESPONSE.md`, `RUNBOOK_BACKUP_RESTORE.md`, `RUNBOOK_KEY_ROTATION.md`).
  - Known limitations: `docs/LIMITATIONS.md`.
  - Release readiness certification: `RELEASE_READINESS.md`.
  - Verification & test evidence: `docs/test-evidence/` (`T1.md` through `T8.md`, `edge-cases.md`, and test screenshots).
  - Performance baselines and capacity models: `docs/perf/BASELINE.md`, `docs/perf/CAPACITY.md`.
  - Implementation plans: `docs/plans/` (`P0.md` through `P12.md`, `T1.md` through `T8.md`, `C1.md`).
- **Traceability Matrix & CI:**
  - Single source of truth: `TRACEABILITY.md`.
  - Traceability enforcement tooling: `scripts/check_traceability.py`.
  - Continuous integration workflows: `.github/workflows/ci.yml`.
  - Rulebooks & licensing: `AGENTS.md`, `LICENSE`, `README.md`, `.gitignore`.

### 1.3 Deletion & Optimization Candidates (Removed in C1)
The following files and patterns are identified as temporary, redundant, or dead:

| File / Component | Category | Size | Reason for Deletion / Optimization |
|---|---|---|---|
| `.coverage` | Temporary file | 340 KB | Local test runner coverage SQLite database; generated artifact. |
| `backend/dev_db.sqlite3` | Temporary file | 0 KB | Empty local development database leftover; gitignored and non-essential. |
| `dist/` | Build artifact | ~0.27 MB | Packaging build artifact generated during test packaging; ephemeral output. |
| `agent/adapters/fake/fake_adapter.py` | Dead imports | N/A | Unused imports `PowerEvent`, `SessionEvent` detected by `vulture`. |
| `agent/adapters/windows/win32_api.py` | Unused variables | N/A | Unused monitor callback parameters `hdc_monitor, lprc_monitor, dw_data` prefixed with `_`. |
| `backend/apps/billing/serializers.py` | Dead import | N/A | Unused import `UsageRecord` detected by `vulture`. |
| `backend/apps/billing/services.py` | Dead import | N/A | Unused import `UsageRecord` detected by `vulture`. |
| `backend/apps/screenshots/storage.py` | Dead import | N/A | Unused import `base64` detected by `vulture`. |
| `deploy/.gitkeep` | Redundant file | 0 KB | Directory already populated with configuration and docker-compose files. |

---

## 2. Tooling Analysis Results

### 2.1 Python Dead Code Audit (`vulture`)
- Scanned all Python modules in `backend/` and `agent/` with confidence >= 90%:
  - `agent/adapters/fake/fake_adapter.py:12`: Unused imports `PowerEvent`, `SessionEvent` -> **Removed**.
  - `agent/adapters/windows/win32_api.py:196`: Unused Win32 callback arguments -> **Prefixed with `_`**.
  - `backend/apps/billing/serializers.py:4`: Unused import `UsageRecord` -> **Removed**.
  - `backend/apps/billing/services.py:17`: Unused import `UsageRecord` -> **Removed**.
  - `backend/apps/screenshots/storage.py:4`: Unused import `base64` -> **Removed**.

### 2.2 Python Dependency Audit (`deptry` & ADR-002)
- Scanned dependencies against import graphs:
  - Agent third-party dependencies: strictly confined to `cryptography` (5.8 MB), `Pillow` (6.5 MB), and `pywin32` (4.2 MB on Windows).
  - Prohibited heavy dependencies: verified **zero** occurrences of `pandas`, `numpy`, `PyQt6`, `Electron`, or heavy ORMs in `agent/`.
  - Backend dependencies: `Django`, `djangorestframework`, `boto3`, `Pillow`, `redis`, `celery`, `gunicorn`, `mysqlclient`. All directly imported and required.

### 2.3 TypeScript & Frontend Dependency Audit (`depcheck` & Vite)
- Executed `npx depcheck` on `frontend/`:
  - Result: **No depcheck issue**.
  - Dependencies: `react`, `react-dom` (only 2 runtime dependencies).
  - DevDependencies: `@types/react`, `@types/react-dom`, `@vitejs/plugin-react`, `typescript`, `vite`.
  - Zero unused dependencies or ghost dependencies found.
- Minified Production Bundle (`npm run build`):
  - `dist/index.html`: **0.94 kB** (gzip: 0.51 kB)
  - `dist/assets/index.css`: **9.25 kB** (gzip: 2.50 kB)
  - `dist/assets/index.js`: **187.34 kB** (gzip: 55.86 kB)
  - Total bundle size: **~197.53 kB** (gzip: **~58.87 kB**), well below typical web application limits.

### 2.4 Static Asset Audit
- Scanned repository for unreferenced raster/vector media assets:
  - Frontend uses inline SVG and CSS icons; zero unreferenced static images in `frontend/`.
  - The 8 image files in `docs/test-evidence/screenshots/t3/` are verified active attachments for UI test audit evidence (§14.2, T3).

---

## 3. Shipped Artifacts Optimization

1. **Desktop Agent Package:**
   - Packaged via `agent/packaging/build_windows.py`.
   - Excludes tests, pytest caches, python caches, git metadata, and debug symbols.
   - Output ZIP size: **~69 KB** (uncompressed staged size: **0.19 MB**).
   - Target budget: < 60 MB (**PASS**).
2. **Backend Container Image (`backend/Dockerfile`):**
   - Multi-stage build based on `python:3.12-slim-bookworm`.
   - Stage 1 compiles wheel dependencies; Stage 2 copies only wheels and backend source.
   - Runs as non-root user `appuser` (UID 10001).
   - Zero test suites, scratch files, or dev tools included in runtime layer.
3. **Frontend Container Image (`frontend/Dockerfile`):**
   - Multi-stage build based on `node:20-alpine` (builder) and `nginx:1.25-alpine` (runtime).
   - Serves minified static bundle via Nginx as non-root user.
   - Estimated compressed image size: < 25 MB.

---

## 4. Verification & Footprint Check

- Re-run T6 footprint test suite: `tests/test_t6_perf_load_footprint.py`.
- Re-run full 332-test regression suite.
- Re-run `python scripts/check_traceability.py --final`.
- Re-run `python scripts/check_migrations.py`.

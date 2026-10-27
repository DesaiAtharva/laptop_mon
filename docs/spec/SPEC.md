# Laptop Productivity Monitoring SaaS — Specification

> **Version:** 1.0
> **Date:** 27 October 2026
> **Status:** Authoritative source of truth for all build prompts.

---

## 1. Goals, Scope and Non-Goals

### 1.1 Goals

- Provide employers with transparent, policy-driven, auditable visibility into how company-issued laptops are used during work hours.
- Capture foreground application usage, session activity (active/idle/locked), and periodic screenshots.
- Deliver actionable productivity metrics and reports to managers and administrators.
- Operate as a lightweight agent that respects OS permissions and user privacy policies.

### 1.2 Scope

- Windows (primary), macOS, and Linux desktop agents.
- Multi-tenant SaaS backend (Django + MySQL).
- React web dashboard for all roles.
- Billing, invitations, tenant lifecycle management.
- Full offline support with durable local queuing and automatic sync.

### 1.3 Non-Goals

- Keylogging, password capture, private-message scraping.
- Hidden or covert monitoring.
- Arbitrary remote command execution.
- Antivirus or EDR evasion.
- Real-time streaming (data is batched and synced).
- Microservices, Kafka, or Kubernetes infrastructure.

---

## 2. Roles and Product Behavior

### 2.1 Roles

| Role | Description |
|---|---|
| **Employee** | Monitored user. Can view own data, monitoring state, effective policy, and submit disputes. Must acknowledge the first-run privacy notice before any capture begins. |
| **Manager** | Views reports and summaries for assigned teams only. |
| **Organization Admin** | Full control over tenant: members, devices, policies, billing, exports, legal requests. |
| **Auditor** | Read-only access to audit logs and reports. No screenshot access by default. |
| **Platform Support** | Just-in-time, approval-gated, time-bound, fully audited access. No standing access to screenshots or content. |
| **Service Identity** | Machine accounts for agent–server communication. |

### 2.2 Permission Matrix

- Screenshot access is a **separate, explicit permission**.
- Managers see **only assigned teams** — never other teams' data.
- Cross-tenant object IDs return a safe 404 or 403.
- Multi-tenant users must send explicit tenant context, validated on every request.
- Tenant ID is **always** derived from authenticated membership — never from the request body.

### 2.3 First-Run Notice

The agent must display a first-run notice explaining what is collected and **require acknowledgement before any capture starts** (also required by §11.3 Privacy).

---

## 3. Logical and Deployment Architecture

### 3.1 Logical Architecture

```
[Desktop Agent] ──HTTPS──► [Django API]
                                │
                    ┌───────────┼───────────┐
                 [MySQL]     [Redis]    [MinIO/S3]
                                │
                           [Celery Workers]
                                │
                           [React Frontend]
```

### 3.2 Security Architecture

- TLS on all transport. Verification never disabled.
- Per-device credentials (prefer public-key authentication).
- Tenant-scoped querysets, cache keys, and object storage keys.
- Audit log: append-only at application level, restricted modification and export.
- Presigned URLs: short-lived, scoped to one object, never logged.

### 3.3 Deployment

- Separate API, ingestion, worker, and scheduler processes from one codebase.
- Private networking between components.
- Minimal infrastructure as code, staged rollout, rollback capability.

---

## 4. Desktop Agent Architecture

### 4.1 Agent Structure

```
agent/
  core/               Shared core — no OS imports
    lifecycle.py      Startup, shutdown, crash loop breaker
    journal.py        SQLite event journal
    spool.py          Encrypted upload spool
    crypto.py         Authenticated encryption, key management
    sync.py           Upload worker with retry/backoff
    policy.py         Policy manager and cache
    scheduler.py      Event-driven scheduler
    privacy_filter.py Exclusion rules, redaction
    diagnostics.py    Logging, support bundle, heartbeat
    status.py         Monitoring state tracker
  adapters/
    base.py           Adapter Protocol with capability flags
    windows/          Win32 event hooks, idle, capture
    macos/            NSWorkspace, permissions, capture
    linux/            X11/Wayland, D-Bus, capture
    fake/             Scriptable deterministic adapter for tests
```

### 4.2 Per-OS Capabilities

| Capability | Windows | macOS | Linux |
|---|---|---|---|
| Foreground app events | Win32 event hook | NSWorkspace notifications | X11 props / Wayland portal |
| Idle detection | GetLastInputInfo | IOKit HID | XScreenSaver / portal |
| Lock/unlock | Session change notifications | NSWorkspace | Login manager D-Bus |
| Sleep/wake | Power notifications | NSWorkspace | logind D-Bus |
| Screen capture | GDI / DXGI | CGDisplayStream | X11 XGetImage / Wayland portal |
| Multi-monitor | EnumDisplayMonitors | NSScreen | XRandR |
| Autostart | Per-user registry run key | Launch agent plist | systemd user service |
| Key store | DPAPI / Credential Manager | Keychain | Secret Service / fallback |

### 4.3 Process Model

- One user-session agent process per logged-in user.
- Capture is separated from upload by bounded queues with defined overload behavior.
- The tray/status UI is **optional and separate** — closing it does not stop capture.
- Monitoring state must remain discoverable even when the UI is closed.

### 4.4 Updater

- Signed release manifest served by the backend (channels, staged rollout percentages, min/max version).
- Agent downloads → verifies hash and signature → stages → swaps atomically → restarts → rolls back on failure.
- Never updates during shutdown.
- Checks local schema compatibility before migrating.

---

## 5. Offline Queue, Shutdown and Recovery

### 5.1 Offline Behavior

- Agent starts offline under a valid cached policy.
- Storage limits: maximum disk use, per-file limit, minimum free-disk threshold, early warning.
- **Priority**: screenshots are dropped before the event journal when space is tight.
- Always writes explicit gap events — never silently deletes data.

### 5.2 Shutdown

- Bounded graceful shutdown: stop capture → commit → close → atomic screenshot → never wait on the network.
- Previous-run marker and unclean-shutdown detection that writes a gap event on next start.

### 5.3 Crash Recovery

- Crash-loop circuit breaker with backoff.
- Startup integrity check on SQLite journal; corrupt database is quarantined and valid records recovered.
- Orphan spool files and orphan journal rows are reconciled at startup.

---

## 6. Synchronization Protocol

### 6.1 Event Batch Upload

- Agent batches events by byte count and item count.
- Exponential backoff with jitter; respects `Retry-After`.
- On 413 (oversized): splits batch.
- On permanent 4xx: stops retrying that batch, logs as gap.
- On 401: attempts refresh or re-enroll — no infinite loop.
- On 403 (revoked): applies revocation policy, stops uploads.
- Deletes local data **only** for events reported `accepted` or `already_accepted`.

### 6.2 Screenshot Upload

Two-phase protocol:
1. `POST agent/screenshots/upload-intents` → receives scoped, expiring upload authorization.
2. Agent uploads directly to private object storage.
3. `POST agent/screenshots/complete` → server verifies object, size, checksum. Idempotent.

A periodic reconciliation job handles orphan objects and incomplete multipart uploads.

---

## 7. Data Model and MySQL Rules

### 7.1 General Rules

- InnoDB storage engine, utf8mb4 character set.
- UUID public identifiers on all tenant-owned models.
- UTC timestamps throughout.
- Explicit foreign keys and unique constraints.
- Indexes on all foreign keys and common filter columns.
- Expand-then-contract schema changes. CI fails on destructive migrations without approved marker.

### 7.2 Core Models

**Tenants**
- `id` (UUID), `name`, `status` (active/suspended/deleting), `created_at`, `updated_at`

**Users**
- `id` (UUID), `email` (unique), `name`, `mfa_enabled`, `created_at`

**Memberships**
- `id`, `tenant_id`, `user_id`, `role`, `status` (active/disabled), unique(tenant_id, user_id)

**Teams**
- `id`, `tenant_id`, `name`, unique(tenant_id, name)

**TeamMembers**
- `id`, `team_id`, `membership_id`, composite FK constraint: membership.tenant_id == team.tenant_id

**AuditLogs**
- `id`, `tenant_id`, `actor_id`, `action`, `resource_type`, `resource_id`, `metadata` (JSON), `request_id`, `created_at`
- Append-only at application level.

**Devices**
- `id` (UUID), `tenant_id`, `membership_id`, `hostname`, `os`, `status` (active/revoked), `agent_version`, `last_seen_at`, `created_at`

**AgentCredentials**
- `id`, `device_id`, `public_key` / `secret_hash`, `status`, `expires_at`, `last_used_at`

**MonitoringPolicies**
- `id`, `tenant_id`, `version` (integer), `valid_until`, `screenshot_interval_seconds`, `idle_threshold_seconds`, `retention_days`, `capture_windows` (JSON), `exclusion_rules` (JSON), `window_title_collection` (boolean), `min_agent_version`, `max_agent_version`, `effective_date`, `created_at`

**AppRules**
- `id`, `tenant_id`, `policy_id`, `app_identifier`, `classification` (productive/neutral/distracting/excluded), `version`

**WorkSessions**
- `id`, `device_id`, `tenant_id`, `started_at`, `ended_at` (nullable), `end_reason`, `session_type`

**ActivityEvents**
- `id` (UUID, from agent), `device_id`, `tenant_id`, `event_type`, `occurred_at`, `received_at`, `payload` (JSON), `batch_id`, `upload_status`

**EventBatches**
- `id`, `device_id`, `tenant_id`, `received_at`, `agent_version`, `schema_version`, `total_events`, `accepted_count`, `status`

**Screenshots**
- `id` (UUID), `device_id`, `tenant_id`, `status` (pending/uploaded/finalized/failed/deleted), `object_key`, `thumbnail_key`, `captured_at`, `width`, `height`, `file_size`, `checksum`, `policy_version`, `delete_after`, `created_at`

**AppUsageIntervals**
- `id`, `device_id`, `tenant_id`, `app_identifier`, `app_classification`, `app_classification_version`, `started_at`, `ended_at`, `duration_seconds`, `state` (active/idle/locked/asleep/unobserved/offline/unclassified/permission-denied/telemetry-gap), `calc_version`

**DailyMetrics**
- Unique grain: `(device_id, local_date, calc_version)`
- Fields: `observed_session_seconds`, `active_seconds`, `idle_seconds`, `productive_seconds`, `neutral_seconds`, `distracting_seconds`, `productive_share`, `monitoring_coverage`, `sync_lag_seconds`, `crash_free_sessions`, `data_freshness_at`

**Subscriptions, Plans, UsageRecords** — see §15.3.

---

## 8. API Design

### 8.1 Error Contracts

All API errors return:
```json
{
  "code": "machine_readable_stable_code",
  "message": "Human readable description",
  "field_errors": {},
  "correlation_id": "uuid"
}
```

HTTP status codes:
- `400` Bad request (validation)
- `401` Unauthenticated
- `403` Forbidden (authorization or revoked)
- `404` Not found (also used for cross-tenant IDOR)
- `409` Conflict (duplicate event with different payload, stale version)
- `413` Payload too large
- `422` Unprocessable entity (schema/semantic errors)
- `429` Rate limited (includes `Retry-After`)
- `503` Overloaded (includes `Retry-After`)
- `5xx` Server error

No error response may leak information about other tenants.

### 8.2 Auth Endpoints

- `POST /api/auth/oidc/callback` — OIDC sign-in with state and nonce validation
- `GET /api/me/tenants` — list tenants for the authenticated user
- `POST /api/tenants` — create tenant
- `GET /api/tenants/{id}/members` — list members (admin only)
- `POST /api/tenants/{id}/invitations` — invite user

### 8.3 Agent Endpoints

- `POST /api/agent/enroll` — token exchange, returns per-device credential
- `GET /api/agent/policy` — effective policy with version, expiry, and signature
- `POST /api/agent/heartbeat` — agent health signals
- `POST /api/agent/events/batch` — event ingestion
- `POST /api/agent/screenshots/upload-intents` — request upload authorization
- `POST /api/agent/screenshots/complete` — finalize screenshot

### 8.4 Dashboard Endpoints

- `GET /api/reports/daily` — daily metrics, paginated, role-scoped
- `GET /api/reports/timeline` — activity timeline, paginated
- `GET /api/reports/app-usage` — app usage breakdown
- `GET /api/screenshots` — screenshot metadata search (separate permission)
- `POST /api/screenshots/{id}/view-url` — request short-lived view URL
- `GET /api/audit-logs` — audit log (admin/auditor)
- `GET /api/devices` — device list
- `POST /api/devices/enrollment-tokens` — create enrollment token
- `POST /api/devices/{id}/revoke` — revoke device
- `GET /api/policies` — policy list
- `PATCH /api/policies/{id}` — update policy (optimistic locking by version)
- `POST /api/exports` — request data export

---

## 9. Timeline and Productivity Calculations

### 9.1 Timeline Reconstruction

- **Deterministic state machine** over sorted events.
- Sort order: `occurred_at` → `source_sequence` → `event_id`.
- Intervals close at each transition and are capped at session, lock, and sleep boundaries.
- No overlapping intervals per device.
- Gaps are **explicit unknowns** — never filled, never counted as active or idle.
- Sessions with no end event are closed provisionally and labeled `inferred`.
- Impossible sequences (e.g., idle-end without idle-start) are normalized, recorded as anomalies, and never produce negative durations.

### 9.2 Metrics

| Metric | Definition |
|---|---|
| Observed session time | Sum of intervals where agent was running and not in gap state |
| Active time | Time in foreground app with no idle |
| Idle time | Time where idle threshold exceeded |
| Productive/neutral/distracting time | Active time partitioned by app classification |
| Productive share | Productive / (Productive + Neutral + Distracting), denominator shown |
| Monitoring coverage | Observed session / scheduled work hours |
| Sync lag | Age of oldest unsynced event |
| Crash-free sessions | Sessions without unclean shutdown |

### 9.3 Recalculation

- Late events recalculate only the affected device and time window (with safety overlap).
- Reports show data freshness timestamp.
- App rule and idle threshold changes are versioned; changing either triggers versioned recalculation.

---

## 10. Screenshot Pipeline and Storage

### 10.1 Capture

- Screenshots compressed as JPEG or WebP.
- Resolution capped and downscaled only under policy.
- Excluded apps and password managers are skipped before capture.
- Window titles not collected unless policy explicitly enables them; redacted when collected.
- Skipped captures record only that they were skipped (not the reason or content).

### 10.2 Storage

- Never stored in MySQL — only object keys.
- Object keys are tenant-scoped and non-guessable.
- Thumbnails are asynchronous and tenant-scoped.
- All uploads treated as untrusted: strict decode, dimension and type limits, malware scan hook.
- View URLs: fresh presigned URL per request, short expiry, scoped to one object, every view audited.

### 10.3 Storage Capacity Formula

```
bytes_per_device_per_day = (
  (work_hours * 3600 / screenshot_interval_seconds)
  * avg_compressed_screenshot_bytes
)
```

Document measured values in `docs/perf/CAPACITY.md`.

---

## 11. Security, Privacy and Compliance

### 11.1 Audit Log Events

Every audit log entry records: actor, action, resource type, resource ID, timestamp, request ID.

Actions that must be logged (non-exhaustive):
- Sign-in, sign-out, MFA events
- Member invite, role change, disable
- Team creation, membership change
- Device enrollment, revocation, reassignment
- Policy create, update, version change
- Screenshot view, export
- Support access request, approval, use
- Billing events
- Tenant suspension, deletion
- Legal hold/deletion requests

### 11.2 Data Handling

- Raw accepted events are immutable.
- Retention: tenant-configurable, flagged for legal review at default values.
- Legal hold: authority check, hold applied, deletion of eligible data, outcome recorded without sensitive content.
- Legal deletion request: authority check, deletion of eligible data, outcome recorded.

### 11.3 Privacy

- First-run notice required before capture.
- Employee self-view: own monitoring state, effective policy, data collected categories, own reports, privacy notice, support route, dispute submission.
- Privacy notice template in `docs/privacy/employee-notice-template.md`.

### 11.4 Threat Model

| Threat | Mitigation |
|---|---|
| Cross-tenant data access (IDOR) | Tenant-scoped querysets on all models; 404/403 on cross-tenant IDs |
| Stolen device credential | Per-device revocation; credential rotation; abnormal usage flags |
| Replayed enrollment token | Single-use, stored hashed, replay prevention |
| Screenshot URL leak | Short-lived presigned URLs, every view audited, URL never logged |
| Malicious upload | Strict decode, type/dimension limits, malware scan hook |
| Compromised admin account | MFA required for privileged roles; session revocation; audit log |
| Tenant spoofing in agent payloads | Tenant derived from device credential, never from request body |
| Secrets in logs/crash dumps | Structured logging with redaction filters; automated scan in CI |
| Stale/cross-tenant cache | Tenant-scoped cache keys; cache invalidation on membership change |
| Support staff data access | Just-in-time grant, approval required, time-bound, fully audited |

---

## 12. Reliability, Observability and SLOs

### 12.1 Agent Health Signals (heartbeat)

- Agent version
- Queue depth (events pending upload)
- Oldest pending event age
- Permission state (per capability)
- Last successful sync timestamp
- Crash-free session indicator

### 12.2 Incident Response

Runbook location: `docs/runbooks/incident-response.md`

Categories: data loss, security breach, service outage, agent malfunction.

### 12.3 SLO Definitions

| SLO | Target |
|---|---|
| API availability | 99.9% |
| Ingestion end-to-end latency (p95) | < 30 s from agent batch send to MySQL commit |
| Dashboard report query (p95) | < 3 s |
| Screenshot view URL generation | < 1 s |
| Agent idle CPU | < 1% |
| Agent memory | < 80 MB |

---

## 13. Edge-Case Register (E01–E100)

See `docs/EDGE_CASE_ASSIGNMENT.md` for the full register with prompt and test layer assignments.

All 100 edge cases must have:
- A test named `test_E##_description`, OR
- A documented limitation in `docs/LIMITATIONS.md` plus a test proving the safe behavior.

Platform-specific cases (E56–E65, E68, E92, E95, E98) require manual test sheets in `docs/test-evidence/`.

---

## 14. Testing and Acceptance

### 14.1 Coverage Thresholds

| Module | Branch Coverage |
|---|---|
| Tenant scoping | ≥ 90% |
| Event ingestion | ≥ 90% |
| Timeline reconstruction | ≥ 90% |
| Agent journal and spool | ≥ 90% |
| Overall | ≥ 80% |

### 14.2 Acceptance Criteria (Release Gate)

- [ ] All test suites pass (T1–T7)
- [ ] `scripts/check_traceability.py --final` passes
- [ ] Every edge case E01–E100 has code and a passing test (or documented limitation + safe behavior test)
- [ ] Agent footprint within budget (≤ 20% of baseline)
- [ ] No cross-tenant data leak (T5)
- [ ] Restore drill completed with RTO/RPO evidence (T4/T8)
- [ ] RELEASE_READINESS.md produced and reviewed

### 14.3 Fault Injection Invariants

For every injected fault, all of the following must hold:
- No accepted event lost
- No duplicate contribution to any metric
- Every gap flagged as a gap
- No fabricated activity
- No plaintext uploaded
- Automatic recovery without manual steps (for recoverable faults)
- Clear reporting for unrecoverable faults

---

## 15. Deployment, Operations and DR

### 15.1 Agent Deployment

- Native signed installer for Windows (P7), macOS (P11), Linux (P12).
- Silent install arguments for IT administrators: enrollment token, autostart config.
- Uninstaller follows documented pending-data policy and never silently deletes unsynced data.

### 15.2 Backend Deployment

- Nginx reverse proxy.
- Separate processes: API, ingestion, workers, scheduler.
- Private networking between all components.
- Non-root containers with minimal attack surface.

### 15.3 Capacity and Cost

- Per-tenant quotas enforced server-side.
- Bulk inserts for event ingestion.
- Query plans reviewed for large report queries.
- Storage capacity formula in §10.3.
- Subscription plans with verified server-side seat limits.

---

## 16. Implementation Roadmap

See `BUILD_PLAYBOOK.md` Section 1 for the full prompt-by-prompt roadmap (P0–P12, T1–T8, C1).

---

## 17. Release Checklist and Open Decisions

### 17.1 Release Checklist

Each item must have a link to evidence in `docs/test-evidence/`:

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All E2E tests pass
- [ ] All 100 edge cases covered or documented
- [ ] Agent footprint measured and within budget
- [ ] Security test evidence (T5) reviewed
- [ ] Cross-tenant isolation verified
- [ ] Fault injection results reviewed (T4)
- [ ] Restore drill completed (T4/T8)
- [ ] Log redaction verified (no secrets in logs)
- [ ] Dependency scan clean (no critical CVEs)
- [ ] Secret scan clean (no secrets in repo)
- [ ] Migration check passes on empty DB and previous version DB
- [ ] `check_traceability.py --final` passes
- [ ] `RELEASE_READINESS.md` produced
- [ ] Privacy notice reviewed
- [ ] Employee notice template reviewed
- [ ] DPDP checklist reviewed by counsel

### 17.2 Open Decisions

| ID | Decision | Status |
|---|---|---|
| OD-01 | Payment provider selection | Open |
| OD-02 | macOS and Linux release timeline | Open |
| OD-03 | Screenshot malware scan provider | Open |
| OD-04 | OIDC provider(s) to support at launch | Open |
| OD-05 | Plan tiers and pricing | Open |
| OD-06 | DPDP / GDPR data residency requirements | Open |

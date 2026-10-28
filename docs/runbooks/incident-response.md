# Runbook: Incident Response Procedures

## 1. Scope & Severity Classification

This runbook defines the incident response procedures under **SPEC §12.2**.

| Severity | Definition | Target Initial Response | Resolution Target |
|---|---|---|---|
| **SEV-1 (Critical)** | System-wide outage, active data loss, confirmed security breach, or tenant isolation breach. | < 15 minutes | < 4 hours |
| **SEV-2 (Major)** | Core capability degraded (e.g. Ingestion down, Celery deadlocked, agent crash-looping). | < 30 minutes | < 8 hours |
| **SEV-3 (Minor)** | Non-blocking feature failure (e.g. Export failure, reporting latency elevated). | < 2 hours | < 24 hours |

---

## 2. Incident Response Workflows

### 2.1 Security Breach & Credential Compromise (E40, E48)
1. **Compromised Admin Account (E48):**
   - Immediately revoke active user sessions:
     ```python
     from apps.accounts.models import UserSession
     UserSession.objects.filter(user=compromised_user).update(revoked_at=timezone.now())
     ```
   - Disable user account: `user.is_active = False; user.save()`.
   - Rotate tenant API secrets and notify organization administrator.
   - Audit all actions performed by user within the compromise window via `/api/audit-logs`.
2. **Leaked Device Credential (E40):**
   - Revoke device via `POST /api/devices/{id}/revoke/`.
   - The device is immediately barred from API access; subsequent uploads return HTTP 403.
   - Issue fresh enrollment token for device re-enrollment.

### 2.2 Data Loss or Storage Degradation (E86, E87)
1. Determine boundary of missing telemetry.
2. Flag missing intervals explicitly as telemetry gaps—**never fabricate activity**.
3. If object storage is degraded, verify agent local encrypted spool retention.
4. Execute disaster recovery restore if data is unrecoverable (see `docs/runbooks/disaster-recovery.md`).

### 2.3 Agent Malfunction or Crash Loop (E10)
1. Agent circuit breaker pauses capture after 5 consecutive crashes with exponential backoff (up to 30 minutes).
2. Gather redacted diagnostics support bundle via `agent --support-bundle`.
3. Check agent version against minimum supported version policy in `backend/apps/policies/models.py`.
4. If necessary, stage automatic rollback to prior known-good version via `agent/core/updater.py`.

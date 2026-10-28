# Runbook: Disaster Recovery, Backup & Restore

## 1. Objectives & SLO Targets

This runbook defines the emergency recovery procedures, backup topologies, and restore verification protocols for the Laptop Productivity Monitoring SaaS under **SPEC §12.3, §15** and edge cases **E86, E87**.

### RTO & RPO Targets per Plan Tier
| Plan Tier | Recovery Point Objective (RPO) | Recovery Time Objective (RTO) | Backup Retention |
|---|---|---|---|
| **Starter** | ≤ 24 hours | ≤ 8 hours | 30 days |
| **Professional** | ≤ 4 hours | ≤ 4 hours | 90 days |
| **Enterprise** | ≤ 1 hour | ≤ 1 hour | 365 days (WORM storage optional) |

---

## 2. Backup Architecture & Cadence

```
                       ┌────────────────────────┐
                       │   Primary MySQL 8.0    │
                       └───────────┬────────────┘
                                   │ Hourly transaction logs & daily mysqldump
                                   ▼
                       ┌────────────────────────┐
                       │ Compressed & Encrypted │
                       │    Backup Archive      │
                       └───────────┬────────────┘
                                   │ Replicated off-site
                                   ▼
                       ┌────────────────────────┐
                       │ Secondary Storage / S3 │
                       └────────────────────────┘
```

1. **MySQL Backups:**
   - Script: `scripts/dr/backup_mysql.py`
   - Daily full logical backup via `mysqldump --single-transaction --quick`.
   - Compressed with gzip and paired with a SHA-256 manifest JSON file.
2. **Object Storage (Screenshots):**
   - Active bucket replication enabled to secondary failover region.
   - S3 object lifecycle rules apply `delete_after` per tenant policy.
3. **Consistency Verification:**
   - Executed weekly via `scripts/dr/verify_db_storage_consistency.py`.

---

## 3. Disaster Scenarios & Recovery Procedures

### Scenario 1: Database Corruption or Accidental Loss (E86)

**Trigger:** MySQL service unrecoverable, hardware failure, or corrupted data pages.

**Procedure:**
1. **Stop Application Traffic:**
   ```bash
   docker compose -f deploy/docker-compose.prod.yml stop api ingestion celery-worker
   ```
2. **Verify Backup Integrity:**
   Select the latest backup manifest:
   ```bash
   python scripts/dr/restore_mysql.py ./backups/laptop_mon_backup_latest.sql.gz --verify-only
   ```
3. **Restore Database:**
   ```bash
   python scripts/dr/restore_mysql.py ./backups/laptop_mon_backup_latest.sql.gz --db-name laptop_mon
   ```
4. **Audit DB & Storage Consistency:**
   ```bash
   python scripts/dr/verify_db_storage_consistency.py
   ```
5. **Restart Services & Validate Health:**
   ```bash
   docker compose -f deploy/docker-compose.prod.yml start api ingestion celery-worker
   curl -f https://api.laptopmon.com/health/ready
   ```

---

### Scenario 2: Regional Cloud or Infrastructure Outage (E87)

**Trigger:** Primary cloud region down or primary storage unavailable.

**Procedure:**
1. **Activate Secondary Standby Region:**
   - Update DNS (Route53/Cloudflare) CNAME records to secondary standby ingress IP.
2. **Degraded Ingestion Mode:**
   - If object storage is temporarily degraded, the agent's spool holds screenshots locally up to disk limits while continuing lightweight event journal synchronization.
   - Missing screenshots are flagged as degraded gaps until storage recovers; no fabricated data is produced.
3. **Promote Replicated MySQL Database:**
   - Point backend `MYSQL_HOST` to the secondary promoted replica.
4. **Verify Application Readiness:**
   - Verify `/health/ready` returns HTTP 200 with all dependencies reporting `healthy`.

---

## 4. Regular Restore Drill Verification

- Quarterly restore drills are performed in staging using real backup archives.
- Measured restore times and verification results must be logged in `docs/test-evidence/dr-drills.md`.

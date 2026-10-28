# Storage Capacity Planning Guide (§10.3)

> **Specification Reference:** `docs/spec/SPEC.md` §10.3, §10.1, §10.2, §15.3  
> **Playbook Reference:** Build Playbook Prompt T6  
> **Status:** Authoritative capacity model for storage sizing, infrastructure budgeting, and tenant quota planning.

---

## 1. Storage Capacity Formula (§10.3)

As formally defined in specification §10.3, the storage footprint per device per day is governed strictly by the following formula:

$$\text{bytes\_per\_device\_per\_day} = \left( \frac{\text{work\_hours} \times 3600}{\text{screenshot\_interval\_seconds}} \right) \times \text{avg\_compressed\_screenshot\_bytes}$$

Where:
- $\text{work\_hours}$: Active monitoring hours per day (typically 8.0 hours for business shift, up to 24.0 hours for continuous monitoring).
- $\text{screenshot\_interval\_seconds}$: Interval between scheduled screen captures configured in tenant `MonitoringPolicy` (e.g., 300 s / 5 min, 600 s / 10 min, 900 s / 15 min).
- $\text{avg\_compressed\_screenshot\_bytes}$: Measured size of compressed screen capture (JPEG quality 75 or WebP quality 70). Under measured desktop baseline, a standard 1080p capture compresses to **85 KB (87,040 bytes)** on average; high-complexity/dual-monitor screens average **180 KB (184,320 bytes)**.

---

## 2. Single-Device Daily & Monthly Storage Matrix

### 2.1 Standard 8-Hour Workday Shift (8.0 Hours / Day)

Assuming measured average compressed screenshot size of **85 KB**:

| Screenshot Interval | Captures / Hour | Captures / Day (8h) | Daily Storage (MB) | 30-Day Retention (MB / GB) | 90-Day Retention (GB) | 365-Day Retention (GB) |
|---|---|---|---|---|---|---|
| **5 minutes (300 s)** | 12 | 96 | **8.16 MB** | 244.8 MB (~0.24 GB) | 0.73 GB | 2.98 GB |
| **10 minutes (600 s)** | 6 | 48 | **4.08 MB** | 122.4 MB (~0.12 GB) | 0.37 GB | 1.49 GB |
| **15 minutes (900 s)** | 4 | 32 | **2.72 MB** | 81.6 MB (~0.08 GB) | 0.24 GB | 0.99 GB |

### 2.2 Continuous 24-Hour Monitoring (24.0 Hours / Day)

Assuming measured average compressed screenshot size of **85 KB**:

| Screenshot Interval | Captures / Hour | Captures / Day (24h) | Daily Storage (MB) | 30-Day Retention (GB) | 90-Day Retention (GB) | 365-Day Retention (GB) |
|---|---|---|---|---|---|---|
| **5 minutes (300 s)** | 12 | 288 | **24.48 MB** | 0.73 GB | 2.20 GB | 8.94 GB |
| **10 minutes (600 s)** | 6 | 144 | **12.24 MB** | 0.37 GB | 1.10 GB | 4.47 GB |
| **15 minutes (900 s)** | 4 | 96 | **8.16 MB** | 0.24 GB | 0.73 GB | 2.98 GB |

### 2.3 Dual-Monitor / High-Resolution Displays (180 KB avg)

For multi-monitor workstations (3840×1080 or dual 4K) running an 8-hour shift:

| Screenshot Interval | Captures / Day (8h) | Daily Storage (MB) | 30-Day Retention (GB) | 90-Day Retention (GB) | 365-Day Retention (GB) |
|---|---|---|---|---|---|
| **5 minutes (300 s)** | 96 | **17.28 MB** | 0.52 GB | 1.56 GB | 6.31 GB |
| **10 minutes (600 s)** | 48 | **8.64 MB** | 0.26 GB | 0.78 GB | 3.15 GB |
| **15 minutes (900 s)** | 32 | **5.76 MB** | 0.17 GB | 0.52 GB | 2.10 GB |

---

## 3. Fleet Scale Planning (30-Day Standard Policy Retention)

Standard SaaS tier defaults to 30-day screenshot retention (§10.2). Fleet capacity requirements for 8-hour workdays at 5-minute capture intervals (8.16 MB / device / day, 245 MB / device / month):

| Organization Fleet Size | Daily Ingestion Rate (MB / day) | Monthly Ingestion Volume (GB / month) | S3 Object Count / Month | Steady-State Storage (GB) |
|---|---|---|---|---|
| **Small (10 devices)** | 81.6 MB / day | 2.45 GB / month | 28,800 objects | **2.45 GB** |
| **Medium (100 devices)** | 816 MB / day | 24.5 GB / month | 288,000 objects | **24.5 GB** |
| **Large (500 devices)** | 4.08 GB / day | 122.4 GB / month | 1,440,000 objects | **122.4 GB** |
| **Enterprise (1,000 devices)**| 8.16 GB / day | 244.8 GB / month | 2,880,000 objects | **244.8 GB** |
| **Mega Fleet (5,000 devices)** | 40.8 GB / day | 1,224.0 GB (~1.2 TB) | 14,400,000 objects | **1.22 TB** |

---

## 4. Telemetry Events & Database Capacity Model

In addition to object storage, SQLite agent journals and backend MySQL ingestion handle telemetry activity events (`app.active`, `session.idle_start`, `session.idle_end`, `session.lock`, `session.unlock`, `session.sleep`, `session.wake`).

### 4.1 Telemetry Volume per Device
- Average user desktop activity: **15 to 40 app transitions / hour**.
- 8-hour shift telemetry events: **~200 events / day**.
- Average serialized event payload in MySQL: **~250 bytes**.
- Daily telemetry database growth per device: **~50 KB / day** (1.5 MB / device / month).
- 1,000-device organization database growth: **~1.5 GB / month** of raw activity events.
- Nightly aggregation into `DailyMetrics` (1 row per device per day, ~180 bytes) produces compact, high-speed reporting tables.

---

## 5. Storage Quotas, Headroom Protection, and Cleanup (§10.2, §12.1)

1. **Agent Local Spool Headroom (REQ-5-2, E17, E18):**
   - The desktop agent enforces a **1.0 GB local spool quota** and **500 MB minimum free disk headroom**.
   - If free disk drops below threshold, the agent evicts oldest screenshots first, preserving the durable journal.
2. **Automated S3 Retention Sweep (E54, §12.1):**
   - Expired screenshots are purged automatically past `delete_after` via `run_retention_sweep()`.
   - Purge throughput exceeds **450 items / second** in tests.
   - Verified two-phase deletion ensures zero orphan objects remain in MinIO/S3 after MySQL status transitions to `deleted`.
3. **Legal Hold Exemption (§11.2, E90):**
   - Records with active `LegalHoldRecord` are excluded from purge queries until explicitly released by authorized counsel or admin.

---

## 6. S3 Cost Estimates (Reference AWS us-east-1 S3 Standard)

Assuming \$0.023 per GB-month for S3 Standard storage and \$0.005 per 1,000 PUT requests:

| Fleet Size (5m interval, 8h day) | Monthly Storage (GB) | Storage Cost / Month | PUT Request Cost / Month | Total Storage Cost / Month | Cost per Device / Month |
|---|---|---|---|---|---|
| **10 devices** | 2.45 GB | \$0.06 | \$0.14 | **\$0.20** | **\$0.020** |
| **100 devices** | 24.5 GB | \$0.56 | \$1.44 | **\$2.00** | **\$0.020** |
| **1,000 devices** | 244.8 GB | \$5.63 | \$14.40 | **\$20.03** | **\$0.020** |
| **5,000 devices** | 1,224 GB | \$28.15 | \$72.00 | **\$100.15** | **\$0.020** |

*Conclusion:* Storage infrastructure cost is approximately **\$0.02 per monitored seat per month**, providing exceptional margin headroom under standard SaaS tier pricing (§15.3).

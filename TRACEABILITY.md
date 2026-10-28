# TRACEABILITY.md

> **Purpose:** Single source of truth linking every spec requirement and edge case to the prompt that builds it, the code that implements it, and the test that proves it.
>
> **Columns:**
> - `ID` — Unique identifier
> - `Requirement / Edge Case` — Text from spec or edge case description
> - `Spec Section` — Section of SPEC.md
> - `Prompt` — Build prompt (P0–P12) or test prompt (T1–T8) that delivers it
> - `Code Path` — File(s) implementing it (filled in by each prompt)
> - `Test Path` — Test file(s) proving it (filled in by each prompt)
> - `Status` — `todo` | `done` | `limitation`

---

## Requirements

| ID | Requirement | Spec Section | Prompt | Code Path | Test Path | Status |
|---|---|---|---|---|---|---|
| REQ-1-1 | MUST provide transparent, policy-driven, auditable monitoring | §1.1 | P0–P12, T3 | backend/apps/analytics/views.py, frontend/src/components/EmployeeSelfView.tsx | tests/test_t3_browser_e2e.py | done |
| REQ-1-2 | MUST capture foreground application usage | §1.1 | P4, P5, P6 | backend/apps/analytics/timeline.py, agent/adapters/windows/adapter.py | tests/test_p4_analytics_timeline_reports.py, tests/test_p6_windows_adapter.py | done |
| REQ-1-3 | MUST capture session activity (active/idle/locked) | §1.1 | P4, P5, P6 | backend/apps/analytics/timeline.py, agent/adapters/windows/adapter.py | tests/test_p4_analytics_timeline_reports.py, tests/test_p6_windows_adapter.py | done |
| REQ-1-4 | MUST capture periodic screenshots | §1.1 | P3, P5, P6 | backend/apps/screenshots/services.py, agent/adapters/windows/adapter.py | tests/test_p3_screenshots_storage_retention.py, tests/test_p6_windows_adapter.py | done |
| REQ-1-5 | MUST operate as a lightweight agent respecting OS permissions | §1.1 | P5, P6, P11, P12, T6 | agent/core/scheduler.py, agent/adapters/windows/adapter.py, agent/adapters/linux/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py, tests/test_p12_linux_adapter.py, tests/test_t6_perf_load_footprint.py | done |
| REQ-1-6 | MUST support Windows (primary), macOS, and Linux | §1.2 | P6, P11, P12 | agent/adapters/windows/, agent/adapters/macos/, agent/adapters/linux/ | tests/test_p6_windows_adapter.py, tests/test_p11_macos_adapter.py, tests/test_p12_linux_adapter.py | done |
| REQ-1-7 | MUST support full offline operation with durable local queuing | §1.2 | P5 | agent/core/journal.py, agent/core/spool.py | tests/test_p5_agent_core.py | done |
| REQ-1-8 | NEVER do keylogging, password capture, or private-message scraping | §1.3 | P0–P12, T3 | backend/apps/policies/models.py, frontend/src/components/EmployeeSelfView.tsx | tests/test_t3_browser_e2e.py | done |
| REQ-1-9 | NEVER perform hidden or covert monitoring | §1.3 | P0–P12, T3 | agent/core/status.py, frontend/src/components/EmployeeSelfView.tsx | tests/test_t3_browser_e2e.py | done |
| REQ-1-10 | NEVER perform arbitrary remote command execution | §1.3 | P0–P12, T3 | backend/apps/devices/views.py | tests/test_t3_browser_e2e.py | done |
| REQ-2-1 | Employee MUST be able to view own monitoring state and data | §2.1 | P8, T3 | backend/apps/analytics/views.py, frontend/src/components/EmployeeSelfView.tsx | tests/test_p8_dashboard_and_disputes.py, tests/test_t3_browser_e2e.py | done |
| REQ-2-2 | Employee MUST acknowledge first-run notice before any capture | §2.1, §2.3 | P5 | agent/core/status.py | tests/test_p5_agent_core.py | done |
| REQ-2-3 | Manager MUST see only assigned teams | §2.2 | P1, P8, T3 | backend/apps/analytics/views.py, frontend/src/components/ManagerTeamView.tsx | tests/test_p8_dashboard_and_disputes.py, tests/test_t3_browser_e2e.py | done |
| REQ-2-4 | Screenshot access MUST be a separate explicit permission | §2.2 | P1, P3, T3 | backend/apps/rbac/permissions.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t3_browser_e2e.py | done |
| REQ-2-5 | Cross-tenant IDs MUST return 404 or 403 | §2.2 | P1, T3, T5 | backend/apps/tenancy/context.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-2-6 | Multi-tenant users MUST send explicit tenant context validated on every request | §2.2 | P1, T3, T5 | backend/apps/tenancy/context.py, frontend/src/services/api.ts | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-2-7 | Tenant ID MUST be derived from authenticated membership — never from request body | §2.2, §3.2 | P1, P2, T3, T5 | backend/apps/tenancy/context.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-3-1 | MUST use TLS on all transport, never disabled | §3.2 | P5, P10 | agent/core/sync.py, backend/apps/common/middleware.py | tests/test_p5_agent_core.py, tests/test_p10_security_observability_dr.py | done |
| REQ-3-2 | MUST use per-device credentials (prefer public-key) | §3.2 | P2, T3 | backend/apps/devices/authentication.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t3_browser_e2e.py | done |
| REQ-3-3 | MUST use tenant-scoped querysets, cache keys, and object keys | §3.2 | P1, P2, P3, T5 | backend/apps/screenshots/storage.py, backend/apps/screenshots/models.py, backend/apps/common/cache.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-3-4 | Audit log MUST be append-only at application level | §3.2 | P1, T3 | backend/apps/audit/models.py, frontend/src/components/AuditLogViewer.tsx | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py | done |
| REQ-4-1 | Agent core MUST NOT import OS-specific modules | §4.1 | P5 | agent/core/ | tests/test_p5_agent_core.py | done |
| REQ-4-2 | Agent MUST separate capture from upload using bounded queues | §4.3 | P5 | agent/core/scheduler.py, agent/core/journal.py | tests/test_p5_agent_core.py | done |
| REQ-4-3 | Closing tray UI MUST NOT stop capture | §4.3 | P5, P6 | agent/core/status.py, agent/adapters/windows/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py | done |
| REQ-4-4 | Monitoring state MUST remain discoverable when UI is closed | §4.3 | P5 | agent/core/status.py | tests/test_p5_agent_core.py | done |
| REQ-4-5 | Updater MUST verify hash and signature before applying update | §4.4 | P7 | agent/core/updater.py, agent/packaging/signing.py | tests/test_p7_updater_packaging.py | done |
| REQ-4-6 | Updater MUST rollback on any failure | §4.4 | P7 | agent/core/updater.py | tests/test_p7_updater_packaging.py | done |
| REQ-4-7 | Updater MUST NOT update during shutdown | §4.4 | P7 | agent/core/updater.py | tests/test_p7_updater_packaging.py | done |
| REQ-5-1 | Agent MUST start offline under a valid cached policy | §5.1 | P5 | agent/core/policy.py | tests/test_p5_agent_core.py | done |
| REQ-5-2 | Agent MUST drop screenshots before event journal when space is tight | §5.1 | P5 | agent/core/spool.py | tests/test_p5_agent_core.py | done |
| REQ-5-3 | Agent MUST write explicit gap events — never silently delete data | §5.1 | P5 | agent/core/journal.py, agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| REQ-5-4 | Shutdown MUST be bounded — never wait on network | §5.2 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| REQ-5-5 | Unclean shutdown MUST be detected and write a gap event on next start | §5.2 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| REQ-5-6 | Crash loop MUST have a circuit breaker with backoff | §5.3 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| REQ-5-7 | Corrupt SQLite MUST be quarantined; valid records recovered | §5.3 | P5 | agent/core/journal.py | tests/test_p5_agent_core.py | done |
| REQ-6-1 | Agent MUST delete local data ONLY after confirmed acceptance | §6.1 | P5 | agent/core/journal.py, agent/core/sync.py | tests/test_p5_agent_core.py | done |
| REQ-6-2 | Every retry MUST be idempotent | §6.1 | P2, P3, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| REQ-6-3 | Screenshot upload MUST be two-phase (intent + complete) and idempotent | §6.2 | P3, P5 | backend/apps/screenshots/services.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py | done |
| REQ-7-1 | All models MUST use InnoDB utf8mb4, UUID public IDs, UTC timestamps | §7.1 | P1 | backend/apps/common/models.py | tests/test_p1_tenancy_rbac_audit.py | done |
| REQ-7-2 | MUST use expand-then-contract schema changes | §7.1 | P1–P12 | backend/apps/ | scripts/check_migrations.py | done |
| REQ-7-3 | CI MUST fail on destructive migrations without approved marker | §7.1 | P1 | scripts/check_migrations.py | tests/test_p1_tenancy_rbac_audit.py | done |
| REQ-7-4 | Raw accepted events MUST be immutable | §7.2 | P2 | backend/apps/ingestion/models.py | tests/test_p2_devices_policies_ingestion.py | done |
| REQ-8-1 | All API errors MUST return stable machine-readable codes with correlation ID | §8.1 | P2 | backend/apps/common/exceptions.py | tests/test_p2_devices_policies_ingestion.py | done |
| REQ-8-2 | No error response MAY leak information about other tenants | §8.1 | P1, P2 | backend/apps/common/exceptions.py | tests/test_p1_tenancy_rbac_audit.py | done |
| REQ-8-3 | Authorization MUST be checked on every request and every Celery task | §3.2 | P1, P4 | backend/apps/rbac/permissions.py, backend/apps/analytics/tasks.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_p4_analytics_timeline_reports.py | done |
| REQ-8-4 | Every endpoint MUST have negative authorization tests | §3.2 | P1, T3, T5 | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-9-1 | Timeline reconstruction MUST be deterministic | §9.1 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| REQ-9-2 | No overlapping intervals per device | §9.1 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| REQ-9-3 | Gaps MUST be explicit unknowns — never filled or counted as activity | §9.1 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| REQ-9-4 | Impossible sequences MUST be normalized, recorded as anomalies, never produce negative durations | §9.1 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| REQ-9-5 | Daily metrics MUST have a unique grain; recalculation MUST be idempotent | §9.3 | P4 | backend/apps/analytics/metrics.py | tests/test_p4_analytics_timeline_reports.py | done |
| REQ-10-1 | Screenshots MUST NOT be stored in MySQL — only object keys | §10.2 | P3 | backend/apps/screenshots/models.py, backend/apps/screenshots/storage.py | tests/test_p3_screenshots_storage_retention.py | done |
| REQ-10-2 | Object keys MUST be tenant-scoped and non-guessable | §10.2 | P3, T5 | backend/apps/screenshots/storage.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-10-3 | Every upload MUST be treated as untrusted (strict decode, type/dimension limits) | §10.2 | P3, T5 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-10-4 | View URLs MUST be short-lived, scoped to one object, and every view audited | §10.2 | P3, T3, T5 | backend/apps/screenshots/services.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-11-1 | Audit log MUST record actor, action, resource, timestamp, request ID for all listed events | §11.1 | P1, T5 | backend/apps/audit/models.py, backend/apps/audit/services.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-11-2 | Legal hold MUST prevent deletion of eligible data | §11.2 | P3 | backend/apps/screenshots/services.py, backend/apps/screenshots/models.py | tests/test_p3_screenshots_storage_retention.py | done |
| REQ-11-3 | Employee self-view MUST show own monitoring state, policy, and data collected | §11.3 | P8, T3 | backend/apps/analytics/views.py, frontend/src/components/EmployeeSelfView.tsx | tests/test_p8_dashboard_and_disputes.py, tests/test_t3_browser_e2e.py | done |
| REQ-11-4 | Each threat in threat model MUST have an automated or documented test | §11.4 | P10, T5 | docs/threat-model.md | tests/test_p10_security_observability_dr.py, tests/test_t5_security_tenant_isolation.py | done |
| REQ-12-1 | Agent heartbeat MUST include all signals in §12.1 | §12.1 | P2, P5 | backend/apps/ingestion/views.py | tests/test_p2_devices_policies_ingestion.py | done |
| REQ-12-2 | Agent silence alerts MUST account for sleep and work hours | §12.2 | P10 | backend/apps/devices/alerts.py | tests/test_p10_security_observability_dr.py | done |
| REQ-13-1 | Every edge case E01–E100 MUST have a test named test_E##_description OR documented limitation + safe behavior test | §13 | T7 | docs/test-evidence/edge-cases.md | tests/ | done |
| REQ-14-1 | Overall test coverage MUST be ≥ 80% branch | §14.1 | T1 | .coveragerc, backend, agent/core | tests/test_t1_coverage_baseline.py, docs/test-evidence/T1.md | done |
| REQ-14-2 | Tenant scoping, ingestion, timeline, journal/spool coverage MUST be ≥ 90% branch | §14.1 | T1 | backend/apps/tenancy/context.py, backend/apps/ingestion/services.py, backend/apps/analytics/timeline.py, agent/core/journal.py, agent/core/spool.py | tests/test_t1_coverage_baseline.py | done |
| REQ-14-3 | All acceptance criteria in §14.2 MUST pass with evidence | §14.2 | T8 | | | todo |
| REQ-14-4 | Fault injection invariants in §14.3 MUST hold | §14.3 | T4 | agent/core/journal.py, agent/core/spool.py, agent/core/lifecycle.py, agent/core/sync.py, backend/apps/ingestion/services.py, backend/apps/analytics/tasks.py | tests/test_t4_fault_injection.py, docs/test-evidence/T4.md | done |
| REQ-15-1 | Native signed installer MUST embed Python runtime (users never install Python) | §15.1 | P7 | agent/installer/install.py, agent/packaging/build_windows.py | tests/test_p7_updater_packaging.py | done |
| REQ-15-2 | Uninstaller MUST follow pending-data policy and NEVER silently delete unsynced data | §15.1 | P7 | agent/installer/uninstall.py | tests/test_p7_updater_packaging.py | done |
| REQ-15-3 | Per-tenant quotas MUST be enforced server-side | §15.3 | P9 | backend/apps/billing/services.py, backend/apps/devices/services.py | tests/test_p9_billing_and_lifecycle.py | done |
| REQ-17-1 | All checklist items in §17.1 MUST have evidence links | §17.1 | T8 | | | todo |
| REQ-17-2 | All open decisions in §17.2 MUST be reviewed at release | §17.2 | T8 | | | todo |

---

## Edge Cases

| ID | Edge Case | Spec Section | Prompt | Code Path | Test Path | Status |
|---|---|---|---|---|---|---|
| E01 | No internet at startup | §13 | P5 | agent/core/policy.py | tests/test_p5_agent_core.py | done |
| E02 | Connection lost mid-upload | §13 | P2, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E03 | Batch committed but response lost | §13 | P2, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E04 | DNS failure or captive portal | §13 | P5 | agent/core/diagnostics.py | tests/test_p5_agent_core.py | done |
| E05 | Proxy, VPN or firewall blocks API | §13 | P5 | agent/core/diagnostics.py | tests/test_p5_agent_core.py | done |
| E06 | TLS certificate invalid or expired | §13 | P5, P10 | agent/core/sync.py | tests/test_p5_agent_core.py | done |
| E07 | Shutdown while online | §13 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| E08 | Hard power loss | §13 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| E09 | Agent killed during SQLite write | §13 | P5 | agent/core/journal.py | tests/test_p5_agent_core.py | done |
| E10 | Agent crashes repeatedly | §13 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| E11 | UI closed, agent continues | §13 | P5 | agent/core/status.py | tests/test_p5_agent_core.py | done |
| E12 | Employee explicitly exits monitoring | §13 | P5 | agent/core/status.py | tests/test_p5_agent_core.py | done |
| E13 | Uninstall with pending data | §13 | P5, P7 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| E14 | OS update or reboot | §13 | P7, P11 | agent/core/updater.py, agent/adapters/macos/adapter.py | tests/test_p7_updater_packaging.py, tests/test_p11_macos_adapter.py | done |

| E15 | Agent update interrupted | §13 | P7 | agent/core/updater.py | tests/test_p7_updater_packaging.py | done |
| E16 | Agent and server version mismatch | §13 | P2, P7 | backend/apps/ingestion/services.py, backend/apps/ingestion/views.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E17 | Local disk full | §13 | P5 | agent/core/spool.py | tests/test_p5_agent_core.py | done |
| E18 | Local queue reaches quota | §13 | P5 | agent/core/journal.py | tests/test_p5_agent_core.py | done |
| E19 | SQLite corrupt | §13 | P5 | agent/core/journal.py | tests/test_p5_agent_core.py | done |
| E20 | Screenshot file without DB row | §13 | P5 | agent/core/spool.py | tests/test_p5_agent_core.py | done |
| E21 | DB row without screenshot file | §13 | P5 | agent/core/spool.py | tests/test_p5_agent_core.py | done |
| E22 | Encryption key unavailable | §13 | P5, P12 | agent/core/crypto.py, agent/adapters/linux/linux_api.py | tests/test_p5_agent_core.py, tests/test_p12_linux_adapter.py | done |

| E23 | Device reimaged or profile deleted | §13 | P2, P5 | backend/apps/devices/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E24 | Device stolen | §13 | P2 | backend/apps/devices/authentication.py, backend/apps/devices/views.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E25 | Device clock far off | §13 | P2, P4, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E26 | Clock changes while running | §13 | P4, P5 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E27 | Timezone changes | §13 | P4, P5 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E28 | DST 23 or 25 hour day | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E29 | Duplicate timestamps | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E30 | Events arrive out of order | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E31 | Duplicate event ID, same payload | §13 | P2 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E32 | Duplicate event ID, different payload | §13 | P2 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E33 | Unknown event type | §13 | P2 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E34 | Oversized batch | §13 | P2, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E35 | Rate limit or overload | §13 | P2, P5 | backend/apps/ingestion/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E36 | Partial batch acceptance | §13 | P2, P5 | backend/apps/ingestion/services.py, backend/apps/ingestion/views.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t2_full_integration.py | done |
| E37 | Policy changed while offline | §13 | P2, P5 | backend/apps/policies/models.py, agent/core/policy.py | tests/test_p2_devices_policies_ingestion.py, tests/test_p5_agent_core.py, tests/test_t2_full_integration.py | done |
| E38 | Device revoked while offline | §13 | P2, P5 | backend/apps/devices/authentication.py, agent/core/policy.py | tests/test_p2_devices_policies_ingestion.py, tests/test_p5_agent_core.py, tests/test_t2_full_integration.py | done |
| E39 | Enrollment token reused or expired | §13 | P2 | backend/apps/devices/models.py, backend/apps/devices/services.py | tests/test_p2_devices_policies_ingestion.py | done |
| E40 | Device credential leaked | §13 | P2 | backend/apps/devices/models.py, backend/apps/devices/authentication.py | tests/test_p2_devices_policies_ingestion.py | done |
| E41 | Employee moved to another team | §13 | P1, P8 | backend/apps/tenancy/views.py, backend/apps/tenancy/services.py | tests/test_p1_tenancy_rbac_audit.py | done |
| E42 | Employee leaves company | §13 | P1, P9 | backend/apps/tenancy/models.py, backend/apps/tenancy/services.py | tests/test_p1_tenancy_rbac_audit.py | done |
| E43 | Tenant suspended | §13 | P1, P9 | backend/apps/tenancy/context.py, backend/apps/tenancy/services.py, backend/apps/tenancy/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_p9_billing_and_lifecycle.py | done |
| E44 | Tenant deleted | §13 | P1, P9 | backend/apps/tenancy/context.py, backend/apps/tenancy/services.py, backend/apps/tenancy/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_p9_billing_and_lifecycle.py | done |
| E45 | Cross-tenant object ID guessed | §13 | P1, T3, T5 | backend/apps/tenancy/context.py, backend/apps/tenancy/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t2_full_integration.py, tests/test_t3_browser_e2e.py, tests/test_t5_security_tenant_isolation.py | done |
| E46 | User in multiple tenants | §13 | P1, P8, T3 | backend/apps/tenancy/context.py, backend/apps/tenancy/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t2_full_integration.py, tests/test_t3_browser_e2e.py | done |
| E47 | Manager changes teams | §13 | P1, P8 | backend/apps/rbac/permissions.py, backend/apps/tenancy/services.py | tests/test_p1_tenancy_rbac_audit.py | done |
| E48 | Admin account compromised | §13 | P1, P10, T5 | backend/apps/accounts/models.py, backend/apps/accounts/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t5_security_tenant_isolation.py | done |
| E49 | Screenshot view URL leaked | §13 | P3, T5 | backend/apps/screenshots/services.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t5_security_tenant_isolation.py | done |
| E50 | Malicious uploaded file | §13 | P3, T5 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t5_security_tenant_isolation.py | done |
| E51 | Screenshot upload partially completes | §13 | P3 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t2_full_integration.py | done |
| E52 | Upload succeeded, finalize failed | §13 | P3 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t2_full_integration.py | done |
| E53 | Finalize succeeded, response lost | §13 | P3 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py, tests/test_t2_full_integration.py | done |
| E54 | Retention job fails | §13 | P3 | backend/apps/screenshots/services.py | tests/test_p3_screenshots_storage_retention.py | done |
| E55 | Screenshot exclusion rule added | §13 | P3 | backend/apps/screenshots/services.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py | done |
| E56 | OS permission denied or revoked | §13 | P5, P6, P11, P12 | agent/core/scheduler.py, agent/adapters/windows/adapter.py, agent/adapters/macos/adapter.py, agent/adapters/linux/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py, tests/test_p11_macos_adapter.py, tests/test_p12_linux_adapter.py | done |
| E57 | Screen locked | §13 | P6 | agent/adapters/windows/adapter.py | tests/test_p6_windows_adapter.py | done |
| E58 | Sleep, hibernate and wake | §13 | P4, P6 | backend/apps/analytics/timeline.py, agent/adapters/windows/adapter.py | tests/test_p4_analytics_timeline_reports.py, tests/test_p6_windows_adapter.py | done |
| E59 | Fast user switching | §13 | P5, P6, P11 | agent/core/lifecycle.py, agent/adapters/windows/adapter.py, agent/adapters/macos/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py, tests/test_p11_macos_adapter.py | done |
| E60 | Remote desktop or VDI | §13 | P6, P12 | agent/adapters/windows/adapter.py, agent/adapters/linux/adapter.py | tests/test_p6_windows_adapter.py, tests/test_p12_linux_adapter.py | done |
| E61 | Multiple monitors and topology changes | §13 | P6, P11 | agent/adapters/windows/adapter.py, agent/adapters/macos/adapter.py | tests/test_p6_windows_adapter.py, tests/test_p11_macos_adapter.py | done |
| E62 | Wayland and X11 capability mismatch | §13 | P12 | agent/adapters/linux/adapter.py | tests/test_p12_linux_adapter.py | done |
| E63 | macOS permission reset | §13 | P11 | agent/adapters/macos/adapter.py | tests/test_p11_macos_adapter.py | done |

| E64 | Windows secure desktop or UAC | §13 | P6 | agent/adapters/windows/adapter.py | tests/test_p6_windows_adapter.py | done |
| E65 | Linux headless or unsupported desktop | §13 | P12 | agent/adapters/linux/adapter.py | tests/test_p12_linux_adapter.py | done |

| E66 | App identifier unavailable | §13 | P4, P6 | backend/apps/analytics/timeline.py, agent/adapters/windows/adapter.py | tests/test_p4_analytics_timeline_reports.py, tests/test_p6_windows_adapter.py | done |
| E67 | Window title has sensitive data | §13 | P5, P6 | agent/core/privacy_filter.py, agent/adapters/windows/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py | done |
| E68 | Screenshot has sensitive data | §13 | P5, P6 | agent/core/privacy_filter.py, agent/adapters/windows/adapter.py | tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py | done |
| E69 | App classification changes | §13 | P4, P8 | backend/apps/analytics/metrics.py | tests/test_p4_analytics_timeline_reports.py | done |
| E70 | Idle threshold changes | §13 | P4, P8 | backend/apps/analytics/metrics.py | tests/test_p4_analytics_timeline_reports.py, tests/test_t2_full_integration.py | done |
| E71 | Session never receives end event | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E72 | Idle end without idle start | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E73 | Overlapping app intervals | §13 | P4 | backend/apps/analytics/timeline.py | tests/test_p4_analytics_timeline_reports.py | done |
| E74 | Late event changes daily totals | §13 | P4, P8 | backend/apps/analytics/metrics.py | tests/test_p4_analytics_timeline_reports.py | done |
| E75 | Worker retries same job | §13 | P4 | backend/apps/analytics/tasks.py | tests/test_p4_analytics_timeline_reports.py | done |
| E76 | Celery or Redis unavailable | §13 | P4 | backend/apps/analytics/tasks.py | tests/test_p4_analytics_timeline_reports.py | done |
| E77 | MySQL failover or deadlock | §13 | P4, P10 | backend/apps/analytics/tasks.py | tests/test_p4_analytics_timeline_reports.py | done |
| E78 | Database migration fails | §13 | P1, P10 | scripts/check_migrations.py | tests/test_p1_tenancy_rbac_audit.py | done |
| E79 | Connection pool exhausted | §13 | P4, T6 | backend/apps/analytics/views.py | tests/test_p4_analytics_timeline_reports.py, tests/test_t6_perf_load_footprint.py | done |
| E80 | Stale or cross-tenant cache | §13 | P1, P10 | backend/apps/common/cache.py | tests/test_p1_tenancy_rbac_audit.py | done |
| E81 | Report query too large | §13 | P4, T6 | backend/apps/analytics/views.py | tests/test_p4_analytics_timeline_reports.py, tests/test_t6_perf_load_footprint.py | done |
| E82 | Export exceeds limits | §13 | P4, T6 | backend/apps/analytics/views.py, backend/apps/analytics/tasks.py | tests/test_p4_analytics_timeline_reports.py, tests/test_t6_perf_load_footprint.py | done |
| E83 | Invitation email delivery fails | §13 | P9 | backend/apps/tenancy/services.py, backend/apps/tenancy/views.py | tests/test_p9_billing_and_lifecycle.py | done |
| E84 | Payment webhook duplicated or out of order | §13 | P9 | backend/apps/billing/services.py, backend/apps/billing/views.py | tests/test_p9_billing_and_lifecycle.py | done |
| E85 | Subscription limit reached | §13 | P2, P9 | backend/apps/billing/services.py, backend/apps/devices/services.py | tests/test_p2_devices_policies_ingestion.py, tests/test_p9_billing_and_lifecycle.py | done |
| E86 | Backup restore needed | §13 | P10 | scripts/dr/backup_mysql.py, scripts/dr/restore_mysql.py, scripts/dr/verify_db_storage_consistency.py | tests/test_p10_security_observability_dr.py | done |
| E87 | Region or provider outage | §13 | P10 | backend/apps/common/views.py, docs/runbooks/disaster-recovery.md | tests/test_p10_security_observability_dr.py | done |
| E88 | Logs or crash dumps contain secrets | §13 | P5, P10 | agent/core/diagnostics.py, backend/apps/common/logging.py | tests/test_p5_agent_core.py, tests/test_p10_security_observability_dr.py | done |
| E89 | False positive or employee dispute | §13 | P8, T3 | backend/apps/analytics/models.py, backend/apps/analytics/views.py, frontend/src/components/DisputeModal.tsx | tests/test_p8_dashboard_and_disputes.py, tests/test_t3_browser_e2e.py | done |
| E90 | Legal retention or deletion request | §13 | P3 | backend/apps/screenshots/services.py, backend/apps/screenshots/views.py | tests/test_p3_screenshots_storage_retention.py | done |
| E91 | Untrusted local administrator tampers | §13 | P7 | agent/core/updater.py, docs/LIMITATIONS.md | tests/test_p7_updater_packaging.py | limitation |
| E92 | Agent disabled by antivirus or EDR | §13 | P6, P7 | agent/adapters/windows/adapter.py, docs/test-evidence/windows.md | tests/test_p6_windows_adapter.py | done |
| E93 | Monotonic clock reset after reboot | §13 | P5 | agent/core/lifecycle.py | tests/test_p5_agent_core.py | done |
| E94 | Compression differs by OS | §13 | P5, P12, T6 | agent/adapters/windows/adapter.py, agent/adapters/macos/adapter.py, agent/adapters/linux/adapter.py | tests/test_p6_windows_adapter.py, tests/test_p11_macos_adapter.py, tests/test_p12_linux_adapter.py, tests/test_t6_perf_load_footprint.py | done |

| E95 | Very large multi-monitor capture | §13 | P6 | agent/adapters/windows/adapter.py | tests/test_p6_windows_adapter.py | done |
| E96 | Battery saver or CPU pressure | §13 | P5, T6 | agent/core/scheduler.py | tests/test_p5_agent_core.py, tests/test_t6_perf_load_footprint.py | done |
| E97 | Offline beyond retention or quota | §13 | P5 | agent/core/journal.py | tests/test_p5_agent_core.py | done |
| E98 | User changes OS account | §13 | P2, P5, P6 | backend/apps/devices/models.py, agent/core/lifecycle.py, agent/adapters/windows/adapter.py | tests/test_p2_devices_policies_ingestion.py, tests/test_p5_agent_core.py, tests/test_p6_windows_adapter.py | done |
| E99 | Concurrent admin policy edits | §13 | P2, P8, T3 | backend/apps/policies/models.py, backend/apps/policies/views.py | tests/test_p2_devices_policies_ingestion.py, tests/test_t3_browser_e2e.py | done |
| E100 | Support staff accesses customer data | §13 | P1, T3 | backend/apps/support_access/models.py, backend/apps/support_access/views.py | tests/test_p1_tenancy_rbac_audit.py, tests/test_t3_browser_e2e.py | done |

---

## Acceptance Criteria (§14.2)

| ID | Criterion | Prompt | Evidence | Status |
|---|---|---|---|---|
| AC-1 | All test suites pass (T1–T7) | T8 | | todo |
| AC-2 | check_traceability.py --final passes | T8 | | todo |
| AC-3 | Every E01–E100 has code and passing test or documented limitation | T7 | docs/test-evidence/edge-cases.md | done |
| AC-4 | Agent footprint within budget (≤ 20% regression from baseline) | T6 | docs/test-evidence/T6.md, docs/perf/BASELINE.md | done |
| AC-5 | No cross-tenant data leak | T5 | docs/test-evidence/T5.md | done |
| AC-6 | Restore drill completed with RTO/RPO evidence | T4, T8 | | todo |
| AC-7 | RELEASE_READINESS.md produced and reviewed | T8 | | todo |

---

## Release Checklist (§17.1)

| ID | Item | Evidence Link | Status |
|---|---|---|---|
| RC-01 | All unit tests pass | T8 | | todo |
| RC-02 | All integration tests pass | T8 | | todo |
| RC-03 | All E2E tests pass | T8 | | todo |
| RC-04 | All 100 edge cases covered or documented | T7, T8 | | todo |
| RC-05 | Agent footprint measured and within budget | T6, T8 | | todo |
| RC-06 | Security test evidence (T5) reviewed | T5, T8 | | todo |
| RC-07 | Cross-tenant isolation verified | T5, T8 | | todo |
| RC-08 | Fault injection results reviewed (T4) | T4, T8 | | todo |
| RC-09 | Restore drill completed (T4/T8) | T4, T8 | | todo |
| RC-10 | Log redaction verified (no secrets in logs) | T5, T8 | | todo |
| RC-11 | Dependency scan clean (no critical CVEs) | T8 | | todo |
| RC-12 | Secret scan clean (no secrets in repo) | T8 | | todo |
| RC-13 | Migration check passes on empty DB and previous version DB | T8 | | todo |
| RC-14 | check_traceability.py --final passes | T8 | | todo |
| RC-15 | RELEASE_READINESS.md produced | T8 | | todo |
| RC-16 | Privacy notice reviewed | P10, T8 | | todo |
| RC-17 | Employee notice template reviewed | P10, T8 | | todo |
| RC-18 | DPDP checklist reviewed by counsel | P10, T8 | | todo |

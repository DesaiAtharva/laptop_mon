# Threat Model & Security Defenses Verification

## 1. Overview

This document formalizes the threat model for the Laptop Productivity Monitoring SaaS under **SPEC §11.4** and verifies that **every identified threat has an automated or documented test (REQ-11-4)**.

---

## 2. Threat Matrix and Verification Traceability

| Threat | Vulnerability / Attack Vector | Architectural Mitigation | Test File & Verification Method | Status |
|---|---|---|---|---|
| **Cross-tenant data access (IDOR)** | Attacker guesses UUIDs of devices, users, or policies belonging to another organization. | Tenant-scoped managers and querysets; requests fail closed with 404/403 on tenant mismatch. | `tests/test_p1_tenancy_rbac_audit.py`<br>`tests/test_p10_security_observability_dr.py` (`test_threat_idor_cross_tenant_access`) | **VERIFIED** |
| **Stolen device credential** | Extracted device token used to forge telemetry from an unauthorized machine. | Immediate server-side revocation (`POST /api/devices/{id}/revoke`), abnormal usage detection. | `tests/test_p2_devices_policies_ingestion.py` (`test_E24_device_stolen`, `test_E40_device_credential_leaked`) | **VERIFIED** |
| **Replayed enrollment token** | Captured enrollment token reused to register unauthorized rogue devices. | Tokens stored hashed (SHA-256), single-use consumption, immediate expiration. | `tests/test_p2_devices_policies_ingestion.py` (`test_E39_enrollment_token_reused_or_expired`) | **VERIFIED** |
| **Screenshot URL leak** | Presigned S3 view URL captured in transit or browser history. | Short-lived URLs (300s expiry), scoped to single object key, view audited in DB, URL never written to application logs. | `tests/test_p3_screenshots_storage_retention.py` (`test_E49_screenshot_view_url_leaked`) | **VERIFIED** |
| **Malicious upload / exploit payload** | Attacker uploads malicious script, zip bomb, or executable disguised as an image. | Strict image decode validation, size caps (10MB), resolution bounds, unprivileged storage, no execution. | `tests/test_p3_screenshots_storage_retention.py` (`test_E50_malicious_uploaded_file`) | **VERIFIED** |
| **Compromised admin account** | Attacker acquires organization admin credentials. | Mandatory MFA on privileged actions, immediate session revocation upon suspicion, audit log of all admin events. | `tests/test_p1_tenancy_rbac_audit.py` (`test_E48_admin_account_compromised`)<br>`tests/test_p10_security_observability_dr.py` (`test_threat_compromised_admin_session_revocation`) | **VERIFIED** |
| **Tenant spoofing in agent payloads** | Malicious agent sends another tenant's ID in request headers or JSON payload to pollute telemetry. | Tenant ID is strictly derived on server from verified device credential — never accepted from payload. | `tests/test_p2_devices_policies_ingestion.py` (`test_agent_cannot_choose_tenant`)<br>`tests/test_p10_security_observability_dr.py` (`test_threat_tenant_spoofing_rejected`) | **VERIFIED** |
| **Secrets in logs / crash dumps** | Sensitive tokens, passwords, or presigned URLs leaked into logging aggregation systems. | `SecretRedactingFilter` and `JSONFormatter` sanitize records using regex masks before emission. | `tests/test_p5_agent_core.py` (`test_E88_redacted_logs`)<br>`tests/test_p10_security_observability_dr.py` (`test_E88_logs_contain_no_secrets`) | **VERIFIED** |
| **Stale / cross-tenant cache leakage** | Redis cache returns cached data belonging to another tenant or invalid permissions after role revocation. | Tenant-scoped cache keys (`tenant:{id}:*`), immediate invalidation on membership/role changes. | `tests/test_p1_tenancy_rbac_audit.py` (`test_E80_stale_or_cross_tenant_cache`) | **VERIFIED** |
| **Support staff data access** | Rogue SaaS support personnel inspect customer screenshots or employee metrics. | Just-in-time approval-gated access, strictly time-bounded (max 8h), zero standing screenshot permissions, all views audited. | `tests/test_p1_tenancy_rbac_audit.py` (`test_E100_support_staff_accesses_customer_data`) | **VERIFIED** |

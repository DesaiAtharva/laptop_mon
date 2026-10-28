# DPDP & GDPR Compliance Checklist for Legal Counsel

> **Disclaimer:** This document is a technical architecture and compliance reference mapping technical capabilities to the Digital Personal Data Protection (DPDP) Act and the General Data Protection Regulation (GDPR). It does not constitute legal advice.

---

## 1. Core Data Protection Principles

| Principle / Legal Requirement | Technical Safeguard in LaptopMon SaaS | Architecture Reference |
|---|---|---|
| **Notice & Consent / Transparency** | First-run mandatory notice before capture begins; Employee Self-View dashboard with complete visibility into logged data. | §2.1, §2.3, §11.3 |
| **Purpose Limitation** | Data capture restricted exclusively to work hours and company-issued laptop usage; no off-hours capture. | §11.2, `MonitoringPolicy.capture_windows` |
| **Data Minimisation** | No keylogging, no password scraping, window title redaction, automatic exclusion of password managers. | §1.3, `agent/core/privacy_filter.py` |
| **Storage Limitation & Retention** | Configurable retention periods with automated verified deletion sweeps (`delete_after`). | §10.2, §11.2, `backend/apps/screenshots/services.py` |
| **Integrity & Confidentiality** | AES-256 authenticated encryption for local spools; TLS 1.3 in transit; private S3 buckets; HMAC webhook signatures. | §3.2, `agent/core/crypto.py` |
| **Right to Erasure ("Right to be Forgotten")** | Staged, verified cascade tenant deletion removing all related user, device, and telemetry records. | E44, `delete_tenant_cascade()` |
| **Right to Grievance Redressal / Dispute** | Built-in dispute submission and review workflow for employees. | §11.3, E89, `backend/apps/analytics/views.py` |
| **Auditability & Accountability** | Append-only immutable audit trail capturing actor, timestamp, action, and request ID. | §11.1, `backend/apps/audit/models.py` |

---

## 2. Retention Defaults and Review

- **Default Screenshot Retention:** 30 days.
- **Default Metrics Retention:** 90 days.
- **Legal Hold:** Organizations may apply explicit legal holds on specific timeframes, which overrides standard automated deletion sweeps until released by an authorized administrator (§11.2, REQ-11-2).

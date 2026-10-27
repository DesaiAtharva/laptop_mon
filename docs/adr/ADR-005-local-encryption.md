# ADR-005: Local Agent Encryption Approach

**Date:** 2026-10-27
**Status:** Accepted

---

## Context

The agent stores event payloads and screenshot spool files locally before upload. These contain potentially sensitive productivity data. We need authenticated encryption using a key that survives reboots but is inaccessible to other users.

## Decision

- **Algorithm:** AES-256-GCM (authenticated encryption with associated data — AEAD).
- **Key storage:**
  - Windows: DPAPI / Windows Credential Manager (user-scoped)
  - macOS: macOS Keychain (user-scoped)
  - Linux: Secret Service API (libsecret) with documented fallback to a key file in a user-only `chmod 600` location.
- **Key unavailability:** If the key cannot be retrieved, the agent **never uploads plaintext**. It keeps the encrypted files and reports the issue via heartbeat. (E22)
- **Spool protocol:** write encrypted temp file → flush → checksum → atomic rename → mark ready in journal.

## Consequences

- Data at rest is protected against other OS users and physical theft (E24) within the OS security model.
- Key loss (key store reset, reimage) means locally stored unsynced data cannot be recovered. This is documented in `docs/LIMITATIONS.md`.
- The fake adapter simulates both key-available and key-unavailable states for testing.

# Enterprise Code Signing & IT Allowlisting Guide

> **Document Version:** 1.0.0  
> **Target Audience:** IT Administrators, InfoSec Teams, SOC Analysts, System Engineers  
> **Relevant Requirements:** REQ-4-5, REQ-15-1, E91, E92

---

## 1. Transparency & Anti-Evasion Pledge

In strict compliance with **`AGENTS.md`**, the Laptop Productivity Monitoring Agent follows these non-negotiable principles:
- **Zero Obfuscation or Evasion:** We never employ rootkits, process hollowing, DLL unhooking, AMSI bypasses, or anti-analysis tricks.
- **Transparent Execution:** Monitoring runs as a visible user-space application with clear system tray presence and policy transparency notifications.
- **Auditable & Policy-Driven:** All capture operations strictly respect tenant policy boundaries.
- **No Covert Persistence:** Startup persistence is registered cleanly under standard Windows Run registry keys (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) or standard scheduled tasks.
- **Never Intercept Secrets:** No keystroke logging, no password field scraping, and no evasion of OS security boundaries (e.g. UAC / Secure Desktop isolation).

---

## 2. Code Signing Architecture

All production agent binaries (`agent.exe`, DLLs, and installers) are signed using an Extended Validation (EV) Code Signing Certificate issued by a trusted Public Certificate Authority.

### 2.1 Authenticode Specifications
- **Digest Algorithm:** SHA-256 (`/fd sha256`)
- **Timestamp Protocol:** RFC 3161 compliant
- **Timestamp Authority:** `http://timestamp.digicert.com` (`/td sha256`)
- **Subject CN:** `Laptop Productivity Monitoring SaaS, Inc.`

### 2.2 Verifying Signatures Locally

Administrators can verify any downloaded agent binary using PowerShell:
```powershell
Get-AuthenticodeSignature -FilePath "C:\Users\<User>\AppData\Local\LaptopMon\bin\agent.exe"
```
Expected output:
```text
SignerCertificate                         Status   StatusMessage Path
-----------------                         ------   ------------- ----
[Thumbprint / Laptop Productivity...]     Valid    Signature verified. agent.exe
```

Or using `signtool.exe`:
```cmd
signtool.exe verify /pa /v "C:\Users\<User>\AppData\Local\LaptopMon\bin\agent.exe"
```

---

## 3. Antivirus & EDR Allowlisting Guidelines

Because productivity monitoring tools monitor foreground window titles and user input idle seconds (via `GetForegroundWindow` and `GetLastInputInfo`), some heuristic-based EDR or Antivirus engines might raise false-positive alerts if unlisted.

### 3.1 Publisher Certificate Allowlisting (Recommended)
Allowlist all binaries signed by:
- **Certificate Issuer:** DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1
- **Certificate Subject:** `CN=Laptop Productivity Monitoring SaaS, Inc.`

### 3.2 Executable Paths & Hashes
If your EDR platform requires path or hash rules:
- **Default Installation Path:** `%LOCALAPPDATA%\LaptopMon\bin\agent.exe`
- **Configuration File:** `%LOCALAPPDATA%\LaptopMon\config.json`
- **Database & Queue Storage:** `%LOCALAPPDATA%\LaptopMon\data\journal.db`
- **Log Files:** `%LOCALAPPDATA%\LaptopMon\logs\`
- **Release Checksums:** Provided in the signed release manifest (`release-manifest-windows-<version>.json`) published to the admin portal.

### 3.3 Network Allowlisting
The agent requires outbound HTTPS (TLS 1.3 or TLS 1.2) communication:
- **Port:** `443` (TCP)
- **Protocols:** HTTPS only (TLS verification is strictly enforced; certificate pinning / validation cannot be bypassed)
- **Endpoints:**
  - `POST /api/v1/devices/events/` (event batch upload)
  - `POST /api/v1/devices/heartbeat/` (liveness check)
  - `GET /api/v1/agent/releases/latest/` (signed release manifests)
  - `GET /api/v1/devices/policies/` (tenant policy synchronization)

---

## 4. Administrative Tampering & Integrity (E91)

As documented in `docs/LIMITATIONS.md` (`LIM-005`):
- Local administrators have OS privileges that allow terminating processes or modifying files.
- The agent self-verifies SHA-256 hashes and code signatures before and after every automatic update.
- If tampering or binary corruption is detected:
  1. The agent refuses to execute untrusted code and rolls back to the previous known-good binary.
  2. If rollback is unavailable or also corrupted, the agent halts safely with an error log.
  3. The backend detects the absence of heartbeats and records telemetry gaps as **explicit unknown time** — never active, idle, or productive time.

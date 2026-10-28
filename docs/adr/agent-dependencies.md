# Agent Dependency Budget & Justifications

> **Rulebook Reference:** `AGENTS.md` Lightness Rules  
> **ADR Reference:** `docs/adr/ADR-002-agent-runtime.md`  
> **Budget Reference:** Installed size < 60 MB, Resident memory < 80 MB, Idle CPU < 1%  
> **Rule:** Every agent dependency needs a one-line justification and size cost.

---

## 1. Allowed Agent Runtime Dependencies

The desktop agent core (`agent/core`) and OS adapters (`agent/adapters`) strictly prohibit heavy frameworks (`pandas`, `numpy`, embedded browsers, heavy GUI toolkits).

| Dependency | Category | Installed Size Cost | One-Line Justification |
|---|---|---|---|
| **Python Standard Library (minimal subset)** | Core Runtime | ~38.0 MB (stripped) | Standard library modules (`sqlite3`, `json`, `hashlib`, `urllib`, `ctypes`, `dataclasses`). |
| **`cryptography`** | Security | ~5.8 MB | Authenticated encryption (ChaCha20-Poly1305) for local SQLite journal and spool payloads (§5.1, ADR-005). |
| **`Pillow` (PIL)** | Image Processing | ~6.5 MB | Cross-platform screenshot compression (JPEG quality 75, WebP quality 70) and thumbnail generation (§10.1). |
| **`pywin32`** *(Windows adapter only)* | OS Interop | ~4.2 MB | Win32 API bindings for `GetLastInputInfo`, `GetForegroundWindow`, session lock/power broadcast messages (§4.2). |
| **`pystray`** *(optional)* | Tray UI | ~0.4 MB | Lightweight system tray status icon for user discoverability without heavy GUI toolkit (E11). |

---

## 2. Total Installed Footprint vs Budget

- **Total Runtime & Third-Party Dependencies:** ~54.9 MB
- **Agent Core Code & Adapters:** ~0.19 MB
- **Total Packaged Agent Size:** **~55.1 MB** (Budget: **< 60.0 MB** — **PASS**)

---

## 3. Explicitly Banned Libraries

- `pandas`: Excessive memory footprint (> 30 MB heap overhead).
- `numpy`: High binary size (> 35 MB) and unnecessary for integer interval calculations.
- `PyQt6` / `PySide6`: Heavy GUI framework (> 120 MB); violates < 60 MB installed size budget.
- `Electron` / `CEF`: Embedded browser engine (> 150 MB RAM, > 100 MB disk).
- `Django` / `SQLAlchemy`: Heavy ORMs; raw parameterized `sqlite3` used with WAL mode for light deterministic durability.

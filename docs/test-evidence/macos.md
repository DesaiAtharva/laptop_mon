# macOS Adapter Test Evidence & Manual Verification Guide

This document defines manual and automated test evidence procedures for the macOS desktop agent adapter, covering core system events, permissions, and multi-display behavior per §4.2, §10.1, §15.1, and edge cases E14, E56, E59, E61, and E63.

---

## Environment Prerequisites

- **Tested OS Versions:** macOS 13 (Ventura), macOS 14 (Sonoma), macOS 15 (Sequoia).
- **Architecture:** Apple Silicon (`arm64`) and Intel (`x86_64`).
- **Permissions Required:**
  - Accessibility (`System Settings > Privacy & Security > Accessibility`)
  - Screen Recording (`System Settings > Privacy & Security > Screen & System Audio Recording`)

---

## Test Scenarios & Evidence Sheet

### 1. Lock & Sleep Transitions (REQ-1-6, E14)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 1.1  | Press `Control + Command + Q` to lock screen | `com.apple.screenIsLocked` notification received. Adapter reports `is_session_locked() == True`. Event `session_state: locked` spooled. Capture suspended. | Check log: `Session locked: True` |
| 1.2  | Unlock screen with password or Touch ID | `com.apple.screenIsUnlocked` notification received. Adapter reports `is_session_locked() == False`. Telemetry resumes. | Check log: `Session locked: False` |
| 1.3  | Close laptop lid (System Sleep) | `NSWorkspaceWillSleepNotification` received. Spool marks gap timestamp. No phantom active minutes recorded. | Verify DB timeline shows explicit `sleep` gap |
| 1.4  | Open laptop lid (System Wake) | `NSWorkspaceDidWakeNotification` received. Next event establishes wake boundary. | Verify DB timeline resumes without interpolating sleep window |

---

### 2. Fast User Switching (E59)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 2.1  | User A is logged in with agent running in user session (LaunchAgent). | Agent operates normally capturing frontmost app for User A. | `python -m agent.core status` shows active |
| 2.2  | Switch to User B via Fast User Switching (Control Center > Switch User). | User A's session is no longer active on console display (`CGSessionCopyCurrentDictionary` `kCGSSessionOnConsoleKey` == False). Agent pauses capture, does not log User B's activity. | Check log: `Console session switched: on_console=False, pausing telemetry` |
| 2.3  | Switch back to User A. | `kCGSSessionOnConsoleKey` returns True. Agent resumes normal monitoring. | Check log: `Console session active: on_console=True, resuming` |

---

### 3. Multi-Monitor & Topology Changes (E61)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 3.1  | Plug in external 4K monitor via HDMI/USB-C. | `CGGetActiveDisplayList()` reports 2 displays with distinct bounds and DPI scaling factors (Retina 2.0x, external 1.0x). | Check log: `Display count: 2. Bounds: [(0,0,1728,1117), (1728,0,3840,2160)]` |
| 3.2  | Trigger screenshot capture while policy permits. | Agent captures either primary screen or composite bounding box under policy limits; bounds normalized to virtual screen coordinates. | Inspect captured screenshot dimensions |
| 3.3  | Unplug external monitor. | Display re-configuration event received (`CGDisplayRegisterReconfigurationCallback`). Display list collapses to 1. No crash or invalid handle exception. | Check log: `Display reconfigured: count=1` |

---

### 4. Permission Revocation & TCC Reset (E56, E63)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 4.1  | Launch agent without granting Screen Recording. | `check_screen_recording_permission()` returns `False`. Screen capture gracefully returns empty/None with error `PermissionDenied`. Core continues collecting app metadata if Accessibility is granted. | Check log: `Screen recording permission not granted (E56)` |
| 4.2  | In System Settings, toggle Screen Recording ON for `LaptopMonAgent`. | `check_screen_recording_permission()` returns `True` on subsequent preflight. Screen capture succeeds without requiring agent relaunch if macOS version supports dynamic update. | Check log: `Screen recording permission: GRANTED` |
| 4.3  | Simulate OS upgrade TCC reset via `tccutil reset ScreenCapture com.laptopmon.agent`. | `verify_after_os_update()` detects permission drop. Agent issues desktop notification / alert asking employee to re-authorize in System Settings. | Check log: `TCC permission reset detected (E63). Action required: Re-authorize in Privacy & Security.` |

---

## Automated Mock Verification

Automated unit and adapter contract tests are executed in `tests/test_p11_macos_adapter.py`.
The mock bridge verifies that the adapter conforms strictly to `OSAdapterProtocol`, satisfies capability invariants, correctly maps macOS bundle identifiers, and handles missing native APIs gracefully on non-macOS host runners.

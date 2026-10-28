# Linux Adapter Test Evidence & Manual Verification Guide

This document defines manual, headless, and virtual X server test evidence procedures for the Linux desktop agent adapter, covering X11, Wayland, systemd user services, and edge cases E22, E56, E60, E62, E65, and E94 per §4.2, §10.1, §15.1.

---

## Test Environment Prerequisites

- **Tested OS Environments:**
  - Ubuntu 22.04 LTS / 24.04 LTS (GNOME Wayland & X11)
  - Debian 12 Bookworm (XFCE X11)
  - Fedora 40 (GNOME Wayland)
- **Virtual Testing Tooling:**
  - `Xvfb` (Virtual Framebuffer X Server) for automated headless X11 testing.
  - `weston` or `mutter --headless` for virtual Wayland compositor testing.
  - `dbus-run-session` for sandboxed D-Bus session testing.

---

## Test Scenarios & Evidence Sheet

### 1. X11 Virtual Server Verification (REQ-1-6, E61)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 1.1  | Start virtual X server: `Xvfb :99 -screen 0 1920x1080x24 & export DISPLAY=:99`. Launch agent. | Agent connects to X server via `XOpenDisplay`, identifies root window, and reports `SessionType.CONSOLE`. | Check log: `Session type: console, display=:99` |
| 1.2  | Query active window with `xdotool` or mock client active. | `_NET_ACTIVE_WINDOW` atom read. Returns valid window name and process ID. | Check telemetry event: `app_identifier` is populated |
| 1.3  | Query idle time via `XScreenSaverQueryInfo`. | Returns simulated or elapsed idle seconds without crash. | `adapter.get_idle_seconds() >= 0.0` |
| 1.4  | Configure virtual second screen (`xrandr`). | `XRandR` enumerates 2 active CRTC outputs. Bounds normalized to virtual screen coordinates. | Check log: `Display count: 2` |

---

### 2. Wayland Portal & Capability Degraded Mode (E62)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 2.1  | Launch in GNOME Wayland session (`XDG_SESSION_TYPE=wayland`). | `is_wayland() == True`. Adapter recognizes compositor environment. | Check log: `Display server: Wayland` |
| 2.2  | Check capabilities. | Screen capture routed through XDG Desktop Portal (`org.freedesktop.portal.Screenshot`). Foreground app detection reports active cgroup / scope rather than crashing on missing X11 properties. | `AdapterCapability.SCREEN_CAPTURE in caps` |
| 2.3  | User denies portal screenshot prompt. | Capture returns `CaptureResult(is_skipped=True, skip_reason="permission_denied")`. No infinite loop or UI hang. | Check log: `Portal capture declined (E56, E62)` |

---

### 3. Headless & Remote Desktop Sessions (E60, E65)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 3.1  | Run agent in headless container (`DISPLAY` and `WAYLAND_DISPLAY` unset). | `get_session_type()` returns `SessionType.HEADLESS`. Capabilities drop `SCREEN_CAPTURE` and `FOREGROUND_APP`. | Check log: `Session type: headless (E65)` |
| 3.2  | Attempt `capture_screen()`. | Returns `CaptureResult(is_skipped=True, skip_reason="headless_environment")`. | `res.is_skipped == True` |
| 3.3  | Run under XRDP or VNC (`XRDP_SESSION=1`). | Adapter detects `SessionType.REMOTE_DESKTOP`. Binds capture exclusively to the remote user session without leaking host console telemetry. | Check log: `Session type: remote_desktop (E60)` |

---

### 4. Secret Storage & Fallback Keyfile (E22)

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 4.1  | Secret Service daemon missing (`org.freedesktop.secrets` unavailable). | Adapter falls back to `~/.config/laptopmon/{key_name}.key`. | Check log: `Using secure local keyfile fallback (E22)` |
| 4.2  | Verify file permissions of fallback keyfile. | File is created with restricted `0600` permissions (`-rw-------`). Directory created with `0700`. | `stat -c "%a" ~/.config/laptopmon/device_key.key` == `600` |

---

### 5. systemd User Service Autostart

| Step | Action | Expected Agent Behavior | Verification Command / Log Check |
|------|--------|--------------------------|----------------------------------|
| 5.1  | Deploy service: `systemctl --user enable laptopmon-agent.service`. | Service linked to `~/.config/systemd/user/graphical-session.target.wants/`. | `systemctl --user is-enabled laptopmon-agent` |
| 5.2  | User graphical login. | `laptopmon-agent` process starts in `app.slice` with sandboxing enabled (`ProtectSystem=strict`, `ProtectHome=read-only`). | `systemctl --user status laptopmon-agent` |

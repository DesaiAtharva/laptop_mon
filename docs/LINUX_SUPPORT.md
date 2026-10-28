# Linux Desktop Support Matrix & Architecture Guide

This document defines the supported Linux distributions, desktop environments, display servers, and system integration mechanisms for the Laptop Productivity Monitoring desktop agent (§4.2, §15.1, E60, E62, E65).

---

## Supported Distributions

| Distribution | Supported Versions | Package Format | Session Types |
|--------------|-------------------|----------------|---------------|
| Ubuntu | 22.04 LTS, 24.04 LTS | `.deb`, `.tar.gz` | Wayland, X11 |
| Debian | 11 (Bullseye), 12 (Bookworm) | `.deb`, `.tar.gz` | Wayland, X11 |
| Fedora | 38, 39, 40 | `.tar.gz` (RPM compatible) | Wayland, X11 |
| Red Hat Enterprise Linux (RHEL) / Rocky | 8, 9 | `.tar.gz` | Wayland, X11 |

---

## Display Server & Capability Matrix (E62, E65)

| Feature | X11 Sessions | Wayland Sessions | Headless / SSH (E65) |
|---------|-------------|------------------|----------------------|
| **Foreground App** | Full (`_NET_ACTIVE_WINDOW`, `/proc/<pid>/cmdline`) | Compositor-dependent; falls back to active cgroup / systemd scope | Unsupported / None |
| **Idle Detection** | Full (`XScreenSaverQueryInfo`) | Compositor idle portal (`org.freedesktop.portal.Idle`) or mutter/kwin D-Bus | None (0.0s) |
| **Screen Capture** | Direct `XGetImage` / XSHM | `org.freedesktop.portal.Screenshot` (User permission prompt) | Unsupported / Skipped |
| **Multi-Monitor** | Full (`XRandR` 1.5+) | Wayland output globals via portal metadata | None |
| **Lock / Sleep** | `org.freedesktop.login1` & Screensaver D-Bus | `org.freedesktop.login1` & Screensaver D-Bus | logind power signals only |
| **Autostart** | systemd user service (`~/.config/systemd/user/`) | systemd user service | None |
| **Key Storage** | Secret Service (`org.freedesktop.secrets`) / Keyfile | Secret Service / Keyfile | Keyfile fallback (`~/.config/laptopmon/key.bin`) |

---

## Desktop Environments & Compositors

- **GNOME (Mutter):** Full support. Under Wayland, screen capture requests are routed through `xdg-desktop-portal-gnome`.
- **KDE Plasma (KWin):** Full support. Screen capture routed through `xdg-desktop-portal-kde`.
- **XFCE / MATE / Cinnamon (X11):** Full native X11 support via `libX11`, `libXss`, and `libXrandr`.
- **Tiling Window Managers (i3, Sway, Hyprland):** Sway/Hyprland supported via `xdg-desktop-portal-wlr`.

---

## Remote Desktop & VDI Sessions (E60)

The adapter inspects session variables to identify remote or virtualized environments:
- `XRDP_SESSION` or `XRDP_SOCKET_PATH`: XRDP session detected.
- `VNCDESKTOP` or display matching `:1` / `:10` without physical GPU: VNC session.
- `SSH_CONNECTION` or missing `DISPLAY`: Remote terminal session.

Remote desktop sessions are reported with `SessionType.REMOTE_DESKTOP`. Telemetry remains isolated to the authenticated user's session without mixing with physical console sessions.

---

## Headless and Unsupported Desktop Environments (E65)

When neither `DISPLAY` nor `WAYLAND_DISPLAY` is exported (or running inside a minimal Docker container or server):
- `LinuxAdapter` reports `SessionType.HEADLESS`.
- Capabilities drop `SCREEN_CAPTURE` and `FOREGROUND_APP`.
- Capture attempts return `CaptureResult(is_skipped=True, skip_reason="headless_environment")`.
- The agent does not crash or loop in error states.

---

## Desktop Secret Service & Fallback Key Storage (E22)

Per §4.2, device authentication keys and local encryption keys are stored using the standard Freedesktop Secret Service API (`org.freedesktop.secrets`) implemented by GNOME Keyring or KDE KWallet.
If the Secret Service daemon is unavailable (e.g. minimal desktop, headless, or locked keyring):
1. The adapter checks for an existing key in `~/.config/laptopmon/device_key.aes`.
2. The key file is restricted to user-only read/write permissions (`0600`).
3. An explicit warning is logged so the administrator is aware of keyfile fallback.

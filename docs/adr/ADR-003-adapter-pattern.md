# ADR-003: Agent Adapter Pattern

**Date:** 2026-10-27
**Status:** Accepted

---

## Context

The agent must run on Windows, macOS, and Linux, but OS APIs are completely different for each platform. We need the core logic to be testable without a real OS.

## Decision

Use the **Adapter Pattern** with a Protocol interface in `agent/adapters/base.py`.

```
agent/core/         — shared logic, imports ONLY from base.py
agent/adapters/
  base.py           — Protocol (structural subtyping) with capability flags
  windows/          — Win32 implementation
  macos/            — NSWorkspace / CGDisplay implementation
  linux/            — X11 / Wayland / D-Bus implementation
  fake/             — Scriptable, deterministic implementation for tests
```

**Capability flags** (exposed by every adapter):
- `can_capture_foreground_app: bool`
- `can_capture_screen: bool`
- `can_detect_idle: bool`
- `can_detect_lock: bool`
- `can_detect_sleep: bool`
- `session_type: Literal["local", "rdp", "vdi", "headless", "unknown"]`

If a capability is unavailable, the adapter reports it explicitly — never silently fails.

## Consequences

- Core code is fully testable with the fake adapter (used by T2, T4, T5).
- Platform-specific code is isolated to its adapter directory.
- The fake adapter enables running the full pipeline early (before any real OS adapter exists).
- Strict rule: **`agent/core/` must never import OS-specific modules.**

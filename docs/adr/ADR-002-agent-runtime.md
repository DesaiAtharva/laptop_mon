# ADR-002: Agent Runtime — Python with Native Packaging

**Date:** 2026-10-27
**Status:** Accepted

---

## Context

The agent must run on Windows, macOS, and Linux without requiring users to install Python.
It must also be lightweight (< 60 MB installed, < 80 MB RAM, < 1% idle CPU).

## Decision

- **Runtime:** Python 3.12, embedded in a native installer per OS.
- **Packaging:** PyInstaller or Nuitka to embed the interpreter; unused stdlib modules stripped.
- **No** Qt, wxWidgets, Electron, or other heavy GUI frameworks in the always-running process.
- Tray icon via `pystray` (Windows/macOS/Linux) or native OS APIs — kept minimal and optional.

## Dependency Budget

Every agent dependency must have a one-line justification and measured size cost in `docs/adr/agent-dependencies.md`.

Banned: `pandas`, `numpy`, embedded browsers, large ORMs (Django not used in agent).

## Consequences

- Agents never require a Python install from end users.
- Build pipeline must produce signed installers per OS.
- Testing uses the fake adapter, which means the full pipeline (not just the agent) is tested early.

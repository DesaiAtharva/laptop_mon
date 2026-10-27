# ADR-004: SQLite Journal Durability Setting

**Date:** 2026-10-27
**Status:** Accepted

---

## Context

The agent uses SQLite as its local event journal. We need to balance durability (no data loss on crash/power loss) against performance (avoid constant tiny disk writes).

## Decision

- **WAL mode** (`PRAGMA journal_mode=WAL`) for better read/write concurrency.
- **`PRAGMA synchronous=NORMAL`** — flushes WAL to disk at checkpoints, not every commit. This accepts a bounded loss window (events since last checkpoint) on hard power loss.
- **Batch commits**: accumulate events for at most N seconds or M bytes before committing. N and M are documented constants in `agent/core/journal.py`.
- **Checkpoint** runs on a periodic timer and on graceful shutdown.
- Loss window is documented in `docs/LIMITATIONS.md`.

## Consequences

- On hard power loss (E08), at most one batch window of events can be lost. This is documented and explicit (gap event written on next start).
- On graceful shutdown (E07), checkpoint runs, so loss is bounded to inflight events only.
- `PRAGMA synchronous=FULL` was considered but rejected due to excessive disk write amplification on the agent's host machine.

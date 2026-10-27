# AGENTS.md — Laptop Productivity Monitoring SaaS Rulebook

> **This file is the authoritative rulebook for every agent conversation.**
> Read it fully at the start of every prompt. If the spec (`docs/spec/SPEC.md`) and a prompt disagree, **stop and ask**.

---

## Mission

Build the Laptop Productivity Monitoring SaaS exactly as specified in `docs/spec/SPEC.md`.
The spec is the source of truth.

---

## Non-Negotiable Product Rules

- Monitoring is **transparent, policy-driven and auditable**.
- **Never** build:
  - Covert or hidden monitoring
  - Hidden persistence
  - Keylogging
  - Password capture
  - Private-message scraping
  - Any bypass of OS permission prompts
  - Remote shell or arbitrary command execution from server to agent
- **Never invent data.** Missing telemetry is an explicit unknown gap — never active, idle or productive time.
- **Never silently restart** monitoring after an explicit authorized stop or uninstall.
- **Never evade** antivirus or EDR tools. Use signing and documented allowlisting instead.
- **Never claim** zero crashes or zero data loss. Build for detection, automatic recovery and honest gap reporting.

---

## Architecture Rules

### Repository Layout
```
backend/        Django application
frontend/       React + TypeScript application
agent/          Desktop agent
  core/         Shared core (no OS imports)
  adapters/
    windows/    Windows adapter
    macos/      macOS adapter
    linux/      Linux adapter
    fake/       Scriptable fake adapter for tests
deploy/         Docker compose, infrastructure as code
docs/           Spec, ADRs, plans, test evidence, perf baselines
tests/          Integration and end-to-end tests
scripts/        Tooling (check_traceability.py, etc.)
```

### Agent Architecture
- One shared core (`agent/core`) + per-OS adapters behind one interface (`agent/adapters/base.py`).
- Core code **must never** import OS-specific modules.
- Adapter interface defines capability flags: foreground app events, idle seconds, session lock/sleep events, screen capture, permission status, session type.

### Backend
- Django + Django REST Framework — modular monolith.
- MySQL InnoDB utf8mb4.
- Celery with Redis (queue and cache only — **never** the source of truth).
- Private S3-compatible object storage.
- **No** microservices, Kafka, or Kubernetes.

### Frontend
- React, TypeScript in strict mode, Vite.

### Data Rules
- UUID public identifiers, UTC timestamps, explicit migrations.
- Expand-then-contract for schema changes.
- **Tenant ID is always derived from authenticated membership or device registration — never from the request body.**

---

## Agent Lightness Rules

> Targets validated by measurement. Record real numbers in `docs/perf/BASELINE.md`.
> **Fail the build** if they regress by more than 20% from baseline.

| Metric | Target |
|---|---|
| Idle CPU | < 1% average |
| Resident memory | < 80 MB |
| Installed size | < 60 MB |

- **Event-driven, not polling.** Where polling is unavoidable, use the longest interval that still meets the spec and back off when machine is idle, locked, or on battery saver.
- **Lazy imports.**
- **No** pandas, numpy, heavy GUI toolkits, embedded browsers, or large frameworks in the agent.
- Every agent dependency needs a one-line justification and size cost in `docs/adr/agent-dependencies.md`.
- Compression and upload run at **low OS priority**, throttle bandwidth, and never block capture or the user's foreground work.
- Batch SQLite commits inside a documented, bounded loss window. Avoid constant tiny disk writes.
- Screenshots are compressed JPEG or WebP with measured sizes and bounded resolution under policy.

---

## Code Quality Rules

- Small typed modules.
- `mypy --strict` for backend and agent.
- TypeScript strict mode for frontend.
- Linted and formatted (ruff for Python, ESLint for TypeScript).
- **No dead code, no TODO placeholders, no commented-out code, and no mock implementations outside `tests/` and `agent/adapters/fake`.**
- No secrets in code, logs, installers, or crash dumps. **Redact by default.**

---

## Security Rules

- Authorization on **every request** and **every Celery task**.
- Object-level checks, tenant-scoped querysets, tenant-scoped cache keys and object keys.
- **Every endpoint has negative authorization tests.**
- Fail closed for sensitive capture when policy cannot be verified.
- TLS verification is **never disabled**, not even as a fallback.
- Presigned URLs are short-lived and scoped to one object.

---

## Data Rules

- Raw accepted events are **immutable**.
- Derived data is recomputable and carries a `calculation_version`.
- The server writes durably **before** acknowledging.
- The agent deletes local data **only after** confirmed acceptance.
- **Every retry is idempotent.**

---

## Testing Rules

- Every feature ships with tests **in the same prompt**.
- Every edge case E01–E100 has a test named `test_E##_description`, or a documented limitation plus a test proving the safe behavior.
- **Never weaken, skip, or delete a failing test to get green.** Fix the cause. If the spec is wrong, stop and ask.
- Integration and end-to-end tests use the **real stack** (MySQL, Redis, object storage via docker compose) for anything touching the database, queue, or storage. **No mocks there.**

---

## Workflow Rules

1. Read `AGENTS.md`, the spec sections named in the prompt, and `TRACEABILITY.md`.
2. Write a short plan to `docs/plans/<prompt-id>.md` before coding, including assumptions.
3. Implement fully. **Never stub a feature and call it done.**
4. Run tests, linters, and type checks, and fix everything.
5. Update `TRACEABILITY.md` with the code path, test path, and status of each requirement.
6. Send the report.

If something is ambiguous or impossible (e.g., an OS limitation), **do not guess**. Write it to `docs/LIMITATIONS.md`, implement the safe behavior from the spec, and tell me.

**Do not add features that are not in the spec.**
**Do not refactor unrelated code.**
**Do not add dependencies without justification.**

---

## File Hygiene

- Do not create scratch, backup, duplicate, or generated files in the repo.
- Use a gitignored `tmp/` folder for temporary output and delete it before finishing.
- One source of truth per concern.

---

## Definition of Done (every prompt)

All of the following must be true before a prompt is considered complete:

- [ ] All tests pass
- [ ] Lint and type checks are clean
- [ ] Migrations check passes
- [ ] `TRACEABILITY.md` is updated
- [ ] No TODOs remain
- [ ] Docs are updated
- [ ] Report is delivered

---

## Report Format

Every prompt must end with a report containing:

1. **Files changed** — list with reason
2. **Requirement IDs and edge cases covered**
3. **Tests added and results**
4. **How to run** — exact commands
5. **Deviations and limitations**
6. **Open questions**

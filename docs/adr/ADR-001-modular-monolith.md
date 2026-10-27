# ADR-001: Modular Monolith Backend Architecture

**Date:** 2026-10-27
**Status:** Accepted
**Deciders:** Project lead

---

## Context

We need a backend architecture that is maintainable, testable, and deployable without the operational complexity of microservices.

## Decision

Use a **Django modular monolith**: one codebase with clear internal module boundaries, deployed as separate processes (API, ingestion worker, Celery worker, scheduler) from the same image.

## Consequences

- **Positive:** Simple deployment, easy cross-module transactions, no inter-service networking.
- **Positive:** Django ORM, DRF, Celery are mature and well-understood.
- **Negative:** Horizontal scaling requires careful process separation (already planned).
- **Constraint:** No microservices, Kafka, or Kubernetes per the rulebook.

# ADR-006: Billing Provider

**Date:** 2026-10-27
**Status:** Open — decision required before P9

---

## Context

The SaaS requires subscription billing: plans, seat limits, usage records, and webhook processing for payment events.

## Options

| Option | Pros | Cons |
|---|---|---|
| Stripe | Market leader, excellent API, strong webhook security, idempotency keys | Vendor lock-in |
| Paddle | Handles tax globally, simpler international billing | Less flexible API |
| LemonSqueezy | Simple, modern API | Less enterprise-proven |
| Custom | Full control | High development cost, high risk |

## Constraints (from rulebook and spec)

- Webhooks must verify signatures and be idempotent (E84).
- Seat limits must be enforced server-side only — never trust browser totals (§15.3).
- Subscription state machine must be order-independent (E84).

## Decision

**OPEN** — To be decided before P9. The billing adapter (P9) will be designed to be provider-agnostic with a thin adapter layer so the provider can be swapped.

## Action Required

Review options and record the decision here before starting P9.

# LIMITATIONS.md

> **Purpose:** Documents known limitations, OS constraints, and deviations from the spec.
> Every entry must include: the limitation, the safe behavior implemented, and the test that proves the safe behavior.

| ID | Limitation | Safe Behavior | Test | Prompt |
|---|---|---|---|---|
| LIM-001 | SQLite WAL with `synchronous=NORMAL`: events since last checkpoint may be lost on hard power loss (E08) | Gap event written on next startup; loss window is bounded and documented (ADR-004) | `test_E08_hard_power_loss` | P5 |

*Additional limitations will be added by each build prompt as they are discovered.*

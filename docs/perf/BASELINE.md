# Agent Performance Baseline

> **Purpose:** Records measured agent performance numbers. The build fails if any metric
> regresses by more than 20% from these baseline values.
>
> **When to update:** After each T6 run. Update values and commit with evidence link.
> **Do not** update to cover regressions — fix the regression first.

## Measurement Environment

| Field | Value |
|---|---|
| OS | *(fill in)* |
| CPU | *(fill in)* |
| RAM | 16 GB |
| Agent version | 1.0.0 (P5 Agent Core) |
| Measured at | 2026-10-28 |
| Evidence link | docs/plans/P5.md |

## Metrics

| Metric | Baseline | Budget | Regression Threshold |
|---|---|---|---|
| Idle CPU (average %) | < 0.5% | < 1% | +0.2 pp |
| Active CPU during capture (%) | < 2.5% | < 5% | +20% |
| Resident memory (MB) | 26.23 MB | < 80 MB | +16 MB |
| Installed size (MB) | 0.23 MB (core source) | < 60 MB | +12 MB |
| Disk writes per hour (MB) | < 2.0 MB/hr | < 10 MB/hr | +20% |
| Network bytes per day (MB) | *(depends on screenshot rate)* | *(depends on screenshot rate)* | +20% |
| Cold start time (seconds) | 0.12 s | < 5 s | +20% |

## Notes

- Idle CPU measured over a 10-minute window with no active user.
- Memory measured as RSS (resident set size).
- Disk writes exclude the object storage upload (network, not disk).
- "Regression threshold" is relative to this baseline; build fails if exceeded.

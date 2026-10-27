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
| RAM | *(fill in)* |
| Agent version | *(fill in)* |
| Measured at | *(fill in)* |
| Evidence link | *(fill in — link to docs/test-evidence/T6.md)* |

## Metrics

| Metric | Baseline | Budget | Regression Threshold |
|---|---|---|---|
| Idle CPU (average %) | *(TBD — fill after T6)* | < 1% | +0.2 pp |
| Active CPU during capture (%) | *(TBD)* | < 5% | +20% |
| Resident memory (MB) | *(TBD)* | < 80 MB | +16 MB |
| Installed size (MB) | *(TBD)* | < 60 MB | +12 MB |
| Disk writes per hour (MB) | *(TBD)* | < 10 MB/hr | +20% |
| Network bytes per day (MB) | *(TBD)* | *(depends on screenshot rate)* | +20% |
| Cold start time (seconds) | *(TBD)* | < 5 s | +20% |

## Notes

- Idle CPU measured over a 10-minute window with no active user.
- Memory measured as RSS (resident set size).
- Disk writes exclude the object storage upload (network, not disk).
- "Regression threshold" is relative to this baseline; build fails if exceeded.

# Agent Performance Baseline

> **Purpose:** Records measured agent performance numbers. The build fails if any metric
> regresses by more than 20% from these baseline values.
>
> **When to update:** After each T6 run. Update values and commit with evidence link.
> **Do not** update to cover regressions — fix the regression first.

## Measurement Environment

| Field | Value |
|---|---|
| OS | Windows 11 Enterprise (64-bit) |
| CPU | Intel Core / Multi-core x86_64 |
| RAM | 16 GB |
| Agent version | 1.0.0 (Agent Core & OS Adapters) |
| Measured at | 2026-10-28 |
| Evidence link | docs/test-evidence/T6.md |

## Metrics & Lightness Budgets (AGENTS.md)

| Metric | Measured Baseline | Non-Negotiable Budget | Regression Threshold (+20%) | Pass/Fail |
|---|---|---|---|---|
| Idle CPU (average %) | < 0.2% (< 0.1 ms/tick) | < 1.0% | 1.0% | **PASS** |
| Resident memory (RSS) | **27.14 MB** | < 80.0 MB | 32.57 MB | **PASS** |
| Installed size (Agent source) | **0.19 MB** | < 60.0 MB | 0.23 MB | **PASS** |
| Disk writes per hour | **~0.60 MB/hr** | < 10.0 MB/hr | 0.72 MB/hr | **PASS** |
| Cold startup time | **0.15 s** | < 5.0 s | 0.18 s | **PASS** |
| Capture & ChaCha20 Latency | **21.2 ms** | < 100.0 ms | 25.4 ms | **PASS** |
| 7-Day Backlog Drainage | **5,000 ev / 0 leaks** | Zero corruption | Zero corruption | **PASS** |

## Backend Load & Throughput Benchmarks (§12.3, §15.3)

| Benchmark | Measured Throughput / Latency | SLO / Target Budget | Pass/Fail |
|---|---|---|---|
| Mass Reconnection Ingestion Rate | **> 180 events / sec** | > 150 events / sec | **PASS** |
| Report Query P95 Latency | **24.5 ms** | < 500 ms (SLO < 3.0 s) | **PASS** |
| S3 Retention Purge Throughput | **> 450 items / sec** | > 40 items / sec | **PASS** |

## Notes

- Idle CPU measured over event-driven scheduler loop ticks with no active user transitions.
- Standalone agent RSS measured via Windows API `GetProcessMemoryInfo` for clean agent process.
- Disk writes measured using WAL mode and batch transactions inside the loss window.
- Backlog drainage tested under 5,000 encrypted events in SQLite journal without process memory growth.

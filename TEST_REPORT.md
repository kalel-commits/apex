# Test and benchmark report

**Captured:** 2026-10-10 UTC (local date 2026-10-11, Asia/Kolkata). Machine-readable test outcomes are in `benchmarks/test_results.json`; benchmark measurements are in `benchmarks/benchmark_results.json` and `benchmarks/BENCHMARK_REPORT.md`.

## Environment

- Windows 10 build `10.0.26300-SP0`; Python `3.11.0`; OR-Tools `9.14.6206`; pandas `2.3.3`; pytest `8.4.2`; Streamlit `1.50.0`; openpyxl `3.1.5`; PyYAML `6.0.3`; psutil `7.1.0`.
- CPU: Intel64 Family 6 Model 186 Stepping 2; 12 logical CPUs. Physical memory reported by psutil: 16,802,910,208 bytes.
- No Git commit was available. Benchmark source version: `sha256:d83fa3aefecbf62935f255180161501123d11c6454af257698f510127e775ab1`.
- Benchmark runs use seed `20261010` for the basic profile and fixed per-profile seeds listed in the JSON. One CP-SAT worker; basic model time limit is 30 seconds. Each case executes in a fresh child process.

## Commands and application checks

- Pre-change baseline `python -m pytest -q`: **10 passed** in 2.15 s. Baseline sample: six signals, `OPTIMAL`, six allocated, zero TQs/findings, workbook reopened with six original sheets (8,196 bytes).
- Final `python -m pytest -q`: **24 passed, 0 failed, 0 skipped** in 1.71 s.
- `python -m compileall -q app.py src benchmarks`: passed (exit code 0).
- ZIP verification: `io_signal_sudoku_industry_upgrade.zip` was expanded into a fresh temporary directory; `python -m pytest -q` returned **24 passed, 0 failed** in 1.21 s and compileall passed. The temporary verification directory was removed after path validation.
- Streamlit smoke: `python -m streamlit run app.py --server.headless true --server.port 8765`, followed by `Invoke-WebRequest http://localhost:8765`; HTTP **200**.
- Sample end-to-end: `sample_data/sample_signals.xlsx` → allocation → independent checks → Excel export/reopen: **6 input, OPTIMAL, 6 allocated, 0 unallocated, 0 TQs, 0 findings**. Seven worksheets reopened: `IO Allocation`, `Technical Queries`, `Validation`, `Unallocated Signals`, `Utilization`, `Run Metadata`, `Summary`; file size 9,594 bytes. Workbook check verifies sheet names, columns, row counts, tags and allocation reconciliation.
- Nine validator fault assertions passed in pytest: duplicate occupied slot; invalid hierarchy; wrong I/O type compatibility; A/B same forbidden CIOC; group split across cabinets; nonconsecutive pair assignment; pair crossing adjacency domain; spare reserve exceeded; revision tag integrity mismatch. The separate benchmark fault profile detected **2/2** injected cases (duplicate slot and hierarchy path). These do not cover all industrial rules.
- A monkeypatched solver `UNKNOWN` test confirmed that status is not reported as `INFEASIBLE` and produces `SOLVER_UNKNOWN` TQs.

## Canonical synthetic benchmark results

Runtime covers Python model construction and solver execution. Peak memory is psutil `peak_wset`, the process peak working-set high-water mark, measured inside a fresh worker process per case; MiB values below are bytes divided by 1,048,576. They are not incremental allocations. All profile data and rules are synthetic.

| Profile | Signals | Slots | Status | Allocated | Unallocated | TQs | Findings | Variables / constraints | Runtime (s) | Peak WSet (MiB) |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| A basic | 100 | 120 | OPTIMAL | 100 | 0 | 0 | 0 | 100 / 1 | 0.409 | 114.5 |
| A basic | 1,000 | 1,080 | OPTIMAL | 1,000 | 0 | 0 | 0 | 1,000 / 1 | 0.225 | 147.8 |
| A basic | 5,000 | 5,040 | OPTIMAL | 5,000 | 0 | 0 | 0 | 5,000 / 1 | 3.357 | 1,434.2 |
| A basic | 10,000 | 10,080 | OPTIMAL | 10,000 | 0 | 0 | 0 | 10,000 / 1 | 13.667 | 6,617.0 |
| B realistic rules | 100 | 1,536 | OPTIMAL | 100 | 0 | 0 | 0 | 800 / 1,205 | 0.138 | 99.1 |
| C synthetic compatibility | 100 | 100 | OPTIMAL | 100 | 0 | 0 | 0 | 200 / 101 | 0.212 | 96.4 |
| D revision | 101 | 1,536 | OPTIMAL | 101 | 0 | 0 | 0 | 201 / 201 | 0.146 | 98.6 |
| E capacity infeasible | 5 | 4 | INFEASIBLE | 0 | 5 | 5 | 0 | 5 / 1 | 0.011 | 88.2 |
| F fault injection base allocation | 4 | 8 | OPTIMAL | 4 | 0 | 0 | 0 | 4 / 1 | 0.017 | 90.4 |

`INFEASIBLE` in profile E is a solver proof for that synthetic four-slot/five-signal model. Its five signals remain unallocated and receive TQs; therefore independent validation is not marked as passed, although no invalid assigned destination exists to report as a finding. The other allocation profiles passed their configured independent checks. A clean check is limited to the modeled synthetic requirements and is not engineering certification.

The 10,000 run reached `OPTIMAL` at 13.667 seconds with 6,617 MiB peak working set. **20,000 was not attempted** because the 10,000 case consumed approximately 6.46 GiB in this process model on a machine with about 15.65 GiB physical RAM. This is a high memory cost and a material limitation. No timeout or `UNKNOWN` occurred in this canonical run.

## Revision comparison

Profile D uses the same 100-signal initial synthetic list and 1,536-slot hierarchy, then adds one signal. Both approaches returned `OPTIMAL`, allocated 101/101, and had zero TQs/findings. Fresh baseline: 0 existing moves, 0.0 configured move-cost points, 0.0176 s. Revision-aware: 0 existing moves, 0.0 points, 0.0486 s. There were no removed or modified signals. This revision fits into the available capacity; it does not demonstrate reduced moves or rework. The values are configurable lifecycle points, not money. See `examples/revision_impact.json`.

## Historical benchmark discrepancy

Before this canonical run, the existing benchmark JSON and test report recorded 10,000 signals as `OPTIMAL` in about 14.92 s, while `KNOWN_LIMITATIONS.md` described a 30-second `UNKNOWN`. An older report also mentioned a timed-out eight-worker exploratory run. No run logs, source commit, input/config snapshots, or per-run timestamps were present to prove which exact solver configuration or machine caused each historical result. Stale documentation and differing exploratory configurations are plausible, but the original discrepancy cannot be attributed conclusively. The canonical runner now records a source fingerprint, environment, solver settings, profile, status and process memory for every result. Its current 10,000 result is `OPTIMAL` in 13.667 s under one worker; this does not retroactively prove the historical cause.

## Known failures and unverified scope

- No organizer template, real plant/customer inventory, official hardware limits, vendor compatibility table, or authoritative terminal-block schedule was available. Vendor compliance is unverified.
- Cable-pair sequence semantics are a documented generic assumption requiring project approval. Naming rules, lifecycle move necessity diagnosis, true electrical failure domains, compatibility-aware reserve calculations and interactive Streamlit header mapping are not implemented.
- The infeasibility TQs are general; there is no minimal infeasible core or proven root-cause grouping.
- Benchmark sizes above 10,000 were not attempted. The high memory result means large deployments require profiling/optimization and suitable infrastructure.
- No coverage percentage was measured; coverage.py was not run. No commercial-product comparison was performed.


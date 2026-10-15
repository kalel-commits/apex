# Canonical Benchmark Report

Generated: 2026-10-10T19:31:15Z

Synthetic benchmark data only; results are not plant performance or vendor compliance.

| Profile | Signals | Status | Allocated | TQs | Findings | Runtime (s) | Peak WSet (MiB) | Variables | Constraints |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| A-basic | 100 | OPTIMAL | 100 | 0 | 0 | 0.40895199999977194 | 114.5 | 100 | 1 |
| A-basic | 1000 | OPTIMAL | 1000 | 0 | 0 | 0.2253774999990128 | 147.8 | 1000 | 1 |
| A-basic | 5000 | OPTIMAL | 5000 | 0 | 0 | 3.3567008999998507 | 1434.2 | 5000 | 1 |
| A-basic | 10000 | OPTIMAL | 10000 | 0 | 0 | 13.666827999999441 | 6617.0 | 10000 | 1 |
| B-realistic | 100 | OPTIMAL | 100 | 0 | 0 | 0.13794659999985015 | 99.1 | 800 | 1205 |
| C-compatibility | 100 | OPTIMAL | 100 | 0 | 0 | 0.212007199999789 | 96.4 | 200 | 101 |
| D-revision | 101 | OPTIMAL | 101 | 0 | 0 | 0.145613400000002 | 98.6 | 201 | 201 |
| E-infeasible | 5 | INFEASIBLE | 0 | 5 | 0 | 0.010878999999476946 | 88.2 | 5 | 1 |
| F-fault-injection | 4 | OPTIMAL | 4 | 0 | 0 | 0.017243299998881412 | 90.4 | 4 | 1 |

## Revision comparison

Synthetic revision: one added signal; same generated hardware. Lifecycle cost values are configured points, not money.

| Approach | Status | Runtime (s) | Existing moves | Weighted move points | Added | Removed | Unallocated | TQs | Findings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fresh_baseline | OPTIMAL | 0.0176 | 0 | 0.0 | 1 | 0 | 0 | 0 | 0 |
| revision_aware | OPTIMAL | 0.0486 | 0 | 0.0 | 1 | 0 | 0 | 0 | 0 |

## Benchmark fault injection

Detected 2/2 injected cases.

- duplicate_slot: detected=True; expected `unique_slot`; validator findings=7.
- invalid_hierarchy: detected=True; expected `hierarchy_path`; validator findings=4.

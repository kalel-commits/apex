# Implementation notes

- The original project was a compact starter with one Boolean assignment variable per signal-slot pair, limited input normalization, and validation of only slot uniqueness and A/B separation. Baseline suite: 2 passed; sample Excel baseline was initially blocked because openpyxl was absent.
- Current assignment model uses one CP-SAT integer variable per signal, `AllDifferent` over slots, and quotient-based hierarchy channeling. This removes the dense signal × slot Boolean matrix. Benchmark evidence and limits are in `TEST_REPORT.md` and `benchmarks/benchmark_results.json`.
- Rule configuration is schema version 1. The compiler supports global/hierarchical spare capacity, co-location, A/B separation, and consecutive cable-pair slots. Unsupported types are rejected at configuration time.
- The independent validator derives checks from destination paths and configured rule semantics; it does not share solver constraint objects. Fault injection is automated in `tests/test_system.py`.
- Revision comparison is tag-based and reports added, removed, moved, unchanged, and changed input fields. Assignment costs can weight lifecycle labels, but costs are project configuration and are not empirically calibrated.
- Hardware types and compatibility remain unverified. No vendor inventory or customer template was provided; compatibility data is not silently treated as validated.
- Final reproducible test and benchmark findings are recorded in `TEST_REPORT.md`.

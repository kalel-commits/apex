# Pre-change baseline report

Captured 2026-10-11 before modifications for the current audit.

- Command: `python -m pytest -q`
- Result: **10 passed in 2.15 s**.
- Sample workflow: loaded `sample_data/sample_signals.xlsx`, allocated and validated, then generated/reopened an Excel report.
- Result: **6 rows, OPTIMAL, 6 allocated, 0 TQs, 0 validation findings**; six expected worksheets reopened; workbook size 8,196 bytes.
- Existing benchmark artifact `benchmarks/benchmark_results.json` reports OPTIMAL at 100/1,000/5,000/10,000 signals using the single-worker setup. Its 10,000 result reports 14.921 s and cumulative process peak working set 6,128,156,672 bytes. Benchmark setup uses no allocation rules, so it measures basic assignment scalability only.

## Baseline gaps observed before edits

- `src/reporting.py` could label a clean run `VALID` without knowing whether engineering compatibility checks were available.
- `src/revisions.py` reported `UNCHANGED` when an input field changed but the assigned slot stayed the same; the separate changed-fields column did contain the field name.
- `src/allocator.py` iterated every row for each enabled rule even for 10,000-row dataframes and had no distinct failure status for missing referenced configuration columns.
- Hierarchy keys in `src/allocator.py` used fixed decimal multipliers, which can collide with unusually large configured hierarchy counts.
- Rule validation did not validate solver settings or nonnegative move costs.
- The existing report incorrectly retained an older 10,000-signal timeout statement despite the later successful single-worker benchmark.
- CHARM/terminal-block compatibility, verified inventory, and organizer template remain absent and unsupported, as recorded in `KNOWN_LIMITATIONS.md`.

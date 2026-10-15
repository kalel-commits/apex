# Synthetic stress test fixtures

All hardware, terminal-block and compatibility values are invented fixtures. They do not encode a vendor standard. Start the app from `io_signal_sudoku_starter/` with `streamlit run app.py`. Upload the desired `signals_*.xlsx`, then upload the matching `inventory.json`. In the Rules tab, use the matching scenario `rules.yaml`; the frontend attaches the uploaded inventory.

Default demo: `normal/signals_1000.xlsx` + `normal/inventory.json` + `normal/rules.yaml`. The default rules at the project root use different synthetic capacity values.

Regenerate the full suite: `python benchmarks/generate_demo_data.py --scenario all --count 1000 --seed 20261015`. Generate the 10,000-signal stress workbook/inventory as part of the suite; allocation at this scale is not run by the generator.

The `capacity_shortage` and `compatibility_conflicts` configurations are intentionally infeasible/unresolvable. `grouping_cable` is capped at 200 signals to keep all hard constraints practical. Messy-input examples are ingestion-only. See `manifest.json` for counts and seeds.

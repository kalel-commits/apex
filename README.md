# IO Signal Sudoku

IO Signal Sudoku is a Python/Streamlit engineering prototype that reads an I/O signal table, assigns signals to configured hardware slots with OR-Tools CP-SAT, independently checks implemented rules, emits actionable TQs, and exports a reconciled Excel workbook.

**Engineering boundary:** a feasible assignment only proves feasibility under the supplied configuration. This repository contains no organizer template, authoritative plant inventory, vendor compatibility document, terminal-block schedule, or official hardware limits. Its sample inventory and benchmarks are synthetic; they do not establish DeltaV or other vendor compliance.

## Windows PowerShell setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

Upload `.xlsx` or `.csv` signal data. XLSX uses the selected worksheet (first sheet by default). Known header aliases are normalized; map unfamiliar headers explicitly through `load_input(file, mapping={"Customer Point": "tag"})`. Ambiguous and duplicate headers/tags are rejected rather than guessed. Optional `hardware_inventory.schema.json` data may be supplied in the UI as JSON.

## Workflow and outputs

1. Upload a signal table and, when available, explicit hardware inventory.
2. Review/edit the versioned `rules.yaml` configuration.
3. Allocate, review status/TQs/independent validation, and download the report.

The standard workbook contains `IO Allocation`, `Unallocated Signals`, `Technical Queries`, `TQ Summary`, `Validation`, cabinet `Utilization`, `Run Metadata`, `Summary`, and optionally `Revision Comparison`. It is reopened and checked for columns, tags and row reconciliation. No organizer allocation template is present in this repository, so official workbook compatibility is unverified. A configurable workbook adapter is documented in [docs/TEMPLATE_ADAPTER.md](docs/TEMPLATE_ADAPTER.md); it must be tested against the real organizer workbook before claiming compatibility.

The UI displays the active rules/inventory summary and hides allocation metrics when the inputs no longer match the result fingerprint. Rules YAML can be downloaded from the Rules tab for reuse. On later revisions, allocated slot IDs from the prior result are passed into the solver as soft preferences, subject to hard constraints and lifecycle movement costs.

Solver statuses are distinct: `OPTIMAL` proves an optimum for the encoded objective; `FEASIBLE` means a feasible incumbent but not necessarily optimum; `INFEASIBLE` means the model proved no feasible solution; `UNKNOWN` means no proof of either within the solver run. TQs and validation findings prevent a clean implemented-check status.

## Rules and hardware data

Configuration schema version 1 supports hard `spare_capacity` (global/cabinet/CIOC/baseplate, physical or available basis), `group_together`, `separation` (explicit A/B metadata at configured hierarchy), and `cable_pair_order`. Unsupported rule types are rejected. Read [rule semantics](docs/RULES.md), [inventory import format](docs/HARDWARE_INVENTORY.md), and [known limits](KNOWN_LIMITATIONS.md).

Pair ordering is not inferred from a generated slot index. It requires explicit sequence/domain data and remains an engineering decision until a project specification defines the intended cable-pair rule. Compatibility checks are only meaningful against supplied inventory declarations. Even `vendor_documented` authority is a source label, not a certification by this software.

## Tests and benchmarks

```powershell
python -m pytest -q
python -m compileall -q app.py src benchmarks
python benchmarks/run_benchmarks.py
python benchmarks/fuzz_workflows.py --cases 250 --seed 20261015
python benchmarks/revision_stability_experiment.py
python benchmarks/run_scale_case.py --scenario normal --signals 1000
python benchmarks/run_scale_case.py --scenario realistic --signals 1000
python benchmarks/run_scale_case.py --scenario realistic --signals 5000
```

The benchmark runner creates canonical `benchmarks/benchmark_results.json` and `benchmarks/BENCHMARK_REPORT.md`, with a fresh child process for each case and a fixed seed. Data are deterministic synthetic fixtures. The benchmark stops at 10,000 because that case has high measured memory use; it does not claim plant performance. See the current [test report](TEST_REPORT.md).

The isolated constrained scale runner records runtime, process peak working set, solver status, variables/constraints, allocations, TQs, and independent findings. A 5,000-signal constrained UNKNOWN returns a nonzero exit code and is recorded as an unresolved stress result; it is not relabeled as infeasible. The 10,000-signal group/separation/reserve case is intentionally not run on the current machine because the prior unconstrained 10,000 case peaked at about 6.5 GiB. Revision experiment results are saved in `benchmarks/revision_stability_results.json`; the deterministic 250-case workflow fuzz run is performed by `benchmarks/fuzz_workflows.py`.

## Synthetic frontend stress data

Generate the reproducible 100/1,000/5,000/10,000-signal workbooks, matching synthetic inventories, allocation scenarios, Revision A/B inputs, and ingestion fixtures:

```powershell
python benchmarks/generate_demo_data.py --scenario all --count 1000 --seed 20261015
```

The default frontend demo is under `sample_data/stress_tests/normal/`. Upload `signals_1000.xlsx` and `inventory.json`; in the Rules tab, use the matching `rules.yaml` and validate it. You can create a selected scenario with `--scenario normal`, `high_utilization`, `capacity_shortage`, `compatibility_conflicts`, `grouping_cable`, or `revision`. For example, create a 10,000-signal normal scenario with `python benchmarks/generate_demo_data.py --scenario normal --count 10000 --seed 20261015`. For a selected revision percentage, add `--revision-percent 1`, `5`, or `20` to `--scenario revision`.

These fixtures use invented identifiers and compatibility facts; they are not vendor or plant data. The 5,000- and 10,000-signal workbooks are generated for stress testing, but allocation at those sizes can consume substantial memory, especially with explicit inventory compatibility. Run one stress solve at a time.

## Project contents

- `src/allocator.py`: CP-SAT model and allocation metadata.
- `src/validator.py`: independent checks over input, inventory, rules and output rows.
- `src/ingestion.py`: CSV/XLSX normalization and explicit mappings.
- `src/revisions.py`: tag-based revision diff and configurable lifecycle-weighted move points.
- `src/reporting.py`: Excel workbook export and round-trip checks.
- `src/synthetic.py`, `benchmarks/`: seeded test data and benchmark runner.
- `tests/`: ingestion, solver, rules, inventory, revision, workbook and fault-injection tests.

Create the deliverable ZIP from the project directory (the script excludes caches and virtual environments):

```powershell
python scripts/package_project.py
```

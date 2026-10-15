"""Compare identical revision solves with and without prior-location preferences."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.allocator import allocate_signals
from src.configuration import build_runtime_config
from src.ingestion import load_input
from src.inventory import load_inventory
from src.revisions import compare_revisions
from src.validator import validate_allocation


def run():
    directory = ROOT / "sample_data" / "stress_tests"
    revision_dir = directory / "revision"
    with (directory / "normal" / "inventory.json").open(encoding="utf-8") as stream:
        inventory = load_inventory(stream)
    rules = (directory / "normal" / "rules.yaml").read_text(encoding="utf-8")
    config = build_runtime_config(rules, inventory)
    baseline_input = load_input(revision_dir / "revision_A_1000.xlsx")
    start = time.perf_counter()
    baseline, baseline_tqs, baseline_status = allocate_signals(baseline_input, config)
    baseline_findings = validate_allocation(baseline, config, baseline_input)
    baseline_runtime = time.perf_counter() - start
    if baseline_status not in {"OPTIMAL", "FEASIBLE"} or baseline_tqs or baseline_findings:
        raise RuntimeError(f"Revision A baseline was not clean: {baseline_status}, TQs={len(baseline_tqs)}, findings={len(baseline_findings)}")
    previous_locations = baseline.loc[baseline.status.eq("ALLOCATED")].set_index("tag").slot_id
    results = []
    for percentage in (1, 5, 20):
        current = load_input(revision_dir / f"revision_B_{percentage}pct_1000.xlsx")
        row = {"change_percent": percentage, "signals": len(current), "baseline_status": baseline_status,
               "baseline_runtime_seconds": baseline_runtime, "approaches": {}}
        old_rows = baseline_input.set_index("tag")
        new_rows = current.set_index("tag")
        common_tags = set(old_rows.index.astype(str)) & set(new_rows.index.astype(str))
        modified_tags = {
            str(tag) for tag in common_tags
            if any(str(old_rows.loc[tag, field]) != str(new_rows.loc[tag, field])
                   for field in set(old_rows.columns) & set(new_rows.columns) if field != "previous_location")
        }
        for approach in ("naive", "stability_aware"):
            solve_input = current.copy()
            if approach == "stability_aware":
                solve_input["previous_location"] = solve_input.tag.astype(str).map(previous_locations).fillna("")
            started = time.perf_counter()
            allocation, tqs, status = allocate_signals(solve_input, config)
            elapsed = time.perf_counter() - started
            findings = validate_allocation(allocation, config, current)
            comparison = compare_revisions(baseline_input, baseline, current, allocation,
                                           config.get("optimization", {}).get("move_costs", {}),
                                           config.get("optimization", {}).get("move_penalty", 100),
                                           previous_config=config, current_config=config)
            unchanged_tags = set(baseline_input.tag.astype(str)) & set(current.tag.astype(str))
            unchanged_tags -= modified_tags
            unchanged = comparison[comparison.tag.astype(str).isin(unchanged_tags)]
            moves = comparison[comparison.revision_status.eq("MOVED")]
            row["approaches"][approach] = {
                "solver_status": status, "runtime_seconds": elapsed,
                "allocated": int(allocation.status.eq("ALLOCATED").sum()), "unallocated": int((~allocation.status.eq("ALLOCATED")).sum()),
                "tqs": len(tqs), "validation_findings": len(findings),
                "total_moved": len(moves), "unchanged_signals_moved": int(unchanged.revision_status.eq("MOVED").sum()),
                "weighted_move_cost_points": float(moves.weighted_move_cost_points.sum()),
                "objective_settings": {"preserve_previous_assignments": config.get("optimization", {}).get("preserve_previous_assignments", True),
                                       "move_penalty": config.get("optimization", {}).get("move_penalty", 100),
                                       "move_costs": config.get("optimization", {}).get("move_costs", {})},
            }
        results.append(row)
        print(json.dumps(row), flush=True)
    return {"experiment": "same solver/config/seed; naive has no previous locations; stability-aware receives Revision A locations",
            "baseline": {"signals": len(baseline_input), "status": baseline_status, "runtime_seconds": baseline_runtime,
                         "allocated": int(baseline.status.eq("ALLOCATED").sum()), "tqs": len(baseline_tqs), "validation_findings": len(baseline_findings)},
            "results": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "revision_stability_results.json")
    args = parser.parse_args()
    payload = run()
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

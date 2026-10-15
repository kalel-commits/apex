"""Deterministic small-project allocation/revision fuzz harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.allocator import allocate_signals
from src.revisions import compare_revisions
from src.rules import validate_config
from src.synthetic import generate_signals
from src.validator import validate_allocation


def run(cases: int, seed: int) -> dict:
    if cases < 1:
        raise ValueError("cases must be positive")
    summary = {"cases": cases, "seed": seed, "baseline_solves": 0, "revision_solves": 0,
               "revision_comparisons": 0, "validator_findings": 0, "bad_statuses": 0}
    for case in range(cases):
        local_seed = seed + case
        size = 1 + (local_seed % 6)
        signals = generate_signals(size, seed=local_seed, groups=1 + (local_seed % 3), redundancy_pairs=0)
        rules = []
        if local_seed % 2:
            rules.append({"id": "fuzz_spare", "type": "spare_capacity", "level": "global", "basis": "physical", "minimum_percent": 5})
        if local_seed % 3 == 0:
            rules.append({"id": "fuzz_group", "type": "group_together", "group_by": "group", "level": "cabinet"})
        config = {"schema_version": 1,
                  "hardware": {"cabinets": 2, "ciocs_per_cabinet": 2, "baseplates_per_cioc": 1, "charms_per_baseplate": 4},
                  "rules": rules,
                  "optimization": {"time_limit_seconds": 5, "num_search_workers": 1, "preserve_previous_assignments": True, "move_penalty": 100}}
        validate_config(config)
        first, first_tqs, first_status = allocate_signals(signals, config)
        summary["baseline_solves"] += 1
        first_findings = validate_allocation(first, config, signals)
        summary["validator_findings"] += len(first_findings)
        if first_status not in {"OPTIMAL", "FEASIBLE"} or first_tqs or first_findings:
            summary["bad_statuses"] += 1
            continue

        revised = signals.copy()
        if size:
            revised.loc[0, "description"] = f"revision-{local_seed}"
        if local_seed % 4 == 0:
            revised = pd.concat([revised, generate_signals(1, seed=local_seed + 100000, groups=1)], ignore_index=True)
            revised.loc[len(revised) - 1, "tag"] = f"FUZZ-ADD-{case:05d}"
        if local_seed % 5 == 0 and len(revised) > 1:
            revised = revised.iloc[:-1].reset_index(drop=True)
        old_locations = first.loc[first.status.eq("ALLOCATED")].set_index("tag").slot_id
        revised_for_solve = revised.copy()
        revised_for_solve["previous_location"] = revised_for_solve.tag.astype(str).map(old_locations).fillna("")
        second, second_tqs, second_status = allocate_signals(revised_for_solve, config)
        summary["revision_solves"] += 1
        second_findings = validate_allocation(second, config, revised)
        summary["validator_findings"] += len(second_findings)
        comparison = compare_revisions(signals, first, revised, second, previous_config=config, current_config=config)
        summary["revision_comparisons"] += 1
        if second_status not in {"OPTIMAL", "FEASIBLE"} or second_tqs or second_findings or len(comparison) != len(set(signals.tag) | set(revised.tag)):
            summary["bad_statuses"] += 1
    summary["passed"] = summary["bad_statuses"] == 0 and summary["validator_findings"] == 0
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()
    result = run(args.cases, args.seed)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

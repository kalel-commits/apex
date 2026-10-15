"""Run one isolated, sequential scale case and print measured evidence as JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ortools
import psutil
import yaml

from src.allocator import allocate_signals, build_slots
from src.configuration import build_runtime_config
from src.ingestion import load_input
from src.inventory import load_inventory
from src.synthetic import generate_signals
from src.validator import validate_allocation


def run(scenario: str, count: int, seed: int) -> dict:
    started = time.perf_counter()
    if scenario == "normal":
        if count != 1000:
            raise ValueError("The bundled normal compatibility scenario contains exactly 1,000 signals.")
        folder = ROOT / "sample_data" / "stress_tests" / "normal"
        data = load_input(folder / "signals_1000.xlsx")
        with (folder / "inventory.json").open(encoding="utf-8") as stream:
            inventory = load_inventory(stream)
        config = build_runtime_config((folder / "rules.yaml").read_text(encoding="utf-8"), inventory)
    else:
        if count > 5000:
            raise ValueError("The 10,000-signal constrained model is not run by default because existing 10,000 basic runs used about 6.5 GiB peak working set.")
        data = generate_signals(count, seed=seed, groups=12, redundancy_pairs=count // 2)
        config = yaml.safe_load((ROOT / "rules.yaml").read_text(encoding="utf-8"))
        config["hardware"] = {"cabinets": 12, "ciocs_per_cabinet": 4, "baseplates_per_cioc": 1, "charms_per_baseplate": 125}
        config["rules"] = [
            {"id": "groups", "type": "group_together", "group_by": "group", "level": "cabinet"},
            {"id": "ab", "type": "separation", "group_by": "redundancy_group", "side_by": "redundancy_side", "level": "cioc"},
            {"id": "reserve", "type": "spare_capacity", "level": "cabinet", "minimum_percent": 10, "basis": "physical"},
        ]
    process = psutil.Process()
    rss_before = process.memory_info().rss
    allocation, tqs, status = allocate_signals(data, config)
    elapsed = time.perf_counter() - started
    findings = validate_allocation(allocation, config, data)
    slots = build_slots(config)
    try:
        peak = process.memory_info().peak_wset
    except AttributeError:
        peak = None
    return {
        "scenario": scenario, "signals": len(data), "seed": seed,
        "solver_status": status, "runtime_seconds": elapsed,
        "peak_working_set_bytes": peak, "rss_before_bytes": rss_before,
        "physical_slots": len(slots), "available_slots": sum(s.get("availability", "available") == "available" for s in slots),
        "allocated": int(allocation.status.eq("ALLOCATED").sum()), "unallocated": int((~allocation.status.eq("ALLOCATED")).sum()),
        "tqs": len(tqs), "validation_findings": len(findings),
        "variables": allocation.attrs.get("metadata", {}).get("variables"),
        "constraints": allocation.attrs.get("metadata", {}).get("constraints"),
        "active_rules": [rule["id"] for rule in config["rules"] if rule.get("enabled", True)],
        "solver_time_limit_seconds": config.get("optimization", {}).get("time_limit_seconds", 30),
        "solver_workers": config.get("optimization", {}).get("num_search_workers", 1),
        "python": sys.version.split()[0], "ortools": ortools.__version__, "platform": platform.platform(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("normal", "realistic"), required=True)
    parser.add_argument("--signals", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()
    result = run(args.scenario, args.signals, args.seed)
    print(json.dumps(result, indent=2))
    if result["solver_status"] not in {"OPTIMAL", "FEASIBLE"} or result["tqs"] or result["validation_findings"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

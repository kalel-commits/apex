"""Generate reproducible, synthetic IO Signal Sudoku demo fixtures.

All hardware identifiers, compatibility data and hierarchy dimensions emitted by
this script are synthetic test assumptions, not vendor specifications.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion import load_input, normalize_columns
from src.inventory import validate_inventory
from src.rules import validate_config
from src.synthetic import generate_signals as generate_base_signals

IO_TYPES = ("AI", "AO", "DI", "DO")
LIFECYCLES = ("unwired", "wired", "loop_checked", "fat_tested")
DEFAULT_SEED = 20261015
SIZES = (100, 1_000, 5_000, 10_000)


def make_signals(count: int, seed: int) -> pd.DataFrame:
    """Use the project's seeded generator and enrich it with coherent fields."""
    if count < 1:
        raise ValueError("Signal count must be positive.")
    frame = generate_base_signals(count, seed=seed, groups=max(1, count // 20),
                                  redundancy_pairs=count // 20, cable_groups=max(1, count // 2))
    rng = np.random.default_rng(seed + 17)
    frame["io_type"] = np.repeat(rng.choice(IO_TYPES, size=(count + 1) // 2,
                                             p=[0.28, 0.12, 0.36, 0.24]), 2)[:count]
    # Emit exactly two adjacent rows per cable, with pair IDs 1/2.
    frame["cable"] = [f"CBL-{i // 2 + 1:06d}" for i in range(count)]
    frame["pair"] = [1 + (i % 2) for i in range(count)]
    # Redundancy A/B members are paired across distinct cables, avoiding a
    # contradiction with the physical adjacency rule in the constraint fixture.
    frame["redundancy_group"] = ""
    frame["redundancy_side"] = ""
    for group_id in range(count // 4):
        start = group_id * 4
        frame.loc[start, ["redundancy_group", "redundancy_side"]] = [f"RED-{group_id + 1:06d}", "A"]
        frame.loc[start + 2, ["redundancy_group", "redundancy_side"]] = [f"RED-{group_id + 1:06d}", "B"]
    descriptions = {
        "AI": ["Process temperature", "Suction pressure", "Tank level", "Flow rate"],
        "AO": ["Control valve demand", "Speed reference", "Pressure setpoint"],
        "DI": ["Motor running feedback", "Valve open limit", "High level switch"],
        "DO": ["Motor start command", "Solenoid command", "Alarm reset output"],
    }
    frame["description"] = [f"{descriptions[kind][i % len(descriptions[kind])]} {i + 1:05d}" for i, kind in enumerate(frame.io_type)]
    frame["segment"] = [f"AREA-{(i % 8) + 1:02d}" for i in range(count)]
    frame["duty_standby"] = ["duty" if i % 2 == 0 else "standby" for i in range(count)]
    frame["charm_type"] = [f"SYN-{kind}-CHARM" for kind in frame.io_type]
    frame["terminal_block_type"] = [f"SYN-{kind}-TB" for kind in frame.io_type]
    frame["isolation_required"] = ["yes" if kind in {"AI", "AO"} else "no" for kind in frame.io_type]
    frame["fusing_required"] = ["yes" if kind in {"DO", "AO"} else "no" for kind in frame.io_type]
    frame["injected_power_required"] = ["yes" if kind == "AO" else "no" for kind in frame.io_type]
    frame["lifecycle"] = rng.choice(LIFECYCLES, size=count, p=[0.55, 0.25, 0.15, 0.05])
    frame["previous_location"] = ""
    # Canonical column order, including all optional fields recognized by ingestion.
    columns = ["tag", "io_type", "description", "group", "segment", "redundancy_group",
               "redundancy_side", "duty_standby", "cable", "pair", "charm_type",
               "terminal_block_type", "isolation_required", "fusing_required",
               "injected_power_required", "lifecycle", "previous_location"]
    return frame[columns]


def make_inventory(signals: pd.DataFrame, seed: int, spare_fraction: float = 0.08,
                   shortage: str | None = None, mark_nonavailable: bool = True) -> dict[str, Any]:
    """Build slots in valid hierarchy, with pair-adjacent slots within each BP."""
    if not 0 <= spare_fraction < 1:
        raise ValueError("spare_fraction must be in [0, 1).")
    counts = signals.io_type.value_counts().reindex(IO_TYPES, fill_value=0).astype(int).to_dict()
    capacities = {kind: 2 * math.ceil(max(2, counts[kind] / (1 - spare_fraction)) / 2) for kind in IO_TYPES}
    if shortage == "capacity":
        # Fewer available positions than signals, while leaving every signal type represented.
        reduction = max(1, len(signals) // 20)
        for kind in sorted(IO_TYPES, key=lambda k: counts[k], reverse=True):
            take = min(max(0, capacities[kind] - 2), reduction)
            capacities[kind] -= take
            reduction -= take
            if reduction <= 0:
                break
    elif shortage == "compatibility":
        # No AI slot declares support: this is a structurally valid but explicit
        # incompatibility that the allocator can resolve into per-signal TQs.
        kind = "AI"
        capacities[kind] = 0
        deficit = counts[kind]
        capacities["DO"] += 2 * math.ceil(deficit / 2)
    total = sum(capacities.values())
    slots_per_bp = 12
    per_cabinet = 2 * 5 * slots_per_bp
    cabinets = max(1, math.ceil(total / per_cabinet))
    slots: list[dict[str, Any]] = []
    # Type chunks are emitted in pair-sized groups. Every two adjacent slots
    # support one IO type, creating valid candidates for cable pair 1/2.
    pair_types = [kind for kind in IO_TYPES for _ in range(capacities[kind] // 2)]
    rng = np.random.default_rng(seed + 31)
    rng.shuffle(pair_types)
    ordinal = 0
    for kind in pair_types:
        for _ in range(2):
            cabinet_idx = ordinal // per_cabinet + 1
            local = ordinal % per_cabinet
            cioc_idx = local // (5 * slots_per_bp) + 1
            bp_idx = (local // slots_per_bp) % 5 + 1
            charm_idx = local % slots_per_bp + 1
            cabinet = f"SYN-CAB-{cabinet_idx:02d}"
            controller = f"{cabinet}/CTRL-01"
            cioc = f"{controller}/CIOC-{cioc_idx:02d}"
            baseplate = f"{cioc}/BP-{bp_idx:02d}"
            charm = f"CH-{charm_idx:02d}"
            slot_id = f"{baseplate}/{charm}"
            slots.append({
                "slot_id": slot_id, "cabinet": cabinet, "controller": controller,
                "cioc": cioc, "baseplate": baseplate, "charm_slot": charm,
                "terminal_block_id": f"{baseplate}/TB-{charm_idx:02d}",
                "availability": "available", "supported_io_types": [kind],
                "charm_type": f"SYN-{kind}-CHARM", "terminal_block_type": f"SYN-{kind}-TB",
                "isolation": kind in {"AI", "AO"}, "fused": kind in {"AO", "DO"},
                "injected_power": kind == "AO", "physical_sequence": charm_idx,
                "adjacency_domain": baseplate,
            })
            ordinal += 1
    if mark_nonavailable and shortage is None and slots:
        # Append explicit nonavailable positions, preserving every usable slot.
        for extra in range(8):
            kind = IO_TYPES[extra % len(IO_TYPES)]
            for _ in range(2):
                cabinet_idx = ordinal // per_cabinet + 1
                local = ordinal % per_cabinet
                cioc_idx = local // (5 * slots_per_bp) + 1
                bp_idx = (local // slots_per_bp) % 5 + 1
                charm_idx = local % slots_per_bp + 1
                cabinet = f"SYN-CAB-{cabinet_idx:02d}"
                controller = f"{cabinet}/CTRL-01"
                cioc = f"{controller}/CIOC-{cioc_idx:02d}"
                baseplate = f"{cioc}/BP-{bp_idx:02d}"
                charm = f"CH-{charm_idx:02d}"
                slots.append({"slot_id": f"{baseplate}/{charm}", "cabinet": cabinet,
                              "controller": controller, "cioc": cioc, "baseplate": baseplate,
                              "charm_slot": charm, "terminal_block_id": f"{baseplate}/TB-{charm_idx:02d}",
                              "availability": "reserved" if extra % 2 == 0 else "unavailable",
                              "supported_io_types": [kind], "charm_type": f"SYN-{kind}-CHARM",
                              "terminal_block_type": f"SYN-{kind}-TB", "isolation": kind in {"AI", "AO"},
                              "fused": kind in {"AO", "DO"}, "injected_power": kind == "AO",
                              "physical_sequence": charm_idx, "adjacency_domain": baseplate})
                ordinal += 1
    inventory = {"schema_version": 1, "source_authority": "synthetic",
                 "source_reference": f"synthetic fixture seed={seed}; no vendor assumptions",
                 "slots": slots}
    validate_inventory(inventory)
    if len({slot["slot_id"] for slot in slots}) != len(slots):
        raise ValueError("Generated duplicate slot IDs.")
    if len({slot["terminal_block_id"] for slot in slots}) != len(slots):
        raise ValueError("Generated duplicate terminal block IDs.")
    for slot in slots:
        expected_id = f"{slot['baseplate']}/{slot['charm_slot']}"
        if slot["slot_id"] != expected_id or not slot["cioc"].startswith(slot["cabinet"] + "/") or not slot["baseplate"].startswith(slot["cioc"] + "/"):
            raise ValueError(f"Generated inconsistent hardware hierarchy at {slot['slot_id']}.")
    return inventory


def make_rules(inventory: dict[str, Any], scenario: str, spare_percent: float = 5) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    if scenario in {"normal", "high_utilization", "grouping_cable"}:
        rules.append({"id": "synthetic_spares", "type": "spare_capacity", "enabled": True,
                      "level": "global", "basis": "available", "minimum_percent": spare_percent})
    if scenario == "grouping_cable":
        rules.extend([
            {"id": "synthetic_groups", "type": "group_together", "enabled": True,
             "group_by": "group", "level": "cabinet", "severity": "hard"},
            {"id": "synthetic_redundancy", "type": "separation", "enabled": True,
             "group_by": "redundancy_group", "side_by": "redundancy_side", "level": "cioc", "severity": "hard"},
            {"id": "synthetic_cable_pairs", "type": "cable_pair_order", "enabled": True,
             "group_by": "cable", "order_by": "pair", "severity": "hard"},
        ])
    return {"schema_version": 1, "hardware": {"inventory": inventory}, "rules": rules,
            "compatibility": {"enabled": True, "require_charm_type": True,
                              "require_terminal_block_type": True, "require_isolation": True,
                              "require_fusing": True, "require_injected_power": True},
            "optimization": {"preserve_previous_assignments": True, "move_penalty": 100,
                              "time_limit_seconds": 30, "num_search_workers": 1, "random_seed": 0}}


def write_workbook(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = normalize_columns(frame).tag.tolist()
    frame.to_excel(path, index=False, sheet_name="Signals")
    reread = load_input(path)
    if len(reread) != len(frame) or reread.tag.tolist() != expected:
        raise ValueError(f"Workbook failed ingestion round trip: {path}")


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def write_yaml(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def revision_pair(base: pd.DataFrame, percent: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if percent not in {1, 5, 20}:
        raise ValueError("Revision percentage must be 1, 5, or 20.")
    old = base.copy()
    new = base.copy()
    rng = np.random.default_rng(seed + int(percent))
    changed = max(3, round(len(base) * percent / 100))
    modified_n = max(1, round(changed * 0.6))
    removed_n = max(1, (changed - modified_n) // 2)
    added_n = max(1, changed - modified_n - removed_n)
    indices = rng.permutation(len(base))
    modified_indices = indices[:modified_n]
    remove_indices = set(indices[modified_n:modified_n + removed_n].tolist())
    for idx in modified_indices:
        new.loc[idx, "description"] = str(new.loc[idx, "description"]) + " (Rev B updated)"
        new.loc[idx, "lifecycle"] = "wired" if new.loc[idx, "lifecycle"] != "wired" else "loop_checked"
    new = new.loc[[i for i in range(len(new)) if i not in remove_indices]].copy()
    additions = make_signals(added_n, seed + 900_000 + int(percent))
    additions["tag"] = [f"REV-B-ADD-{percent:02d}-{i + 1:05d}" for i in range(added_n)]
    additions["group"] = f"REV-B-ADDED-{percent:02d}"
    additions["redundancy_group"] = ""
    additions["redundancy_side"] = ""
    new = pd.concat([new, additions], ignore_index=True)
    return old, new, {"changed_percent_target": percent, "modified": modified_n,
                      "removed": removed_n, "added": added_n,
                      "unchanged": len(base) - modified_n - removed_n}


def scenario_data(name: str, count: int, seed: int) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    signals = make_signals(count, seed)
    if name == "normal":
        inventory = make_inventory(signals, seed, spare_fraction=0.08)
    elif name == "high_utilization":
        inventory = make_inventory(signals, seed, spare_fraction=0.015)
    elif name == "capacity_shortage":
        inventory = make_inventory(signals, seed, spare_fraction=0.0, shortage="capacity", mark_nonavailable=False)
    elif name == "compatibility_conflicts":
        inventory = make_inventory(signals, seed, spare_fraction=0.0, shortage="compatibility", mark_nonavailable=False)
    elif name == "grouping_cable":
        # Deliberately bounded so all hard constraints are practical to exercise.
        if count > 200:
            raise ValueError("grouping_cable scenario is limited to 200 signals for a safe CP-SAT demo.")
        inventory = make_inventory(signals, seed, spare_fraction=0.15, mark_nonavailable=False)
    else:
        raise ValueError(f"Unknown scenario: {name}")
    cfg = make_rules(inventory, name, spare_percent=1 if name == "high_utilization" else (5 if name in {"normal", "grouping_cable"} else 0))
    validate_config(cfg)
    return signals, inventory, cfg


def emit_scenario(out: Path, name: str, count: int, seed: int) -> dict[str, Any]:
    signals, inventory, config = scenario_data(name, count, seed)
    sub = out / name
    signal_path = sub / f"signals_{count}.xlsx"
    inventory_path = sub / "inventory.json"
    rules_path = sub / "rules.yaml"
    write_workbook(signals, signal_path)
    write_json(inventory, inventory_path)
    validate_inventory(json.loads(inventory_path.read_text(encoding="utf-8")))
    # The frontend takes inventory as its own JSON upload. Keep this YAML small;
    # app.py attaches the uploaded inventory to hardware.inventory at runtime.
    ui_config = {**config, "hardware": {"cabinets": 1, "ciocs_per_cabinet": 1,
                                         "baseplates_per_cioc": 1, "charms_per_baseplate": 12}}
    write_yaml(ui_config, rules_path)
    parsed = load_input(signal_path)
    if set(IO_TYPES) - set(parsed.io_type.unique()):
        raise ValueError(f"Scenario {name} did not cover all four IO types.")
    return {"scenario": name, "signals": len(signals), "available_slots": sum(s["availability"] == "available" for s in inventory["slots"]),
            "physical_slots": len(inventory["slots"]), "seed": seed,
            "files": [str(p.relative_to(out)).replace("\\", "/") for p in (signal_path, inventory_path, rules_path)]}


def emit_messy(out: Path, seed: int) -> list[str]:
    frame = make_signals(30, seed).sample(frac=1, random_state=seed).reset_index(drop=True)
    aliases = {"tag": "  Tag Name  ", "io_type": "I/O", "group": " Grp ",
               "redundancy_group": "Redundancy Group", "redundancy_side": "Redundancy Side",
               "cable": "Cable No", "pair": "Pair No", "description": "Signal Description",
               "segment": "Segment", "duty_standby": "Service Role", "charm_type": "Charm Type",
               "terminal_block_type": "TB Type", "isolation_required": "Isolation Required",
               "fusing_required": "Fuse Required", "injected_power_required": "Power Injection",
               "lifecycle": "Engineering Status", "previous_location": "Previous Location"}
    messy = frame.rename(columns=aliases)
    messy["Customer Notes"] = "unmapped optional notes"
    messy = messy[["Customer Notes", *reversed(messy.columns[:-1])]]
    path = out / "messy_input" / "signals_messy.xlsx"
    write_workbook(messy, path)
    negative = out / "messy_input" / "invalid_missing_tag.csv"
    negative.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"IO": ["AI", "DO"], "Cable": ["C-1", "C-2"]}).to_csv(negative, index=False)
    ambiguous = out / "messy_input" / "invalid_ambiguous_tag_headers.csv"
    pd.DataFrame({"Tag": ["X1"], "Tag Name": ["X1"], "IO": ["AI"]}).to_csv(ambiguous, index=False)
    return [str(p.relative_to(out)).replace("\\", "/") for p in (path, negative, ambiguous)]


def generate_suite(out: Path, seed: int, count: int) -> dict[str, Any]:
    manifest: dict[str, Any] = {"schema_version": 1, "seed": seed, "synthetic_assumptions": [
        "All controller, cabinet, CIOC, baseplate, CHARM and terminal-block IDs are invented test identifiers.",
        "IO compatibility and isolation/fusing/injected-power facts are fabricated to exercise code paths, not vendor data.",
        "Each cable has two synthetic signals with pair IDs 1 and 2, mapped to adjacent candidate slots in one baseplate.",
        "Groups and redundancy labels are artificial; A/B side aliases/engineering meanings are not inferred.",
        "Reserved and unavailable slots are synthetic status examples only."], "scenarios": [], "revisions": []}
    for n in SIZES:
        signals = make_signals(n, seed)
        path = out / "sizes" / f"signals_{n}.xlsx"
        inventory_path = out / "sizes" / f"inventory_{n}.json"
        rules_path = out / "sizes" / f"rules_{n}.yaml"
        write_workbook(signals, path)
        inventory = make_inventory(signals, seed, spare_fraction=0.08, mark_nonavailable=False)
        write_json(inventory, inventory_path)
        validate_inventory(json.loads(inventory_path.read_text(encoding="utf-8")))
        size_rules = make_rules(inventory, "normal", spare_percent=5)
        size_rules["hardware"] = {"cabinets": 1, "ciocs_per_cabinet": 1,
                                   "baseplates_per_cioc": 1, "charms_per_baseplate": 12}
        write_yaml(size_rules, rules_path)
        manifest["scenarios"].append({"scenario": "size_only", "signals": n, "seed": seed,
                                      "physical_slots": len(inventory["slots"]),
                                      "available_slots": len(inventory["slots"]),
                                      "files": [str(p.relative_to(out)).replace("\\", "/") for p in (path, inventory_path, rules_path)]})
    for name, scenario_count in [("normal", count), ("high_utilization", count),
                                 ("capacity_shortage", count), ("compatibility_conflicts", count),
                                 ("grouping_cable", min(count, 100))]:
        manifest["scenarios"].append(emit_scenario(out, name, scenario_count, seed))
    base = make_signals(count, seed)
    rev_dir = out / "revision"
    for pct in (1, 5, 20):
        old, new, counts = revision_pair(base, pct, seed)
        a = rev_dir / f"revision_A_{count}.xlsx"
        b = rev_dir / f"revision_B_{pct}pct_{count}.xlsx"
        write_workbook(old, a); write_workbook(new, b)
        manifest["revisions"].append({**counts, "signals_A": len(old), "signals_B": len(new), "seed": seed,
                                       "files": [str(p.relative_to(out)).replace("\\", "/") for p in (a, b)]})
    messy_files = emit_messy(out, seed)
    manifest["fixtures"] = {"messy_input": {"signals": 30, "seed": seed,
                                             "intended_test": "Alias normalization, shuffled columns, unknown optional column, blank optional values.",
                                             "files": [messy_files[0]]},
                            "negative_ingestion": {"intended_test": "Missing required tag and ambiguous tag aliases must be rejected.",
                                                   "files": messy_files[1:]}}
    config_path = out / "generation_config.json"
    write_json({"default_signal_count": count, "seed": seed, "supported_size_files": list(SIZES),
                "scenario_names": ["normal", "high_utilization", "capacity_shortage", "compatibility_conflicts", "grouping_cable"],
        "revision_percentages": [1, 5, 20], "generation_script": "benchmarks/generate_demo_data.py"}, config_path)
    manifest["generation_config"] = "generation_config.json"
    readme = """# Synthetic stress test fixtures\n\nAll hardware, terminal-block and compatibility values are invented fixtures. They do not encode a vendor standard. Start the app from `io_signal_sudoku_starter/` with `streamlit run app.py`. Upload the desired `signals_*.xlsx`, then upload the matching `inventory.json`. In the Rules tab, use the matching scenario `rules.yaml`; the frontend attaches the uploaded inventory.\n\nDefault demo: `normal/signals_1000.xlsx` + `normal/inventory.json` + `normal/rules.yaml`. The default rules at the project root use different synthetic capacity values.\n\nRegenerate the full suite: `python benchmarks/generate_demo_data.py --scenario all --count 1000 --seed 20261015`. Generate the 10,000-signal stress workbook/inventory as part of the suite; allocation at this scale is not run by the generator.\n\nThe `capacity_shortage` and `compatibility_conflicts` configurations are intentionally infeasible/unresolvable. `grouping_cable` is capped at 200 signals to keep all hard constraints practical. Messy-input examples are ingestion-only. See `manifest.json` for counts and seeds.\n"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    write_json(manifest, out / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1_000, help="Signal count for named scenarios and revisions.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scenario", default="all", choices=["all", "normal", "high_utilization", "capacity_shortage", "compatibility_conflicts", "grouping_cable", "revision"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "sample_data" / "stress_tests")
    parser.add_argument("--revision-percent", type=int, default=5, choices=[1, 5, 20],
                        help="Selected percentage when --scenario revision is used; the full suite always emits 1/5/20%%.")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    out = args.output_dir.resolve()
    if args.scenario == "all":
        manifest = generate_suite(out, args.seed, args.count)
    elif args.scenario == "revision":
        base = make_signals(args.count, args.seed)
        old, new, changes = revision_pair(base, args.revision_percent, args.seed)
        rev_dir = out / "revision"
        a, b = rev_dir / f"revision_A_{args.count}.xlsx", rev_dir / f"revision_B_{args.revision_percent}pct_{args.count}.xlsx"
        write_workbook(old, a); write_workbook(new, b)
        manifest = {"schema_version": 1, "seed": args.seed, "revision": changes,
                    "signals_A": len(old), "signals_B": len(new),
                    "files": [str(p.relative_to(out)).replace("\\", "/") for p in (a, b)]}
        out.mkdir(parents=True, exist_ok=True)
        write_json(manifest, out / "manifest.json")
    else:
        manifest = {"schema_version": 1, "seed": args.seed,
                    "scenarios": [emit_scenario(out, args.scenario, args.count, args.seed)]}
        write_json(manifest, out / "manifest.json")
    print(json.dumps({"output_dir": str(out), "scenario_count": len(manifest["scenarios"]),
                      "manifest": str(out / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()

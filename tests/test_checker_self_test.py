"""Deterministic validator self-test with distinct injected bad results/inputs."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from src.allocator import allocate_signals
from src.inventory import load_inventory
from src.validator import validate_allocation


ROOT = Path(__file__).resolve().parents[1]


def _baseline():
    inventory = load_inventory((ROOT / "sample_data" / "synthetic_test_inventory.json").open(encoding="utf-8"))
    config = {
        "schema_version": 1,
        "hardware": {"cabinets": 1, "ciocs_per_cabinet": 1, "baseplates_per_cioc": 2, "charms_per_baseplate": 2, "inventory": inventory},
        "rules": [],
        "compatibility": {"enabled": True, "require_charm_type": True, "require_terminal_block_type": True,
                          "require_isolation": True, "require_fusing": True, "require_injected_power": True},
        "optimization": {"time_limit_seconds": 5, "num_search_workers": 1},
    }
    signals = pd.DataFrame([
        {"tag": "AI-1", "io_type": "AI", "charm_type": "TEST-AI", "terminal_block_type": "TEST-TB-AI", "isolation_required": "yes", "fusing_required": "no", "injected_power_required": "no"},
        {"tag": "AI-2", "io_type": "AI", "charm_type": "TEST-AI", "terminal_block_type": "TEST-TB-AI", "isolation_required": "yes", "fusing_required": "no", "injected_power_required": "no"},
    ])
    allocation, tqs, status = allocate_signals(signals, config)
    assert status in {"OPTIMAL", "FEASIBLE"} and not tqs
    assert not validate_allocation(allocation, config, signals)
    return signals, config, allocation


def _case_inputs():
    signals, config, allocation = _baseline()
    cases = []

    def add(name, expected, *, result=None, cfg=None, original=None):
        cases.append((name, expected, allocation.copy() if result is None else result,
                      deepcopy(config) if cfg is None else cfg, signals.copy() if original is None else original))

    missing = allocation.iloc[:-1].copy(); add("missing input tag", "revision_integrity", result=missing, original=signals)
    extra = pd.concat([allocation, allocation.iloc[[0]].assign(tag="EXTRA")], ignore_index=True); add("extra result tag", "revision_integrity", result=extra)
    duplicate_input = pd.concat([signals, signals.iloc[[0]]], ignore_index=True); add("duplicate input tag", "input_tags", original=duplicate_input)
    blank_input = signals.copy(); blank_input.loc[0, "tag"] = " "; add("blank input tag", "input_tags", original=blank_input)
    bad = allocation.copy(); bad.loc[0, "status"] = "MAYBE"; add("unknown allocation status", "allocation_status", result=bad)
    bad = allocation.copy(); bad.loc[0, "slot_id"] = "CAB-X/UNKNOWN"; add("nonexistent slot", "slot_existence", result=bad)
    bad = allocation.copy(); reserved = next(slot for slot in config["hardware"]["inventory"]["slots"] if slot["availability"] == "reserved")
    for field in ("slot_id", "cabinet", "cioc", "baseplate", "charm_slot", "terminal_block_id"):
        bad.loc[0, field] = reserved.get(field, "") or ""
    add("reserved destination", "slot_availability", result=bad)
    bad = allocation.copy(); bad.loc[1, "slot_id"] = bad.loc[0, "slot_id"]; add("two signals collide on one slot", "unique_slot", result=bad)
    bad = allocation.copy(); bad.loc[1, "tag"] = bad.loc[0, "tag"]; add("duplicate allocated tag", "exactly_one_assignment", result=bad)
    for field, rule_id in (("cabinet", "hierarchy_path"), ("cioc", "hierarchy_path"), ("baseplate", "hierarchy_path"), ("charm_slot", "hierarchy_path")):
        bad = allocation.copy(); bad.loc[0, field] = "WRONG"; add(f"mismatched {field} path", rule_id, result=bad)
    bad = allocation.copy(); bad.loc[0, "terminal_block_id"] = "WRONG-TB"; add("mismatched terminal block", "terminal_block_assignment", result=bad)

    def change_assigned_slot(field, value):
        cfg = deepcopy(config)
        assigned = allocation.loc[0, "slot_id"]
        slot = next(slot for slot in cfg["hardware"]["inventory"]["slots"] if slot["slot_id"] == assigned)
        slot[field] = value
        return cfg

    bad_config = change_assigned_slot("supported_io_types", ["DO"]); add("unsupported I/O type", "io_type_compatibility", cfg=bad_config)
    bad_config = change_assigned_slot("charm_type", "WRONG-CHARM"); add("wrong CHARM type", "compatibility", cfg=bad_config)
    bad_config = change_assigned_slot("terminal_block_type", "WRONG-TB"); add("wrong terminal-block type", "compatibility", cfg=bad_config)
    bad_config = change_assigned_slot("isolation", False); add("wrong isolation capability", "compatibility", cfg=bad_config)
    bad_config = change_assigned_slot("fused", True); add("wrong fusing capability", "compatibility", cfg=bad_config)
    bad_config = change_assigned_slot("injected_power", True); add("wrong injected-power capability", "compatibility", cfg=bad_config)
    return cases


@pytest.mark.parametrize("case_name,expected_rule,result,config,original", _case_inputs(), ids=lambda value: value if isinstance(value, str) else None)
def test_checker_detects_each_injected_violation(case_name, expected_rule, result, config, original):
    findings = validate_allocation(result, config, original)
    assert any(finding["rule_id"] == expected_rule for finding in findings), f"self-test case was not detected: {case_name}"

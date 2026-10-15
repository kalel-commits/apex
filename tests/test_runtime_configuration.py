"""Regression coverage for the Streamlit rules-plus-uploaded-inventory path."""
from __future__ import annotations

import math
from pathlib import Path

from src.allocator import allocate_signals
from src.configuration import build_runtime_config, require_expected_inventory
from src.ingestion import load_input
from src.inventory import load_inventory
from src.validator import validate_allocation


ROOT = Path(__file__).resolve().parents[1]
NORMAL = ROOT / "sample_data" / "stress_tests" / "normal"


def test_normal_1000_demo_uses_uploaded_scenario_rules_and_inventory():
    signals = load_input(NORMAL / "signals_1000.xlsx")
    with (NORMAL / "inventory.json").open("r", encoding="utf-8") as stream:
        uploaded_inventory = load_inventory(stream)
    uploaded_rules = (NORMAL / "rules.yaml").read_text(encoding="utf-8")

    # This is the same config builder used by both UI rule validation and allocation.
    config = build_runtime_config(uploaded_rules, uploaded_inventory)
    require_expected_inventory(config)
    assert config["hardware"]["inventory"] == uploaded_inventory
    assert config["rules"][0]["basis"] == "available"
    assert config["rules"][0]["minimum_percent"] == 5

    # The old UI default is a distinct, valid config, but its 10% physical reserve
    # permits only 997 of these 1,000 signals in this 1,108-slot inventory.
    default_yaml = (ROOT / "rules.yaml").read_text(encoding="utf-8")
    default_config = build_runtime_config(default_yaml, uploaded_inventory)
    default_reserve = next(rule for rule in default_config["rules"] if rule["type"] == "spare_capacity")
    default_maximum = math.floor(len(uploaded_inventory["slots"]) * (1 - default_reserve["minimum_percent"] / 100))
    assert default_maximum == 997 < len(signals)

    allocation, tqs, status = allocate_signals(signals, config)
    findings = validate_allocation(allocation, config, signals)
    assert status in {"OPTIMAL", "FEASIBLE"}
    assert int(allocation.status.eq("ALLOCATED").sum()) == 1000
    assert not tqs
    assert not findings

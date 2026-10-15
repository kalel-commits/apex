from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from src.configuration import (
    build_runtime_config,
    configuration_fingerprint,
    require_expected_inventory,
    result_matches_fingerprint,
)


RULES = """
schema_version: 1
hardware:
  cabinets: 1
  ciocs_per_cabinet: 1
  baseplates_per_cioc: 1
  charms_per_baseplate: 2
rules:
  - id: reserve
    type: spare_capacity
    enabled: true
    minimum_percent: 0
compatibility:
  enabled: true
optimization:
  time_limit_seconds: 3
  num_search_workers: 1
"""


def _inventory() -> dict:
    return {
        "schema_version": 1,
        "source_authority": "synthetic",
        "source_reference": "test fixture",
        "slots": [{
            "slot_id": "CAB-01/CIOC-01/BP-01/CHARM-01",
            "cabinet": "CAB-01", "cioc": "CIOC-01", "baseplate": "BP-01", "charm_slot": "CHARM-01",
            "availability": "available", "supported_io_types": ["AI"], "charm_type": "AI",
            "terminal_block_type": "TB-AI", "isolation": True, "fused": False, "injected_power": False,
        }],
    }


def _signals() -> pd.DataFrame:
    return pd.DataFrame([{"tag": "LOOP-001", "io_type": "AI", "description": "Pressure"}])


def test_normal_scenario_configuration_requires_and_attaches_uploaded_inventory():
    config = build_runtime_config(RULES, _inventory())
    require_expected_inventory(config)
    assert config["hardware"]["inventory"] == _inventory()
    assert config["rules"][0]["id"] == "reserve"
    assert config["compatibility"]["enabled"] is True


def test_compatibility_scenario_without_inventory_is_rejected_before_solving():
    config = build_runtime_config(RULES)
    with pytest.raises(ValueError, match="requires an explicit inventory"):
        require_expected_inventory(config)


def test_result_fingerprint_tracks_rules_inventory_and_signal_data():
    signals = _signals()
    inventory = _inventory()
    config = build_runtime_config(RULES, inventory)
    original = configuration_fingerprint(signals, config)
    assert result_matches_fingerprint(original, original)

    changed_rules = deepcopy(config)
    changed_rules["rules"][0]["minimum_percent"] = 1
    assert not result_matches_fingerprint(original, configuration_fingerprint(signals, changed_rules))

    changed_inventory = deepcopy(config)
    changed_inventory["hardware"]["inventory"]["slots"][0]["availability"] = "reserved"
    assert not result_matches_fingerprint(original, configuration_fingerprint(signals, changed_inventory))

    changed_signals = signals.copy()
    changed_signals.loc[0, "description"] = "Changed description"
    assert not result_matches_fingerprint(original, configuration_fingerprint(changed_signals, config))

    changed_solver = deepcopy(config)
    changed_solver["optimization"]["time_limit_seconds"] = 4
    assert not result_matches_fingerprint(original, configuration_fingerprint(signals, changed_solver))


def test_result_is_not_current_when_fingerprint_is_missing_or_different():
    assert not result_matches_fingerprint(None, "active")
    assert not result_matches_fingerprint("old", "active")
    assert result_matches_fingerprint("same", "same")

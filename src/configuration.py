"""Build the effective runtime configuration used by the Streamlit workflow."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
import yaml

from src.inventory import validate_inventory
from src.rules import validate_config


def build_runtime_config(rules_text: str, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse rule YAML, attach the currently uploaded inventory, and validate it."""
    try:
        config = yaml.safe_load(rules_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse rules YAML: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("Rules YAML must contain a configuration object.")
    if inventory is not None:
        config.setdefault("hardware", {})["inventory"] = inventory
    return validate_config(config)


def require_expected_inventory(config: dict[str, Any]) -> None:
    """Reject a compatibility scenario that is missing its explicit inventory."""
    validate_config(config)
    if config.get("compatibility", {}).get("enabled", False):
        inventory = config.get("hardware", {}).get("inventory")
        if inventory is None:
            raise ValueError(
                "This rules configuration enables compatibility checks and requires an explicit inventory. "
                "Upload the matching inventory JSON before allocating."
            )
        validate_inventory(inventory)


def configuration_fingerprint(signals: pd.DataFrame, config: dict[str, Any]) -> str:
    """Hash only allocation-relevant normalized signals and effective configuration."""
    columns = sorted(str(column) for column in signals.columns)
    frame = signals.copy()
    frame.columns = [str(column) for column in frame.columns]
    frame = frame.reindex(columns=columns)
    records = []
    for row in frame.itertuples(index=False, name=None):
        records.append([_json_value(value) for value in row])
    payload = {
        "signals": {"columns": columns, "rows": records},
        "configuration": config,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def result_matches_fingerprint(result_fingerprint: str | None, active_fingerprint: str | None) -> bool:
    return bool(result_fingerprint and active_fingerprint and result_fingerprint == active_fingerprint)


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

"""Versioned configuration validation for supported generic rules."""
from __future__ import annotations
import math
from typing import Any
from src.inventory import validate_inventory

SUPPORTED = {"spare_capacity", "separation", "group_together", "cable_pair_order"}
LEVELS = {"cabinet", "cioc", "baseplate"}

def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict): raise ValueError("Configuration must be a YAML object.")
    if config.get("schema_version") != 1: raise ValueError("schema_version must be 1.")
    hw = config.get("hardware")
    if not isinstance(hw, dict): raise ValueError("hardware must be an object.")
    inventory=hw.get("inventory")
    for key in ("cabinets", "ciocs_per_cabinet", "baseplates_per_cioc", "charms_per_baseplate"):
        if key not in hw and inventory is not None: continue
        if not isinstance(hw.get(key), int) or isinstance(hw[key], bool) or hw[key] < 1: raise ValueError(f"hardware.{key} must be a positive integer.")
    rules = config.get("rules")
    if not isinstance(rules, list): raise ValueError("rules must be a list.")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict): raise ValueError("Each rule must be an object.")
        if not isinstance(rule.get("id"),str) or not rule["id"].strip() or rule["id"] in ids: raise ValueError("Every rule needs a unique nonempty id.")
        ids.add(rule["id"])
        if rule.get("type") not in SUPPORTED: raise ValueError(f"Unsupported rule type: {rule.get('type')!r}.")
        if not isinstance(rule.get("enabled",True),bool): raise ValueError(f"Rule {rule['id']}: enabled must be true or false.")
        if rule.get("severity", "hard") != "hard": raise ValueError("Only hard severity is supported for constraints.")
        if rule["type"] == "spare_capacity":
            val = float(rule.get("minimum_percent", 0))
            if not math.isfinite(val) or not 0 <= val < 100: raise ValueError(f"Rule {rule['id']}: minimum_percent must be finite and in [0, 100).")
            if rule.get("level", "global") not in {*LEVELS, "global"}: raise ValueError("Invalid spare capacity level.")
            if rule.get("basis","physical") not in {"physical","available"}: raise ValueError(f"Rule {rule['id']}: basis must be physical or available.")
        if rule["type"] in {"separation", "group_together"} and rule.get("level", "cioc" if rule["type"] == "separation" else "cabinet") not in LEVELS:
            raise ValueError(f"Rule {rule['id']}: unsupported hierarchy level.")
        if rule["type"] == "cable_pair_order" and rule.get("level", "slot") != "slot": raise ValueError("cable_pair_order supports level='slot'.")
        if rule["type"] in {"group_together","separation","cable_pair_order"}:
            keys={"group_together":("group_by",),"separation":("group_by","side_by"),"cable_pair_order":("group_by","order_by")}[rule["type"]]
            for key in keys:
                if key in rule and (not isinstance(rule[key],str) or not rule[key].strip()): raise ValueError(f"Rule {rule['id']}: {key} must be a nonempty column name.")
    optimization=config.get("optimization",{})
    if not isinstance(optimization,dict): raise ValueError("optimization must be an object.")
    time_limit=optimization.get("time_limit_seconds",30)
    if not isinstance(time_limit,(int,float)) or isinstance(time_limit,bool) or not math.isfinite(time_limit) or time_limit<=0: raise ValueError("optimization.time_limit_seconds must be finite and positive.")
    workers=optimization.get("num_search_workers",1)
    if not isinstance(workers,int) or isinstance(workers,bool) or workers<1: raise ValueError("optimization.num_search_workers must be a positive integer.")
    penalty=optimization.get("move_penalty",100)
    if not isinstance(penalty,(int,float)) or isinstance(penalty,bool) or not math.isfinite(penalty) or penalty<0: raise ValueError("optimization.move_penalty must be finite and nonnegative.")
    costs=optimization.get("move_costs",{})
    if not isinstance(costs,dict): raise ValueError("optimization.move_costs must be an object.")
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in costs.values()): raise ValueError("Lifecycle move costs must be finite nonnegative numbers.")
    if inventory is not None: validate_inventory(inventory)
    compatibility=config.get("compatibility",{})
    if not isinstance(compatibility,dict): raise ValueError("compatibility must be an object.")
    for key,value in compatibility.items():
        if key not in {"enabled","require_charm_type","require_terminal_block_type","require_isolation","require_fusing","require_injected_power"}:
            raise ValueError(f"Unsupported compatibility setting: {key!r}.")
        if not isinstance(value,bool): raise ValueError(f"compatibility.{key} must be true or false.")
    return config

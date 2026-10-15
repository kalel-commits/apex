"""Revision comparison helpers; identities are matched by tag."""
from __future__ import annotations
import json
import pandas as pd


def _configuration_changes(previous_config, current_config) -> list[str]:
    if previous_config is None or current_config is None:
        return []
    changes = []
    old_rules = {rule.get("id"): rule for rule in previous_config.get("rules", [])}
    new_rules = {rule.get("id"): rule for rule in current_config.get("rules", [])}
    for rule_id in sorted(set(old_rules) | set(new_rules)):
        if old_rules.get(rule_id) != new_rules.get(rule_id):
            changes.append(f"rule {rule_id!r} added, removed, or changed")
    for section in ("compatibility", "optimization"):
        if previous_config.get(section, {}) != current_config.get(section, {}):
            changes.append(f"{section} settings changed")
    old_inventory = previous_config.get("hardware", {}).get("inventory")
    new_inventory = current_config.get("hardware", {}).get("inventory")
    old_inventory_key = json.dumps(old_inventory, sort_keys=True, default=str)
    new_inventory_key = json.dumps(new_inventory, sort_keys=True, default=str)
    if old_inventory_key != new_inventory_key:
        changes.append("explicit inventory or slot compatibility/availability changed")
    old_hardware = {key: value for key, value in previous_config.get("hardware", {}).items() if key != "inventory"}
    new_hardware = {key: value for key, value in current_config.get("hardware", {}).items() if key != "inventory"}
    if old_hardware != new_hardware:
        changes.append("synthetic hardware capacity changed")
    return changes

def compare_revisions(previous_input: pd.DataFrame, previous_allocation: pd.DataFrame,
                      current_input: pd.DataFrame, current_allocation: pd.DataFrame,
                      move_costs: dict[str, float] | None = None, default_move_cost: float = 100,
                      previous_config: dict | None = None, current_config: dict | None = None) -> pd.DataFrame:
    old={str(r.tag):r for _,r in previous_input.iterrows()}; new={str(r.tag):r for _,r in current_input.iterrows()}
    old_slots={str(r.tag):str(r.slot_id) for _,r in previous_allocation.iterrows() if str(r.get("status",""))=="ALLOCATED"}
    new_slots={str(r.tag):str(r.slot_id) for _,r in current_allocation.iterrows() if str(r.get("status",""))=="ALLOCATED"}
    config_changes = _configuration_changes(previous_config, current_config)
    rows=[]
    for tag in sorted(set(old)|set(new)):
        changed_fields=[]
        if tag in old and tag in new:
            for col in sorted(set(old[tag].index)&set(new[tag].index)):
                if col not in {"previous_location"} and str(old[tag][col]) != str(new[tag][col]): changed_fields.append(col)
        if tag not in old: status="ADDED"
        elif tag not in new: status="REMOVED"
        elif tag not in old_slots or tag not in new_slots: status="UNALLOCATED"
        elif old_slots[tag] != new_slots[tag]: status="MOVED"
        elif changed_fields: status="MODIFIED"
        else: status="UNCHANGED"
        lifecycle=str(old[tag].get("lifecycle","unwired")).strip().lower() if tag in old else "unwired"
        cost=float((move_costs or {}).get(lifecycle,default_move_cost)) if status=="MOVED" else 0.0
        reasons=[]
        if status=="MOVED":
            if changed_fields:
                reasons.append("signal input changed: " + ", ".join(changed_fields))
            reasons.extend(config_changes)
            if not reasons:
                reasons.append("no input/configuration change identified; alternate optimum or solver tie-break may have changed placement")
        rows.append({"tag":tag,"revision_status":status,"old_slot":old_slots.get(tag,""),"new_slot":new_slots.get(tag,""),"changed_fields":", ".join(changed_fields),"lifecycle":lifecycle,"weighted_move_cost_points":cost,"movement_reason":"; ".join(reasons),"movement_reason_basis":"observed input/configuration changes" if reasons and not reasons[0].startswith("no input/") else ("unexplained assignment change" if status=="MOVED" else "")})
    return pd.DataFrame(rows,columns=["tag","revision_status","old_slot","new_slot","changed_fields","lifecycle","weighted_move_cost_points","movement_reason","movement_reason_basis"])

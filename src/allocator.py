"""CP-SAT allocation for synthetic regular hierarchies or explicit inventory."""
from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from typing import Any

import pandas as pd
from ortools.sat.python import cp_model

from src.inventory import validate_inventory
from src.rules import validate_config


def build_slots(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all physical slots. Explicit inventory wins over synthetic counts."""
    hw = config["hardware"]
    inventory = hw.get("inventory")
    if inventory is not None:
        validate_inventory(inventory)
        slots = []
        for row in inventory["slots"]:
            item = dict(row)
            item["cioc_path"] = str(row["cioc"])
            item["baseplate_path"] = str(row["baseplate"])
            item["cabinet_path"] = str(row["cabinet"])
            item["charm_slot_path"] = str(row["charm_slot"])
            slots.append(item)
        return slots
    slots = []
    for cabinet in range(1, hw["cabinets"] + 1):
        for cioc in range(1, hw["ciocs_per_cabinet"] + 1):
            for baseplate in range(1, hw["baseplates_per_cioc"] + 1):
                for charm in range(1, hw["charms_per_baseplate"] + 1):
                    cabinet_path = f"CAB-{cabinet:02d}"
                    cioc_path = f"{cabinet_path}/CIOC-{cioc:02d}"
                    baseplate_path = f"{cioc_path}/BP-{baseplate:02d}"
                    charm_path = f"CHARM-{charm:02d}"
                    slots.append({
                        "slot_id": f"{baseplate_path}/{charm_path}",
                        "cabinet": cabinet, "cioc": (cabinet, cioc),
                        "baseplate": (cabinet, cioc, baseplate), "charm": charm,
                        "cabinet_path": cabinet_path, "cioc_path": cioc_path,
                        "baseplate_path": baseplate_path, "charm_slot_path": charm_path,
                        "availability": "available", "supported_io_types": None,
                        "charm_type": None, "terminal_block_type": None,
                        "isolation": None, "fused": None, "injected_power": None,
                    })
    return slots


def hierarchy(slot: dict[str, Any], level: str):
    if level == "cabinet": return slot["cabinet"]
    if level == "cioc": return slot["cioc"]
    if level == "baseplate": return slot["baseplate"]
    raise ValueError(f"Unsupported hierarchy level: {level}")


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _truth(value: Any) -> bool | None:
    if value is None or pd.isna(value) or _text(value) == "": return None
    if isinstance(value, bool): return value
    normalized = _text(value).lower()
    if normalized in {"true", "yes", "1", "required", "fused"}: return True
    if normalized in {"false", "no", "0", "not required", "unfused"}: return False
    return None


def _side(value: Any, rule: dict[str, Any]) -> str:
    text = _text(value).upper()
    aliases = rule.get("side_aliases", {})
    for side in ("A", "B"):
        choices = [side, *(str(x).upper() for x in aliases.get(side, []))]
        if text in choices: return side
    return ""


def _tq(tag: str, rule: str, reason: str, evidence: str, suggestion: str,
       category: str = "ENGINEERING_DATA") -> dict[str, str]:
    key = f"{tag}|{rule}|{reason}|{evidence}"
    return {
        "id": hashlib.sha1(key.encode()).hexdigest()[:12].upper(),
        "category": category, "tag": str(tag), "affected_signals": str(tag),
        "rule_id": rule, "reason": reason, "evidence": evidence,
        "suggestion": suggestion,
        "needed_change": "Provide or correct the referenced customer/hardware data; approve rule changes through engineering.",
    }


def _empty_result(signals: pd.DataFrame, tqs: list[dict], status: str, started: float):
    out = signals.copy()
    for col in ("slot_id", "cabinet", "cioc", "baseplate", "charm_slot", "terminal_block_id", "status"):
        out[col] = "TQ" if col == "status" else ""
    out.attrs["metadata"] = {"status": status, "runtime_seconds": time.perf_counter() - started,
                             "variables": 0, "constraints": 0}
    return out, tqs, status


def _signal_slot_compatibility(row: pd.Series, slot: dict[str, Any], compatibility: dict[str, Any]) -> tuple[bool, bool]:
    """Return (matches, needs-review) for a row and one explicit inventory slot."""
    unresolved = False
    io_type = _text(row.get("io_type", "")).upper()
    supported = slot.get("supported_io_types") or []
    if io_type not in {str(x).upper() for x in supported}: return False, False
    pairs = (
        ("charm_type", "charm_type", "require_charm_type"),
        ("terminal_block_type", "terminal_block_type", "require_terminal_block_type"),
        ("isolation_required", "isolation", "require_isolation"),
        ("fusing_required", "fused", "require_fusing"),
        ("injected_power_required", "injected_power", "require_injected_power"),
    )
    for signal_field, slot_field, required_flag in pairs:
        required = bool(compatibility.get(required_flag, False))
        signal_value = row.get(signal_field, "")
        inventory_value = slot.get(slot_field)
        if signal_field in {"isolation_required","fusing_required","injected_power_required"}:
            expected_bool=_truth(signal_value)
            if required and expected_bool is None: unresolved=True
            if required and inventory_value is None: unresolved=True
            if expected_bool is not None and inventory_value is None: unresolved=True
            elif expected_bool is not None and inventory_value is not expected_bool: return False, unresolved
            continue
        if required and _text(signal_value) == "": unresolved = True
        if required and inventory_value is None: unresolved = True
        if _text(signal_value) and inventory_value is None:
            unresolved = True
        if _text(signal_value) and str(signal_value).strip().casefold() != str(inventory_value).strip().casefold():
            if inventory_value is not None: return False, unresolved
    return not unresolved, unresolved


def allocate_signals(signals: pd.DataFrame, config: dict[str, Any]):
    """Allocate rows to unique destinations; only hard configured constraints are modeled."""
    started = time.perf_counter()
    validate_config(config)
    if not isinstance(signals, pd.DataFrame): raise TypeError("signals must be a pandas DataFrame")
    signals = signals.copy().reset_index(drop=True)
    signals = signals.where(pd.notna(signals), "")
    if "tag" not in signals: raise ValueError("Invalid input: required tag field is missing.")
    if signals.empty: raise ValueError("Invalid input: no signal rows were provided.")
    signals["tag"] = signals["tag"].astype(str).str.strip()
    if signals.tag.eq("").any(): raise ValueError("Invalid input: blank tag found.")
    if signals.tag.duplicated().any(): raise ValueError("Invalid input: duplicate tags found.")

    slots = build_slots(config)
    if not slots: return _empty_result(signals, [], "INFEASIBLE_CAPACITY", started)
    rules = [rule for rule in config["rules"] if rule.get("enabled", True)]
    inventory = config["hardware"].get("inventory")
    compatibility = config.get("compatibility", {})
    use_compatibility = bool(compatibility.get("enabled", False))
    base_tqs: list[dict[str, str]] = []
    candidate_indices: dict[int, list[int]] = {}
    unresolved_tags: set[int] = set()

    # Check rule-specific input and inventory semantics before building a solver model.
    for rule in rules:
        rtype = rule["type"]
        fields = {
            "group_together": (rule.get("group_by", "group"),),
            "separation": (rule.get("group_by", "redundancy_group"), rule.get("side_by", "redundancy_side")),
            "cable_pair_order": (rule.get("group_by", "cable"), rule.get("order_by", "pair")),
        }.get(rtype, ())
        for field in fields:
            if field not in signals.columns:
                for i, tag in enumerate(signals.tag):
                    base_tqs.append(_tq(tag, rule["id"], "A configured rule references a missing input column.",
                                         f"Column {field!r} is absent from the input dataframe.",
                                         f"Map the customer column to {field!r} or correct this rule."))
                    unresolved_tags.add(i)
        if rtype == "separation":
            group_field, side_field = fields
            if group_field in signals and side_field in signals:
                for i, row in signals.iterrows():
                    group, side = _text(row[group_field]), _text(row[side_field])
                    if bool(group) != bool(side) or (group and not _side(side, rule)):
                        base_tqs.append(_tq(row.tag, rule["id"], "Redundancy metadata is missing or inconsistent.",
                                             f"{group_field}={group!r}; {side_field}={side!r}.",
                                             "Confirm the A/B relationship and provide a consistent group and side."))
                        unresolved_tags.add(i)
        elif rtype == "cable_pair_order":
            cable_field, pair_field = fields
            pairs_by_cable: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(list))
            if cable_field in signals and pair_field in signals:
                for i, row in signals.iterrows():
                    cable, pair_text = _text(row[cable_field]), _text(row[pair_field])
                    if not cable or not pair_text:
                        field = cable_field if not cable else pair_field
                        base_tqs.append(_tq(row.tag, rule["id"], "Cable/pair ordering data is incomplete.",
                                             f"Required field {field!r} is blank.",
                                             f"Provide {field!r} for this signal."))
                        unresolved_tags.add(i)
                        continue
                    try: pair_number = float(pair_text)
                    except (ValueError, TypeError):
                        base_tqs.append(_tq(row.tag, rule["id"], "Pair number is not numeric.",
                                             f"{pair_field}={pair_text!r}.", "Correct the cable-pair number."))
                        unresolved_tags.add(i); continue
                    pairs_by_cable[cable][pair_number].append(i)
            for cable, numbers in pairs_by_cable.items():
                for pair_number, indices in numbers.items():
                    if len(indices) > 1:
                        for i in indices:
                            base_tqs.append(_tq(signals.loc[i, "tag"], rule["id"], "Pair numbering is ambiguous.",
                                                 f"Cable {cable!r} repeats pair number {pair_number:g}.",
                                                 "Correct the duplicate pair number using the cable schedule."))
                            unresolved_tags.add(i)
            if not inventory:
                for i, row in signals.iterrows():
                    if _text(row.get(cable_field, "")):
                        base_tqs.append(_tq(row.tag, rule["id"], "Physical cable-pair adjacency is not defined by the synthetic hierarchy.",
                                             "No authoritative slot sequence and adjacency domain were supplied.",
                                             "Provide verified physical_sequence and adjacency_domain for inventory slots, and confirm pair-order semantics."))
                        unresolved_tags.add(i)
            elif any("physical_sequence" not in slot or "adjacency_domain" not in slot for slot in slots):
                for i, row in signals.iterrows():
                    if _text(row.get(cable_field, "")):
                        base_tqs.append(_tq(row.tag, rule["id"], "Physical adjacency metadata is incomplete.",
                                             "Inventory slots require physical_sequence and adjacency_domain.",
                                             "Import a verified adjacency sequence or disable pair ordering after engineering review."))
                        unresolved_tags.add(i)

    if use_compatibility:
        if not inventory:
            for i, row in signals.iterrows():
                base_tqs.append(_tq(row.tag, "compatibility", "Compatibility rules require explicit hardware inventory.",
                                     "The configured hierarchy is synthetic and contains no compatibility matrix.",
                                     "Import inventory with supported I/O, CHARM and terminal-block data."))
                unresolved_tags.add(i)
        else:
            all_declared_types = {str(t).upper() for slot in slots for t in (slot.get("supported_io_types") or [])}
            for i, row in signals.iterrows():
                io_type = _text(row.get("io_type", "")).upper()
                if not io_type:
                    base_tqs.append(_tq(row.tag, "compatibility", "I/O type is missing.", "io_type is blank.", "Provide the documented signal I/O type.")); unresolved_tags.add(i)
                elif io_type not in all_declared_types:
                    base_tqs.append(_tq(row.tag, "compatibility", "I/O type is not declared by the supplied inventory.",
                                         f"No slot declares support for {io_type!r}.", "Confirm the I/O type or supply compatible hardware data.")); unresolved_tags.add(i)

    available = [j for j, slot in enumerate(slots) if slot.get("availability", "available") == "available"]
    for i, row in signals.iterrows():
        candidates = list(available)
        if use_compatibility and inventory:
            candidates = []
            unresolved_inventory = False
            for j in available:
                matches, unresolved = _signal_slot_compatibility(row, slots[j], compatibility)
                unresolved_inventory |= unresolved
                if matches: candidates.append(j)
            if not candidates and unresolved_inventory and i not in unresolved_tags:
                base_tqs.append(_tq(row.tag, "compatibility", "Compatibility cannot be established from incomplete inventory metadata.",
                                     "Required CHARM/TB/isolation/fusing/power properties are unknown.",
                                     "Provide the missing verified inventory properties.")); unresolved_tags.add(i)
            elif not candidates and i not in unresolved_tags:
                io_type = _text(row.get("io_type", "")).upper()
                base_tqs.append(_tq(row.tag, "compatibility", "No available slot satisfies the configured compatibility data.",
                                     f"Signal type {io_type!r}; {len(available)} available slots examined.",
                                     "Confirm signal requirements or add compatible available hardware.", "NO_COMPATIBLE_HARDWARE"))
                unresolved_tags.add(i)
        if "cable_pair_order" in [r["type"] for r in rules] and inventory:
            candidates = [j for j in candidates if "physical_sequence" in slots[j] and "adjacency_domain" in slots[j]]
        candidate_indices[i] = candidates
        if not candidates and i not in unresolved_tags:
            base_tqs.append(_tq(row.tag, "availability", "No available hardware slots remain.",
                                 f"{len(available)} slots are marked available.", "Add verified inventory or correct availability status.", "CAPACITY"))
            unresolved_tags.add(i)

    # Keep metadata TQs unique and deterministic; signals with unresolved data do not enter the model.
    dedup = {item["id"]: item for item in base_tqs}
    base_tqs = list(dedup.values())
    model_indices = [i for i in range(len(signals)) if i not in unresolved_tags]
    if not model_indices:
        out, _, status = _empty_result(signals, base_tqs, "UNRESOLVED_ENGINEERING_DATA", started)
        out.attrs["metadata"].update({"inventory_source": (inventory or {}).get("source_reference", "synthetic configuration"), "available_slots": len(available)})
        return out, base_tqs, status

    # Per-cabinet/global reserves use the explicitly configured physical/available basis.
    def reserve_capacity(rule: dict[str, Any]):
        basis = rule.get("basis", "physical")
        eligible = list(range(len(slots))) if basis == "physical" else available
        level = rule.get("level", "global")
        if level == "global": return {0: len(eligible)}
        counts: dict[Any, int] = defaultdict(int)
        for j in eligible: counts[hierarchy(slots[j], level)] += 1
        return counts

    physical_m = len(slots)
    model = cp_model.CpModel()
    regular = inventory is None
    x: dict[int, cp_model.IntVar] = {}
    local: dict[int, cp_model.IntVar] = {}
    for i in model_indices:
        values = candidate_indices[i]
        x[i] = model.NewIntVarFromDomain(cp_model.Domain.FromValues(values), f"slot_{i}")
        if not regular:
            local[i] = model.NewIntVar(0, len(values)-1, f"candidate_{i}")
            model.AddElement(local[i], values, x[i])
    model.AddAllDifferent(list(x.values()))

    hw = config["hardware"]
    divisors = {
        "cabinet": hw.get("ciocs_per_cabinet",1) * hw.get("baseplates_per_cioc",1) * hw.get("charms_per_baseplate",1),
        "cioc": hw.get("baseplates_per_cioc",1) * hw.get("charms_per_baseplate",1),
        "baseplate": hw.get("charms_per_baseplate",1),
    }
    hierarchy_keys = {level: sorted({hierarchy(slot, level) for slot in slots}, key=str)
                       for level in ("cabinet", "cioc", "baseplate")}
    if regular:
        hierarchy_codes = {
            "cabinet": {key:key-1 for key in hierarchy_keys["cabinet"]},
            "cioc": {key:(key[0]-1)*hw["ciocs_per_cabinet"]+key[1]-1 for key in hierarchy_keys["cioc"]},
            "baseplate": {key:((key[0]-1)*hw["ciocs_per_cabinet"]+(key[1]-1))*hw["baseplates_per_cioc"]+key[2]-1 for key in hierarchy_keys["baseplate"]},
        }
        hierarchy_limits = {"cabinet":hw["cabinets"],"cioc":hw["cabinets"]*hw["ciocs_per_cabinet"],
                            "baseplate":hw["cabinets"]*hw["ciocs_per_cabinet"]*hw["baseplates_per_cioc"]}
    else:
        hierarchy_codes = {level: {key:k for k,key in enumerate(keys)} for level,keys in hierarchy_keys.items()}
        hierarchy_limits = {level:len(keys) for level,keys in hierarchy_keys.items()}

    def hierarchy_vars(level: str, label: str):
        result = {}
        if regular:
            for i in model_indices:
                v = model.NewIntVar(0, hierarchy_limits[level]-1, f"{label}_{i}")
                model.AddDivisionEquality(v, x[i], divisors[level]); result[i] = v
        else:
            for i in model_indices:
                vals = [hierarchy_codes[level][hierarchy(slots[j], level)] for j in candidate_indices[i]]
                v = model.NewIntVar(0, max(0, hierarchy_limits[level]-1), f"{label}_{i}")
                model.AddElement(local[i], vals, v); result[i] = v
        return result

    for rule in rules:
        if rule["type"] == "spare_capacity":
            level = rule.get("level", "global")
            capacities = reserve_capacity(rule)
            reserve_fraction = float(rule["minimum_percent"]) / 100
            if level == "global":
                capacity = capacities[0]
                model.Add(len(model_indices) <= math.floor(capacity * (1-reserve_fraction)))
            else:
                hvars = hierarchy_vars(level, f"{rule['id']}_hierarchy")
                for key, capacity in capacities.items():
                    code = hierarchy_codes[level][key]
                    indicators=[]
                    for i in model_indices:
                        indicator=model.NewBoolVar(f"{rule['id']}_{level}_{code}_{i}")
                        model.Add(hvars[i]==code).OnlyEnforceIf(indicator)
                        model.Add(hvars[i]!=code).OnlyEnforceIf(indicator.Not())
                        indicators.append(indicator)
                    model.Add(sum(indicators) <= math.floor(capacity * (1-reserve_fraction)))
        elif rule["type"] == "group_together":
            field, level = rule.get("group_by", "group"), rule.get("level", "cabinet")
            hvars = hierarchy_vars(level, f"{rule['id']}_group")
            grouped: dict[str, list[int]] = defaultdict(list)
            for i in model_indices:
                group = _text(signals.loc[i, field])
                if group: grouped[group].append(i)
            for indices in grouped.values():
                for i in indices[1:]: model.Add(hvars[i] == hvars[indices[0]])
        elif rule["type"] == "separation":
            field, side_field, level = rule.get("group_by", "redundancy_group"), rule.get("side_by", "redundancy_side"), rule.get("level", "cioc")
            hvars = hierarchy_vars(level, f"{rule['id']}_separation")
            grouped: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"A": [], "B": []})
            for i in model_indices:
                group = _text(signals.loc[i, field]); side = _side(signals.loc[i, side_field], rule)
                if group and side: grouped[group][side].append(i)
            for sides in grouped.values():
                for a in sides["A"]:
                    for b in sides["B"]: model.Add(hvars[a] != hvars[b])
        elif rule["type"] == "cable_pair_order":
            cable_field, pair_field = rule.get("group_by", "cable"), rule.get("order_by", "pair")
            grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
            for i in model_indices:
                grouped[_text(signals.loc[i, cable_field])].append((float(signals.loc[i, pair_field]), i))
            seq_vars = {}; domain_vars = {}
            for i in model_indices:
                vals = [slots[j]["physical_sequence"] for j in candidate_indices[i]]
                domains = [slots[j]["adjacency_domain"] for j in candidate_indices[i]]
                seq_vars[i] = model.NewIntVar(min(vals), max(vals), f"physical_sequence_{i}")
                model.AddElement(local[i], vals, seq_vars[i])
                domain_keys = sorted(set(domains)); domain_codes = {v:k for k,v in enumerate(domain_keys)}
                domain_vars[i] = model.NewIntVar(0, max(0,len(domain_codes)-1), f"adjacency_domain_{i}")
                model.AddElement(local[i], [domain_codes[d] for d in domains], domain_vars[i])
            for pairs in grouped.values():
                pairs.sort()
                for (_, a), (_, b) in zip(pairs, pairs[1:]):
                    model.Add(domain_vars[a] == domain_vars[b])
                    model.Add(seq_vars[b] == seq_vars[a] + 1)

    objective = []
    optimization = config.get("optimization", {})
    old_index = {slot["slot_id"]: j for j, slot in enumerate(slots)}
    if optimization.get("preserve_previous_assignments", True):
        for i in model_indices:
            old = _text(signals.loc[i].get("previous_location", ""))
            if old in old_index and old_index[old] in candidate_indices[i]:
                lifecycle = _text(signals.loc[i].get("lifecycle", "unwired")).lower()
                weight = int(optimization.get("move_costs", {}).get(lifecycle, optimization.get("move_penalty", 100)))
                moved = model.NewBoolVar(f"moved_{i}")
                model.Add(x[i] != old_index[old]).OnlyEnforceIf(moved)
                model.Add(x[i] == old_index[old]).OnlyEnforceIf(moved.Not())
                objective.append(weight * moved)
    if objective: model.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(optimization.get("time_limit_seconds", 30))
    solver.parameters.num_search_workers = int(optimization.get("num_search_workers", 1))
    solver.parameters.random_seed = int(optimization.get("random_seed", 0))
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    runtime = time.perf_counter() - started
    proto = model.Proto()
    solver_metadata = {
        "status": status, "runtime_seconds": runtime,
        "variables": len(proto.variables), "constraints": len(proto.constraints),
        "active_rules": [rule["id"] for rule in rules], "solver_time_limit_seconds": solver.parameters.max_time_in_seconds,
        "solver_workers": solver.parameters.num_search_workers, "random_seed": solver.parameters.random_seed,
        "physical_slots": len(slots), "available_slots": len(available),
        "inventory_authority_declared": (inventory or {}).get("source_authority", "synthetic"),
        "inventory_source_reference": (inventory or {}).get("source_reference", "generated synthetic hierarchy"),
    }
    solved = status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if not solved:
        reason = "Solver time limit reached; feasibility remains unknown." if status_code == cp_model.UNKNOWN else "No feasible assignment exists for the configured model."
        category = "SOLVER_UNKNOWN" if status_code == cp_model.UNKNOWN else "INFEASIBLE_MODEL"
        for i in model_indices:
            base_tqs.append(_tq(signals.loc[i, "tag"], "allocation", reason, f"CP-SAT status: {status}.",
                                 "Review capacity and hard-rule interactions; solver status does not identify a proven root cause.", category))

    rows = []
    for i, row in signals.iterrows():
        item = row.to_dict()
        if i in model_indices and solved:
            slot = slots[solver.Value(x[i])]
            item.update({"slot_id": slot["slot_id"], "cabinet": slot["cabinet_path"], "cioc": slot["cioc_path"],
                         "baseplate": slot["baseplate_path"], "charm_slot": slot["charm_slot_path"],
                         "terminal_block_id": slot.get("terminal_block_id", "") or "", "status": "ALLOCATED"})
        else:
            item.update({"slot_id": "", "cabinet": "", "cioc": "", "baseplate": "", "charm_slot": "",
                         "terminal_block_id": "", "status": "TQ"})
        rows.append(item)
    result = pd.DataFrame(rows)
    if solved and objective:
        solver_metadata["objective"] = solver.ObjectiveValue()
        solver_metadata["best_bound"] = solver.BestObjectiveBound()
    else:
        solver_metadata["objective"] = None
        solver_metadata["best_bound"] = None
    result.attrs["metadata"] = solver_metadata
    # Stable IDs permit the same root-cause TQ to be deduplicated in the report.
    base_tqs = list({entry["id"]: entry for entry in base_tqs}.values())
    return result, base_tqs, status

"""Independent result checks implemented separately from solver constraints."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from src.inventory import validate_inventory
from src.rules import validate_config


def _physical_slots(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct destinations from raw configuration; do not consume solver slots."""
    hw=config["hardware"]
    if hw.get("inventory") is not None:
        validate_inventory(hw["inventory"])
        return [dict(slot) for slot in hw["inventory"]["slots"]]
    rows=[]
    for c in range(1,hw["cabinets"]+1):
        for i in range(1,hw["ciocs_per_cabinet"]+1):
            for b in range(1,hw["baseplates_per_cioc"]+1):
                for s in range(1,hw["charms_per_baseplate"]+1):
                    cab=f"CAB-{c:02d}"; cioc=f"{cab}/CIOC-{i:02d}"; bp=f"{cioc}/BP-{b:02d}"; charm=f"CHARM-{s:02d}"
                    rows.append({"slot_id":f"{bp}/{charm}","cabinet":c,"cioc":(c,i),"baseplate":(c,i,b),"charm_slot":s,
                                 "cabinet_path":cab,"cioc_path":cioc,"baseplate_path":bp,"charm_slot_path":charm,
                                 "availability":"available","supported_io_types":None,"charm_type":None,"terminal_block_type":None,
                                 "isolation":None,"fused":None,"injected_power":None})
    return rows


def _domain(slot: dict[str, Any], level: str):
    if level=="cabinet": return slot["cabinet"]
    if level=="cioc": return slot["cioc"]
    if level=="baseplate": return slot["baseplate"]
    raise ValueError(f"Unsupported hierarchy level {level!r}")


def _side(value: Any, rule: dict[str, Any]) -> str:
    text=str(value or "").strip().upper()
    aliases=rule.get("side_aliases",{})
    for letter in ("A","B"):
        if text in {letter,*[str(x).upper() for x in aliases.get(letter,[])]}: return letter
    return ""


def _as_bool(value: Any):
    if value is None or pd.isna(value) or str(value).strip()=="": return None
    if isinstance(value,bool): return value
    normalized=str(value).strip().lower()
    if normalized in {"true","yes","1","required","fused"}: return True
    if normalized in {"false","no","0","not required","unfused"}: return False
    return None


def _finding(rule_id: str, explanation: str, tag: str = "", *, severity: str = "ERROR",
             expected: str = "", actual: str = "", destination: str = "", suggestion: str = "") -> dict[str, Any]:
    tags=[part.strip() for part in str(tag).split(",") if part.strip()]
    return {"rule_id":rule_id,"severity":severity,"signal_tags":tags,"tag":tag,
            "assigned_destination":destination,"expected_condition":expected,"actual_condition":actual,
            "explanation":explanation,"issue":explanation,
            "suggested_resolution":suggestion or "Correct the input, inventory or allocation and run validation again."}


def validate_allocation(allocation: pd.DataFrame, config: dict, input_signals: pd.DataFrame | None = None) -> list[dict]:
    findings=[]
    try: validate_config(config)
    except Exception as exc: return [_finding("configuration",f"Cannot validate invalid configuration: {exc}",severity="UNSUPPORTED")]
    required={"tag","status","slot_id"}
    if not isinstance(allocation,pd.DataFrame) or not required<=set(allocation.columns):
        missing=sorted(required-set(allocation.columns)) if isinstance(allocation,pd.DataFrame) else sorted(required)
        return [_finding("schema",f"Missing result columns: {missing}",severity="UNSUPPORTED")]
    slots=_physical_slots(config); by_slot={str(s["slot_id"]):s for s in slots}
    if len(by_slot)!=len(slots): findings.append(_finding("inventory","Inventory contains duplicate physical slot IDs."))
    status=allocation["status"].astype(str)
    invalid=~status.isin({"ALLOCATED","TQ"})
    for _,row in allocation.loc[invalid].iterrows(): findings.append(_finding("allocation_status",f"Unknown status {row.status!r}.",str(row.tag),actual=str(row.status)))
    if input_signals is not None:
        if "tag" not in input_signals:
            findings.append(_finding("input_tags","Original input is missing the required tag field."))
        else:
            original=[str(v).strip() for v in input_signals.tag.fillna("")]
            actual=[str(v).strip() for v in allocation.tag.fillna("")]
            if Counter(original)!=Counter(actual):
                findings.append(_finding("revision_integrity",f"Input/result tags differ: missing={list((Counter(original)-Counter(actual)).elements())[:10]}, extra={list((Counter(actual)-Counter(original)).elements())[:10]}.",expected="One result row for each input tag",actual="Tag row counts differ"))
            duplicated=[tag for tag,count in Counter(original).items() if tag and count>1]
            if duplicated: findings.append(_finding("input_tags",f"Original input contains duplicate tags: {duplicated[:10]}.",",".join(duplicated[:10])))
            blanks=[str(i) for i,v in enumerate(original) if not v]
            if blanks: findings.append(_finding("input_tags",f"Original input contains blank tags on row indexes {blanks[:10]}.",",".join(blanks[:10])))
    allocated=allocation[status.eq("ALLOCATED")].copy()
    allocated_tags=allocated.tag.astype(str)
    for tag,count in Counter(allocated_tags).items():
        if count>1: findings.append(_finding("exactly_one_assignment",f"Allocated signal appears {count} times.",tag,actual=f"{count} allocated rows"))
    # Validate the complete path against raw physical inventory and destination availability.
    for _,row in allocated.iterrows():
        tag=str(row.tag); slot=by_slot.get(str(row.slot_id))
        if slot is None:
            findings.append(_finding("slot_existence",f"Destination {row.slot_id!r} is not in configured hardware.",tag,actual=str(row.slot_id)))
            continue
        if slot.get("availability","available")!="available":
            findings.append(_finding("slot_availability",f"Destination is marked {slot.get('availability')!r}.",tag,expected="available",actual=str(slot.get("availability")),destination=str(row.slot_id)))
        if slot.get("inventory") is not None: pass
        expected_path={
            "cabinet":str(slot.get("cabinet_path",slot.get("cabinet",""))),
            "cioc":str(slot.get("cioc_path",slot.get("cioc",""))),
            "baseplate":str(slot.get("baseplate_path",slot.get("baseplate",""))),
            "charm_slot":str(slot.get("charm_slot_path",slot.get("charm_slot",""))),
        }
        for column,expected_value in expected_path.items():
            if column not in allocation or str(row.get(column,""))!=expected_value:
                findings.append(_finding("hierarchy_path",f"{column} does not match the inventory path for slot {row.slot_id}.",tag,expected=expected_value,actual=str(row.get(column,"")),destination=str(row.slot_id)))
        tb=str(slot.get("terminal_block_id") or "")
        if "terminal_block_id" in allocation and str(row.get("terminal_block_id") or "")!=tb:
            findings.append(_finding("terminal_block_assignment",f"Terminal block does not match inventory for slot {row.slot_id}.",tag,expected=tb,actual=str(row.get("terminal_block_id") or ""),destination=str(row.slot_id)))
    for slot_id,frame in allocated.groupby("slot_id",dropna=False):
        if len(frame)>1:
            for tag in frame.tag.astype(str): findings.append(_finding("unique_slot",f"Slot {slot_id} is assigned to {len(frame)} signals.",tag,actual=str(slot_id),destination=str(slot_id)))

    active=[r for r in config["rules"] if r.get("enabled",True)]
    for rule in active:
        rtype=rule["type"]
        if rtype=="spare_capacity":
            level=rule.get("level","global"); basis=rule.get("basis","physical"); reserve=float(rule["minimum_percent"])/100
            capacity=Counter()
            for slot in slots:
                if basis=="available" and slot.get("availability","available")!="available": continue
                key=0 if level=="global" else _domain(slot,level); capacity[key]+=1
            usage=Counter()
            for _,row in allocated.iterrows():
                slot=by_slot.get(str(row.slot_id))
                if slot: usage[0 if level=="global" else _domain(slot,level)]+=1
            for key,cap in capacity.items():
                max_use=math.floor(cap*(1-reserve))
                if usage[key]>max_use:
                    findings.append(_finding(rule["id"],f"{level} {key!r} exceeds the {rule['minimum_percent']}% spare requirement.",expected=f"at most {max_use} occupied of {cap} {basis} slots",actual=f"{usage[key]} occupied",suggestion="Add capacity or revise the reserve basis/percentage only with engineering approval."))
        elif rtype in {"group_together","separation"}:
            group_field=rule.get("group_by","group" if rtype=="group_together" else "redundancy_group")
            level=rule.get("level","cabinet" if rtype=="group_together" else "cioc")
            side_field=rule.get("side_by","redundancy_side")
            needed=[group_field] if rtype=="group_together" else [group_field,side_field]
            for field in needed:
                if field not in allocation:
                    findings.append(_finding(rule["id"],f"Configured column {field!r} is absent; mandatory rule could not be verified.",severity="UNSUPPORTED"))
            groups=defaultdict(lambda:defaultdict(list))
            for _,row in allocated.iterrows():
                slot=by_slot.get(str(row.slot_id)); group=str(row.get(group_field,"") or "").strip()
                if not slot or not group: continue
                location=_domain(slot,level)
                if rtype=="group_together": groups[group][location].append(str(row.tag))
                else:
                    side=_side(row.get(side_field,""),rule)
                    if not side: findings.append(_finding(rule["id"],f"Group {group!r} has missing or invalid A/B designation.",str(row.tag),expected="A or B",actual=str(row.get(side_field,""))))
                    else: groups[group][side].append((location,str(row.tag)))
            if rtype=="group_together":
                for group,locations in groups.items():
                    if len(locations)>1:
                        tags=[t for values in locations.values() for t in values]
                        findings.append(_finding(rule["id"],f"Group {group!r} spans multiple {level} locations.",",".join(tags),expected=f"one {level}",actual=str(list(locations))))
            else:
                for group,sides in groups.items():
                    for a,_ in sides.get("A",[]):
                        for b,_ in sides.get("B",[]):
                            if a==b:
                                tags=[tag for _,tag in sides.get("A",[]) if _==a]+[tag for _,tag in sides.get("B",[]) if _==b]
                                findings.append(_finding(rule["id"],f"A/B signals in group {group!r} share {level} {a!r}.",",".join(tags),expected="different failure domains",actual=repr(a)))
        elif rtype=="cable_pair_order":
            if not config["hardware"].get("inventory"):
                findings.append(_finding(rule["id"],"Physical cable-pair ordering is unsupported without inventory sequence/domain metadata.",severity="UNSUPPORTED",suggestion="Supply authoritative physical_sequence and adjacency_domain data.")); continue
            cable_field=rule.get("group_by","cable"); pair_field=rule.get("order_by","pair"); cables=defaultdict(list)
            for _,row in allocated.iterrows():
                slot=by_slot.get(str(row.slot_id)); cable=str(row.get(cable_field,"") or "").strip()
                try: pair=float(row.get(pair_field,""))
                except (ValueError,TypeError):
                    findings.append(_finding(rule["id"],f"Pair number is missing or invalid in {pair_field!r}.",str(row.tag),destination=str(row.slot_id))); continue
                if not cable: findings.append(_finding(rule["id"],f"Cable identifier is missing in {cable_field!r}.",str(row.tag),destination=str(row.slot_id))); continue
                if slot is None: continue
                if "physical_sequence" not in slot or "adjacency_domain" not in slot:
                    findings.append(_finding(rule["id"],"Assigned inventory slot lacks physical adjacency metadata.",str(row.tag),severity="UNSUPPORTED",destination=str(row.slot_id))); continue
                cables[cable].append((pair,str(slot["adjacency_domain"]),int(slot["physical_sequence"]),str(row.tag)))
            for cable,pairs in cables.items():
                pairs.sort()
                if len({p[0] for p in pairs})!=len(pairs): findings.append(_finding(rule["id"],f"Cable {cable!r} contains duplicated pair numbers.",",".join(p[3] for p in pairs)))
                for left,right in zip(pairs,pairs[1:]):
                    if left[1]!=right[1] or right[2]!=left[2]+1:
                        findings.append(_finding(rule["id"],f"Cable {cable!r} pair positions are not physically consecutive within one adjacency domain.",f"{left[3]},{right[3]}",expected=f"same domain, sequence {left[2]+1}",actual=f"{right[1]} sequence {right[2]}"))

    compatibility=config.get("compatibility",{})
    if compatibility.get("enabled",False):
        inventory=config["hardware"].get("inventory")
        if not inventory:
            findings.append(_finding("compatibility","No supplied inventory is available to verify compatibility.",severity="UNSUPPORTED"))
        else:
            for _,row in allocated.iterrows():
                slot=by_slot.get(str(row.slot_id))
                if not slot: continue
                tag=str(row.tag); io_type=str(row.get("io_type","")).strip().upper()
                supported={str(v).strip().upper() for v in slot.get("supported_io_types",[])}
                if not io_type or io_type not in supported:
                    findings.append(_finding("io_type_compatibility",f"Signal type {io_type!r} is not explicitly supported by the assigned slot.",tag,expected=str(sorted(supported)),actual=io_type,destination=str(row.slot_id)))
                checks=(("charm_type","charm_type","require_charm_type"),("terminal_block_type","terminal_block_type","require_terminal_block_type"),("isolation_required","isolation","require_isolation"),("fusing_required","fused","require_fusing"),("injected_power_required","injected_power","require_injected_power"))
                for signal_field,slot_field,required_flag in checks:
                    expected=row.get(signal_field,""); actual=slot.get(slot_field)
                    if signal_field in {"isolation_required","fusing_required","injected_power_required"}:
                        expected_bool=_as_bool(expected)
                        if compatibility.get(required_flag,False) and (expected_bool is None or actual is None):
                            findings.append(_finding("compatibility_metadata",f"Required {signal_field} compatibility cannot be verified from signal/inventory data.",tag,severity="UNSUPPORTED",expected=str(expected),actual=str(actual),destination=str(row.slot_id)))
                        elif expected_bool is not None and actual is not expected_bool:
                            findings.append(_finding("compatibility",f"Assigned slot does not match required {signal_field}.",tag,expected=str(expected_bool),actual=str(actual),destination=str(row.slot_id)))
                        continue
                    if compatibility.get(required_flag,False) and (expected is None or str(expected).strip()=="" or actual is None):
                        findings.append(_finding("compatibility_metadata",f"Required {signal_field} compatibility cannot be verified from signal/inventory data.",tag,severity="UNSUPPORTED",expected=str(expected),actual=str(actual),destination=str(row.slot_id)))
                    elif expected is not None and str(expected).strip() and str(expected).strip().casefold()!=str(actual).strip().casefold():
                        findings.append(_finding("compatibility",f"Assigned slot does not match required {signal_field}.",tag,expected=str(expected),actual=str(actual),destination=str(row.slot_id)))
    # Unavailable mandatory engineering checks are surfaced, never inferred as passing.
    return findings

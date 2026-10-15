"""Import and validate explicit hardware inventory and per-slot compatibility data."""
from __future__ import annotations
import json
from typing import Any, BinaryIO

AUTHORITY={"synthetic","customer","vendor_documented"}
REQUIRED_SLOT={"slot_id","cabinet","cioc","baseplate","charm_slot","availability","supported_io_types","charm_type","terminal_block_type","isolation","fused","injected_power"}

def validate_inventory(data: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(data,dict) or data.get("schema_version")!=1: raise ValueError("Inventory schema_version must be 1.")
    authority=data.get("source_authority")
    if authority not in AUTHORITY: raise ValueError(f"source_authority must be one of {sorted(AUTHORITY)}.")
    reference=data.get("source_reference")
    if not isinstance(reference,str) or not reference.strip(): raise ValueError("Inventory source_reference is required (use 'synthetic fixture' for test data).")
    rows=data.get("slots")
    if not isinstance(rows,list) or not rows: raise ValueError("Inventory slots must be a nonempty list.")
    seen=set(); adjacency=set()
    for pos,slot in enumerate(rows,1):
        if not isinstance(slot,dict): raise ValueError(f"slots[{pos}] must be an object.")
        missing=REQUIRED_SLOT-set(slot)
        if missing: raise ValueError(f"slots[{pos}] missing fields: {sorted(missing)}.")
        sid=slot["slot_id"]
        if not isinstance(sid,str) or not sid.strip() or sid in seen: raise ValueError(f"slots[{pos}] has a blank or duplicate slot_id.")
        seen.add(sid)
        for field in ("cabinet","cioc","baseplate","charm_slot"):
            if not isinstance(slot[field],(str,int)) or isinstance(slot[field],bool) or not str(slot[field]).strip(): raise ValueError(f"slots[{pos}].{field} must be a nonempty string or integer.")
        if slot["availability"] not in {"available","reserved","unavailable"}: raise ValueError(f"slots[{pos}].availability is invalid.")
        if not isinstance(slot["supported_io_types"],list) or any(not isinstance(v,str) or not v.strip() for v in slot["supported_io_types"]): raise ValueError(f"slots[{pos}].supported_io_types must be a list of nonempty types.")
        for field in ("charm_type","terminal_block_type"):
            if slot[field] is not None and not isinstance(slot[field],str): raise ValueError(f"slots[{pos}].{field} must be a string or null.")
        for field in ("isolation","fused","injected_power"):
            if slot[field] is not None and not isinstance(slot[field],bool): raise ValueError(f"slots[{pos}].{field} must be true, false, or null (unknown).")
        if "physical_sequence" in slot and (not isinstance(slot["physical_sequence"],int) or isinstance(slot["physical_sequence"],bool)): raise ValueError(f"slots[{pos}].physical_sequence must be an integer.")
        if "adjacency_domain" in slot and (not isinstance(slot["adjacency_domain"],str) or not slot["adjacency_domain"].strip()): raise ValueError(f"slots[{pos}].adjacency_domain must be a nonempty string.")
        if "physical_sequence" in slot and "adjacency_domain" in slot:
            key=(slot["adjacency_domain"],slot["physical_sequence"])
            if key in adjacency: raise ValueError(f"Duplicate physical adjacency position {key!r}.")
            adjacency.add(key)
    return data

def load_inventory(file_obj: BinaryIO) -> dict[str,Any]:
    try:
        data=json.load(file_obj)
    except Exception as exc:
        raise ValueError(f"Could not parse inventory JSON: {exc}") from exc
    return validate_inventory(data)

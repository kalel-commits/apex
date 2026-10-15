import io
import pandas as pd
import pytest
import yaml
from src.ingestion import normalize_columns
from src.rules import validate_config
from src.allocator import allocate_signals
from src.validator import validate_allocation
from src.reporting import build_excel_report
from src.synthetic import generate_signals
from src.revisions import compare_revisions
from src.allocator import build_slots
from src.inventory import load_inventory, validate_inventory

@pytest.fixture
def config():
    value=yaml.safe_load(open("rules.yaml",encoding="utf-8")); value["hardware"]={"cabinets":2,"ciocs_per_cabinet":2,"baseplates_per_cioc":2,"charms_per_baseplate":4}; value["rules"]=[]; return value

def test_header_conflicts_and_blank_rows():
    x=normalize_columns(pd.DataFrame({" Tag Name ":["T1",None],"I/O":["AI",None]})); assert len(x)==1 and x.loc[0,"tag"]=="T1"
    with pytest.raises(ValueError,match="Ambiguous"): normalize_columns(pd.DataFrame({"Tag":["a"],"Tag Name":["b"]}))

def test_unknown_rule_rejected(config):
    config["rules"]=[{"id":"x","type":"unsafe_exec"}]
    with pytest.raises(ValueError,match="Unsupported rule"): validate_config(config)

def test_solver_configuration_validation(config):
    config["optimization"]["num_search_workers"]=0
    with pytest.raises(ValueError,match="num_search_workers"): validate_config(config)
    config["optimization"]["num_search_workers"]=1; config["optimization"]["move_costs"]={"wired":-1}
    with pytest.raises(ValueError,match="nonnegative"): validate_config(config)

def test_empty_signal_table_rejected(config):
    with pytest.raises(ValueError,match="no signal rows"): allocate_signals(pd.DataFrame(columns=["tag"]),config)

def test_allocation_validator_and_report(config):
    data=generate_signals(6,seed=3,groups=1)
    result,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs
    assert validate_allocation(result,config,data)==[]
    b=result.copy(); b.loc[1,"slot_id"]=b.loc[0,"slot_id"]
    assert any(i["rule_id"]=="unique_slot" for i in validate_allocation(b,config))
    bad=result.copy(); bad.loc[0,"cabinet"]="CAB-99"
    assert any(i["rule_id"]=="hierarchy_path" for i in validate_allocation(bad,config))
    report=build_excel_report(result,tqs,[],result.attrs["metadata"])
    x=pd.ExcelFile(io.BytesIO(report)); assert "Summary" in x.sheet_names and "IO Allocation" in x.sheet_names
    summary=pd.read_excel(io.BytesIO(report),sheet_name="Summary")
    assert "UNVERIFIED" in summary.loc[0,"validation_status"] and summary.loc[0,"validation_status"]!="VALID"
    revised=data.iloc[:-1].copy(); second,_,_=allocate_signals(revised,config)
    diff=compare_revisions(data,result,revised,second)
    report=build_excel_report(second,[],[],revision=diff)
    assert "Revision Comparison" in pd.ExcelFile(io.BytesIO(report)).sheet_names

def test_group_and_redundancy_rules(config):
    data=generate_signals(4,groups=1,redundancy_pairs=1)
    config["rules"]=[{"id":"sep","type":"separation","group_by":"redundancy_group","side_by":"redundancy_side","level":"cioc"},{"id":"grp","type":"group_together","group_by":"group","level":"cabinet"}]
    result,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not validate_allocation(result,config,data)

def test_synthetic_reproducible():
    pd.testing.assert_frame_equal(generate_signals(20,4),generate_signals(20,4))

def test_fault_injection_group_separation_spare_pair_and_revision(config):
    data=generate_signals(4,groups=1,redundancy_pairs=1,cable_groups=1)
    baseline,tqs,status=allocate_signals(data,config); assert status in {"OPTIMAL","FEASIBLE"}
    rules=[{"id":"sep","type":"separation","group_by":"redundancy_group","side_by":"redundancy_side","level":"cioc"},
           {"id":"grp","type":"group_together","group_by":"group","level":"cabinet"},
           {"id":"pair","type":"cable_pair_order","group_by":"cable","order_by":"pair"}]
    config["rules"]=rules
    # Each check is independently fed a mutated otherwise-successful output.
    slots=build_slots(config); bad=baseline.copy()
    # A/B same forbidden CIOC, but distinct physical CHARM slots.
    aidx=data.index[data.redundancy_side.eq("A")][0]; bidx=data.index[data.redundancy_side.eq("B")][0]
    sa=next(s for s in slots if s["slot_id"]==baseline.loc[aidx,"slot_id"])
    same_cioc=next(s for s in slots if s["cioc"]==sa["cioc"] and s["slot_id"] not in set(baseline.slot_id))
    bad.loc[bidx,"slot_id"]=same_cioc["slot_id"]
    assert any(x["rule_id"]=="sep" for x in validate_allocation(bad,config))
    # A functional group spans cabinets.
    bad=baseline.copy(); first=slots[0]; other=next(s for s in slots if s["cabinet"]!=first["cabinet"])
    bad.loc[1,"slot_id"]=other["slot_id"]
    assert any(x["rule_id"]=="grp" for x in validate_allocation(bad,config))
    # Pair order is non-consecutive.
    bad=baseline.iloc[:2].copy(); bad["pair"]=bad["pair"].astype(str); bad.loc[0,"cable"]="SAME"; bad.loc[1,"cable"]="SAME"; bad.loc[0,"pair"]="1"; bad.loc[1,"pair"]="2"
    bad.loc[0,"slot_id"]=slots[0]["slot_id"]; bad.loc[1,"slot_id"]=slots[2]["slot_id"]
    assert any(x["rule_id"]=="pair" for x in validate_allocation(bad,config))
    # Global reserve violation: five assigned against eight slots and 50% reserve.
    config["hardware"]={"cabinets":1,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":8}; config["rules"]=[]
    five=generate_signals(5,groups=1); bad,_,_=allocate_signals(five,config)
    config["rules"]=[{"id":"reserve","type":"spare_capacity","level":"global","minimum_percent":50}]
    assert any(x["rule_id"]=="reserve" for x in validate_allocation(bad,config))
    # Revision assignment consistency catches missing and newly introduced tags.
    assert any(x["rule_id"]=="revision_integrity" for x in validate_allocation(baseline.iloc[:-1],config,data))
    revised=data.iloc[:-1].copy(); revised.loc[revised.index[0],"io_type"]="AO"
    diff=compare_revisions(data,baseline,revised,baseline.iloc[:-1]); assert set(diff.revision_status)=={"MODIFIED","UNCHANGED","REMOVED"}
    assert diff.loc[diff.tag.eq(data.iloc[0].tag),"revision_status"].iloc[0]=="MODIFIED"
    assert diff.loc[diff.tag.eq(data.iloc[0].tag),"old_slot"].iloc[0]==diff.loc[diff.tag.eq(data.iloc[0].tag),"new_slot"].iloc[0]

def test_unverified_compatibility_is_reported_unsupported(config):
    data=generate_signals(2); allocated,_,_=allocate_signals(data,config)
    config["compatibility"]={"enabled":True}
    issues=validate_allocation(allocated,config)
    assert any(x["rule_id"]=="compatibility" and "No supplied inventory" in x["issue"] for x in issues)

def test_enabled_pair_rule_refuses_missing_engineering_data(config):
    data=generate_signals(3); data["pair"]=data["pair"].astype(str); data.loc[1,"pair"]=""
    config["rules"]=[{"id":"pairs","type":"cable_pair_order","group_by":"cable","order_by":"pair"}]
    allocation,tqs,status=allocate_signals(data,config)
    assert status=="UNRESOLVED_ENGINEERING_DATA" and not allocation.status.eq("ALLOCATED").any()
    assert tqs and tqs[0]["rule_id"]=="pairs" and "pair" in tqs[0]["evidence"]

def test_configured_missing_column_is_actionable_tq(config):
    data=generate_signals(2)
    config["rules"]=[{"id":"custom_group","type":"group_together","group_by":"customer_segment","level":"cabinet"}]
    allocation,tqs,status=allocate_signals(data,config)
    assert status=="UNRESOLVED_ENGINEERING_DATA" and not allocation.status.eq("ALLOCATED").any()
    assert any(t["rule_id"]=="custom_group" and "customer_segment" in t["evidence"] for t in tqs)

def inventory_config(config):
    import json
    config["hardware"]["inventory"]=json.load(open("sample_data/synthetic_test_inventory.json",encoding="utf-8"))
    config["compatibility"]={"enabled":True,"require_charm_type":True,"require_terminal_block_type":True,"require_isolation":True}
    config["rules"]=[]
    return config

def test_inventory_compatibility_and_reserved_slots(config):
    config=inventory_config(config)
    data=pd.DataFrame([{"tag":"A1","io_type":"AI","charm_type":"TEST-AI","terminal_block_type":"TEST-TB-AI","isolation_required":"yes"}])
    allocation,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs
    assert allocation.loc[0,"slot_id"] in {"CAB-A/CIOC-1/BP-1/CH-01","CAB-A/CIOC-1/BP-1/CH-02"}
    assert validate_allocation(allocation,config,data)==[]
    reserved=data.copy(); reserved.loc[0,"io_type"]="DO"; reserved.loc[0,"charm_type"]="TEST-DO"; reserved.loc[0,"terminal_block_type"]="TEST-TB-DO"; reserved.loc[0,"isolation_required"]="no"
    placed,queries,status=allocate_signals(reserved,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not queries and placed.loc[0,"slot_id"].endswith("BP-2/CH-01")
    unknown=data.copy(); unknown.loc[0,"io_type"]="RTD"
    _,queries,status=allocate_signals(unknown,config)
    assert status=="UNRESOLVED_ENGINEERING_DATA" and any("not declared" in q["reason"] for q in queries)

def test_inventory_validator_detects_injected_wrong_compatibility(config):
    config=inventory_config(config)
    data=pd.DataFrame([{"tag":"AI-1","io_type":"AI","charm_type":"TEST-AI","terminal_block_type":"TEST-TB-AI","isolation_required":"yes"}])
    allocation,_,_=allocate_signals(data,config)
    wrong=allocation.copy(); wrong.loc[0,"slot_id"]="CAB-A/CIOC-1/BP-2/CH-01"; wrong.loc[0,"baseplate"]="CAB-A/CIOC-1/BP-2"; wrong.loc[0,"charm_slot"]="CH-01"; wrong.loc[0,"terminal_block_id"]="TB-A:03"
    findings=validate_allocation(wrong,config,data)
    assert any(f["rule_id"] in {"io_type_compatibility","compatibility"} for f in findings)

def test_cable_adjacency_uses_explicit_physical_domains(config):
    config=inventory_config(config); config["compatibility"]["enabled"]=False
    config["rules"]=[{"id":"pair_adjacent","type":"cable_pair_order","group_by":"cable","order_by":"pair"}]
    data=pd.DataFrame([{"tag":"PAIR-1","io_type":"AI","cable":"C-1","pair":1},
                       {"tag":"PAIR-2","io_type":"AI","cable":"C-1","pair":2}])
    allocation,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs
    positions={s["slot_id"]:(s["adjacency_domain"],s["physical_sequence"]) for s in config["hardware"]["inventory"]["slots"]}
    first,second=[positions[x] for x in allocation.slot_id]
    assert first[0]==second[0] and second[1]==first[1]+1
    assert validate_allocation(allocation,config,data)==[]
    bad=allocation.copy(); bad.loc[0,"slot_id"]="CAB-A/CIOC-1/BP-1/CH-02"; bad.loc[0,"charm_slot"]="CH-02"; bad.loc[0,"terminal_block_id"]="TB-A:02"
    # Pair order now crosses BP-1 sequence 2 to BP-2 sequence 1.
    findings=validate_allocation(bad,config,data)
    assert any(f["rule_id"]=="pair_adjacent" and "physically consecutive" in f["issue"] for f in findings)

def test_inventory_schema_rejects_duplicate_physical_positions():
    import json
    inv=json.load(open("sample_data/synthetic_test_inventory.json",encoding="utf-8"))
    inv["slots"][1]["physical_sequence"]=1
    with pytest.raises(ValueError,match="Duplicate physical adjacency position"): validate_inventory(inv)

def test_pair_duplicate_numbers_are_tq_and_distinct_cables_are_independent(config):
    config=inventory_config(config); config["compatibility"]["enabled"]=False
    config["rules"]=[{"id":"pairs","type":"cable_pair_order","group_by":"cable","order_by":"pair"}]
    data=pd.DataFrame([{"tag":"P1","io_type":"AI","cable":"C1","pair":1},
                       {"tag":"P2","io_type":"AI","cable":"C1","pair":1}])
    result,tqs,status=allocate_signals(data,config)
    assert status=="UNRESOLVED_ENGINEERING_DATA" and all(t["tag"] in {"P1","P2"} for t in tqs)
    data.loc[1,"cable"]="C2"
    result,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs and not validate_allocation(result,config,data)

def test_per_cabinet_spare_is_hard_and_uses_floor_rounding(config):
    config["hardware"]={"cabinets":2,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":2}
    config["rules"]=[{"id":"cabinet_spare","type":"spare_capacity","level":"cabinet","minimum_percent":25,"basis":"physical"}]
    data=generate_signals(2,groups=1)
    allocation,tqs,status=allocate_signals(data,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs
    used=allocation.groupby("cabinet").size()
    assert all(count<=1 for count in used)
    too_many=generate_signals(3,groups=1)
    allocation,_,status=allocate_signals(too_many,config)
    assert status=="INFEASIBLE"

def test_revision_diff_distinguishes_changed_data_from_movement(config):
    old=generate_signals(2,groups=1); allocation,_,_=allocate_signals(old,config)
    new=old.copy(); new.loc[0,"io_type"]="AO"; new=pd.concat([new,generate_signals(1,seed=99).assign(tag="NEW")],ignore_index=True)
    new_allocation,_,_=allocate_signals(new,config)
    diff=compare_revisions(old,allocation,new,new_allocation).set_index("tag")
    assert diff.loc["NEW","revision_status"]=="ADDED"
    assert diff.loc[old.loc[0,"tag"],"revision_status"] in {"MODIFIED","MOVED"}
    unchanged,_,_=allocate_signals(old,config)
    same=compare_revisions(old,allocation,old,unchanged)
    assert set(same.revision_status)=={"UNCHANGED"}
    forced=allocation.copy(); forced.loc[0,"slot_id"]="other-slot"
    old_with_lifecycle=old.copy(); old_with_lifecycle.loc[0,"lifecycle"]="wired"
    moved=compare_revisions(old_with_lifecycle,allocation,old_with_lifecycle,forced,{"wired":77})
    assert moved.loc[moved.tag.eq(old.loc[0,"tag"]),"weighted_move_cost_points"].iloc[0]==77
    assert "no input/configuration change identified" in moved.loc[moved.tag.eq(old.loc[0,"tag"]),"movement_reason"].iloc[0]

def test_previous_locations_influence_revision_assignment_but_hard_compatibility_wins(config):
    config["hardware"]={"cabinets":1,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":2}
    config["rules"]=[]
    one=pd.DataFrame([{"tag":"STABLE-1","io_type":"AI"}])
    baseline,_,status=allocate_signals(one,config)
    assert status in {"OPTIMAL","FEASIBLE"}
    preferred=one.copy(); preferred["previous_location"]="CAB-01/CIOC-01/BP-01/CHARM-02"
    retained,_,status=allocate_signals(preferred,config)
    assert status in {"OPTIMAL","FEASIBLE"}
    assert retained.loc[0,"slot_id"]==preferred.loc[0,"previous_location"]
    assert baseline.loc[0,"slot_id"]!=retained.loc[0,"slot_id"]

    import json
    config["hardware"]={"cabinets":1,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":2,
                         "inventory":json.load(open("sample_data/synthetic_test_inventory.json",encoding="utf-8"))}
    config["compatibility"]={"enabled":True,"require_charm_type":True,"require_terminal_block_type":True,"require_isolation":True}
    config["rules"]=[]
    valid=pd.DataFrame([{"tag":"VALID-DO","io_type":"DO","charm_type":"TEST-DO","terminal_block_type":"TEST-TB-DO","isolation_required":"no","previous_location":"CAB-A/CIOC-1/BP-1/CH-01"}])
    placed,tqs,status=allocate_signals(valid,config)
    assert status in {"OPTIMAL","FEASIBLE"} and not tqs
    assert placed.loc[0,"slot_id"]!="CAB-A/CIOC-1/BP-1/CH-01"
    assert validate_allocation(placed,config,valid)==[]

def test_movement_reason_lists_observed_input_and_rule_changes(config):
    old=generate_signals(2,groups=1)
    previous,_,_=allocate_signals(old,config)
    new=old.copy(); new.loc[0,"io_type"]="DO" if old.loc[0,"io_type"]!="DO" else "AI"
    next_config={**config,"rules":[{"id":"reserve_demo","type":"spare_capacity","level":"global","minimum_percent":5}]}
    current=previous.copy()
    alternative=next(slot["slot_id"] for slot in build_slots(next_config) if slot["slot_id"] not in set(previous.slot_id))
    current.loc[0,"slot_id"]=alternative
    diff=compare_revisions(old,previous,new,current,previous_config=config,current_config=next_config)
    moved=diff.loc[diff.tag.eq(old.loc[0,"tag"])].iloc[0]
    assert moved.revision_status=="MOVED"
    assert "io_type" in moved.movement_reason
    assert "rule 'reserve_demo' added, removed, or changed" in moved.movement_reason
    assert moved.movement_reason_basis=="observed input/configuration changes"

def test_solver_unknown_is_not_reported_as_infeasible(config,monkeypatch):
    from src import allocator
    class Params: max_time_in_seconds=0; num_search_workers=0; random_seed=0
    class UnknownSolver:
        def __init__(self): self.parameters=Params()
        def Solve(self,model): return allocator.cp_model.UNKNOWN
        def StatusName(self,status): return "UNKNOWN"
    monkeypatch.setattr(allocator.cp_model,"CpSolver",UnknownSolver)
    allocation,tqs,status=allocate_signals(generate_signals(2),config)
    assert status=="UNKNOWN" and tqs and all(tq["category"]=="SOLVER_UNKNOWN" for tq in tqs)

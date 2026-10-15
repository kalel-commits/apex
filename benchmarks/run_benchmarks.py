"""Canonical synthetic benchmark runner. Each measured case runs in a fresh process."""
from __future__ import annotations
import hashlib, json, os, platform, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def fingerprint():
    digest=hashlib.sha256()
    for path in sorted([*ROOT.joinpath("src").glob("*.py"),ROOT/"rules.yaml",ROOT/"benchmarks"/"run_benchmarks.py"]):
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    return "sha256:"+digest.hexdigest()

def worker(case):
    import pandas as pd, psutil, ortools, yaml
    from src.synthetic import generate_signals
    from src.allocator import allocate_signals, build_slots
    from src.validator import validate_allocation
    from src.revisions import compare_revisions
    proc=psutil.Process(); start=time.perf_counter()
    if case["profile"]=="G-normal-scenario":
        from src.configuration import build_runtime_config
        from src.ingestion import load_input
        from src.inventory import load_inventory
        scenario=ROOT/"sample_data"/"stress_tests"/"normal"
        data=load_input(scenario/"signals_1000.xlsx")
        with (scenario/"inventory.json").open(encoding="utf-8") as stream: inventory=load_inventory(stream)
        cfg=build_runtime_config((scenario/"rules.yaml").read_text(encoding="utf-8"),inventory)
    elif case["profile"]=="E-infeasible":
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8")); cfg["hardware"]={"cabinets":1,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":4}; cfg["rules"]=[]; data=generate_signals(5,seed=20261010,groups=1)
    elif case["profile"]=="C-compatibility":
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8")); cfg["rules"]=[]
        data=generate_signals(case["n"],seed=case["seed"],groups=1)
        slots=[]
        for i,kind in enumerate(data.io_type,1):
            slots.append({"slot_id":f"SYN-CAB/CIOC-1/BP-{i:03d}/CH-01","cabinet":"SYN-CAB","cioc":"CIOC-1","baseplate":f"BP-{i:03d}","charm_slot":"CH-01","availability":"available","supported_io_types":[kind],"charm_type":f"SYN-{kind}","terminal_block_type":f"SYN-TB-{kind}","isolation":False,"fused":False,"injected_power":False})
        cfg["hardware"]={"inventory":{"schema_version":1,"source_authority":"synthetic","source_reference":"benchmark-generated fixture","slots":slots}}
        cfg["compatibility"]={"enabled":True,"require_charm_type":True,"require_terminal_block_type":True}
        data["charm_type"]="SYN-"+data.io_type; data["terminal_block_type"]="SYN-TB-"+data.io_type
    elif case["profile"]=="H-realistic-rules":
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8"))
        data=generate_signals(case["n"],seed=case["seed"],groups=12,redundancy_pairs=case["n"]//2)
        cfg["hardware"]={"cabinets":12,"ciocs_per_cabinet":4,"baseplates_per_cioc":1,"charms_per_baseplate":125}
        cfg["rules"]=[{"id":"groups","type":"group_together","group_by":"group","level":"cabinet"},
                      {"id":"ab","type":"separation","group_by":"redundancy_group","side_by":"redundancy_side","level":"cioc"},
                      {"id":"reserve","type":"spare_capacity","level":"cabinet","minimum_percent":10,"basis":"physical"}]
    else:
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8")); data=generate_signals(case["n"],seed=case["seed"],groups=1,redundancy_pairs=0)
        cfg["hardware"]={"cabinets":max(1,(case["n"]+119)//120),"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":120}
        cfg["rules"]=[]
        if case["profile"]=="B-realistic":
            data=generate_signals(case["n"],seed=case["seed"],groups=10,redundancy_pairs=min(10,case["n"]//2))
            cfg["hardware"]={"cabinets":4,"ciocs_per_cabinet":4,"baseplates_per_cioc":8,"charms_per_baseplate":12}
            cfg["rules"]=[{"id":"groups","type":"group_together","group_by":"group","level":"cabinet"},{"id":"ab","type":"separation","group_by":"redundancy_group","side_by":"redundancy_side","level":"cioc"},{"id":"reserve","type":"spare_capacity","level":"cabinet","minimum_percent":10,"basis":"physical"}]
    if case["profile"]=="D-revision":
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8")); cfg["hardware"]={"cabinets":4,"ciocs_per_cabinet":4,"baseplates_per_cioc":8,"charms_per_baseplate":12}; cfg["rules"]=[]
        initial=generate_signals(100,seed=case["seed"],groups=1)
        old,_,old_status=allocate_signals(initial,cfg)
        revised=pd.concat([initial,generate_signals(1,seed=case["seed"]+1).assign(tag="REV-ADDED")],ignore_index=True)
        prior=dict(zip(old.tag,old.slot_id)); revised["previous_location"]=revised.tag.map(prior).fillna("")
        comparisons=[]
        for name,preserve in (("fresh_baseline",False),("revision_aware",True)):
            current={**cfg,"optimization":{**cfg["optimization"],"preserve_previous_assignments":preserve}}
            t0=time.perf_counter(); out,tqs,st=allocate_signals(revised,current); seconds=time.perf_counter()-t0
            diff=compare_revisions(initial,old,revised,out,current["optimization"].get("move_costs",{}),current["optimization"].get("move_penalty",100))
            comparisons.append({"approach":name,"status":st,"runtime_seconds":seconds,"existing_moved":int(diff.revision_status.eq("MOVED").sum()),"lifecycle_weighted_move_cost_points":float(diff.weighted_move_cost_points.sum()),"added":int(diff.revision_status.eq("ADDED").sum()),"removed":int(diff.revision_status.eq("REMOVED").sum()),"unallocated":int((~out.status.eq("ALLOCATED")).sum()),"tqs":len(tqs),"validation_findings":len(validate_allocation(out,current,revised))})
        data=revised; allocation=out; tqs=tqs; status=st
        revision_metrics={"initial_status":old_status,"customer_changes":"one added signal; no removals or modifications","approaches":comparisons}
    elif case["profile"]=="F-fault-injection":
        cfg=yaml.safe_load((ROOT/"rules.yaml").read_text(encoding="utf-8")); cfg["hardware"]={"cabinets":1,"ciocs_per_cabinet":1,"baseplates_per_cioc":1,"charms_per_baseplate":8}; cfg["rules"]=[]
        data=generate_signals(4,seed=case["seed"],groups=1)
        allocation,_,status=allocate_signals(data,cfg); fault_results=[]
        for name,mutator,expected in (("duplicate_slot",lambda frame:frame.assign(slot_id=frame.slot_id.iloc[0]),"unique_slot"),("invalid_hierarchy",lambda frame:frame.assign(cabinet="CAB-INVALID"),"hierarchy_path")):
            corrupted=mutator(allocation.copy()); found=validate_allocation(corrupted,cfg,data); detected=any(item["rule_id"]==expected for item in found)
            fault_results.append({"fault":name,"expected_rule":expected,"detected":detected,"validator_findings":len(found)})
        tqs=[]; revision_metrics={"fault_injection":fault_results,"detected":sum(x["detected"] for x in fault_results),"total":len(fault_results)}
    else:
        revision_metrics=None
    if case["profile"]=="A-basic" and case["n"]==10000: cfg["optimization"]["time_limit_seconds"]=30
    cfg["optimization"]["num_search_workers"]=1
    memory_before=proc.memory_info().rss
    if case["profile"] not in {"D-revision","F-fault-injection"}: allocation,tqs,status=allocate_signals(data,cfg)
    elapsed=time.perf_counter()-start
    findings=validate_allocation(allocation,cfg,data)
    meta=allocation.attrs.get("metadata",{})
    slot_count=len([s for s in build_slots(cfg) if s.get("availability","available")=="available"])
    try: peak=proc.memory_info().peak_wset
    except AttributeError: peak=None
    objective=meta.get("objective"); bound=meta.get("best_bound")
    gap=abs(objective-bound)/max(abs(objective),1) if objective is not None and bound is not None else None
    allocated_count=int(allocation.status.eq("ALLOCATED").sum()); unallocated_count=int((~allocation.status.eq("ALLOCATED")).sum())
    fully_checked=(not findings and not tqs and unallocated_count==0 and status in {"OPTIMAL","FEASIBLE"})
    return {**case,"seed":case.get("seed",20261010),"git_commit":None,"source_version":fingerprint(),"python":sys.version.split()[0],"ortools":ortools.__version__,"os":platform.platform(),"cpu":platform.processor() or platform.machine(),"logical_cpus":os.cpu_count(),"total_physical_memory_bytes":psutil.virtual_memory().total,"active_constraints":[r["id"] for r in cfg["rules"] if r.get("enabled",True)],"solver_time_limit_seconds":cfg["optimization"].get("time_limit_seconds",30),"solver_workers":cfg["optimization"]["num_search_workers"],"solver_status":status,"allocation_returned":bool(allocation.status.eq("ALLOCATED").any()),"validation_checks_finding_free":not findings,"independent_validation_passed":fully_checked,"validation_findings":len(findings),"runtime_seconds":elapsed,"peak_working_set_bytes":peak,"peak_measurement":"psutil process peak_wset high-water mark; fresh child process per case","rss_before_bytes":memory_before,"signals":len(data),"available_slots":slot_count,"allocated":allocated_count,"unallocated":unallocated_count,"tq_count":len(tqs),"variables":meta.get("variables",0),"constraints":meta.get("constraints",0),"objective":objective,"best_bound":bound,"optimality_gap":gap,"inventory_authority":cfg["hardware"].get("inventory",{}).get("source_authority","synthetic configuration"),"tqs":tqs,"findings":findings,"revision_metrics":revision_metrics}

def main():
    if len(sys.argv)>2 and sys.argv[1]=="--worker":
        print(json.dumps(worker(json.loads(sys.argv[2])))); return
    cases=[]
    for n in (100,1000,5000,10000): cases.append({"profile":"A-basic","n":n,"seed":20261010})
    cases.append({"profile":"G-normal-scenario","n":1000,"seed":20261015})
    cases += [{"profile":"H-realistic-rules","n":1000,"seed":20261015},{"profile":"H-realistic-rules","n":5000,"seed":20261015}]
    cases += [{"profile":"B-realistic","n":100,"seed":222},{"profile":"C-compatibility","n":100,"seed":333},{"profile":"D-revision","n":100,"seed":919},{"profile":"E-infeasible","n":5,"seed":444},{"profile":"F-fault-injection","n":4,"seed":555}]
    rows=[]
    for case in cases:
        proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",json.dumps(case)],capture_output=True,text=True,timeout=180)
        if proc.returncode:
            rows.append({**case,"solver_status":"WORKER_FAILED","error":proc.stderr[-3000:],"stdout":proc.stdout[-1000:]})
        else: rows.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        print(json.dumps(rows[-1]),flush=True)
    payload={"schema_version":1,"generated_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"source_version":fingerprint(),"environment":{"python":sys.version.split()[0],"os":platform.platform()},"runs":rows}
    out=ROOT/"benchmarks"/"benchmark_results.json"; out.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    lines=["# Canonical Benchmark Report","",f"Generated: {payload['generated_utc']}","","Synthetic benchmark data only; results are not plant performance or vendor compliance.","","| Profile | Signals | Status | Allocated | TQs | Findings | Runtime (s) | Peak WSet (MiB) | Variables | Constraints |","|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows: lines.append(f"| {r['profile']} | {r['signals'] if 'signals' in r else r.get('n')} | {r.get('solver_status')} | {r.get('allocated','')} | {r.get('tq_count','')} | {r.get('validation_findings','')} | {r.get('runtime_seconds','')} | {round(r['peak_working_set_bytes']/1048576,1) if r.get('peak_working_set_bytes') else 'unavailable'} | {r.get('variables','')} | {r.get('constraints','')} |")
    revision=next((r.get("revision_metrics") for r in rows if r["profile"]=="D-revision"),None)
    if revision:
        lines += ["","## Revision comparison","","Synthetic revision: one added signal; same generated hardware. Lifecycle cost values are configured points, not money.","","| Approach | Status | Runtime (s) | Existing moves | Weighted move points | Added | Removed | Unallocated | TQs | Findings |","|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for item in revision["approaches"]: lines.append(f"| {item['approach']} | {item['status']} | {item['runtime_seconds']:.4f} | {item['existing_moved']} | {item['lifecycle_weighted_move_cost_points']} | {item['added']} | {item['removed']} | {item['unallocated']} | {item['tqs']} | {item['validation_findings']} |")
        example=ROOT/"examples"/"revision_impact.json"; example.parent.mkdir(exist_ok=True); example.write_text(json.dumps(revision,indent=2),encoding="utf-8")
    faults=next((r.get("revision_metrics") for r in rows if r["profile"]=="F-fault-injection"),None)
    if faults:
        lines += ["","## Benchmark fault injection","",f"Detected {faults['detected']}/{faults['total']} injected cases.",""]
        for item in faults["fault_injection"]: lines.append(f"- {item['fault']}: detected={item['detected']}; expected `{item['expected_rule']}`; validator findings={item['validator_findings']}.")
    (ROOT/"benchmarks"/"BENCHMARK_REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
if __name__=="__main__": main()

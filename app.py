"""Engineer-facing Streamlit orchestration; allocation authority comes from supplied data."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from src.allocator import allocate_signals, build_slots
from src.configuration import (
    build_runtime_config,
    configuration_fingerprint,
    require_expected_inventory,
    result_matches_fingerprint,
)
from src.ingestion import load_input
from src.inventory import load_inventory, validate_inventory
from src.reporting import build_excel_report, build_template_report, summarize_tqs, summarize_utilization
from src.revisions import compare_revisions
from src.validator import validate_allocation


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _active_config_summary(signals: pd.DataFrame, config: dict, signal_source: str, inventory_upload: str, rules_source: str) -> dict:
    inventory = config.get("hardware", {}).get("inventory")
    slots = build_slots(config)
    enabled = [rule for rule in config.get("rules", []) if rule.get("enabled", True)]
    reserve_rules = [rule for rule in enabled if rule.get("type") == "spare_capacity"]
    optimization = config.get("optimization", {})
    return {
        "Signal input": signal_source,
        "Signal count": len(signals),
        "Inventory": "Explicit uploaded inventory" if inventory is not None else "Synthetic hierarchy (no explicit inventory)",
        "Inventory upload": inventory_upload if inventory is not None else "None",
        "Inventory source": inventory.get("source_reference", "unspecified") if inventory is not None else "Generated from hardware counts",
        "Inventory authority": inventory.get("source_authority", "unspecified") if inventory is not None else "synthetic/incomplete",
        "Physical slots": len(slots),
        "Available slots": sum(slot.get("availability", "available") == "available" for slot in slots),
        "Rules source": rules_source,
        "Active rule IDs": [rule["id"] for rule in enabled],
        "Enabled rules": len(enabled),
        "Spare capacity": [
            {"rule_id": rule["id"], "minimum_percent": rule.get("minimum_percent", 0), "basis": rule.get("basis", "physical")}
            for rule in reserve_rules
        ],
        "Compatibility": config.get("compatibility", {"enabled": False}),
        "Solver time limit (seconds)": optimization.get("time_limit_seconds", 30),
        "Solver workers": optimization.get("num_search_workers", 1),
    }


st.set_page_config(page_title="IO Signal Sudoku", page_icon="🧩", layout="wide")
st.markdown("""<style>
  .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1500px;}
  [data-testid="stMetric"] {background: #f4f7fa; border: 1px solid #dce5ec; padding: .7rem 1rem; border-radius: .55rem;}
  [data-testid="stMetricLabel"] {color: #385064;}
  h1, h2, h3 {color: #14344a;}
</style>""", unsafe_allow_html=True)
st.title("IO Signal Sudoku")
st.caption("Configurable I/O allocation with independent checks. A feasible synthetic model is not proof of vendor or plant compliance.")
default_rules = Path("rules.yaml").read_text(encoding="utf-8")
default_rules_digest = _digest(default_rules.encode("utf-8"))

input_tab, rules_tab, results_tab = st.tabs(["1 · Input & inventory", "2 · Rules", "3 · Allocate & report"])

with input_tab:
    upload = st.file_uploader("Signal list (.xlsx or .csv)", type=["xlsx", "csv"], key="signal_upload")
    if upload is not None:
        raw_signals = upload.getvalue()
        signal_digest = _digest(raw_signals)
        if signal_digest != st.session_state.get("signal_digest"):
            try:
                st.session_state["signals"] = load_input(upload)
                st.session_state["signal_digest"] = signal_digest
                st.session_state["signal_source"] = upload.name
            except Exception as exc:
                st.session_state.pop("signals", None)
                st.session_state.pop("signal_digest", None)
                st.error(f"Input requires correction: {exc}")
        if "signals" in st.session_state:
            data = st.session_state["signals"]
            st.success(f"Loaded {len(data):,} normalized signals from {st.session_state.get('signal_source', upload.name)}.")
            st.dataframe(data.head(100), use_container_width=True)
    elif st.session_state.get("signal_digest"):
        for key in ("signals", "signal_digest", "signal_source"):
            st.session_state.pop(key, None)
        st.warning("Signal upload was cleared. Upload a workbook before allocating.")

    inv_upload = st.file_uploader("Optional explicit hardware inventory (.json)", type=["json"], key="inventory_upload")
    if inv_upload is not None:
        raw_inventory = inv_upload.getvalue()
        inventory_digest = _digest(raw_inventory)
        if inventory_digest != st.session_state.get("inventory_digest"):
            try:
                st.session_state["inventory"] = load_inventory(inv_upload)
                st.session_state["inventory_digest"] = inventory_digest
                st.session_state["inventory_source_name"] = inv_upload.name
                st.session_state.pop("inventory_upload_error", None)
            except Exception as exc:
                for key in ("inventory", "inventory_digest", "inventory_source_name"):
                    st.session_state.pop(key, None)
                st.session_state["inventory_upload_error"] = f"Inventory rejected: {exc}"
                st.error(f"Inventory rejected: {exc}")
        if "inventory" in st.session_state:
            inventory = st.session_state["inventory"]
            validate_inventory(inventory)
            available_count = sum(slot["availability"] == "available" for slot in inventory["slots"])
            st.info(f"Inventory accepted: {inventory['source_authority']} authority · {len(inventory['slots']):,} physical slots · {available_count:,} available slots")
    elif st.session_state.get("inventory_digest"):
        for key in ("inventory", "inventory_digest", "inventory_source_name"):
            st.session_state.pop(key, None)
        st.warning("Explicit inventory upload was cleared; the active configuration has no uploaded inventory.")
    elif inv_upload is None:
        st.session_state.pop("inventory_upload_error", None)

    template_upload = st.file_uploader("Optional allocation template workbook (.xlsx)", type=["xlsx"], key="template_upload")
    if template_upload is not None:
        template_bytes = template_upload.getvalue()
        template_digest = _digest(template_bytes)
        if template_digest != st.session_state.get("template_digest"):
            st.session_state["template_bytes"] = template_bytes
            st.session_state["template_digest"] = template_digest
            st.session_state["template_source_name"] = template_upload.name
    elif st.session_state.get("template_digest"):
        for key in ("template_bytes", "template_digest", "template_source_name"):
            st.session_state.pop(key, None)

    st.caption("Unfamiliar column names require explicit mapping through the ingestion API; safety-critical fields are not guessed by text similarity.")
    if "signals" not in st.session_state:
        st.info("Upload a signal list, or try sample_data/sample_signals.xlsx.")

with rules_tab:
    if "rules_text" not in st.session_state:
        st.session_state["rules_text"] = default_rules
        st.session_state["rules_source"] = "project default: rules.yaml"
        st.session_state["rules_digest"] = default_rules_digest
    rules_upload = st.file_uploader("Optional scenario rules YAML", type=["yaml", "yml"], key="scenario_rules_upload")
    if rules_upload is not None:
        uploaded_rules = rules_upload.getvalue()
        uploaded_digest = _digest(uploaded_rules)
        if uploaded_digest != st.session_state.get("scenario_rules_digest"):
            st.session_state["scenario_rules_digest"] = uploaded_digest
            try:
                st.session_state["rules_text"] = uploaded_rules.decode("utf-8-sig")
                st.session_state["rules_source"] = f"uploaded scenario: {rules_upload.name}"
                st.session_state["rules_digest"] = _digest(st.session_state["rules_text"].encode("utf-8"))
            except UnicodeDecodeError:
                st.session_state["rules_error"] = "Rules file must be UTF-8 encoded YAML."
    elif st.session_state.get("scenario_rules_digest"):
        st.session_state.pop("scenario_rules_digest", None)
        st.session_state["rules_text"] = default_rules
        st.session_state["rules_source"] = "project default: rules.yaml"
        st.session_state["rules_digest"] = default_rules_digest
        st.session_state.pop("rules_error", None)

    st.text_area("Versioned rules.yaml", height=360, key="rules_text")
    rules_text = st.session_state["rules_text"]
    active_rules_digest = _digest(rules_text.encode("utf-8"))
    if active_rules_digest != st.session_state.get("rules_digest"):
        st.session_state["rules_source"] = f"edited in rules editor (from {st.session_state.get('rules_source', 'unknown source')})"
        st.session_state["rules_digest"] = active_rules_digest
    if st.session_state.get("rules_error"):
        st.error(st.session_state["rules_error"])
    st.download_button("Download reusable rules YAML", rules_text, file_name="io_signal_sudoku_rules.yaml", mime="application/yaml")
    if st.button("Validate and save rules"):
        try:
            parsed = build_runtime_config(rules_text, st.session_state.get("inventory"))
            if st.session_state.get("inventory_upload_error"):
                raise ValueError(st.session_state["inventory_upload_error"])
            if st.session_state.get("rules_error"):
                raise ValueError(st.session_state["rules_error"])
            require_expected_inventory(parsed)
            st.session_state["config"] = parsed
            st.success("Configuration is valid for supported rule types and required inputs are present.")
        except Exception as exc:
            st.error(str(exc))

with results_tab:
    signals = st.session_state.get("signals")
    active_config = None
    active_fingerprint = None
    config_error = None
    if signals is None:
        st.warning("Upload a signal list first.")
    else:
        try:
            if st.session_state.get("inventory_upload_error"):
                raise ValueError(st.session_state["inventory_upload_error"])
            if st.session_state.get("rules_error"):
                raise ValueError(st.session_state["rules_error"])
            active_config = build_runtime_config(rules_text, st.session_state.get("inventory"))
            require_expected_inventory(active_config)
            active_fingerprint = configuration_fingerprint(signals, active_config)
            st.subheader("Active allocation configuration")
            st.json(_active_config_summary(
                signals,
                active_config,
                st.session_state.get("signal_source", "in-memory signal data"),
                st.session_state.get("inventory_source_name", "None"),
                st.session_state.get("rules_source", "rules editor"),
            ))
            st.caption(f"Configuration fingerprint: `{active_fingerprint}`")
        except Exception as exc:
            config_error = str(exc)
            st.error(f"Configuration is not ready: {config_error}")

    allocate_clicked = st.button("Allocate and independently validate", type="primary", disabled=(signals is None or active_config is None))
    if allocate_clicked and active_config is not None and signals is not None:
        try:
            solve_signals = signals.copy()
            previous_allocation = st.session_state.get("last_result")
            previous_input = st.session_state.get("last_input")
            previous_config = st.session_state.get("last_config")
            if previous_allocation is not None and "tag" in previous_allocation and "slot_id" in previous_allocation:
                previous_locations = previous_allocation.loc[
                    previous_allocation.get("status", pd.Series(index=previous_allocation.index, dtype=str)).eq("ALLOCATED"),
                    ["tag", "slot_id"],
                ].drop_duplicates("tag").set_index("tag")["slot_id"]
                solve_signals["previous_location"] = solve_signals["tag"].astype(str).map(previous_locations).fillna("")
            with st.status("Validating inputs and preparing allocation…", expanded=True) as progress:
                progress.update(label="Running CP-SAT allocation…", state="running")
                allocation, tqs, status = allocate_signals(solve_signals, active_config)
                progress.update(label=f"Solver finished: {status}. Running independent validation…", state="running")
                validation = validate_allocation(allocation, active_config, signals)
                progress.update(label=f"Allocation workflow completed: {status}", state="complete" if status in {"OPTIMAL", "FEASIBLE"} else "error")
            revision = compare_revisions(
                previous_input, previous_allocation, signals, allocation,
                active_config.get("optimization", {}).get("move_costs", {}),
                active_config.get("optimization", {}).get("move_penalty", 100),
                previous_config=previous_config, current_config=active_config,
            ) if previous_input is not None and previous_allocation is not None else None
            st.session_state["last_input"] = signals.copy()
            st.session_state["last_result"] = allocation.copy()
            st.session_state["last_config"] = active_config
            st.session_state["result"] = {
                "allocation": allocation, "tqs": tqs, "status": status, "validation": validation,
                "revision": revision, "config": active_config, "fingerprint": active_fingerprint,
            }
        except Exception as exc:
            st.error(f"Allocation did not complete: {exc}")

    stored_result = st.session_state.get("result")
    if stored_result is not None:
        is_current = result_matches_fingerprint(stored_result.get("fingerprint"), active_fingerprint)
        if not is_current:
            st.warning("The displayed allocation result is stale because the active signal data, inventory, rules, or solver configuration changed. Run allocation again to refresh it.")
            st.caption(f"Result fingerprint: `{stored_result.get('fingerprint', 'unavailable')}` · Active fingerprint: `{active_fingerprint or 'unavailable'}`")
        else:
            allocation = stored_result["allocation"]
            tqs = stored_result["tqs"]
            status = stored_result["status"]
            validation = stored_result["validation"]
            revision = stored_result["revision"]
            config = stored_result["config"]
            meta = allocation.attrs.get("metadata", {})
            allocated_count = int(allocation.status.eq("ALLOCATED").sum())
            unallocated_count = int((~allocation.status.eq("ALLOCATED")).sum())
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Solver", status)
            m2.metric("Allocated", allocated_count)
            m3.metric("Unallocated", unallocated_count)
            m4.metric("TQs", len(tqs))
            m5.metric("Validation findings", len(validation))
            st.caption(f"Runtime {meta.get('runtime_seconds', 0):.3f}s · result fingerprint `{stored_result['fingerprint']}`")
            if status == "INFEASIBLE":
                st.error("The solver proved this configuration has no feasible full assignment. Review the TQs and capacity/rule inputs.")
            elif status == "UNKNOWN":
                st.warning("The solver did not find or prove a feasible assignment within the configured time limit. UNKNOWN is not proof of infeasibility.")
            elif status == "FEASIBLE":
                st.info("A valid assignment was found, but the solver did not prove it optimal within the configured limit.")
            elif status == "OPTIMAL":
                st.success("A feasible assignment was found and optimality was proven for the configured objective.")
            st.write("Mandatory check coverage is limited to configured and implemented rules. A clean result is not vendor-certified.")
            utilization = summarize_utilization(allocation, config)
            st.subheader("Cabinet utilization and spare capacity")
            if not utilization.empty:
                used_cabinets = int((utilization.allocated > 0).sum())
                cabinet_metric, capacity_note = st.columns([1, 4])
                cabinet_metric.metric("Cabinets occupied", used_cabinets, help="Count of configured cabinets with at least one signal in this result.")
                capacity_note.caption(f"{len(utilization)} cabinets are represented in the configured inventory/hierarchy. Occupied-cabinet count describes this assignment; it is not a minimum-cabinet optimization claim.")
                st.dataframe(utilization, use_container_width=True, hide_index=True)
                st.bar_chart(utilization.set_index("cabinet")[["allocated", "spare_slots"]], height=260)
            st.subheader("Allocation details")
            allocation_query = st.text_input("Search allocation rows", placeholder="Tag, description, type, cabinet, slot…", key="allocation_search")
            allocation_view = allocation
            if allocation_query.strip():
                mask = allocation.astype(str).apply(lambda column: column.str.contains(allocation_query.strip(), case=False, regex=False)).any(axis=1)
                allocation_view = allocation.loc[mask]
            st.dataframe(allocation_view, use_container_width=True, height=430)
            tq_tab, tq_summary_tab, validation_tab = st.tabs([f"Technical queries ({len(tqs)})", "TQ causes", f"Validation findings ({len(validation)})"])
            with tq_tab:
                tq_frame = pd.DataFrame(tqs)
                tq_query = st.text_input("Search technical queries", placeholder="Tag, reason, rule, or suggestion…", key="tq_search")
                if tq_query.strip() and not tq_frame.empty:
                    tq_mask = tq_frame.astype(str).apply(lambda column: column.str.contains(tq_query.strip(), case=False, regex=False)).any(axis=1)
                    tq_frame = tq_frame.loc[tq_mask]
                st.dataframe(tq_frame, use_container_width=True, height=360)
            with tq_summary_tab:
                tq_summary = summarize_tqs(tqs)
                st.caption("Grouped by identical emitted category, rule, reason, and suggestion; this does not infer a shared causal root.")
                st.dataframe(tq_summary, use_container_width=True, height=360)
            with validation_tab:
                st.dataframe(pd.DataFrame(validation), use_container_width=True, height=360)
            if revision is not None:
                st.subheader("Revision comparison")
                st.dataframe(revision, use_container_width=True)
            if validation:
                st.error("Independent checks found errors or unsupported requirements.")
            elif tqs or unallocated_count:
                st.warning("Some signals remain unresolved. Review the TQs before using the report.")
            else:
                st.success("All input signals are allocated and implemented independent checks passed.")
            st.download_button(
                "Download full Excel report",
                build_excel_report(allocation, tqs, validation, metadata=meta, revision=revision, config=config),
                file_name="io_allocation_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            template_mapping = config.get("reporting", {}).get("template_mapping") if isinstance(config.get("reporting", {}), dict) else None
            if st.session_state.get("template_bytes") is not None:
                if template_mapping:
                    try:
                        template_output = build_template_report(allocation, st.session_state["template_bytes"], template_mapping)
                        st.download_button("Download mapped allocation template", template_output, file_name="io_allocation_template_filled.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception as exc:
                        st.error(f"Template export failed: {exc}")
                else:
                    st.info("A template workbook is uploaded, but `reporting.template_mapping` is not configured in the rules YAML. The full standard report remains available above.")

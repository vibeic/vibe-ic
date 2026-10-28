"""Exercise source-owned selection through the canonical front door.

These are configuration/dispatch tests, not EDA qualification or IC PASS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import _path_layout as layout
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow109
from programs.tests._hostpaths import require_repo


def profile(name="Small digital IC without DFT"):
    registry = flow109.load_registry()
    return copy.deepcopy(next(p["features"] for p in registry["reference_profiles"] if p["name"] == name))


def test_d05_position5_routes_only_structural_native_evidence_to_existing_frontend():
    features = profile()
    features["has_power_intent"] = True
    plan = flow109.resolve_plan(features)
    row = flow109.resolve_step(plan, "D05")

    assert row["profile"]["execution_status"] == (
        "NATIVE_COMPONENT_ONLY_ROW_METRICS_NOT_MEASURED")
    dispatch = flow109.source_owned_native_dispatch(row)

    assert row["position"] == 5
    assert dispatch["adapter"] == "flow109_frontend"
    assert dispatch["producer"] == "l21_to_upf_emit.py:main"
    assert dispatch["consumer"] == "flow109_frontend.py:_execute_d05"
    assert row["profile"]["native_steps"] == [
        "OpenROAD.read_upf", "OpenROAD.eval_upf"]
    assert row["metric_acceptance_status"] == (
        "NOT_MEASURED_NATIVE_METHOD_UNAVAILABLE")
    assert {item["metric"]: item["status"] for item in row["obligations"]} == {
        "semantic_demand_coverage": "NOT_MEASURED_NATIVE_METHOD_UNAVAILABLE",
        "illegal_power_states": "NOT_MEASURED_NATIVE_METHOD_UNAVAILABLE",
        "supply_cell_assignments": "NOT_MEASURED_NATIVE_METHOD_UNAVAILABLE",
    }


def test_source_mapping_preserves_native_identity_and_unfiltered_position():
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "phase1_phase2_phase3.yaml")
    import yaml
    native = yaml.safe_load(source.read_text())["steps"]
    plan = flow109.resolve_plan(profile())
    cts = flow109.resolve_step(plan, "D38")
    assert cts["legacy70"] == [{"position": 34, "id": "19", "name": native[33]["name"]}]
    assert cts["position"] > 34
    assert cts["profile"]["dispatch"]["native_step_id"] == "19"
    assert cts["tool_uses"][0]["use_id"] == "flow109.D38.default.openroad"
    assert plan["runtime_verdict"] == plan["flow109_acceptance"] == "NOT_MEASURED"
    assert [g["id"] for g in plan["gate_layers"]] == [f"G{i}" for i in range(1, 10)]
    assert cts["gate_matrix_status"] == "NOT_MEASURED_FOR_109"


def test_reference_profiles_close_without_turning_unknown_into_false():
    for item in flow109.load_registry()["reference_profiles"]:
        plan = flow109.resolve_plan(item["features"])
        assert plan["selected_count"] > 0
        assert plan["status"] == "PLAN_RESOLVED_NOT_EXECUTED"
    features = profile()
    del features["has_digital"]
    with pytest.raises(flow109.Flow109Error, match="FEATURE_UNRESOLVED"):
        flow109.resolve_plan(features)


def _write_dft_intent(project, monkeypatch, *, scan, bist=False, route='ic'):
    import fault_scan_chain_insert as producer
    intent = {"requires_scan": scan, **({"reason": "test declares scan not required"} if not scan else {})}
    if scan:
        from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
        intent = _intent()
    _publish_dft_intent(project, intent, route=route)
    binding, problems = producer.load_d09_dft_contract(project)
    assert problems == [] and binding is not None
    return binding


def _publish_dft_intent(project, intent, *, route='ic'):
    import _delivery_route
    assert _delivery_route.admit(project, route) is None
    import spec_declaration_emit as declaration
    docs = project / "input/docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L7_verification_plan.md").write_text(
        "# Verification\nThe Plugin MUST declare `plugin_output/declaration.json` "
        "before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n"
        "| `dft` | Yes | object |\n")
    (project / 'input/feature-decisions.json').write_text(json.dumps({'dft': intent}))
    assert declaration.main(
        [str(project), "--set", "dft=" + json.dumps(intent)]) == 0
    import phase1_one_shot_runner as phase1
    output = phase1._d01_emit_dft_intent(project)
    if output is not None:
        report = layout.report_path(project, 'phase1_one_shot.json')
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'project': str(project.resolve()), **__import__('_delivery_route').report_label(project), 'dft_intent_output': output}))


def test_d09_scan_intent_is_source_bound_without_author_chain_length(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    context = flow109.execution_context(flow109.resolve_plan(features), "D22", "D22")
    _write_dft_intent(tmp_path, monkeypatch, scan=True, route='ip')

    intent = flow109.dft_source_intent(tmp_path, context)

    assert intent["requires_scan"] is True
    assert intent["source_binding"]["intent"]["test_port_def"]["scan_in"] == {
        "public": "scan_in", "native": "sin"}
    assert intent["realized_chain_length"] == "NOT_YET_REALIZED"
    assert "declared_chain_length" not in intent


def test_explicit_no_scan_skips_only_d23_d24_and_keeps_d25_d26(tmp_path, monkeypatch):
    features = profile("Small digital IC without DFT")
    plan = flow109.resolve_plan(features)
    selected = {row["id"] for row in plan["rows"]}
    _write_dft_intent(tmp_path, monkeypatch, scan=False)
    context = flow109.execution_context(plan, "D22", "D22")

    intent = flow109.dft_source_intent(tmp_path, context)

    assert intent["requires_scan"] is False
    assert {"D23", "D24"}.isdisjoint(selected)
    assert {"D25", "D26"}.issubset(selected)
    assert plan["conditional_skips"] == []


@pytest.mark.parametrize("step,native_entry", [("D25", "11"), ("D26", "10")])
def test_explicit_authoritative_no_scan_still_starts_d25_d26_real_owner(
        tmp_path, monkeypatch, step, native_entry):
    import _delivery_route
    features = profile("Small digital IC without DFT")
    _write_dft_intent(tmp_path, monkeypatch, scan=False)
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"features": features}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step=step, exit_step=step, container="")

    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == native_entry
    route = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert route["native_step_id"] == {"D25": "13", "D26": "10"}[step]
    plan = json.loads((tmp_path / "reports/flow109/plan.json").read_text())
    assert all(row["source_validated"] for row in plan["conditional_skips"])


def test_scan_compression_and_bist_applicability_are_not_exclusive(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    features["requires_scan"] = False
    plan = flow109.resolve_plan(features)
    _write_dft_intent(tmp_path, monkeypatch, scan=False, bist=True, route='ip')

    intent = flow109.dft_source_intent(
        tmp_path, flow109.execution_context(plan, "D22", "D22"))

    selected = {row["id"] for row in plan["rows"]}
    assert intent["source_binding"]["intent"]["requires_scan"] is False
    assert "D52" in selected
    assert {"D23", "D24"}.issubset(selected)
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"features": features}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D25", exit_step="D25", container="")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == "11"


@pytest.mark.parametrize("damage,code", [
    ("missing", "FLOW109_DFT_INTENT_MISSING"),
    ("malformed", "D09_DFT_AUTHORITY_INVALID"),
    ("forged", "D09_DFT_AUTHORITY_INVALID")])
def test_d09_dft_intent_refuses_missing_malformed_or_conflicting_source(
        tmp_path, monkeypatch, damage, code):
    features = profile("Mapped soft-IP with prestitched scan")
    context = flow109.execution_context(flow109.resolve_plan(features), "D22", "D22")
    if damage == "malformed":
        _publish_dft_intent(tmp_path, {"requires_scan": "false"}, route='ip')
    elif damage == "forged":
        _write_dft_intent(tmp_path, monkeypatch, scan=True, route='ip')
        source = tmp_path / "input/docs/L7_verification_plan.md"
        source.write_text(source.read_text() + "\nforged\n")

    with pytest.raises(flow109.Flow109Error, match=code):
        flow109.dft_source_intent(tmp_path, context)


def test_old_three_role_d09_intent_fails_closed(tmp_path, monkeypatch):
    intent = {"requires_scan": True,
              "test_port_def": {
                  "scan_enable": {"public": "scan_enable", "native": "shift"},
                  "scan_in": {"public": "scan_in", "native": "sin"},
                  "scan_out": {"public": "scan_out", "native": "sout"}},
              "test_mode": {"clock": "clk", "clock_domains": ["clk"],
                            "edge": "rising", "reset": {"signal": "rst",
                            "style": "synchronous", "active_level": 1,
                            "shift_value": 0}}}
    _publish_dft_intent(tmp_path, intent, route='ip')
    features = profile("Mapped soft-IP with prestitched scan")
    context = flow109.execution_context(flow109.resolve_plan(features), "D22", "D22")

    with pytest.raises(flow109.Flow109Error, match="D09_DFT_AUTHORITY_INVALID"):
        flow109.dft_source_intent(tmp_path, context)


def _d30_scan_case(project, monkeypatch, top="neutral_unit"):
    import hashlib
    import fault_scan_chain_insert as producer
    from programs.tests.test_issue3444_l20_scan_reconciliation import (
        _intent, _native_payload, _planned)
    dft = _intent(); dft['dft_plan'] = {'planned_chain_count': 1, 'max_chain_length': 32}
    _planned(project, dft, route='ip')
    calls = _native_payload(project, monkeypatch)
    rc, report = producer.run_chain(
        project, "phase2/stage2/synth/netlist.v", "clk", "sky130",
        reset="rst", skip_boundary="on", top_module="neutral_unit",
        require_l20_contract=True)
    assert rc == 0 and report["published"] is True and len(calls) == 1
    assert producer.l20_binding_is_current(project, report)[0] is True
    # Mirror the released D23 caller's post-consumption publication bit.  The
    # actual currentness consumer above, not this bit alone, authorizes it.
    report["authorized_by_l20_contract"] = True
    scan_sdc = project / "phase2/stage2/dft/scan_mode.sdc"
    scan_sdc.parent.mkdir(parents=True, exist_ok=True)
    scan_sdc.write_text(
        "create_clock -period 100.0 [get_ports {tck}]\n"
        "set_case_analysis 1 [get_ports {shift}]\n"
        "set_case_analysis 1 [get_ports {test}]\n")
    l20 = report["l20_contract"]
    report["scan_mode_constraint"] = {
        "kind": "scan_shift_clock", "path": str(scan_sdc.relative_to(project)),
        "sha256": hashlib.sha256(scan_sdc.read_bytes()).hexdigest(),
        "l20_path": l20["path"], "l20_sha256": l20["sha256"],
        "clock": "tck", "frequency_mhz": "10.0", "period_ns": "100.0"}
    # This fixture already exercised the real currentness reader above.  Its
    # added timing actuator is the sealed D26 API input under review here.
    monkeypatch.setattr(producer, "l20_binding_is_current", lambda *_: (True, "current"))
    scan_report = project / producer.SCAN_JSON_REL
    scan_report.parent.mkdir(parents=True, exist_ok=True)
    scan_report.write_text(json.dumps(report))
    synth = project / "phase2/stage2/synth"
    post = synth / "post_dft_netlist.v"
    post.write_bytes((project / producer.SCAN_NETLIST_REL).read_bytes())
    dft = project / "reports/phase2/dft"
    reports = project / "reports"; reports.mkdir(exist_ok=True)
    digest = "sha256:" + hashlib.sha256(post.read_bytes()).hexdigest()
    (reports / "lec.json").write_text(json.dumps({
        "verdict": "PASS", "equivalent": True,
        "proof_identity": {"top": top, "gate_netlist": {
            "path": "phase2/stage2/synth/post_dft_netlist.v", "sha256": digest}},
        "scan_functional_mode": {"requested": True, "applied": True}}))
    (project / "input/flow109").mkdir(parents=True)
    (project / "input/flow109/D22.json").write_text(json.dumps({"top": top}))
    rows = project / "reports/flow109/default_rows"; rows.mkdir(parents=True)
    for step in ("D25", "D26"):
        (rows / f"{step}.json").write_text(json.dumps({
            "step_id": step, "default_row_status": "PASS", "completed": True}))
    (rows / "D24.json").write_text(json.dumps({
        "step_id": "D24", "default_row_status": "PASS", "completed": True,
        "adopted_netlist": {"artifact_id": "D24_POST_SCAN_NETLIST",
            "path": "phase2/stage2/synth/post_dft_netlist.v",
            "sha256": hashlib.sha256(post.read_bytes()).hexdigest()},
        "native_scan_report": {"path": "reports/phase2/dft/scan_chain.json",
            "sha256": hashlib.sha256((dft / "scan_chain.json").read_bytes()).hexdigest()}}))
    adopted = json.loads((rows / "D24.json").read_text())["adopted_netlist"]
    base_sdc = project / "phase2/stage2/constraints/neutral_unit.sdc"
    base_sdc.parent.mkdir(parents=True)
    base_sdc.write_text("create_clock -period 10.0 [get_ports {clk}]\n")
    functional_sdc = project / "reports/flow109/d26_timing/functional_post_scan.sdc"
    functional_sdc.parent.mkdir(parents=True)
    functional_sdc.write_text(
        "create_clock -period 10.0 [get_ports {clk}]\n"
        "set_case_analysis 0 [get_ports {test}]\n"
        "set_case_analysis 0 [get_ports {shift}]\n"
        "set_case_analysis 0 [get_ports {sin}]\n"
        "set_case_analysis 0 [get_ports {tck}]\n"
        "set_case_analysis 0 [get_ports {rst}]\n")
    functional_native = project / "phase3/librelane/d26_post_scan_functional/vibeic_receipt.json"
    scan_native = project / "phase3/librelane/d26_post_scan_scan/vibeic_receipt.json"
    ref = lambda path: {"path": str(path.relative_to(project)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    for mode, native in (("functional", functional_native), ("scan", scan_native)):
        native.parent.mkdir(parents=True)
        state_in = native.parent / "state_in.json"
        state_in.write_text(json.dumps({"nl": str(post.resolve())}))
        native.write_text(json.dumps({"input": {"step": "OpenROAD.STAPrePNR",
            "state": hashlib.sha256(state_in.read_bytes()).hexdigest(),
            "state_files": {str(post.resolve()): hashlib.sha256(post.read_bytes()).hexdigest()}},
            "sha256": {"state_in.json": hashlib.sha256(state_in.read_bytes()).hexdigest()}}))
        (native.parent / "config.json").write_text(json.dumps({
            "PNR_SDC_FILE": str((functional_sdc if mode == "functional" else
                                  project / report["scan_mode_constraint"]["path"]).resolve())}))
        (native.parent / "state_out.json").write_text(json.dumps({"nl": str(post.resolve())}))
    import librelane_contract
    monkeypatch.setattr(librelane_contract, "validate_step_receipt",
                        lambda folder, *_: json.loads((folder / "vibeic_receipt.json").read_text()))
    gates = project / "reports/flow109/d26_timing"; gates.mkdir(parents=True, exist_ok=True)
    intent = flow109.dft_source_intent(
        project, flow109.execution_context(
            flow109.resolve_plan(profile("Mapped soft-IP with prestitched scan")),
            "D30", "D30"))
    functional_constraint = {**ref(functional_sdc), "mode": "functional",
        "base_sdc": ref(base_sdc), "clock": "clk",
        "clock_select": "test", "clock_select_value": 0,
        "scan_enable": "shift", "scan_enable_value": 0,
        "scan_input": "sin", "scan_input_value": 0,
        "scan_clock": "tck", "scan_clock_value": 0,
        "reset": "rst", "reset_value": 0,
        "d09_path": intent["source_binding"]["path"],
        "d09_sha256": intent["source_binding"]["sha256"]}
    scan_constraint = {**report["scan_mode_constraint"], "mode": "scan"}
    gate_refs = {}
    for mode, constraint in (("functional", functional_constraint),
                             ("scan", scan_constraint)):
        native = functional_native if mode == "functional" else scan_native
        state_sha = hashlib.sha256((native.parent / "state_out.json").read_bytes()).hexdigest()
        sdc_gate = gates / f"{mode}_sdc_gate.json"
        sdc_gate.write_text(json.dumps({"verdict": "PASS", "findings": [],
            "netlist_sha256": adopted["sha256"], "sdc_sha256": constraint["sha256"],
            "state_out_sha256": state_sha,
            "corners": {"tt": {"check_setup": {}}}}))
        slack_gate = gates / f"{mode}_slack_gate.json"
        slack_gate.write_text(json.dumps({"verdict": "PASS", "findings": [],
            "state_out_sha256": state_sha,
            "corners": {"tt": {"setup_ws": {"status": "MEASURED", "value": 0.1},
                                "hold_ws": {"status": "MEASURED", "value": 0.1}}}}))
        gate_refs[mode] = {
            "sdc_gate": {**ref(sdc_gate), "verdict": "PASS", "findings": [],
                         "corners": {"tt": {"check_setup": {}}}},
            "slack_gate": {**ref(slack_gate), "verdict": "PASS", "findings": [],
                "corners": {"tt": {"setup_ws": {"status": "MEASURED", "value": 0.1},
                                    "hold_ws": {"status": "MEASURED", "value": 0.1}}}}}
    def arm(mode, native, constraint):
        return {"status": "PASS", "constraint": constraint,
            "adopted_netlist": {key: adopted[key] for key in ("path", "sha256")},
            "native": {"folder": str(native.parent.relative_to(project)),
                       "receipt": ref(native), "input_step": "OpenROAD.STAPrePNR"},
            **gate_refs[mode]}
    timing = project / "reports/flow109/d26_scan_mode.json"
    timing.write_text(json.dumps({
        "schema": "vibeic.flow109.d26-timing-modes.v1", "step_id": "D26",
        "position": 38, "top": top, "aggregate_status": "PASS",
        "functional_baseline": {"status": "PASS", "folder": "phase3/stage3/10",
            "canonical_pass": True, "current_inputs": True,
            "canonical_consumer_status": "PASS"},
        "post_scan_arms": {
            "functional": arm("functional", functional_native, functional_constraint),
            "scan": arm("scan", scan_native, scan_constraint)},
        "scan": {"applicability": "APPLICABLE", "status": "PASS",
            "d09_binding": intent["source_binding"],
            "scan_chain_report": {"path": "reports/phase2/dft/scan_chain.json",
                "sha256": hashlib.sha256((dft / "scan_chain.json").read_bytes()).hexdigest(),
                "published": True, "d09_contract": report["d09_contract"],
                "measured_artifacts": report["measured_artifacts"],
                "native_clock_controls": report["native_clock_controls"], "current": True},
            "adopted_d24": {**{key: adopted[key] for key in ("path", "sha256")},
                "current": True, "is_scan_inserted": True, "native_step": "12",
                "flow109_step": "D24", "position": 36,
                "resolver_note": "post-DFT netlist selected", "folder": "phase2/stage2/12"},
            "constraint": scan_constraint,
            },
        "modes_measured": ["functional_baseline", "post_scan_functional",
                           "post_scan_scan"]}))
    d26 = json.loads((rows / "D26.json").read_text())
    d26["timing_modes_receipt"] = ref(timing)
    (rows / "D26.json").write_text(json.dumps(d26))
    features = profile("Mapped soft-IP with prestitched scan")
    return flow109.execution_context(flow109.resolve_plan(features), "D30", "D30")


def test_d30_rejects_d26_input_netlist_substitution(tmp_path, monkeypatch):
    import hashlib
    context = _d30_scan_case(tmp_path, monkeypatch)
    assert flow109.dft_preroute_admission(tmp_path, context)['flow109_acceptance'] == 'NOT_MEASURED'
    folder = tmp_path / 'phase3/librelane/d26_post_scan_functional'
    other = tmp_path / 'other_netlist.v'
    other.write_text('module neutral_unit; endmodule\n')
    state_in = folder / 'state_in.json'
    state_in.write_text(json.dumps({'nl': str(other.resolve())}))
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    state_sha = hashlib.sha256(state_in.read_bytes()).hexdigest()
    receipt['input']['state'] = state_sha
    receipt['input']['state_files'] = {str(other.resolve()): hashlib.sha256(other.read_bytes()).hexdigest()}
    receipt['sha256']['state_in.json'] = state_sha
    receipt_path.write_text(json.dumps(receipt))
    timing_path = tmp_path / 'reports/flow109/d26_scan_mode.json'
    timing = json.loads(timing_path.read_text())
    timing['post_scan_arms']['functional']['native']['receipt']['sha256'] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    timing_path.write_text(json.dumps(timing))
    row_path = tmp_path / 'reports/flow109/default_rows/D26.json'
    row = json.loads(row_path.read_text())
    row['timing_modes_receipt']['sha256'] = hashlib.sha256(timing_path.read_bytes()).hexdigest()
    row_path.write_text(json.dumps(row))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D26_INPUT_NETLIST_UNBOUND'):
        flow109.dft_preroute_admission(tmp_path, context)


def test_d30_scan_front_door_rejects_different_bound_timing_netlist(tmp_path, monkeypatch):
    # Fixture authorities are synthetic; this exercises the real front door only.
    import hashlib
    import _delivery_route
    context = _d30_scan_case(tmp_path, monkeypatch)
    assert flow109.dft_preroute_admission(tmp_path, context)['normalized_preroute_chain']['reason'] == 'D30_DELIVERY_ARTIFACT_UNBOUND'
    folder = tmp_path / 'phase3/librelane/d26_post_scan_functional'
    other = tmp_path / 'different_timed.v'
    other.write_text('module neutral_unit(input clk, output q); assign q=~clk; endmodule\n')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ('state_in.json', 'state_out.json'):
        (folder / name).write_text(json.dumps({'nl': str(other.resolve())}))
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['input']['state'] = sha(folder / 'state_in.json')
    receipt['input']['state_files'] = {str(other.resolve()): sha(other)}
    receipt['sha256']['state_in.json'] = sha(folder / 'state_in.json')
    receipt_path.write_text(json.dumps(receipt))
    timing_path = tmp_path / 'reports/flow109/d26_scan_mode.json'
    timing = json.loads(timing_path.read_text())
    arm = timing['post_scan_arms']['functional']
    arm['native']['receipt']['sha256'] = sha(receipt_path)
    for name in ('sdc_gate', 'slack_gate'):
        gate_path = tmp_path / arm[name]['path']
        gate = json.loads(gate_path.read_text())
        gate['state_out_sha256'] = sha(folder / 'state_out.json')
        if name == 'sdc_gate':
            gate['netlist_sha256'] = sha(other)
        gate_path.write_text(json.dumps(gate))
        arm[name]['sha256'] = sha(gate_path)
    timing_path.write_text(json.dumps(timing))
    row_path = tmp_path / 'reports/flow109/default_rows/D26.json'
    row = json.loads(row_path.read_text())
    row['timing_modes_receipt']['sha256'] = sha(timing_path)
    row_path.write_text(json.dumps(row))
    assert _delivery_route.admit(tmp_path, 'ip') is None
    manifest = tmp_path / 'scan-manifest.json'
    manifest.write_text(json.dumps({'features': profile('Mapped soft-IP with prestitched scan')}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest, execution_mode=None,
                           flow109_plan_only=False, entry_step='D30', exit_step='D30')
    assert flow109.prepare_front_door(args, tmp_path) == 1
    refusal = json.loads((tmp_path / 'reports/flow109/admission.json').read_text())
    assert refusal['status'] == 'FAIL' and refusal['native_started'] is False
    assert refusal['reason'] == 'FLOW109_PREROUTE_NETLIST_MISMATCH'
    assert not list((tmp_path / 'reports/flow109').rglob('*d30-delivery*'))


def test_d30_refuses_row_pass_without_bound_delivery_netlist(tmp_path, monkeypatch):
    context = _d30_scan_case(tmp_path, monkeypatch)
    admission = flow109.dft_preroute_admission(tmp_path, context)
    chain = admission['normalized_preroute_chain']
    assert chain['status'] == 'NOT_MEASURED'
    assert chain['reason'] == 'D30_DELIVERY_ARTIFACT_UNBOUND'
    assert set(chain['points']) == {'D24', 'D25', 'D26'}
    assert 'D30' not in chain['points']
    result = {'step_id': 'D30', 'context_sha256': context['context_sha256'],
              'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True}
    answer = flow109._selected_step_result(tmp_path, context, result)
    assert answer['default_row_status'] == 'NOT_MEASURED'
    assert answer['completed'] is False
    assert answer['normalized_chain_reason'] == 'D30_DELIVERY_BINDING_UNPROVEN'


def test_d30_accepts_native_d24_d25_identity_and_chain_report(tmp_path, monkeypatch):
    context = _d30_scan_case(tmp_path, monkeypatch)

    result = flow109.dft_preroute_admission(tmp_path, context)

    assert result["identity_agreement"] == "D24_D25_D30_MATCH"
    assert result["adopted_netlist"]["artifact_id"] == "D24_POST_SCAN_NETLIST"
    assert result["native_chain"]["internal_chain_length"] == 2
    modes = result["pre_route_timing"]["timing_modes"]
    assert modes["modes_measured"] == ["functional_baseline", "post_scan_functional"]
    arms = modes["post_scan_arms"]
    assert set(arms) == {"functional"}
    assert arms["functional"]["adopted_netlist"]["sha256"] == result["adopted_netlist"]["sha256"]
    assert arms["functional"]["constraint"]["clock_select_value"] == 0
    assert result["pre_route_timing"]["applicable_modes"] == ["functional"]


def test_d30_explicit_no_scan_accepts_current_functional_only_d26(
        tmp_path, monkeypatch):
    import hashlib
    _write_dft_intent(tmp_path, monkeypatch, scan=False, route='ip')
    top = "neutral_unit"
    mapped = tmp_path / f"phase2/stage2/synth/{top}_synth.v"
    mapped.parent.mkdir(parents=True)
    mapped.write_text("module neutral_unit(input clk, output q); assign q=clk; endmodule\n")
    (tmp_path / "input/flow109").mkdir(parents=True)
    (tmp_path / "input/flow109/D22.json").write_text(json.dumps({"top": top}))
    reports = tmp_path / "reports"; reports.mkdir(exist_ok=True)
    (reports / "lec.json").write_text(json.dumps({
        "verdict": "PASS", "equivalent": True,
        "proof_identity": {"top": top, "gate_netlist": {
            "path": str(mapped.relative_to(tmp_path)),
            "sha256": "sha256:" + hashlib.sha256(mapped.read_bytes()).hexdigest()}}}))
    rows = reports / "flow109/default_rows"; rows.mkdir(parents=True)
    (rows / "D25.json").write_text(json.dumps({
        "step_id": "D25", "default_row_status": "PASS", "completed": True}))
    features = profile("Mapped soft-IP with prestitched scan")
    features["requires_scan"] = False
    context = flow109.execution_context(flow109.resolve_plan(features), "D30", "D30")
    intent = flow109.dft_source_intent(tmp_path, context)
    timing = reports / "flow109/d26_scan_mode.json"
    timing.write_text(json.dumps({
        "schema": "vibeic.flow109.d26-timing-modes.v1", "step_id": "D26",
        "position": 38, "top": top, "aggregate_status": "PASS",
        "functional_baseline": {"status": "PASS", "folder": "historical-functional",
            "canonical_pass": True, "current_inputs": True,
            "canonical_consumer_status": "PASS"},
        "post_scan_arms": {},
        "scan": {"applicability": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                 "d09_binding": intent["source_binding"]},
        "modes_measured": ["functional_baseline"]}))
    (rows / "D26.json").write_text(json.dumps({
        "step_id": "D26", "default_row_status": "PASS", "completed": True,
        "timing_modes_receipt": {"path": str(timing.relative_to(tmp_path)),
            "sha256": hashlib.sha256(timing.read_bytes()).hexdigest()}}))
    # The released no-scan baseline records only a Step10 version folder;
    # without the real synthesis and STA producer bindings it is unproven.
    with pytest.raises(flow109.Flow109Error, match='FLOW109_PREROUTE_INPUTS_UNPROVEN'):
        flow109.dft_preroute_admission(tmp_path, context)
    # Isolated positive fixture for the already-existing native receipt shape.
    # These authorities are explicitly mocked; they do not constitute row PASS.
    import design_one_shot_runner as design
    import synth_handoff_netlist_check as handoff
    import librelane_contract as native_contract
    (rows / 'D22.json').write_text(json.dumps({
        'step_id': 'D22', 'default_row_status': 'PASS', 'completed': True}))
    monkeypatch.setattr(handoff, 'bound_handoff', lambda *_: {
        'verdict': 'PASS', 'mapped': str(mapped.resolve()),
        'netlist_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest()})
    monkeypatch.setattr(design, '_current_phase2_consumer', lambda _p, step, _t:
                        {'folder': 'historical-functional'} if step == '10' else None)
    native = tmp_path / 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr'
    native.mkdir(parents=True)
    state_in = native / 'state_in.json'; state_out = native / 'state_out.json'
    state_in.write_text(json.dumps({'nl': str(mapped.resolve())}))
    state_out.write_text(json.dumps({'nl': str(mapped.resolve())}))
    native_record = {'input': {'step': 'OpenROAD.STAPrePNR',
        'state': hashlib.sha256(state_in.read_bytes()).hexdigest(),
        'state_files': {str(mapped.resolve()): hashlib.sha256(mapped.read_bytes()).hexdigest()}},
        'sha256': {'state_in.json': hashlib.sha256(state_in.read_bytes()).hexdigest()}}
    (native / 'vibeic_receipt.json').write_text(json.dumps(native_record))
    monkeypatch.setattr(native_contract, 'validate_step_receipt',
                        lambda folder, *_: json.loads((folder / 'vibeic_receipt.json').read_text()))
    gate = tmp_path / 'phase3/librelane/prelayout/gates/step10_slack.json'
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({'verdict': 'PASS', 'corners': {'tt': {}},
        'source': str(state_out.resolve()), 'state_out_sha256': hashlib.sha256(state_out.read_bytes()).hexdigest()}))
    result = flow109.dft_preroute_admission(tmp_path, context)
    assert result['normalized_preroute_chain']['reason'] == 'D30_DELIVERY_ARTIFACT_UNBOUND'
    assert set(result['normalized_preroute_chain']['points']) == {'D22', 'D25', 'D26'}

    assert result["requires_scan"] is False
    assert result["identity_agreement"] == "D22_D25_D30_MATCH"
    assert result["pre_route_timing"]["timing_modes"]["scan"]["applicability"] == "NOT_APPLICABLE"

    # Actual owner writes an independent D30 output, but fixtures here stand
    # in for D22/D25/D26 and Step10/14 authority: component evidence only.
    import step_output_collector as versions
    handoff_folder = 'test-nonscan-d30-handoff'
    handoff_file = versions._versions_root(tmp_path) / handoff_folder / 'outputs.json'
    handoff_file.parent.mkdir(parents=True, exist_ok=True)
    handoff_file.write_text(json.dumps({'canonical_pass': True, 'status': 'PASS'}))
    monkeypatch.setattr(design, '_current_phase2_consumer', lambda _p, step, _t:
        {'folder': 'historical-functional' if step == '10' else handoff_folder})
    attempt = flow109._new_attempt(tmp_path, context)
    delivery_ref = design._d30_publish_delivery(tmp_path, context, attempt, handoff_folder)
    chain = flow109._complete_preroute_chain(tmp_path, context, result, delivery_ref,
                                              d30_context_sha256=context['context_sha256'])
    assert chain['status'] == 'PASS', chain
    assert set(chain['references']) == {'D22', 'D25', 'D26', 'D30'}
    answer = flow109._selected_step_result(tmp_path, context, {
        'step_id': 'D30', 'context_sha256': context['context_sha256'],
        'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True,
        'd30_delivery_receipt': delivery_ref})
    assert answer['default_row_status'] == 'NOT_MEASURED'
    assert answer['normalized_chain_reason'] == 'D30_METRIC_BINDINGS_UNIMPLEMENTED'

    # Simulate a real producer reporting a different bound D26 input.  The
    # public selection must return measured FAIL before the delivery owner.
    foreign = tmp_path / 'foreign_timed.v'
    foreign.write_text('module neutral_unit(input clk, output q); assign q=~clk; endmodule\n')
    state_in.write_text(json.dumps({'nl': str(foreign.resolve())}))
    state_out.write_text(json.dumps({'nl': str(foreign.resolve())}))
    native_record['input']['state'] = hashlib.sha256(state_in.read_bytes()).hexdigest()
    native_record['input']['state_files'] = {str(foreign.resolve()): hashlib.sha256(foreign.read_bytes()).hexdigest()}
    native_record['sha256']['state_in.json'] = hashlib.sha256(state_in.read_bytes()).hexdigest()
    (native / 'vibeic_receipt.json').write_text(json.dumps(native_record))
    gate_body = json.loads(gate.read_text())
    gate_body['state_out_sha256'] = hashlib.sha256(state_out.read_bytes()).hexdigest()
    gate.write_text(json.dumps(gate_body))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_PREROUTE_NETLIST_MISMATCH'):
        flow109.dft_preroute_admission(tmp_path, context)
    import _delivery_route
    assert _delivery_route.admit(tmp_path, 'ip') is None
    manifest = tmp_path / 'nonscan-manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest, execution_mode=None,
                           flow109_plan_only=False, entry_step='D30', exit_step='D30')
    assert flow109.prepare_front_door(args, tmp_path) == 1
    refusal = json.loads((tmp_path / 'reports/flow109/admission.json').read_text())
    assert refusal['status'] == 'FAIL' and refusal['native_started'] is False
    assert refusal['reason'] == 'FLOW109_PREROUTE_NETLIST_MISMATCH'


@pytest.mark.parametrize("damage, code", [
    ("pre_scan", "FLOW109_D25_GATE_IDENTITY_MISMATCH"),
    ("foreign_netlist", "FLOW109_D30_NETLIST_FOREIGN"),
    ("foreign_report", "FLOW109_D30_SCAN_REPORT_STALE"),
    ("stale_d09", "FLOW109_D26_SCAN_D09_MISMATCH"),
    ("wrong_hash", "FLOW109_D25_GATE_IDENTITY_MISMATCH"),
    ("d24_hash", "FLOW109_D30_D24_IDENTITY_MISMATCH"),
    ("unresolved_length", "FLOW109_D30_CHAIN_STATISTICS_UNRESOLVED"),
    ("d26_missing", "FLOW109_D26_TIMING_MODES_MISSING"),
    ("functional_only", "FLOW109_D26_SCAN_TIMING_NOT_MEASURED"),
    ("old_functional_subject", "FLOW109_D26_SCAN_NETLIST_MISMATCH"),
    ("absent_mode_authority", "FLOW109_D26_MODE_VALIDATOR_MISMATCH"),
    ("wrong_scan_mode", "FLOW109_D26_SCAN_CONSTRAINT_MISMATCH"),
    ("stale_scan_arm", "FLOW109_D26_SCAN_NATIVE_STALE"),
    ("violating_scan_sta", "FLOW109_D26_SCAN_GATE_FAIL"),
])
def test_d30_refuses_prescan_foreign_stale_or_unresolved_inputs(
        tmp_path, monkeypatch, damage, code):
    context = _d30_scan_case(tmp_path, monkeypatch)
    if damage == "pre_scan":
        (tmp_path / "phase2/stage2/synth/post_dft_netlist.v").write_text(
            "module unit(input clk, input rst_n); endmodule\n")
    elif damage == "foreign_netlist":
        path = tmp_path / "phase2/stage2/synth/post_dft_netlist.v"
        foreign = tmp_path.parent / (tmp_path.name + "-foreign-scan.v")
        foreign.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(foreign)
    elif damage == "foreign_report":
        path = tmp_path / "reports/phase2/dft/scan_chain.json"
        body = json.loads(path.read_text()); body["clock"] = "foreign_clock"
        path.write_text(json.dumps(body))
    elif damage == "stale_d09":
        from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
        intent = _intent()
        intent['dft_plan'] = {'planned_chain_count': 1, 'max_chain_length': 32}
        intent["test_port_def"]["scan_enable"]["public"] = "scan_enable_new"
        _publish_dft_intent(tmp_path, intent, route='ip')
    elif damage == "wrong_hash":
        path = tmp_path / "reports/lec.json"
        body = json.loads(path.read_text())
        body["proof_identity"]["gate_netlist"]["sha256"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(body))
    elif damage == "d24_hash":
        path = tmp_path / "reports/flow109/default_rows/D24.json"
        body = json.loads(path.read_text())
        body["adopted_netlist"]["sha256"] = "0" * 64
        path.write_text(json.dumps(body))
    elif damage == "unresolved_length":
        path = tmp_path / "reports/phase2/dft/scan_chain.json"
        body = json.loads(path.read_text()); body["internal_chain_length"] = None
        path.write_text(json.dumps(body))
    elif damage == "d26_missing":
        path = tmp_path / "reports/flow109/default_rows/D26.json"
        body = json.loads(path.read_text()); body.pop("timing_modes_receipt")
        path.write_text(json.dumps(body))
    else:
        timing = tmp_path / "reports/flow109/d26_scan_mode.json"
        body = json.loads(timing.read_text())
        if damage == "functional_only":
            body["scan"]["status"] = "NOT_MEASURED"
            body["post_scan_arms"] = {}
            body["modes_measured"] = ["functional_baseline"]
        elif damage == "old_functional_subject":
            old = tmp_path / "phase2/stage2/synth/netlist.v"
            body["post_scan_arms"]["functional"]["adopted_netlist"] = {
                "path": str(old.relative_to(tmp_path)),
                "sha256": __import__("hashlib").sha256(old.read_bytes()).hexdigest()}
        elif damage == "absent_mode_authority":
            body["post_scan_arms"]["functional"]["constraint"].pop("clock_select")
        elif damage == "wrong_scan_mode":
            body["post_scan_arms"]["scan"]["constraint"]["mode"] = "functional"
        elif damage == "stale_scan_arm":
            receipt = tmp_path / body["post_scan_arms"]["scan"]["native"]["receipt"]["path"]
            receipt.write_text(receipt.read_text() + "\n")
        else:
            arm = body["post_scan_arms"]["scan"]
            gate = tmp_path / arm["slack_gate"]["path"]
            gate_body = json.loads(gate.read_text())
            gate_body["verdict"] = "FAIL"
            gate_body["findings"] = ["LL_STA_SETUP_VIOLATION"]
            gate.write_text(json.dumps(gate_body))
            arm["slack_gate"].update(
                verdict="FAIL", findings=gate_body["findings"],
                sha256=__import__("hashlib").sha256(gate.read_bytes()).hexdigest())
        if damage != "stale_scan_arm":
            timing.write_text(json.dumps(body))
            row = tmp_path / "reports/flow109/default_rows/D26.json"
            d26 = json.loads(row.read_text())
            d26["timing_modes_receipt"]["sha256"] = __import__("hashlib").sha256(
                timing.read_bytes()).hexdigest()
            row.write_text(json.dumps(d26))

    if damage in {"wrong_scan_mode", "stale_scan_arm", "violating_scan_sta"}:
        # D26 validates functional timing only; D49/D70 own scan-mode timing.
        result = flow109.dft_preroute_admission(tmp_path, context)
        assert result["pre_route_timing"]["applicable_modes"] == ["functional"]
        assert set(result["pre_route_timing"]["timing_modes"]["post_scan_arms"]) == {"functional"}
    else:
        with pytest.raises(flow109.Flow109Error, match=code):
            flow109.dft_preroute_admission(tmp_path, context)


def _final_timing_case(project, monkeypatch):
    import hashlib
    import flow109_final_lec as final_lec
    import flow109_final_lec_physical as physical
    _d30_scan_case(project, monkeypatch, top="neutral_unit")
    # D50's physical fixture must use a physical D30 context too. Isolate its
    # upstream D23/D24 native proof here; the real no-chain D30 control above
    # exercises that producer and binding without this fixture substitution.
    features = profile("Low-power secure scan SoC")
    d30_context = flow109.execution_context(flow109.resolve_plan(features), "D30", "D30")
    def physical_fixture(project, _context, _intent):
        row, ref = flow109._accepted_row(project, flow109._D24_RESULT, "D24")
        return {"D24_result": ref, "adopted_netlist": row["adopted_netlist"],
                "scan_cell_reconciliation": {"fixture": "D23_D24_native_binding"}}
    monkeypatch.setattr(flow109, "physical_d24_binding", physical_fixture)
    d30_admission = flow109.dft_preroute_admission(project, d30_context)
    # This D50 fixture supplies a synthetic accepted handoff, while invoking
    # the actual D30 producer/consumer; no native row acceptance is claimed.
    import design_one_shot_runner as design
    import step_output_collector as versions
    handoff_folder = 'test-d50-d30-handoff'
    handoff = versions._versions_root(project) / handoff_folder / 'outputs.json'
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(json.dumps({'canonical_pass': True, 'status': 'PASS'}))
    monkeypatch.setattr(design, '_current_phase2_consumer',
                        lambda _p, _s, _t: {'folder': handoff_folder})
    attempt = flow109._new_attempt(project, d30_context)
    delivery_ref = design._d30_publish_delivery(project, d30_context, attempt, handoff_folder)
    d30_admission['normalized_preroute_chain'] = flow109._complete_preroute_chain(
        project, d30_context, d30_admission, delivery_ref,
        d30_context_sha256=d30_context['context_sha256'])
    assert d30_admission['normalized_preroute_chain']['status'] == 'PASS'
    rows = project / "reports/flow109/default_rows"
    (rows / "D30.json").write_text(json.dumps({
        "step_id": "D30", "default_row_status": "PASS", "completed": True,
        "context_sha256": d30_context['context_sha256'],
        "d30_delivery_receipt": delivery_ref,
        "dft_preroute_admission": d30_admission}))
    final_netlist = project / "phase3/stage3/pnr/chip_top_pnr.v"
    final_netlist.parent.mkdir(parents=True)
    final_netlist.write_text("module neutral_unit(input clk, output sout); assign sout=clk; endmodule\n")
    final_record = {"path": str(final_netlist.relative_to(project)),
                    "sha256": hashlib.sha256(final_netlist.read_bytes()).hexdigest()}
    transform = project / "reports/flow109/D44/physical-transform.json"
    transform.parent.mkdir(parents=True)
    transform.write_text(json.dumps({
        "status": "PREPARED_NOT_EQUIVALENCE_PROVEN",
        "kind": "def_bound_powered_chip_functional_views_v1",
        "raw_adopted_netlist": physical.record(
            (project / d30_admission["adopted_netlist"]["path"]).resolve())}))
    transform_record = {"path": str(transform.relative_to(project)),
                        "sha256": hashlib.sha256(transform.read_bytes()).hexdigest()}
    proof = project / "reports/flow109/D44/proof.json"
    proof.write_text(json.dumps({"verdict": "PASS"}))
    proof_record = {"path": str(proof.relative_to(project)),
                    "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}
    baseline = project / final_lec.BASELINE; baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({
        "adopted_netlist": final_record,
        "consumer_netlists": {role: final_record
                              for role in ("sta", "lvs_reference", "release")},
        "proof": proof_record,
        "transformations": [{"kind": "def_bound_physical_preparation",
                             "input": "input/flow109/physical.json"}],
        "transformation_receipt": transform_record}))
    baseline_record = {"path": str(baseline.relative_to(project)),
                       "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest()}
    d44_input = project / final_lec.INPUT; d44_input.parent.mkdir(parents=True, exist_ok=True)
    d44_input.write_text(json.dumps({"top": "neutral_unit"}))
    source_identity = {"programs/flow109_final_lec.py": "1" * 64}
    d44_context = {"context_sha256": "2" * 64}
    (rows / "D44.json").write_text(json.dumps({
        "schema": final_lec.SCHEMA, "step_id": "D44",
        "component_status": "PASS", "default_row_status": "PASS",
        "completed": True, "execution_context": d44_context,
        "source_sha256": source_identity, "common_baseline": baseline_record}))
    (rows / "D49.json").write_text(json.dumps({
        "step_id": "D49", "default_row_status": "PASS", "completed": True}))
    monkeypatch.setattr(final_lec, "require_launch_admission", lambda *_: None)
    monkeypatch.setattr(final_lec, "operation_sources", lambda: source_identity)
    monkeypatch.setattr(final_lec, "bind_metrics", lambda *_: {
        "status": "PASS", "metrics": {
            "final_lec_unproved": {"status": "PASS"},
            "sta_lvs_release_netlist_mapping": {
                "status": "PASS", "reference": final_lec._record(project, baseline)}}})

    sta = project / "phase3/librelane/23-sta"
    sta.mkdir(parents=True)
    sdc = project / "phase3/stage3/pnr/constraint.sdc"; sdc.write_text("create_clock -period 10 [get_ports clk]\n")
    spef = project / "phase3/stage3/extracted/chip_top.spef"; spef.parent.mkdir(parents=True); spef.write_text("*SPEF \"IEEE 1481-1998\"\n")
    sdf = project / "phase3/stage3/sta/chip_top.sdf"; sdf.parent.mkdir(parents=True); sdf.write_text("(DELAYFILE)\n")
    liberty = project / "input/pdk/liberty/tt.lib"; liberty.parent.mkdir(parents=True); liberty.write_text("library(tt){}\n")
    state = sta / "state_out.json"
    state.write_text(json.dumps({"nl": str(final_netlist), "sdc": str(sdc),
                                 "spef": {"tt": str(spef)}, "sdf": {"tt": str(sdf)}}))
    (sta / "config.json").write_text(json.dumps({"meta": {"step": "OpenROAD.STAPostPNR"}}))
    corner = sta / "tt"; corner.mkdir()
    (corner / "sta.log").write_text(
        f"Reading cell library for the 'tt' corner at '{liberty}'\n")
    signoff = project / "reports/phase3/sta_postpnr_signoff.json"; signoff.parent.mkdir(parents=True, exist_ok=True)
    signoff.write_text(json.dumps({"sta_state": str(state),
        "sta_state_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
        "corners": {"tt": {}}, "judgment": {"verdict": "PASS",
        "worst_setup": {"corner": "tt"}}}))
    features = profile("Low-power secure scan SoC")
    context = flow109.execution_context(flow109.resolve_plan(features), "D50", "D50")
    return context, final_netlist, baseline, state


def _physical_wrapper_timing_case(project, monkeypatch, *, same_name=False,
                                  same_final_bytes=False):
    """Use the real physical producer's relevant top/path receipt schema."""
    import flow109_final_lec as final_lec
    import flow109_final_lec_physical as physical
    context, final_netlist, baseline, state = _final_timing_case(project, monkeypatch)
    logical_top = "neutral_unit"
    physical_top = logical_top if same_name else "chip_top"
    rows = project / "reports/flow109/default_rows"
    d30 = json.loads((rows / "D30.json").read_text())["dft_preroute_admission"]
    if same_final_bytes:
        final_netlist.write_bytes(
            (project / d30["adopted_netlist"]["path"]).read_bytes())
    else:
        final_netlist.write_text(
            f"module {physical_top}(input clk, output sout); "
            "assign sout=clk; endmodule\n")
    final_record = final_lec._record(project, final_netlist)

    physical_input = project / "input/flow109/physical.json"
    physical_input.write_text(json.dumps({
        "schema": physical.SCHEMA, "top": physical_top,
        "logical_top": logical_top}))
    physical_input_record = final_lec._record(project, physical_input)

    transform = project / "reports/flow109/D44/physical-transform.json"
    transform.write_text(json.dumps({
        "schema": physical.SCHEMA,
        "producer": "flow109_final_lec_physical",
        "status": "PREPARED_NOT_EQUIVALENCE_PROVEN",
        "kind": physical.KIND,
        "inputs": {str(physical_input.resolve()): physical_input_record["sha256"]},
        "top": physical_top,
        "logical_top": logical_top,
        "raw_adopted_netlist": physical.record(
            (project / d30["adopted_netlist"]["path"]).resolve())}))
    transform_record = final_lec._record(project, transform)
    transformations = [{"kind": physical.KIND, "input": physical_input_record}]

    baseline_body = json.loads(baseline.read_text())
    baseline_body.update(
        adopted_netlist=final_record,
        consumer_netlists={role: final_record
                           for role in ("sta", "lvs_reference", "release")},
        transformations=transformations,
        transformation_receipt=transform_record)
    baseline.write_text(json.dumps(baseline_body))
    d44 = rows / "D44.json"
    d44_body = json.loads(d44.read_text())
    d44_body["common_baseline"] = final_lec._record(project, baseline)
    d44.write_text(json.dumps(d44_body))
    d44_input = project / final_lec.INPUT
    d44_input.write_text(json.dumps({
        "schema": final_lec.SCHEMA, "top": physical_top,
        "transformations": transformations}))
    sta_config = state.parent / "config.json"
    sta_config.write_text(json.dumps({
        "meta": {"step": "OpenROAD.STAPostPNR"},
        "DESIGN_NAME": physical_top}))
    return context, final_netlist, baseline, state, {
        "logical_top": logical_top, "physical_top": physical_top,
        "transform": transform, "physical_input": physical_input,
        "sta_config": sta_config}


def test_d50_refuses_d30_profile_mismatch_before_reopening(tmp_path, monkeypatch):
    context, _final, _baseline, _state, _tops = _physical_wrapper_timing_case(tmp_path, monkeypatch)
    row_path = tmp_path / 'reports/flow109/default_rows/D30.json'
    row = json.loads(row_path.read_text())
    row['dft_preroute_admission']['profile_identity']['features_sha256'] = '0' * 64
    row_path.write_text(json.dumps(row))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D30_PROFILE_MISMATCH'):
        flow109.dft_final_timing_admission(tmp_path, context)


def test_d50_final_timing_accepts_physical_rewrite_with_transform_and_lec_trace(
        tmp_path, monkeypatch):
    context, final_netlist, _baseline, _state, tops = _physical_wrapper_timing_case(
        tmp_path, monkeypatch)

    result = flow109.dft_final_timing_admission(tmp_path, context)

    assert result["pre_route_netlist"]["sha256"] != result["final_adopted_netlist"]["sha256"]
    assert result["D44_pre_source"]["sha256"] == result["pre_route_netlist"]["sha256"]
    assert Path(result["D44_pre_source"]["path"]).is_absolute()
    assert result["D44_pre_source"]["resolved_path"] == result["pre_route_netlist"]["path"]
    assert result["physical_transform"] is not None
    assert result["timing"]["sha256"]["sta_netlist"] == result["final_adopted_netlist"]["sha256"]
    assert result["timing"]["sha256"]["spef"]
    assert result["timing"]["sdf_sha256"]
    assert result["lec_measures_timing"] is False
    assert result["logical_top"] == tops["logical_top"]
    assert result["physical_top"] == tops["physical_top"]


@pytest.mark.parametrize("damage, code", [
    ("wrong_logical_top", "FLOW109_D44_LOGICAL_TOP_MISMATCH"),
    ("wrong_physical_top", "FLOW109_D44_PHYSICAL_TOP_MISMATCH"),
    ("wrong_timing_top", "FLOW109_D49_TIMING_TOP_MISMATCH"),
])
def test_d50_physical_wrapper_refuses_wrong_logical_or_physical_top(
        tmp_path, monkeypatch, damage, code):
    context, _final, baseline, _state, paths = _physical_wrapper_timing_case(
        tmp_path, monkeypatch)
    if damage in {"wrong_logical_top", "wrong_physical_top"}:
        transform = paths["transform"]
        body = json.loads(transform.read_text())
        body["logical_top" if damage == "wrong_logical_top" else "top"] = "foreign_top"
        transform.write_text(json.dumps(body))
        baseline_body = json.loads(baseline.read_text())
        import flow109_final_lec as final_lec
        baseline_body["transformation_receipt"] = final_lec._record(tmp_path, transform)
        baseline.write_text(json.dumps(baseline_body))
        d44 = tmp_path / "reports/flow109/default_rows/D44.json"
        d44_body = json.loads(d44.read_text())
        d44_body["common_baseline"] = final_lec._record(tmp_path, baseline)
        d44.write_text(json.dumps(d44_body))
    else:
        config = json.loads(paths["sta_config"].read_text())
        config["DESIGN_NAME"] = "foreign_top"
        paths["sta_config"].write_text(json.dumps(config))

    with pytest.raises(flow109.Flow109Error, match=code):
        flow109.dft_final_timing_admission(tmp_path, context)


def test_d50_same_name_physical_transform_accepts_full_top_trace(
        tmp_path, monkeypatch):
    context, _final, _baseline, _state, tops = _physical_wrapper_timing_case(
        tmp_path, monkeypatch, same_name=True)

    result = flow109.dft_final_timing_admission(tmp_path, context)

    assert result["logical_top"] == tops["logical_top"]
    assert result["physical_top"] == tops["physical_top"]
    assert result["physical_transform"] is not None
    assert result["D44_pre_source"]["mode"] == "D44_TRANSFORM_SOURCE"


@pytest.mark.parametrize("damage, code", [
    ("wrong_logical_top", "FLOW109_D44_LOGICAL_TOP_MISMATCH"),
    ("wrong_preparation_top", "FLOW109_D44_PHYSICAL_TOP_MISMATCH"),
    ("wrong_timing_top", "FLOW109_D49_TIMING_TOP_MISMATCH"),
])
def test_d50_same_name_physical_transform_refuses_wrong_top_trace(
        tmp_path, monkeypatch, damage, code):
    context, _final, baseline, _state, paths = _physical_wrapper_timing_case(
        tmp_path, monkeypatch, same_name=True)
    if damage in {"wrong_logical_top", "wrong_preparation_top"}:
        transform = paths["transform"]
        body = json.loads(transform.read_text())
        body["logical_top" if damage == "wrong_logical_top" else "top"] = "foreign_top"
        transform.write_text(json.dumps(body))
        baseline_body = json.loads(baseline.read_text())
        import flow109_final_lec as final_lec
        baseline_body["transformation_receipt"] = final_lec._record(tmp_path, transform)
        baseline.write_text(json.dumps(baseline_body))
        d44 = tmp_path / "reports/flow109/default_rows/D44.json"
        d44_body = json.loads(d44.read_text())
        d44_body["common_baseline"] = final_lec._record(tmp_path, baseline)
        d44.write_text(json.dumps(d44_body))
    else:
        config = json.loads(paths["sta_config"].read_text())
        config["DESIGN_NAME"] = "foreign_top"
        paths["sta_config"].write_text(json.dumps(config))

    with pytest.raises(flow109.Flow109Error, match=code):
        flow109.dft_final_timing_admission(tmp_path, context)


def test_d50_same_name_same_bytes_transform_still_checks_preparation_top(
        tmp_path, monkeypatch):
    context, final_netlist, baseline, _state, paths = _physical_wrapper_timing_case(
        tmp_path, monkeypatch, same_name=True, same_final_bytes=True)
    d30 = json.loads((tmp_path / "reports/flow109/default_rows/D30.json").read_text())
    assert (__import__("hashlib").sha256(final_netlist.read_bytes()).hexdigest()
            == d30["dft_preroute_admission"]["adopted_netlist"]["sha256"])
    transform = paths["transform"]
    body = json.loads(transform.read_text())
    body["logical_top"] = "foreign_top"
    transform.write_text(json.dumps(body))
    import flow109_final_lec as final_lec
    baseline_body = json.loads(baseline.read_text())
    baseline_body["transformation_receipt"] = final_lec._record(tmp_path, transform)
    baseline.write_text(json.dumps(baseline_body))
    d44 = tmp_path / "reports/flow109/default_rows/D44.json"
    d44_body = json.loads(d44.read_text())
    d44_body["common_baseline"] = final_lec._record(tmp_path, baseline)
    d44.write_text(json.dumps(d44_body))

    with pytest.raises(flow109.Flow109Error, match="FLOW109_D44_LOGICAL_TOP_MISMATCH"):
        flow109.dft_final_timing_admission(tmp_path, context)


@pytest.mark.parametrize("damage, code", [
    ("missing_transform", "FLOW109_D44_FINAL_EQUIVALENCE_UNACCEPTED"),
    ("stale_final", "FLOW109_D44_FINAL_NETLIST_UNBOUND"),
    ("foreign_timing", "FLOW109_D49_TIMING_NETLIST_MISMATCH"),
    ("foreign_spef", "FLOW109_D49_TIMING_PROVENANCE_MISMATCH"),
    ("missing_sdf", "FLOW109_D49_SDF_UNRESOLVED"),
    ("missing_pre_source", "FLOW109_D44_PRE_SOURCE_MISSING"),
    ("stale_pre_source", "FLOW109_D44_PRE_SOURCE_STALE"),
    ("foreign_pre_source", "FLOW109_D44_PRE_SOURCE_MISMATCH"),
    ("outside_pre_source", "FLOW109_D44_PRE_SOURCE_FOREIGN"),
    ("traversal_pre_source", "FLOW109_D44_PRE_SOURCE_FOREIGN"),
    ("hash_mismatch", "FLOW109_D44_PRE_SOURCE_STALE"),
])
def test_d50_final_timing_refuses_missing_stale_or_foreign_provenance(
        tmp_path, monkeypatch, damage, code):
    context, final_netlist, baseline, state = _final_timing_case(tmp_path, monkeypatch)
    if damage == "missing_transform":
        body = json.loads(baseline.read_text()); body["transformations"] = []
        body.pop("transformation_receipt"); baseline.write_text(json.dumps(body))
    elif damage == "stale_final":
        final_netlist.write_text(final_netlist.read_text() + "// stale\n")
    elif damage == "foreign_timing":
        other = tmp_path / "phase3/stage3/pnr/foreign.v"; other.write_text("module foreign; endmodule\n")
        body = json.loads(state.read_text()); body["nl"] = str(other); state.write_text(json.dumps(body))
        signoff = tmp_path / "reports/phase3/sta_postpnr_signoff.json"
        doc = json.loads(signoff.read_text()); doc["sta_state_sha256"] = __import__("hashlib").sha256(state.read_bytes()).hexdigest()
        signoff.write_text(json.dumps(doc))
    elif damage == "foreign_spef":
        foreign = tmp_path.parent / (tmp_path.name + "-foreign.spef")
        foreign.write_text("*SPEF \"IEEE 1481-1998\"\n")
        body = json.loads(state.read_text()); body["spef"] = {"tt": str(foreign)}
        state.write_text(json.dumps(body))
        signoff = tmp_path / "reports/phase3/sta_postpnr_signoff.json"
        doc = json.loads(signoff.read_text()); doc["sta_state_sha256"] = __import__("hashlib").sha256(state.read_bytes()).hexdigest()
        signoff.write_text(json.dumps(doc))
    elif damage == "missing_sdf":
        body = json.loads(state.read_text()); body["sdf"] = {}
        state.write_text(json.dumps(body))
        signoff = tmp_path / "reports/phase3/sta_postpnr_signoff.json"
        doc = json.loads(signoff.read_text()); doc["sta_state_sha256"] = __import__("hashlib").sha256(state.read_bytes()).hexdigest()
        signoff.write_text(json.dumps(doc))
    else:
        import flow109_final_lec_physical as physical
        transform = tmp_path / "reports/flow109/D44/physical-transform.json"
        transform_body = json.loads(transform.read_text())
        if damage == "missing_pre_source":
            transform_body.pop("raw_adopted_netlist")
        elif damage == "hash_mismatch":
            transform_body["raw_adopted_netlist"]["sha256"] = "0" * 64
        elif damage in {"outside_pre_source", "traversal_pre_source"}:
            outside = tmp_path.parent / (tmp_path.name + "-outside-pre-source.v")
            outside.write_text("module neutral_unit(input clk, output sout); assign sout=clk; endmodule\n")
            transform_body["raw_adopted_netlist"] = physical.record(outside.resolve())
            if damage == "traversal_pre_source":
                transform_body["raw_adopted_netlist"]["path"] = "../" + outside.name
        else:
            foreign = tmp_path / "phase2/stage2/synth/foreign-pre-source.v"
            foreign.write_text("module neutral_unit(input clk, output sout); assign sout=~clk; endmodule\n")
            transform_body["raw_adopted_netlist"] = physical.record(foreign.resolve())
            if damage == "stale_pre_source":
                foreign.write_text(foreign.read_text() + "// stale\n")
        transform.write_text(json.dumps(transform_body))
        transform_record = {"path": str(transform.relative_to(tmp_path)),
            "sha256": __import__("hashlib").sha256(transform.read_bytes()).hexdigest()}
        baseline_body = json.loads(baseline.read_text())
        baseline_body["transformation_receipt"] = transform_record
        baseline.write_text(json.dumps(baseline_body))
        baseline_record = {"path": str(baseline.relative_to(tmp_path)),
            "sha256": __import__("hashlib").sha256(baseline.read_bytes()).hexdigest()}
        d44 = tmp_path / "reports/flow109/default_rows/D44.json"
        d44_body = json.loads(d44.read_text())
        d44_body["common_baseline"] = baseline_record
        d44.write_text(json.dumps(d44_body))

    with pytest.raises(flow109.Flow109Error, match=code):
        flow109.dft_final_timing_admission(tmp_path, context)


def test_d50_real_front_door_uses_existing_producer_and_consumer(
        tmp_path, monkeypatch):
    context, _final, _baseline, _state = _final_timing_case(tmp_path, monkeypatch)
    import _delivery_route
    import flow109_frontend
    import path_delay_fault_atpg_run as producer
    import path_delay_coverage_check as consumer
    assert _delivery_route.admit(tmp_path, "ic") is None
    monkeypatch.setattr(producer, "main", lambda argv: 0)
    monkeypatch.setattr(consumer, "audit", lambda *_: {"verdict": "PASS", "value": 100.0})
    features = profile("Low-power secure scan SoC")
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"features": features}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D50", exit_step="D50", container="")

    assert flow109.prepare_front_door(args, tmp_path) == 0
    result = json.loads((tmp_path / "reports/flow109/components/D50.json").read_text())
    assert result["default_row_status"] == "PASS"
    assert result["dft_final_timing_admission"]["lec_measures_timing"] is False

    import sdd_atpg_run as sdd_producer
    import sdd_coverage_check as sdd_consumer
    monkeypatch.setattr(sdd_producer, "main", lambda argv: 0)
    monkeypatch.setattr(sdd_consumer, "audit", lambda *_: {"verdict": "PASS", "value": 100.0})
    args.entry_step = args.exit_step = "D51"
    assert flow109.prepare_front_door(args, tmp_path) == 0
    result = json.loads((tmp_path / "reports/flow109/components/D51.json").read_text())
    assert result["default_row_status"] == "PASS"
    assert result["dft_final_timing_admission"]["D50"]["path"].endswith("D50.json")


@pytest.mark.parametrize("mutation", ["derived", "endpoint", "fpga", "non_boolean"])
def test_invalid_feature_sets_refuse_before_dispatch(mutation):
    features = profile()
    if mutation == "derived":
        features["digital_physical"] = False
    elif mutation == "endpoint":
        features["soft_ip"] = True
    elif mutation == "fpga":
        features = profile("Analog model-IP")
        features["fpga_final"] = True
    else:
        features["has_digital"] = "false"
    with pytest.raises(flow109.Flow109Error):
        flow109.resolve_plan(features)


def test_boolean_grammar_visits_hidden_unknowns_and_rejects_code():
    with pytest.raises(flow109.Flow109Error, match="FEATURE_UNRESOLVED"):
        flow109.predicate("always or omitted", {"always": True})
    with pytest.raises(flow109.Flow109Error, match="PREDICATE_INVALID"):
        flow109.predicate("open('unsafe')", {})


def test_analog_profile_cannot_be_forced_into_digital_default():
    features = profile("Analog hard-IP")
    plan = flow109.resolve_plan(features)
    assert flow109.resolve_step(plan, "D69")["selected_profile"] == "analog_die"
    assert flow109.resolve_step(plan, "D69")["profile"]["tools"] == "Magic.RCX"
    assert flow109.resolve_step(plan, "D69")["profile"]["native_steps"] == ["Magic.RCX"]
    with pytest.raises(flow109.Flow109Error, match="PROFILE_INAPPLICABLE"):
        flow109.resolve_plan(features, {"D69": "default"})


def test_odb_fill_is_not_aliased_to_legacy_gds_fill_pass():
    plan = flow109.resolve_plan(profile())
    fill = flow109.resolve_step(plan, "D62")
    assert fill["profile"]["entrypoint"]["command"] == "density_fill"
    assert fill["profile"]["geometry_format"] == "ODB"
    assert fill["profile"]["native_steps"] == [
        "OpenROAD.DensityFill", "OpenROAD.CheckMetalDensity",
        "OpenROAD.CheckFillObstructions"]
    window = flow109.resolve_execution_window(plan, "D62", "D62")
    assert window["native_step_id"] == "flow109.D62"
    assert window["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_density_fill"
    assert window["resolved_row"]["profile"]["dispatch"]["flow109_metrics_status"] == "IMPLEMENTED_D62_RUNTIME"
    final_extract = flow109.resolve_execution_window(plan, "D69", "D69")
    assert final_extract["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_final_extract"
    final_electrical = flow109.resolve_execution_window(plan, "D70", "D70")
    assert final_electrical["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_final_electrical"
    continuation = flow109.resolve_execution_window(plan, "D38", "D41")
    assert [row["id"] for row in continuation["resolved_rows"]] == ["D38", "D39", "D40", "D41"]
    assert continuation["native_entry_step"] == "19"
    assert continuation["native_exit_step"] == "32"


def test_context_rejects_changed_tool_identity_and_changed_selection():
    plan = flow109.resolve_plan(profile())
    original = flow109.execution_context(plan, "D38", "D38", runtime_tool_uses=[],
                                         qualification_registry="input/qualifications.json")
    assert flow109.validate_execution_context(original) == original
    changed = copy.deepcopy(original)
    changed["runtime_tool_uses"].append({"use_id": "unrelated"})
    with pytest.raises(flow109.Flow109Error, match="CONTEXT_STALE"):
        flow109.validate_execution_context(changed)
    changed = copy.deepcopy(original)
    changed["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "21"
    changed["context_sha256"] = flow109.digest(
        {k: v for k, v in changed.items() if k != "context_sha256"})
    with pytest.raises(flow109.Flow109Error, match="CONTEXT_STALE"):
        flow109.validate_execution_context(changed)


def test_completion_audit_writer_stamps_only_validated_flow109_identity(
        tmp_path, monkeypatch):
    """The audit producer binds current flow identity to source, not omission."""
    import flow_compliance_check

    context = flow109.execution_context(flow109.resolve_plan(profile()),
                                        "D09", "D09")
    path = tmp_path / "flow109-context.json"
    path.write_text(json.dumps(context))
    monkeypatch.setenv("VIBEIC_FLOW109_CONTEXT", str(path))
    identity = flow_compliance_check._resolved_flow_identity()
    assert identity == {
        "schema": "vibeic.resolved-flow-identity.v1",
        "status": "RESOLVED",
        "flow_id": "109",
        "source": "VALIDATED_FLOW109_EXECUTION_CONTEXT",
        "context_sha256": context["context_sha256"],
        "registry_sha256": context["registry_sha256"],
        "planner_sha256": context["planner_sha256"],
    }

    changed = copy.deepcopy(context)
    changed["requested_step"] = "D11"
    path.write_text(json.dumps(changed))
    invalid = flow_compliance_check._resolved_flow_identity()
    assert invalid["status"] == "INVALID"
    assert invalid["flow_id"] is None


def test_default_public_cli_runs_flow109_and_emits_current_identity(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "vibe_ic_one_shot_runner.py")
    manifest = tmp_path / "manifest.json"
    features = profile("Low-power secure scan SoC")
    features["requires_functional_safety"] = True
    manifest.write_text(json.dumps({"features": features}))
    old = tmp_path / "reports" / "phase3_one_shot.json"
    old.parent.mkdir()
    old.write_text('{"verdict":"PASS","native_identity":"preserve"}\n')
    before = old.read_bytes()
    # Omit --flow deliberately: 109 is the public runtime, not an opt-in label
    # over the older route.
    command = [sys.executable, str(runner), str(tmp_path),
               "--flow109-manifest", str(manifest), "--flow109-plan-only", "--route", "ic", "--no-dashboard"]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path / "reports" / "flow109" / "plan.json").read_text())
    assert plan["flow_id"] == "109"
    identity = {row["id"]: row["position"] for row in plan["rows"]}
    expected = {"D09": 17, "D11": 19, "D13": 21,
                "D22": 34, "D23": 35, "D30": 42, "D50": 72}
    assert {key: identity.get(key) for key in expected} == expected
    assert plan["flow109_acceptance"] == "NOT_MEASURED"
    assert old.read_bytes() == before
    assert not (tmp_path / "reports" / "flow109" / "admission.json").exists()
    # Select an optional unmapped safety row explicitly: this digital profile's
    # D06 now has a native owner, so it is no longer a refusal case.
    unmapped = next(row['id'] for row in plan['rows'] if not row['profile'].get('dispatch'))
    result = subprocess.run([x for x in command if x != "--flow109-plan-only"]
                            + ["--entry-step", unmapped, "--exit-step", unmapped],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert "FLOW109_PRODUCER_UNIMPLEMENTED" in result.stderr
    assert old.read_bytes() == before
    # The implemented fill component still cannot launch without qualification.
    result = subprocess.run([x for x in command if x != "--flow109-plan-only"]
                            + ["--entry-step", "D62", "--exit-step", "D62"],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert "QUALIFICATION_RUNTIME_ABSENT" in result.stderr
    refusal = json.loads((tmp_path / "reports/flow109/admission.json").read_text())
    assert refusal["native_started"] is False
    assert old.read_bytes() == before


def test_obsolete_explicit_public_flow_refuses_before_project_access(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "vibe_ic_one_shot_runner.py")
    absent = tmp_path / "does-not-exist"
    result = subprocess.run(
        [sys.executable, str(runner), str(absent), "--flow", "70"],
        text=True, capture_output=True)
    assert result.returncode == 2
    assert "invalid choice: '70'" in result.stderr
    assert not absent.exists()


def test_real_front_door_selection_translates_only_the_named_component(tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile(), "runtime_tool_uses": [],
                                    "qualification_registry": "input/qualifications.json"}))
    observed = []
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    # This control observes the selection/dispatch contract only. Qualification
    # behavior itself is covered by the admission module's native controls.
    monkeypatch.setitem(sys.modules, "flow109_admission", SimpleNamespace(
        require_admission=lambda project, context: observed.append(context) or {"status": "PASS", "test_scope": "selection_only"}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="D38", exit_step="D38")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == args.exit_step == "19"
    assert observed[0]["requested_step"] == "D38"
    context = json.loads(Path(__import__("os").environ[flow109.CONTEXT_ENV]).read_text())
    assert flow109.validate_execution_context(context) == observed[0]


def test_frontend_rows_route_stable_ids_to_existing_default_owner_sites():
    plan = flow109.resolve_plan(profile())
    expected = {
        "D01": ("D1", "phase1_one_shot_runner", "D1", "D1"),
        "D02": ("0.5ic", "phase1_one_shot_runner", "D1", "D1"),
        "D09": ("1", "design_one_shot_runner", "1", "4"),
        "D10": ("P0", "design_one_shot_runner", "1", "1"),
        "D11": ("2", "design_one_shot_runner", "2", "2"),
        "D12": ("3", "design_one_shot_runner", "2", "3"),
        "D13": ("4", "design_one_shot_runner", "4", "4"),
        "D14": ("5", "design_one_shot_runner", "4", "5"),
        "D19": ("7", "design_one_shot_runner", "7", "7"),
        "D20": ("8", "design_one_shot_runner", "8", "8"),
        "D25": ("13", "design_one_shot_runner", "11", "13"),
        "D26": ("10", "design_one_shot_runner", "10", "10"),
        "D30": ("14", "design_one_shot_runner", "14", "14"),
    }
    for row_id, values in expected.items():
        row = flow109.resolve_step(plan, row_id)
        dispatch = row["profile"]["dispatch"]
        assert dispatch["kind"] == "canonical_owner_window"
        assert (dispatch["native_step_id"], dispatch["owner_runner"],
                dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == values
        assert dispatch["native_step_id"] == row["legacy70"][0]["id"]
        expected_status = ("NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED" if row_id == "D11"
                           else "NATIVE_COMPONENT_ONLY_NOT_109_ACCEPTED")
        assert row["profile"]["execution_status"] == expected_status
        assert dispatch["flow109_metrics_status"] == "UNIMPLEMENTED"


def test_d24_routes_to_existing_default_dft_producer_and_consumer(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    plan = flow109.resolve_plan(features)
    row = flow109.resolve_step(plan, "D24")
    dispatch = row["profile"]["dispatch"]
    assert dispatch["kind"] == "canonical_owner_window"
    assert (dispatch["native_step_id"], dispatch["owner_runner"],
            dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == (
                "12", "design_one_shot_runner", "12", "12")
    assert dispatch["producer"] == (
        "design_one_shot_runner.py:_step_post_dft_optimization")
    assert dispatch["consumer"] == (
        "design_one_shot_runner retained Step 12 canonical acceptance")
    assert row["profile"]["execution_status"] == (
        "NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED")
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ip") is None
    _write_dft_intent(tmp_path, monkeypatch, scan=True, route='ip')
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D24", exit_step="D24", container="")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("12", "12")
    owner = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert owner["owner_runner"] == "design_one_shot_runner"
    assert owner["native_step_id"] == "12"


def test_d23_routes_to_existing_default_dft_producer_and_consumer(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    plan = flow109.resolve_plan(features)
    row = flow109.resolve_step(plan, "D23")
    dispatch = row["profile"]["dispatch"]
    assert dispatch["kind"] == "canonical_owner_window"
    assert (dispatch["native_step_id"], dispatch["owner_runner"],
            dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == (
                "11", "design_one_shot_runner", "11", "11")
    assert dispatch["producer"] == (
        "design_one_shot_runner.py:_step_dft_insertion")
    assert dispatch["consumer"] == (
        "design_one_shot_runner retained Step 11 canonical acceptance")
    assert row["profile"]["execution_status"] == (
        "NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED")
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ip") is None
    _write_dft_intent(tmp_path, monkeypatch, scan=True, route='ip')
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D23", exit_step="D23", container="")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("11", "11")
    owner = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert owner["owner_runner"] == "design_one_shot_runner"
    assert owner["native_step_id"] == "11"


def _step9_native_state(tmp_path, monkeypatch):
    import hashlib
    import vibe_ic_one_shot_runner as runner

    netlist = tmp_path / "phase2/stage2/synth/netlist.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top(input clk); endmodule\n")
    sha = hashlib.sha256(netlist.read_bytes()).hexdigest()
    folder = "phase2/stage2/9_current"
    record = tmp_path / "steps" / folder / "outputs.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({
        "status": "NOT_MEASURED",
        "canonical_pass": False,
        "outputs": [{"rel": "phase2/stage2/synth/netlist.v", "sha256": sha}],
    }))
    versions = SimpleNamespace(
        _read_index=lambda _p: {"steps": [{"id": "9", "folder": folder}]},
        _versions_root=lambda _p: tmp_path / "steps",
        _sha=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    )
    handoff = SimpleNamespace(bound_handoff=lambda _p: {
        "verdict": "PASS", "canonical": str(netlist), "mapped": str(netlist),
        "netlist_sha256": sha, "findings": [],
    })
    monkeypatch.setitem(sys.modules, "step_output_collector", versions)
    monkeypatch.setitem(sys.modules, "synth_handoff_netlist_check", handoff)
    return runner, netlist


def test_d23_accepts_current_native_step9_handoff_without_area_budget(
        tmp_path, monkeypatch):
    runner, _ = _step9_native_state(tmp_path, monkeypatch)

    current, error = runner._current_step9_checkpoint(tmp_path)

    assert error is None
    assert current["step9_record"]["status"] == "NOT_MEASURED"
    assert current["native_handoff"]["verdict"] == "PASS"


def test_d23_rejects_step9_handoff_after_netlist_bytes_change(tmp_path, monkeypatch):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    netlist.write_text("module changed; endmodule\n")

    current, error = runner._current_step9_checkpoint(tmp_path)

    assert current is None
    assert "no longer matches" in error


@pytest.mark.parametrize("case", ["noncanonical", "missing", "stale", "foreign"])
def test_d26_refuses_unbound_step9_before_prelayout_producer(
        tmp_path, monkeypatch, case):
    """A native handoff alone is not the current canonical D22 checkpoint."""
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name("top_synth.v")
    netlist.rename(mapped)
    import hashlib
    sha = hashlib.sha256(mapped.read_bytes()).hexdigest()
    record = next((tmp_path / "steps").rglob("outputs.json"))
    body = json.loads(record.read_text())
    body["outputs"][0]["sha256"] = sha
    record.write_text(json.dumps(body))
    sys.modules["synth_handoff_netlist_check"].bound_handoff = lambda _p: {
        "verdict": "PASS", "canonical": str(mapped), "mapped": str(mapped),
        "netlist_sha256": sha, "findings": [],
    }
    versions = sys.modules["step_output_collector"]
    if case == "missing":
        versions._read_index = lambda _p: {"steps": []}
    elif case == "noncanonical":
        versions.latest_pass = lambda *_a: None
    else:
        current = {**body, "folder": "phase2/stage2/9_current",
                   "current_inputs": case != "stale", "canonical_pass": True,
                   "status": "PASS", "result": {"canonical_consumer": {
                       "status": "PASS", "outputs": {"netlist": "foreign"}}}}
        versions.latest_pass = lambda *_a: current
        monkeypatch.setitem(sys.modules, "_flow_yaml", SimpleNamespace(
            load=lambda: {"steps": [{"id": "9"}]}))
        monkeypatch.setitem(sys.modules, "execution_backend_gates", SimpleNamespace(
            contracts=lambda *_a: {"netlist": "current"}))
    launched = []
    versions.current_acceptance = lambda *_a: [{
        "id": "10", "folder": "phase3/prelayout/10_current",
        "status": "PASS", "canonical_pass": True,
        "result": {"canonical_consumer": {"status": "PASS", "step": {
            "reasons": []}}}}]
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", SimpleNamespace(
        _phase2_pdk_config=lambda *_a: "neutral-pdk"))
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", SimpleNamespace(
        step_prelayout_signoff=lambda *a, **_k: launched.append(a) or SimpleNamespace(
            status="PASS", detail=f"{case} producer ran")))

    result = runner._complete_step10_prelayout(tmp_path, "top", "neutral", "")

    assert result["verdict"] == "NOT_MEASURED"
    expected = ("current Step9 native synthesis record" if case == "missing"
                else "current canonical Step9 checkpoint")
    assert expected in result["detail"]
    assert launched == []


def test_d26_current_canonical_step9_launches_prelayout_producer(
        tmp_path, monkeypatch):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name("top_synth.v")
    netlist.rename(mapped)
    sha = __import__("hashlib").sha256(mapped.read_bytes()).hexdigest()
    record = next((tmp_path / "steps").rglob("outputs.json"))
    body = json.loads(record.read_text())
    outputs = {"netlist": {"path": str(mapped), "sha256": sha}}
    body.update({"status": "PASS", "canonical_pass": True,
                 "current_inputs": True,
                 "outputs": [{"rel": "phase2/stage2/synth/netlist.v",
                              "sha256": sha}],
                 "result": {"canonical_consumer": {
                     "status": "PASS", "outputs": outputs}}})
    record.write_text(json.dumps(body))
    current = {**body, "folder": "phase2/stage2/9_current"}
    versions = sys.modules["step_output_collector"]
    versions.latest_pass = lambda *_a: current
    versions.current_acceptance = lambda *_a: [{
        "id": "10", "folder": "phase3/prelayout/10_current",
        "status": "PASS", "canonical_pass": True,
        "result": {"canonical_consumer": {"status": "PASS", "step": {
            "reasons": []}}}}]
    sys.modules["synth_handoff_netlist_check"].bound_handoff = lambda _p: {
        "verdict": "PASS", "canonical": str(mapped), "mapped": str(mapped),
        "netlist_sha256": sha, "findings": []}
    monkeypatch.setitem(sys.modules, "_flow_yaml", SimpleNamespace(
        load=lambda: {"steps": [{"id": "9"}]}))
    monkeypatch.setitem(sys.modules, "execution_backend_gates", SimpleNamespace(
        contracts=lambda *_a: outputs))
    launched = []
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", SimpleNamespace(
        _phase2_pdk_config=lambda *_a: "neutral-pdk"))
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", SimpleNamespace(
        step_prelayout_signoff=lambda *a, **_k: launched.append(a) or SimpleNamespace(
            status="PASS", detail="canonical Step10 consumer PASS")))

    result = runner._complete_step10_prelayout(tmp_path, "top", "neutral", "")

    assert result["verdict"] == "PASS"
    assert launched == [(tmp_path, "top", "neutral-pdk", "")]


def test_d23_rejects_wrong_l20_before_scan_or_atpg_launch(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner
    # This directly exercises the retained pre-stitched owner, without a
    # selected physical D23 context leaked from another test.
    monkeypatch.setattr(runner, '_flow109_selected_row', lambda _row: False)

    mapped = tmp_path / "phase2/stage2/synth/top_synth.v"
    mapped.parent.mkdir(parents=True)
    mapped.write_text("module top(input clk); endmodule\n")
    monkeypatch.setattr(runner, "_current_step9_checkpoint",
                        lambda _p: ({"native_handoff": {"verdict": "PASS"}}, None))
    design = SimpleNamespace(
        derive_dft_clock_reset=lambda _p: ("clk", "rst", False),
        _step_dft_insertion=lambda *a, **k: pytest.fail(
            "wrong L20 must refuse before the native producer"),
    )
    atpg = SimpleNamespace(resolve_mapped_netlist=lambda *_a, **_k: (
        "phase2/stage2/synth/top_synth.v", "test"))
    scan = SimpleNamespace(
        count_flops=lambda _text: 64,
        load_l20_scan_contract=lambda *_a, **_k: (
            None, ["L20 length=63 does not match mapped-netlist flop count 64"]),
    )
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", design)
    monkeypatch.setitem(sys.modules, "fault_atpg_run", atpg)
    monkeypatch.setitem(sys.modules, "fault_scan_chain_insert", scan)

    result = runner._complete_step11_dft(tmp_path, "top", "unused")

    assert result["verdict"] == "NOT_MEASURED"
    assert "length=63" in result["detail"]


@pytest.mark.parametrize("step,native", [("D23", "11"), ("D24", "12")])
@pytest.mark.parametrize("status", ["PASS", "FAIL", "NOT_MEASURED"])
def test_bounded_dft_owner_publishes_its_actual_selected_step_verdict(
        tmp_path, monkeypatch, step, native, status):
    import _delivery_route
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    _write_dft_intent(tmp_path, monkeypatch, scan=True, route='ip')
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.setenv(flow109.ATTEMPT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step=step, exit_step=step, container="")
    assert flow109.prepare_front_door(args, tmp_path) is None

    result = runner._finish_selected_native_owner(
        tmp_path, native, {"verdict": status})

    published = json.loads((tmp_path / "reports/flow109/default_rows" /
                            f"{step}.json").read_text())
    assert result["default_row_status"] == published["default_row_status"] == status
    assert published["step_id"] == step
    assert published["completed"] is (status == "PASS")
    assert published["whole_flow_acceptance"] == "NOT_MEASURED"
    assert published["delivery_accepted"] is False


def test_bounded_owner_finish_does_not_change_legacy_execution(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner

    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    assert runner._finish_selected_native_owner(
        tmp_path, "11", {"verdict": "PASS"}) is None
    assert not (tmp_path / "reports/flow109/default_rows").exists()


def _d09_report_body(tmp_path, *, lint="PASS", reference="PASS", cdc="PASS"):
    """Create only producer evidence; the product path must add its binding."""
    rtl = tmp_path / "phase2/stage1/rtl/chip_top.sv"
    rtl.parent.mkdir(parents=True, exist_ok=True)
    rtl.write_text("module chip_top(input logic clk); endmodule\n")
    source_input = tmp_path / "input/spec.md"
    source_input.parent.mkdir(parents=True, exist_ok=True)
    source_input.write_bytes(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "flow109.json").read_bytes())
    evidence = []
    for name in ("crossing", "async_input", "reset_dep"):
        path = tmp_path / f"reports/phase2/cdc/{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"verdict": cdc}) + "\n")
        evidence.append(str(path.relative_to(tmp_path)))
    return {
        "project": str(tmp_path.resolve()),
        "verdict": "PASS",
        "declared_window": {"entry_step": "1", "exit_step": "4",
                            "dispatched_step_ids": ["1", "2", "3", "4"]},
        "steps": [
            {"name": "rtl_gen", "status": "PASS_WITH_WAIVERS",
             "extras": {"preserved": True, "rtl_provenance": "AUTHORED"}},
            {"name": "rtl_lint_tool", "status": lint, "extras": {}},
            {"name": "phase2_manifests", "status": "PASS",
             "output_files": evidence, "extras": {}},
            {"name": "reference_tb", "status": reference, "extras": {}},
        ],
    }


def _d09_owner_report(tmp_path, monkeypatch, *, lint="PASS", reference="PASS",
                      cdc="PASS", generated=None):
    """Issue the real child identity and let the existing writer bind it."""
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design
    import vibe_ic_one_shot_runner as runner

    report = _d09_report_body(
        tmp_path, lint=lint, reference=reference, cdc=cdc)
    if generated is not None:
        report['steps'][0] = generated
    out = tmp_path / "reports/orchestrator/phase2_one_shot.json"

    def child(command, *, env=None, **_kwargs):
        context = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        design._write_phase2_report(
            out, report, tmp_path, invocation_context=context)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)
    invocation = {}
    assert runner._run_phase(
        "D09 focused child", runner.PROGRAMS_DIR / "phase2_one_shot_runner.py",
        [str(tmp_path), "--entry-step", "1", "--exit-step", "4"],
        env=dict(os.environ), invocation=invocation) == 0
    report = json.loads(out.read_text())
    context = flow109.execution_context(flow109.resolve_plan(profile()),
                                        "D09", "D09")
    request = tmp_path / "d09-request.json"
    request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,
                       str(flow109._new_attempt(tmp_path, context)))
    return (runner, report,
            tmp_path / "phase2/stage1/rtl/chip_top.sv",
            tmp_path / "input/spec.md", invocation)


@pytest.mark.parametrize('kind,expected', [
    ('valid', 'PASS'), ('unbound', 'NOT_MEASURED'),
    ('no_generator', 'NOT_MEASURED'), ('failed', 'FAIL'),
])
def test_d09_generated_rtl_requires_current_bound_producer(tmp_path, monkeypatch, kind, expected):
    rtl = tmp_path / 'phase2/stage1/rtl/chip_top.sv'
    generated = {'name': 'rtl_gen', 'status': 'PASS',
                 'output_files': [str(rtl)],
                 'extras': {'program_first': True, 'deterministic_generator': 'neutral'}}
    if kind == 'unbound':
        generated['output_files'] = [str(tmp_path / 'elsewhere.sv')]
    if kind == 'no_generator':
        generated['extras'] = {}
    if kind == 'failed':
        generated['status'] = 'FAIL'
    runner, report, _, _, invocation = _d09_owner_report(
        tmp_path, monkeypatch, generated=generated)
    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)
    assert answer['verdict'] == expected


def test_d09_completion_requires_full_bound_owner_report_and_preserves_rtl(
        tmp_path, monkeypatch):
    runner, report, rtl, _, invocation = _d09_owner_report(tmp_path, monkeypatch)
    before = rtl.read_bytes()

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == "PASS"
    assert rtl.read_bytes() == before
    terminal = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) /
                           "result.json").read_text())
    assert terminal["default_row_status"] == "PASS"
    assert terminal["whole_flow_acceptance"] == "NOT_MEASURED"
    assert terminal["delivery_accepted"] is False
    component = terminal["components"][0]
    assert component["step_id"] == "D09"
    assert component["completed"] is True
    assert answer["evidence"]["rtl_inventory"][0]["path"] == "chip_top.sv"


@pytest.mark.parametrize("case,expected", [
    ("missing_lint", "NOT_MEASURED"),
    ("missing_handoff", "NOT_MEASURED"),
    ("lint_fail", "FAIL"),
    ("reference_fail", "FAIL"),
    ("cdc_fail", "FAIL"),
    ("changed_rtl", "NOT_MEASURED"),
    ("changed_input", "NOT_MEASURED"),
    ("foreign_report", "NOT_MEASURED"),
    ("stale_invocation", "NOT_MEASURED"),
    ("foreign_runner", "NOT_MEASURED"),
    ("foreign_attempt", "NOT_MEASURED"),
    ("foreign_native", "NOT_MEASURED"),
])
def test_d09_completion_fails_closed_on_missing_failed_or_foreign_evidence(
        tmp_path, monkeypatch, case, expected):
    runner, report, rtl, source_input, invocation = _d09_owner_report(
        tmp_path, monkeypatch,
        lint="FAIL" if case == "lint_fail" else "PASS",
        reference="FAIL" if case == "reference_fail" else "PASS",
        cdc="FAIL" if case == "cdc_fail" else "PASS")
    if case == "missing_lint":
        report["steps"] = [row for row in report["steps"]
                           if row["name"] != "rtl_lint_tool"]
    elif case == "missing_handoff":
        report["steps"][0]["extras"]["preserved"] = False
    elif case == "changed_rtl":
        rtl.write_text("module changed; endmodule\n")
    elif case == "changed_input":
        source_input.write_text("changed input\n")
    elif case == "foreign_report":
        report["runner_binding"]["project"] = str(tmp_path / "foreign")
    elif case == "stale_invocation":
        report["runner_binding"]["invocation_id"] = "0" * 32
    elif case == "foreign_runner":
        report["runner_binding"]["argv"][1] = str(tmp_path / "foreign.py")
    elif case == "foreign_attempt":
        monkeypatch.setenv(flow109.ATTEMPT_ENV, str(tmp_path / "foreign"))
    elif case == "foreign_native":
        context_path = Path(os.environ[flow109.CONTEXT_ENV])
        context = json.loads(context_path.read_text())
        context["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "2"
        context["context_sha256"] = flow109.digest(
            {key: value for key, value in context.items()
             if key != "context_sha256"})
        context_path.write_text(json.dumps(context))
    (tmp_path / "reports/orchestrator/phase2_one_shot.json").write_text(
        json.dumps(report, indent=2) + "\n")

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == expected
    assert answer["whole_flow_verdict"] == "NOT_MEASURED"


def test_d09_completion_does_not_overwrite_existing_attempt_result(
        tmp_path, monkeypatch):
    runner, report, _, _, invocation = _d09_owner_report(tmp_path, monkeypatch)
    result = Path(os.environ[flow109.ATTEMPT_ENV]) / "result.json"
    retained = b'{"immutable":"existing"}\n'
    result.write_bytes(retained)

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == "NOT_MEASURED"
    assert "FLOW109_ATTEMPT_RESULT_EXISTS" in answer["detail"]
    assert result.read_bytes() == retained


def _public_d09_entry(tmp_path, monkeypatch):
    """Configure the real public D09 entry with its separately-owned 1..4 span."""
    import _delivery_route
    import vibe_ic_one_shot_runner as runner

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    real_prepare = flow109.prepare_front_door

    def prepare_with_owned_span(args, project):
        result = real_prepare(args, project)
        if result is None:
            context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
            if context.get("requested_step") == "D09":
                args.exit_step = "4"
        return result

    monkeypatch.setattr(flow109, "prepare_front_door", prepare_with_owned_span)
    monkeypatch.setattr(
        runner._canonical_admission, "admit_span",
        lambda *_a, **_k: SimpleNamespace(admitted=True,
                                           identity_sha256="a" * 64))
    monkeypatch.setattr(
        runner._canonical_admission, "child_env",
        lambda _identity, env: dict(env))
    monkeypatch.setattr(sys, "argv", [
        str(Path(runner.__file__)), str(tmp_path), "--flow", "109",
        "--flow109-manifest", str(manifest), "--entry-step", "D09",
        "--exit-step", "D09", "--route", "ic", "--skip-phase1",
        "--skip-phase3", "--skip-analog", "--no-dashboard",
    ])
    return runner


def test_public_d09_entry_issues_child_binding_and_observes_terminal_result(
        tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design

    runner = _public_d09_entry(tmp_path, monkeypatch)
    body = _d09_report_body(tmp_path)
    report_path = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    issued = []

    def child(command, *, env=None, **_kwargs):
        context = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        issued.append(context)
        design._write_phase2_report(
            report_path, body, tmp_path, invocation_context=context)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)

    assert runner._main() == 0

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    terminal = json.loads((attempt / "result.json").read_text())
    report = json.loads(report_path.read_text())
    summary = json.loads(
        (tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert len(issued) == 1
    assert report["runner_binding"]["invocation_id"] == issued[0]["invocation_id"]
    assert report["runner_binding"]["argv"] == issued[0]["argv"]
    assert terminal["default_row_status"] == "PASS"
    assert terminal["components"][0]["step_id"] == "D09"
    assert summary["d09_finalization"]["verdict"] == "PASS"
    assert summary["whole_flow_verdict"] == "NOT_MEASURED"


def test_public_d09_entry_refuses_stale_retained_report_invocation(
        tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design

    runner = _public_d09_entry(tmp_path, monkeypatch)
    body = _d09_report_body(tmp_path)
    report_path = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    old_argv = [sys.executable, str(Path(runner.PROGRAMS_DIR) /
                "design_one_shot_runner.py"), str(tmp_path),
                "--entry-step", "1", "--exit-step", "4"]
    old_context = {
        "invocation_id": "0" * 32, "argv": old_argv,
        "project": str(tmp_path.resolve()),
        "source": dispatch._runner_source_snapshot(old_argv),
    }
    design._write_phase2_report(
        report_path, body, tmp_path, invocation_context=old_context)
    os.utime(report_path, (1, 1))
    launched = []

    def child(_command, *, env=None, **_kwargs):
        raw = (env or {}).get(dispatch._RUNNER_CONTEXT_ENV)
        launched.append(json.loads(raw) if raw else None)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)

    assert runner._main() == 1

    attempts = sorted((tmp_path / "reports/flow109/attempts").glob("window-*"))
    terminal = json.loads((attempts[-1] / "result.json").read_text())
    summary = json.loads(
        (tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert len(launched) == 1
    assert terminal["default_row_status"] == "NOT_MEASURED"
    assert terminal["components"][0]["completed"] is False
    assert summary["d09_finalization"]["verdict"] == "NOT_MEASURED"
    assert "D09_REPORT_UNBOUND" in summary["d09_finalization"]["detail"]
    assert launched[0]["invocation_id"] != old_context["invocation_id"]


@pytest.mark.parametrize("case,status,rc", [
    ("pass", "PASS", 0),
    ("producer_fail", "FAIL", 1),
    ("postcheck_not_measured", "NOT_MEASURED", 2),
])
def test_public_d26_owner_finalizes_selected_attempt(
        tmp_path, monkeypatch, case, status, rc):
    import _delivery_route
    import flow109
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    calls = []
    producer = "FAIL" if case == "producer_fail" else "PASS"
    monkeypatch.setattr(runner, "_complete_step10_prelayout",
                        lambda *_a, **_k: calls.append("producer") or {
                            "verdict": producer, "detail": case})
    monkeypatch.setattr(runner, "_complete_step8_postcheck",
                        lambda *_a, **_k: calls.append("postcheck") or {
                            "verdict": ("NOT_MEASURED"
                                        if case == "postcheck_not_measured" else "PASS"),
                            "detail": case})
    monkeypatch.setattr(sys, "argv", [str(Path(runner.__file__)), str(tmp_path),
                        "--flow", "109", "--flow109-manifest", str(manifest),
                        "--entry-step", "D26", "--exit-step", "D26",
                        "--route", "ip", "--no-dashboard"])

    assert runner._main() == rc

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    result = json.loads((attempt / "result.json").read_text())
    summary = json.loads((tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert result["schema"] == "vibeic.flow109.window-attempt-result.v1"
    assert result["default_row_status"] == status
    assert result["components"][0]["step_id"] == "D26"
    assert result["components"][0]["completed"] is (status == "PASS")
    assert summary["d26_finalization"]["verdict"] == status
    assert calls == (["producer"] if case == "producer_fail"
                     else ["producer", "postcheck"])


def test_public_d26_preexisting_attempt_result_is_not_overwritten(
        tmp_path, monkeypatch):
    import _delivery_route
    import flow109
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    monkeypatch.setattr(runner, "_complete_step10_prelayout",
                        lambda *_a, **_k: {"verdict": "FAIL", "detail": "producer failed"})
    finish = flow109.finish_native_window
    retained = '{"immutable":"existing"}\n'
    def preexisting(project, report):
        result = Path(os.environ[flow109.ATTEMPT_ENV]) / "result.json"
        result.write_text(retained)
        return finish(project, report)
    monkeypatch.setattr(flow109, "finish_native_window", preexisting)
    monkeypatch.setattr(sys, "argv", [str(Path(runner.__file__)), str(tmp_path),
                        "--flow", "109", "--flow109-manifest", str(manifest),
                        "--entry-step", "D26", "--exit-step", "D26",
                        "--route", "ip", "--no-dashboard"])

    assert runner._main() == 2

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    assert (attempt / "result.json").read_text() == retained
    summary = json.loads((tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert summary["d26_finalization"]["verdict"] == "NOT_MEASURED"
    assert summary["d26_finalization"]["detail"].startswith(
        "D26_FINALIZATION_REFUSED: FLOW109_ATTEMPT_RESULT_EXISTS:")


def test_owner_route_uses_native_span_without_generic_qualification_registry(
        tmp_path, monkeypatch):
    # prepare_front_door intentionally installs the active request; restore
    # that environment at this control's boundary, like the older control.
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    monkeypatch.setitem(sys.modules, "flow109_admission", SimpleNamespace(
        require_admission=lambda *a, **k: pytest.fail("generic qualification must not run")))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D12", exit_step="D12")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("2", "3")
    route = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert route["owner_runner"] == "design_one_shot_runner"
    assert route["native_step_id"] == "3"
    assert route["component_status"] == route["flow109_acceptance"] == "NOT_MEASURED"
    request = json.loads(Path(__import__("os").environ[flow109.CONTEXT_ENV]).read_text())
    assert request["requested_step"] == "D12"
    assert request["resolved_row"]["id"] == "D12"
    assert request["context_sha256"] == route["context_sha256"]
    attempt_value = __import__("os").environ.get(
        flow109.ATTEMPT_ENV, "ATTEMPT_ENV_UNSET")
    assert Path(attempt_value).parent.name == "attempts"
    attempt = Path(attempt_value)
    immutable = json.loads((attempt / "request.json").read_text())
    assert immutable["context_sha256"] == request["context_sha256"]
    assert immutable["registry_sha256"] == request["registry_sha256"]
    assert immutable["planner_sha256"] == request["planner_sha256"]


def test_d09_owner_span_routes_validation_without_neighbor_row_credit(
        tmp_path, monkeypatch):
    """D09 may consume the native span, but only D09 receives a row result."""
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D09")
    assert row["position"] == 17
    assert row["profile"]["dispatch"] == {
        "kind": "canonical_owner_window",
        "owner_runner": "design_one_shot_runner",
        "native_step_id": "1",
        "owner_entry_step": "1",
        "owner_exit_step": "4",
        "producer": "design_one_shot_runner.py:step_rtl_gen",
        "consumer": "design_one_shot_runner rtl_gen retained acceptance",
        "engine_families": [],
        "acceptance_scope": "existing_native_component_only",
        "flow109_metrics_status": "UNIMPLEMENTED",
    }

    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D09", exit_step="D09")

    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("1", "4")
    route = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert route["owner_runner"] == "design_one_shot_runner"
    assert (route["native_step_id"], route["entry_step"], route["exit_step"]) == (
        "1", "1", "4")
    request = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    report = {"steps": [{
        "status": "PASS", "extras": {"step_id": "1",
        "context_sha256": request["context_sha256"],
        "default_row_status": "PASS", "completed": True}}, *[
        {"status": "PASS", "extras": {"step_id": native,
         "context_sha256": request["context_sha256"],
         "default_row_status": "PASS", "completed": True,
         "metrics": {"must_not_be_credited": native}}}
        for native in ("2", "3", "4")
    ]]}

    result = flow109.finish_native_window(tmp_path, report)

    assert [item["step_id"] for item in result["components"]] == ["D09"]
    assert result["default_row_status"] == "PASS"
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["whole_flow_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False
    assert not any((tmp_path / "reports/flow109/default_rows" / f"{step}.json").exists()
                   for step in ("D11", "D12", "D13"))
    assert not any((tmp_path / "reports/flow109/components" / f"{step}.json").exists()
                   for step in ("D11", "D12", "D13"))
    assert "metrics" not in result["components"][0]


@pytest.mark.parametrize("step, adapter, component_scope", [
    ("D45", "flow109_netlist_cdc", None),
    ("D69", "flow109_final_extract", "native_final_gds_floating_fill_component"),
    ("D70", "flow109_final_electrical", "final_sta_native_component_only"),
    ("D71", "flow109_final_gls", "final_sdf_gls_component_only"),
])
def test_registered_native_component_route_does_not_claim_generic_qualification(
        step, adapter, component_scope):
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, step)
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["adapter"] == adapter
    assert dispatch.get("component_scope") == component_scope
    if step == "D69":
        assert dispatch['engine_families'] == ['magic']
        assert dispatch['engine_steps'] == {'magic': ['vibeic-final-fill-spef extract']}
    context = flow109.execution_context(plan, step, step)
    admission = flow109.source_owned_native_admission(context)
    assert admission["admitted"] is True
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"
    claimed = flow109.execution_context(plan, step, step, runtime_tool_uses=[],
                                        qualification_registry="input/qualifications.json")
    assert flow109.source_owned_native_admission(claimed) is None
    assert flow109.source_owned_native_dispatch(flow109.resolve_step(plan, "D62")) is None


def test_final_native_window_reaches_real_missing_input_refusal_without_generic_claim(
        tmp_path, monkeypatch):
    import _delivery_route
    import flow109_admission

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, __import__("os").environ.get(name, ""))
        monkeypatch.delenv(name)
    monkeypatch.setattr(
        flow109_admission, "require_admission",
        lambda *a, **k: pytest.fail("generic qualification must remain unclaimed"))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D69", exit_step="D71")

    assert flow109.prepare_front_door(args, tmp_path) == 2
    d69 = json.loads((tmp_path / "reports/flow109/components/D69.json").read_text())
    assert d69["component_status"] == "NOT_MEASURED"
    assert d69["reason"] == "D69_REQUIRED_INPUT_ABSENT"
    assert d69["native_started"] is False
    assert not (tmp_path / "reports/flow109/components/D70.json").exists()
    assert not (tmp_path / "reports/flow109/components/D71.json").exists()
    attempt = next((tmp_path / "reports/flow109/attempts").iterdir())
    terminal = json.loads((attempt / "result.json").read_text())
    assert terminal["component_status"] == "NOT_MEASURED"
    assert terminal["flow109_acceptance"] == "NOT_MEASURED"
    assert terminal["whole_flow_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("step, reason", [
    ("D69", "D69_REQUIRED_INPUT_ABSENT"),
    ("D70", "D70_REQUIRED_INPUT_ABSENT"),
    ("D71", "D71_INPUT_INVALID"),
])
def test_final_native_single_entry_reaches_own_missing_input_refusal(
        tmp_path, monkeypatch, step, reason):
    import _delivery_route
    import flow109_admission

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, __import__("os").environ.get(name, ""))
        monkeypatch.delenv(name)
    monkeypatch.setattr(
        flow109_admission, "require_admission",
        lambda *a, **k: pytest.fail("generic qualification must remain unclaimed"))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step=step, exit_step=step)

    assert flow109.prepare_front_door(args, tmp_path) == 2
    component = json.loads(
        (tmp_path / f"reports/flow109/components/{step}.json").read_text())
    assert component["component_status"] == "NOT_MEASURED"
    assert component["reason"] == reason
    assert component["native_started"] is False
    admission_record = json.loads(
        (tmp_path / "reports/flow109/admission.json").read_text())
    assert admission_record["status"] == "NOT_APPLICABLE"
    assert admission_record["qualification_status"] == "NOT_CLAIMED"
    assert admission_record["flow109_acceptance"] == "NOT_MEASURED"


def test_unregistered_adapter_cannot_select_existing_native_policy():
    row = flow109.resolve_step(flow109.resolve_plan(profile()), "D45")
    row["profile"]["dispatch"]["adapter"] = "caller_plugin"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_forged_backend_owner_cannot_select_existing_native_policy():
    row = flow109.resolve_step(flow109.resolve_plan(profile()), "D31")
    row["profile"]["dispatch"]["native_step_id"] = "caller-step"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d34_clock_planning_registers_real_special_owner_and_strict_claim_path():
    import flow109_clock_plan

    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D34")
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["native_step_id"] == "flow109.D34"
    assert dispatch["adapter"] == "flow109_clock_plan"
    assert dispatch["admission_policy"] == "source_owned_existing_native"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert flow109_clock_plan._consumer_row()["id"] == 16
    sources = flow109_clock_plan.operation_sources()
    assert "programs/phase3_one_shot_runner.py" in sources
    assert "programs/_physical_current.py" in sources
    assert "programs/clock_plan_check.py" in sources
    context = flow109.execution_context(plan, "D34", "D34")
    admission = flow109.source_owned_native_admission(context)
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"
    claimed = flow109.execution_context(
        plan, "D34", "D34", runtime_tool_uses=[],
        qualification_registry="input/qualifications.json")
    assert flow109.source_owned_native_admission(claimed) is None

    row["profile"]["dispatch"]["adapter"] = "flow109_missing_clock_owner"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d44_retained_lec_registers_only_existing_native_admission_fields():
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D44")
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["adapter"] == "flow109_final_lec"
    assert dispatch["native_step_id"] == "flow109.D44"
    assert dispatch["admission_policy"] == "source_owned_existing_native"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    context = flow109.execution_context(plan, "D44", "D44")
    admission = flow109.source_owned_native_admission(context)
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"

    del row["profile"]["dispatch"]["acceptance_scope"]
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d63_routes_only_to_current_canonical_default35_owner():
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D63")
    dispatch = flow109.source_owned_native_dispatch(row)

    assert row["profile"]["execution_status"] == "NATIVE_COMPONENT_ONLY_NOT_109_ACCEPTED"
    assert dispatch["kind"] == "canonical_backend_window"
    assert dispatch["native_step_id"] == "35"
    assert dispatch["producer"] == "execution_backend_producers.py:produce"
    assert dispatch["consumer"] == "execution_backend_gates.py:evaluate"
    assert dispatch["native_required_outputs"] == ["reports/phase3/dfm_screen.json"]
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert dispatch["flow109_metrics_status"] == "UNIMPLEMENTED"
    assert row["metric_acceptance_status"] == "UNIMPLEMENTED"
    assert row["gate_matrix_status"] == "NOT_MEASURED_FOR_109"

    context = flow109.execution_context(plan, "D63", "D63")
    admission = flow109.source_owned_native_admission(context)
    assert admission["admitted"] is True
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"

    context["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "34"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_CONTEXT_STALE"):
        flow109.validate_execution_context(context)


def test_owner_route_refuses_wrong_owner_and_unknown_native_mapping():
    plan = flow109.resolve_plan(profile())
    row = next(item for item in plan["rows"] if item["id"] == "D12")
    row["profile"]["dispatch"]["owner_runner"] = "phase1_one_shot_runner"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_OWNER_MISMATCH"):
        flow109.resolve_execution_window(plan, "D12", "D12")
    plan = flow109.resolve_plan(profile())
    row = next(item for item in plan["rows"] if item["id"] == "D12")
    row["profile"]["dispatch"]["native_step_id"] = "12"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_OWNER_NATIVE_MAPPING_UNKNOWN"):
        flow109.resolve_execution_window(plan, "D12", "D12")


def test_frontend_owner_window_preserves_existing_indivisible_spans():
    window = flow109.resolve_execution_window(flow109.resolve_plan(profile()), "D09", "D14")
    assert window["dispatch_kind"] == "canonical_owner_window"
    assert [row["id"] for row in window["resolved_rows"]] == [
        "D09", "D10", "D11", "D12", "D13", "D14"]
    assert (window["native_entry_step"], window["native_exit_step"]) == ("1", "5")

# Native completion is an owner answer, separate from whole-flow acceptance.
@pytest.mark.parametrize('component,status,completed,expected', [
    ('PASS','PASS',True,'PASS'), ('PASS','PASS',False,'NOT_MEASURED'),
    ('PASS',None,True,'NOT_MEASURED'), ('FAIL','PASS',True,'FAIL'),
    ('NOT_MEASURED','PASS',True,'NOT_MEASURED'), ('PASS','FAIL',False,'FAIL')])
def test_selected_native_completion_is_not_blanket_component_pass(
        tmp_path, component, status, completed, expected):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    result = {'step_id':'D11','context_sha256':context['context_sha256'],
              'component_status':component,'completed':completed}
    if status is not None: result['default_row_status'] = status
    answer = flow109._selected_step_result(tmp_path, context, result)
    assert answer['default_row_status'] == expected
    assert answer['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert answer['delivery_accepted'] is False


@pytest.mark.parametrize('field,value', [
    ('step_id','foreign'), ('context_sha256','foreign'),
    ('whole_flow_acceptance','PASS'), ('delivery_accepted',True)])
def test_selected_native_completion_rejects_foreign_identity_and_whole_claims(tmp_path,field,value):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    result = {'step_id':'D11','context_sha256':context['context_sha256'],
              'component_status':'PASS','default_row_status':'PASS','completed':True}
    result[field] = value
    with pytest.raises(flow109.Flow109Error, match='FLOW109_COMPONENT_RESULT_INVALID'):
        flow109._selected_step_result(tmp_path, context, result)
    assert not (tmp_path/'reports/flow109/default_rows/D11.json').exists()


def test_selected_native_completion_empty_is_not_a_result(tmp_path):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_COMPONENT_RESULT_INVALID'):
        flow109._selected_step_result(tmp_path, context, {})


def test_selected_completion_consumer_is_not_limited_to_a_row_allowlist(tmp_path):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    calls=[]
    def consume(project, request, component):
        calls.append(request['requested_step'])
        return {'step_id':'D11','context_sha256':request['context_sha256'],
                'default_row_status':'PASS','completed':True}
    answer=flow109._selected_step_result(tmp_path,context,
        {'step_id':'D11','context_sha256':context['context_sha256'],
         'component_status':'PASS','flow109_acceptance':'NOT_MEASURED'},
        SimpleNamespace(consume_default_row_completion=consume))
    assert calls==['D11'] and answer['default_row_status']=='PASS'


@pytest.mark.parametrize('native,status,completed,expected', [
    ('2','PASS',True,'PASS'), ('2','PASS',False,'NOT_MEASURED'),
    ('2','FAIL',False,'FAIL'), ('foreign','PASS',True,'NOT_MEASURED')])
def test_owner_finish_uses_only_selected_completed_native_result(
        tmp_path, monkeypatch, native,status,completed,expected):
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D11','D11')
    request=tmp_path/'request.json';request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    report={'steps':[{'status':status,'extras':{'step_id':native,
        'context_sha256':context['context_sha256'],
        'default_row_status':status,'completed':completed}}]}
    result=flow109.finish_native_window(tmp_path,report)
    assert result['default_row_status']==expected
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_owner_finish_rejects_stale_context_and_empty_report(tmp_path,monkeypatch):
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D11','D11')
    request=tmp_path/'request.json';request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    report={'steps':[{'status':'PASS','extras':{'step_id':'2',
        'context_sha256':'foreign','default_row_status':'PASS','completed':True}}]}
    with pytest.raises(flow109.Flow109Error,match='FLOW109_CONTEXT_STALE'):
        flow109.finish_native_window(tmp_path,report)
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    assert flow109.finish_native_window(tmp_path,{'steps':[]})['default_row_status']=='NOT_MEASURED'
    context['context_sha256']='stale';request.write_text(json.dumps(context))
    assert flow109.finish_native_window(tmp_path,report) is None


def test_selected_lint_window_stops_at_its_own_step():
    window=flow109.resolve_execution_window(flow109.resolve_plan(profile()),'D11','D11')
    assert window['resolved_row']['profile']['dispatch']['owner_exit_step']=='2'


def test_public_d10_missing_metric_binding_is_not_silent_success(tmp_path, monkeypatch):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    monkeypatch.setattr(runner, '_run_phase', lambda *args, **kwargs: 0)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: ('PASS', None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': 'PASS', 'steps': []})
    rc = runner._main()
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    terminal = json.loads((attempt / 'result.json').read_text())
    assert rc != 0
    assert terminal['default_row_status'] == 'NOT_MEASURED'
    assert terminal['components'][0]['step_id'] == 'D10'
    assert terminal['delivery_accepted'] is False
    summary = json.loads((tmp_path / 'reports/orchestrator/vibe_ic_one_shot.json').read_text())
    assert summary['d10_finalization']['verdict'] == 'NOT_MEASURED'
    assert 'D10_METRIC_BINDINGS_UNIMPLEMENTED' in summary['d10_finalization']['detail']


def test_public_d10_does_not_overwrite_existing_attempt_result(tmp_path, monkeypatch):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    retained = b'{"retained":true}\n'
    def child(*args, **kwargs):
        (Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').write_bytes(retained)
        return 0
    monkeypatch.setattr(runner, '_run_phase', child)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: ('PASS', None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': 'PASS', 'steps': []})
    assert runner._main() != 0
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    assert (attempt / 'result.json').read_bytes() == retained


def test_d10_refusal_tracks_selected_registry_binding(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner
    request = tmp_path / 'context.json'
    request.write_text('{}')
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    context = {'resolved_row': {'profile': {'dispatch': {'flow109_metrics_status': 'UNIMPLEMENTED'}}}}
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda _: context)
    assert runner._d10_metrics_unimplemented() is True
    context['resolved_row']['profile']['dispatch']['flow109_metrics_status'] = 'IMPLEMENTED'
    assert runner._d10_metrics_unimplemented() is False


def test_public_d10_does_not_mask_failed_phase2(tmp_path, monkeypatch):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    monkeypatch.setattr(runner, '_run_phase', lambda *args, **kwargs: 1)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: ('FAIL', None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': 'FAIL', 'steps': []})
    assert runner._main() != 0
    summary = json.loads((tmp_path / 'reports/orchestrator/vibe_ic_one_shot.json').read_text())
    phase2 = next(row for row in summary['phases'] if row['name'] == 'phase2')
    assert phase2['verdict'] == 'FAIL'
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    assert json.loads((attempt / 'result.json').read_text())['default_row_status'] == 'NOT_MEASURED'


def test_d10_yosys_observation_requires_matching_current_native_binding(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'attributes': {}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['status'] == 'OBSERVED'
    assert observation['elaboration_errors'] == 0
    assert observation['unexpected_blackboxes'] == 0
    assert observation['qualification'] == 'NOT_MEASURED'
    path.write_text(json.dumps({'modules': {'top': {'cells': {'u': {'type': 'foreign'}}}}}))
    assert runner._d10_yosys_observation(tmp_path)['status'] == 'NOT_MEASURED'


def test_d10_yosys_observation_does_not_approve_nonzero_blackboxes(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'cells': {'u': {'type': 'macro'}}},
                         'macro': {'attributes': {'blackbox': '1'}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['observed_blackbox_instances'] == ['u']
    assert observation['unexpected_blackboxes'] is None
    assert observation['qualification'] == 'NOT_MEASURED'


def test_d10_yosys_observation_follows_hierarchy_and_refuses_unknown_cells(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'cells': {'u': {'type': 'child'}}},
                         'child': {'cells': {'m': {'type': 'macro'}}},
                         'macro': {'attributes': {'blackbox': '1'}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['observed_blackbox_instances'] == ['u/m']
    assert observation['unexpected_blackboxes'] is None
    graph['modules']['child']['cells']['m']['type'] = 'undefined'
    path.write_text(json.dumps(graph))
    bound['sha256']['netlist.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert runner._d10_yosys_observation(tmp_path)['status'] == 'NOT_MEASURED'


def test_public_d10_keeps_yosys_observation_separate_from_row_verdict(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'modules': {'top': {'cells': {}}}}))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    monkeypatch.setattr(runner, '_run_phase', lambda *args, **kwargs: 0)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: ('PASS', None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': 'PASS', 'steps': []})
    assert runner._main() != 0
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    terminal = json.loads((attempt / 'result.json').read_text())
    assert terminal['default_row_status'] == 'NOT_MEASURED'
    observation = terminal['components'][0]['evidence']['yosys_observation']
    assert observation['elaboration_errors'] == 0
    assert observation['unexpected_blackboxes'] == 0
    assert observation['qualification'] == 'NOT_MEASURED'
    assert terminal['delivery_accepted'] is False


@pytest.mark.parametrize('mode', ['pass', 'yosys_fail', 'rtl_changed'])
def test_public_d10_runs_isolated_p0_but_never_promotes_missing_inventory(tmp_path, monkeypatch, mode):
    import re
    import p0_tool_frontend_check as frontend
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(runner._pl, 'published_here', lambda *_: True)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    top = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    top.parent.mkdir(parents=True)
    top.write_text(json.dumps({'top_module': 'top'}))
    prior = tmp_path / frontend.RTL_ELAB_REL
    prior.parent.mkdir(parents=True, exist_ok=True)
    prior.write_bytes(b'prior-native-evidence\n')
    def fake_tool(tool, args, project, image):
        if tool == 'yosys':
            if mode == 'yosys_fail':
                return SimpleNamespace(returncode=1, stdout='', stderr='native failure')
            output = Path(re.search(r'write_json\s+([^;\s]+)', args[-1]).group(1))
            output.write_text(json.dumps({'modules': {'top': {'attributes': {'top': '1'}, 'cells': {}}}}))
            if mode == 'rtl_changed':
                rtl.write_text(rtl.read_text() + '// changed while running\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(frontend, '_invoke', fake_tool)
    monkeypatch.setattr(runner, '_run_phase', lambda *args, **kwargs: 0)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: ('PASS', None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': 'PASS', 'steps': []})
    assert runner._main() != 0
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    terminal = json.loads((attempt / 'result.json').read_text())
    assert terminal['default_row_status'] == 'NOT_MEASURED'
    assert terminal['delivery_accepted'] is False
    p0 = terminal['components'][0]['evidence']['p0_native']
    assert p0['status'] == ('PASS' if mode == 'pass' else 'NOT_MEASURED')
    producer_result = tmp_path / p0['producer_result']['path']
    assert producer_result.is_file()
    recorded = json.loads(producer_result.read_text())
    assert recorded['tools']['Yosys.JsonHeader']['exit_code'] == (1 if mode == 'yosys_fail' else 0)
    if mode == 'pass':
        assert p0['qualification'] == 'NOT_MEASURED'
        assert (tmp_path / p0['elaboration_path']).is_file()
    assert prior.read_bytes() == b'prior-native-evidence\n'


@pytest.mark.parametrize('phase_verdict,fresh', [('PASS', False), ('FAIL', True)])
def test_public_d10_never_runs_p0_after_stale_or_failed_phase2(tmp_path, monkeypatch, phase_verdict, fresh):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D10' if x == 'D09' else x for x in sys.argv])
    monkeypatch.setattr(runner._pl, 'published_here', lambda *_: fresh)
    monkeypatch.setattr(runner, '_run_phase', lambda *args, **kwargs: 0)
    monkeypatch.setattr(runner, '_row_verdict', lambda *args, **kwargs: (phase_verdict, None))
    monkeypatch.setattr(runner, '_read_report', lambda *args, **kwargs: {'verdict': phase_verdict, 'steps': []})
    def forbidden(*_args):
        raise AssertionError('P0 must not run on a stale or failed producer')
    monkeypatch.setattr(runner, '_d10_p0_native', forbidden)
    assert runner._main() != 0
    attempt = next((tmp_path / 'reports/flow109/attempts').glob('window-*'))
    terminal = json.loads((attempt / 'result.json').read_text())
    assert terminal['default_row_status'] == 'NOT_MEASURED'
    assert terminal['components'][0]['evidence']['p0_native']['status'] == 'NOT_MEASURED'


def test_d10_single_gate_dry_run_real_frontend_positive_negative_and_no_project_writes(tmp_path, monkeypatch, capsys):
    import hashlib
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    argv = [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10', '--only',
            'p0_tool_frontend_check', '--dry-run']
    monkeypatch.setattr(sys, 'argv', argv)
    def snapshot():
        return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob('*') if p.is_file()}
    before = snapshot()
    assert runner._main() == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['gate_status'] == 'PASS'
    assert result['row_status'] == 'NOT_MEASURED'
    assert result['tool_qualification'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert snapshot() == before
    rtl.write_text('module top(input a, output y); missing_cell x(.a(a),.y(y)); endmodule\n')
    before = snapshot()
    assert runner._main() == 1
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['gate_status'] == 'FAIL'
    assert result['row_status'] == 'NOT_MEASURED'
    assert snapshot() == before


def test_d10_single_gate_dry_run_missing_binding_never_starts_flow(tmp_path, monkeypatch, capsys):
    import vibe_ic_one_shot_runner as runner
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10',
                                     '--only', 'feature_inventory', '--dry-run'])
    monkeypatch.setattr(flow109, 'prepare_front_door', lambda *_: pytest.fail('must not dispatch flow'))
    assert runner._main() == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['gate_status'] == result['row_status'] == 'NOT_MEASURED'
    assert result['reason'] == 'MISSING_ADOPTED_FEATURE_INVENTORY'
    assert list(tmp_path.iterdir()) == []


def test_d10_single_gate_dry_run_refuses_changed_inputs_and_untrusted_runtime(tmp_path, monkeypatch, capsys):
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10',
                                     '--only', 'p0_tool_frontend_check', '--dry-run'])
    def changed(_project, *, output_project):
        output = output_project / frontend.RTL_ELAB_REL
        output.parent.mkdir(parents=True)
        output.write_text('{"modules":{"top":{}}}')
        rtl.write_text(rtl.read_text() + '// changed\n')
        return {'passed': True, 'findings': [], 'tools': {
            'Yosys.JsonHeader': {'exit_code': 0}, 'Verilator.Lint': {'exit_code': 0}}}
    monkeypatch.setattr(frontend, 'check', changed)
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == answer['row_status'] == 'NOT_MEASURED'
    assert 'changed' in answer['detail']
    monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', str(tmp_path / 'missing.json'))
    monkeypatch.setattr(frontend, 'check', lambda *_a, **_k: pytest.fail('untrusted runtime must not run'))
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == 'NOT_MEASURED'


def test_d10_single_gate_dry_run_never_classifies_tool_crash_as_design_fail(tmp_path, monkeypatch, capsys):
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10',
                                     '--only', 'p0_tool_frontend_check', '--dry-run'])
    monkeypatch.setattr(frontend, 'check', lambda *_a, **_k: {'passed': False,
        'findings': ['tool crashed'], 'tools': {'Yosys.JsonHeader': {'exit_code': -9},
                                               'Verilator.Lint': {'exit_code': 0}}})
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == 'NOT_MEASURED'
    assert answer['reason'] == 'NATIVE_FRONTEND_ABNORMAL_TERMINATION'
    assert answer['row_status'] == 'NOT_MEASURED'


def test_dft_vocabulary_scan_and_non_scan_dft_selection(tmp_path):
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    scan = _intent()
    scan['requires_scan'] = True
    _publish_dft_intent(tmp_path, scan)
    features = profile('Small digital IC without DFT')
    features['requires_dft'] = True
    features['requires_scan'] = True
    rows = {row['id'] for row in flow109.resolve_plan(features)['rows']}
    assert {'D23', 'D24', 'D36'} <= rows
    binding = flow109.dft_source_intent(tmp_path, {'features': features})
    assert binding['requires_scan'] is True
    assert 'scan_test' not in binding

    features['requires_scan'] = False
    rows = {row['id'] for row in flow109.resolve_plan(features)['rows']}
    assert 'D23' in rows and 'D24' in rows and 'D36' not in rows
    registry = {r['id']: r for r in flow109.load_registry()['rows']}
    assert all(o['when'] == 'requires_scan' for o in registry['D23']['obligations'])
    assert all(o['when'] == 'requires_scan' for o in registry['D24']['obligations'])


def test_dft_vocabulary_rejects_old_key_and_unreasoned_negative(tmp_path):
    import fault_scan_chain_insert as producer
    features = profile('Small digital IC without DFT')
    _publish_dft_intent(tmp_path, {'scan_test': False, 'requires_scan': False,
                                   'reason': 'no scan required'})
    binding, problems = producer.load_d09_dft_contract(tmp_path)
    assert binding is None and 'DFT_INTENT_SCHEMA_INVALID' in str(problems)
    with pytest.raises(flow109.Flow109Error, match='D09_DFT_AUTHORITY_INVALID'):
        flow109.dft_source_intent(tmp_path, {'features': features})

    other = tmp_path / 'negative'; other.mkdir()
    _publish_dft_intent(other, {'requires_scan': False})
    with pytest.raises(flow109.Flow109Error, match='FLOW109_DFT_INTENT_MISSING'):
        flow109.dft_source_intent(other, {'features': features})

    good = tmp_path / 'reasoned'; good.mkdir()
    _publish_dft_intent(good, {'requires_scan': False, 'reason': 'no scan required'})
    binding = flow109.dft_source_intent(good, {'features': features})
    assert binding['requires_scan'] is False


def test_dft_vocabulary_unreasoned_negative_blocks_d22_front_door(tmp_path):
    import _delivery_route
    features = profile('Small digital IC without DFT')
    _publish_dft_intent(tmp_path, {'requires_scan': False})
    assert _delivery_route.admit(tmp_path, 'ic') is None
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D22', exit_step='D22', container='')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_DFT_INTENT_MISSING'):
        flow109.prepare_front_door(args, tmp_path)
    assert not (tmp_path / 'reports/flow109/owner_route.json').exists()


def test_dft_vocabulary_canonical_named_intent_rejects_legacy_key(tmp_path):
    import spec_declaration_emit as declaration
    import fault_scan_chain_insert as producer
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    intent = {'scan_test': False, 'requires_scan': False, 'reason': 'no scan required'}
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(intent)]) == 0
    assert (tmp_path / 'plugin_output/dft_intent.json').is_file()
    binding, problems = producer.load_d09_dft_contract(tmp_path)
    assert binding is None and 'DFT_INTENT_SCHEMA_INVALID' in str(problems)


def test_dft_vocabulary_mbist_plan_records_scan_metric_skips(tmp_path):
    import _delivery_route
    features = profile('Small digital IC without DFT')
    features['requires_dft'] = True
    features['requires_scan'] = False
    _publish_dft_intent(tmp_path, {'requires_scan': False, 'reason': 'MBIST only'})
    assert _delivery_route.admit(tmp_path, 'ic') is None
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=True, execution_mode='default',
                           entry_step='D22', exit_step='D24', container='')
    assert flow109.prepare_front_door(args, tmp_path) == 0
    plan = json.loads((tmp_path / 'reports/flow109/plan.json').read_text())
    assert {'D23', 'D24'} <= {row['id'] for row in plan['rows']}
    skips = plan['conditional_skips']
    assert skips and all(item['reason'] == 'MBIST only' for item in skips)
    assert not any(item['step_id'] in ('D23', 'D24') and 'metric' not in item for item in skips)
    assert any(item.get('metric') == 'scan_test_protocol_integrity' for item in skips)
    assert all(item.get('source_validated') is True for item in skips)


def test_d10_dft_ports_dry_run_real_frontend_positive_and_missing_port(tmp_path, monkeypatch, capsys):
    import hashlib
    import vibe_ic_one_shot_runner as runner
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    rtl.write_text('module top(input scan_enable, scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_enable ^ scan_in ^ test_mode ^ scan_clock; endmodule\n')
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10', '--only', 'dft_port_consistency', '--dry-run'])
    snapshot = lambda: {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    before = snapshot()
    assert runner._main() == 0
    good = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert good['gate_status'] == 'PASS' and good['row_status'] == 'NOT_MEASURED'
    assert snapshot() == before
    rtl.write_text('module top(input scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_in ^ test_mode ^ scan_clock; endmodule\n')
    before = snapshot()
    assert runner._main() == 1
    bad = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert bad['gate_status'] == 'FAIL' and bad['reason'] == 'DFT_PORT_MISMATCH'
    assert bad['port_evidence']['mismatches'][0]['role'] == 'scan_enable'
    assert bad['row_status'] == 'NOT_MEASURED' and snapshot() == before


def test_d10_dft_owner_consumes_current_native_elaboration(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import _specrtl_common
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_in ^ test_mode ^ scan_clock; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    result = frontend.check(tmp_path, output_project=tmp_path)
    assert result['passed'] is True
    path = tmp_path / frontend.RTL_ELAB_REL
    p0 = {'status': 'PASS', 'top': 'top', 'elaboration_path': frontend.RTL_ELAB_REL,
          'elaboration_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
          'input_fingerprint': native.source_binding(tmp_path, 'top', _specrtl_common.rtl_source_files(tmp_path))['fingerprint']}
    # This test isolates the DFT-port comparison; the P0 identity is tested
    # independently through its consumer and actual-source refusal controls.
    monkeypatch.setattr(runner, '_validate_d10_p0_consumer', lambda *_: {'status': 'PASS'})
    observed = runner._d10_dft_ports(tmp_path, p0)
    assert observed['status'] == 'FAIL' and observed['reason'] == 'DFT_PORT_MISMATCH'
    assert observed['mismatches'][0]['role'] == 'scan_enable'
    rtl.write_text(rtl.read_text() + '// changed after elaboration\n')
    assert runner._d10_dft_ports(tmp_path, p0)['status'] == 'NOT_MEASURED'


def test_d10_p0_consumer_binds_actual_argv_and_rejects_stale_inputs(tmp_path, monkeypatch):
    import hashlib
    import shutil
    import _cdc_netlist as native
    import _specrtl_common
    import librelane_contract as contract
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output b); assign b=a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    result = frontend.check(tmp_path, output_project=tmp_path)
    assert result['passed'] is True
    receipt = tmp_path / 'p0_result.json'; receipt.write_text(json.dumps(result))
    authority = {'image': 'image-ref', 'image_id': 'image-id', 'cid': 'cid', 'attestation_sha256': 'launch'}
    monkeypatch.setattr(contract, 'local_image_attestation', lambda: dict(authority))
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    p0 = {'status':'PASS', 'top':'top',
        'elaboration_path':frontend.RTL_ELAB_REL,
        'elaboration_sha256':digest(tmp_path / frontend.RTL_ELAB_REL),
        'producer_result': {'path':'p0_result.json', 'sha256':digest(receipt)},
        'input_fingerprint':native.source_binding(tmp_path, 'top', _specrtl_common.rtl_source_files(tmp_path))['fingerprint'],
        'producer_source_sha256':digest(frontend.__file__), 'runner_source_sha256':digest(runner.__file__),
        'tool_sha256':{name:digest(shutil.which(name)) for name in ('yosys','verilator')}, **authority}
    assert runner._validate_d10_p0_consumer(tmp_path, p0)['argv_validation'] == 'MATCH'
    bad = json.loads(receipt.read_text())
    bad['tools']['Yosys.JsonHeader']['argv'][4] = bad['tools']['Yosys.JsonHeader']['argv'][4].replace('read_slang', 'read_verilog', 1)
    receipt.write_text(json.dumps(bad)); p0['producer_result']['sha256'] = digest(receipt)
    with pytest.raises(ValueError, match='Yosys command'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    receipt.write_text(json.dumps(result)); p0['producer_result']['sha256'] = digest(receipt)
    wrong_image = dict(p0, image_id='foreign')
    with pytest.raises(ValueError, match='launch identity'):
        runner._validate_d10_p0_consumer(tmp_path, wrong_image)
    elab = tmp_path / frontend.RTL_ELAB_REL
    original_elab = elab.read_bytes(); elab.write_bytes(original_elab + b' ')
    with pytest.raises(ValueError, match='elaboration is missing or stale'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    elab.write_bytes(original_elab)
    rtl.write_text(rtl.read_text() + '// stale source\n')
    with pytest.raises(ValueError, match='source, producer or runner'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    assert p0['status'] == 'PASS'  # P0 only; this test does not claim D10.


def test_d10_dft_owner_finalizes_mismatch_as_fail(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner
    monkeypatch.setattr(runner, '_d10_p0_native', lambda _p: {'status': 'PASS'})
    monkeypatch.setattr(runner, '_d10_yosys_observation', lambda _p: {})
    monkeypatch.setattr(runner, '_d10_dft_ports', lambda _p, _p0: {'status': 'FAIL', 'reason': 'DFT_PORT_MISMATCH'})
    reports = []
    def finish(_p, report):
        reports.append(report)
        return {'default_row_status': report['steps'][0]['extras']['default_row_status']}
    monkeypatch.setattr(flow109, 'finish_native_window', finish)
    outcome = runner._finish_d10_unimplemented_owner(tmp_path, run_p0=True)
    assert reports[0]['steps'][0]['status'] == 'FAIL'
    assert outcome['verdict'] == 'FAIL' and outcome['whole_flow_verdict'] == 'NOT_MEASURED'


def test_d01_dft_producer_binding_and_wrong_owner_refusal(tmp_path):
    import phase1_one_shot_runner as phase1
    import fault_scan_chain_insert as scan
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent(), route='ip')
    produced = phase1._d01_emit_dft_intent(tmp_path)
    assert produced and produced['producer'] == 'D01'
    report = layout.report_path(tmp_path, 'phase1_one_shot.json')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'project': str(tmp_path.resolve()), **__import__('_delivery_route').report_label(tmp_path), 'dft_intent_output': produced}))
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding and not problems
    features = profile('Mapped soft-IP with prestitched scan')
    admission = flow109.dft_source_intent(tmp_path, {'features': features})
    assert admission['source_step'] == 'D01' and set(admission['source_evidence']) == {'D01'}
    for owner in ('D09', None):
        forged = dict(produced); forged['producer'] = owner
        report.write_text(json.dumps({'project': str(tmp_path.resolve()), **__import__('_delivery_route').report_label(tmp_path), 'dft_intent_output': forged}))
        binding, problems = scan.load_d09_dft_contract(tmp_path)
        assert binding is None and 'UNPROVEN_ADAPTER_BINDING' in str(problems)
        with pytest.raises(flow109.Flow109Error):
            flow109.dft_source_intent(tmp_path, {'features': features})


def test_d01_missing_dft_intent_blocks_d22(tmp_path):
    import _delivery_route
    features = profile('Small digital IC without DFT')
    assert _delivery_route.admit(tmp_path, 'ic') is None
    manifest = tmp_path / 'manifest.json'; manifest.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D22', exit_step='D22', container='')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_DFT_INTENT_MISSING'):
        flow109.prepare_front_door(args, tmp_path)
    assert not (tmp_path / 'reports/flow109/owner_route.json').exists()


def test_d01_producer_reaches_d22_and_d09_only_consumes(tmp_path, monkeypatch, capsys):
    import _delivery_route
    import phase1_one_shot_runner as phase1
    import design_one_shot_runner as design
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    assert phase1._as_the_producer(lambda _p: 0)(tmp_path) == 0
    produced = phase1._RUN['dft_intent_output']
    assert produced and produced['producer'] == 'D01'
    report = layout.report_path(tmp_path, 'phase1_one_shot.json'); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'project': str(tmp_path.resolve()), **__import__('_delivery_route').report_label(tmp_path), 'dft_intent_output': produced}))
    before = (tmp_path / produced['path']).read_bytes()
    early = design.declaration_before_step4(tmp_path)
    assert early['producer'] == 'D01' and early['emitted'] is True
    assert (tmp_path / produced['path']).read_bytes() == before
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input scan_enable, scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_enable ^ scan_in ^ test_mode ^ scan_clock; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    import flow109_metric_acceptance as metric
    diagnostic = metric.dry_run_d10(tmp_path, 'dft_port_consistency')
    assert diagnostic['gate_status'] == 'PASS'
    assert _delivery_route.admit(tmp_path, 'ic') is None
    features = profile('Small digital IC without DFT')
    features['requires_dft'] = features['requires_scan'] = True
    manifest = tmp_path / 'manifest.json'; manifest.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D22', exit_step='D22', container='')
    assert flow109.prepare_front_door(args, tmp_path) == 2
    assert 'FLOW109 D22: component NOT_MEASURED' in capsys.readouterr().out
    plan = json.loads((tmp_path / 'reports/flow109/plan.json').read_text())
    assert plan['dft_source_admission']['source_step'] == 'D01'


def test_d09_dft_consumer_refuses_wrong_owner_without_reemission(tmp_path, monkeypatch):
    import design_one_shot_runner as design
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    report = layout.report_path(tmp_path, 'phase1_one_shot.json')
    body = json.loads(report.read_text()); body['dft_intent_output']['producer'] = 'D09'
    report.write_text(json.dumps(body))
    artifact = tmp_path / body['dft_intent_output']['path']
    before = artifact.read_bytes()
    monkeypatch.setattr(design.subprocess, 'run', lambda *_a, **_kw: pytest.fail('D09 must not re-emit DFT intent'))
    result = design.declaration_before_step4(tmp_path)
    assert result['producer'] == 'D01' and result['emitted'] is False
    assert 'UNPROVEN_ADAPTER_BINDING' in result['reason']
    assert artifact.read_bytes() == before


def test_d01_fresh_author_decisions_produce_bound_intent(tmp_path):
    assert __import__('_delivery_route').admit(tmp_path, 'ic') is None
    import phase1_one_shot_runner as phase1
    import fault_scan_chain_insert as scan
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    docs = tmp_path / 'input/docs'; docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    decisions = tmp_path / 'input/feature-decisions.json'
    decisions.write_text(json.dumps({'dft': _intent()}))
    assert not (tmp_path / 'plugin_output/dft_intent.json').exists()
    assert phase1._as_the_producer(lambda _p: 0)(tmp_path) == 0
    output = phase1._RUN['dft_intent_output']
    assert output and output['producer'] == 'D01'
    assert output['path'] == 'plugin_output/dft_intent.json'
    assert 'input/feature-decisions.json' in output['sources']
    report = layout.report_path(tmp_path, 'phase1_one_shot.json'); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'project': str(tmp_path.resolve()), **__import__('_delivery_route').report_label(tmp_path), 'dft_intent_output': output}))
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding and not problems
    decisions.write_text(json.dumps({'dft': {'requires_scan': False, 'reason': 'changed'}}))
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding is None and problems


def test_d01_does_not_relabel_old_d09_decision_without_d01_source(tmp_path):
    import phase1_one_shot_runner as phase1
    import spec_declaration_emit as declaration
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    docs = tmp_path / 'input/docs'; docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(_intent())]) == 0
    old = (tmp_path / 'plugin_output/dft_intent.json').read_bytes()
    assert phase1._d01_emit_dft_intent(tmp_path) is None
    assert (tmp_path / 'plugin_output/dft_intent.json').read_bytes() == old


def test_d30_dft_plan_requires_source_bound_positive_limits(tmp_path):
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    data = _intent(); data['dft_plan'] = {'planned_chain_count': 2, 'max_chain_length': 128}
    _publish_dft_intent(tmp_path, data, route='ip')
    intent = flow109.dft_source_intent(tmp_path, {'features': profile('Mapped soft-IP with prestitched scan')})
    plan = flow109.dft_plan_reference(intent)
    assert plan['producer'] == 'D01' and plan['planned_chain_count'] == 2
    assert plan['max_chain_length'] == 128 and 'actual_chain_source' not in plan
    assert plan['sha256'] == intent['source_binding']['sha256']
    for bad in ({}, {'planned_chain_count': 0, 'max_chain_length': 128},
                {'planned_chain_count': 2, 'max_chain_length': True}):
        import copy
        invalid = copy.deepcopy(intent); invalid['source_binding']['intent']['dft_plan'] = bad
        with pytest.raises(flow109.Flow109Error, match='FLOW109_D30_DFT_PLAN_MISSING'):
            flow109.dft_plan_reference(invalid)
    assert flow109.dft_plan_reference({'requires_scan': False})['status'] == 'NOT_APPLICABLE'


def test_d23_openroad_scan_replace_component_no_chain_report(tmp_path, monkeypatch):
    import hashlib
    import os
    import subprocess
    from types import SimpleNamespace
    import design_one_shot_runner as design
    import vibe_ic_one_shot_runner as runner
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    base = Path('/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0')
    liberty = base / 'lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_3v30.lib'
    tech = base / 'techlef/gf180mcu_fd_sc_mcu9t5v0__nom.tlef'
    lef = base / 'lef/gf180mcu_fd_sc_mcu9t5v0.lef'
    assert all(p.is_file() for p in (liberty, tech, lef))
    source = tmp_path / 'unit.v'
    source.write_text('module unit(input clk, input d, output q); reg x,y; always @(posedge clk) begin x<=d; y<=x; end assign q=y; endmodule\n')
    mapped = tmp_path / 'mapped.v'
    run = subprocess.run(['yosys', '-Q', '-T', '-p', f'read_verilog {source}; synth -top unit; dfflibmap -liberty {liberty}; write_verilog -noattr {mapped}'], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    dft = _intent(); dft['dft_plan'] = {'planned_chain_count': 1, 'max_chain_length': 32}
    _publish_dft_intent(tmp_path, dft)
    features = profile('Small digital IC without DFT')
    features['requires_dft'] = features['requires_scan'] = True
    context = flow109.execution_context(flow109.resolve_plan(features), 'D23', 'D23')
    context_path = tmp_path / 'context.json'; context_path.write_text(json.dumps(context))
    attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    monkeypatch.setattr(design, '_phase2_pdk_config', lambda *_: SimpleNamespace(name='gf180mcuD', tech_lef=tech, cell_lef=lef, liberty=liberty))
    checkpoint = {'native_handoff': {'canonical': str(mapped), 'netlist_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest()}}
    result = runner._d23_scan_replace_component(tmp_path, 'unit', checkpoint)
    assert result['component_status'] == 'PASS', result
    assert result['verdict'] == result['whole_flow_verdict'] == 'NOT_MEASURED'
    artifact = tmp_path / result['scan_cell_list']['path']
    doc = json.loads(artifact.read_text())
    assert doc['producer'] == 'D23' and doc['operation'] == 'OpenROAD.scan_replace'
    assert all(len(doc[k]) == 64 for k in ('producer_source_sha256', 'comparator_source_sha256',
                                          'openroad_sha256', 'yosys_sha256', 'attestation_sha256'))
    assert doc['cid'] == os.environ.get('HOSTNAME') or doc['cid'].startswith(os.environ.get('HOSTNAME', 'invalid'))
    assert doc['returncode'] == 0 and doc['argv'][1:3] == ['-no_init', '-exit']
    for name in ('recipe', 'log'):
        rec = doc[name]; assert hashlib.sha256((tmp_path / rec['path']).read_bytes()).hexdigest() == rec['sha256']
    assert len(doc['cells']) == 2
    assert not (tmp_path / 'reports/phase2/dft/scan_chain.json').exists()
    checkpoint['native_handoff']['netlist_sha256'] = '0' * 64
    stale = runner._d23_scan_replace_component(tmp_path, 'unit', checkpoint)
    assert stale['component_status'] == stale['verdict'] == 'NOT_MEASURED'
    assert 'differs from synthesis handoff' in stale['detail']
    finished = runner._finish_selected_native_owner(tmp_path, '11', result)
    assert finished['default_row_status'] == 'NOT_MEASURED'
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D23.json').read_text())
    assert row['scan_cell_list'] == result['scan_cell_list']
    assert row['native_component_status'] == 'PASS' and row['default_row_status'] == 'NOT_MEASURED'
    intent = flow109.dft_source_intent(tmp_path, context)
    bound = flow109.d23_scan_replacement_binding(tmp_path, context, intent)
    assert bound['scan_cell_list'] == result['scan_cell_list'] and len(bound['cells']) == 2
    # D24 reads the actual D23 output in this same host-attested launch.
    import librelane_contract as native_contract
    d24_context = flow109.execution_context(flow109.resolve_plan(features), 'D24', 'D24')
    d24_context_path = tmp_path / 'd24-context.json'
    d24_context_path.write_text(json.dumps(d24_context))
    d24_attempt = flow109._new_attempt(tmp_path, d24_context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(d24_context_path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(d24_attempt))
    authority = native_contract.local_image_attestation()
    with monkeypatch.context() as stale_launch:
        stale_launch.setenv('VIBEIC_FLOW109_D23_ATTESTATION', str(tmp_path / 'absent-launch.json'))
        refused = runner._complete_step12_post_dft(tmp_path, 'unused')
        assert refused['verdict'] == 'NOT_MEASURED'
        assert 'FLOW109_D23_ORIGINAL_LAUNCH_UNPROVEN' in refused['detail']
        assert not (d24_attempt / 'd24_post_dft.v').exists()
    optimized = runner._complete_step12_post_dft(tmp_path, 'unused')
    assert optimized['component_status'] == 'PASS', optimized
    assert optimized['verdict'] == optimized['whole_flow_verdict'] == 'NOT_MEASURED'
    receipt = json.loads((tmp_path / optimized['post_dft_component']['path']).read_text())
    assert receipt['source'] == bound['replaced']
    assert receipt['scan_cell_list'] == result['scan_cell_list']
    assert (tmp_path / receipt['netlist']['path']).is_file()
    d24_finished = runner._finish_selected_native_owner(tmp_path, '12', optimized)
    assert d24_finished['default_row_status'] == 'NOT_MEASURED'
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    # Exercise the real D30 admission and D24 list consumer with a real D23
    # producer. LEC and STA here are synthetic fixture inputs, not native proof.
    import lec_gate_netlist_select as netlists
    adopted_path = tmp_path / 'phase2/stage2/synth/post_dft_netlist.v'
    adopted_path.parent.mkdir(parents=True, exist_ok=True)
    adopted_path.write_bytes((tmp_path / receipt['netlist']['path']).read_bytes())
    def adopted_ref():
        return {'artifact_id': 'D24_POST_SCAN_NETLIST',
                'path': 'phase2/stage2/synth/post_dft_netlist.v',
                'sha256': hashlib.sha256(adopted_path.read_bytes()).hexdigest()}
    rows = tmp_path / 'reports/flow109/default_rows'
    def publish_d24():
        (rows / 'D24.json').write_text(json.dumps({'step_id': 'D24',
            'default_row_status': 'PASS', 'completed': True,
            'adopted_netlist': adopted_ref(), 'scan_cell_list': result['scan_cell_list']}))
    publish_d24()
    for step in ('D25', 'D26'):
        (rows / f'{step}.json').write_text(json.dumps(
            {'step_id': step, 'default_row_status': 'PASS', 'completed': True}))
    manifest = tmp_path / 'input/flow109/D22.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({'top': 'unit'}))
    (tmp_path / 'reports/lec.json').write_text(json.dumps({'verdict': 'PASS', 'equivalent': True,
        'proof_identity': {'gate_netlist': {'path': str(adopted_path.relative_to(tmp_path)),
            'sha256': 'sha256:' + hashlib.sha256(adopted_path.read_bytes()).hexdigest()}}}))
    monkeypatch.setattr(netlists, 'proof_subject_binding', lambda *_: {'state': netlists.BINDING_MATCH})
    # D25 and D26 are synthetic in this D23/D24 native component test.
    synthetic_folder = tmp_path / 'phase3/librelane/synthetic-sta'
    synthetic_folder.mkdir(parents=True, exist_ok=True)
    state = synthetic_folder / 'state_in.json'
    state.write_text(json.dumps({'nl': str(adopted_path.resolve())}))
    synthetic_receipt = {'input': {'state': hashlib.sha256(state.read_bytes()).hexdigest(),
        'state_files': {str(adopted_path.resolve()): hashlib.sha256(adopted_path.read_bytes()).hexdigest()}},
        'sha256': {'state_in.json': hashlib.sha256(state.read_bytes()).hexdigest()}}
    (synthetic_folder / 'vibeic_receipt.json').write_text(json.dumps(synthetic_receipt))
    (synthetic_folder / 'state_out.json').write_text(json.dumps({'nl': str(adopted_path.resolve())}))
    monkeypatch.setattr(native_contract, 'validate_step_receipt', lambda folder, *_:
                        json.loads((folder / 'vibeic_receipt.json').read_text()))
    monkeypatch.setattr(flow109, '_d26_timing_modes_binding', lambda *a, **k:
        {'post_scan_arms': {'functional': {'native': {'folder': str(synthetic_folder.relative_to(tmp_path))}}}})
    accepted = flow109.dft_preroute_admission(tmp_path, context)
    assert accepted['native_chain']['producer_step'] == 'D36'
    assert accepted['flow109_acceptance'] == 'NOT_MEASURED'
    assert accepted['scan_cell_list_reconciliation']['scan_cell_list'] == result['scan_cell_list']
    assert not (tmp_path / 'reports/phase2/dft/scan_chain.json').exists()
    original = adopted_path.read_text()
    adopted_path.write_text(original.replace(doc['cells'][0]['cell'], 'missing_scan_cell', 1))
    publish_d24()
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D30_SCAN_CELL_LIST_MISMATCH'):
        flow109.dft_preroute_admission(tmp_path, context)
    adopted_path.write_text(original)
    publish_d24()
    artifact.write_text(artifact.read_text() + ' ')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D23_SCAN_CELLS_STALE'):
        flow109.d23_scan_replacement_binding(tmp_path, context, intent)


def test_d23_component_reference_survives_finalization_without_row_pass(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner
    seen = []
    monkeypatch.setattr(flow109, 'finish_native_window', lambda _p, report: seen.append(report) or report)
    ref = {'path': 'attempt/d23_scan_cells.json', 'sha256': 'a' * 64}
    result = runner._finish_selected_native_owner(tmp_path, '11', {
        'verdict': 'NOT_MEASURED', 'component_status': 'PASS', 'scan_cell_list': ref})
    extra = seen[0]['steps'][0]['extras']
    assert extra['scan_cell_list'] == ref and extra['native_component_status'] == 'PASS'
    assert extra['default_row_status'] == 'NOT_MEASURED' and extra['completed'] is False
    assert result['steps'][0]['status'] == 'NOT_MEASURED'


def test_d23_original_launch_reuse_requires_unchanged_host_receipt(tmp_path, monkeypatch):
    import hashlib
    old_cid, new_cid = '12' * 32, '34' * 32
    image = 'sha256:' + 'ab' * 32
    launch = {'cid': old_cid, 'image': image,
        'container_inspect': {'Id': old_cid, 'Image': image,
            'Config': {'Image': image, 'Hostname': old_cid[:12]},
            'State': {'Running': True, 'Paused': False, 'Dead': False}},
        'image_inspect': [{'Id': image, 'RepoDigests': []}]}
    receipt = tmp_path / 'original-launch.json'
    receipt.write_text(json.dumps(launch))
    doc = {'cid': old_cid, 'image': image, 'image_id': image,
           'attestation_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}
    current = {'cid': new_cid, 'image': image, 'image_id': image,
               'attestation_path': str(tmp_path / 'current-launch.json')}
    monkeypatch.setenv('VIBEIC_FLOW109_D23_ATTESTATION', str(receipt))
    flow109._d23_original_launch(doc, current)
    receipt.write_text(receipt.read_text() + ' ')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D23_ORIGINAL_LAUNCH_UNPROVEN'):
        flow109._d23_original_launch(doc, current)
    monkeypatch.setenv('VIBEIC_FLOW109_D23_ATTESTATION', str(tmp_path / 'missing'))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D23_ORIGINAL_LAUNCH_UNPROVEN'):
        flow109._d23_original_launch(doc, current)


def test_d30_delivery_owner_records_current_adopted_netlist_and_refuses_stale(tmp_path, monkeypatch):
    import hashlib
    import design_one_shot_runner as design
    import step_output_collector as versions
    context = _d30_scan_case(tmp_path, monkeypatch)
    context_path = tmp_path / 'd30-context.json'
    context_path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    attempt = flow109._new_attempt(tmp_path, context)
    versions_root = versions._versions_root(tmp_path)
    folder = 'test-d30-handoff'
    handoff = versions_root / folder / 'outputs.json'
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(json.dumps({'canonical_pass': True, 'status': 'PASS'}))
    monkeypatch.setattr(design, '_current_phase2_consumer',
                        lambda _p, _s, _t: {'folder': folder})
    ref = design._d30_publish_delivery(tmp_path, context, attempt, folder)
    receipt = json.loads((tmp_path / ref['path']).read_text())
    delivered = tmp_path / receipt['delivered_netlist']['path']
    assert receipt['step_id'] == 'D30'
    assert receipt['context_sha256'] == context['context_sha256']
    assert receipt['window_context_sha256'] == context['context_sha256']
    assert receipt['handoff_folder'] == folder
    assert receipt['flow109_acceptance'] == 'NOT_MEASURED'
    assert hashlib.sha256(delivered.read_bytes()).hexdigest() == receipt['source_netlist']['sha256']
    admission = flow109.dft_preroute_admission(tmp_path, context)
    chain = flow109._complete_preroute_chain(
        tmp_path, context, admission, ref, d30_context_sha256=context['context_sha256'])
    assert chain['status'] == 'PASS', chain
    assert set(chain['references']) == {'D24', 'D25', 'D26', 'D30'}
    assert chain['references']['D30']['path'] != chain['references']['D24']['path']
    assert chain['flow109_acceptance'] == 'NOT_MEASURED'
    selected = flow109._selected_step_result(tmp_path, context, {
        'step_id': 'D30', 'context_sha256': context['context_sha256'],
        'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True,
        'd30_delivery_receipt': ref})
    assert selected['dft_preroute_admission']['normalized_preroute_chain']['status'] == 'PASS'
    assert selected['default_row_status'] == 'NOT_MEASURED'
    assert selected['normalized_chain_reason'] == 'D30_METRIC_BINDINGS_UNIMPLEMENTED'
    with monkeypatch.context() as stale:
        stale.setattr(design, '_current_phase2_consumer', lambda *_: None)
        rejected = flow109._complete_preroute_chain(
            tmp_path, context, admission, ref, d30_context_sha256=context['context_sha256'])
        assert rejected['status'] == 'NOT_MEASURED'
        assert rejected['reason'] == 'D30_DELIVERY_BINDING_UNPROVEN'
    original_delivery = delivered.read_bytes()
    delivered.write_bytes(original_delivery + b'\n')
    stale_delivery = flow109._complete_preroute_chain(
        tmp_path, context, admission, ref, d30_context_sha256=context['context_sha256'])
    assert stale_delivery['status'] == 'NOT_MEASURED'
    assert stale_delivery['reason'] == 'D30_DELIVERY_BINDING_UNPROVEN'
    delivered.write_bytes(original_delivery)
    assert delivered != tmp_path / receipt['source_netlist']['path']
    # Exercise the actual handoff owner with retained producer acceptance as a
    # fixture. The D30 row verdict and native LEC/STA are not asserted here.
    owner_attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(owner_attempt))
    monkeypatch.setattr(versions, '_read_index', lambda _p: {'steps': [{'id': '14', 'folder': folder}]})
    monkeypatch.setattr(design._spf, 'retained_call', lambda *a, **kw: {
        'current_step_producers': {'verdict': 'PASS', 'executed': 1}})
    owner = design.step_synthesis_handoff(tmp_path)
    assert owner.status == 'PASS'
    assert owner.extras['d30_delivery_receipt']['path'].startswith(
        str(owner_attempt.relative_to(tmp_path)))
    second = flow109._new_attempt(tmp_path, context)
    monkeypatch.setattr(design, '_current_phase2_consumer', lambda *_: None)
    with pytest.raises(ValueError, match='handoff consumer is not current'):
        design._d30_publish_delivery(tmp_path, context, second, folder)
    assert not (second / 'd30_delivered_netlist.v').exists()

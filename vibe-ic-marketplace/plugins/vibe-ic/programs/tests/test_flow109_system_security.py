"""Focused D16/D17/D73 producer-reader and value-negative controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import flow109_system_security as S
import flow109


def _put(project: Path, name: str, value) -> dict:
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _context(row_id: str) -> dict:
    registry = json.loads((Path(S.__file__).parent.parent / "flow/flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == row_id)
    row["profile"] = next(item for item in row["profiles"] if item["id"] == "default")
    return {"requested_step": row_id, "native_step_id": f"flow109.{row_id}",
            "context_sha256": row_id.lower() * 32, "resolved_row": row}


def test_owned_registry_routes_only_the_three_existing_components():
    registry = flow109.load_registry()
    features = next(item["features"] for item in registry["reference_profiles"]
                    if item["name"] == "Low-power secure scan SoC")
    plan = flow109.resolve_plan(features)
    for row_id in ("D16", "D17", "D73"):
        row = flow109.resolve_step(plan, row_id)
        dispatch = flow109.source_owned_native_dispatch(row)
        assert dispatch["adapter"] == "flow109_system_security"
        assert dispatch["native_step_id"] == f"flow109.{row_id}"
        admitted = flow109.source_owned_native_admission(
            flow109.execution_context(plan, row_id, row_id))
        assert admitted["qualification_status"] == "NOT_CLAIMED"
        assert admitted["flow109_acceptance"] == "NOT_MEASURED"


def _d16_case(project: Path):
    log = _put(project, "native/run.log", "SYSTEM_PASS\n")
    tb = _put(project, "native/system_tb.v", "module system_tb; endmodule\n")
    rtl = _put(project, "phase2/stage1/rtl/chip_top.v", "module chip_top; endmodule\n")
    model = _put(project, "native/cell_model.v", "module cell_model; endmodule\n")
    l10 = _put(project, "phase1/generated_docs/L10_TEST_CASES.json",
               {"test_cases": [{"name": "firmware_gpio"}]})
    record = _put(project, "native/functional_cases.json", {
        "program": "full_stack_functional_tb",
        "schema": "vibeic.full_stack_functional.v1",
        "verdict": "PASS", "full_stack_top": {"module": "chip_top", "refusal": None},
        "design_input": {"L10_TEST_CASES.json": l10["sha256"]},
        "sources": [rtl], "models": [model],
        "cases": [{"name": "firmware_gpio", "state": "passed",
                   "tb": tb["path"], "tb_sha256": tb["sha256"],
                   "run_log": log["path"], "run_log_sha256": log["sha256"]}]})
    _put(project, S.MANIFESTS["D16"], {"schema": S.SCHEMA, "step_id": "D16",
        "full_stack_record": record,
        "required_scenarios": [{"id": "firmware_gpio", "case": "firmware_gpio"}]})


def _formal(project: Path, obligation: str) -> dict:
    safe = obligation.replace(".", "_")
    sby = _put(project, f"formal/{safe}.sby", "[options]\nmode prove\n")
    log = _put(project, f"formal/{safe}.log", "SBY DONE (PASS, rc=0)\n")
    proof = _put(project, f"formal/{safe}.sv",
                 "module proof;\n  required_guard: assert (1'b1);\nendmodule\n")
    task = S.SECURITY_TASKS[obligation]
    result = _put(project, f"formal/{safe}.json", {
        "program": "formal_property_run", "verdict": "PASS", "all_proved": True,
        "unbounded_proved": True, "proof_strength": "unbounded", "failed": 0,
        "properties": [{"task": task, "mode": "prove", "status": "PASS",
                         "bound": "unbounded"}],
        "sby": sby["path"], "evidence": log["path"],
        "sby_sha256": sby["sha256"], "evidence_sha256": log["sha256"],
        "proof_inputs": {"files": {Path(proof["path"]).name: proof["sha256"]}}})
    return {"result": result, "task": task}


def _d17_case(project: Path):
    text = "\n".join(f"| {item} | Required security condition. |" for item in S.SECURITY_IDS) + "\n"
    source = _put(project, "input/docs/security.md", text)
    requirements = [{"id": item, "sources": [{
        "file": source, "line_start": index + 1, "line_end": index + 1,
        "excerpt": text.splitlines()[index]}], "proof_binding": {
            "legacy_id": item, "task": S.SECURITY_TASKS[item], "properties": ["required_guard"]}}
        for index, item in enumerate(S.SECURITY_IDS)]
    component = _put(project, "formal/component_property_contract.json", {"property_denominator": 3})
    contract = _put(project, "input/flow109/property_contract.json", {
        "property_denominator": 3, "catalogue_source": source,
        "required_security_requirements": requirements})
    proofs = {item: _formal(project, item) for item in S.SECURITY_IDS}
    for binding in proofs.values():
        path = project / binding["result"]["path"]
        result = json.loads(path.read_text())
        result.update(property_contract=component["path"], property_contract_sha256=component["sha256"],
                      property_denominator=3, authored_property_count=3, unresolved_obligations=[])
        binding["result"] = _put(project, binding["result"]["path"], result)
    _put(project, S.MANIFESTS["D17"], {"schema": S.SCHEMA, "step_id": "D17",
        "property_contract": contract, "component_contract": component,
        "required_security_requirements": list(S.SECURITY_IDS), "formal_results": proofs})


def test_d16_reopens_canonical_full_stack_population_and_rejects_old_skeleton(tmp_path):
    _d16_case(tmp_path)
    result = S.execute(tmp_path, _context("D16"))
    assert result["component_status"] == "PASS", result
    record = tmp_path / "native/functional_cases.json"
    old = {"verdict": "PASS", "functional_verified": False, "vectors_total": 8}
    record.write_text(json.dumps(old))
    manifest = json.loads((tmp_path / S.MANIFESTS["D16"]).read_text())
    manifest["full_stack_record"]["sha256"] = hashlib.sha256(record.read_bytes()).hexdigest()
    (tmp_path / S.MANIFESTS["D16"]).write_text(json.dumps(manifest))
    refused = S.execute(tmp_path, _context("D16"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "D16_NATIVE_PRODUCER_MISMATCH"


def test_d16_missing_required_scenario_and_stale_log_refuse(tmp_path):
    _d16_case(tmp_path)
    manifest = json.loads((tmp_path / S.MANIFESTS["D16"]).read_text())
    manifest["required_scenarios"][0]["case"] = "hello_missing"
    (tmp_path / S.MANIFESTS["D16"]).write_text(json.dumps(manifest))
    assert S.execute(tmp_path, _context("D16"))["reason"] == "D16_REQUIRED_SCENARIO_NOT_PASSED"
    _d16_case(tmp_path)
    (tmp_path / "native/run.log").write_text("changed\n")
    assert S.execute(tmp_path, _context("D16"))["reason"] == "FLOW109_SECURITY_INPUT_STALE"


def test_d17_requires_all_three_current_unbounded_formal_results(tmp_path):
    _d17_case(tmp_path)
    result = S.execute(tmp_path, _context("D17"))
    assert result["component_status"] == "PASS", result
    assert result["metrics"]["security_counterexample_failures"] == 0
    manifest = json.loads((tmp_path / S.MANIFESTS["D17"]).read_text())
    manifest["formal_results"][S.SECURITY_IDS[0]]["task"] = S.SECURITY_TASKS[S.SECURITY_IDS[1]]
    (tmp_path / S.MANIFESTS["D17"]).write_text(json.dumps(manifest))
    refused = S.execute(tmp_path, _context("D17"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "D17_FORMAL_REQUIREMENT_MISMATCH"


def test_d17_counterexample_is_fail_not_not_measured(tmp_path):
    _d17_case(tmp_path)
    path = tmp_path / "formal/opentitan_aes_sparse_fsm_alert.json"
    body = json.loads(path.read_text())
    body.update(verdict="FAIL", all_proved=False, failed=1)
    body["properties"][0].update(status="FAIL", bound="cex")
    path.write_text(json.dumps(body))
    manifest = json.loads((tmp_path / S.MANIFESTS["D17"]).read_text())
    manifest["formal_results"][S.SECURITY_IDS[1]]["result"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / S.MANIFESTS["D17"]).write_text(json.dumps(manifest))
    result = S.execute(tmp_path, _context("D17"))
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D17_SECURITY_COUNTEREXAMPLE"


def test_d17_stale_proof_input_refuses_and_restored_bytes_pass(tmp_path):
    _d17_case(tmp_path)
    proof = tmp_path / "formal/opentitan_aes_shadowed_controls.sv"
    original = proof.read_bytes()
    proof.write_text("module changed; endmodule\n")
    refused = S.execute(tmp_path, _context("D17"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "D17_FORMAL_INPUTS_STALE"
    proof.write_bytes(original)
    restored = S.execute(tmp_path, _context("D17"))
    assert restored["component_status"] == "PASS", restored


def test_d17_stale_sby_and_transcript_refuse_and_restored_bytes_pass(tmp_path):
    _d17_case(tmp_path)
    for leaf in ("opentitan_aes_shadowed_controls.sby",
                 "opentitan_aes_shadowed_controls.log"):
        path = tmp_path / "formal" / leaf
        original = path.read_bytes()
        path.write_bytes(original + b"\npost-proof mutation\n")
        refused = S.execute(tmp_path, _context("D17"))
        assert refused["component_status"] == "NOT_MEASURED"
        assert refused["reason"] == "D17_FORMAL_EVIDENCE_STALE"
        path.write_bytes(original)
        restored = S.execute(tmp_path, _context("D17"))
        assert restored["component_status"] == "PASS", restored


def test_d17_missing_proof_time_sby_or_transcript_digest_refuses(tmp_path):
    _d17_case(tmp_path)
    manifest_path = tmp_path / S.MANIFESTS["D17"]
    manifest = json.loads(manifest_path.read_text())
    result_ref = manifest["formal_results"][S.SECURITY_IDS[0]]["result"]
    result_path = tmp_path / result_ref["path"]
    result = json.loads(result_path.read_text())
    result.pop("sby_sha256")
    result_path.write_text(json.dumps(result))
    result_ref["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    refused = S.execute(tmp_path, _context("D17"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "D17_FORMAL_EVIDENCE_UNBOUND"


def _d73_case(project: Path):
    _d17_case(project)
    d17 = S.execute(project, _context("D17"))
    netlist = _put(project, "adopted/aes.v", """
module chip_top(clk_i, lc_escalate_en_i, alert_fatal_o, test_done_o);
wire shadow_q, committed_q, err_update;
wire [5:0] aes_ctrl_cs;
wire sparse_alert;
endmodule
""")
    baseline = _put(project, "reports/flow109/D44/common-baseline.json", {
        "producer": "flow109_final_lec", "adopted_netlist": netlist})
    d44 = _put(project, "reports/flow109/D44/component.json", {
        "step_id": "D44", "component_status": "PASS",
        "metric_acceptance_status": "PASS", "common_baseline": baseline})
    _put(project, S.MANIFESTS["D73"], {"schema": S.SCHEMA, "step_id": "D73",
        "d17_component": d17["receipt"], "d44_component": d44,
        "adopted_netlist": netlist, "top": "chip_top"})


def _rebind_d44(project: Path, digest: str):
    baseline_path = project / "reports/flow109/D44/common-baseline.json"
    baseline = json.loads(baseline_path.read_text())
    baseline["adopted_netlist"]["sha256"] = digest
    baseline_path.write_text(json.dumps(baseline))
    component_path = project / "reports/flow109/D44/component.json"
    component = json.loads(component_path.read_text())
    component["common_baseline"]["sha256"] = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    component_path.write_text(json.dumps(component))
    manifest_path = project / S.MANIFESTS["D73"]
    manifest = json.loads(manifest_path.read_text())
    manifest["d44_component"]["sha256"] = hashlib.sha256(component_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_d73_binds_current_d17_and_adopted_security_population(tmp_path):
    _d73_case(tmp_path)
    result = S.execute(tmp_path, _context("D73"))
    assert result["component_status"] == "PASS", result
    assert result["metrics"]["scan_debug_access_violations"] == 0
    netlist = tmp_path / "adopted/aes.v"
    netlist.write_text(netlist.read_text().replace("shadow_q", "removed_q"))
    manifest = json.loads((tmp_path / S.MANIFESTS["D73"]).read_text())
    manifest["adopted_netlist"]["sha256"] = hashlib.sha256(netlist.read_bytes()).hexdigest()
    (tmp_path / S.MANIFESTS["D73"]).write_text(json.dumps(manifest))
    _rebind_d44(tmp_path, manifest["adopted_netlist"]["sha256"])
    refused = S.execute(tmp_path, _context("D73"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "D73_IMPLEMENTED_SECURITY_POPULATION_MISSING"


def test_d73_exposed_debug_port_is_measured_failure(tmp_path):
    _d73_case(tmp_path)
    netlist = tmp_path / "adopted/aes.v"
    netlist.write_text(netlist.read_text().replace("test_done_o", "test_done_o, debug_en"))
    manifest = json.loads((tmp_path / S.MANIFESTS["D73"]).read_text())
    manifest["adopted_netlist"]["sha256"] = hashlib.sha256(netlist.read_bytes()).hexdigest()
    (tmp_path / S.MANIFESTS["D73"]).write_text(json.dumps(manifest))
    _rebind_d44(tmp_path, manifest["adopted_netlist"]["sha256"])
    result = S.execute(tmp_path, _context("D73"))
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D73_TEST_DEBUG_ACCESS_EXPOSED"



def test_additional_source_required_unproved_property_blocks_completion(tmp_path):
    _d17_case(tmp_path)
    manifest_path = tmp_path / S.MANIFESTS["D17"]
    manifest = json.loads(manifest_path.read_text())
    doc = tmp_path / "input/docs/security.md"
    extra = "| EXTRA.PROTECTION | Additional mandatory protection. |"
    source = _put(tmp_path, "input/docs/security.md", doc.read_text() + extra + "\n")
    path = tmp_path / manifest["property_contract"]["path"]
    contract = json.loads(path.read_text())
    contract["catalogue_source"] = source
    for row in contract["required_security_requirements"]:
        row["sources"][0]["file"] = source
    # Omitting the newly documented requirement must refuse, not select only
    # the old passing population.
    manifest["property_contract"] = _put(tmp_path, str(path.relative_to(tmp_path)), contract)
    manifest_path.write_text(json.dumps(manifest))
    omitted = S.execute(tmp_path, _context("D17"))
    assert omitted["component_status"] == "NOT_MEASURED"
    assert omitted["reason"] == "D17_SOURCE_REQUIREMENT_POPULATION_INCOMPLETE"
    contract["required_security_requirements"].append({"id": "EXTRA.PROTECTION",
        "sources": [{"file": source, "line_start": 4, "line_end": 4, "excerpt": extra}],
        "proof_binding": None, "reason": "No native proof exists."})
    manifest["property_contract"] = _put(tmp_path, str(path.relative_to(tmp_path)), contract)
    manifest_path.write_text(json.dumps(manifest))
    result = S.execute(tmp_path, _context("D17"))
    assert result["component_status"] == "NOT_MEASURED"
    assert result["metrics"]["required_requirement_count"] == 4
    assert result["metrics"]["proved_requirement_count"] == 3
    assert result["metrics"]["unproved_requirement_count"] == 1
    assert result["reason"] == "D17_SOURCE_REQUIRED_SECURITY_PROPERTIES_UNPROVED"
    assert not result.get("completed")

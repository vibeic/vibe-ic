"""Normal L6 production of source-bound AI proposals, not a synthetic signer.

The checked-in incomplete FSM source stays FAIL without author input. CLI facts
exercise typed projection and the real RTL-author handoff; no fixture asserts
that an AI-proposed behavior is functionally correct or independently reviewed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import ai_signed_judgement as judgement
import _phase1_producer_identity as identity
import phase1_doc_one_shot_runner as phase1
import l6_fsm_scaffold_actionable_check as gate


PLUGIN = Path(phase1.__file__).resolve().parent.parent
SOURCE = (PLUGIN / "programs/tests/fixtures/fsm_source_contract/incomplete_detector.md").read_text()
INTERFACE = """
## Interface
| Signal | Direction | Width | Description |
| --- | --- | --- | --- |
| bit_in | input | 1 | Received bit |
| wave | output | 5 | Output word |
"""


def _l6(project):
    return json.loads((project / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_text())


def _produce(project):
    text = (project / "input/docs/control.md").read_text()
    phase1.gen_l6_control_logic(project, {"control.md": text})
    return _l6(project)


def _source(project, extra=""):
    path = project / "input/docs/control.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE + INTERFACE + extra)
    return _produce(project)


def _cli(*args):
    env = dict(os.environ, PYTHONPATH=str(PLUGIN / "tools"))
    cp = subprocess.run([sys.executable, "-m", "phase1_engine.cli", *map(str, args)],
                        cwd=PLUGIN, env=env, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def _proposal(project, original, port="bit_in", value=1):
    names = [s["name"] for s in original["fsm_states"]]
    rows = []
    for name in names:
        rows.extend([
            {"from": name, "to": names[-1],
             "guard": {"port": port, "op": "==", "value": value}},
            {"from": name, "to": names[0], "default": True},
        ])
    raw = project / "author-extracted.json"
    raw.write_text(json.dumps({"L6.fsm_transitions": rows}))
    from phase1_expert_parse_track import input_text_report
    source_snapshot = project / "author-source.txt"
    source_snapshot.write_text(input_text_report(project)["text"])
    path = project / "phase1/behavioral_refinement.facts.yaml"
    # The actual supported CLI creates inferred FactGraph provenance. Source
    # binding hashes the raw input text, never the generated L6 serialization.
    _cli("ingest-extracted", raw, "--class-path", "digital.control",
         "--ic-name", original["ic_name"], "--text-file", source_snapshot, "--out", path)
    _cli("set-fact", path, "--path", "L6.fsm_transitions", "--value",
         json.dumps(rows), "--source", "inferred", "--origin", "ai_behavioral_author",
         "--reasoning", "Propose an ordered restart policy for unspecified branches.")
    data = yaml.safe_load(path.read_text())
    data["metadata"].update(
        status="proposed", assumptions=["Unspecified branches restart the detector."],
        fsm_machine=original["fsm_machines"][0]["machine_id"])
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path, data


def _save(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_no_proposal_preserves_source_document_and_missing_behavior_failure(tmp_path):
    original = _source(tmp_path)
    first = (tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_bytes()
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"
    assert not any(s.get("transitions") for s in original["fsm_states"])
    (tmp_path / "phase1/unrelated.json").write_text('{"fsm_transitions": []}')
    _produce(tmp_path)
    assert (tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_bytes() == first


@pytest.mark.parametrize("port,value,op", [("bit_in", 1, "=="), ("wave", 31, "=="), ("wave", 0, "!=")])
def test_true_cli_proposal_is_projected_by_normal_stamped_producer(tmp_path, port, value, op):
    original = _source(tmp_path)
    path, facts = _proposal(tmp_path, original, port, value)
    if op != "==":
        for row in facts["facts"][0]["value"]:
            if "guard" in row:
                row["guard"]["op"] = op
        _save(path, facts)
    current = _produce(tmp_path)
    assert len(current.get("fsm_transitions", [])) == 6
    assert gate.evaluate(tmp_path)["verdict"] == "PASS"  # structural only
    for before, after in zip(original["fsm_states"], current["fsm_states"]):
        assert {k: v for k, v in after.items() if k != "transitions"} == {
            k: v for k, v in before.items() if k != "transitions"}
        assert after["transitions"][-1]["default"] is True
        assert after["transitions"][0]["guard"] == {"port": port, "op": op, "value": value}
        assert all("source_literal" not in e for e in after["transitions"])
    assert current["extraction_evidence"] == original["extraction_evidence"]
    prov = current["behavioral_refinement"]
    assert prov["status"] == "proposed" and prov["source"] == "inferred"
    assert prov["reasoning"] == facts["facts"][0]["provenance"]["reasoning"]
    assert prov["assumptions"] == facts["metadata"]["assumptions"]
    assert prov["author_input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert prov["behavioral_implementation"] == "NOT_MEASURED"
    assert current["_generator"]["emitter"].startswith("phase1_doc_one_shot_runner")


@pytest.mark.parametrize("defect", [
    "missing_default", "default_not_last", "duplicate", "unknown_port", "unknown_state",
    "foreign_machine", "row_machine", "expression", "negative", "out_of_range", "bool",
    "source_stated", "no_reasoning", "no_assumptions", "not_proposed", "extra_fact",
])
def test_invalid_proposal_refuses_and_keeps_source_only_document(tmp_path, defect):
    original = _source(tmp_path)
    path, data = _proposal(tmp_path, original)
    rows = data["facts"][0]["value"]
    if defect == "missing_default": rows.pop()
    elif defect == "default_not_last": rows[0:2] = reversed(rows[0:2])
    elif defect == "duplicate": rows.insert(0, copy.deepcopy(rows[0]))
    elif defect == "unknown_port": rows[0]["guard"]["port"] = "unmentioned"
    elif defect == "unknown_state": rows[0]["to"] = "UNMENTIONED"
    elif defect == "foreign_machine": data["metadata"]["fsm_machine"] = "foreign"
    elif defect == "row_machine": rows[0]["machine"] = "foreign"
    elif defect == "expression": rows[0]["guard"]["port"] = "bit_in || wave"
    elif defect == "negative": rows[0]["guard"]["value"] = -1
    elif defect == "out_of_range": rows[0]["guard"]["value"] = 2
    elif defect == "bool": rows[0]["guard"]["value"] = True
    elif defect == "source_stated": data["facts"][0]["provenance"]["source"] = "user_stated"
    elif defect == "no_reasoning": data["facts"][0]["provenance"]["reasoning"] = ""
    elif defect == "no_assumptions": data["metadata"]["assumptions"] = []
    elif defect == "not_proposed": data["metadata"]["status"] = "confirmed"
    elif defect == "extra_fact": data["facts"].append(copy.deepcopy(data["facts"][0]))
    _save(path, data)
    with pytest.raises(ValueError, match="BEHAVIORAL_REFINEMENT_REFUSED"):
        _produce(tmp_path)
    assert _l6(tmp_path) == original
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"


def test_explicit_source_edge_refuses_proposal_and_is_preserved(tmp_path):
    _source(tmp_path)
    explicit = PLUGIN / "programs/tests/fixtures/fsm_source_contract/lowercase_controller.md"
    (tmp_path / "input/docs/control.md").write_text(explicit.read_text() + INTERFACE)
    original = _produce(tmp_path)
    assert any(s.get("transitions") for s in original["fsm_states"])
    _proposal(tmp_path, original)
    with pytest.raises(ValueError, match="explicit source transitions"):
        _produce(tmp_path)
    assert _l6(tmp_path) == original


def test_source_edit_refuses_stale_proposal_and_discards_previous_projection(tmp_path):
    original = _source(tmp_path)
    _proposal(tmp_path, original)
    assert _produce(tmp_path)["behavioral_refinement"]["status"] == "proposed"
    source = tmp_path / "input/docs/control.md"
    source.write_text(source.read_text() + "\nThe interface timing remains unspecified.\n")
    with pytest.raises(ValueError, match="source_text_sha256"):
        _produce(tmp_path)
    assert "behavioral_refinement" not in _l6(tmp_path)
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"


def test_author_input_and_source_bind_existing_currentness_and_d1_evidence(tmp_path):
    original = _source(tmp_path)
    path, data = _proposal(tmp_path, original)
    before = identity.input_tree_snapshot(tmp_path)
    with identity.ProducerRecorder() as recorder:
        _produce(tmp_path)
    identity.stamp(tmp_path, recorder, input_before=before)
    current = identity.assess(tmp_path, PLUGIN / "programs")
    assert current["state"] == identity.REUSE, current
    digest = judgement.evidence_sha256(tmp_path, "D1")
    original_bytes = path.read_bytes()
    assert path in judgement.evidence(tmp_path, "D1")
    data["metadata"]["assumptions"].append("Another author assumption.")
    _save(path, data)
    changed = identity.assess(tmp_path, PLUGIN / "programs")
    assert changed["reason"] == identity.DESIGN_INPUT_CHANGED, changed
    assert judgement.evidence_sha256(tmp_path, "D1") != digest
    import vibe_ic_one_shot_runner as frontdoor
    fresh = frontdoor._phase1_freshness(tmp_path)
    note = frontdoor._stale_generated_docs_note(False, fresh, True, "entry past phase 1")
    reasons = []
    assert "STALE_GENERATED_DOCS" in note and identity.DESIGN_INPUT_CHANGED in note
    assert frontdoor._demote_for_stale_generated_docs("PASS", note, reasons) == "NOT_MEASURED"
    assert reasons == [note]
    path.write_bytes(original_bytes)
    assert identity.assess(tmp_path, PLUGIN / "programs")["state"] == identity.REUSE
    source = tmp_path / "input/docs/control.md"
    source.write_text(source.read_text() + "\nAn additional source statement.\n")
    assert identity.assess(tmp_path, PLUGIN / "programs")["reason"] == identity.DESIGN_INPUT_CHANGED
    assert judgement.evidence_sha256(tmp_path, "D1") != digest


def test_first_proposal_addition_invalidates_existing_producer_identity(tmp_path):
    _source(tmp_path)
    before = identity.input_tree_snapshot(tmp_path)
    with identity.ProducerRecorder() as recorder:
        original = _produce(tmp_path)
    identity.stamp(tmp_path, recorder, input_before=before)
    assert identity.assess(tmp_path, PLUGIN / "programs")["state"] == identity.REUSE
    _proposal(tmp_path, original)
    assert identity.assess(tmp_path, PLUGIN / "programs")["reason"] == identity.DESIGN_INPUT_CHANGED


def test_canonical_d1_declares_optional_author_input_without_changing_source_hash(tmp_path):
    import step_input_scope
    import step_required_inputs_check as required
    from phase1_expert_parse_track import input_text_report
    flow = PLUGIN / "flow/phase1_phase2_phase3.yaml"
    steps, error = required.load_flow(flow)
    assert error is None
    assert required.declaration_defects(steps) == []
    d1 = next(s for s in steps if str(s["id"]) == "D1")
    entry = next(e for e in d1["required_inputs"]
                 if e.get("path") == identity.BEHAVIORAL_REFINEMENT_INPUT)
    assert entry["from"] == "external" and entry["check"] == "none"
    specs = step_input_scope.declared_scope("D1", flow)
    assert step_input_scope.in_declared_scope(identity.BEHAVIORAL_REFINEMENT_INPUT, specs)
    original = _source(tmp_path)
    source_text = input_text_report(tmp_path)["text"]
    _proposal(tmp_path, original)
    assert input_text_report(tmp_path)["text"] == source_text


def test_actual_step_rtl_gen_handoff_carries_projection_and_provenance(tmp_path):
    from design_one_shot_runner import step_rtl_gen
    original = _source(tmp_path)
    _proposal(tmp_path, original, "wave", 31)
    current = _produce(tmp_path)
    result = step_rtl_gen(tmp_path, "crypto_accelerator")
    assert result.status == "PASS_WITH_WAIVERS", result
    assert result.extras["fallback_skill"] == "spec-to-rtl"
    delivered = result.extras["behavioral_refinement"]
    assert delivered["provenance"] == current["behavioral_refinement"]
    assert delivered["fsm_transitions"] == current["fsm_transitions"]
    assert Path(delivered["l6_path"]).is_file()
    assert "inferred/proposed" in result.detail and "NOT_MEASURED" in result.detail
    assert not list((tmp_path / "phase2/stage1/rtl").glob("*.v"))


def test_existing_runner_material_and_d1_snapshot_bind_optional_proposal(tmp_path):
    import benchmark_dispatch as dispatch
    original = _source(tmp_path)
    # Snapshot capture needs a prompt/report generation, not a passing report
    # or an AI signature. No launch, runner, scorer or acceptance is invoked.
    (tmp_path / "input/phase1_prompt.md").write_text("A neutral controller.\n")
    report = tmp_path / "reports/orchestrator/phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"verdict":"NOT_MEASURED"}')
    absent_material = dispatch._runner_material_snapshot(tmp_path)
    assert "behavioral_refinement_input" not in absent_material
    absent = dispatch._capture_d1_evidence(tmp_path)
    assert absent.author_inputs == ()
    path, data = _proposal(tmp_path, original)
    with pytest.raises(ValueError, match="D1_SNAPSHOT_AUTHOR_INPUT_SET_CHANGED"):
        dispatch._assert_d1_snapshot_current(absent)
    material = dispatch._runner_material_snapshot(tmp_path)
    assert material["behavioral_refinement_input"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = dispatch._capture_d1_evidence(tmp_path)
    assert snapshot.author_inputs[0][0] == path
    assert snapshot.digest != absent.digest
    data["metadata"]["assumptions"].append("Additional author assumption.")
    _save(path, data)
    assert dispatch._runner_material_snapshot(tmp_path) != material
    with pytest.raises(ValueError, match="D1_SNAPSHOT_GENERATION_CHANGED"):
        dispatch._assert_d1_snapshot_current(snapshot)


def test_symlink_author_input_is_refused_without_replacing_source_facts(tmp_path):
    original = _source(tmp_path)
    path, _ = _proposal(tmp_path, original)
    elsewhere = tmp_path / "proposal-saved.yaml"
    path.rename(elsewhere)
    path.symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        _produce(tmp_path)
    assert _l6(tmp_path) == original


def test_retained_ordinary_d1_producer_uses_bound_factgraph_schema(tmp_path):
    import benchmark_dispatch as dispatch
    source = tmp_path / "input/docs/control.md"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE + INTERFACE)
    (tmp_path / "input/phase1_prompt.md").write_text(SOURCE + INTERFACE)
    command = [sys.executable, str(PLUGIN / "programs/vibe_ic_one_shot_runner.py"),
               str(tmp_path), "--entry-step", "D1", "--exit-step", "D1",
               "--route", "ic", "--skip-analog"]
    budget = dispatch._RunnerBudget(1, 1, 1)
    baseline = budget.run(command)
    assert (tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json").is_file(), baseline
    original = _l6(tmp_path)
    assert not any(s.get("transitions") for s in original["fsm_states"])
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"
    path, _ = _proposal(tmp_path, original, "wave", 31)
    proposed = budget.run(command)
    current = _l6(tmp_path)
    assert len(current.get("fsm_transitions", [])) == 6, proposed
    assert current["_generator"]["emitter"].startswith("phase1_doc_one_shot_runner")
    assert not (tmp_path / "reports/audit/ai_judgements/D1.json").exists()
    receipt = json.loads((tmp_path / "reports/orchestrator/runtime_program_tree.json").read_text())
    retained = Path(receipt["retained_programs_dir"]).parent
    manifest = json.loads((retained.parent / "manifest.json").read_text())
    schema = "tools/phase1_engine/schema.py"
    assert manifest["files"][schema] == hashlib.sha256((PLUGIN / schema).read_bytes()).hexdigest()
    assert (retained / schema).is_file()
    assert current["behavioral_refinement"]["author_input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert proposed.invocation["material_after"]["behavioral_refinement_input"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = (tmp_path / "phase1/step_identity.json").read_text()
    assert "tools/phase1_engine/schema.py" in sidecar
    assert "programs/_phase1_behavioral_refinement.py" in sidecar
    # This records the actual non-passing D1 invocation, not an invented AI
    # verdict. Structural L6 production is independent of remaining D1 gaps.
    assert proposed.rc == 1, proposed
    original_facts = path.read_bytes()
    try:
        path.write_bytes(original_facts + b"\n# A subsequent author edit.\n")
        diagnostic = dispatch._stored_runner_diagnostics(proposed.invocation)
        assert diagnostic["reason_class"] == "RUNNER_MATERIAL_UNBOUND", diagnostic
        (tmp_path / "reports/orchestrator/behavioral_refinement_reverse.json").write_text(
            json.dumps(diagnostic, indent=2))
    finally:
        path.write_bytes(original_facts)

"""Current Default D1 entrance and honest expert-handoff controls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PROGRAMS = Path(__file__).resolve().parents[1]


def _raw_docs_project(project):
    source = PROGRAMS / "tests/fixtures/r0929_dieid_basis_self_tapeout_die/input/step_0_5ic_answers.json"
    answers = json.loads(source.read_text())
    answers["answer_provenance"]["synthesis_area_budget"] = {
        "answered_by": "owner", "citation": "Neutral front-door input for D1 entrance control"}
    answers["operator_template"] = {"path": "input/submission_template_source", "slot": "s1"}
    path = project / "input/step_0_5ic_answers.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(answers, sort_keys=True) + "\n")
    template = project / "input/submission_template_source"
    template.mkdir()
    (template / "s1.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\nCORE_AREA: [26, 26, 974, 1974]\n"
        "SEAL_RING_WIDTH: 26\nFP_SIZING: absolute\npads: [pad_n0, pad_n1, pad_s0]\n")
    docs = project / "input/docs"
    docs.mkdir()
    (docs / "design.md").write_text("# design\n")


def test_canonical_default_frontdoor_produces_d1_and_waits_for_expert(tmp_path):
    project = tmp_path / "subject"
    _raw_docs_project(project)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith("VIBEIC_EXECUTION")}
    command = [sys.executable, "-I", str(PROGRAMS / "vibe_ic_one_shot_runner.py"),
               str(project), "--route", "ic", "--execution-mode", "default",
               "--skip-analog", "--no-dashboard", "--exit-step", "D1"]
    measurement = {"argv": command}
    started = time.monotonic()
    try:
        with (tmp_path / "frontdoor.log").open("w") as log:
            completed = subprocess.run(command, env=environment, stdout=log,
                                       stderr=subprocess.STDOUT, text=True, timeout=240)
        measurement["returncode"] = completed.returncode
    except subprocess.TimeoutExpired:
        measurement["timed_out"] = True
        raise
    finally:
        measurement["elapsed_s"] = time.monotonic() - started
        (tmp_path / "frontdoor-command.json").write_text(
            json.dumps(measurement, indent=2) + "\n")
    phase1 = json.loads((project / "reports/orchestrator/phase1_one_shot.json").read_text())
    docs = sorted((project / "phase1/generated_docs").glob("L*.json"))
    assert len(docs) >= 13, phase1
    assert phase1["step_0_5ic"] == "ran", phase1
    adoption = list((project / "reports/execution").glob("*/0.5ic/adoption.json"))
    assert len(adoption) == 1
    assert json.loads(adoption[0].read_text())["status"] == "ADOPTED"
    assert adoption[0].stat().st_mtime_ns <= min(doc.stat().st_mtime_ns for doc in docs)
    arm = adoption[0].parent / "frontend_0_5ic"
    output = arm / "outputs"
    chain = json.loads((output / "issued-producer-chain.json").read_text())["payload"]
    for name in ("submission_template", "tapeout_declaration"):
        rel = "reports/phase1/" + name + ".json"
        assert hashlib.sha256((output / rel).read_bytes()).hexdigest() == chain["outputs"][rel]
        assert (output / rel).stat().st_ctime_ns == chain["output_ctimes"][rel]
        assert (output / "reports/execution_gates" / (name + "_check.json")).is_file()
    receipt = json.loads((arm / "receipt.json").read_text())
    assert receipt["evidence"]["gates"] == {
        "submission_template_check": "PASS", "tapeout_declaration_check": "PASS"}
    assert all(process["rc"] == 0 for process in receipt["processes"])
    assert (project / "phase1/step_identity.json").is_file()
    expert = json.loads((project / "reports/audit/phase1/expert_parse_track.json").read_text())
    assert expert["ai_subtrack"]["status"] == "HANDOFF_EMITTED", expert
    assert phase1["verdict"] not in ("PASS", "PASS_WITH_WAIVERS"), phase1
    assert completed.returncode != 0
    frontdoor = json.loads((project / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert frontdoor["halted_at"] == "phase1", frontdoor
    assert frontdoor["verdict"] not in ("PASS", "PASS_WITH_WAIVERS")
    assert any("downstream registration and dispatch were not started" in item
               for item in frontdoor["advisories"])
    for report in ("phase2_one_shot.json", "phase3_one_shot.json"):
        assert not (project / "reports/orchestrator" / report).exists()
    assert not (project / "phase2").exists()
    assert not (project / "phase3").exists()
    assert {path.parent.name for path in
            (project / "reports/execution").glob("*/*/plan.json")} == {"0.5ic"}
    disclosure = phase1["canonical_producer"]
    assert disclosure["step_id"] == "D1"
    assert disclosure["controller_qualification"] == "NOT_MEASURED"
    assert disclosure["mode"] == "default"
    assert "NO_REGISTERED_PROVIDER" not in json.dumps(phase1)
    assert not list((project / "reports/execution").glob("*/D1/adoption.json"))


import pytest
from types import SimpleNamespace
import execution_modes as em
import execution_policy as policy
from programs.tests.test_execution_receipt_chain import isolated_transport, real_entry


def _phase1_runtime(project, mode="default"):
    project.mkdir()
    real_entry("IC", mode, project)
    return policy.bootstrap(project, parameters={"skip_analog": True}, phase1_only=True)


def _row(detail, extras):
    return SimpleNamespace(status="NOT_MEASURED", detail=detail, extras=extras)


@pytest.mark.parametrize("damage", ["missing", "invalid", "closed"])
def test_canonical_d1_selection_reconsumes_capability(tmp_path, monkeypatch, damage):
    project = tmp_path / "subject"
    runtime = _phase1_runtime(project)
    fd = os.memfd_create("invalid-d1-capability")
    os.write(fd, b"not an issued capability")
    try:
        if damage == "missing":
            monkeypatch.delenv(policy._CAPABILITY_FD_ENV)
        else:
            monkeypatch.setenv(policy._CAPABILITY_FD_ENV, str(fd))
        if damage == "closed":
            os.close(fd)
        with pytest.raises(em.Refusal, match="REQUEST_CAPABILITY_INVALID"):
            policy.dispatch_ordinary_site(project, "phase1_one_shot_runner", "doc_extract", _row)
        assert "canonical_phase1_producer" not in runtime
    finally:
        if damage != "closed":
            os.close(fd)


def test_default_canonical_d1_scope_does_not_unlock_other_rows(tmp_path, monkeypatch):
    project = tmp_path / "subject"
    runtime = _phase1_runtime(project)
    assert policy.dispatch_fixed_step(project, "unknown")["reason"] == "NO_REGISTERED_PROVIDER"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "slot.yaml").write_text("not an admitted input\n")
    alias = project / "input/template_alias"
    alias.symlink_to(outside, target_is_directory=True)
    for template in (str(outside), "../outside", "input/template_alias"):
        with pytest.raises(em.Refusal, match="ORDINARY_INPUT_PATH_UNSAFE"):
            policy._fixed_inputs(runtime, "0.5ic", parameters={"template": template})
    absent = policy._fixed_inputs(runtime, "0.5ic", parameters={
        "template": "input/absent_template", "no_template_reason": "Owner-declared absence"})
    assert set(absent) == {"input/step_0_5ic_answers.json"}
    result = policy.dispatch_ordinary_site(project, "design_one_shot_runner", "rtl_gen", _row)
    assert result.status == "NOT_MEASURED"
    assert result.extras["execution_results"][0]["reason"] == "NO_REGISTERED_PROVIDER"
    monkeypatch.setitem(runtime, "phase1_only", False)
    result = policy.dispatch_ordinary_site(project, "phase1_one_shot_runner", "doc_extract", _row)
    assert result.status == "NOT_MEASURED"
    assert "canonical_phase1_producer" not in runtime


def test_ultra_d1_keeps_controller_refusal(tmp_path):
    project = tmp_path / "subject"
    runtime = _phase1_runtime(project, "ultra")
    result = policy.dispatch_ordinary_site(project, "phase1_one_shot_runner", "doc_extract", _row)
    assert result.status == "NOT_MEASURED"
    assert result.extras["execution_results"][0]["reason"] == "NO_REGISTERED_PROVIDER"
    assert "canonical_phase1_producer" not in runtime

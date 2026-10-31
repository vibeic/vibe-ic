"""Neutral controls for prompt-only structural rejection and immutable replay.

Native controls require an explicitly selected immutable runtime; missing tools
are NOT_MEASURED, not successful qualification. No dataset or oracle is read.
"""
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import rtl_repair_contract as rc
import librelane_contract as launch
import test_issue3655_structural_repair_contract as existing

PROMPT_SCHEMA = "vibeic.prompt_structural_contract.v1"
COMPLETION_SCHEMA = "vibeic.prompt_structural_completion.v1"
PROMPT = """Implement module neutral_select with this one-bit interface:
 - input a
 - input b
 - input s
 - output y
Output y selects a when s is zero and b when s is one.
The implementation shall use only multiplexers for the selectable data path.
"""


@pytest.fixture
def native(monkeypatch):
    image = os.environ.get("VIBEIC_STRUCTURAL_TEST_IMAGE")
    container = os.environ.get("VIBEIC_STRUCTURAL_TEST_CONTAINER")
    if not image or "@sha256:" not in image or not container:
        pytest.skip("native prompt structure NOT_MEASURED: select immutable image and container")
    cp = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, check=True)
    info = json.loads(cp.stdout)[0]
    pinned = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert pinned == info["Image"]
    monkeypatch.setattr(existing, "IMAGE", image)
    monkeypatch.setattr(existing, "IMAGE_ID", pinned)
    monkeypatch.setattr(existing, "PROMPT", PROMPT)
    # Unit fixture supplies the ordinary original-input selection. Runner gate
    # provenance is unchanged by this patch and is tested by its own suite.
    monkeypatch.setattr(bd, "_task_rtl_input", lambda task: "original")
    return {"backend": "native", "selection": "explicit-neutral-test-runtime",
            "container": container, "container_id": info["Id"],
            "image_id": pinned, "image_digest": image.split("@", 1)[1]}


def task_and_review(tmp_path, native, candidate=existing.WRONG):
    run = tmp_path / "run"
    project = run / "projects" / "neutral"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral_select.sv").write_text(candidate)
    (project / "input").mkdir()
    (project / "input" / "phase1_prompt.md").write_text(PROMPT)
    reports = project / "reports" / "orchestrator"
    reports.mkdir(parents=True)
    (reports / "phase2_one_shot.json").write_text(json.dumps({"steps": [
        {"name": "rtl_gen", "status": "PASS", "detail": "neutral control"}]}))
    bio._stage_public_original("neutral", PROMPT, {}, project)
    got = bio.collect("rtllm", "neutral", project)
    task = bd._make_ai_review_task("neutral", project, got, existing.ROUTING, 0,
        run, "PROGRAM", program_phases={"phase3_verifying": {"ran": {
            "step4_functional_evidence": "NOT_APPLICABLE"}}})
    task["verification_execution"] = native
    declaration = existing._contract(candidate)
    declaration["schema"] = PROMPT_SCHEMA
    declaration["candidate_path"] = declaration.pop("source_path")
    declaration.pop("source_sha256")
    review = existing._write_structural_review(task, candidate, declaration=declaration)
    return task, review


def save_review(task, review):
    Path(task["review_path"]).write_text(json.dumps(review))


def test_prompt_only_admits_real_structural_counterexample_without_program_pass(tmp_path, native):
    task, review = task_and_review(tmp_path, native)
    verdict = bd._validate_ai_review(task)
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "FAIL"
    assert {x["code"] for x in verdict["structural_result"]["findings"]} == {"STRUCTURAL_CONTRACT_VIOLATION"}
    assert verdict["program_review_coverage"]["blocking_gaps"] == 0
    assert verdict["status"] == "REPAIR_REQUIRED", verdict["reasons"]


@pytest.mark.parametrize("case", ["wrong_function", "correct_structure", "unbound_dut", "inherited_failure"])
def test_prompt_only_does_not_admit_unproven_rejection(tmp_path, native, case):
    candidate = existing.WRONG
    if case == "wrong_function":
        candidate = candidate.replace("left | right", "~(left | right)")
    elif case == "correct_structure":
        candidate = existing.RIGHT
    task, review = task_and_review(tmp_path, native, candidate)
    challenge = Path(task["challenge_path"])
    if case == "unbound_dut":
        text = """module vibeic_ai_challenge_tb;
initial begin
 if (1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
 $display("VIBEIC_AI_CHALLENGE=PASS"); $finish;
end
endmodule
"""
        challenge.write_text(text)
        review["verification_test"]["sha256"] = bd._sha256_text(text)
        save_review(task, review)
    elif case == "inherited_failure":
        text = challenge.read_text().replace("(s ? b : a)", "(s ? a : b)")
        inherited = challenge.with_name("inherited.sv")
        inherited.write_text(text)
        task["verification_challenges"] = [{
            "schema": bd._CHALLENGE_SCHEMA, "id": task["id"],
            "path": str(inherited), "sha256": bd._sha256_text(text),
            "top_module": "vibeic_ai_challenge_tb", "prompt_sha256": task["prompt_sha256"]}]
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    if case == "wrong_function":
        assert verdict["challenge_result"]["status"] == "FAIL"
    elif case == "correct_structure":
        assert verdict["structural_result"]["verdict"] == "PASS"
    elif case == "unbound_dut":
        assert verdict["challenge_result"]["status"] == "PASS"
        assert verdict["program_review_coverage"]["blocking_gaps"] > 0
    else:
        assert verdict["challenge_result"]["status"] == "PASS"
        assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"


def test_prompt_structure_repair_replays_same_contract_and_requires_fresh_review(tmp_path, native):
    task, review = task_and_review(tmp_path, native)
    admitted = bd._validate_ai_review(task)
    assert admitted["status"] == "REPAIR_REQUIRED"
    project = Path(task["project"])
    working = project / "phase2/stage1/rtl/neutral_select.sv"
    working.write_text(existing.RIGHT)
    repaired_hash = bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    structural = copy.deepcopy(review["structural_verification"])
    structural["candidate_sha256"] = bd._sha256_text(existing.RIGHT)
    author = {"kind": "AI", "model": "neutral-repair-control"}
    contract = {"schema": COMPLETION_SCHEMA, "prompt_sha256": task["prompt_sha256"],
                "parent_rtl_sha256": task["rtl_sha256"], "candidate_sha256": repaired_hash,
                "challenge_sha256": admitted["verified_challenge"]["sha256"],
                "author": author, "oracle_accessed": False, "structural": structural}
    record = {"schema": bd._AI_REPAIR_RECORD_SCHEMA, "id": task["id"],
              "prompt_sha256": task["prompt_sha256"], "parent_rtl_sha256": task["rtl_sha256"],
              "repaired_rtl_sha256": repaired_hash, "challenge_sha256": contract["challenge_sha256"],
              "author": author, "oracle_accessed": False,
              "rationale": "Use the explicit mux implementation and retain the immutable structural and functional proof contracts.",
              "repair_contract": contract}
    path = bd._repair_record_path(project.parent.parent, task)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    provenance, reasons = bd._validate_repair_record(path, task, repaired_hash, admitted["verified_challenge"])
    assert reasons == [], reasons
    assert bd._requires_repair_contract(task, contract)
    collected = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
                            repair_contract=contract, require_repair_contract=True)
    assert collected["ok"], collected
    proof = collected["repair_contract"]["structural"]
    assert proof["verdict"] == "PASS"
    assert proof["execution"]["script_sha256"] == admitted["structural_result"]["execution"]["script_sha256"]
    fresh = bd._make_ai_review_task("neutral", project, collected, existing.ROUTING, 0,
        project.parent.parent, "AI_REPAIR", verification_challenges=[admitted["verified_challenge"]],
        repair_provenance=provenance, repair_parent_candidate=task["candidate_snapshot"])
    fresh["verification_execution"] = native
    assert bd._validate_ai_review(fresh)["status"] == "PENDING"
    fresh_review = existing._write_structural_review(fresh, existing.RIGHT, declaration=structural)
    fresh_review.pop("structural_verification")
    fresh_review["semantic_review"]["verdict"] = "PASS"
    fresh_review["semantic_review"]["findings"] = []
    save_review(fresh, fresh_review)
    assert bd._validate_ai_review(fresh)["status"] == "ACCEPTED"
    record["repair_contract"]["structural"]["expectations"]["required_cell_types"] = {"$and": 1}
    path.write_text(json.dumps(record))
    _, reasons = bd._validate_repair_record(path, task, repaired_hash, admitted["verified_challenge"])
    assert any("differs from the admitted" in x for x in reasons)
    working.write_text(existing.WRONG)
    bad_contract = copy.deepcopy(contract)
    bad_contract["candidate_sha256"] = bd._sha256_text(existing.WRONG)
    bad_contract["structural"] = copy.deepcopy(review["structural_verification"])
    bad = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
                      repair_contract=bad_contract, require_repair_contract=True)
    assert not bad["ok"]
    assert bad["repair_contract"]["structural"]["verdict"] == "FAIL"


@pytest.mark.parametrize("tamper", ["candidate", "prompt", "unsupported_abstraction", "source_mode"])
def test_prompt_structure_binding_cannot_be_laundered(tmp_path, native, tamper):
    task, review = task_and_review(tmp_path, native)
    declaration = review["structural_verification"]
    if tamper == "candidate":
        declaration["candidate_sha256"] = "0" * 64
    elif tamper == "prompt":
        declaration["requirement_source"]["sha256"] = "0" * 64
    elif tamper == "unsupported_abstraction":
        declaration["abstraction"] = "SOURCE_SYNTAX_ASSIGN_VS_ALWAYS"
    else:
        declaration["source_path"] = declaration["candidate_path"]
    save_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] in {"REJECTED", bd._NOT_MEASURED}
    assert verdict["structural_result"]["verdict"] in {"REFUSED", "NOT_MEASURED"}


@pytest.mark.parametrize("entrypoint,prefix", [(None, []),
    (["/dockerstartup/scripts/ui_startup.sh"], ["--skip"])])
@pytest.mark.parametrize("rc_value", [0, 17])
def test_structural_launcher_normalizes_native_and_legacy_without_masking_exit(tmp_path, monkeypatch, entrypoint, prefix, rc_value):
    monkeypatch.setattr(launch, "_image_entrypoint", lambda *args: entrypoint)
    monkeypatch.setattr(rc, "_docker_image_id", lambda *args: (existing.IMAGE_ID, None))
    monkeypatch.setattr(rc.shutil, "which", lambda name: "/usr/bin/" + name)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        output_mount = next(x for x in argv if x.endswith(":/out:rw"))
        out = Path(output_mount[:-len(":/out:rw")])
        (out / "rtlil.json").write_text(json.dumps({"modules": {"neutral_select": {
            "cells": {"m": {"type": "$mux"}}}}}))
        return subprocess.CompletedProcess(argv, rc_value, "native-control", "failure-control" if rc_value else "")
    monkeypatch.setattr(rc.subprocess, "run", run)
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(existing.RIGHT)
    declaration = existing._contract(existing.RIGHT)
    result = rc.run_structural_contract(candidate, declaration, original_source=existing.WRONG,
        requirement_sources={"input/phase1_prompt.md": existing.PROMPT})
    assert result["verdict"] == ("PASS" if rc_value == 0 else "NOT_MEASURED")
    argv = calls[0]
    at = argv.index(existing.IMAGE)
    assert argv[at+1:at+1+len(prefix)] == prefix
    assert argv[at+1+len(prefix):at+3+len(prefix)] == ["yosys", "-Q"]
    assert argv[argv.index("--user")+1] == f"{os.getuid()}:{os.getgid()}"
    assert "--network=none" in argv and "--memory=4g" in argv
    assert result["execution"]["returncode"] == rc_value


def test_source_bound_mode_keeps_its_prior_program_pass_requirement(tmp_path, native):
    _, task = existing._review_task(tmp_path, existing.WRONG)
    task["verification_execution"] = native
    existing._write_structural_review(task, existing.WRONG)
    admitted = bd._validate_ai_review(task)
    assert admitted["status"] == "REPAIR_REQUIRED"
    assert admitted["challenge_result"]["status"] == "PASS"
    assert admitted["structural_result"]["verdict"] == "FAIL"
    task["program_verification"]["functional_evidence"] = "NOT_APPLICABLE"
    task["program_verification"]["functional_confirmation_required"] = True
    rejected = bd._validate_ai_review(task)
    assert rejected["status"] == "REJECTED"
    assert any("existing Program" in x for x in rejected["reasons"])
    project = existing._project(tmp_path / "source-repair", existing.RIGHT)
    repaired = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
        repair_contract=existing._normal_repair_contract(existing.RIGHT), require_repair_contract=True)
    assert repaired["ok"], repaired
    assert repaired["repair_contract"]["preservation"]["verdict"] == "PASS"
    assert repaired["repair_contract"]["elaboration_matrix"]["verdict"] == "PASS"
    assert repaired["repair_contract"]["structural"]["verdict"] == "PASS"


def test_issued_contract_exposes_prompt_binding_without_claiming_syntax_proof(tmp_path):
    task, _ = task_and_review(tmp_path, {"backend": "host"})
    shape = task["review_requirements"]["required_envelope"]["structural_verification"]
    alternative = shape["_prompt_only_alternative"]
    assert PROMPT_SCHEMA in alternative
    assert "candidate_path" in alternative and "all active inherited challenges must PASS" in alternative
    assert "source-syntax methods are not established" in alternative


def test_program_output_rebinding_preserves_prompt_structure_obligations():
    contract = {"schema": COMPLETION_SCHEMA, "candidate_sha256": "old-bundle",
                "author": {"kind": "AI", "model": "neutral"},
                "structural": {"schema": PROMPT_SCHEMA, "candidate_path": "logic.sv",
                    "candidate_sha256": "old-file", "expectations": {"required_cell_types": {"$mux": 1}}}}
    rebound = bd._program_output_repair_contract(contract, {"source": "neutral"},
        {"output_rtl_sha256": "new-bundle", "output_rtl": {"logic.sv": {"sha256": "new-file"}}})
    assert rebound["candidate_sha256"] == "new-bundle"
    assert rebound["structural"]["candidate_sha256"] == "new-file"
    assert rebound["structural"]["expectations"] == contract["structural"]["expectations"]
    assert contract["structural"]["candidate_sha256"] == "old-file"


def test_normalizer_refuses_an_ambiguous_explicit_image():
    with pytest.raises(launch.Refusal, match="LL_IMAGE_TOKEN_AMBIGUOUS"):
        launch._image_tool_argv(["docker", "run", "declared", "declared"], image="declared")

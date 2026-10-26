"""Native source-bound controls for issue 3655's existing repair consumer."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
from _hostpaths import require_repo
from rtl_repair_contract import sha256_text


PROMPT = "The implementation shall use only multiplexers for the selectable data path.\n"
WRONG = """module neutral_select(input wire a, b, s, output wire y);
wire ns, left, right;
assign ns = ~s;
assign left = ns & a;
assign right = s & b;
assign y = left | right;
endmodule
"""
RIGHT = """module neutral_select(input wire a, b, s, output wire y);
assign y = s ? b : a;
endmodule
"""
IMAGE_ID = "sha256:a6713464903bd9f6c3de15cea8653cb0cf1388a24915632190ad64ce3fc2c3d5"
IMAGE = "ghcr.io/vibeic/vibeic-eda@" + IMAGE_ID
ROUTING = {
    "nature": "spec_generation", "route": "SPEC_TO_RTL",
    "source": "neutral_fixture", "needs_ai_parse": True,
}


def test_checked_in_completion_consumer_forwards_structural_requirement_sources():
    consumer = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "benchmark_io_adapter.py").read_text(errors="replace")
    assert 'contract = {"structural": contract}' in consumer
    assert "requirement_sources=requirement_sources" in consumer


def _native_ready() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("native structural control NOT_MEASURED: docker unavailable")
    probe = subprocess.run(
        [docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True)
    if probe.returncode or probe.stdout.strip() != IMAGE_ID:
        pytest.skip("native structural control NOT_MEASURED: immutable image unavailable")


def _project(tmp_path: Path, candidate: str, original: str = WRONG) -> Path:
    project = tmp_path / "project"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral_select.sv").write_text(candidate)
    original_dir = project / "input" / "public_original" / "files"
    original_dir.mkdir(parents=True)
    (original_dir / "neutral_select.sv").write_text(original)
    (project / "input" / "phase1_prompt.md").write_text(PROMPT)
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps(
        {"steps": [{"name": "rtl_gen", "status": "PASS", "detail": "neutral fixture"}]}))
    return project


def _contract(candidate: str) -> dict:
    quote = PROMPT.strip()
    return {
        "schema": "vibeic.native_structural_contract.v1",
        "source_path": "neutral_select.sv",
        "source_sha256": sha256_text(WRONG),
        "candidate_sha256": sha256_text(candidate),
        "top": "neutral_select",
        "abstraction": "RTLIL_AFTER_PROC_OPT",
        "scope": "top_module_cells",
        "requirement_source": {
            "path": "input/phase1_prompt.md",
            "sha256": sha256_text(PROMPT),
            "quote": quote,
            "quote_sha256": sha256_text(quote),
        },
        "backend": {"kind": "docker", "image": IMAGE, "image_id": IMAGE_ID},
        "expectations": {
            "required_cell_types": {"$mux": 1},
            "forbidden_cell_types": ["$and", "$or", "$not"],
            "allow_other_cell_types": False,
        },
    }


def _normal_repair_contract(candidate: str) -> dict:
    return {
        "schema": "vibeic.source_bounded_completion.v1",
        "preservation": {
            "schema": "vibeic.rtl_preservation_declaration.v1",
            "sources": [{
                "path": "neutral_select.sv",
                "source_sha256": sha256_text(WRONG),
                "candidate_sha256": sha256_text(candidate),
                "authorized_edit_regions": [],
                "preserved_executable_fragments": [{"quote": "module neutral_select"}],
            }],
        },
        "elaboration_matrix": {
            "schema": "vibeic.public_elaboration_matrix.v1",
            "source_path": "neutral_select.sv",
            "source_sha256": sha256_text(WRONG),
            "candidate_sha256": sha256_text(candidate),
            "source_quotes": ["module neutral_select"],
            "top": "neutral_select",
            "supported_macros": [],
            "supported_parameters": [],
            "configurations": [{"name": "default"}],
        },
        "structural": _contract(candidate),
    }


def _functional_run(tmp_path: Path, source: str, name: str) -> tuple[int, str]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.fail("functional control NOT_MEASURED: iverilog/vvp unavailable")
    rtl = tmp_path / f"{name}.sv"
    tb = tmp_path / f"{name}_tb.sv"
    out = tmp_path / f"{name}.vvp"
    rtl.write_text(source)
    tb.write_text("""module tb;
reg a, b, s; wire y; integer i;
neutral_select dut(a,b,s,y);
initial begin
  for (i=0; i<8; i=i+1) begin
    {s,b,a}=i; #1;
    if (y !== (s ? b : a)) $fatal(1, "functional mismatch");
  end
  $display("FUNCTIONAL_PASS"); $finish;
end
endmodule
""")
    compiled = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(out), str(rtl), str(tb)],
        capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    return ran.returncode, ran.stdout + ran.stderr


def _review_task(tmp_path: Path, candidate: str, *, functional="PASS") -> tuple[Path, dict]:
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path / "run", candidate)
    bio._stage_public_original("neutral", PROMPT, {"neutral_select.sv": WRONG}, project)
    got = bio.collect("rtllm", "neutral", project)
    task = bd._make_ai_review_task(
        "neutral", project, got, ROUTING, 0, run, "PROGRAM",
        program_phases={"phase3_verifying": {"ran": {
            "step4_functional_evidence": functional}}})
    return run, task


def _write_structural_review(task: dict, candidate: str, *, declaration=None) -> dict:
    challenge_source = r"""module vibeic_ai_challenge_tb;
reg a, b, s; wire y; integer i;
neutral_select dut(.a(a), .b(b), .s(s), .y(y));
initial begin
  for (i=0; i<8; i=i+1) begin
    {s,b,a}=i; #1;
    if (y !== (s ? b : a)) begin
      $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1);
    end
  end
  $display("VIBEIC_AI_CHALLENGE=PASS"); $finish;
end
endmodule
"""
    challenge_path = Path(task["challenge_path"])
    challenge_path.parent.mkdir(parents=True, exist_ok=True)
    challenge_path.write_text(challenge_source)
    review = {
        "schema": bd._AI_REVIEW_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "source_sha256": task["public_original_input"]["source_sha256"],
        "reviewer": {"kind": "AI", "model": "neutral-structural-reviewer"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {
            "verdict": "FAIL",
            "findings": [{"issue": "declared mux-only structure is absent"}],
            "rationale": (
                "The public prompt requires a mux-only implementation while the "
                "frozen candidate uses a Boolean gate decomposition."),
            "prompt_evidence": [{
                "excerpt": PROMPT.strip(),
                "supports": "The public input uniquely declares the required structure."}],
        },
        "verification_test": {
            "schema": bd._CHALLENGE_SCHEMA,
            "path": str(challenge_path.resolve()),
            "sha256": bd._sha256_text(challenge_source),
            "top_module": "vibeic_ai_challenge_tb",
            "rationale": (
                "Exhaustively drive every scalar input combination to establish "
                "that functionality remains correct and is not the repair basis."),
            "expected_behavior": "Output y selects a when s is zero and b when s is one.",
            "prompt_evidence": [{
                "excerpt": PROMPT.strip(),
                "supports": "The data path is a two-input selection function."}],
        },
        "structural_verification": declaration or _contract(candidate),
    }
    review_path = Path(task["review_path"])
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review))
    return review


def test_actual_consumer_rejects_wrong_structure_and_accepts_replayed_repair(tmp_path):
    _native_ready()
    before_functional = _functional_run(tmp_path, WRONG, "wrong")
    after_functional = _functional_run(tmp_path, RIGHT, "right")
    assert before_functional[0] == after_functional[0] == 0
    assert "FUNCTIONAL_PASS" in before_functional[1]
    assert "FUNCTIONAL_PASS" in after_functional[1]

    wrong = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "wrong", WRONG),
        repair_contract=_contract(WRONG))
    assert wrong["ok"] is False
    assert wrong["repair_contract"]["verdict"] == "FAIL"
    wrong_proof = wrong["repair_contract"]["structural"]
    assert wrong_proof["verdict"] == "FAIL"
    assert wrong_proof["execution"]["image_id"] == IMAGE_ID
    assert wrong_proof["execution"]["limits"] == {
        "cpus": 2, "memory": "4g", "timeout_seconds": 300, "network": "none"}
    assert wrong_proof["observation"]["cell_type_counts"].get("$mux", 0) == 0

    repaired = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "right", RIGHT),
        repair_contract=_contract(RIGHT))
    assert repaired["ok"] is True
    replay = repaired["repair_contract"]["structural"]
    assert replay["verdict"] == "PASS"
    assert replay["execution"]["script_sha256"] == wrong_proof["execution"]["script_sha256"]
    assert replay["observation"]["cell_type_counts"] == {"$mux": 1}

    strict = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "strict", RIGHT),
        supplied_rtl=True, repair_contract=_normal_repair_contract(RIGHT),
        require_repair_contract=True)
    assert strict["ok"] is True
    assert strict["repair_contract"]["preservation"]["verdict"] == "PASS"
    assert strict["repair_contract"]["elaboration_matrix"]["verdict"] == "PASS"
    assert strict["repair_contract"]["structural"]["verdict"] == "PASS"


def test_actual_authorizer_admits_structural_fail_with_functional_pass(tmp_path):
    _native_ready()
    _, task = _review_task(tmp_path, WRONG)
    _write_structural_review(task, WRONG)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "FAIL"
    assert verdict["verified_structural_contract"] == _contract(WRONG)


def test_authorizer_does_not_fail_conforming_structure(tmp_path):
    _native_ready()
    _, task = _review_task(tmp_path, RIGHT)
    _write_structural_review(task, RIGHT)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "PASS"
    assert any("structural finding is not proven" in item
               for item in verdict["reasons"])


def test_authorizer_refuses_ambiguous_scope_as_not_measured(tmp_path):
    _, task = _review_task(tmp_path, WRONG)
    declaration = _contract(WRONG)
    del declaration["scope"]
    _write_structural_review(task, WRONG, declaration=declaration)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["reasons"] == []
    assert verdict["structural_result"]["verdict"] == "NOT_MEASURED"


def test_authorizer_does_not_admit_yosys_elaboration_failure(tmp_path):
    _native_ready()
    _, task = _review_task(tmp_path, WRONG)
    declaration = _contract(WRONG)
    declaration["top"] = "missing_top"
    _write_structural_review(task, WRONG, declaration=declaration)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "NOT_MEASURED"
    assert {item["code"] for item in verdict["structural_result"]["findings"]} == {
        "STRUCTURAL_PROOF_EXECUTION_UNMEASURED"}
    assert any("native structural proof was NOT_MEASURED" in item
               for item in verdict["unmeasurable"])


def test_authorizer_rejects_generic_structural_fail(tmp_path, monkeypatch):
    _, task = _review_task(tmp_path, WRONG)
    _write_structural_review(task, WRONG)

    def generic_fail(*_args, **_kwargs):
        return {"verdict": "FAIL", "findings": [{
            "code": "STRUCTURAL_PROOF_EXECUTION_FAILED",
            "message": "synthetic future generic failure"}]}

    monkeypatch.setattr("rtl_repair_contract.run_structural_contract", generic_fail)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "FAIL"
    assert any("generic structural FAIL is not a measured" in item
               for item in verdict["reasons"])


def test_authorizer_requires_prior_functional_pass(tmp_path):
    _, task = _review_task(tmp_path, WRONG, functional="FAIL")
    _write_structural_review(task, WRONG)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("functional evidence PASS" in item for item in verdict["reasons"])


@pytest.mark.parametrize("tamper", ["source", "candidate", "requirement", "tool"])
def test_authorizer_refuses_structural_identity_drift(tmp_path, tamper):
    _, task = _review_task(tmp_path, WRONG)
    declaration = _contract(WRONG)
    if tamper == "source":
        declaration["source_sha256"] = "0" * 64
    elif tamper == "candidate":
        declaration["candidate_sha256"] = "0" * 64
    elif tamper == "requirement":
        declaration["requirement_source"]["sha256"] = "0" * 64
    else:
        declaration["backend"]["image_id"] = "0" * 64
    _write_structural_review(task, WRONG, declaration=declaration)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["structural_result"]["verdict"] == "REFUSED"
    assert any("native structural proof was refused" in item
               for item in verdict["reasons"])


def test_repair_record_must_rebind_and_replay_admitted_structure(tmp_path):
    _native_ready()
    run, task = _review_task(tmp_path, WRONG)
    _write_structural_review(task, WRONG)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    project = Path(task["project"])
    repaired_path = project / "phase2" / "stage1" / "rtl" / "neutral_select.sv"
    repaired_path.write_text(RIGHT)
    repaired_hash = bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    author = {"kind": "AI", "model": "neutral-structural-repairer"}
    contract = _normal_repair_contract(RIGHT)
    contract.update({
        "prompt_sha256": task["prompt_sha256"],
        "source_sha256": task["public_original_input"]["source_sha256"],
        "parent_rtl_sha256": task["rtl_sha256"],
        "candidate_sha256": repaired_hash,
        "challenge_sha256": verdict["verified_challenge"]["sha256"],
        "author": author,
        "oracle_accessed": False,
    })
    record = {
        "schema": bd._AI_REPAIR_RECORD_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "parent_rtl_sha256": task["rtl_sha256"],
        "repaired_rtl_sha256": repaired_hash,
        "challenge_sha256": verdict["verified_challenge"]["sha256"],
        "author": author,
        "oracle_accessed": False,
        "rationale": (
            "Replace the Boolean decomposition with the public mux-only form "
            "and replay both functional and native structural proofs."),
        "repair_contract": contract,
    }
    record_path = bd._repair_record_path(run, task)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record))
    validated, reasons = bd._validate_repair_record(
        record_path, task, repaired_hash, verdict["verified_challenge"])
    assert reasons == []
    assert validated is not None
    del record["repair_contract"]["structural"]
    record_path.write_text(json.dumps(record))
    _, missing_reasons = bd._validate_repair_record(
        record_path, task, repaired_hash, verdict["verified_challenge"])
    assert any("structural proof is missing" in item for item in missing_reasons)


def test_unconstrained_equivalent_architecture_does_not_fail(tmp_path):
    project = _project(tmp_path, WRONG)
    result = bio.collect("rtllm", "neutral", project)
    assert result["ok"] is True
    assert "repair_contract" not in result


def test_ambiguous_structural_scope_is_not_measured_and_refused(tmp_path):
    contract = _contract(WRONG)
    del contract["scope"]
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, WRONG), repair_contract=contract)
    assert result["ok"] is False
    assert result["repair_contract"]["structural"]["verdict"] == "NOT_MEASURED"
    assert {f["code"] for f in result["repair_contract"]["findings"]} == {
        "STRUCTURAL_SCOPE_AMBIGUOUS"}


@pytest.mark.parametrize("tamper", ["source", "candidate", "requirement", "tool"])
def test_structural_identity_drift_is_refused_before_acceptance(tmp_path, tamper):
    contract = _contract(RIGHT)
    if tamper == "source":
        contract["source_sha256"] = "0" * 64
    elif tamper == "candidate":
        contract["candidate_sha256"] = "0" * 64
    elif tamper == "requirement":
        contract["requirement_source"]["sha256"] = "0" * 64
    else:
        contract["backend"]["image_id"] = "0" * 64
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, RIGHT), repair_contract=contract)
    assert result["ok"] is False
    assert result["repair_contract"]["structural"]["verdict"] == "REFUSED"


def test_structural_author_cannot_inject_a_synthesis_remap(tmp_path):
    contract = _contract(RIGHT)
    contract["script"] = "synth; abc"
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, RIGHT), repair_contract=contract)
    assert result["ok"] is False
    finding = result["repair_contract"]["structural"]["findings"][0]
    assert finding["code"] == "STRUCTURAL_COMMAND_INJECTION_REFUSED"

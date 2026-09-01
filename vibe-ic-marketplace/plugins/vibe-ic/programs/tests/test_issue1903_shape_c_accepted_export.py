"""Fail-closed controls for the Program First Shape-C sole emit."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import benchmark_dispatch as dispatch
import shape_b_sample_export as guarded_export
from _hostpaths import require_repo
from test_issue1903_shape_c_accepted_export_control import _fixture


def _task(run):
    return json.loads((run / "needs_ai_review.jsonl").read_text())


def _replace_candidate(run: Path, task: dict, rtl_text: str) -> dict:
    candidate = task["candidate_snapshot"]
    rtl_path = Path(candidate["rtl_paths"][0])
    rtl_path.write_text(rtl_text)
    digest = hashlib.sha256(rtl_text.encode()).hexdigest()
    candidate["rtl_sha256"] = digest
    Path(candidate["completion_path"]).write_text(rtl_text)
    payload_path = Path(candidate["response_payload_path"])
    payload = json.loads(payload_path.read_text())
    payload["completion"] = rtl_text
    payload_path.write_text(json.dumps(payload) + "\n")
    Path(candidate["manifest_path"]).write_text(json.dumps(candidate) + "\n")
    task["rtl_sha256"] = digest
    task["program_candidate_snapshot"] = candidate
    review_path = Path(task["review_path"])
    review = json.loads(review_path.read_text())
    review["rtl_sha256"] = digest
    review_path.write_text(json.dumps(review) + "\n")
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    return task


def test_stale_reviewed_hash_blocks_without_sample(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["rtl_sha256"] = "0" * 64
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "BLOCKED" in str(exc)
        assert "reviewed hash" in str(exc) or "ACCEPTED" in str(exc)
    else:
        raise AssertionError("stale hash did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_wrong_scorer_top_blocks_without_sample(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    _replace_candidate(
        run, task,
        "module DifferentTop(input logic a, output logic y); "
        "assign y = a; endmodule\n",
    )
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "scorer-facing top module 'TopModule' is absent" in str(exc)
    else:
        raise AssertionError("wrong top did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_compile_failure_blocks_the_claimed_blocking_emit(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    _replace_candidate(
        run, task,
        "module TopModule(input logic a, output logic y) assign y = a; endmodule\n",
    )
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "BLOCKED" in str(exc)
        assert "standalone iverilog -g2012 compile FAILED" in str(exc)
    else:
        raise AssertionError("a non-compiling sample reached the scorer")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_missing_phase1_provenance_blocks_loudly(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    for path in (run / "projects" / "Prob900_neutral" / "phase1" /
                 "generated_docs").glob("L*.json"):
        path.unlink()
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "Phase-1 L-doc provenance is absent" in str(exc)
    else:
        raise AssertionError("missing Phase-1 provenance did not block")


def test_runner_evidence_mismatch_blocks_without_sample(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["program_verification"]["runner_rc"] = 1
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "runner rc differs from solve_report" in str(exc)
    else:
        raise AssertionError("runner evidence mismatch did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_nonzero_broader_runner_rc_is_disclosed_but_does_not_block_rtl_sample(
        tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["program_verification"]["runner_rc"] = 1
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0]["rc"] = 1
    (run / "solve_report.json").write_text(json.dumps(solve) + "\n")
    dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    assert (run / "samples" / "Prob900_neutral_sample01.sv").is_file()
    recorded = json.loads((run / "solve_report.json").read_text())
    assert recorded["results"][0]["rc"] == 1
    assert recorded["results"][0]["phases"]["phase3_verifying"]["ran"][
        "rtl_gen"] == "PASS"
    assert recorded["results"][0].get("export_guard_notes") == []


def test_shape_c_applicable_guard_skip_is_recorded_in_solve_report(
        tmp_path, monkeypatch):
    run, dataset, _ = _fixture(tmp_path)
    note = "NOTE: worked-example oracle SKIP (applicable, non-blocking)"

    monkeypatch.setattr(
        "shape_b_sample_export.guard_export",
        lambda *args, **kwargs: (True, [note]),
    )
    dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)

    recorded = json.loads((run / "solve_report.json").read_text())
    assert recorded["results"][0].get("export_guard_notes") == [note]


def test_nonzero_broader_runner_rc_with_failed_rtl_gate_still_blocks(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["program_verification"]["runner_rc"] = 1
    task["program_verification"]["rtl_gen"] = "FAIL"
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0]["rc"] = 1
    solve["results"][0]["phases"]["phase3_verifying"]["ran"][
        "rtl_gen"] = "FAIL"
    (run / "solve_report.json").write_text(json.dumps(solve) + "\n")
    with pytest.raises(SystemExit, match="RTL-owning Program gate did not pass"):
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


@pytest.mark.parametrize("encoded_zero", ["0", 0.0, False])
def test_non_integer_runner_rc_blocks_without_sample(tmp_path, encoded_zero):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["program_verification"]["runner_rc"] = encoded_zero
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0]["rc"] = encoded_zero
    (run / "solve_report.json").write_text(json.dumps(solve) + "\n")
    with pytest.raises(SystemExit, match="runner rc is absent"):
        dispatch._export_accepted_shape_c_samples(
            "verilogeval-v2", run)
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


@pytest.mark.parametrize("malformed", ["not-an-object", [], 7])
def test_malformed_program_verification_blocks_without_sample(
        tmp_path, malformed):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["program_verification"] = malformed
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    with pytest.raises(SystemExit, match="verification record is malformed"):
        dispatch._export_accepted_shape_c_samples(
            "verilogeval-v2", run)
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_malformed_candidate_snapshot_blocks_without_sample(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    task["candidate_snapshot"] = "not-an-object"
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    with pytest.raises(SystemExit, match="candidate snapshot record is malformed"):
        dispatch._export_accepted_shape_c_samples(
            "verilogeval-v2", run)
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


@pytest.mark.parametrize(
    "location",
    ["root", "results", "result_row", "phases", "phase3", "ran"],
)
def test_malformed_solve_report_containers_block_without_sample(
        tmp_path, location):
    run, dataset, _ = _fixture(tmp_path)
    solve = json.loads((run / "solve_report.json").read_text())
    if location == "root":
        solve = []
    elif location == "results":
        solve["results"] = "not-a-list"
    elif location == "result_row":
        solve["results"] = ["not-an-object"]
    elif location == "phases":
        solve["results"][0]["phases"] = "not-an-object"
    elif location == "phase3":
        solve["results"][0]["phases"]["phase3_verifying"] = []
    else:
        solve["results"][0]["phases"]["phase3_verifying"]["ran"] = "bad"
    (run / "solve_report.json").write_text(json.dumps(solve) + "\n")
    with pytest.raises(SystemExit, match="BLOCKED"):
        dispatch._export_accepted_shape_c_samples(
            "verilogeval-v2", run)
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_foreign_phase1_project_substitution_blocks(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    task = _task(run)
    foreign = tmp_path / "foreign-project"
    docs = foreign / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_foreign.json").write_text(json.dumps({"foreign": True}) + "\n")
    task["project"] = str(foreign.resolve())
    task["phase1_provenance"] = __import__(
        "emit_attestation").phase1_provenance(foreign)
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "runner-owned project" in str(exc)
    else:
        raise AssertionError("foreign Phase-1 project did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_later_task_failure_leaves_no_earlier_sample(tmp_path, monkeypatch):
    run, dataset, _ = _fixture(tmp_path)
    first = _task(run)
    second = copy.deepcopy(first)
    second["id"] = "Prob901_neutral"
    (run / "needs_ai_review.jsonl").write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n")
    solve = json.loads((run / "solve_report.json").read_text())
    second_result = copy.deepcopy(solve["results"][0])
    second_result["id"] = second["id"]
    solve["results"].append(second_result)
    (run / "solve_report.json").write_text(json.dumps(solve) + "\n")

    def fake_export(task, samples, top_module, **kwargs):
        if task["id"] == first["id"]:
            samples.mkdir(parents=True, exist_ok=True)
            emitted = samples / f"{task['id']}_sample01.sv"
            emitted.write_text("module TopModule; endmodule\n")
            return {"verdict": "PASS", "exported": str(emitted)}
        return {"verdict": "BLOCKED", "reasons": ["injected later failure"]}

    monkeypatch.setattr(dispatch, "_export_accepted_shape_c_task", fake_export)
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "injected later failure" in str(exc)
    else:
        raise AssertionError("later task failure did not block")
    samples = run / "samples"
    assert not samples.is_dir() or not list(samples.glob("*.sv"))


def test_empty_shape_c_worklist_blocks(tmp_path):
    run, dataset, _ = _fixture(tmp_path)
    (run / "needs_ai_review.jsonl").write_text("")
    (run / "solve_report.json").write_text(json.dumps({"results": []}) + "\n")
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "review worklist is empty" in str(exc)
    else:
        raise AssertionError("empty Shape-C worklist did not block")


def test_attestation_write_failure_blocks_and_removes_sample(tmp_path,
                                                             monkeypatch):
    run, dataset, _ = _fixture(tmp_path)

    def fail_record(*args, **kwargs):
        raise OSError("simulated attestation write failure")

    monkeypatch.setattr("emit_attestation.record", fail_record)
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "Shape-C emit attestation failed" in str(exc)
    else:
        raise AssertionError("attestation failure did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_attestation_readback_failure_blocks_and_removes_sample(tmp_path,
                                                                monkeypatch):
    run, dataset, _ = _fixture(tmp_path)

    def fail_load(path):
        raise OSError("simulated attestation readback failure")

    monkeypatch.setattr("emit_attestation._load", fail_load)
    try:
        dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    except SystemExit as exc:
        assert "Shape-C emit attestation failed" in str(exc)
    else:
        raise AssertionError("attestation readback failure did not block")
    assert not (run / "samples" / "Prob900_neutral_sample01.sv").exists()


def test_shape_b_route_is_preserved(tmp_path, monkeypatch):
    called = []

    def fake_export(*args, **kwargs):
        called.append((args, kwargs))
        return {"verdict": "PASS", "guard_notes": [
            "NOTE: worked-example oracle SKIP (applicable, non-blocking)"]}

    monkeypatch.setattr("shape_b_sample_export.export", fake_export)
    run = tmp_path / "run"
    dataset = tmp_path / "dataset"
    project = run / "project"
    frozen = run / "frozen" / "rtl"
    prompt = project / "input" / "phase1_prompt.md"
    design = dataset / "neutral_core"
    for path in (design, frozen, prompt.parent):
        path.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Module name: neutral_core\n")
    (design / "design_description.txt").write_text(
        "Module name: neutral_core\n")
    (frozen / "00_neutral_core.v").write_text(
        "module neutral_core(input a, output y); assign y=a; endmodule\n")
    task = {"id": "neutral_core", "project": str(project),
            "prompt_path": str(prompt),
            "candidate_snapshot": {"rtl_paths": [str(frozen / "00_neutral_core.v")]}}
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    dispatch._export_accepted_shape_b_samples("rtllm", dataset, run)
    assert len(called) == 1

    (run / "solve_report.json").write_text(json.dumps({
        "results": [{"id": "neutral_core"}],
    }) + "\n")
    dispatch._export_accepted_shape_b_samples("rtllm", dataset, run)
    assert len(called) == 2
    solve = json.loads((run / "solve_report.json").read_text())
    assert solve["results"][0].get("export_guard_notes") == [
        "NOTE: worked-example oracle SKIP (applicable, non-blocking)"]


def test_checked_in_shape_c_sample_remains_guard_compatible(tmp_path):
    source = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "benchmark",
        "canonical_samples", "verilogeval-v2", "Prob062_bugs_mux2.sv",
    )
    sample = tmp_path / "sample.sv"
    shutil.copy2(source, sample)
    ok, problems = guarded_export.guard_export(sample)
    assert ok, problems
    assert "TopModule" in guarded_export._module_names(sample.read_text())

"""Substantive pre-fix control for issue #1903.

The test calls the pre-existing export integration point.  On the parent it
executes successfully but observes no Shape-C sample; after the fix it observes
the exact reviewed sample and its attestation.  This is a value assertion, not
an import/absence-only control.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import benchmark_dispatch as dispatch
import emit_attestation


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fixture(root: Path) -> tuple[Path, Path, str]:
    run = root / "run"
    dataset = root / "dataset"
    project = run / "projects" / "Prob900_neutral"
    snapshot = run / "candidate_snapshots" / "Prob900_neutral" / "program-x"
    rtl_dir = snapshot / "rtl"
    prompt = project / "input" / "phase1_prompt.md"
    docs = project / "phase1" / "generated_docs"
    review = run / "ai_reviews" / "Prob900_neutral" / "review.json"
    response = run / "responses" / "Prob900_neutral.json"
    challenge = run / "ai_verification_challenges" / "Prob900_neutral" / "challenge_tb.sv"
    for directory in (dataset, rtl_dir, prompt.parent, docs, review.parent,
                      response.parent, challenge.parent):
        directory.mkdir(parents=True, exist_ok=True)
    prompt_text = (
        "Implement a module named TopModule with input logic a and output "
        "logic y. Assign y to a.\n"
    )
    rtl_text = "module TopModule(input logic a, output logic y); assign y = a; endmodule\n"
    prompt.write_text(prompt_text)
    (dataset / "Prob900_neutral_prompt.txt").write_text(prompt_text)
    (docs / "L9_microarchitecture.json").write_text(
        json.dumps({"top_module": "TopModule"}) + "\n")
    rtl_path = rtl_dir / "00_TopModule.sv"
    rtl_path.write_text(rtl_text)
    completion = snapshot / "completion.txt"
    payload = snapshot / "response_payload.json"
    manifest = snapshot / "manifest.json"
    completion.write_text(rtl_text)
    payload.write_text(json.dumps({"id": "Prob900_neutral", "ok": True,
                                   "completion": rtl_text}) + "\n")
    rtl_hash = _sha(rtl_text)
    candidate = {
        "schema": "vibeic.benchmark.candidate_snapshot.v1",
        "id": "Prob900_neutral",
        "candidate_origin": "PROGRAM",
        "rtl_sha256": rtl_hash,
        "rtl_paths": [str(rtl_path.resolve())],
        "completion_path": str(completion.resolve()),
        "response_payload_path": str(payload.resolve()),
        "source_rtl_paths": [str((project / "phase2" / "stage1" / "rtl" /
                                  "TopModule.sv").resolve())],
        "manifest_path": str(manifest.resolve()),
    }
    manifest.write_text(json.dumps(candidate, indent=2) + "\n")
    task = {
        "schema": "vibeic.benchmark.ai_review_task.v2",
        "id": "Prob900_neutral",
        "project": str(project.resolve()),
        "candidate_origin": "PROGRAM",
        "candidate_snapshot": candidate,
        "program_candidate_snapshot": candidate,
        "verification_challenges": [],
        "repair_provenance": None,
        "prompt_path": str(prompt.resolve()),
        "rtl_paths": [str(rtl_path.resolve())],
        "working_rtl_paths": candidate["source_rtl_paths"],
        "prompt_sha256": _sha(prompt_text),
        "phase1_provenance": emit_attestation.phase1_provenance(project),
        "rtl_sha256": rtl_hash,
        "program_routing": {"nature": "spec_generation",
                            "route": "phase1_entry", "source": "program",
                            "needs_ai_parse": True},
        # ``_ai_review_task`` emits these two keys unconditionally (they are
        # not optional in the producer), so a task without them models a
        # handoff the runner cannot actually write.  PROGRAM functional
        # evidence PASS is the ``confirmation_required=False`` branch; the
        # required-confirmation branch is covered in
        # ``test_benchmark_program_first_ai_review.py``.
        "program_verification": {
            "actor": "vibe_ic_one_shot_runner",
            "rtl_gen": "PASS",
            "runner_rc": 0,
            "functional_evidence": "PASS",
            "functional_evidence_source":
                "phase3_verifying.ran.step4_functional_evidence",
            "functional_confirmation_required": False,
        },
        "review_path": str(review.resolve()),
        "challenge_path": str(challenge.resolve()),
        "response_path": str(response.resolve()),
    }
    review.write_text(json.dumps({
        "schema": "vibeic.benchmark.ai_review.v2",
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "reviewer": {"kind": "AI", "model": "fixture-reviewer"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {"verdict": "PASS", "findings": [],
                            "rationale": "The output continuously mirrors the input exactly as the prompt requires."},
    }) + "\n")
    (run / "needs_ai_review.jsonl").write_text(json.dumps(task) + "\n")
    (run / "solve_report.json").write_text(json.dumps({
        "results": [{
            "id": task["id"],
            "rc": 0,
            "ok": True,
            "candidate_ready": True,
            "accepted": True,
            "candidate_origin": "PROGRAM",
            "review_task": task["review_path"],
            "phases": {"phase3_verifying": {"ran": {
                "rtl_gen": "PASS",
                "step4_functional_evidence": "PASS"}}},
        }],
    }) + "\n")
    return run, dataset, rtl_text


def test_existing_export_front_door_emits_shape_c_reviewed_value(tmp_path):
    run, dataset, rtl_text = _fixture(tmp_path)
    dispatch._export_accepted_shape_c_samples("verilogeval-v2", run)
    sample = run / "samples" / "Prob900_neutral_sample01.sv"
    observed = sample.read_text() if sample.is_file() else "<NO_SAMPLE>"
    assert observed == rtl_text
    attestation = [json.loads(line) for line in
                   (run / "samples" / ".emit_attestation.jsonl").read_text().splitlines()]
    assert attestation[-1]["sample"] == sample.name
    assert attestation[-1]["shape"] == "C"
    assert attestation[-1]["phase1"]["ran"] is True

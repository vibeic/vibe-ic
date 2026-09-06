"""Same-candidate correction is a new proof round, never a PASS shortcut."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

import test_benchmark_program_first_ai_review as fixtures
from _hostpaths import require_repo

bd = fixtures.bd


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _request(run, task):
    request = {
        "schema": "vibeic.benchmark.ai_review_correction.v1",
        "id": task["id"],
        "task_sha256": bd._sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True)),
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "review_sha256": _digest(task["review_path"]),
        "challenge_sha256": _digest(task["challenge_path"]),
        "author": {"kind": "AI", "model": "independent-test-reviewer"},
        "blind": {"oracle_accessed": False},
        "rationale": (
            "The current test asserts the opposite of the direct assignment "
            "stated in the public prompt. Preserve its exact bytes and request "
            "a fresh independent proof round; this statement grants no acceptance."),
        "prompt_evidence": [{"excerpt": "assign y = a",
                             "supports": "The public requirement is direct equality, not inversion."}],
    }
    path = run / "correction_request.json"
    path.write_text(json.dumps(request))
    return path, request


def _case(tmp_path):
    run, task, _ = fixtures._task(tmp_path)
    review = fixtures._valid_review(task)
    test_path = Path(task["challenge_path"])
    source = test_path.read_text().replace("if (y !== 1'b0)", "if (y !== 1'b1)")
    test_path.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    review["semantic_review"].update({
        "verdict": "FAIL", "findings": ["The reviewer incorrectly expects inversion."],
        "prompt_evidence": review["verification_test"]["prompt_evidence"],
    })
    fixtures._write_review(task, review)
    fixtures._solve_report(run, task)
    request_path, request = _request(run, task)
    return run, task, request_path, request


def _resume(run, request_path):
    # Meaningful pre-fix control: run the real OLD entry when it has no
    # correction operation and observe its retained REPAIR_REQUIRED verdict.
    # No missing-function/import failure is credited as behavioral evidence.
    kwargs = ({"review_correction": str(request_path)}
              if "review_correction" in inspect.signature(bd.cmd_resume).parameters
              else {})
    return bd.cmd_resume("rtllm", "/unused", str(run), **kwargs)


def _protected(task):
    return {str(path): _digest(path) for path in [task["prompt_path"],
            task["review_path"], task["challenge_path"],
            *task["rtl_paths"], *task["working_rtl_paths"]]}


@fixtures._NEEDS_SIMULATOR
def test_real_resume_advances_same_candidate_without_repair_or_acceptance(tmp_path):
    run, old, request_path, _ = _case(tmp_path)
    before = _protected(old)
    assert bd._validate_ai_review(old)["status"] == "REPAIR_REQUIRED"
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    outcome = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["review_outcomes"][0]
    assert outcome["status"] == "PENDING", outcome
    assert new["candidate_snapshot"] == old["candidate_snapshot"]
    assert new["rtl_sha256"] == old["rtl_sha256"]
    assert new["prompt_sha256"] == old["prompt_sha256"]
    assert new["program_review_obligations"] == old["program_review_obligations"]
    assert new["review_path"] != old["review_path"]
    assert new["challenge_path"] != old["challenge_path"]
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert new["verification_challenges"][-1]["sha256"] == _digest(old["challenge_path"])
    assert _protected(old) == before
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    assert not Path(old["response_path"]).exists()
    archive = Path(new["review_correction"]["archive_path"])
    assert (archive / "prior_review.json").read_bytes() == Path(old["review_path"]).read_bytes()
    assert (archive / "prior_challenge_tb.sv").read_bytes() == Path(old["challenge_path"]).read_bytes()


@fixtures._NEEDS_SIMULATOR
@pytest.mark.parametrize("supersede, expected", [(False, "REJECTED"), (True, "ACCEPTED")])
def test_corrected_round_uses_normal_inherited_supersession(tmp_path, supersede, expected):
    run, old, request_path, request = _case(tmp_path)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    # On old code the occupied current path is itself an observed limitation;
    # never overwrite it even in the negative-control run.
    assert Path(new["challenge_path"]).exists() is False
    review = fixtures._valid_review(new)
    if supersede:
        review["challenge_supersessions"] = [{
            "schema": bd._CHALLENGE_SUPERSESSION_SCHEMA,
            "challenge_sha256": request["challenge_sha256"],
            "rationale": request["rationale"],
            "prompt_evidence": request["prompt_evidence"],
        }]
    fixtures._write_review(new, review)
    verdict = bd._validate_ai_review(new)
    assert verdict["status"] == expected, verdict
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == (0 if supersede else 2)
    assert _digest(old["challenge_path"]) == request["challenge_sha256"]
    if supersede:
        assert verdict["inherited_challenge_results"][0]["status"] == "SUPERSEDED"
    else:
        assert not Path(old["response_path"]).exists()


@fixtures._NEEDS_SIMULATOR
def test_correction_replay_is_idempotent_and_preserves_fresh_authored_test(tmp_path):
    run, _, request_path, _ = _case(tmp_path)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert Path(new["challenge_path"]).exists() is False
    fixtures._write_direct_assignment_challenge(new)
    before = _digest(new["challenge_path"])
    assert _resume(run, request_path) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == new
    assert _digest(new["challenge_path"]) == before


@fixtures._NEEDS_SIMULATOR
def test_corrected_test_fail_cannot_accept_or_retire_original(tmp_path):
    run, _, request_path, request = _case(tmp_path)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert not Path(new["challenge_path"]).exists()
    review = fixtures._valid_review(new)
    path = Path(new["challenge_path"])
    source = path.read_text().replace("if (y !== 1'b1)", "if (y !== 1'b0)")
    path.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    review["challenge_supersessions"] = [{
        "schema": bd._CHALLENGE_SUPERSESSION_SCHEMA,
        "challenge_sha256": request["challenge_sha256"],
        "rationale": request["rationale"], "prompt_evidence": request["prompt_evidence"],
    }]
    fixtures._write_review(new, review)
    verdict = bd._validate_ai_review(new)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert not Path(new["response_path"]).exists()


@fixtures._NEEDS_SIMULATOR
def test_supersession_after_correction_still_requires_complete_coverage(tmp_path):
    run, old = fixtures._truth_table_task(tmp_path)
    review = fixtures._valid_review(old)
    review["verification_test"] = fixtures._write_one_row_challenge(old)
    path = Path(old["challenge_path"])
    source = path.read_text().replace("value !== 8'h11", "value !== 8'hAA")
    path.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    fixtures._write_review(old, review)
    fixtures._solve_report(run, old)
    request_path, request = _request(run, old)
    request["prompt_evidence"] = review["verification_test"]["prompt_evidence"]
    request_path.write_text(json.dumps(request))
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert not Path(new["challenge_path"]).exists()
    review = fixtures._valid_review(new)
    review["verification_test"] = fixtures._write_one_row_challenge(new)
    review["challenge_supersessions"] = [{
        "schema": bd._CHALLENGE_SUPERSESSION_SCHEMA,
        "challenge_sha256": request["challenge_sha256"],
        "rationale": request["rationale"], "prompt_evidence": request["prompt_evidence"],
    }]
    fixtures._write_review(new, review)
    verdict = bd._validate_ai_review(new)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["inherited_challenge_results"][0]["status"] == "SUPERSEDED"
    assert verdict["program_review_coverage"]["status"] == "FAIL"
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert not Path(new["response_path"]).exists()


@pytest.mark.parametrize("field, value", [
    ("schema", "wrong"), ("task_sha256", "0" * 64),
    ("prompt_sha256", "0" * 64), ("rtl_sha256", "0" * 64),
    ("review_sha256", "0" * 64), ("challenge_sha256", "0" * 64),
    ("author", {"kind": "Program", "model": "test"}),
    ("author", {"kind": "AI", "model": "unknown"}),
    ("blind", {"oracle_accessed": True}), ("rationale", "short"),
    ("prompt_evidence", [{"excerpt": "invented requirement", "supports": "unfounded statement"}]),
])
def test_malformed_or_stale_request_blocks_before_resume(tmp_path, monkeypatch, capsys, field, value):
    run, task, path, request = _case(tmp_path)
    request[field] = value
    path.write_text(json.dumps(request))
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: pytest.fail("refused request reached resume"))
    assert _resume(run, path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


@pytest.mark.parametrize("kind", ["prompt", "rtl", "review", "challenge", "working", "accepted", "published"])
def test_source_drift_or_published_candidate_blocks(tmp_path, monkeypatch, capsys, kind):
    run, task, path, _ = _case(tmp_path)
    files = {"prompt": task["prompt_path"], "rtl": task["rtl_paths"][0],
             "review": task["review_path"], "challenge": task["challenge_path"],
             "working": task["working_rtl_paths"][0]}
    if kind in files:
        target = Path(files[kind])
        target.write_text(target.read_text() + "\n ")
    elif kind == "published":
        Path(task["response_path"]).write_text("{}")
    else:
        report = run / "solve_report.json"
        data = json.loads(report.read_text())
        data["results"][0]["accepted"] = True
        report.write_text(json.dumps(data))
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: pytest.fail("drift reached resume"))
    assert _resume(run, path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


@pytest.mark.parametrize("field", ["review_path", "challenge_path", "prompt_path"])
def test_symlink_evidence_is_refused_without_touching_target(tmp_path, monkeypatch, field):
    run, task, request, _ = _case(tmp_path)
    path = Path(task[field])
    saved = path.with_suffix(".original")
    path.rename(saved)
    path.symlink_to(saved)
    before = _digest(saved)
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: pytest.fail("symlink reached resume"))
    assert _resume(run, request) == 2
    assert _digest(saved) == before


def test_concurrent_coordinator_refuses_correction(tmp_path, capsys):
    run, task, request, _ = _case(tmp_path)
    before = _protected(task)
    with bd._run_root_coordinator_lock(run, "test-held"):
        assert _resume(run, request) == 2
    assert "another benchmark_dispatch coordinator owns" in capsys.readouterr().err
    assert _protected(task) == before


@pytest.mark.parametrize("target", ["request", "lock", "archive_parent"])
def test_symlink_request_lock_or_archive_parent_is_refused(tmp_path, monkeypatch, target):
    run, task, request, _ = _case(tmp_path)
    if target == "request":
        original = request.with_suffix(".original")
        request.rename(original)
        request.symlink_to(original)
    elif target == "lock":
        original = run / "untouched_lock_target"
        original.write_text("must not truncate")
        (run / bd._COORDINATOR_LOCK).symlink_to(original)
    else:
        original = tmp_path / "archive_target"
        original.mkdir()
        (run / "review_corrections").symlink_to(original, target_is_directory=True)
    before = _protected(task)
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: pytest.fail("symlink reached resume"))
    assert _resume(run, request) == 2
    assert _protected(task) == before
    if target == "lock":
        assert original.read_text() == "must not truncate"


@fixtures._NEEDS_SIMULATOR
@pytest.mark.parametrize("kind", ["missing", "tampered"])
def test_replay_refuses_missing_or_modified_archive(tmp_path, capsys, kind):
    run, old, request, _ = _case(tmp_path)
    assert _resume(run, request) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert not Path(new["challenge_path"]).exists()
    archived = Path(new["review_correction"]["archive_path"]) / "prior_challenge_tb.sv"
    if kind == "missing":
        archived.rename(archived.with_suffix(".saved"))
    else:
        archived.write_text(archived.read_text() + "\n// changed\n")
    before = _protected(old)
    assert _resume(run, request) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert _protected(old) == before


@fixtures._NEEDS_SIMULATOR
@pytest.mark.parametrize("after_commit", [False, True])
def test_interrupted_transition_resumes_without_rewriting_old_evidence(tmp_path, monkeypatch, after_commit):
    run, old, request, _ = _case(tmp_path)
    before = _protected(old)
    real = bd._write_jsonl
    interrupted = False

    def cut(path, rows):
        nonlocal interrupted
        if Path(path) == run / bd._REVIEW_WORKLIST and not interrupted:
            interrupted = True
            if after_commit:
                real(path, rows)
            raise OSError("injected interruption at atomic transition commit")
        return real(path, rows)

    monkeypatch.setattr(bd, "_write_jsonl", cut)
    assert _resume(run, request) == 2
    assert interrupted
    assert _protected(old) == before
    monkeypatch.setattr(bd, "_write_jsonl", real)
    assert _resume(run, request) == 2
    assert bd._validate_ai_review(bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0])["status"] == "PENDING"
    assert _protected(old) == before


def test_checked_in_public_doc_supplies_real_correction_evidence(tmp_path, monkeypatch):
    artifact = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                            "tests", "fixtures", "real_benchmark", "datasheet_pin_table_interface.md")
    run, task = fixtures._task_with(tmp_path, artifact.read_text(),
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    review = fixtures._valid_review(task)
    evidence = [{"excerpt": "The output is registered with one clock cycle latency.",
                 "supports": "This public artifact provides an explicit output latency obligation."}]
    review["verification_test"]["prompt_evidence"] = evidence
    fixtures._write_review(task, review)
    fixtures._solve_report(run, task)
    request_path, request = _request(run, task)
    request["prompt_evidence"] = evidence
    request_path.write_text(json.dumps(request))
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: 2)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["challenge_path"] != task["challenge_path"]
    assert new["verification_challenges"][0]["prompt_evidence"] == evidence
    # This is a real-input transaction test, not a correctness claim for RTL
    # implementing the document; no acceptance validator is bypassed in product.

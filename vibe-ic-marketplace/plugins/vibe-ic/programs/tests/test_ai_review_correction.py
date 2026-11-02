"""Same-candidate correction is a new proof round, never a PASS shortcut."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import shutil
import sys

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


def _clarification_case(tmp_path, supplemental=False, public_doc=None, *, issue_run=True):
    prompt = public_doc or (
        "Design module dut with input a and output y. assign y = a.\n"
        "Acknowledge after the prescribed delay.\n")
    excerpt = ("The output is registered with one\nclock cycle latency."
               if public_doc else "Acknowledge after the prescribed delay.")
    run, task = fixtures._task_with(tmp_path, prompt,
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    # A source question is not a functional claim and need not author a test.
    shape = dict(task)
    shape["program_verification"] = {"functional_confirmation_required": False}
    review = fixtures._valid_review(shape)
    review["semantic_review"].update({
        "verdict": "NEEDS_CLARIFICATION", "findings": [],
        "rationale": "The public timing obligation needs a reference event before an expected result can be derived.",
    })
    review["spec_clarification"] = {
        "schema": "vibeic.spec_clarification.v1",
        "source_sha256": [task["prompt_sha256"]],
        "requests": [{
            "source_sha256": task["prompt_sha256"], "excerpt": excerpt,
            "missing_information": "The event starting the timing interval is unspecified.",
            "question": "Which event starts the stated interval, including after reset?",
        }],
    }
    if supplemental:
        test = fixtures._write_direct_assignment_challenge(task)
        review["measured_defined_subset"] = {"path": test["path"], "sha256": test["sha256"]}
    fixtures._write_review(task, review)
    if issue_run:
        fixtures._solve_report(run, task)
    request = {
        "schema": bd._REVIEW_CORRECTION_SCHEMA, "id": task["id"],
        "task_sha256": bd._review_task_digest(task),
        "prompt_sha256": task["prompt_sha256"], "rtl_sha256": task["rtl_sha256"],
        "review_sha256": _digest(task["review_path"]),
        "challenge_sha256": _digest(task["challenge_path"]) if supplemental else None,
        "author": {"kind": "AI", "model": "independent-test-reviewer"},
        "blind": {"oracle_accessed": False},
        "rationale": ("A fresh independent reviewer will reconsider the source-bound question on unchanged candidate bytes. "
                      "Archive the prior question and any uncontracted diagnostic without creating a repair or acceptance permit."),
        "prompt_evidence": [{"excerpt": excerpt,
                             "supports": "The questioned interval is stated in the unchanged public source."}],
    }
    path = run / "correction_request.json"
    path.write_text(json.dumps(request))
    return run, task, path, request, review


def _optional_protected(task):
    return {str(path): Path(path).read_bytes() if Path(path).is_file() else None
            for path in [task["prompt_path"], task["review_path"], task["challenge_path"],
                         *task["rtl_paths"], *task["working_rtl_paths"]]}


def _correction_batch_case(tmp_path):
    """Two real immutable correction transitions in one neutral run."""
    import benchmark_io_adapter as bio
    run, first, path, first_request, review = _clarification_case(tmp_path, issue_run=False)
    project = run / "projects/p2"
    shutil.copytree(first["project"], project)
    prompt = (project / "input/phase1_prompt.md").read_text()
    bio._stage_public_original("p2", prompt, {}, project)
    second = bd._make_ai_review_task(
        "p2", project, bio.collect("rtllm", "p2", project), fixtures.ROUTING,
        0, run, "PROGRAM")
    review = {**review, "id": "p2", "prompt_sha256": second["prompt_sha256"],
              "rtl_sha256": second["rtl_sha256"],
              "source_sha256": second["public_original_input"]["source_sha256"]}
    fixtures._write_review(second, review)
    route = bd._make_ai_route_task(
        "p2", project, {"public_original_input": second["public_original_input"]},
        fixtures.ROUTING, run, "rtllm", benchmark="rtllm", dataset_path=Path("/unused"))
    fixtures._solve_report(run, first, extra_routes=[route])
    first_request["task_sha256"] = bd._review_task_digest(first)
    first_path = path.with_name("first_correction.json")
    first_path.write_text(json.dumps(first_request))
    request = {**first_request, "id": "p2",
               "task_sha256": bd._review_task_digest(second),
               "prompt_sha256": second["prompt_sha256"], "rtl_sha256": second["rtl_sha256"],
               "review_sha256": _digest(second["review_path"]), "challenge_sha256": None}
    second_path = first_path.with_name("second_correction.json")
    second_path.write_text(json.dumps(request))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [first, second])
    solve = bd._read_json_regular(run / "solve_report.json")
    solve["results"].append({**solve["results"][0], "id": "p2"})
    solve["total"] = 2
    bd._atomic_write_json(run / "solve_report.json", solve)
    return run, [first, second], [first_path, second_path]


def _count_normal_resume(monkeypatch):
    consume = bd._cmd_resume_locked
    calls = []
    def counted(*args, **kwargs):
        calls.append(args)
        return consume(*args, **kwargs)
    monkeypatch.setattr(bd, "_cmd_resume_locked", counted)
    return calls


def test_repeated_cli_corrections_apply_all_before_one_normal_resume(tmp_path, monkeypatch):
    run, old, paths = _correction_batch_case(tmp_path)
    protected = [_optional_protected(task) for task in old]
    apply = bd._apply_review_correction
    applied = []
    def record(run_p, request):
        with pytest.raises(bd._CoordinatorBusy):
            with bd._run_root_coordinator_lock(run_p, "cannot-interleave"):
                pass
        applied.append(request.name)
        return apply(run_p, request)
    monkeypatch.setattr(bd, "_apply_review_correction", record)
    monkeypatch.setattr(bd, "_install_orphan_guard", lambda: None)
    calls = _count_normal_resume(monkeypatch)
    monkeypatch.setattr(sys, "argv", [bd.__file__, "rtllm", "--resume", "--dataset",
        "/unused", "--run", str(run), "--review-correction", str(paths[0]),
        "--review-correction", str(paths[1])])
    with pytest.raises(SystemExit) as exit:
        bd.main()
    assert applied == [path.name for path in paths], applied
    assert len(calls) == 1
    assert exit.value.code == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert [task["id"] for task in new] == ["p1", "p2"]
    assert all(task["review_path"] != prior["review_path"] for task, prior in zip(new, old))
    assert [_optional_protected(task) for task in old] == protected
    assert all(bd._validate_ai_review(task)["status"] == "PENDING" for task in new)
    assert all(not Path(task["response_path"]).exists() for task in old)


def test_legacy_single_correction_still_runs_one_normal_consumer(tmp_path, monkeypatch):
    run, old, path, _, _ = _clarification_case(tmp_path)
    calls = _count_normal_resume(monkeypatch)
    assert bd.cmd_resume("rtllm", "/unused", str(run), review_correction=str(path)) == 2
    assert len(calls) == 1
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]["review_path"] != old["review_path"]


@pytest.mark.parametrize("damage", ["malformed", "stale"])
def test_later_correction_refusal_preserves_pending_prefix_and_retry(tmp_path, monkeypatch, damage):
    run, old, paths = _correction_batch_case(tmp_path)
    raw = paths[1].read_bytes()
    if damage == "malformed":
        paths[1].write_text('{invalid')
    else:
        request = json.loads(raw)
        request["task_sha256"] = "0" * 64
        paths[1].write_text(json.dumps(request))
    calls = _count_normal_resume(monkeypatch)
    assert bd.cmd_resume("rtllm", "/unused", str(run),
                         review_correction=[str(path) for path in paths]) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert [task["review_path"] == prior["review_path"] for task, prior in zip(new, old)] == [False, True]
    assert calls == []
    assert bd._validate_ai_review(new[0])["status"] == "PENDING"
    archive = Path(new[0]["review_correction"]["archive_path"])
    preserved = {str(p): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
    assert all(not Path(task["response_path"]).exists() for task in old)
    assert all(row["accepted"] is False for row in bd._read_json_regular(run / "solve_report.json")["results"])
    paths[1].write_bytes(raw)
    assert bd.cmd_resume("rtllm", "/unused", str(run),
                         review_correction=[str(path) for path in paths]) == 2
    retried = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert len(calls) == 1 and retried[0] == new[0]
    assert retried[1]["review_path"] != old[1]["review_path"]
    assert all(p.read_bytes() == data for path, data in preserved.items() for p in [Path(path)])
    assert all(bd._validate_ai_review(task)["status"] == "PENDING" for task in retried)


def test_duplicate_request_in_batch_reuses_one_immutable_transition(tmp_path, monkeypatch):
    run, old, path, _, _ = _clarification_case(tmp_path)
    calls = _count_normal_resume(monkeypatch)
    assert bd.cmd_resume("rtllm", "/unused", str(run),
                         review_correction=[str(path), str(path)]) == 2
    assert len(calls) == 1
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    assert len(list((run / "review_corrections/p1").glob("*/transition.json"))) == 1
    assert bd._validate_ai_review(new)["status"] == "PENDING"


@pytest.mark.parametrize("corrections", [[], ["one.json"], "one.json"])
def test_empty_or_mixed_correction_batch_never_enters_operations(tmp_path, monkeypatch, capsys, corrections):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid correction combination entered an operation")
    for name in ("_apply_review_correction", "_apply_program_regate", "_cmd_resume_locked"):
        monkeypatch.setattr(bd, name, forbidden)
    kwargs = {"review_correction": corrections}
    if corrections:
        kwargs["program_regate"] = "regate.json"
    assert bd.cmd_resume("rtllm", "/unused", str(tmp_path / "run"), **kwargs) == 2
    error = capsys.readouterr().err
    assert "PROGRAM_REGATE_REFUSED" in error if corrections else "correction list must not be empty" in error


@pytest.mark.parametrize("supplemental", [False, True])
def test_real_resume_corrects_valid_question_without_inventing_a_test(tmp_path, supplemental):
    run, old, path, _, _ = _clarification_case(tmp_path, supplemental)
    before = _optional_protected(old)
    assert bd._validate_ai_review(old)["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    # Pre-fix this reads the unchanged occupied question path: an observed
    # refusal of a valid correction, not a missing function/import control.
    assert new["review_path"] != old["review_path"]
    assert new["candidate_snapshot"] == old["candidate_snapshot"]
    assert new["verification_challenges"] == old["verification_challenges"]
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert _optional_protected(old) == before
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    assert not Path(old["response_path"]).exists()
    outcome = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["review_outcomes"][0]
    assert outcome["status"] == "PENDING", outcome
    record = new["review_correction"]
    expected = ("PRESERVED_UNCONTRACTED_SUPPLEMENTAL_NOT_PROMOTED"
                if supplemental else "ABSENT_NO_VERIFICATION_OBLIGATION")
    assert record["prior_challenge_status"] == expected
    archive = Path(record["archive_path"])
    assert (archive / "prior_review.json").read_bytes() == Path(old["review_path"]).read_bytes()
    if supplemental:
        assert (archive / "prior_challenge_tb.sv").read_bytes() == Path(old["challenge_path"]).read_bytes()
    else:
        assert not (archive / "prior_challenge_tb.sv").exists()
    status = json.loads((archive / "prior_challenge_status.json").read_text())
    assert status["status"] == expected
    assert record["repair_authorized"] is False


@pytest.mark.parametrize("supplemental", [False, True])
def test_question_correction_replay_preserves_archive_and_fresh_test(tmp_path, supplemental):
    run, old, request, _, _ = _clarification_case(tmp_path, supplemental)
    assert _resume(run, request) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    fixtures._write_direct_assignment_challenge(new)
    before = _digest(new["challenge_path"])
    assert _resume(run, request) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == new
    assert _digest(new["challenge_path"]) == before


def test_question_correction_keeps_every_active_inherited_obligation(tmp_path):
    run, old, path, request, _ = _clarification_case(tmp_path)
    inherited = fixtures._write_invalid_inherited_challenge(old)
    old["verification_challenges"] = [inherited]
    fixtures._solve_report(run, old)
    request["task_sha256"] = bd._review_task_digest(old)
    path.write_text(json.dumps(request))
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    assert new["verification_challenges"] == [inherited]
    review = fixtures._valid_review(new)
    fixtures._write_review(new, review)
    outcome = bd._validate_ai_review(new)
    assert outcome["status"] == "REJECTED", outcome
    assert outcome["inherited_challenge_results"][0]["status"] == "INVALID"
    assert not Path(old["response_path"]).exists()


@pytest.mark.parametrize("damage", ["question", "review_schema", "missing_hash", "stale_hash",
                                    "changed_file", "new_file", "non_question", "malformed_test"])
def test_question_correction_refuses_invalid_or_drifted_material(tmp_path, monkeypatch, capsys, damage):
    supplemental = damage not in {"new_file", "missing_hash"}
    run, old, path, request, review = _clarification_case(tmp_path, supplemental)
    if damage == "question":
        review["spec_clarification"]["requests"][0]["excerpt"] = "An invented public obligation."
    elif damage == "review_schema":
        review["schema"] = "wrong"
    elif damage == "non_question":
        review["semantic_review"]["verdict"] = "FAIL"
        review.pop("spec_clarification")
    elif damage == "malformed_test":
        review["verification_test"] = "not an object"
    elif damage == "missing_hash":
        request.pop("challenge_sha256")
    elif damage == "stale_hash":
        request["challenge_sha256"] = "0" * 64
    elif damage == "changed_file":
        target = Path(old["challenge_path"])
        target.write_text(target.read_text() + "\n// changed after request\n")
    elif damage == "new_file":
        fixtures._write_direct_assignment_challenge(old)
    if damage in {"question", "review_schema", "non_question", "malformed_test"}:
        fixtures._write_review(old, review)
        request["review_sha256"] = _digest(old["review_path"])
    path.write_text(json.dumps(request))
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    monkeypatch.setattr(bd, "_cmd_resume_locked", lambda *a, **k: pytest.fail("refused correction reached resume"))
    assert _resume(run, path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


def test_question_correction_rechecks_absent_supplemental_before_commit(tmp_path, monkeypatch, capsys):
    run, old, path, _, _ = _clarification_case(tmp_path)
    writer = bd._atomic_write_text
    def change_after_prepare(target, text):
        writer(target, text)
        if Path(target).name == "transition.json":
            fixtures._write_direct_assignment_challenge(old)
    monkeypatch.setattr(bd, "_atomic_write_text", change_after_prepare)
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    assert _resume(run, path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


def test_checked_in_public_doc_backs_question_correction(tmp_path):
    artifact = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                            "tests", "fixtures", "real_benchmark", "datasheet_pin_table_interface.md")
    run, old, path, _, _ = _clarification_case(tmp_path, supplemental=True, public_doc=artifact.read_text())
    assert bd._validate_ai_review(old)["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    assert new["verification_challenges"] == old["verification_challenges"]


def test_question_supplemental_drift_between_snapshot_and_hash_is_refused(tmp_path, monkeypatch, capsys):
    run, old, path, _, _ = _clarification_case(tmp_path, supplemental=True)
    target = Path(old["challenge_path"])
    read = Path.read_bytes
    changed = False
    def drift_after_first_read(source):
        nonlocal changed
        data = read(source)
        if source == target and not changed:
            changed = True
            source.write_bytes(data + b"\n// concurrent change\n")
        return data
    monkeypatch.setattr(Path, "read_bytes", drift_after_first_read)
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    assert _resume(run, path) == 2
    assert changed
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before

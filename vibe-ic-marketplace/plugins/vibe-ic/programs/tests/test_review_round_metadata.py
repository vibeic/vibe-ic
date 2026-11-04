"""Same-candidate operations preserve the scorer's existing round metadata."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

import test_ai_review_correction as correction
import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd


@pytest.fixture
def scorer():
    path = Path(bd.__file__).resolve().parents[1] / "benchmark/score_iverilog_tb.py"
    spec = importlib.util.spec_from_file_location("round_metadata_reader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _view(scorer, root, task):
    root.mkdir(parents=True, exist_ok=True)
    (root / bd._ACCEPTANCE_REPORT).write_text(json.dumps({"review_outcomes": [{
        "id": task["id"], "status": "ACCEPTED", "review_path": task["review_path"],
    }]}))
    return scorer.scored_view(root)


def _case(tmp_path, origin):
    run, parent, runner = fixtures._dispatched_parent_task(tmp_path)
    project = Path(parent["project"])
    invocation = parent["program_verification"]["runner_invocation"]
    options = {}
    if origin == "AI_REPAIR":
        review = fixtures._proven_fail_review(parent)
        fixtures._write_review(parent, review)
        challenge, reasons = bd._challenge_from_review(
            parent, review, Path(parent["prompt_path"]).read_text())
        assert reasons == []
        Path(parent["working_rtl_paths"][0]).write_text(
            "module dut(input wire a, output wire y); assign y = a; endmodule\n")
        record = fixtures._write_ai_repair_record(run, parent, challenge)
        provenance, reasons = bd._validate_repair_record(
            bd._repair_record_path(run, parent), parent,
            record["repaired_rtl_sha256"], challenge)
        assert reasons == []
        options = {"verification_challenges": [challenge],
                   "program_candidate": parent["candidate_snapshot"],
                   "repair_parent_candidate": parent["candidate_snapshot"],
                   "repair_provenance": provenance}
        argv = bd._resume_solver_argv(runner, project, True, "2", "8")
        process = bd._RunnerBudget(1, None, 0).run(argv)
        assert process.error is None
        invocation = process.invocation
    got = (bd._collect_runner_result(process, argv, "rtllm", "p1", project)
           if origin == "AI_REPAIR" else
           json.loads(Path(parent["candidate_snapshot"]["response_payload_path"]).read_text()))
    task = bd._make_ai_review_task(
        "p1", project, got, fixtures.ROUTING, 0, run, origin,
        runner_invocation=invocation, **options)
    fixtures._solve_report(run, task)
    return run, task, runner


def _reenter(monkeypatch, runner):
    fixtures._stub_dispatched_reentry(monkeypatch)
    argv_for = bd._resume_solver_argv
    monkeypatch.setattr(bd, "_resume_solver_argv", lambda _runner, *a, **kw:
                        argv_for(runner, *a, **{**kw, "resolve_manifest": False}))
    snapshot = bd._runner_source_snapshot
    def changed_source(argv, **kwargs):
        source = copy.deepcopy(snapshot(argv, **kwargs))
        if len(argv) == 2:
            source["consumer"]["sha256"] = "0" * 64
        return source
    monkeypatch.setattr(bd, "_runner_source_snapshot", changed_source)
    collect = fixtures.bio.collect
    monkeypatch.setattr(fixtures.bio, "collect", lambda fmt, pid, project, **kwargs:
        {"ok": True, "completion": bd._candidate_text(bd._rtl_files(project)),
         "rtl_gen": "NOT_APPLICABLE", "supplied_rtl": True}
        if kwargs.get("supplied_rtl") else collect(fmt, pid, project, **kwargs))


@pytest.mark.parametrize("operation", ["correction", "regate"])
@pytest.mark.parametrize("origin,round_number,expected", [
    ("PROGRAM", 0, "single-shot-first-candidate"),
    ("AI_BACKUP", 0, "single-shot-first-candidate"),
    ("AI_REPAIR", 1, "converged-composed"),
])
def test_normal_same_candidate_operation_keeps_recorded_round(
        tmp_path, monkeypatch, scorer, operation, origin, round_number, expected):
    run, old, runner = _case(tmp_path, origin)
    before = _view(scorer, tmp_path / "metadata-before", old)
    assert before["view"] == expected, before
    protected = {str(p): Path(p).read_bytes() for p in [
        old["prompt_path"], *old["rtl_paths"], *old["working_rtl_paths"]]}
    if operation == "correction":
        fixtures._write_review(old, fixtures._valid_review(old))
        request_path, _ = correction._request(run, old)
        bd._apply_review_correction(run, request_path)
    else:
        _reenter(monkeypatch, runner)
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    after = _view(scorer, tmp_path / "metadata-after", new)
    assert after["view"] == expected, after
    assert after["candidate_rounds"][old["id"]] == {
        "origin": origin.lower(), "round": round_number}, after
    assert new["review_path"] != old["review_path"]
    assert new["challenge_path"] != old["challenge_path"]
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert new["candidate_origin"] == old["candidate_origin"]
    assert new["rtl_sha256"] == old["rtl_sha256"]
    assert new.get("repair_provenance") == old.get("repair_provenance")
    assert {p: Path(p).read_bytes() for p in protected} == protected
    assert not Path(old["response_path"]).exists()
    if operation == "correction":
        bd._apply_review_correction(run, request_path)
        assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == new


@pytest.mark.parametrize("operation", ["correction", "regate"])
@pytest.mark.parametrize("origin,stem,expected", [
    ("AI_BACKUP", "review-correction-unknown", "single-shot-first-candidate"),
    ("AI_REPAIR", "review-correction-unknown", "NOT_MEASURED"),
    ("AI_REPAIR", "ai_repair-r0-unknown", "NOT_MEASURED"),
])
def test_opaque_first_candidate_and_unknown_repair_remain_honest(
        tmp_path, monkeypatch, scorer, operation, origin, stem, expected):
    run, task, runner = _case(tmp_path, origin)
    old = Path(task["review_path"])
    task["review_path"] = str(old.with_name(stem + ".json"))
    fixtures._solve_report(run, task)
    if operation == "correction":
        fixtures._write_review(task, fixtures._valid_review(task))
        request_path, _ = correction._request(run, task)
        bd._apply_review_correction(run, request_path)
    else:
        _reenter(monkeypatch, runner)
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != task["review_path"]
    result = _view(scorer, tmp_path / "metadata-after", new)
    assert result["view"] == expected, result
    if origin == "AI_REPAIR":
        assert result["candidate_rounds"] == {}
    assert new["rtl_sha256"] == task["rtl_sha256"]
    assert not Path(new["response_path"]).exists()


@pytest.mark.parametrize("operation", ["correction", "regate"])
def test_stale_working_material_still_uses_existing_refusal(
        tmp_path, monkeypatch, operation):
    run, task, runner = _case(tmp_path, "PROGRAM")
    fixtures._write_review(task, fixtures._valid_review(task))
    request_path, _ = correction._request(run, task)
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    Path(task["working_rtl_paths"][0]).write_text("module drift; endmodule\n")
    if operation == "correction":
        with pytest.raises(ValueError, match="prompt/candidate/working RTL drift"):
            bd._apply_review_correction(run, request_path)
    else:
        _reenter(monkeypatch, runner)
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
        assert any(row["status"] == "RUNNER_REGATE_BLOCKED"
                   for row in bd._read_jsonl(run / bd._REPAIR_WORKLIST))
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before
    assert not (run / "review_corrections").exists()
    assert not (run / "runner_regates").exists()
    assert not Path(task["response_path"]).exists()


@pytest.mark.parametrize("transformed", [False, True])
def test_explicit_program_regate_prepares_repair_round(
        tmp_path, monkeypatch, scorer, transformed):
    import test_program_reentry as reentry

    monkeypatch.setattr(bd, "_program_version", lambda: reentry._OLD_PROGRAM)
    run, initial, _ = fixtures._task(tmp_path)
    project = Path(initial["project"])
    working = Path(initial["working_rtl_paths"][0])
    working.write_text(reentry._SIGNED_RTL.replace("y = a", "y = ~a"))
    parent = bd._make_ai_review_task(
        "p1", project, fixtures.bio.collect("rtllm", "p1", project),
        fixtures.ROUTING, 0, run, "PROGRAM")
    review = fixtures._proven_fail_review(parent)
    fixtures._write_review(parent, review)
    challenge, reasons = bd._challenge_from_review(
        parent, review, Path(parent["prompt_path"]).read_text())
    assert reasons == []
    working.write_text(reentry._SIGNED_RTL)
    record = fixtures._write_ai_repair_record(run, parent, challenge)
    fixtures._solve_report(run, parent, exit_step="2")
    fixtures._stub_dispatched_reentry(monkeypatch)
    old = reentry._historical_pending_repair(run, parent, challenge, reentry._UNWANTED)
    monkeypatch.setattr(bd, "_program_version", lambda: reentry._NEW_PROGRAM)
    request_path, _ = reentry._request(run, old, record["repaired_rtl_sha256"])
    reentry._gate(monkeypatch, reentry._BENIGN if transformed else reentry._SIGNED_RTL)
    prepared = []
    path_for = bd._regate_path
    def observe_path(path, *args, **kwargs):
        resolved = path_for(path, *args, **kwargs)
        if resolved.parent.parent.name == "ai_reviews":
            prepared.append(resolved)
        return resolved
    monkeypatch.setattr(bd, "_regate_path", observe_path)
    try:
        assert bd._apply_program_regate("rtllm", "/unused", run, request_path, 1) == 2
    except ValueError as exc:
        assert "author preimage contract failed" in str(exc)
        assert "TOOL_UNAVAILABLE" in str(exc) or "COMPILER_IDENTITY_UNTRUSTED" in str(exc)
        assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old
        new = {**old, "review_path": str(prepared[-1])}
        (tmp_path / "explicit-preparation-limitation.txt").write_text(str(exc))
    else:
        new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
        assert new["rtl_sha256"] != old["rtl_sha256"]
        assert (new["rtl_sha256"] != record["repaired_rtl_sha256"]) is transformed
    result = _view(scorer, tmp_path / "metadata-after", new)
    assert result["view"] == "converged-composed", result
    assert result["candidate_rounds"]["p1"] == {"origin": "ai_repair", "round": 1}
    assert new["repair_provenance"] == old["repair_provenance"]
    assert not Path(new["response_path"]).exists()

"""Original runner closure at actual neutral producer/consumer boundaries."""
import json
from pathlib import Path
import shutil
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as bd
import benchmark_io_adapter as bio


WIRE = "module neutral(input a,output y); assign y=a; endmodule\n"


def _fixture(tmp_path, *, retained=False):
    project = tmp_path / "run/projects/neutral"
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Implement neutral wire-through module with input a and output y.\n")
    bio._stage_public_original("neutral", prompt.read_text(), {}, project)
    rtl = project / "phase2/stage1/rtl/neutral.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(WIRE)
    runner = tmp_path / "vibe_ic_one_shot_runner.py"
    runner.write_text('''import json, pathlib, sys
sys.path.insert(0, %r)
p = pathlib.Path(sys.argv[1]).resolve()
mode = sys.argv[2]
q = p/'reports/orchestrator/phase2_one_shot.json'
summary = {'project':str(p), 'verdict':'NOT_MEASURED',
           'steps':[{'name':'rtl_gen','status':'PASS','detail':'neutral current producer'}]}
if mode == 'generate':
    (p/'phase2/stage1/rtl/neutral.v').write_text(%r)
q.parent.mkdir(parents=True, exist_ok=True)
q.write_text(json.dumps(summary))
print('neutral completed stdout')
print('REFUSED: NEUTRAL_DOWNSTREAM after current report', file=sys.stderr)
raise SystemExit(1)
''' % (str(PROGRAMS), WIRE))
    return project, runner


def _retained_compiled_task(tmp_path, monkeypatch, *, change_during_execution=False,
                            supplied=False, top_module="dut"):
    """Real native compile, retained source and the actual report/receipt writers."""
    import test_benchmark_program_first_ai_review as fixture
    from _hostpaths import require_repo
    monkeypatch.delenv("VIBEIC_RETAINED_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("VIBEIC_RETAINED_PLUGIN_MANIFEST", raising=False)
    project = fixture._project(tmp_path)
    if top_module != "dut":
        for relative in ("input/phase1_prompt.md", "phase2/stage1/rtl/dut.v",
                         "phase1/generated_docs/L1_DATASHEET.json"):
            path = project / relative
            path.write_text(path.read_text().replace("dut", top_module))
    prompt = (project / "input/phase1_prompt.md").read_text()
    bio._stage_public_original("p1", prompt, {}, project)
    source = tmp_path / "source-plugin/programs"
    source.mkdir(parents=True)
    actual = require_repo() / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    for name in ("benchmark_dispatch.py", "design_one_shot_runner.py"):
        shutil.copy2(actual / name, source / name)
    consumer = source / "benchmark_dispatch.py"
    monkeypatch.setattr(bd, "__file__", str(consumer))
    runner = source / "vibe_ic_one_shot_runner.py"
    runner.write_text('''import hashlib, json, pathlib, subprocess, sys
sys.path[:0] = [%r, %r]
p = pathlib.Path(sys.argv[1]).resolve()
rtl = p/'phase2/stage1/rtl/dut.v'
command = ['iverilog', '-g2012', '-s', %r, '-tnull', str(rtl)]
compiled = subprocess.run(command, capture_output=True, text=True)
report = p/'reports/orchestrator/phase2_one_shot.json'
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text(json.dumps({
    'project': str(p), 'verdict': 'PASS' if compiled.returncode == 0 else 'FAIL',
    'steps': [{'name': 'rtl_gen', 'status': %r, 'detail': 'retained native candidate; run declared --entry-step 2'},
              {'name': 'rtl_lint_tool', 'status': 'PASS' if compiled.returncode == 0 else 'FAIL',
               'detail': compiled.stderr, 'extras': {'command': command,
                   'native_returncode': compiled.returncode,
                   'input_sha256': hashlib.sha256(rtl.read_bytes()).hexdigest()}}]}))
if %r:
    consumer = pathlib.Path(%r)
    consumer.write_text(consumer.read_text() + '\\n# changed during execution\\n')
raise SystemExit(compiled.returncode)
''' % (str(source), str(PROGRAMS), top_module, 'NOT_APPLICABLE' if supplied else 'PASS',
       change_during_execution, str(consumer)))
    # Use the ordinary dispatcher construction for the input contract this
    # fixture already stages and its issued route later consumes.  A hand-made
    # argv without --rtl-input original mislabeled this invocation as
    # structured Phase-1 input even though public_original was the authority.
    argv = bd._solver_argv(
        runner, project, "2", "2", delivery_route="ip",
        input_contract="original")
    process = bd._RunnerBudget(1, 1, 1).run(argv)
    got = bd._collect_runner_result(process, argv, "rtllm", "p1", project,
                                    supplied_rtl=supplied)
    if change_during_execution:
        return project, process, argv, got
    assert process.rc == 0 and process.error is None and got["ok"] is True, (process.stderr, got)
    task = bd._make_ai_review_task("p1", project, got, fixture.ROUTING, 0,
                                   tmp_path / "run", "PROGRAM", runner_invocation=process.invocation)
    assert bd._invocation_rtl_input(process.invocation) == "original"
    assert task["phase1_provenance"]["input_contract"] == "original"
    assert task["phase1_provenance"]["ran"] is False
    return project, process, argv, task


def _human_resume_case(tmp_path, monkeypatch):
    """Neutral input through Human's issued I/O, ordinary resume and sole emit."""
    import test_benchmark_program_first_ai_review as fixture
    from _hostpaths import require_repo
    registry = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "benchmark",
        "BENCHMARK_REGISTRY.json").read_text())
    assert registry["benchmarks"]["verilogeval-human"]["shape"] == "C"
    _, process, argv, task = _retained_compiled_task(
        tmp_path, monkeypatch, top_module="TopModule")
    run = tmp_path / "run"
    (run / "responses").mkdir()
    fixture._solve_report(run, task, exit_step="2", benchmark="verilogeval-human")
    route = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    receipt = fixture._issue_pending_route_fixture(
        run, route, requested_evidence="lint_validated", benchmark="verilogeval-human")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0].update(route_receipt=receipt, entry=receipt["entry_step"],
                                rc=process.rc, review_task=task["review_path"])
    (run / "solve_report.json").write_text(json.dumps(solve))
    return run, process, argv, task


def _human_review(task):
    import test_benchmark_program_first_ai_review as fixture
    review = fixture._valid_review(task)
    path = Path(review["verification_test"]["path"])
    source = path.read_text().replace("dut candidate", "TopModule candidate")
    path.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    return review


def _export_human_sample(run, task):
    bd._require_program_first_ai_acceptance(run)
    try:
        bd._export_accepted_shape_c_samples("verilogeval-human", run)
        outcome = {"status": "EXPORTED"}
    except SystemExit as exc:
        outcome = {"status": "BLOCKED", "reason": str(exc)}
    assert outcome["status"] == "EXPORTED", outcome
    sample = run / "samples" / f"{task['id']}_sample01.sv"
    assert sample.read_bytes() == Path(task["candidate_snapshot"]["completion_path"]).read_bytes()
    return sample


def test_recovered_native_acceptance_restores_export_ready_state(tmp_path, monkeypatch):
    import test_benchmark_program_first_ai_review as fixture
    run, process, argv, task = _human_resume_case(tmp_path, monkeypatch)
    fixture._write_review(task, _human_review(task))
    assert bd.cmd_resume("verilogeval-human", "/unused", str(run)) == 0
    preserved = {p: p.read_bytes() for p in (
        Path(task["review_path"]),
        Path(task["candidate_snapshot"]["manifest_path"]), Path(task["response_path"]))}
    _upgrade_live_programs(argv)

    assert bd.cmd_resume("verilogeval-human", "/unused", str(run)) == 0
    _export_human_sample(run, task)
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["ok"] is result["candidate_ready"] is result["accepted"] is True
    assert result["review_task"] == task["review_path"]
    assert result["candidate_origin"] == "PROGRAM"
    assert {p: p.read_bytes() for p in preserved} == preserved
    assert not (run / "runner_regates").exists()


def test_corrected_native_review_syncs_export_pointer_after_fresh_proof(tmp_path, monkeypatch):
    import test_ai_review_correction as correction
    import test_benchmark_program_first_ai_review as fixture
    run, process, _, old = _human_resume_case(tmp_path, monkeypatch)
    review = _human_review(old)
    path = Path(old["challenge_path"])
    source = path.read_text().replace("if (y !== 1'b0)", "if (y !== 1'b1)")
    path.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    review["semantic_review"].update({
        "verdict": "FAIL", "findings": ["The reviewer incorrectly expects inversion."],
        "prompt_evidence": review["verification_test"]["prompt_evidence"]})
    fixture._write_review(old, review)
    request_path, request = correction._request(run, old)
    preserved = {p: p.read_bytes() for p in (
        Path(old["review_path"]), path,
        Path(old["candidate_snapshot"]["manifest_path"]))}
    assert bd.cmd_resume("verilogeval-human", "/unused", str(run),
                         review_correction=str(request_path)) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    archive = Path(new["review_correction"]["archive_path"])
    archived = {p: p.read_bytes() for p in archive.iterdir() if p.is_file()}
    with pytest.raises(SystemExit, match="not ACCEPTED"):
        bd._export_accepted_shape_c_samples("verilogeval-human", run)
    fresh = _human_review(new)
    fresh["challenge_supersessions"] = [{
        "schema": bd._CHALLENGE_SUPERSESSION_SCHEMA,
        "challenge_sha256": request["challenge_sha256"],
        "rationale": request["rationale"], "prompt_evidence": request["prompt_evidence"]}]
    fixture._write_review(new, fresh)
    assert bd.cmd_resume("verilogeval-human", "/unused", str(run)) == 0
    _export_human_sample(run, new)
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["review_task"] == new["review_path"]
    assert result["candidate_origin"] == new["candidate_origin"] == "PROGRAM"
    assert new["candidate_snapshot"] == old["candidate_snapshot"]
    assert {p: p.read_bytes() for p in preserved} == preserved
    assert {p: p.read_bytes() for p in archived} == archived


@pytest.mark.parametrize("mutation", ["frozen_rtl", "review_hash", "collector_unready"])
def test_native_acceptance_sync_cannot_promote_unready_or_tampered_candidate(
        tmp_path, monkeypatch, mutation):
    import test_benchmark_program_first_ai_review as fixture
    run, process, argv, task = _human_resume_case(tmp_path, monkeypatch)
    fixture._write_review(task, _human_review(task))
    assert bd.cmd_resume("verilogeval-human", "/unused", str(run)) == 0
    _upgrade_live_programs(argv)
    if mutation == "frozen_rtl":
        Path(task["rtl_paths"][0]).write_text("module TopModule; endmodule\n")
    elif mutation == "review_hash":
        review = json.loads(Path(task["review_path"]).read_text())
        review["rtl_sha256"] = "0" * 64
        fixture._write_review(task, review)
    else:
        # Real collector refusal: its owning report no longer permits collection.
        report = Path(task["project"]) / "reports/orchestrator/phase2_one_shot.json"
        document = json.loads(report.read_text())
        document["steps"][0]["status"] = "BLOCKED"
        report.write_text(json.dumps(document))
        assert bio.collect("verilogeval", "p1", Path(task["project"]))["ok"] is False
    assert bd.cmd_resume("verilogeval-human", "/unused", str(run)) == 2
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["candidate_ready"] is result["accepted"] is False
    with pytest.raises(SystemExit, match="BLOCKED"):
        bd._export_accepted_shape_c_samples("verilogeval-human", run)
    assert not (run / "samples" / "p1_sample01.sv").exists()


def _upgrade_live_programs(argv):
    for path in (Path(argv[1]), Path(bd.__file__)):
        path.write_text(path.read_text() + "\n# next installed version\n")


def test_completed_native_proof_survives_live_runner_and_dispatcher_upgrade(tmp_path, monkeypatch):
    project, process, argv, task = _retained_compiled_task(tmp_path, monkeypatch)
    report = project / "reports/orchestrator/phase2_one_shot.json"
    measured = json.loads(report.read_bytes())["steps"][1]
    assert measured["extras"]["native_returncode"] == 0
    _upgrade_live_programs(argv)
    assert bd._runner_reentry_reason(task, {"accepted": True}) is None


@pytest.mark.parametrize("supplied", [False, True])
def test_published_native_candidate_reuses_original_review_after_upgrade(tmp_path, monkeypatch, supplied):
    import test_benchmark_program_first_ai_review as fixture
    project, process, argv, task = _retained_compiled_task(tmp_path, monkeypatch, supplied=supplied)
    run = tmp_path / "run"
    (run / "responses").mkdir()
    fixture._solve_report(run, task, exit_step="2")
    routes = bd._read_jsonl(run / bd._ROUTE_WORKLIST)
    receipt = fixture._issue_pending_route_fixture(run, routes[0], requested_evidence="lint_validated")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0].update(route_receipt=receipt, entry=receipt["entry_step"])
    (run / "solve_report.json").write_text(json.dumps(solve))
    fixture._write_review(task, fixture._valid_review(task))
    initial_rc = bd.cmd_resume("rtllm", "/unused", str(run))
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted_ids"] == ["p1"]
    assert initial_rc == 0
    paths = (Path(task["review_path"]), Path(task["response_path"]))
    original = {p: p.read_bytes() for p in paths}
    _upgrade_live_programs(argv)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted_ids"] == ["p1"]
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]["review_path"] == task["review_path"]
    assert {p: p.read_bytes() for p in original} == original
    assert not (run / "runner_regates").exists()


@pytest.mark.parametrize("mutation", ["no_receipt", "options", "output"])
def test_program_owned_supplied_rtl_still_requires_unchanged_native_binding(tmp_path, monkeypatch, mutation):
    import test_benchmark_program_first_ai_review as fixture
    project, _, _, task = _retained_compiled_task(tmp_path, monkeypatch, supplied=True)
    run = tmp_path / "run"
    (run / "responses").mkdir()
    fixture._solve_report(run, task, exit_step="2")
    routes = bd._read_jsonl(run / bd._ROUTE_WORKLIST)
    receipt = fixture._issue_pending_route_fixture(run, routes[0], requested_evidence="lint_validated")
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0].update(route_receipt=receipt, entry=receipt["entry_step"])
    (run / "solve_report.json").write_text(json.dumps(solve))
    fixture._write_review(task, fixture._valid_review(task))
    assert task["candidate_origin"] == "PROGRAM"
    assert bio.collect("rtllm", "p1", project)["ok"] is False
    if mutation == "no_receipt":
        task["program_verification"].pop("runner_invocation")
        bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    else:
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
        if mutation == "options":
            task["program_verification"]["runner_argv"].append("--changed-window")
            bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
        else:
            Path(task["working_rtl_paths"][0]).write_text("module dut; endmodule\n")
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted_ids"] == []
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]["candidate_origin"] == "PROGRAM"

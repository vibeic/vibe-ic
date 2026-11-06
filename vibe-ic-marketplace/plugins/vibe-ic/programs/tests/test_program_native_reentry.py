"""Explicit PROGRAM regeneration controls; runner reports are SOURCE_ONLY_FIXTURE.

The real receipt, public-input, route, snapshot and executable host challenge
consumers run here. The child is a neutral producer, not native gate evidence.
"""
import copy
import json
import shutil
from pathlib import Path

import pytest
from _hostpaths import require_repo

import test_benchmark_program_first_ai_review as fx

bd, bio = fx.bd, fx.bio
pytestmark = fx._NEEDS_SIMULATOR
OLD = "0.0.1"


@pytest.fixture(autouse=True)
def _runtime(monkeypatch):
    fx._rt_pair.assume_matching_runtime_pair(monkeypatch)
    monkeypatch.setenv("VIBEIC_CHALLENGE_BACKEND", "host")


def _setup(tmp_path, monkeypatch, *, with_sibling=False):
    run, seed, _ = fx._task(tmp_path)
    project = Path(seed["project"])
    old_root = run / "old-plugin"
    programs = old_root / "programs"
    programs.mkdir(parents=True)
    (old_root / ".claude-plugin").mkdir()
    (old_root / ".claude-plugin/plugin.json").write_text(json.dumps({"version": OLD}))
    shipped_producer = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "design_one_shot_runner.py")
    shutil.copyfile(shipped_producer,
                    programs / "design_one_shot_runner.py")
    runner = programs / "vibe_ic_one_shot_runner.py"
    script = '''import pathlib, sys
sys.path.insert(0, %r)
sys.path.insert(0, %r)
import json
def _write_phase2_report(path, report, project):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
p = pathlib.Path(sys.argv[1])
_write_phase2_report(p/'reports/orchestrator/phase2_one_shot.json', {
 'verdict':'PASS', 'steps':[{'name':n,'status':'PASS','detail':'neutral producer'} for n in ('rtl_gen','rtl_validate')],
 'measurement_scope':'SOURCE_ONLY_FIXTURE','native_gate_status':'NOT_MEASURED'}, p)
''' % (str(fx.PROGRAMS), str(programs))
    runner.write_text(script)
    argv = bd._resume_solver_argv(runner, project, False, "1", "2",
                                 input_contract="original")
    process = bd._RunnerBudget(1, 1, 1).run(argv)
    assert process.error is None, process.error
    got = bd._collect_runner_result(process, argv, "rtllm", "p1", project)
    assert got["ok"], got
    task = bd._make_ai_review_task("p1", project, got, fx.ROUTING, 0, run, "PROGRAM",
                                   runner_invocation=process.invocation)
    siblings, extra_routes = [], []
    if with_sibling:
        sibling_project = fx._project(tmp_path, problem_id="p2")
        sibling_prompt = (sibling_project / "input/phase1_prompt.md").read_text()
        sibling_source = (sibling_project / "phase2/stage1/rtl/dut.v").read_text()
        bio._stage_public_original("p2", sibling_prompt, {"dut.v": sibling_source}, sibling_project)
        sibling_argv = bd._resume_solver_argv(runner, sibling_project, False, "1", "2",
                                              input_contract="original")
        sibling_process = bd._RunnerBudget(1, 1, 1).run(sibling_argv)
        assert sibling_process.error is None
        sibling_got = bd._collect_runner_result(sibling_process, sibling_argv, "rtllm", "p2", sibling_project)
        siblings.append(bd._make_ai_review_task("p2", sibling_project, sibling_got, fx.ROUTING, 0, run, "PROGRAM",
                                               runner_invocation=sibling_process.invocation))
        extra_routes.append(bd._make_ai_route_task(
            "p2", sibling_project, {"public_original_input": siblings[0]["public_original_input"]},
            fx.ROUTING, run, "rtllm", benchmark="rtllm", dataset_path=Path("/unused")))
    fx._solve_report(run, task, exit_step="2", extra_routes=extra_routes)
    route = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    receipt = fx._issue_pending_route_fixture(run, route, requested_evidence="lint_validated")
    for sibling_route in bd._read_jsonl(run / bd._ROUTE_WORKLIST)[1:]:
        fx._issue_pending_route_fixture(run, sibling_route, requested_evidence="lint_validated")
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["results"][0].update(entry=receipt["entry_step"], route_receipt=receipt)
    solve_path.write_text(json.dumps(solve))
    review = fx._valid_review(task)
    fx._write_review(task, review)
    # A second distinct inherited executable proof remains active as well.
    inherited, reasons = bd._challenge_from_review(task, review, Path(task["prompt_path"]).read_text())
    assert reasons == []
    path = run / "inherited_tb.sv"
    path.write_text(Path(inherited["path"]).read_text() + "\n// previous independent proof\n")
    inherited.update(path=str(path), sha256=bd._sha256_text(path.read_text()))
    task["verification_challenges"] = [inherited]
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task, *siblings])
    request = {
        "schema": bd._PROGRAM_REGATE_SCHEMA, "id": "p1",
        "task_sha256": bd._review_task_digest(task),
        "prompt_sha256": task["prompt_sha256"], "stale_output_sha256": task["rtl_sha256"],
        "program_version_before": OLD, "program_version_after": bd._program_version(),
        "program_identity": bd._program_source_identity(),
        "review_sha256": bd._sha256_text(Path(task["review_path"]).read_text()),
        "challenge_sha256": review["verification_test"]["sha256"],
        "author": {"kind": "AI", "model": "neutral-independent-reviewer"},
        "blind": {"oracle_accessed": False},
        "rationale": "Re-enter the fixed deterministic Program on the unchanged public input; retain all executable proofs and require a fresh independent review of the regenerated candidate.",
    }
    request_path = run / "native-request.json"
    request_path.write_text(json.dumps(request))
    # Keep ordinary resume's source-upgrade selector quiet: this control is
    # specifically about the explicit authoring retry, not same-bytes re-gating.
    new_runner = run / "new-runner" / runner.name
    new_runner.parent.mkdir()
    fixed_rtl = "module dut(input wire a, output wire y);\n assign y = a;\nendmodule\n"
    new_runner.write_text(script + "\n(p/'phase2/stage1/rtl/dut.v').write_text(%r)\n" % fixed_rtl)
    # Emit AFTER generation so the real report/receipt binds the new material.
    text = new_runner.read_text()
    authoring = text[text.index("\n(p/"):]
    prepare = "\nassert not list((p/'phase2/stage1/rtl').glob('*.v'))\n(p/'phase2/stage1/rtl').mkdir(parents=True, exist_ok=True)\n"
    new_runner.write_text(text[:text.index("_write_phase2_report(p/")] + prepare + authoring + "\n" +
                          text[text.index("_write_phase2_report(p/"):text.index("\n(p/")])
    seen = []
    argv_for = bd._resume_solver_argv

    def selected(_runner, proj, supplied_rtl, *args, **kwargs):
        seen.append(supplied_rtl)
        return argv_for(new_runner, proj, supplied_rtl, *args,
                        **kwargs)

    monkeypatch.setattr(bd, "_resume_solver_argv", selected)
    return run, task, request_path, request, seen, old_root


def _resume(run, request):
    return bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1,
                         program_regate=str(request))


def test_completed_program_has_no_ordinary_worker_reentry(tmp_path, monkeypatch):
    run, task, _, _, _, _ = _setup(tmp_path, monkeypatch)
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert bd._runner_reentry_reason(task, result) is None
    assert bd._validate_ai_review(task)["challenge_result"]["status"] == "PASS"


def test_explicit_program_regeneration_retains_challenges_and_history(tmp_path, monkeypatch, capsys):
    run, old, request, _, seen, _ = _setup(tmp_path, monkeypatch)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["results"][0]["ai_repair_required"] = True
    solve_path.write_text(json.dumps(solve))
    bd._write_jsonl(run / bd._REPAIR_WORKLIST, [{
        "id": "p1", "status": "PROGRAM_GATE_NOT_MEASURED", "reviewed_rtl_sha256": old["rtl_sha256"]}])
    frozen = {path: Path(path).read_bytes() for path in
              [old["candidate_snapshot"]["manifest_path"], *old["rtl_paths"],
               old["review_path"], old["challenge_path"],
               old["verification_challenges"][0]["path"]]}
    assert _resume(run, request) == 2
    output = capsys.readouterr()
    current = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert current["review_path"] != old["review_path"], output.err
    assert current["rtl_sha256"] != old["rtl_sha256"]
    assert current["candidate_origin"] == "PROGRAM" and current["repair_provenance"] is None
    assert current["public_original_input"] == old["public_original_input"]
    assert seen == [False]
    assert {c["sha256"] for c in current["verification_challenges"]} == {
        old["verification_challenges"][0]["sha256"],
        bd._sha256_text(Path(old["challenge_path"]).read_text())}
    assert all(Path(p).read_bytes() == data for p, data in frozen.items())
    assert not Path(current["review_path"]).exists()
    assert not Path(current["response_path"]).exists()
    assert current["program_verification"]["runner_invocation"] != old["program_verification"]["runner_invocation"]
    assert bd._runner_reentry_reason(current, {}) is None
    archive = Path(current["program_regate"]["archive_path"])
    assert json.loads((archive / "prior_task.json").read_text()) == old
    assert (archive / "terminal.json").is_file()
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    result = json.loads(solve_path.read_text())["results"][0]
    assert result["ai_repair_required"] is False
    assert result["accepted"] is False and result["awaiting_ai_review"] is True
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["schema"] == bd._ACCEPTANCE_SCHEMA
    assert acceptance["accepted_ids"] == [] and acceptance["pending_review"] == 1


def test_program_reentry_leaves_an_accepted_sibling_untouched(tmp_path, monkeypatch):
    run, task, path, _, seen, _ = _setup(tmp_path, monkeypatch, with_sibling=True)
    # A normal second product fixture, published before the targeted request.
    sibling = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[1]
    project = Path(sibling["project"])
    got = bio.collect("rtllm", "p2", project)
    fx._write_review(sibling, fx._valid_review(sibling))
    Path(sibling["response_path"]).write_bytes(Path(sibling["candidate_snapshot"]["response_payload_path"]).read_bytes())
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task, sibling])
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    result = copy.deepcopy(solve["results"][0])
    pointer = bd._read_json_regular(project / "reports/orchestrator/receipts/route_decision.current.json")
    receipt = bd._read_json_regular(Path(pointer["receipt_path"]))["payload"]
    result.update(id="p2", accepted=True, candidate_ready=True, entry=receipt["entry_step"],
                  candidate_origin="PROGRAM", review_task=sibling["review_path"], route_receipt=receipt,
                  runner_invocation=sibling["program_verification"]["runner_invocation"],
                  public_original_input=sibling["public_original_input"])
    result["phases"] = fx.fpa.attribute(project, routing=fx.ROUTING, entry=result["entry"],
                                       evidence=result["evidence"], exit_step="2", artefact_collected=True)
    solve.update(total=2, accepted=1)
    solve["results"].append(result)
    solve_path.write_text(json.dumps(solve))
    accepted = {"id": "p2", "status": "ACCEPTED", "reviewer_model": "previous-independent-reviewer"}
    bd._atomic_write_json(run / bd._ACCEPTANCE_REPORT, {
        "schema": bd._ACCEPTANCE_SCHEMA, "accepted_ids": ["p2"], "accepted": 1,
        "total": 2, "review_outcomes": [accepted]})
    frozen = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    frozen.update({p: Path(p).read_bytes() for p in
                   [sibling["review_path"], sibling["response_path"], *sibling["rtl_paths"]]})
    assert _resume(run, path) == 2
    assert seen == [False]
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[1] == sibling
    sibling_result = json.loads(solve_path.read_text())["results"][1]
    assert sibling_result["accepted"] is True
    assert sibling_result["required_gate_ledger"]["eligibility"] == "ELIGIBLE"
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["accepted_ids"] == ["p2"]
    sibling_outcome = next(o for o in acceptance["review_outcomes"] if o["id"] == "p2")
    assert sibling_outcome["status"] == "ACCEPTED"
    assert all(Path(p).read_bytes() == data for p, data in frozen.items()), [p for p, data in frozen.items() if Path(p).read_bytes() != data]


@pytest.mark.parametrize("control,needle", [
    ("stale", "stale task_sha256"), ("accepted", "task must be unaccepted"),
    ("published", "candidate already published"), ("origin", "only an"),
    ("version", "Program version unchanged"), ("identity", "stale Program identity"),
    ("same-source", "Program identity has not changed"),
    ("working", "working or frozen RTL drift"), ("public", "PUBLIC_INPUT"),
    ("request-proof-metadata", None),
    ("inherited-challenge", "invalid current review/source"),
])
def test_program_native_reentry_refusals(tmp_path, monkeypatch, capsys, control, needle):
    run, task, path, request, seen, old_root = _setup(tmp_path, monkeypatch)
    if control == "stale":
        request["task_sha256"] = "0" * 64
    elif control == "accepted":
        solve_path = run / "solve_report.json"
        solve = json.loads(solve_path.read_text())
        solve["results"][0]["accepted"] = True
        solve_path.write_text(json.dumps(solve))
    elif control == "published":
        Path(task["response_path"]).write_text("{}")
    elif control == "origin":
        task["candidate_origin"] = "AI_BACKUP"
    elif control == "version":
        request["program_version_before"] = request["program_version_after"]
    elif control == "identity":
        request["program_identity"]["source_sha256"] = "0" * 64
    elif control == "same-source":
        task["program_regate"] = {"program_identity": request["program_identity"]}
    elif control == "working":
        Path(task["working_rtl_paths"][0]).write_text("module drift; endmodule\n")
    elif control == "public":
        Path(task["public_original_input_paths"][0]).write_text("module drift; endmodule\n")
    elif control == "request-proof-metadata":
        request["review_sha256"] = "0" * 64
        request["challenge_sha256"] = "0" * 64
        (old_root / ".claude-plugin/plugin.json").write_text(json.dumps({"version": "different-history-label"}))
    elif control == "inherited-challenge":
        Path(task["verification_challenges"][0]["path"]).write_text("module drift; endmodule\n")
    if control in {"origin", "same-source"}:
        bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
        request["task_sha256"] = bd._review_task_digest(task)
    path.write_text(json.dumps(request))
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, path) == 2
    output = capsys.readouterr()
    if control == "request-proof-metadata":
        current = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
        assert current["review_path"] != task["review_path"], output.err
        assert seen == [False]
        assert Path(task["challenge_path"]).read_bytes()
        assert task["challenge_path"] in [c["path"] for c in current["verification_challenges"]]
        assert not Path(current["review_path"]).exists()
        return
    assert needle in output.err, output
    assert seen == []
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


def test_program_reentry_failure_has_terminal_evidence_and_no_ai_permit(tmp_path, monkeypatch):
    run, task, path, _, seen, _ = _setup(tmp_path, monkeypatch)
    runner = run / "new-runner/vibe_ic_one_shot_runner.py"
    runner.write_text("raise RuntimeError('neutral producer failed before report')\n")
    assert _resume(run, path) == 2
    assert seen == [False]
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == [task]
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert not Path(task["response_path"]).exists()
    archives = list((run / "runner_regates/p1").glob("program-regate-*"))
    assert len(archives) == 1
    terminal = json.loads((archives[0] / "terminal.json").read_text())
    assert terminal["status"] == "FAILED"
    assert terminal["result"]["rc"] != 0
    assert terminal["result"]["runner_invocation"]


def test_identical_regenerated_bytes_still_need_a_new_review(tmp_path, monkeypatch):
    run, task, path, _, _, _ = _setup(tmp_path, monkeypatch)
    runner = run / "new-runner/vibe_ic_one_shot_runner.py"
    script = runner.read_text()
    original = Path(task["rtl_paths"][0]).read_text()
    runner.write_text("\n".join("(p/'phase2/stage1/rtl/dut.v').write_text(%r)" % original
                                if line.startswith("(p/'phase2/stage1/rtl/dut.v').write_text") else line
                                for line in script.splitlines()) + "\n")
    assert _resume(run, path) == 2
    current = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert current["rtl_sha256"] == task["rtl_sha256"]
    assert current["review_path"] != task["review_path"]
    assert not Path(current["review_path"]).exists()
    assert not Path(current["response_path"]).exists()


def test_changed_public_source_during_regeneration_cannot_rebind_the_task(tmp_path, monkeypatch):
    run, task, path, _, _, _ = _setup(tmp_path, monkeypatch)
    runner = run / "new-runner/vibe_ic_one_shot_runner.py"
    # Restage a different otherwise-valid public manifest in the child. This
    # must not become the new task's baseline when the original was already bound.
    mutation = ("import benchmark_io_adapter as bio\n"
                "bio._stage_public_original('p1', (p/'input/phase1_prompt.md').read_text(), "
                "{'dut.v': 'module dut(input a, output y); assign y = a; endmodule\\n'}, p)\n")
    runner.write_text(runner.read_text().replace("_write_phase2_report(p/", mutation + "_write_phase2_report(p/"))
    assert _resume(run, path) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == [task]
    assert not Path(task["response_path"]).exists()
    archive = next((run / "runner_regates/p1").glob("program-regate-*"))
    terminal = json.loads((archive / "terminal.json").read_text())
    assert terminal["status"] == "FAILED"
    assert terminal["reason"] or terminal["result"].get("runner_diagnostics")
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == []

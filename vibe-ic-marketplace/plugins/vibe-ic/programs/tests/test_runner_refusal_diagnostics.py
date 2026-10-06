"""Producer/consumer diagnostics on neutral projects; no dataset evaluation."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as bd
import benchmark_io_adapter as bio
from _hostpaths import require_repo


def _argv(project):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "vibe_ic_one_shot_runner.py")
    return [sys.executable, str(runner), str(project), "--skip-analog",
            "--skip-hardware", "--skip-phase3", "--entry-step", "2",
            "--exit-step", "2", "--no-dashboard"]


def test_real_canonical_refusal_survives_the_producer(tmp_path):
    argv = _argv(tmp_path)
    raw = subprocess.run(argv, capture_output=True, text=True)
    process = bd._RunnerBudget(1, None, 0).run(argv)
    assert raw.returncode == process.rc == 2
    assert raw.stderr.startswith("REFUSED: DELIVERY_ROUTE_UNDECLARED")
    assert getattr(process, "stderr", "") == raw.stderr
    assert getattr(process, "stdout", None) == raw.stdout
    receipt = json.loads(Path(process.receipt_path).read_text())
    assert receipt["argv"] == argv
    assert receipt["project"] == str(tmp_path.resolve())
    assert receipt["stderr"] == raw.stderr
    assert receipt["rc"] == 2


def test_diagnostic_receipts_follow_the_existing_report_taxonomy(tmp_path):
    import reports_subfolder_taxonomy_check as taxonomy
    process = bd._RunnerBudget(1, None, 0).run(_argv(tmp_path))
    assert process.rc == 2
    result = taxonomy.audit(tmp_path)
    assert result.passed, result.stray_dirs


def test_frontdoor_names_the_actual_refusal_instead_of_missing_provenance(tmp_path, monkeypatch):
    prompt = tmp_path / "input" / "phase1_prompt.md"
    prompt.parent.mkdir()
    prompt.write_text("Describe a neutral digital block.\n")
    # Explicitly exercise a refused invocation independently of the separately
    # maintained default route policy (_solver_argv, PR #2846).
    argv = _argv(tmp_path)
    argv[argv.index("--entry-step") + 1] = "D1"
    argv[argv.index("--exit-step") + 1] = "D1"
    monkeypatch.setattr(bd, "_solver_argv", lambda *a: list(argv))
    result = bd._ensure_phase1_frontdoor(Path(_argv(tmp_path)[1]), tmp_path,
                                        bd._RunnerBudget(1, None, 0))
    assert result["status"] == "BLOCKED"
    assert result["runner_rc"] == 2
    assert result["reason"].startswith("REFUSED: DELIVERY_ROUTE_UNDECLARED")


def _report(project, status="PASS", *, invocation_context=None):
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    from design_one_shot_runner import _write_phase2_report
    _write_phase2_report(report, {"steps": [{"name": "rtl_gen",
                         "status": status, "detail": "neutral evidence"}]}, project,
                         invocation_context=invocation_context)
    return report


def test_solve_exposes_the_current_refusal_with_stale_scaffolds(tmp_path, monkeypatch):
    import test_issue1970_benchmark_dispatch_parallel as fx
    # This helper may be imported after an importlib test has replaced the
    # bare benchmark_dispatch module. Bind both helper modules to the objects
    # this test patches so its producer argv and stage seam stay aligned.
    monkeypatch.setattr(fx, "bd", bd)
    monkeypatch.setattr(fx, "bio", bio)
    real_run = subprocess.run
    fx._install_solve_fakes(monkeypatch, {})
    canonical_argv = bd._solver_argv

    def solver_argv(runner, project, entry, exit_step, *args):
        if exit_step == "D1":
            return canonical_argv(runner, project, entry, exit_step, *args)
        # Deliberately omit the downstream route to exercise the real refusal.
        return _argv(project)

    def producer(argv, **kwargs):
        if argv[argv.index("--exit-step") + 1] == "D1":
            fx.review_fixture._emit_d1_fixture_report(
                Path(argv[2]), json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(bd, "_solver_argv", solver_argv)
    monkeypatch.setattr(bd.subprocess, "run", producer)
    original_stage = bio.stage

    def stage(fmt, problem, project):
        result = original_stage(fmt, problem, project)
        _report(project, "FAIL")
        return result

    monkeypatch.setattr(bio, "stage", stage)
    dataset = tmp_path / "empty-input"
    dataset.mkdir()
    run = tmp_path / "solve"
    assert fx._solve_after_ai_route("rtllm", dataset, run) == 2
    results = json.loads((run / "solve_report.json").read_text())["results"]
    for row in results:
        assert row["rc"] == 2
        diagnostic = row.get("runner_diagnostics") or {}
        assert diagnostic.get("reason_class", "UNDISCLOSED") == "DELIVERY_ROUTE_UNDECLARED"
        assert not row["candidate_ready"]
        assert not row["awaiting_ai_backup"]
        assert row["phase1_frontdoor"]["status"] == "GENERATED"
        assert row["phase1_frontdoor"]["d1_gate"]["current_call"] is True
        receipt = json.loads(Path(diagnostic["receipt_path"]).read_text())
        assert receipt["project"] == str((run / "projects" / row["id"]).resolve())
        assert receipt["invocation_id"] == diagnostic["invocation_id"]


@pytest.mark.parametrize("rc", [0, 1, 2])
def test_fresh_reports_preserve_collection_even_after_nonzero_handoffs(
        tmp_path, monkeypatch, rc):
    def producer(argv, **_kwargs):
        _report(tmp_path, invocation_context=json.loads(_kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
        return subprocess.CompletedProcess(argv, rc, "complete stdout\n" * 500,
                                           "REFUSED: INNER_HANDOFF: continue by evidence\n")

    monkeypatch.setattr(bd.subprocess, "run", producer)
    argv = _argv(tmp_path)
    process = bd._RunnerBudget(1, None, 0).run(argv)
    calls = []
    monkeypatch.setattr(bio, "collect", lambda *a, **k:
                        calls.append((a, k)) or {"ok": True, "completion": "neutral"})
    got = bd._collect_runner_result(process, argv, "neutral", "n", tmp_path)
    assert got["ok"] is True
    assert len(calls) == 1
    assert got["runner_diagnostics"]["status"] == "REPORTS_AVAILABLE"
    assert process.error is None
    receipt = json.loads(Path(process.receipt_path).read_text())
    assert receipt["stdout"] == "complete stdout\n" * 500
    assert receipt["stderr"] == "REFUSED: INNER_HANDOFF: continue by evidence\n"


@pytest.mark.parametrize("rc", [0, 2])
def test_stale_pass_report_cannot_lend_evidence_to_a_new_invocation(
        tmp_path, monkeypatch, rc):
    _report(tmp_path)
    argv = _argv(tmp_path)
    monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], rc, "", "REFUSED: NEUTRAL_INPUT: absent\n"))
    process = bd._RunnerBudget(1, None, 0).run(argv)
    monkeypatch.setattr(bio, "collect", lambda *a, **k: pytest.fail("stale evidence reached collection"))
    got = bd._collect_runner_result(process, argv, "neutral", "n", tmp_path)
    assert got["ok"] is False
    assert got["reason"] == "REFUSED: NEUTRAL_INPUT: absent"


@pytest.mark.parametrize("corruption", ["project", "argv", "receipt", "report", "invocation"])
def test_diagnostics_cannot_be_rebound_or_replayed(tmp_path, monkeypatch, corruption):
    argv = _argv(tmp_path)
    monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k:
                        (_report(tmp_path, invocation_context=json.loads(k["env"][bd._RUNNER_CONTEXT_ENV])), subprocess.CompletedProcess(a[0], 0, "ok", ""))[1])
    process = bd._RunnerBudget(1, None, 0).run(argv)
    project = tmp_path
    if corruption == "project":
        project = tmp_path / "other"
    elif corruption == "argv":
        argv = [*argv, "--different-invocation"]
    elif corruption == "receipt":
        Path(process.receipt_path).unlink()
    elif corruption == "report":
        _report(tmp_path, "FAIL")
    else:
        process = replace(process, invocation_id="another-invocation")
    monkeypatch.setattr(bio, "collect", lambda *a, **k: pytest.fail("unbound evidence reached collection"))
    got = bd._collect_runner_result(process, argv, "neutral", "n", project)
    assert got["ok"] is False
    assert got["runner_diagnostics"]["status"] == "INVOCATION_MISMATCH"


def test_resume_keeps_each_projects_invocation(tmp_path, monkeypatch):
    import test_issue1970_benchmark_dispatch_parallel as fx
    monkeypatch.setattr(fx, "bd", bd)
    monkeypatch.setattr(fx, "bio", bio)
    fx._install_common_fakes(monkeypatch)
    run = tmp_path / "resume"
    fx._write_resume_fixture(run)
    monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 2, "", "REFUSED: NEUTRAL_INPUT: absent\n"))
    assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    rows = json.loads((run / "solve_report.json").read_text())["results"]
    identities = set()
    for row in rows:
        diagnostic = row.get("runner_diagnostics") or {}
        assert diagnostic.get("reason_class", "UNDISCLOSED") == "NEUTRAL_INPUT"
        receipt = json.loads(Path(diagnostic["receipt_path"]).read_text())
        assert receipt["project"] == str((run / "projects" / row["id"]).resolve())
        identities.add(diagnostic["invocation_id"])
    assert len(identities) == 2


def test_an_old_receipt_cannot_supply_diagnostics_after_an_identical_rerun(tmp_path, monkeypatch):
    argv = _argv(tmp_path)
    monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 2, "", "REFUSED: NEUTRAL_INPUT: absent\n"))
    budget = bd._RunnerBudget(1, None, 0)
    first = budget.run(argv)
    second = budget.run(argv)
    assert first.invocation_id != second.invocation_id
    stale = bd._collect_runner_result(first, argv, "neutral", "n", tmp_path)
    current = bd._collect_runner_result(second, argv, "neutral", "n", tmp_path)
    assert stale["runner_diagnostics"]["status"] == "INVOCATION_MISMATCH"
    assert current["reason"] == "REFUSED: NEUTRAL_INPUT: absent"


def test_a_missing_invocation_cannot_supply_report_evidence(tmp_path, monkeypatch):
    _report(tmp_path)
    monkeypatch.setattr(bio, "collect", lambda *a, **k: pytest.fail("missing invocation reached collection"))
    got = bd._collect_runner_result(bd._ProcessOutcome(0), _argv(tmp_path), "neutral", "n", tmp_path)
    assert got["ok"] is False
    assert got["runner_diagnostics"]["status"] == "INVOCATION_MISMATCH"


def test_timeout_retains_partial_streams_and_the_failed_invocation(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", "1")

    def producer(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 1, output=b"partial stdout\n", stderr=b"partial stderr\n")

    monkeypatch.setattr(bd.subprocess, "run", producer)
    process = bd._RunnerBudget(1, None, 0).run(_argv(tmp_path))
    assert process.rc is None
    assert "TimeoutExpired" in process.error
    receipt = json.loads(Path(process.receipt_path).read_text())
    assert receipt["stdout"] == process.stdout == "partial stdout\n"
    assert receipt["stderr"] == process.stderr == "partial stderr\n"
    assert receipt["error"] == process.error


def test_generic_budget_command_does_not_treat_its_argument_as_a_project(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('complete')\n")
    output = tmp_path / "receipt.txt"
    process = bd._RunnerBudget(1, None, 0).run([sys.executable, str(script), str(output)])
    assert process.rc == 0, process.stderr
    assert output.read_text() == "complete"


def test_d1_nonzero_handoff_uses_fresh_phase1_evidence_with_an_old_phase2_report(
        tmp_path, monkeypatch):
    import emit_attestation as ea
    prompt = tmp_path / "input" / "phase1_prompt.md"
    prompt.parent.mkdir()
    prompt.write_text("Describe a neutral digital block.\n")
    _report(tmp_path)
    emitted = []
    monkeypatch.setattr(ea, "phase1_provenance", lambda project:
                        {"ran": bool(emitted), "basis": "neutral fresh provenance"})

    def producer(argv, **kwargs):
        report = tmp_path / "reports" / "orchestrator" / "phase1_one_shot.json"
        from design_one_shot_runner import _write_phase2_report
        _write_phase2_report(report, {"status": "NOT_MEASURED", "handoff": "expert"}, tmp_path,
                             invocation_context=json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
        emitted.append(True)
        return subprocess.CompletedProcess(argv, 2, "Phase 1 expert handoff\n", "")

    monkeypatch.setattr(bd.subprocess, "run", producer)
    result = bd._ensure_phase1_frontdoor(Path(_argv(tmp_path)[1]), tmp_path,
                                        bd._RunnerBudget(1, None, 0))
    assert result["runner_rc"] == 2
    assert result["status"] == "GENERATED"
    assert result["provenance"]["ran"] is True
    assert result["runner_diagnostics"]["fresh_reports"] == ["phase1_one_shot.json"]


def test_regate_archives_the_actual_refusal_and_preserves_original(tmp_path, monkeypatch, capsys):
    import test_program_reentry as fx
    fx._rt_pair.assume_matching_runtime_pair(monkeypatch)
    # Only build the existing signed-input state; the test measures the runner
    # refusal, not an RTL proof or this host's simulator installation.
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *a, **k: {"status": "FAIL", "returncode": 1})
    run, task, signed, path, request = fx._stuck_request(tmp_path, monkeypatch)
    protected = fx._protected(run, task)
    real_run = subprocess.run

    def producer(argv, **kwargs):
        if "vibe_ic_one_shot_runner.py" in str(argv):
            return subprocess.CompletedProcess(argv, 2, "", "REFUSED: NEUTRAL_INPUT: absent\n")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(bd.subprocess, "run", producer)
    assert fx._resume(run, path) == 2
    assert fx._protected(run, task) == protected
    receipts = list(run.rglob("runner_result.json"))
    assert len(receipts) == 1
    record = json.loads(receipts[0].read_text())
    diagnostic = record.get("runner_diagnostics") or {}
    assert diagnostic.get("reason_class", "UNDISCLOSED") == "NEUTRAL_INPUT"
    assert diagnostic["project"].endswith("/staged_project")
    assert diagnostic["argv"] == record["argv"]
    assert "REFUSED: NEUTRAL_INPUT: absent" in capsys.readouterr().err

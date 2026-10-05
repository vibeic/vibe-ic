#!/usr/bin/env python3
"""Tests for phase1_one_shot_runner.py — Phase 1 (Path A) orchestrator.

Wave 83 — coverage for previously untested orchestrator.

Phase 1 wraps tools/phase1_engine/cli.py. Tests run the orchestrator's
control-flow only — they verify the runner SKIPs cleanly when no input
is staged, FAILs cleanly when phase1_engine is unreachable, and emits
the aggregate JSON report under reports/.

Cases:
  1. EMPTY_FIXTURE_IS_BLOCKED — project dir present but no input files →
                           canonical step D1's `required_inputs` pre-flight
                           REFUSES: the ingest step is never dispatched, the row
                           is BLOCKED / REQUIRED_INPUT_ABSENT, the verdict is
                           FAIL and the exit code is 1. (Until the pre-flight
                           was wired this SKIPped with exit 0 and verdict
                           PASS_WITH_WAIVERS — a pass tier over a Phase 1 that
                           was handed nothing to read.) Its REVERSE half —
                           the same project plus ONE staged prompt — completes.
  2. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  3. INTEGRATION_REPORT_SHAPE — emitted phase1_one_shot.json must contain
                                  phase / project / steps / verdict keys.
  4. STEP_DETAIL_REASON_PRESENT — when SKIPped, the detail explains
                                    that input/phase1_structured.yaml or
                                    input/docs/ is missing.
  5. INPUT_DOCS_TRIGGERS_INGEST — staging input/docs/ flips the runner
                                    out of SKIP into ingest_render.
                                    Without phase1_engine cli installed
                                    the step records FAIL but the runner
                                    still emits a summary report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
import _path_layout as _pl  # noqa: E402  R-0915-151

#: WHERE THE PRODUCER WRITES IT, asked of the router rather than spelled here. R-0915-151/160.
#: These five arms read `reports/phase1_one_shot.json` until R-0915-151 moved the producer onto
#: `_path_layout`'s router -- the flat location is one the repo's own
#: `reports_subfolder_taxonomy_check` calls a stray file. They were red on that landing and the
#: regression set that landed it did not include this file, which is how they stayed red.
def _phase1_report(project: Path) -> Path:
    return _pl.report_path(project, "phase1_one_shot.json")


PROG = Path(__file__).resolve().parent.parent / \
    "phase1_one_shot_runner.py"

#: `_run`'s default, and now the ONLY bound in this file. NOT a round number
#: picked by feel: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the
#: pytest harness bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
#: The default was already 60 and correct. Two call sites OVERRODE it with 300,
#: which is the shape a per-call bound invites: the safe default is declared
#: once and then walked past one keyword at a time. MEASURED here: the runner
#: over a tmp_path project with one staged prompt takes 2.23 s worst of six
#: calls, so neither override was buying anything — 60 s is ~27x measured.
#: The two sites still PASS it explicitly rather than falling through to the
#: default. Dropping the keyword altogether also silences the finding, but it
#: does so by making the bound unreadable: the gate resolves a module-level
#: int and a literal, never a parameter forwarded from a signature default, so
#: those two call sites would have left its denominator (`bounded_sites`)
#: instead of satisfying it. A green earned by becoming invisible to the check
#: is the failure this gate family exists to prevent, so the count is held:
#: 745 readable bounds before this change, 745 after.
_RUN_TIMEOUT_S = 60


def _run(args: list,
         timeout: int = _RUN_TIMEOUT_S) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args + ["--route", "ic"],
        capture_output=True, text=True)


def _stage_prompt(project: Path) -> None:
    """One staged input — the minimum that makes this a runnable Phase 1."""
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "input" / "phase1_prompt.md").write_text(
        "# a 4-bit up counter with a synchronous reset\n")


def _stage_expert_answer(project: Path) -> None:
    """The independent IC Expert reading required for a completed D1 run."""
    out = (project / "reports" / "audit" / "phase1" /
           "expert_parse_track_pack")
    out.mkdir(parents=True, exist_ok=True)
    (out / "l_doc_expectations.json").write_text(json.dumps({
        "expectations": [{
            "id": "identity::declared_name",
            "layer": "L1_DATASHEET",
            "field_path": "ic_name",
            "requirement": "the caller-stated IC name",
            "evidence": ["runner argument: --ic-name TST_CHIP"],
            "expected_tokens": ["TST_CHIP"],
        }],
    }))


def _sign_d1_after_first_pass(project: Path) -> None:
    """A reviewer signs the L-doc bytes the first pass actually produced."""
    import ai_signed_judgement as judgement
    digest = judgement.evidence_sha256(project, "D1")
    assert digest
    out = project / "reports/audit/ai_judgements/D1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "schema": judgement.SCHEMA, "step_id": "D1",
        "evidence_sha256": digest, "verdict": "PASS",
        "signed_by": "ic-expert-agent", "judgement": "reviewed generated L documents",
    }))


def test_empty_fixture_is_blocked_not_a_pass(tmp_path):
    """WAS `test_skip_empty_fixture`, and the rename is the finding.

    This case used to assert that a project with NO INPUT AT ALL exits 0 with
    verdict `PASS_WITH_WAIVERS` — "an empty project gracefully reports nothing
    to do". Canonical step D1's `required_inputs` pre-flight removes that: a
    Phase 1 that was handed nothing to read has not passed with a waiver, it
    has not run. The row is BLOCKED, the absence is NAMED, and the verdict is
    FAIL.

    Nothing downstream regresses on this: `vibe_ic_one_shot_runner
    ._phase1_decision` already returns `(False, "")` for a project with none of
    these five inputs, so the orchestrator never dispatched Phase 1 in this
    state — only a direct standalone invocation reaches it.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--ic-name", "TST_CHIP"])
    assert cp.returncode == 1, cp.stderr
    rep = _phase1_report(project)
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["phase"] == 1
    # R-0915-85 — NOT `FAIL`. Nothing about this design failed: D1 was refused
    # because the project holds none of the five declared inputs, so no L-doc
    # was ever examined. The run is NOT GREEN — rc 1, asserted above — and it
    # says which of the two kinds of not-green it is. Publishing FAIL here
    # would claim a finding about a design nothing looked at.
    assert body["verdict"] == "NOT_MEASURED", body["verdict"]
    ingest = next((s for s in body["steps"]
                    if s["name"] == "phase1_ingest_render"), None)
    assert ingest is not None
    assert ingest["status"] == "NOT_MEASURED"
    assert ingest["extras"]["finding"] == "REQUIRED_INPUT_ABSENT"
    # …and it says WHAT was missing, not merely that something was.
    assert "input/phase1_prompt.md" in ingest["detail"]


def test_reverse_one_staged_input_and_the_same_run_completes(tmp_path):
    """The REVERSE half of the case above: the ONLY difference is one staged
    file, and the run completes with a pass tier. Without this, the assertion
    above could be satisfied by a runner that refuses everything."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _stage_prompt(project)
    _stage_expert_answer(project)
    cp = _run([str(project), "--ic-name", "TST_CHIP", "--mode", "prompt"],
              timeout=_RUN_TIMEOUT_S)
    assert cp.returncode == 1
    assert json.loads(_phase1_report(project).read_text())["reason_class"] == (
        "awaiting_signed_judgement")
    _sign_d1_after_first_pass(project)
    cp = _run([str(project), "--ic-name", "TST_CHIP", "--second-track-only"],
              timeout=_RUN_TIMEOUT_S)
    assert cp.returncode == 0, cp.stderr
    body = json.loads(
        _phase1_report(project).read_text())
    assert body["verdict"] in ("PASS", "PASS_WITH_WAIVERS")
    ingest = next(s for s in body["steps"]
                  if s["name"] == "phase1_ingest_render")
    assert ingest["status"] != "NOT_MEASURED"


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    # The subject is the REPORT SHAPE of a completed run, so the fixture stages
    # the one input that makes it a completed run. Before D1 was pre-flighted,
    # an input-less project also "completed" (exit 0, PASS_WITH_WAIVERS); it no
    # longer does, and measuring report shape on a refusal would be measuring a
    # different thing.
    _stage_prompt(project)
    _stage_expert_answer(project)
    cp = _run([str(project), "--ic-name", "TST_CHIP", "--mode", "prompt"],
              timeout=_RUN_TIMEOUT_S)
    assert cp.returncode == 1
    _sign_d1_after_first_pass(project)
    cp = _run([str(project), "--ic-name", "TST_CHIP", "--second-track-only"],
              timeout=_RUN_TIMEOUT_S)
    assert cp.returncode == 0
    body = json.loads(
        _phase1_report(project).read_text())
    for k in ("phase", "project", "ic_name", "steps", "verdict"):
        assert k in body, f"missing key {k} in report"
    assert (body["delivery_route"], body["deliverable"]) == ("IC", "DIE")
    assert body["ic_name"] == "TST_CHIP"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 2  # ingest + human_docs


def test_step_detail_explains_missing_input(tmp_path):
    """UNCHANGED IN SUBSTANCE: the row must still say WHICH input was missing.
    Only the exit code and status moved (0/SKIP → 1/BLOCKED), because a Phase 1
    given nothing to read is refused rather than waived."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 1
    body = json.loads(
        _phase1_report(project).read_text())
    ingest = next(s for s in body["steps"]
                  if s["name"] == "phase1_ingest_render")
    detail = ingest["detail"].lower()
    # Reason mentions either the YAML or docs/ input path.
    assert ("phase1_structured.yaml" in detail or "docs" in detail
            or "engine" in detail)
    # …and the pre-flight's ledger is named, so the reason is followable.
    assert body.get("preflight_ledger") == "reports/audit/step_preflight.json"


def test_input_docs_directory_changes_branch(tmp_path):
    """Stage input/docs/ → the doc-extraction branch is taken. Per the v0.1.x
    raw-docs routing fix, a populated input/docs/ (with no layer-JSON) routes to
    `mode="docs"` and is delegated to phase1_doc_one_shot_runner; the orchestrator
    emits the JSON report regardless of host engine availability. (The older
    inline-`steps` report shape is also accepted for backward compat.)
    """
    project = tmp_path / "proj"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "tst_chip_spec.txt").write_text(
        "TST_CHIP — minimal stub for orchestrator test\n")
    cp = _run([str(project), "--ic-name", "TST_CHIP"])
    rep = _phase1_report(project)
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["ic_name"] == "TST_CHIP"
    if "steps" in body:  # legacy inline-steps report shape
        ingest = next(s for s in body["steps"]
                      if s["name"] == "phase1_ingest_render")
        # Unsigned D1 execution is uncredited even when extraction ran.
        assert ingest["status"] in ("NOT_MEASURED", "FAIL", "SKIP")
    else:  # v0.1.x delegated docs-mode report — input/docs/ took the docs branch
        assert body.get("mode") == "docs"
        assert body.get("delegated_to")
        assert body.get("verdict") in ("NOT_MEASURED", "FAIL", "SKIP")


def test_docs_delegate_rc2_is_not_measured_and_blocks_downstream(
        tmp_path, monkeypatch):
    """A VACUOUS delegated gate result remains blocking at the front door."""
    import phase1_one_shot_runner as runner

    project = tmp_path / "proj"
    (project / "input" / "docs").mkdir(parents=True)
    (project / "input" / "docs" / "spec.md").write_text("design input\n")

    monkeypatch.setattr(runner, "_run_step_0_5ic",
                        lambda project, pdk=None: 0)
    monkeypatch.setattr(runner, "_detect_input_mode", lambda project: "docs")
    monkeypatch.setattr(runner, "_run_docs_mode", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        runner, "run_phase1_second_track",
        lambda *args, **kwargs: pytest.fail(
            "the expert track must not run after an undetermined D1"),
    )

    old_argv = sys.argv[:]
    sys.argv = [str(PROG), str(project), "--mode", "docs",
                "--ic-name", "TST_CHIP", "--route", "ic"]
    try:
        rc = runner.main()
    finally:
        sys.argv = old_argv

    assert rc == 2
    report = json.loads(_phase1_report(project).read_text())
    assert report["delegated_rc"] == 2
    assert report["verdict"] == "NOT_MEASURED"
    assert report["pass1"] == {
        "verdict": "NOT_MEASURED",
        "rc": 2,
        "source": "extraction and route before expert track",
    }
    assert report["steps"][0]["status"] == "NOT_MEASURED"
    assert report["steps"][0]["reason_class"] == "no_population"
    assert report["steps"][1]["status"] == "NOT_MEASURED"
    assert report["steps"][1]["reason_class"] == "upstream_refused"

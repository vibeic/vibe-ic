#!/usr/bin/env python3
"""#544 — a DECLARED sign-off gate that returned no verdict must not release.

THE OBSERVED DEFECT. A phase-3 run reported `PASS_WITH_WAIVERS` while carrying
-72.07 ns of setup violation at the slow sign-off corner, on a real routed DEF
with a real max-RC SPEF, DRC 0 and LVS matching uniquely. Five declared sign-off
gates reported SKIP with `gate program not present` —
`post_route_signoff_corner_check` among them, the gate whose entire job is to
FAIL on a negative sign-off corner — and `_aggregate_verdict` folds SKIP into
`PASS_WITH_WAIVERS`. The run looked clean because the only gate that would have
disagreed had not spoken.

TWO WAYS IN, TESTED SEPARATELY, because a fix aimed at the observed symptom
misses the second:

  1. `test_absent_gate_program_*` — the program file is not found. The observed
     trigger (a `PROGRAMS_DIR` derived from a `__file__` in a worktree deleted
     mid-run) was environmental and is NOT the defect; the defect is that the
     code could not tell it from "this gate is not part of this deployment" and
     carried on either way. Reproduced here by pointing `PROGRAMS_DIR` at a
     COMPLETE deployment minus exactly one gate, over a project whose sign-off
     corner is genuinely negative.

  2. `test_rc2_*` — the gate exits 2, this repo's canonical NOT-CHECKED code
     (`_vacuous_exit.RC_VACUOUS`, enforced across the gate population by #528).
     This path needs NO broken environment: it is reachable by any sign-off gate
     that hits an input it cannot read, and by an argparse rejection, and it is
     driven here through the REAL, COMPLETE `PROGRAMS_DIR` with nothing patched.

THE CLEAN CASE IS MEASURED, NOT ASSERTED (`test_a_complete_deployment_*`): the
same fixture with every gate present and passing must still reach `PASS`, and
must produce a roll-up whose `not_checked` list is empty. A change that turned
every incomplete checkout into a hard failure would get worked around, and a
worked-around gate is worse than the hole.

INNER TIMEOUTS (#542). Every gate driven here is a pure report reader — none of
the five contains a `subprocess`, `docker` or `shutil.which` call — and returns
in well under a second. `_INNER_TIMEOUT_S` is far below CI's `--timeout=180`
harness bound, so a hang fails THIS test instead of killing the subset.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))

import ci_harness_timeout_ceiling_check as ceiling_check   # noqa: E402

_CEILING_REPO_ROOT = ceiling_check.find_repo_root()

#: CI's per-test harness bound, READ from the workflows (vibe-ic#542). The
#: landed version of this line was `= 180`, a second copy of a value this file
#: cannot see, and it was the wrong shape twice over: the repo declares FOUR
#: pytest bounds across two workflows and they do not agree, so the binding one
#: is the minimum. None when no workflow is reachable — the guard below then
#: SKIPs rather than fall back to a remembered number.
_CI_HARNESS_TIMEOUT_S = (
    ceiling_check.ci_harness_timeout_seconds(_CEILING_REPO_ROOT)
    if _CEILING_REPO_ROOT else None)

#: Inner subprocess bound. MUST stay below CI's harness bound (#542): a test
#: whose own timeout is at or above it cannot fail as a test — pytest kills the
#: whole targeted subset first and every other file's result is lost.
_INNER_TIMEOUT_S = 60

#: What `phase3_one_shot_runner.main` exits 0 on. A sign-off that was not
#: performed must not produce any of these.
_RELEASING = ("PASS", "PASS_WITH_WAIVERS", "PASS_WITH_OPEN_SOURCE_CONSTRAINTS")

# Padding to clear eda_report_audit's MIN_REPORT_BYTES anti-fabrication floor.
_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB

_STA_RPT = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n"
    "slack (MET)\nsetup check: PASS\nhold check: PASS\n"
    "data arrival time: 2.34 ns\n" + _PAD
)

#: The same report with THIS STEP'S OWN path violated. Needed since step 23's
#: `sta_report_check` became step-scoped (`--under
#: phase3/stage3/sta/post_route_timing.rpt`): before that it discovered
#: project-wide and so failed on the multi-corner report below, which belongs
#: to the corner gates, not to it. A fixture that wants `sta_signoff` to FAIL
#: must now violate the artefact `sta_signoff` actually reads.
_STA_RPT_VIOLATED = _STA_RPT.replace(
    "WNS = 0.15 ns\nTNS = 0.0 ns\nslack (MET)\nsetup check: PASS",
    "WNS = -3.28 ns\nTNS = -91.4 ns\nslack (VIOLATED)\nsetup check: FAIL")

_EM_RPT = (
    "OpenROAD Electromigration Analysis\n"
    "EM lifetime: 10 years worst-case\n"
    "Javg = 2.5 mA/um  current density\n"
    "Jpeak = 8.1 mA/um  peak current\n"
    "RMS current: 3.2 mA/um\n" + _PAD
)

#: The shape #544 was reported against: nominal clean, sign-off corner deeply
#: violated. The number is the one the field run carried.
_MULTICORNER_VIOLATED = (
    "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
    "# SETUP corner: max-RC   HOLD corner: min-RC\n"
    "=== SETUP (max-RC corner, SPEF=max) ===\n"
    "worst slack max -72.07\n"
    "=== HOLD (min-RC corner, SPEF=min) ===\n"
    "worst slack min 0.54\n"
)


@pytest.fixture()
def runner():
    import phase3_one_shot_runner as R  # noqa: WPS433
    return R


def _project(tmp: Path, *, violated_corner: bool = False,
             violated_own_report: bool = False) -> Path:
    """A minimal but tool-authentic post-route project.

    `violated_corner` violates the MULTI-CORNER report — the artefact
    `post_route_signoff_corner_check` and `sta_corner_record_completeness_check`
    read. `violated_own_report` violates step 23's OWN declared report, which
    since the step-scoping change is the only artefact `sta_report_check`
    reads. They are separate flags because they are separate defects, and
    conflating them is what let a pre-layout gate be failed by a post-ECO file.
    """
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        _STA_RPT_VIOLATED if violated_own_report else _STA_RPT)
    if violated_corner:
        (sta / "sta_spef_multicorner.rpt").write_text(_MULTICORNER_VIOLATED)
    rpt = tmp / "reports" / "phase3"
    rpt.mkdir(parents=True)
    (rpt / "em.rpt").write_text(_EM_RPT)
    return tmp


def _deployment(tmp: Path, omit: "tuple[str, ...]" = ()) -> Path:
    """A programs directory that is COMPLETE except for the names in `omit`.

    Symlinked rather than copied so the deployment is the real one — the gates
    that ARE present are byte-for-byte the shipped programs and import their
    own siblings normally. This is the deleted-worktree shape: everything in
    place, some declared gates unreachable.
    """
    dest = tmp / "deployment_programs"
    dest.mkdir()
    for entry in _PROGRAMS.iterdir():
        if entry.name in omit or entry.name == "tests":
            continue
        (dest / entry.name).symlink_to(entry)
    for name in omit:
        assert not (dest / name).exists(), name
        assert (_PROGRAMS / name).is_file(), (
            f"{name} is not a shipped program — the omission proves nothing")
    return dest


#: The three declared sign-off gates that read the STA reports. In the field
#: report all of these, plus #306's, went missing together: one deployment
#: fault, five gates.
_STA_SIGNOFF_PROGRAMS = ("sta_report_check.py",
                         "post_route_signoff_corner_check.py",
                         "sta_corner_record_completeness_check.py")


def _all_signoff_steps(runner, project: Path):
    """Every declared sign-off gate the runner plans, in plan order."""
    return ([runner.step_drv_promotion_corroboration(project)]
            + runner.step_declared_signoff_gates(project))


# ===========================================================================
# (1) THE OBSERVED REPRODUCTION — an absent program over a negative corner
# ===========================================================================
def test_absent_gate_programs_do_not_release_a_negative_signoff_corner(
        tmp_path, runner, monkeypatch):
    """THE FIELD CASE, CONSTRUCTED. A project whose sign-off corner is really at
    -72.07 ns, and the gates that read the STA reports are not in the
    deployment — the shape the report describes, where one deleted worktree
    took out every STA sign-off gate at once.

    PRE-FIX: three `SKIP`s and one `PASS`, and `_aggregate_verdict` answered
    `PASS_WITH_WAIVERS` — a releasing verdict over an unexamined -72.07 ns.

    The surviving gate (`em_signoff`) is what makes this decisive rather than
    circular: something DID pass, so the run is non-releasing only because the
    absent gates are non-releasing.
    """
    proj = _project(tmp_path / "proj", violated_corner=True)
    monkeypatch.setattr(runner, "PROGRAMS_DIR",
                        _deployment(tmp_path, omit=_STA_SIGNOFF_PROGRAMS))

    results = {r.name: r for r in runner.step_declared_signoff_gates(proj)}

    corner = results["sta_corner"]
    assert corner.status == "BLOCKED", (
        "the gate that FAILs on a negative sign-off corner was absent and the "
        "runner recorded it as neutral", corner)
    assert runner._SIGNOFF_NOT_CHECKED in corner.detail, corner.detail
    assert "post_route_signoff_corner_check.py" in corner.detail, corner.detail
    assert [results[n].status for n in ("sta_signoff", "sta_record")] == \
        ["BLOCKED"] * 2, results
    assert results["em_signoff"].status == "PASS", results["em_signoff"]

    verdict = runner._aggregate_verdict(list(results.values()))
    assert verdict not in _RELEASING, (
        f"a PASS beside three sign-off gates that never ran released the run "
        f"as {verdict!r}, over -72.07 ns nobody looked at")


def test_a_single_absent_declared_gate_withholds_the_release(
        tmp_path, runner, monkeypatch):
    """Absence ALONE is enough, with no violation anywhere to help.

    An otherwise-clean project, a deployment complete except for one declared
    sign-off gate: the other three genuinely PASS and the run still must not
    release. This is the sharp form — pre-fix it was `PASS_WITH_WAIVERS`, and
    nothing about the design was wrong; what was wrong was that the flow named
    a sign-off gate and no verdict came back.
    """
    proj = _project(tmp_path / "proj")
    monkeypatch.setattr(
        runner, "PROGRAMS_DIR",
        _deployment(tmp_path, omit=("post_route_signoff_corner_check.py",)))
    results = {r.name: r for r in runner.step_declared_signoff_gates(proj)}

    assert results["sta_corner"].status == "BLOCKED", results["sta_corner"]
    assert [results[n].status for n in ("sta_signoff", "sta_record",
                                        "em_signoff")] == ["PASS"] * 3, results
    assert not any(r.status == "FAIL" for r in results.values()), (
        "no gate found a design defect, so the verdict below is about the "
        "absence and nothing else", results)
    assert runner._aggregate_verdict(list(results.values())) not in _RELEASING


def test_the_absent_gates_are_the_only_reason_the_run_did_not_release(
        tmp_path, runner, monkeypatch):
    """The control on the reproduction: with the SAME project and a COMPLETE
    deployment, the run is red for the RIGHT reason — the corner really is at
    -72.07 ns — rather than because the fixture is broken in some other way.

    It also records something the reproduction alone would hide: the corner
    gates independently detect this corner, because they read the same
    multi-corner report. The field case was expensive precisely because the
    deployment fault removed all of them at once.

    CORRECTED with the step-scoping change: `sta_report_check` used to be a
    THIRD independent detector here, but only by discovering project-wide —
    it was reading the corner gates' artefact, not its own. That is the same
    mechanism that let step 10's PRE-LAYOUT gate be failed by step 32's
    post-ECO report, so the redundancy was never real coverage. The corner
    detection asserted below is unchanged; only the count of accidental
    detectors is.
    """
    proj = _project(tmp_path / "proj", violated_corner=True)
    monkeypatch.setattr(runner, "PROGRAMS_DIR", _deployment(tmp_path))
    results = {r.name: r for r in runner.step_declared_signoff_gates(proj)}
    corner = results["sta_corner"]
    assert corner.status == "FAIL", corner
    assert "-72.07" in corner.detail, corner.detail
    assert not any(r.status == "BLOCKED" for r in results.values()), results


def test_absent_gate_program_blocks_the_drv_promotion_step_too(
        tmp_path, runner, monkeypatch):
    """#306's gate is the fifth of the five that vanished in the field report.
    It runs through the same helper, so it cannot drift from the other four."""
    proj = _project(tmp_path / "proj")
    monkeypatch.setattr(
        runner, "PROGRAMS_DIR",
        _deployment(tmp_path, omit=("drv_promotion_corroboration_check.py",)))
    r = runner.step_drv_promotion_corroboration(proj)
    assert r.status == "BLOCKED", r
    assert runner._aggregate_verdict([r]) not in _RELEASING, r


# ===========================================================================
# (2) THE PATH THAT NEEDS NO BROKEN ENVIRONMENT — rc 2
# ===========================================================================
def test_rc2_from_a_declared_signoff_gate_does_not_release(tmp_path, runner):
    """rc 2 is this repo's canonical NOT-CHECKED code. A declared sign-off gate
    that correctly reports "I could not check this" was recorded as
    no-information and the sign-off passed.

    Driven through the REAL `PROGRAMS_DIR` with the REAL gate and nothing
    patched — this needs no broken deployment at all, which is why a fix aimed
    only at the observed symptom would leave it open.
    """
    proj = _project(tmp_path)
    r = runner._run_declared_signoff_gate(
        proj, "sta_signoff", "sta_report_check.py",
        "reports/phase3/sta/post_route_summary.json", ("--mode", "bogus"),
        timeout=_INNER_TIMEOUT_S)
    assert r.status == "BLOCKED", r
    assert "rc=2" in r.detail, r.detail
    assert runner._aggregate_verdict([r]) not in _RELEASING, r


def test_rc2_stays_distinct_from_a_design_failure(tmp_path, runner):
    """Non-releasing is not the same as "the design is bad". The BLOCKED tier
    keeps the distinction where triage reads it — the step's own status — which
    is what stops this fix from being a blunt "call everything a FAIL"."""
    proj = _project(tmp_path)
    r = runner._run_declared_signoff_gate(
        proj, "sta_signoff", "sta_report_check.py",
        "reports/phase3/sta/post_route_summary.json", ("--mode", "bogus"),
        timeout=_INNER_TIMEOUT_S)
    assert r.status != "FAIL", (
        "a checker fault was recorded as a verdict about the design", r)
    assert r.status in runner._VERDICT_TIERS, (
        "the status is not in the module's declared verdict vocabulary", r)


@pytest.mark.parametrize("rc", [2, 3, 70])
def test_every_non_verdict_exit_code_is_non_releasing(tmp_path, runner,
                                                      monkeypatch, rc):
    """Only 0 and 1 are verdicts. A stub gate that exits with anything else —
    including a code no gate uses today — must not be able to buy a release.

    The stub also covers the "genuine input-missing rc 2" flavour that
    `_gate_invocation` separates from an argparse rejection: it writes no
    `usage:` block, so it is classified as the gate's own NOT-CHECKED, not as a
    caller defect. Both are non-verdicts and both must block.
    """
    proj = _project(tmp_path / "proj")
    dep = _deployment(tmp_path)
    stub = dep / "stub_signoff_gate.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"print('could not read the sign-off report')\n"
        f"sys.exit({rc})\n")
    monkeypatch.setattr(runner, "PROGRAMS_DIR", dep)
    r = runner._run_declared_signoff_gate(
        proj, "sta_corner", "stub_signoff_gate.py",
        "reports/phase3/sta/post_route_signoff_corner.json",
        timeout=_INNER_TIMEOUT_S)
    assert r.status == "BLOCKED", (rc, r)
    assert f"rc={rc}" in r.detail, r.detail
    assert runner._aggregate_verdict([r]) not in _RELEASING, (rc, r)


def test_an_rc2_argparse_rejection_says_it_was_never_validly_invoked(
        tmp_path, runner):
    """rc 2 carries two meanings and the detail must say which. #492 already
    built the classifier; reusing it is what makes the line actionable instead
    of a bare number."""
    proj = _project(tmp_path)
    r = runner._run_declared_signoff_gate(
        proj, "sta_signoff", "sta_report_check.py",
        "reports/phase3/sta/post_route_summary.json", ("--mode", "bogus"),
        timeout=_INNER_TIMEOUT_S)
    assert "never validly invoked" in r.detail, r.detail
    assert "invalid choice" in r.detail, r.detail


# ===========================================================================
# (3) THE CLEAN CASE — measured, not asserted
# ===========================================================================
def test_a_complete_deployment_with_every_gate_passing_still_releases(
        tmp_path, runner):
    """The control that keeps this fix usable. Nothing patched, every declared
    gate present, a project each of them passes: still PASS."""
    proj = _project(tmp_path)
    results = _all_signoff_steps(runner, proj)
    assert [r.status for r in results] == ["PASS"] * 5, [
        (r.name, r.status, r.detail[:120]) for r in results]
    assert runner._aggregate_verdict(results) == "PASS", results

    rollup = runner.declared_signoff_rollup(results)
    assert rollup["declared"] == 5, rollup
    assert rollup["not_checked"] == [], rollup
    assert rollup["failed"] == [], rollup
    assert rollup["line"] == "5 of 5 declared sign-off gate(s) PASSED", rollup


def test_a_clean_project_still_writes_every_declared_verdict_json(tmp_path,
                                                                  runner):
    """The gates did not merely return PASS — they produced the sign-off
    outputs the flow declares. A fix that made them return early would satisfy
    the status assertion above and deliver nothing."""
    proj = _project(tmp_path)
    _all_signoff_steps(runner, proj)
    for rel in ("reports/phase3/sta/drv_promotion_corroboration.json",
                "reports/phase3/sta/post_route_summary.json",
                "reports/phase3/sta/post_route_signoff_corner.json",
                "reports/phase3/sta/sta_corner_record_completeness.json",
                "reports/phase3/em_signoff.json"):
        assert (proj / rel).is_file(), f"{rel} was not written"


def test_a_real_finding_is_still_a_fail_not_a_block(tmp_path, runner):
    """The other side of the clean control: a gate that RAN and found a real
    violation must still be FAIL. Collapsing FAIL into BLOCKED would lose the
    only distinction this fix is careful to keep."""
    proj = _project(tmp_path, violated_corner=True)
    results = {r.name: r for r in runner.step_declared_signoff_gates(proj)}
    assert results["sta_corner"].status == "FAIL", results["sta_corner"]
    assert runner._aggregate_verdict(list(results.values())) == "FAIL"


# ===========================================================================
# (4) THE HONEST ROLL-UP (#538's shape)
# ===========================================================================
def test_the_rollup_names_what_was_not_checked(tmp_path, runner, monkeypatch):
    """`_aggregate_verdict` is one word over the whole plan and is silent about
    how much of the sign-off was performed. #538's precedent is to state the
    denominator; without it, four PASSes and one gate that never ran read
    identically to five PASSes."""
    proj = _project(tmp_path / "proj")
    monkeypatch.setattr(
        runner, "PROGRAMS_DIR",
        _deployment(tmp_path, omit=("post_route_signoff_corner_check.py",)))
    rollup = runner.declared_signoff_rollup(
        runner.step_declared_signoff_gates(proj))
    assert rollup["not_checked"] == ["sta_corner"], rollup
    assert rollup["declared"] == 4, rollup
    assert rollup["line"] == (
        "3 of 4 declared sign-off gate(s) PASSED; "
        "1 NOT CHECKED (not a pass): sta_corner"), rollup["line"]


def test_the_rollup_names_a_failing_gate_apart_from_an_unchecked_one(
        tmp_path, runner, monkeypatch):
    """"3 of 4 passed" is not enough on its own: a reader must be able to tell
    a gate that found a violation from one that never spoke. #538's line keeps
    them in separate clauses and so does this one.

    `violated_own_report=True` is what makes `sta_signoff` one of the two
    failures now that it is step-scoped. Before scoping this fixture got the
    same two failures for free — because `sta_signoff` was reading the corner
    gates' multi-corner report rather than its own declared artefact.
    """
    proj = _project(tmp_path / "proj", violated_corner=True,
                    violated_own_report=True)
    monkeypatch.setattr(
        runner, "PROGRAMS_DIR",
        _deployment(tmp_path, omit=("post_route_signoff_corner_check.py",)))
    rollup = runner.declared_signoff_rollup(
        runner.step_declared_signoff_gates(proj))
    assert rollup["not_checked"] == ["sta_corner"], rollup
    assert rollup["failed"] == ["sta_signoff", "sta_record"], rollup
    assert "FAILED: sta_signoff, sta_record" in rollup["line"], rollup["line"]
    assert "NOT CHECKED (not a pass): sta_corner" in rollup["line"], \
        rollup["line"]


def test_the_rollup_uses_the_repo_wide_not_checked_wording(runner):
    """One wording, not a fifth spelling. `gatekeeper_review._hygiene_verdict`
    prints this exact phrase for the CI hygiene set (#538)."""
    import gatekeeper_review  # noqa: WPS433
    assert runner._SIGNOFF_NOT_CHECKED == "NOT CHECKED (not a pass)"
    assert runner._SIGNOFF_NOT_CHECKED in (
        Path(gatekeeper_review.__file__).read_text(errors="replace")), (
        "the phrase this roll-up reuses is no longer the one #538 established")


def test_the_rollup_is_published_beside_the_headline_verdict():
    """A roll-up nobody emits is a function, not a disclosure. It must land in
    the summary document the run publishes and on the console."""
    src = _RUNNER_SRC.read_text(errors="replace")
    assert '"declared_signoff_gates": signoff_rollup' in src, (
        "the sign-off denominator is computed but never written to "
        "reports/orchestrator/phase3_one_shot.json")
    assert 'print(f"sign-off: {signoff_rollup[\'line\']}")' in src, (
        "the sign-off denominator is never printed beside the verdict")


def test_the_rollup_describes_only_the_steps_the_plan_carries(runner):
    """A run that did not reach the sign-off steps must be described by a
    smaller denominator, never by invented rows."""
    assert runner.declared_signoff_rollup([])["declared"] == 0
    partial = [runner.StepResult("sta_signoff", "PASS")]
    assert runner.declared_signoff_rollup(partial)["declared"] == 1


# ===========================================================================
# (5) DRIFT GUARDS — the properties that must not quietly come back
# ===========================================================================
def test_no_declared_signoff_gate_outcome_routes_to_skip():
    """The defect was a status literal, so the guard is on the status literal.

    Every non-verdict exit of `_run_declared_signoff_gate` must go through
    `_signoff_not_checked`; a re-introduced `"SKIP"` anywhere in that function
    is the whole bug back.
    """
    import ast
    tree = ast.parse(_RUNNER_SRC.read_text(errors="replace"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_run_declared_signoff_gate")
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "SKIP" not in literals, (
        "a declared sign-off gate outcome routes to SKIP again — SKIP is "
        "neutral in _aggregate_verdict, which is #544")
    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_signoff_not_checked" in calls, (
        "the shared non-verdict helper is no longer used")


def test_the_status_this_fix_returns_is_non_green_in_the_aggregate(runner):
    """The load-bearing coupling, driven rather than read: `BLOCKED` is only
    worth returning because `_aggregate_verdict` refuses to release on it. An
    edit that moved BLOCKED into the green bucket would silently reopen #544
    while every status assertion above still passed."""
    blocked = runner.StepResult("sta_corner", "BLOCKED", 0.0, "x")
    assert runner._aggregate_verdict([blocked]) not in _RELEASING
    assert runner._aggregate_verdict(
        [runner.StepResult("sta_signoff", "PASS"), blocked]) not in _RELEASING


def test_both_signoff_gate_tables_run_through_one_implementation():
    """#306's gate and the step-23/25 four had two copies of "what does an
    absent program mean", and they had already drifted: the #306 copy created
    the project directory it was asked to audit. One implementation is what
    stops that recurring."""
    src = _RUNNER_SRC.read_text(errors="replace")
    assert "return _run_declared_signoff_gate(project, *_DRV_PROMOTION_GATE" \
        in src, "step_drv_promotion_corroboration forked its own gate runner again"
    assert src.count("def _run_declared_signoff_gate(") == 1


def test_every_declared_signoff_step_name_is_covered_by_the_rollup(runner):
    """A gate added to either table without being named in the roll-up would be
    invisible in the denominator — the #538 shape in miniature."""
    planned = ((runner._DRV_PROMOTION_GATE[0],)
               + tuple(g[0] for g in runner._DECLARED_SIGNOFF_GATES))
    assert set(planned) == set(runner.DECLARED_SIGNOFF_STEP_NAMES), (
        planned, runner.DECLARED_SIGNOFF_STEP_NAMES)


def test_absence_is_not_offered_as_an_inapplicability_opt_out():
    """The judgement this issue turns on, pinned. A legitimate "this gate does
    not apply" case EXISTS — but it has two declared homes, the flow yaml's
    `condition: files_exist:` and the gate's own rc-0 NOT_APPLICABLE
    self-report, and neither is file presence. No third surface may appear
    here: `signoff_ladder_run.TierResult.release_gating` is set in code
    "never from a design artifact, so no project can opt its own gates out",
    and a per-entry opt-out column that only ever reads True is a back door.
    """
    import phase3_one_shot_runner as R  # noqa: WPS433
    for entry in R._DECLARED_SIGNOFF_GATES + (R._DRV_PROMOTION_GATE,):
        assert len(entry) == 4, (
            "a declared sign-off gate grew a fifth column — if it is an "
            "opt-out, re-read #544's reasoning before adding it", entry)
        assert not any(isinstance(v, bool) for v in entry), entry


def test_the_five_declared_signoff_gates_need_no_external_tool():
    """The evidence behind "no ENV_UNAVAILABLE case arises for these gates",
    which is why absence gets no reviewed-waiver path here. If one of them ever
    starts shelling out, that conclusion has to be revisited and this test is
    where the revisiting is triggered."""
    import phase3_one_shot_runner as R  # noqa: WPS433
    for entry in R._DECLARED_SIGNOFF_GATES + (R._DRV_PROMOTION_GATE,):
        src = (_PROGRAMS / entry[1]).read_text(errors="replace")
        for token in ("subprocess", "docker", "shutil.which"):
            assert token not in src, (
                f"{entry[1]} now depends on an external tool ({token}); the "
                f"reasoning that no ENV_UNAVAILABLE waiver path is needed for "
                f"these gates no longer holds")


def test_the_blast_radius_is_recorded_where_the_change_is():
    """The repo's rule for a gate wired blocking (#306): the measured blast
    radius belongs beside the wiring."""
    prose = " ".join(_RUNNER_SRC.read_text(errors="replace")
                     .replace("#", " ").split())
    assert "70 invocations, 47 rc 0 and 23 rc 1" in prose, (
        "the corpus measurement behind this change is not recorded")
    assert "-72.07 ns" in prose, (
        "the concrete finding that justified the change is not recorded")


def test_inner_subprocess_bounds_stay_under_the_ci_harness_bound():
    """#542 — a test whose own subprocess timeout is at or above CI's harness
    bound cannot fail as a test; it kills the whole subset.

    Parsed by the SHARED scanner rather than an inline walk: the bound and the
    parse now have one implementation each, and this file inherits the two
    shapes an inline copy did not have (a bound spelled as a module constant,
    and a wrapper that splats `**kwargs` into a launcher)."""
    if _CI_HARNESS_TIMEOUT_S is None:
        pytest.skip("no .github/workflows in reach — the harness bound cannot "
                    "be resolved, and a remembered copy of it is the defect")
    ceiling = _CI_HARNESS_TIMEOUT_S // ceiling_check.CEILING_DIVISOR
    assert _INNER_TIMEOUT_S <= ceiling
    findings, unresolved, sites = ceiling_check.scan_source(
        Path(__file__).read_text(errors="replace"), Path(__file__).name,
        ceiling)
    assert sites, "no bound was READ at all — has the scan stopped working?"
    assert not findings and not unresolved, "\n  ".join(
        str(x) for x in list(findings) + list(unresolved))


def test_the_gates_this_file_drives_finish_well_inside_that_bound(tmp_path,
                                                                 runner):
    """The bound is only honest if it is generous. Measure the slowest thing
    this file asks for — all five gates on a real fixture — rather than
    assuming."""
    import time
    proj = _project(tmp_path)
    t0 = time.time()
    _all_signoff_steps(runner, proj)
    elapsed = time.time() - t0
    assert elapsed < _INNER_TIMEOUT_S / 2, (
        f"five declared sign-off gates took {elapsed:.1f}s; the inner bound "
        f"of {_INNER_TIMEOUT_S}s is no longer generous")

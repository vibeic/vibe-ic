#!/usr/bin/env python3
"""Step 37.5ic's merged gate — OUR ladder always, the OPERATOR's when there is one.

WHAT THIS FILE PINS
-------------------
T1  OUR arm runs on a project with NO operator template. That is the whole
    point of retiring step `37.5self`: the general ladder is not a route a
    design can miss, it is an arm every design that reaches 37.5ic gets.
T2  A PDK the registry names NO live shuttle for is ONE FEWER ARM, not a
    failure and not a different route — and the absence is a written line with
    an authority on it, never a silence.
T3  Registry-says-yes-and-nothing-was-fetched is NOT_DETERMINED and REFUSES.
    "We did not go and get it" must not produce the artefact of "we got it and
    it passed" — which is exactly what a silent skip would produce.
T4  BOTH arms run when the PDK ships a precheck and its template was fetched,
    and a FORCED DISAGREEMENT between the two authorities FAILS the step. The
    disagreement is a finding of its own; it is never resolved by preferring an
    arm.
T5  The disagreement detector DISCRIMINATES: agreement is not reported as
    disagreement, and a NOT_DETERMINED on one side is an ABSENCE rather than a
    disagreement. A detector that fires on everything proves as little as one
    that fires on nothing.
T6  EVERY finding names the authority that produced it, and carries a boolean
    saying whether that authority is ours — because the value of the operator's
    arm is precisely that its verdict is not one we wrote.
T7  The operator arm's artefact EXISTS on every path, including the paths where
    the operator was never asked, and on those paths it says so under OUR name.
    An absent file and a "nobody asked" file are read identically by everything
    downstream, and that is the defect this step was rebuilt to close.
T8  The registry answers "does this PDK ship a shuttle precheck", a RETIRED
    counterparty is not an answer of yes, and it is still NAMED.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _submission_template as ST         # noqa: E402
import _tapeout_declaration as TD          # noqa: E402
import general_precheck as GP              # noqa: E402
import tapeout_precheck as TP              # noqa: E402
import _watchdog                           # noqa: E402


def _supervised_runner(cmd, timeout=None):
    """A `tapeout_precheck.Runner` that bounds NO PROGRESS instead of runtime.

    `TP.default_runner` launches each arm under `subprocess.run(..., timeout=N)`
    and maps a `TimeoutExpired` onto rc 124, which `_run_arm` then reports as the
    arm having FAILED. So the wall-clock budget is not a guard here — it is a
    verdict generator: exceed it because the host is busy and the merged report
    records the precheck as broken, indistinguishably from the precheck really
    being broken. The number cannot tell those apart, because "how long has it
    been" is a different question from "is it working".

    Every launch in this module therefore goes through progress supervision
    (CPU + I/O over the child's /proc tree, plus the growth of its captured
    output). `timeout` is accepted and IGNORED so the Runner signature — and
    `TP.main`'s `--timeout` path, which cannot be handed a runner — keep
    working; a genuinely hung arm is still killed, arriving as rc
    `_watchdog.RC_STALLED`, which is not 124 and not any rc an arm produces."""
    res = _watchdog.run_host_supervised(list(cmd))
    return res.rc, res.out, res.err


@pytest.fixture(autouse=True)
def _no_wall_clock_verdicts(monkeypatch):
    """Every arm launch in this module is supervised, including the ones this
    file cannot pass a `runner=` to (`TP.main`, and the `TP.default_runner`
    delegation inside `_mirror_operator`). Patching the module seam rather than
    each call site is what makes that complete."""
    monkeypatch.setattr(TP, "default_runner", _supervised_runner)
import tapeout_readiness_check as TRC      # noqa: E402

# The GDSII writer is REAL BYTES, and it is the one the general-precheck tests
# already use. Re-encoding it here would be a second encoder to keep in step.
from test_general_precheck import (        # noqa: E402
    _die_at_origin, _die_off_origin_via_children)


# --------------------------------------------------------------------------- #
# Fixtures — a project, and a stand-in for the counterparty's container
# --------------------------------------------------------------------------- #
def _project(tmp_path: Path, gds_maker, answers: dict, *,
             pdk: str, slots: bool) -> Path:
    """A chip-path project, with or without the operator's slot template.

    `pdk` is written where the tree's own accessor reads it
    (`declared_pdk_is_the_pdk_used_check.declared_target` probes
    `input/project.json`), so this fixture does not invent a second channel for
    a fact the flow already records.
    """
    proj = tmp_path / "proj"
    gds_maker(proj / "phase3" / "stage4" / "gds" / "chip_top.gds")
    doc, ignored = TD.merge_answers(TD.blank_declaration(), answers)
    assert not ignored, f"test wrote an unknown answer key: {ignored}"
    p = proj / TD.DECLARATION_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))

    (proj / "input").mkdir(parents=True, exist_ok=True)
    (proj / "input" / "project.json").write_text(json.dumps({"pdk": pdk}))

    if slots:
        slot = proj / "input" / "submission_template" / "slots" / "1x1.yaml"
        slot.parent.mkdir(parents=True, exist_ok=True)
        slot.write_text("DIE_AREA: [0, 0, 100.0, 80.0]\n")
        # AND THE DESIGN DECLARES WHICH SLOT IT BOUGHT. Staging a template is
        # the OPERATOR's half; it does not choose for the design. Before
        # 2026-09-04 a sole slot file was read as the design's choice, so these
        # fixtures never had to say — and a design that never chose would have
        # been silently moved the moment the operator listed a second slot.
        # `submission_template_ingest` states the rule for the whole step: the
        # slot is "the slot this design DECLARES it targets. Never guessed and
        # never defaulted."
        # AND THE DESIGN DECLARES WHICH SLOT IT BOUGHT, in the flow's own
        # home for that fact: `operator_template.slot` in the step-0.5ic
        # answers, which is where `_run_step_0_5ic` reads it. Before
        # 2026-09-04 a sole slot file was read as the design's choice, so these
        # fixtures never had to say -- and a design that never chose would have
        # been silently moved the moment the operator listed a second slot.
        ans_p = proj / ST.DESIGN_ANSWERS_REL
        ans_p.parent.mkdir(parents=True, exist_ok=True)
        prior = {}
        if ans_p.is_file():
            try:
                prior = json.loads(ans_p.read_text())
            except ValueError:
                prior = {}
        prior.setdefault("operator_template", {})["slot"] = "1x1"
        ans_p.write_text(json.dumps(prior, indent=2))
    else:
        marker = proj / TD.SELF_TAPEOUT_REL
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    return proj


def _mirror_operator(flip=None, flip_to=None):
    """A runner that REALLY runs our arm and MIRRORS it on the operator's side.

    The counterparty's arm is a container this suite cannot run, and
    `test_tapeout_readiness_check.py` already pins what that arm does with a
    real run directory. What is under test HERE is the MERGE, so the operator's
    side is a report at the path its own program would have written — and our
    side is executed for real, because the claim "our ladder runs on every
    design" is worthless if the test fakes it.

    IT MIRRORS RATHER THAN INVENTS, and that is the whole design of this
    fixture. A stand-in that asserted its own fixed verdicts would disagree
    with our arm on every step our arm happens to refuse — in this environment
    the delegated checkers have no inputs and refuse four of them — and the
    test would then "detect a disagreement" it manufactured wholesale. Mirroring
    means the two arms agree everywhere EXCEPT the one step the test flips, so
    the detector is being asked about exactly one thing.
    """
    def run(cmd, timeout):
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if any("general_precheck.py" in c for c in cmd):
            return TP.default_runner(cmd, timeout)
        ours = json.loads(out.parent.joinpath("general_precheck.json").read_text())
        by = {s["step_id"]: s for s in ours["steps"]}
        steps = []
        for sid in _OPERATOR_LADDER:
            mine = by.get(sid, {})
            v = mine.get("verdict", GP.PASS)
            if sid == flip:
                v = flip_to
            steps.append({"step_id": sid, "label": sid, "verdict": v,
                          "evidence": f"operator container reported {v}"})
        verdict = (GP.FAIL if any(s["verdict"] == GP.FAIL for s in steps)
                   else GP.NOT_DETERMINED
                   if any(s["verdict"] == GP.NOT_DETERMINED for s in steps)
                   else GP.PASS)
        out.write_text(json.dumps({
            "project": cmd[2], "shuttle": "wafer_space_gf180mcu",
            "verdict": verdict,
            "reason": "stand-in for the operator's own run directory",
            "steps": steps}, indent=2))
        return 0 if verdict == GP.PASS else 1, "", ""
    return run


def _stub_both(our_steps, their_steps):
    """Both arms fabricated — for the claims that are about the MERGE's verdict
    ladder rather than about either ladder's own content."""
    def run(cmd, timeout):
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        steps = (our_steps if any("general_precheck.py" in c for c in cmd)
                 else their_steps)
        verdict = (GP.FAIL if any(s["verdict"] == GP.FAIL for s in steps)
                   else GP.NOT_DETERMINED
                   if any(s["verdict"] == GP.NOT_DETERMINED for s in steps)
                   else GP.PASS)
        out.write_text(json.dumps(
            {"verdict": verdict, "reason": "stub", "steps": steps}, indent=2))
        return 0 if verdict == GP.PASS else 1, "", ""
    return run


#: The operator ladder's step ids for a non-COB submission, taken from the
#: registry rather than re-typed, so a change to the real ladder reaches this
#: fixture instead of leaving it quietly describing an older one.
_OPERATOR_LADDER = tuple(
    st.step_id for st in TRC.SHUTTLES["wafer_space_gf180mcu"].ladder
    if not st.cob_only)


def _all_green(ladder):
    return [{"step_id": sid, "label": sid, "verdict": GP.PASS,
             "evidence": "green"} for sid in ladder]


_DIE_ANSWERS = {"deliverable": "DIE", "top_cell": "chip_top",
                "die_origin_um": [0, 0], "die_area_um": [0, 0, 100.0, 80.0],
                "database_unit_um": 0.001}


def _finding_kinds(rep):
    return [f.kind for f in rep.findings]


def _arm(rep, which):
    return next(a for a in rep.arms if a.arm == which)


# --------------------------------------------------------------------------- #
# T8 — the registry answers the applicability question
# --------------------------------------------------------------------------- #
def test_t8_the_registry_says_which_pdks_ship_a_shuttle_precheck():
    assert TRC.shuttle_for_pdk("gf180mcuD").shuttle_id == "wafer_space_gf180mcu"
    # A DIFFERENT open PDK is not a match, so the arm is genuinely conditional.
    assert TRC.shuttle_for_pdk("ihp-sg13g2") is None
    assert TRC.shuttle_for_pdk("nangate45") is None
    # An unknown / unstated PDK resolves to nothing — and the CALLER, not this
    # function, is what keeps that apart from "this PDK has no shuttle".
    assert TRC.shuttle_for_pdk("") is None


def test_t8_a_retired_counterparty_is_not_an_answer_of_yes_and_is_still_named():
    # The retired shuttle's PDK must NOT produce a live arm: a counterparty
    # that stopped answering cannot refuse, and demanding a run from one that
    # no longer exists would make every design on that PDK unpassable forever.
    assert TRC.shuttle_for_pdk("sky130A") is None
    named = [s.shuttle_id for s in TRC.retired_shuttles_for_pdk("sky130A")]
    assert named == ["efabless_open_mpw"], (
        "a PDK that ONCE had an external bar and no longer does is a different "
        f"fact from one that never had one; got {named!r}")


# --------------------------------------------------------------------------- #
# T1 / T2 / T7 — no operator template, and a PDK with no shuttle
# --------------------------------------------------------------------------- #
def test_t1_our_arm_runs_on_a_project_with_no_operator_template(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    rep = TP.evaluate(proj)

    ours = _arm(rep, "ours")
    assert ours.state == TP.RAN, ours.reason
    assert ours.verdict in (GP.PASS, GP.FAIL, GP.NOT_DETERMINED)
    assert (proj / TP.OUR_ARM_ARTEFACT).is_file(), (
        "our arm must write its own report; the merge quotes it, it does not "
        "replace it")
    # It really ran the ladder rather than declining: every ladder step of
    # `general_precheck` is present in the arm's steps.
    assert {s["step_id"] for s in ours.steps} == {s.step_id for s in GP.LADDER}


def test_t2_a_pdk_with_no_shuttle_is_one_fewer_arm_not_a_failure(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    rep = TP.evaluate(proj)

    op = _arm(rep, "operator")
    assert op.state == TP.NOT_APPLICABLE, op.reason
    assert rep.arms_expected == 1, (
        "with no live shuttle for this PDK the step expects ONE arm; counting a "
        "second and never running it is how an absence becomes invisible")
    # The absence is a LINE, with an authority, not a silence.
    absent = [f for f in rep.findings
              if f.kind == "ARM" and f.verdict == TP.NOT_APPLICABLE]
    assert len(absent) == 1 and absent[0].authority_is_ours, absent
    assert "names no LIVE shuttle" in absent[0].message


def test_t7_the_operator_artefact_exists_even_when_nobody_asked(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    TP.evaluate(proj)

    rec = json.loads((proj / TP.THEIR_ARM_ARTEFACT).read_text())
    assert rec["arm_ran"] is False
    assert rec["verdict_is_the_operators"] is False
    assert rec["authority_is_ours"] is True
    assert rec["verdict"] == TP.NOT_APPLICABLE
    assert rec["steps"] == []


# --------------------------------------------------------------------------- #
# T3 — the registry says yes and nothing was fetched
# --------------------------------------------------------------------------- #
def test_t3_registry_says_yes_but_nothing_fetched_is_not_determined(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=False)
    rep = TP.evaluate(proj)

    op = _arm(rep, "operator")
    assert op.state == TP.NOT_DETERMINED, op.reason
    assert "never fetched" in op.reason
    assert rep.arms_expected == 2 and rep.arms_ran <= 1
    # The step REFUSES. Which non-pass it lands on depends on what our own arm
    # found, and the claim being pinned here is that the missing arm is never
    # credited: `verdict` is not PASS and the operator arm is named as missing.
    assert rep.verdict != TP.PASS, rep.reason
    assert any(a.state == TP.NOT_DETERMINED for a in rep.arms)

    rec = json.loads((proj / TP.THEIR_ARM_ARTEFACT).read_text())
    assert rec["verdict"] == TP.NOT_DETERMINED and rec["arm_ran"] is False


def test_t3_a_missing_operator_arm_alone_is_enough_to_refuse(tmp_path):
    """The isolating half of T3.

    Our arm is stubbed ALL GREEN, so the ONLY thing left that can stop this
    step is the arm that should have run and did not. If a silent skip were
    still possible anywhere, this is where it would show up as a PASS.
    """
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=False)
    rep = TP.evaluate(proj, runner=_stub_both(
        _all_green(s.step_id for s in GP.LADDER), []))

    assert _arm(rep, "ours").verdict == GP.PASS
    assert _arm(rep, "operator").state == TP.NOT_DETERMINED
    assert rep.verdict == TP.NOT_DETERMINED, rep.reason
    assert "did not run is not a pass" in rep.reason


def test_t3_the_same_project_with_the_template_fetched_can_pass(tmp_path):
    """The other side of the SAME control: identical project, identical stubs,
    one difference — the operator's template is there. RED/GREEN on the one
    condition under test, so the refusal above is attributable to it and to
    nothing else."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj, runner=_stub_both(
        _all_green(s.step_id for s in GP.LADDER),
        _all_green(_OPERATOR_LADDER)))

    assert _arm(rep, "operator").state == TP.RAN
    assert rep.verdict == TP.PASS, rep.reason


def test_t3_the_not_fetched_case_is_a_different_artefact_from_the_no_shuttle_case(
        tmp_path):
    """The two absences must not be one absence.

    This is the discriminating half of T3. Both projects lack the operator's
    template; only one of them is on a PDK that ships a precheck. If the two
    produced the same record, the whole condition would be decorative.
    """
    fetched_none_shuttle_yes = _project(
        tmp_path / "a", _die_at_origin, _DIE_ANSWERS,
        pdk="gf180mcuD", slots=False)
    fetched_none_shuttle_no = _project(
        tmp_path / "b", _die_at_origin, _DIE_ANSWERS,
        pdk="ihp-sg13g2", slots=False)
    a = TP.evaluate(fetched_none_shuttle_yes)
    b = TP.evaluate(fetched_none_shuttle_no)

    assert _arm(a, "operator").state == TP.NOT_DETERMINED
    assert _arm(b, "operator").state == TP.NOT_APPLICABLE
    assert a.arms_expected == 2 and b.arms_expected == 1
    assert (json.loads((fetched_none_shuttle_yes / TP.THEIR_ARM_ARTEFACT).read_text())
            != json.loads((fetched_none_shuttle_no / TP.THEIR_ARM_ARTEFACT).read_text()))


def test_t3_a_pdk_nobody_declared_is_not_determined_never_not_applicable(tmp_path):
    """Hard rule: "I could not look" and "I looked and found nothing" differ."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="", slots=False)
    (proj / "input" / "project.json").unlink()
    rep = TP.evaluate(proj)

    op = _arm(rep, "operator")
    assert op.state == TP.NOT_DETERMINED, op.reason
    assert "no PDK target" in op.reason
    assert rep.verdict != TP.PASS, rep.reason


# --------------------------------------------------------------------------- #
# T4 / T5 / T6 — both arms, and the disagreement
# --------------------------------------------------------------------------- #
def test_t4_both_arms_run_when_the_template_was_fetched(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj,
                      runner=_mirror_operator())

    assert _arm(rep, "ours").state == TP.RAN
    assert _arm(rep, "operator").state == TP.RAN, _arm(rep, "operator").reason
    assert rep.arms_expected == 2 and rep.arms_ran == 2
    assert (proj / TP.OUR_ARM_ARTEFACT).is_file()
    assert (proj / TP.THEIR_ARM_ARTEFACT).is_file()
    # The two ladders really do overlap, which is what makes a cross-check
    # possible at all. If this ever drops to zero the disagreement pass is
    # vacuous and this assertion is the thing that says so.
    assert len(rep.shared_ladder_steps) >= 8, rep.shared_ladder_steps


def test_t4_a_forced_disagreement_fails_the_step(tmp_path):
    """OUR arm refuses the origin; the operator's stand-in clears it."""
    proj = _project(tmp_path, _die_off_origin_via_children, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj, runner=_mirror_operator(
        flip="KLayout.CheckSize", flip_to=GP.PASS))

    ours = next(s for s in _arm(rep, "ours").steps
                if s["step_id"] == "KLayout.CheckSize")
    assert ours["verdict"] == GP.FAIL, (
        "the fixture must make OUR arm refuse, or there is no disagreement to "
        "detect and this test proves nothing")

    assert [d["step_id"] for d in rep.disagreements] == ["KLayout.CheckSize"]
    assert rep.verdict == TP.FAIL, rep.reason
    assert "disagree" in rep.reason
    # It is NOT resolved by preferring an arm: BOTH verdicts survive in the
    # finding, each with its own authority.
    d = rep.disagreements[0]
    assert {v["verdict"] for v in d["verdicts"]} == {GP.PASS, GP.FAIL}
    assert [v["authority_is_ours"] for v in d["verdicts"]] == [True, False]
    kinds = _finding_kinds(rep)
    assert "DISAGREEMENT" in kinds


def test_t4_the_disagreement_fails_in_the_other_direction_too(tmp_path):
    """The operator refuses a layout OUR ladder cleared. Same verdict, and it
    must be reached from the other side — a merge that only notices one arm's
    refusals is half a merge."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj, runner=_mirror_operator(
        flip="KLayout.CheckSize", flip_to=GP.FAIL))

    ours = next(s for s in _arm(rep, "ours").steps
                if s["step_id"] == "KLayout.CheckSize")
    assert ours["verdict"] == GP.PASS
    assert [d["step_id"] for d in rep.disagreements] == ["KLayout.CheckSize"]
    assert rep.verdict == TP.FAIL


def test_t5_agreement_is_not_reported_as_disagreement(tmp_path):
    proj = _project(tmp_path, _die_off_origin_via_children, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj, runner=_mirror_operator())

    assert rep.disagreements == [], (
        "both authorities refused the SAME step for the same layout; that is "
        "agreement, and reporting it as a disagreement would bury the real "
        "ones")
    assert rep.verdict == TP.FAIL      # still a refusal — just not a disagreement
    assert "refused" in rep.reason


def test_t5_an_undetermined_on_one_side_is_an_absence_not_a_disagreement(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    # BOTH arms stubbed, so the only non-pass in the whole run is the single
    # NOT_DETERMINED under test. If an absence were being read as a
    # disagreement, this is where it would turn the verdict into a FAIL.
    theirs = _all_green(_OPERATOR_LADDER)
    for st in theirs:
        if st["step_id"] == "KLayout.CheckSize":
            st["verdict"] = GP.NOT_DETERMINED
    rep = TP.evaluate(proj, runner=_stub_both(
        _all_green(s.step_id for s in GP.LADDER), theirs))

    assert rep.disagreements == [], (
        "one authority reached no verdict; that is an absence. Calling it a "
        "disagreement would flood the report with the very silence the arms "
        "exist to surface")
    assert rep.verdict == TP.NOT_DETERMINED, rep.reason
    assert "determined nothing" in rep.reason


def test_t6_every_finding_names_its_authority(tmp_path):
    proj = _project(tmp_path, _die_off_origin_via_children, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj, runner=_mirror_operator(
        flip="KLayout.CheckSize", flip_to=GP.PASS))

    assert rep.findings, "a step that found nothing to say has not been run"
    for f in rep.findings:
        assert f.authority and "/" in f.authority, f
        assert isinstance(f.authority_is_ours, bool), f
    # BOTH authorities are represented, and exactly one of them is not ours.
    ours = {f.authority for f in rep.findings if f.authority_is_ours}
    theirs = {f.authority for f in rep.findings if not f.authority_is_ours}
    assert ours == {"vibe-ic/general_precheck", "vibe-ic/tapeout_precheck"}
    assert theirs == {"wafer_space_gf180mcu/gf180mcu-precheck"}, theirs


def test_t6_the_summary_line_states_the_denominator(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    line = TP.evaluate(proj).summary_line()
    for token in ("arms_expected=", "arms_ran=", "disagreements=",
                  "findings_by_authority=", "pdk="):
        assert token in line, f"{token!r} missing from {line!r}"


# --------------------------------------------------------------------------- #
# The verdict ladder itself
# --------------------------------------------------------------------------- #
def test_a_clean_two_arm_run_passes_and_rc_is_zero(tmp_path):
    """PASS is REACHABLE. A gate nobody has seen pass is as unproven as one
    nobody has seen fail."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)

    rep = TP.evaluate(proj, runner=_stub_both(
        _all_green(s.step_id for s in GP.LADDER),
        _all_green(_OPERATOR_LADDER)))
    assert rep.verdict == TP.PASS, rep.reason
    assert rep.arms_ran == 2 and rep.disagreements == []


def test_an_arm_that_writes_no_report_is_an_error_not_a_pass(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)

    def writes_nothing(cmd, timeout):
        return 0, "", ""          # rc 0 and NO artefact — the worst shape

    rep = TP.evaluate(proj, runner=writes_nothing)
    assert _arm(rep, "ours").state == TP.ERROR
    assert rep.verdict == TP.NOT_DETERMINED, (
        "an arm that exited 0 and produced nothing must never be credited as "
        "a pass")


def test_the_operator_artefact_exists_even_when_the_arm_ERRORED(tmp_path):
    """The third path to that file, and the one easiest to forget.

    T7 covers the arm that was never asked. This is the arm that WAS asked and
    came back with nothing readable — a worse state, and the one that must not
    be the state that leaves the declared output absent. An absent file is the
    single shape a reader cannot tell from "this run predates the arm".
    """
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=True)
    rep = TP.evaluate(proj,
                      runner=lambda cmd, t: (0, "", ""))   # rc 0, writes nothing

    assert _arm(rep, "operator").state == TP.ERROR
    assert (proj / TP.THEIR_ARM_ARTEFACT).is_file(), (
        "the operator arm's declared output is absent on the ERROR path")
    rec = json.loads((proj / TP.THEIR_ARM_ARTEFACT).read_text())
    assert rec["arm_state"] == TP.ERROR and rec["arm_ran"] is False
    assert rec["verdict"] == TP.NOT_DETERMINED, (
        "ERROR must map onto one of the THREE verdicts, not become a fourth")
    assert rec["verdict_is_the_operators"] is False
    assert rep.verdict == TP.NOT_DETERMINED


def test_main_returns_one_for_every_non_pass(tmp_path):
    proj = _project(tmp_path, _die_off_origin_via_children, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    # `--timeout` is deliberately not passed: the launcher this reaches is
    # supervised (see `_no_wall_clock_verdicts`), so any value would be inert,
    # and leaving one in argv would read as a bound that still decides
    # something.
    rc = TP.main([str(proj)])
    assert rc == 1
    doc = json.loads((proj / TP.MERGED_ARTEFACT).read_text())
    assert doc["verdict"] in (TP.FAIL, TP.NOT_DETERMINED)
    assert doc["emitted_by"]


def test_main_refuses_a_project_directory_that_is_not_there(tmp_path):
    assert TP.main([str(tmp_path / "nope")]) == 2


# --------------------------------------------------------------------------- #
# THE PDK A SIGN-OFF IS GRADED AGAINST IS THE ONE THE RUN BUILT
# --------------------------------------------------------------------------- #
def _multi_target_project(tmp_path: Path, built: str) -> Path:
    """A design declaring TWO targets, whose run built the SECOND one.

    Written where the tree's own accessors read: `L19_CONSTRAINTS_PDK.json` for
    the declared target and its alternates, and a tool log for the libraries
    that were actually loaded. No second channel is invented for either.
    """
    proj = tmp_path / "proj"
    l19 = proj / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
    l19.parent.mkdir(parents=True, exist_ok=True)
    l19.write_text(json.dumps({"fields": {
        "pdk_target": "alpha130",
        "pdk_target_alternates": ["alpha130", "beta180"],
    }}))
    log = proj / "phase3" / "stage3" / "pnr" / "tool.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"read_lef /pdks/{built}/libs.ref/{built}_fd_sc/lef/{built}_fd_sc.lef\n"
        f"read_liberty /pdks/{built}/libs.ref/{built}_fd_sc/lib/"
        f"{built}_fd_sc__tt.lib\n")
    return proj


class TestTheGradedPdkIsTheOneTheRunBuilt:
    """MEASURED on spm x gf180mcuD, 2026-09-02, a run invoked
    `--pdk gf180mcuD`: `resolve_pdk` returned `sky130` and the merged report
    published `pdk=sky130`. L19 was RIGHT -- the design declares
    `pdk_target: "sky130"` with `pdk_target_alternates: ["sky130", "gf180mcu"]`
    -- and step 37.5ic's gate clause passes no `--pdk`, so the scalar primary
    was the only thing anybody read. `operator_arm_applicability`,
    `shuttle_for_pdk` and `retired_shuttles_for_pdk` were all answered for a
    process the run never used.
    """

    def test_the_corroborated_alternate_wins_over_the_declared_primary(
            self, tmp_path):
        """THE DIRECTION THE FIX ADDS. Fails against the pre-fix resolver,
        which returned the primary whatever the run had loaded."""
        proj = _multi_target_project(tmp_path, built="beta180")
        pdk, source = TP.resolve_pdk(proj)
        assert pdk == "beta180", (pdk, source)
        assert "tool logs" in (source or ""), source

    def test_a_single_target_design_resolves_exactly_as_before(self, tmp_path):
        """THE CONTROL, and it holds in BOTH directions: a design with no
        alternates must reach the unchanged `declared_target` path even if its
        logs name something else, because there is no declared set to choose
        from and this function must not invent one."""
        proj = tmp_path / "proj"
        l19 = proj / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
        l19.parent.mkdir(parents=True, exist_ok=True)
        l19.write_text(json.dumps({"fields": {"pdk_target": "alpha130"}}))
        log = proj / "phase3" / "tool.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("read_lef /pdks/beta180/libs.ref/x/lef/beta180_x.lef\n")
        pdk, source = TP.resolve_pdk(proj)
        assert pdk == "alpha130", (pdk, source)
        assert "tool logs" not in (source or ""), source

    def test_an_explicit_pdk_still_wins(self, tmp_path):
        """Also both directions: the caller's own answer outranks every
        derivation, before and after."""
        proj = _multi_target_project(tmp_path, built="beta180")
        assert TP.resolve_pdk(proj, "gamma90") == ("gamma90", "--pdk")

    def test_two_corroborated_targets_are_not_resolved_here(self, tmp_path):
        """THE OVER-REACH CONTROL, all-negative, so it holds in BOTH
        directions. A run whose logs name libraries from TWO declared targets
        is a contradiction `declared_pdk_is_the_pdk_used_check` owns and
        reports as one; this function must not pick a winner."""
        proj = _multi_target_project(tmp_path, built="beta180")
        log = proj / "phase3" / "stage3" / "pnr" / "tool.log"
        log.write_text(log.read_text() +
                       "read_lef /pdks/alpha130/libs.ref/y/lef/alpha130_y.lef\n")
        pdk, source = TP.resolve_pdk(proj)
        assert pdk == "alpha130", (pdk, source)
        assert "tool logs" not in (source or ""), source

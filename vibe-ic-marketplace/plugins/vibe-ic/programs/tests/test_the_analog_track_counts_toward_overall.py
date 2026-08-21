"""test_the_analog_track_counts_toward_overall.py — the roll-up, both directions.

WHAT WAS MEASURED, AND WHY THE ORDERING GUARD WAS NOT ENOUGH
============================================================
`flow_compliance_check.py` run exactly as `design_one_shot_runner.step_final_audit`
runs it (`--phase 2 --strict-structural --allow-thin-input`, env
`PHASE23_ANALOG_FPGA_STUB=1`), over four trees per family that differ in ONE
recorded content value. Rank = `(verdict, -failed-step count)`; higher is better.

    BEFORE (v1.9.50's derived ordering guard, and nothing else)

      thin  design-bound        FAIL  FAIL=3  rank (0,-3)  ordering-violations 3
            disclosed           FAIL  FAIL=3  rank (0,-3)  ordering-violations 3
            silent key-absent   PASS  FAIL=4  rank (2,-4)  ordering-violations 0
            silent "undeclared" PASS  FAIL=4  rank (2,-4)  ordering-violations 0

The two SILENT trees audit `Overall: PASS` while failing MORE analog steps than
either tree that spoke, and they do it with an EMPTY ordering-violation list.
That is the whole mechanism: under `--phase 2 --strict-structural` the verdict
scope was the `P0` structural-RTL umbrella alone, so the analog track reached
`Overall` ONLY through the step-execution ordering guard — and that guard
adjudicates DONE-CLAIMS. A tree that CLAIMED an analog step done over a failed
dependency could be marked down. A tree whose analog steps simply FAILED made no
claim to adjudicate and could not be. Doing nothing was structurally cheaper
than doing something badly and saying so.

`_flow_verdict_tiers`' own module docstring records this as the flow-POLICY
question it deliberately left open and called "the owner's to settle".

OWNER POLICY (2026-08-02), vibe-ic#634: THE ANALOG TRACK COUNTS TOWARD
`Overall`. AFTER, on the same trees, the silent trees audit FAIL at rank (0,-4)
— below both trees that spoke, on the failed-step count, in both families.

THE INVARIANT IS A PROPERTY OF THE WHOLE CHAIN, never of one adjacent pair:

    rank(design-bound)  >=  rank(disclosed)  >=  rank(silent)

Repair one pair by moving one element into line and the other breaks. Every
test below measures BOTH directions on the SAME trees, in one run.

THE CONTROL THAT MATTERS MOST — ABSENT IS NOT FAILED
----------------------------------------------------
Every A-step's flow `condition` keys on an analog block list, so a design with
no analog content resolves the WHOLE track to `SKIPPED-CONDITION`, which the
shared vocabulary registers as `EXCUSED` — precisely what the producer already
subtracts from `total_required`. The scoping predicate is the COMPLEMENT of that
set, so absent is free and ONLY absent is free. Section 1 asserts that on a tree
built by DELETING the analog track from a tree that fails — one difference,
measured both ways — and it is the first thing in this file on purpose.

Every fixture is synthetic: invented block names, an open PDK selector, library
nominal geometries, no design content.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flow_verdict_tiers as TIERS                              # noqa: E402
import test_silence_is_not_cheaper_than_disclosure as THIN       # noqa: E402
import test_two_gates_over_one_artefact_cannot_disagree as FULL  # noqa: E402

FLOW_COMPLIANCE = PROGRAMS / "flow_compliance_check.py"

#: The token a producer writes when the upstream shipped no record — a
#: non-empty string, so a rule keyed on "is the field present?" accepts it.
NO_RECORD = "undeclared"

#: Better is a HIGHER number. Only the relation matters.
_VERDICT_RANK = {"FAIL": 0, "PASS_WITH_WAIVERS": 1,
                 "PASS_WITH_OPEN_SOURCE_CONSTRAINTS": 1, "PASS": 2}


def _flow_audit(project: Path, *extra: str) -> dict:
    """The audit `design_one_shot_runner.step_final_audit` runs, verbatim —
    same flags, same env, and the verdict read off the same `Overall:` line
    the runner greps out of stdout. `extra` adds the flags the runner itself
    forwards conditionally (`--skip-analog`)."""
    env = dict(os.environ)
    env["PHASE23_ANALOG_FPGA_STUB"] = "1"
    out = project / "_audit.json"
    p = subprocess.run(
        [sys.executable, str(FLOW_COMPLIANCE), str(project),
         "--phase", "2", "--strict-structural", "--allow-thin-input",
         *extra, "--json", str(out)],
        # 45 s, MEASURED not guessed: all 13 cases in this file, each of which
        # makes one of these calls, run in 10 s together. The ceiling that
        # matters is the harness's 180 s — an inner bound above 60 s can outlive
        # it and kill the SESSION instead of the test, which
        # `ci_harness_timeout_ceiling_check` failed this file on at merge.
        capture_output=True, text=True, timeout=45, env=env)
    rep = json.loads(out.read_text())
    # The runner's own substring test, in its own order (`PASS` is a prefix
    # of `PASS_WITH_WAIVERS`). This is the value that becomes the runner's
    # `final_audit` step verdict, so it is what the tests below assert on.
    if "Overall: PASS_WITH_WAIVERS" in p.stdout:
        rep["_runner_final_audit"] = "WAIVED"
    elif "Overall: PASS" in p.stdout:
        rep["_runner_final_audit"] = "PASS"
    else:
        rep["_runner_final_audit"] = "FAIL"
    return rep


def _rank(rep: dict) -> tuple:
    """HOW GOOD IS THIS RUN, from the audit's own report and nothing else.

      * a better `Overall` verdict is a better run;
      * among runs with the SAME verdict, the one with FEWER failed canonical
        steps is the better run.

    Neither component mentions analog, disclosure or silence, so no assertion
    below can be satisfied by a ranking built to produce the answer. The
    second component is what makes "at the bottom" measurable once the verdict
    words tie.
    """
    return (_VERDICT_RANK[rep["overall"]], -rep["counts"].get("FAIL", 0))


def _statuses(rep: dict) -> dict:
    return {str(s.get("id")): s.get("status") for s in rep.get("steps", [])}


def _analog_ids(rep: dict) -> list:
    return [str(s.get("id")) for s in rep.get("steps", [])
            if TIERS.in_analog_track(s)]


# ══ 1. ABSENT IS NOT FAILED — the control, first, and asserted both ways ═══

def test_a_design_with_no_analog_content_still_audits_pass(tmp_path):
    """THE CONTROL THAT MATTERS MOST, and it is a DIFFERENCE, not a fact.

    Two trees built from one builder. The second is the first with the analog
    track DELETED — so the only thing that varies is whether this design has
    analog content at all. The tree whose analog track ran and failed must
    audit FAIL; the tree that has no analog track must audit PASS.

    Asserted as a pair on purpose. "The digital tree passes" alone is
    satisfied by a scoping that gates on nothing, and "the analog tree fails"
    alone is satisfied by a scoping that gates on everything and takes every
    pure-digital cell in the matrix down with it. Only the pair pins the
    discrimination.
    """
    failed = THIN._project(tmp_path / "analog_present", THIN.SIZED)
    absent = THIN._project(tmp_path / "analog_absent", THIN.SIZED)
    shutil.rmtree(absent / "phase3" / "analog")

    rep_failed = _flow_audit(failed)
    rep_absent = _flow_audit(absent)

    st_absent = _statuses(rep_absent)
    track = _analog_ids(rep_absent)
    assert track, "the flow declares no analog track — this control is inert"
    assert all(TIERS.is_excused(st_absent[i]) for i in track), (
        f"PRECONDITION: on a design with no analog content the whole track "
        f"must resolve to a legitimately-not-run status, and it resolved to "
        f"{ {i: st_absent[i] for i in track} } — the control is not measuring "
        f"absence")

    assert (rep_absent["_runner_final_audit"] == "PASS"
            and rep_absent["overall"] == "PASS"), (
        f"a design with NO analog content audits "
        f"{rep_absent['overall']} — the scoping cannot tell 'this design has "
        f"no analog track' from 'this design's analog track failed', which "
        f"breaks every pure-digital cell in the matrix")
    assert rep_failed["_runner_final_audit"] == "FAIL", (
        f"a design whose analog track FAILED audits "
        f"{rep_failed['overall']} — the analog track does not reach Overall")


def test_the_scoping_predicate_lets_exactly_the_not_run_states_through():
    """The mechanism behind section 1, pinned where it cannot be reached by a
    fixture accident, and DERIVED rather than listed.

    Parametrised over `PRODUCER_STATUSES` — the pin on the producer's whole
    vocabulary — so a status word registered tomorrow is exercised on the
    commit that registers it, and the two halves partition that vocabulary
    instead of restating it. And the fail-safe direction: a word this tree has
    never seen is scoped IN, because "absent" is a claim the vocabulary has to
    make, not a default anything inherits.
    """
    assert TIERS.EXCUSED & TIERS.PRODUCER_STATUSES, (
        "no excused word is in the producer's vocabulary — this pin is inert")
    for word in TIERS.EXCUSED:
        assert not TIERS.scoped_into_verdict({"status": word}), (
            f"{word} means the step legitimately did not run and must not "
            f"reach the verdict")
    for word in TIERS.PRODUCER_STATUSES - TIERS.EXCUSED:
        assert TIERS.scoped_into_verdict({"status": word}), (
            f"{word} does not mean the step legitimately did not run, so it "
            f"must reach the verdict")
    assert TIERS.scoped_into_verdict({"status": "NO-SUCH-TIER-EXISTS"}), (
        "a status nothing has registered was treated as a legitimate skip — "
        "absent must be CLAIMED, never inherited by a word nobody knows")


def test_the_analog_track_is_identified_by_the_flows_own_stage(tmp_path):
    """Chip-AGNOSTIC, and renumber-proof. The track is whatever the flow yaml
    marks with the analog stage word — never a step-id allow-list, which is
    the shape that goes quiet on the step it did not know about."""
    rep = _flow_audit(THIN._project(tmp_path, THIN.SIZED))
    track = _analog_ids(rep)
    assert track, "no step in the flow carries the analog stage word"
    assert not any(TIERS.in_analog_track(s) for s in rep["steps"]
                   if str(s.get("stage", "")).strip().lower()
                   != TIERS.ANALOG_STAGE), (
        "in_analog_track answered yes for a step outside the analog stage")
    assert not TIERS.in_analog_track({"stage": "stage_mixed_signal"}), (
        "mixed-signal is a DIFFERENT track and is deliberately not scoped "
        "in by this change")


# ══ 2. THE CHAIN, BOTH DIRECTIONS, ON THE SAME TREES ══════════════════════

_VARIANTS = {"design-bound": "SIZED", "disclosed": "STRUCTURE_ONLY",
             "silent-key-absent": None, "silent-token": NO_RECORD}

_FAMILIES = {"thin": THIN, "full": FULL}


def _four_trees(family, root: Path) -> dict:
    mod = _FAMILIES[family]
    out = {}
    for name, which in _VARIANTS.items():
        content = (mod.SIZED if which == "SIZED"
                   else mod.STRUCTURE_ONLY if which == "STRUCTURE_ONLY"
                   else which)
        out[name] = _flow_audit(
            mod._project(root / name.replace("-", "_"), content))
    return out


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_the_chain_holds_in_both_directions(family, tmp_path):
    """THE HEADLINE. One run, four trees, every adjacent pair in the chain,
    and the whole chain in one assertion so repairing one pair by moving one
    element cannot pass while it breaks the other.

        rank(design-bound) >= rank(disclosed) >= rank(silent)

    The precondition keeps this from being true of four trees the audit never
    looked at: the design-bound tree's analog track must actually have failed.
    """
    reps = _four_trees(family, tmp_path)
    ranks = {k: _rank(v) for k, v in reps.items()}
    shown = {k: (v["overall"], v["counts"].get("FAIL", 0))
             for k, v in reps.items()}

    bound_track = {i: _statuses(reps["design-bound"])[i]
                   for i in _analog_ids(reps["design-bound"])}
    assert any(TIERS.is_non_green(s) for s in bound_track.values()), (
        f"PRECONDITION: the design-bound tree's analog track did not fail "
        f"({bound_track}), so this comparison is over four trees with nothing "
        f"to rank")

    for hi, lo in (("design-bound", "disclosed"),
                   ("disclosed", "silent-key-absent"),
                   ("disclosed", "silent-token")):
        assert ranks[hi] >= ranks[lo], (
            f"[{family}] rank({hi})={ranks[hi]} < rank({lo})={ranks[lo]} — "
            f"the chain pays a producer to say less. All four: {shown}")


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_the_silent_trees_are_at_the_bottom_not_the_top(family, tmp_path):
    """The direction the derived ordering guard alone does NOT reach, asserted
    on its own so it cannot be lost inside the chain above.

    A tree that deleted its disclosure fields must not out-rank either tree
    that kept them. Strictly below, not merely tied: the silent trees have
    MORE failed analog steps than the trees that spoke, and a ranking that
    cannot see that is a ranking a producer can still game by going quiet.
    """
    reps = _four_trees(family, tmp_path)
    ranks = {k: _rank(v) for k, v in reps.items()}
    shown = {k: (v["overall"], v["counts"].get("FAIL", 0))
             for k, v in reps.items()}

    for silent in ("silent-key-absent", "silent-token"):
        for spoke in ("design-bound", "disclosed"):
            assert ranks[silent] < ranks[spoke], (
                f"[{family}] the SILENT tree ranks {ranks[silent]} and the "
                f"{spoke} tree ranks {ranks[spoke]} — silence is not below "
                f"speech. All four: {shown}")


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_a_failed_analog_track_reaches_the_verdict_without_a_done_claim(
        family, tmp_path):
    """THE MECHANISM, separated from the ordering guard it used to depend on.

    The silent tree in the THIN family makes NO done-claim its own track can
    be adjudicated on — and it must fail anyway. Assert both halves: no
    analog-track done-claim AND a FAIL verdict. If a later change re-routes
    this through the ordering guard, the first half fails and the reader is
    told the verdict came back for a different reason than the one this test
    is about.
    """
    mod = _FAMILIES[family]
    rep = _flow_audit(mod._project(tmp_path, None))
    track = {i: _statuses(rep)[i] for i in _analog_ids(rep)}

    assert any(TIERS.is_non_green(s) for s in track.values()), (
        f"[{family}] PRECONDITION: nothing in the silent tree's analog track "
        f"is unmet ({track})")
    assert rep["_runner_final_audit"] == "FAIL", (
        f"[{family}] a tree whose analog track FAILED audits "
        f"{rep['overall']} — doing nothing is still cheaper than doing "
        f"something badly and saying so. Track: {track}")


def test_a_failed_analog_track_with_no_done_claim_at_all_still_fails(tmp_path):
    """The same mechanism with the ordering guard REMOVED from the picture
    entirely, rather than merely argued about.

    The thin family's silent tree carries NOTHING on its analog track that
    `is_done_claim` answers yes to — every step is FAIL or MISSING — so the
    ordering guard has no subject there and the whole analog-track violation
    list is empty. It must still audit FAIL. This is the assertion that
    distinguishes "the scoping works" from "the ordering guard happened to
    catch it".
    """
    rep = _flow_audit(THIN._project(tmp_path, None))
    track = {i: _statuses(rep)[i] for i in _analog_ids(rep)}

    claims = {i: s for i, s in track.items() if TIERS.is_done_claim(s)}
    assert not claims, (
        f"PRECONDITION: the silent tree's analog track DOES make a done-claim "
        f"({claims}) — this test can no longer show that the verdict reaches "
        f"a track that only failed")
    analog_ordering = [v for v in (rep.get("ordering_violations") or [])
                       if any(i in str(v) for i in track)]
    assert not analog_ordering, (
        f"PRECONDITION: the analog track drew ordering violations "
        f"({analog_ordering}) — the verdict may be coming back through the "
        f"guard rather than through the scoping this test is about")
    assert any(TIERS.is_non_green(s) for s in track.values()), (
        f"PRECONDITION: nothing in the silent tree's analog track is unmet "
        f"({track})")
    assert rep["_runner_final_audit"] == "FAIL", (
        f"a tree whose analog track FAILED with NO done-claim to adjudicate "
        f"audits {rep['overall']} — the failure never reaches Overall at all. "
        f"Track: {track}")


def test_an_analog_track_that_produced_nothing_is_not_a_track_that_was_never_asked(
        tmp_path):
    """MISSING vs SKIPPED-CONDITION, isolated from FAIL entirely.

    Two trees. Both have ZERO failed steps. One declares analog blocks and
    then produces none of their declared outputs — every A-step MISSING. The
    other declares nothing, so every A-step is SKIPPED-CONDITION. Nothing in
    either tree is FAIL, so a scoping that keyed on the FAIL bucket alone
    would rank them identically, and a run that never started its analog work
    would cost exactly what a design with no analog work costs.
    """
    declared = THIN._project(tmp_path / "declared", THIN.SIZED)
    for blk in (declared / "phase3" / "analog").iterdir():
        if blk.is_dir():
            shutil.rmtree(blk)          # the block list stays; the work goes
    absent = THIN._project(tmp_path / "absent", THIN.SIZED)
    shutil.rmtree(absent / "phase3" / "analog")

    rep_declared = _flow_audit(declared)
    rep_absent = _flow_audit(absent)

    assert rep_declared["counts"].get("FAIL", 0) == 0, (
        f"PRECONDITION: the declared-but-empty tree has failed steps "
        f"({rep_declared['counts']}), so this no longer isolates MISSING "
        f"from FAIL")
    track = {i: _statuses(rep_declared)[i] for i in _analog_ids(rep_declared)}
    assert all(s == "MISSING" for s in track.values()), (
        f"PRECONDITION: the declared-but-empty track is not uniformly "
        f"MISSING ({track})")

    assert rep_absent["overall"] == "PASS", rep_absent["overall"]
    assert rep_declared["_runner_final_audit"] == "FAIL", (
        f"a design that DECLARED an analog track and produced none of it "
        f"audits {rep_declared['overall']} — identical to a design that has "
        f"no analog track at all. Not starting is not the same as having "
        f"nothing to start")


# ══ 3. THE SCOPING MAY NOT REACH PAST THE TRACK IT WAS DECIDED FOR ════════

def test_a_legitimately_skipped_analog_track_is_not_converted_into_a_deferral(
        tmp_path):
    """THE SECOND WAY THIS COULD HAVE BROKEN THE MATRIX, and it does not show
    up as a FAIL.

    `SKIPPED-CONDITION` on the analog track is what BOTH "this design has no
    analog content" and an explicit `--skip-analog` resolve to. Beside the
    failing/missing buckets sits a third one: a DISCLOSED self-skip of a
    sign-off step the open-source container cannot clear becomes a non-green
    item and then a deferral entry, and A3-A9 are all in that table. Scope
    the not-run states in and a pure-digital design acquires a deferral list
    by not having analog content.

    Asserted on the EXACT verdict word, never a prefix.
    `PASS_WITH_OPEN_SOURCE_CONSTRAINTS` contains the substring
    `Overall: PASS`, so the runner's own test reads it as a pass — which is
    precisely how this would have arrived unannounced. Both shapes of
    "did not run" are driven: the track absent, and the track present but
    skipped by flag.
    """
    absent = THIN._project(tmp_path / "absent", THIN.SIZED)
    shutil.rmtree(absent / "phase3" / "analog")
    rep_absent = _flow_audit(absent)
    assert rep_absent["overall"] == "PASS", (
        f"a design with no analog content audits {rep_absent['overall']} "
        f"rather than a plain PASS — the analog track acquired a cost by "
        f"being absent")

    present = THIN._project(tmp_path / "present", THIN.SIZED)
    assert _flow_audit(present)["overall"] == "FAIL", (
        "PRECONDITION: this tree's analog track does not fail when it IS "
        "audited, so skipping it proves nothing")
    rep_skipped = _flow_audit(present, "--skip-analog")
    track = {i: _statuses(rep_skipped)[i] for i in _analog_ids(rep_skipped)}
    assert all(TIERS.is_excused(s) for s in track.values()), (
        f"PRECONDITION: --skip-analog did not resolve the track to a "
        f"legitimately-not-run status ({track})")
    assert rep_skipped["overall"] == "PASS", (
        f"a tree whose analog track was skipped BY REQUEST audits "
        f"{rep_skipped['overall']} rather than a plain PASS — a deliberate "
        f"skip was converted into a cost, and at the "
        f"PASS_WITH_OPEN_SOURCE_CONSTRAINTS tier the runner would still read "
        f"it as a pass while a deferral list appeared underneath")


def test_the_mixed_signal_track_is_not_scoped_in_by_this_change(tmp_path):
    """DECLARED, NOT FIXED. `stage_mixed_signal` reaches `Overall` exactly the
    way it did before — through the ordering guard only. Pinned so the next
    reader can tell a deliberate boundary from an oversight, and so widening
    it later is a decision somebody makes rather than one that happens."""
    rep = _flow_audit(THIN._project(tmp_path, THIN.SIZED))
    ms = [s for s in rep["steps"]
          if str(s.get("stage", "")).strip().lower() == "stage_mixed_signal"]
    assert ms, "the flow declares no mixed-signal track — this pin is inert"
    assert not any(TIERS.in_analog_track(s) for s in ms), (
        "the mixed-signal track was pulled into the analog scoping")


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

"""test_matrix_mutation_ledger.py — the STANDING gate: a cell may not be called
ENFORCED unless a NAMED mutation is known to redden it, and a new flow step may
not arrive with eight unfalsifiable cells.

    ``test_flow_matrix_coverage.py`` proves every one of the 504 cells has a
    real, collected, non-skipping pytest item in a known state. Its own
    docstring says what that does NOT prove: that the item's predicate could
    ever have said no. This file asks for the missing half — name the change
    to this repository that makes this cell fail — and then RE-EXECUTES it.

====================================================================
THE FOUR THINGS THIS FILE REFUSES
====================================================================
1. **An ENFORCED cell with no named mutation.**
   :func:`test_every_enforced_cell_carries_a_named_mutation` asks the owning
   dimension module for the cell's state (never forms its own opinion) and, for
   every ENFORCED one, demands an entry in ``matrix_mutation_ledger.MUTATIONS``
   that was MEASURED to redden that exact cell. 481 of the 504 today.

2. **A flow that grew a step.**
   The flow-gate page says ``流程長一個步驟，覆蓋就自動變不完整``. That is a
   description until something stops a push over it. ``applies_to`` in the
   ledger is a FROZEN list of the step ids each mutation was actually run
   against, so a 64th step is in nobody's list, its eight cells are uncovered,
   and :func:`test_a_grown_flow_arrives_with_uncovered_cells` names the step.
   The control for this is shipped and runs every time: a synthetic 64th step is
   spliced into a COPY of the flow and the gate is re-run in a subprocess, which
   must exit non-zero naming that step.

3. **A mutation that was written down but never run.**
   Three locks, described in full in the ledger's own module docstring:
   LOCK 1 re-resolves every (entry, step) pair's edit site against the live tree
   (705 pairs, one yaml parse); LOCK 2 REPLAYS each entry's witness for real on
   an isolated copy and requires the cell to go PASS -> FAIL with the declared
   ``red_signal`` present; LOCK 3 checks the recorded arithmetic against itself.
   The replay lock has no off switch — an unrecognised
   ``VIBE_IC_MATRIX_MUTATION_REPLAY`` is a failure, not a skip.

   The counts here cover all THREE channels. The third, ``ARTEFACT_MUTATION``,
   edits a number inside a PUBLISHED REPORT rather than the source, and is
   gated in its own file — ``test_matrix_artefact_mutation_channel.py`` — for
   one reason worth stating here: half its entries RECORD that the cell they
   target cannot be reddened from artefact content, and an entry like that must
   never be able to satisfy point 1 above. The tuples are kept separate and the
   separation is asserted there.

4. **A NOT-FALSIFIABLE cell buried instead of published.**
   A cell no mutation could move is a FINDING, and
   :func:`test_not_falsifiable_cells_are_published_and_specific` requires it to
   be a real cell of the live grid with the shapes that were tried recorded. The
   list is empty as measured 2026-08-06, and the emptiness is asserted so a
   future entry has to be added deliberately rather than drifted into.

====================================================================
WHAT THIS FILE DOES *NOT* CLAIM
====================================================================
  * A mutation proves the cell is CONNECTED to something a change can move. It
    does not prove the predicate is strong, and no count here may be quoted as
    "481 defects would be caught".
  * By default LOCK 2 re-executes ONE witness per yaml/tree entry (16 pytest
    runs) plus EVERY artefact entry (8 gate replays, which have no witness
    subset), not all 705 pairs. That number is asserted rather than left for a
    reader to assume, and ``VIBE_IC_MATRIX_MUTATION_REPLAY=all`` is the
    audit-grade mode.
  * 13 cells are already red at 1ea6689b. An already-red cell is falsifiable by
    definition; it is recorded in the entry's ``baseline_red`` and excluded from
    the attributable count, and no witness may be one of them.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import pytest




# THE ONE CHANNEL WHOSE SUBJECT LEFT THIS REPOSITORY.
#
# `L.MUTATIONS` edits the flow yaml or the plugin tree — both are here, and
# nothing below about them changes. `L.ARTEFACT_MUTATIONS` edits a number inside
# a PUBLISHED REPORT, and every one of its entries names the published run
# `ic/spm/v1.10.18_sky130A`, which now lives in
# https://github.com/vibeic/benchmark-data. In this checkout those eight entries
# cannot resolve, cannot replay, and cannot be spoken about at all.
#
# The rule this repository already applies to an absent TOOL (vibe-ic#1357)
# applies to an absent CORPUS: a check that cannot measure must never report
# that it measured. Where an assertion below mixes the channels, the artefact
# half is set aside ONLY when there is no corpus to read — the aggregate is
# byte-for-byte what it was wherever `VIBE_IC_BENCHMARK_DATA` points at a clone,
# and the artefact channel's own LOCK 1 / LOCK 2 live in
# `test_matrix_artefact_mutation_channel.py`, corpus-gated there.



DIMENSION_MODULE_GLOB = "test_matrix_d[1-8]_*.py"

#: The synthetic step the growth control splices in. Named so a reader who sees
#: it in a failure knows it is a probe and not a real flow step.
CANARY_STEP_ID = "ZZ_MUTATION_LEDGER_CANARY_STEP"

#: How long one witness replay may take. The dimension-7 cell alone runs ~18s
#: twice, and the two PLUGIN_TREE replays copy and re-run the plugin.
#:
#: THE ONE BOUND IN THIS CORPUS THAT DOES NOT FIT UNDER THE CEILING (vibe-ic#1022)
#: -----------------------------------------------------------------------------
#: `ci_harness_timeout_ceiling_check` permits any ONE blocking call at most
#: `180 // 3` = 60 s, and it reports this line as an ADVISORY rather than a
#: finding only because `L.replay_many` is a cross-module callee it cannot
#: resolve. The hazard is identical to the ones it CAN resolve, and it is
#: reachable: a one-line edit to `programs/matrix_mutation_ledger.py` selects
#: this file into the 180 s targeted lane (verified with the real CLI,
#: `ci_targeted_test_select.py --base HEAD` — 15 files at the smoke floor, 17
#: with this file and `test_matrix_artefact_mutation_channel.py` added).
#:
#: It is NOT lowered to 60 anyway, because measurement says 60 would be a bound
#: that fires on work that is passing. `replay_many` forwards this to each
#: `_run_cell`, i.e. ONE `subprocess.run` running one pytest cell. MEASURED here
#: over the full 24-pair witness plan, 32 cores, instrumented at `_run_cell`:
#: 32 invocations, worst SINGLE bounded call 42.61 s at `jobs=8` and 26.8 s
#: uncontended, both in the dimension-7 cell (the ~18s in the line above has
#: grown). A 60 s bound is 1.41x the contended worst case — thinner than the
#: 2.7x this file already calls its thinnest margin below, and under it on any
#: host slower than this one. Trading a session-killer for an intermittent red
#: is not a fix.
#:
#: The correct remedy is the checker's second one — move the two replay-driven
#: tests (`test_lock2_…`, `test_the_replay_actually_ran_and_is_not_starved`) out
#: of the 180 s lane. That is NOT done here: this tree has no second lane to move
#: them to (`pytest.ini` names a `tests/` tree that does not exist, and there is
#: no marker/deselect wiring in `tools/gatekeeper-land.sh`), so the move is new
#: lane infrastructure rather than a re-bound. Until it exists this entry is
#: recorded BY NAME with the measurement above in
#: `test_ci_harness_timeout_ceiling_check._REVIEWED_ADVISORY_RESIDUAL`.
REPLAY_TIMEOUT = 900

#: Headroom between the replay's TOTAL wall budget and the per-test bound the
#: harness is actually enforcing.
#:
#: `REPLAY_TIMEOUT` above bounds ONE cell. Nothing bounded the PLAN, so the
#: aggregate was `len(plan)` cells deep and undeclared — and the pinned
#: `--timeout-method=thread` does not fail the TEST when that aggregate is
#: exceeded, it takes the whole SESSION. MEASURED on clean `7c376e348`, DEFAULT
#: `witness` mode (not the audit mode — this is the lane that really runs),
#: whole file, under the pinned harness with `--timeout` set to a bound this
#: plan cannot afford:
#:
#:     REALEXIT=1
#:     lines matching passed|failed|error in the whole output:   0
#:     FAILED lines:                                             0
#:     ... waiter.acquire() / +++ Timeout +++  in replay_many's as_completed
#:
#: Ninety-odd tests had already reached a verdict and not one is reported. A
#: script grepping that output for failures reads ZERO — the same zero a clean
#: run produces. An empty result is not a zero. With a budget the same run keeps
#: its summary line and NAMES what it could not reach.
#:
#: 10 s, and DELIBERATELY SMALL, because the headroom IS the regression window:
#: every second between `bound - headroom` and `bound` is a second in which a
#: replay that WOULD have finished is cut off instead. Below `bound - headroom`
#: nothing changes; above `bound` the session was dying anyway; only in between
#: does a green become a named red. Shrinking the headroom shrinks the only harm
#: this guard can do.
#:
#: 10 s is what the window has to absorb, not a round number picked by feel. The
#: deadline is checked BEFORE each pair and `replay_many` halves the per-cell
#: clamp so one pair cannot overrun it by a whole cell, so the residue is the
#: last wave's process teardown plus the dict-build and assertions that follow
#: the replay inside the same test (sub-second, measured). It is deliberately
#: NOT a proportion of the bound: the overrun it covers does not grow with the
#: bound.
REPLAY_BUDGET_HEADROOM = 10

#: Set by :func:`_record_harness_bound` from the bound pytest is REALLY
#: enforcing. `None` means no per-test bound is in effect — the audit lane —
#: and the replay then runs unbounded, exactly as it did before.
_HARNESS_BOUND: object = None


@pytest.fixture(scope="session", autouse=True)
def _record_harness_bound(pytestconfig):
    """Read the harness's own per-test bound instead of assuming 180.

    Assuming it would make this file wrong the day the harness moves, and would
    silently truncate the audit lane — which sets no bound at all — down to a
    batch lane's budget.
    """
    global _HARNESS_BOUND
    _HARNESS_BOUND = pytestconfig.getoption("timeout", default=None)


def replay_budget() -> object:
    """Total wall seconds the replay may spend, or ``None`` for unbounded."""
    bound = _HARNESS_BOUND
    try:
        bound = float(bound)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if bound <= 0:
        return None
    return max(1.0, bound - REPLAY_BUDGET_HEADROOM)

#: Bound for the two DIRECT pytest launches in this file (the growth control
#: and the witness-address collection). NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
#: The landed values were 600 (growth control) and 300 (collection). MEASURED
#: here: the growth control runs ONE cell nodeid under a spliced flow and takes
#: 22.18 s worst of its two calls; the collection is `--collect-only` over
#: eight nodeids at 0.84 s. 22.18 s is the thinnest margin in this file — 2.7x
#: — and it is stated rather than rounded away, because the growth control
#: makes TWO of these calls in one test and 2 x 60 = 120 s is precisely the
#: two-call shape the `// 3` divisor was measured to leave room for.
#: `REPLAY_TIMEOUT` above is deliberately NOT folded in here: it bounds
#: `replay_many`, a cross-module callee this gate cannot resolve, and it is
#: reported as an advisory rather than a finding. Changing it would alter what
#: the replays are allowed to do, which is not this change's subject.
_PYTEST_TIMEOUT_S = 60


# ══════════════════════════════════════════════════════════════════════
# The state of a cell is answered by the module that OWNS it
# ══════════════════════════════════════════════════════════════════════


#: A cell whose owning dimension module could not answer at all, carrying the
#: reason. NEVER folded into ENFORCED/WAIVED/NA: an unanswerable cell is a third
#: state, and the whole point of naming it is that "I could not look" must not
#: read the same as "I looked and it was fine".
UNREADABLE = "UNREADABLE: "






# ══════════════════════════════════════════════════════════════════════
# The review gate on the ledger's own size
# ══════════════════════════════════════════════════════════════════════








# ══════════════════════════════════════════════════════════════════════
# 1. AN ENFORCED CELL WITH NO NAMED MUTATION
# ══════════════════════════════════════════════════════════════════════






# ══════════════════════════════════════════════════════════════════════
# 2. A FLOW THAT GREW A STEP
# ══════════════════════════════════════════════════════════════════════












# ══════════════════════════════════════════════════════════════════════
# 3. A MUTATION WRITTEN DOWN BUT NEVER RUN — LOCKS 1, 2, 3
# ══════════════════════════════════════════════════════════════════════
















def test_the_replay_budget_is_below_the_harness_bound_that_would_kill_it():
    """The budget must come from the bound pytest is REALLY enforcing.

    A budget at or above the harness bound is no budget at all — the session
    dies first and the replay never gets to stop itself. And with no bound in
    effect (the audit lane, which is where ``all`` mode belongs) there must be
    NO budget, or this file would silently truncate the audit it was asked for.
    """
    bound = _HARNESS_BOUND
    budget = replay_budget()
    if budget is None:
        assert not bound, (
            f"no replay budget was derived although pytest is enforcing "
            f"{bound!r} per test; the replay can still kill the session")
        return
    assert budget < float(bound), (
        f"replay budget {budget}s is not below the harness bound {bound}s, so "
        f"the session is killed before the replay can report a shortfall")
    assert budget == max(1.0, float(bound) - REPLAY_BUDGET_HEADROOM), (
        f"budget {budget}s is not {bound}s minus the declared "
        f"{REPLAY_BUDGET_HEADROOM}s of headroom")


def test_no_budget_at_all_leaves_the_replay_exactly_as_it_was():
    """The audit lane's contract, asserted where a reader will look for it.

    ``all`` mode is documented as costing minutes and belongs in a lane with no
    per-test bound. If this file derived a budget there anyway it would cut the
    audit off and report a shortfall for a run that was given all the time it
    asked for — which is the same conflation, pointing the other way.
    """
    for absent in (None, "", 0, 0.0, "none"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys.modules[__name__], "_HARNESS_BOUND", absent)
            assert replay_budget() is None, (
                f"harness bound {absent!r} means NO bound is in effect, but a "
                f"budget of {replay_budget()} was derived from it")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys.modules[__name__], "_HARNESS_BOUND", 180.0)
        assert replay_budget() == 180.0 - REPLAY_BUDGET_HEADROOM






















# ══════════════════════════════════════════════════════════════════════
# #1432 — "the witness was already red" is not "the mutation failed"
# ══════════════════════════════════════════════════════════════════════
# These guards are built from ReplayResult values rather than from real
# replays ON PURPOSE. The property under test is the SCORING of a measured
# outcome, and the audit-grade `all` mode that surfaces these pairs costs
# minutes per parametrisation. A real already-red replay IS measured, in
# ~2s, by test_matrix_artefact_mutation_channel.py's
# `test_control_the_baseline_must_pass_or_the_entry_is_already_red`, which
# pins `verdict == "ALREADY_RED"`; these guards pin what the three consumers
# then DO with that verdict.
















def test_the_unmeasurable_count_is_disclosed_not_skipped():
    """PROHIBITION 1, the disclosure half.

    The grid records ``unmeasurable=`` in its ``matrix_mutation_replay``
    property. Pinned against the source so the count cannot be dropped from the
    disclosure while the ratchet keeps passing.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    assert "unmeasurable={len(unmeasurable)}" in src, (
        "the replay property no longer discloses the unmeasurable count; a "
        "reader of the grid's PASS could not tell how much of it was measured")


# ══════════════════════════════════════════════════════════════════════
# #1403 — the replay's own BOUND firing is not a verdict about the gate
# ══════════════════════════════════════════════════════════════════════
# Reproduced on bare `origin/main`, this file's two replay-driven tests
# selected ALONE under the real harness contract (`--timeout=180
# --timeout-method=thread`): two `Timeout` banners, NO summary line, rc=1, the
# stack inside `_run_cell`'s `subprocess.run`. No batch, no interaction — the
# measurement simply did not finish.
#
# That red is indistinguishable, to a harness reading exit codes, from the red
# that means "a mutation stopped reddening its witness" — which is the whole
# subject of #1403, and which cost the fleet a standing brief pointed at a
# regression that was not there. The distinction has to live in the OUTPUT.
#
# THE CELL IS NO LONGER BOUNDED BY A CLOCK. It is supervised by forward
# progress, so what these tests must produce is not "a cell that is slow" — a
# slow cell now runs to completion, which is the whole point — but a cell that
# has STOPPED MOVING. The knob below is therefore a CADENCE, not a deadline:
# how many times to LOOK, and how far apart.
#
# `poll_s` is 1.0 s and not something smaller on purpose. pytest's own start-up
# costs about 0.65 s idle and over 2 s under load, and a stall window narrower
# than that boot floor would trip on the boot rather than on the sleep — the
# test would still go green and would be measuring the wrong thing. At three
# looks a second apart the child's own start-up keeps the meter alive, and the
# stall is caused by the probe going quiet. These tests cost ~4 s each.
_LOOKS_THAT_ALWAYS_STALL = {"stall_looks": 3, "poll_s": 1.0}

#: THE SUBJECT THESE THREE TESTS KILL, and it is no longer a real matrix cell.
#:
#: They used to point `_run_cell` at `D3-UNDECLARED-ARTEFACT`'s witness on the
#: argument that one second was "small enough to fire on any cell". That stopped
#: being true when dimension 3's cell learned to SKIP where the published corpus
#: is not in the checkout: the child now returns before the bound can fire, so
#: the kill this file exists to measure never happens. Measured on `ee849c19e`,
#: five consecutive runs of that exact call at a 60 s bound:
#:
#:     rc=0  `1 skipped in 0.65s`   child 0.89 s
#:     rc=0  `1 skipped in 0.62s`   child 0.84 s
#:     rc=0  `1 skipped in 0.60s`   child 0.81 s
#:     rc=0  `1 skipped in 0.60s`   child 0.81 s
#:     rc=0  `1 skipped in 0.62s`   child 0.83 s
#:
#: 0.81 s < 1 s, so all three tests were RED on an idle host and green only on a
#: host slow enough to push pytest's own start-up past the bound — a control
#: whose verdict is a property of the machine. Nothing about the claim under
#: test — that an unreadable child returns a reason instead of raising, and is
#: never given a colour — was ever about which cell was killed.
#:
#: The probe now sleeps FOREVER rather than for thirty seconds. Under a clock,
#: thirty seconds was simply longer than the bound; under progress supervision
#: the question is different, and a thirty-second sleep would eventually WAKE
#: and answer. A probe that never wakes is motionless on CPU, on I/O and on
#: output for as long as anyone looks, which is exactly the state the
#: supervisor is defined to catch — and, unlike a duration, it is that state on
#: every host.
_A_CELL_THAT_CANNOT_FINISH = ("import time\n\n\n"
                              "def test_probe():\n"
                              "    while True:\n"
                              "        time.sleep(3600)\n")














# ══════════════════════════════════════════════════════════════════════
# 4. NOT-FALSIFIABLE IS PUBLISHED, NOT BURIED
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Guards on this file's own instruments
# ══════════════════════════════════════════════════════════════════════
#: Dimensions of the live matrix that this ledger does NOT carry cells for,
#: each with the reason. `CELL_TESTS` is what decides the ledger's grid, and
#: nothing required it to cover every declared dimension — so a dimension added
#: to the matrix simply contributed no cells here and no test said a word.
#: Silent absence is the one thing this campaign refuses, so it is named.
LEDGER_DIMENSIONS_NOT_COVERED: Dict[int, str] = {
    9: ("verdict_consumed, added 2026-08-21. Its cells are NOT in this ledger. "
        "Registering them means a measured `applies_to` sweep over all 69 "
        "steps for each mutation shape, which is a sweep this change did not "
        "run — and an entry whose applies_to was not measured is exactly what "
        "LOCK 1 exists to refuse. The dimension is not unguarded in the "
        "meantime: test_matrix_d9_verdict_consumed.py carries its own mutation "
        "arms for all three legs plus both control arms, and they RUN on every "
        "session. What is missing is this ledger's per-cell reach, not "
        "falsifiability evidence."),
}

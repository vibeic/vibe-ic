"""test_matrix_mutation_ledger.py — the STANDING gate: a cell may not be called
ENFORCED unless a NAMED mutation is known to redden it, and a new flow step may
not arrive with eight unfalsifiable cells.

    ``test_matrix_63x8_coverage.py`` proves every one of the 504 cells has a
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

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pytest
import yaml

import matrix_mutation_ledger as L
from matrix_63x8 import flowref as F
from matrix_63x8.cells import DIMENSION_NAMES, DIMENSIONS


def _domain_progress(scope: str, completed: int, total: int) -> None:
    plugin = sys.modules.get("_pytest_progress_plugin")
    progress = getattr(plugin, "domain_progress", None)
    if callable(progress):
        progress(scope, completed, total)

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
from _published_corpus import corpus_root, needs_corpus  # noqa: E402


def _artefact_names_when_unreadable() -> frozenset:
    """Entry names this checkout cannot speak about: empty wherever it can.

    Returns the ARTEFACT_MUTATION names only while the published corpus is
    absent. With a corpus present this is empty, so every caller's aggregate is
    exactly the one it was before — including its ability to FAIL.
    """
    if corpus_root() is not None:
        return frozenset()
    return frozenset(m.name for m in L.ARTEFACT_MUTATIONS)

TESTS_DIR = Path(__file__).resolve().parent
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
@lru_cache(maxsize=1)
def dimension_modules() -> Dict[int, object]:
    """``{dim: module}``, keyed by each module's own ``DIM`` constant.

    Same shape as the coverage meta-test's loader, and for the same reason: a
    mislabelled module must be a duplicate-dimension failure, not a silent
    double count.
    """
    out: Dict[int, object] = {}
    for path in sorted(TESTS_DIR.glob(DIMENSION_MODULE_GLOB)):
        spec = importlib.util.spec_from_file_location(f"_matmut_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        dim = getattr(mod, "DIM", None)
        assert isinstance(dim, int), f"{path.name} declares no integer DIM"
        assert dim not in out, f"{path.name} re-declares DIM={dim}"
        out[dim] = mod
    return out


#: A cell whose owning dimension module could not answer at all, carrying the
#: reason. NEVER folded into ENFORCED/WAIVED/NA: an unanswerable cell is a third
#: state, and the whole point of naming it is that "I could not look" must not
#: read the same as "I looked and it was fine".
UNREADABLE = "UNREADABLE: "


@lru_cache(maxsize=1)
def cell_states() -> Dict[Tuple[str, int], str]:
    """``{(step, dim): state}`` — live, from the eight owning modules.

    ONE UNANSWERABLE CELL USED TO POISON ALL 552. `matrix_cell_state` raises
    when its dimension cannot place a step — dimension 3 does exactly that for
    a step with no record in `matrix_d3_output_manifest.json` — and the
    exception escaped this loop, so `cell_states()` itself blew up and EVERY
    parametrized case of `test_every_enforced_cell_carries_a_named_mutation`
    went red. MEASURED with the growth control's own synthetic step spliced in:
    69 of the 70 reported step ids were perfectly covered steps reporting a
    failure about a step that is not them, and the one real cause appeared
    only inside a traceback. A gate that reddens everything names nothing.

    The failure is therefore ATTRIBUTED to the cell that produced it and every
    other module still answers. It is not swallowed: an `UNREADABLE` cell is
    neither ENFORCED nor covered, so the per-step test below refuses on it
    explicitly rather than letting the census count it as "not enforced".
    """
    mods = dimension_modules()
    assert sorted(mods) == list(range(1, 9)), (
        f"expected eight dimension modules, found {sorted(mods)}; a dimension "
        f"with no module contributes {len(F.step_ids())} cells this gate can "
        f"neither state nor falsify")
    out: Dict[Tuple[str, int], str] = {}
    for dim, mod in mods.items():
        for sid in F.step_ids():
            try:
                state = mod.matrix_cell_state(sid)
            except Exception as exc:                        # noqa: BLE001
                state = f"{UNREADABLE}d{dim} could not place step {sid!r}: {exc}"
            out[(F.normalize_id(sid), dim)] = state
    return out


def enforced_cells() -> List[Tuple[str, int]]:
    return sorted(k for k, v in cell_states().items() if v == "ENFORCED")


# ══════════════════════════════════════════════════════════════════════
# The review gate on the ledger's own size
# ══════════════════════════════════════════════════════════════════════
def grid_findings(states: Dict[Tuple[str, int], str],
                  step_ids: Sequence[str],
                  pinned_grid: Tuple[int, int, int],
                  pinned_not_enforced: Sequence[Tuple[str, int, str]],
                  ) -> Tuple[str, ...]:
    """Everything this grid does that the pin was not measured against.

    PURE, and deliberately so. The control below drives it in BOTH directions
    with synthetic grids, which is the only way to show that a gate whose live
    answer is "nothing wrong" would still say no — and it plants nothing in the
    corpus to do it. A guard whose only falsification is a manual experiment is
    a guard nobody re-runs.

    Returns one finding per cell, never a bare boolean: the count is what
    vibe-ic#1421 records as insufficient, because ``482 -> 479`` cannot say
    whether three enforcements were retired on purpose or three gates stopped
    catching, and two cells trading places says nothing at all.
    """
    out: List[str] = []
    measured = (len(step_ids), 8,
                sum(1 for v in states.values() if v == "ENFORCED"))
    if measured != tuple(pinned_grid):
        out.append(f"the grid's shape changed: measured {measured} "
                   f"(steps, dimensions, ENFORCED cells), pinned "
                   f"{tuple(pinned_grid)}")

    pinned = {(str(s), int(d)): str(st) for s, d, st in pinned_not_enforced}
    live = {k: v for k, v in states.items() if v != "ENFORCED"}

    for cell in sorted(set(live) - set(pinned)):
        out.append(f"{cell[0]}/d{cell[1]} LEFT ENFORCED and is now "
                   f"{live[cell]} — it is not in LEDGER_CELLS_NOT_ENFORCED")
    for cell in sorted(set(pinned) - set(live)):
        was = pinned[cell]
        now = states.get(cell)
        if now is None:
            out.append(f"{cell[0]}/d{cell[1]} was pinned {was} and is no "
                       f"longer a cell of this grid")
        else:
            out.append(f"{cell[0]}/d{cell[1]} was pinned {was} and is now "
                       f"{now} — a cell GAINED enforcement")
    for cell in sorted(set(pinned) & set(live)):
        if pinned[cell] != live[cell]:
            out.append(f"{cell[0]}/d{cell[1]} changed state "
                       f"{pinned[cell]} -> {live[cell]}")
    return tuple(out)


def test_the_ledger_grid_matches_what_was_measured():
    """Steps, dimensions, the ENFORCED count AND the cells that are not.

    Everything else in this file computes from the live flow. This one place
    compares the computed value against numbers a human signed off on, for
    exactly the reason ``GRID_AS_MEASURED`` exists in the coverage meta-test: a
    64th step would be picked up everywhere and the arithmetic would keep
    partitioning tidily, which is precisely the silent shape to refuse.

    THE COUNT ALONE WAS NOT ENOUGH, and vibe-ic#1421 is the record of it. A
    flow-yaml change reclassified three cells and moved the count from 482 to
    479 in a commit that never touched this file — so the failure read as a
    batch INTERACTION, and the only repair the message offered was to re-pin
    the number, which is indistinguishable from covering up three gates that
    stopped catching. Worse, the pin's own bisect note records ``23d96bf5``
    swapping two cells "for a net change of zero": a real state change the
    scalar could not see at all. The inventory names the cell in both cases.
    """
    findings = grid_findings(cell_states(), F.step_ids(),
                             L.LEDGER_AS_MEASURED, L.LEDGER_CELLS_NOT_ENFORCED)
    assert findings == (), (
        "the ledger's grid no longer matches what was measured:\n  "
        + "\n  ".join(findings) + "\n"
        f"steps now in the flow that no ledger entry was measured against: "
        f"{sorted(set(F.normalize_id(s) for s in F.step_ids()) - measured_steps())}\n"
        "Every ENFORCED cell needs a mutation that was RUN against it. Run "
        "`python3 programs/matrix_mutation_ledger.py --census --resolve`, add "
        "the measured entries, then update LEDGER_AS_MEASURED *and* "
        "LEDGER_CELLS_NOT_ENFORCED in the SAME change as the flow edit that "
        "moved them — never after it. A cell moving OUT of ENFORCED must say "
        "which cell and why; a lowered count with no named cell is the shape "
        "this gate exists to refuse.")


def test_the_grid_gate_names_the_cell_that_moved():
    """The control: this gate says no, and says WHICH cell, in both directions.

    Driven against :func:`grid_findings` with synthetic copies of the live
    grid. Nothing is written and no subprocess is launched, so it costs
    milliseconds and runs on every invocation rather than living in a comment.

    The fourth case is the one that justifies the inventory existing. A cell
    leaving ENFORCED and another entering it in the same change leaves the
    count at exactly the pinned value, so the tuple comparison this file
    shipped before vibe-ic#1421 is GREEN on it — asserted here directly, not
    described — while the inventory reports both cells by name.
    """
    live = dict(cell_states())
    pinned_grid = L.LEDGER_AS_MEASURED
    pinned_cells = L.LEDGER_CELLS_NOT_ENFORCED

    def shape(states):
        """Exactly the comparison this gate made before the inventory."""
        return (len(F.step_ids()), 8,
                sum(1 for v in states.values() if v == "ENFORCED"))

    def moved(*pairs):
        """A COPY of the live grid with each ``(cell, state)`` applied."""
        out = dict(live)
        for cell, state in pairs:
            out[cell] = state
        return out

    # 0. the live grid, unmodified. If this is not silent the cases below
    #    prove nothing, so it is asserted here rather than assumed.
    assert grid_findings(live, F.step_ids(), pinned_grid, pinned_cells) == ()

    an_enforced = sorted(k for k, v in live.items() if v == "ENFORCED")[0]
    a_pinned = (str(pinned_cells[0][0]), int(pinned_cells[0][1]))

    # 1. a cell LOSES enforcement -> named, with the state it landed in.
    lost = moved((an_enforced, "NA"))
    found = grid_findings(lost, F.step_ids(), pinned_grid, pinned_cells)
    assert any(f"{an_enforced[0]}/d{an_enforced[1]} LEFT ENFORCED" in f
               for f in found), found

    # 2. a cell GAINS enforcement -> named. The count moves the other way, so
    #    a pin that only ever grew would miss nothing here; the point is that
    #    the cell is named rather than left to a diff of two integers.
    gained = moved((a_pinned, "ENFORCED"))
    found = grid_findings(gained, F.step_ids(), pinned_grid, pinned_cells)
    assert any(f"{a_pinned[0]}/d{a_pinned[1]} was pinned" in f
               and "GAINED enforcement" in f for f in found), found

    # 3. a non-ENFORCED cell changes KIND (a live NA becoming a registered
    #    waiver, or the reverse). The count cannot move at all.
    other = "WAIVED" if live[a_pinned] == "NA" else "NA"
    switched = moved((a_pinned, other))
    assert shape(switched) == tuple(pinned_grid)
    found = grid_findings(switched, F.step_ids(), pinned_grid, pinned_cells)
    assert any(f"{a_pinned[0]}/d{a_pinned[1]} changed state" in f
               for f in found), found

    # 4. THE NET-ZERO SWAP. One cell out, one cell in, count unchanged.
    swapped = moved((an_enforced, "NA"), (a_pinned, "ENFORCED"))
    assert shape(swapped) == tuple(pinned_grid), (
        "the swap must leave the shape tuple identical, or this case is not "
        "testing what it claims to")
    found = grid_findings(swapped, F.step_ids(), pinned_grid, pinned_cells)
    assert any(f"{an_enforced[0]}/d{an_enforced[1]} LEFT ENFORCED" in f
               for f in found), found
    assert any(f"{a_pinned[0]}/d{a_pinned[1]} was pinned" in f
               for f in found), found
    assert not any("the grid's shape changed" in f for f in found), (
        "the shape arm must be SILENT on a net-zero swap — that silence is "
        "the defect the inventory was added to cover, and if the shape arm "
        "starts firing here this control stops proving anything: " + str(found))


@lru_cache(maxsize=1)
def measured_steps() -> frozenset:
    """Every step id any ledger entry was actually run against."""
    return frozenset(s for m in L.MUTATIONS for s in m.applies_to)


# ══════════════════════════════════════════════════════════════════════
# 1. AN ENFORCED CELL WITH NO NAMED MUTATION
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "sid", [F.normalize_id(s) for s in F.step_ids()],
    ids=lambda s: f"step{s}")
def test_every_enforced_cell_carries_a_named_mutation(sid):
    """For each of this step's 8 cells: ENFORCED implies a measured mutation.

    The state comes from the dimension module that owns the cell. A cell that is
    WAIVED (strict xfail, registered reason) or NA (asserted live precondition)
    is already accounted for by the coverage meta-test and needs no mutation
    here — that is the reverse case, and it must keep passing.
    """
    states = cell_states()
    problems: List[str] = []
    for dim in range(1, 9):
        state = states[(sid, dim)]
        if state.startswith(UNREADABLE):
            problems.append(
                f"{sid}/d{dim}:{DIMENSION_NAMES[dim]} could not be READ at "
                f"all, so its falsifiability is UNKNOWN rather than fine — "
                f"{state[len(UNREADABLE):]}")
            continue
        if state != "ENFORCED":
            continue
        covering = L.mutations_covering(sid, dim)
        if covering:
            continue
        nf = L.not_falsifiable_for(sid, dim)
        if nf is not None:
            problems.append(
                f"{sid}/d{dim}:{DIMENSION_NAMES[dim]} is recorded "
                f"NOT-FALSIFIABLE ({nf.observed}) yet the module still reports "
                f"ENFORCED — a cell nothing can redden is not enforcing "
                f"anything, and the two statements cannot both stand")
            continue
        problems.append(
            f"{sid}/d{dim}:{DIMENSION_NAMES[dim]} is ENFORCED and NO mutation "
            f"in matrix_mutation_ledger.MUTATIONS was measured to redden it. "
            f"A green cell with no reachable red is a certificate, not a "
            f"measurement.")
    assert not problems, (
        f"step {sid}: {len(problems)} cell(s) enforce nothing anyone has "
        f"shown can fail:\n  - " + "\n  - ".join(problems) +
        f"\n\nBuild the mutation, RUN it, and record it:\n"
        f"  python3 programs/matrix_mutation_ledger.py --census\n"
        f"  python3 programs/matrix_mutation_ledger.py --replay <NAME> "
        f"--step {sid}\n"
        f"If no mutation can redden the cell, that is the FINDING: record it in "
        f"NOT_FALSIFIABLE with what was tried. Never weaken the predicate, "
        f"widen a waiver, or edit a fixture to suit.")


def test_the_coverage_is_complete_and_the_count_is_stated(record_property):
    """One aggregate statement, so a CI reader gets the number without reading
    504 parametrized results — and so an empty census cannot pass quietly."""
    states = cell_states()
    rep = L.census(states)
    record_property("matrix_mutation_census", json.dumps(
        {k: rep[k] for k in ("steps", "considered", "covered", "entries",
                             "replay_mode", "replay_pairs")}))
    assert rep["considered"] == len(enforced_cells()) > 0, rep
    assert not rep["uncovered"], (
        f"{len(rep['uncovered'])} ENFORCED cell(s) carry no measured "
        f"mutation: {rep['uncovered'][:24]}")
    assert rep["covered"] == rep["considered"], rep


# ══════════════════════════════════════════════════════════════════════
# 2. A FLOW THAT GREW A STEP
# ══════════════════════════════════════════════════════════════════════
def test_the_flow_declares_no_step_the_ledger_never_measured():
    """The named half of the growth gate: report the NEW STEP, not 8 anonymous
    uncovered cells.

    ``test_every_enforced_cell_carries_a_named_mutation`` would also go red, but
    it would go red eight times over with no statement of why. This says it
    once, with the step id, which is what an author needs.
    """
    live = [F.normalize_id(s) for s in F.step_ids()]
    unmeasured = [s for s in live if s not in measured_steps()]
    assert not unmeasured, (
        f"the flow declares {len(unmeasured)} step(s) that no mutation in the "
        f"ledger was ever run against: {unmeasured}.\n"
        f"Each brings 8 cells whose falsifiability nobody has measured. "
        f"流程長一個步驟，覆蓋就自動變不完整 — and this is the line that stops "
        f"the push rather than describing the problem afterwards.\n"
        f"For each new step: pick the mutation family whose edit site it has, "
        f"RUN it (`--replay <NAME> --step <id>`), and add the step to that "
        f"entry's applies_to together with the updated `reddened` count.")


def _flow_with_an_extra_step() -> Dict:
    """A copy of the live flow with one synthetic step appended.

    The step is a faithful shape — id, name, stage, a gate with an executable
    clause, required_outputs, blocks_on — so every dimension module has
    something real to look at. That matters: a degenerate step could be excused
    by an NA precondition and the control would prove nothing.
    """
    doc = copy.deepcopy(L.load_flow())
    doc["steps"].append({
        "id": CANARY_STEP_ID,
        "name": "synthetic step spliced in by the mutation-ledger growth control",
        "stage": "stage3",
        "programs": ["drc_report_check"],
        "gate": {"all_of": [
            {"program_exit_zero":
                "drc_report_check . --json reports/phase3/zzcanary_drc.json"},
        ]},
        "required_outputs": ["reports/phase3/zzcanary_drc.json"],
        "blocks_on": [44],
    })
    return doc


def test_a_grown_flow_arrives_with_uncovered_cells(tmp_path):
    """CONTROL (negative direction): splice in a 64th step, and the ledger's own
    census must report its cells uncovered.

    This is the cheap half — it exercises the ledger's arithmetic against a
    grown flow without paying for a subprocess. The expensive half, which runs
    the REAL gate, is the next test.

    A DELTA, NOT AN ABSOLUTE, and that is the repair this test needed. It used
    to open with `assert not before["uncovered"]`, which made it report SOMEONE
    ELSE'S finding and stop measuring its own: the ledger's own comment on
    :data:`LEDGER_AS_MEASURED` says `0.5ic/d3` is honestly uncovered and must
    stay that way, so from the day that cell arrived this control was red for a
    reason that has nothing to do with a flow that grew. Two tests already say
    `0.5ic/d3` — `test_every_enforced_cell_carries_a_named_mutation[step0.5ic]`
    and the aggregate above — and a third saying it in a growth control is not
    a third finding, it is a control that stopped controlling. What this test
    owns is the DIFFERENCE the extra step makes, so that is what it asserts:
    exactly the canary's eight cells arrive, and no pre-existing uncovered cell
    is lost on the way (a census that dropped one would otherwise pass here).
    """
    grown = tmp_path / "grown_flow.yaml"
    grown.write_text(yaml.safe_dump(_flow_with_an_extra_step(), sort_keys=False,
                                    allow_unicode=True), encoding="utf-8")
    states = dict(cell_states())
    for dim in range(1, 9):
        states[(CANARY_STEP_ID, dim)] = "ENFORCED"

    before = L.census(cell_states())

    old = os.environ.get(L.FLOW_YAML_ENV)
    os.environ[L.FLOW_YAML_ENV] = str(grown)
    try:
        after = L.census(states)
    finally:
        if old is None:
            os.environ.pop(L.FLOW_YAML_ENV, None)
        else:
            os.environ[L.FLOW_YAML_ENV] = old

    assert after["steps"] == before["steps"] + 1
    baseline = set(before["uncovered"])
    grown_set = set(after["uncovered"])
    assert baseline <= grown_set, (
        f"growing the flow LOST uncovered cell(s) {sorted(baseline - grown_set)} "
        f"— the census answered a smaller question about a bigger flow")
    assert sorted(grown_set - baseline) == sorted(
        f"{CANARY_STEP_ID}/d{d}" for d in range(1, 9)), (
        f"a new step must arrive with exactly its own 8 cells uncovered; the "
        f"grown census added {sorted(grown_set - baseline)} over a baseline of "
        f"{sorted(baseline)}")


def test_the_gate_itself_reddens_on_a_grown_flow(tmp_path):
    """CONTROL (bidirectional, end to end): the REAL gate, on the REAL grown
    flow, in a subprocess.

    The previous test measures the ledger's arithmetic. This one measures the
    gate: it re-runs ``test_every_enforced_cell_carries_a_named_mutation``
    against a flow with a synthetic 64th step and requires a non-zero exit that
    NAMES the step. Without this the growth claim would rest on a census
    function agreeing with itself.

    BOTH DIRECTIONS, AS A DIFFERENCE OF FAILING CASES rather than as
    `clean_run.returncode == 0`. The absolute form was the right control only
    while the live census was perfectly covered; the moment one cell became
    honestly uncovered — `0.5ic/d3`, which the ledger argues at length must
    STAY uncovered — the clean arm exited 1, this test went red, and the growth
    claim it exists to certify stopped being measured at all. Worse, the red it
    reported was a restatement of a finding two other tests already name.

    What the control actually needs is that the gate DISCRIMINATES: the grown
    flow must fail for the canary and the clean flow must not. So both arms are
    run with `-rf`, their FAILING parametrized step ids are compared, and the
    difference must be exactly the canary. That still catches a gate red on
    everything (the canary would then be in the clean set too) and it also
    catches the opposite defect the old form could not see: a gate that stops
    reddening some OTHER step keeps the exit code at 1 and would have passed.
    """
    grown = tmp_path / "grown_flow.yaml"
    grown.write_text(yaml.safe_dump(_flow_with_an_extra_step(), sort_keys=False,
                                    allow_unicode=True), encoding="utf-8")
    name = "test_every_enforced_cell_carries_a_named_mutation"
    node = str(Path("programs/tests") / Path(__file__).name) + "::" + name

    def run(flow_override):
        env = dict(os.environ)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        if flow_override is None:
            env.pop(L.FLOW_YAML_ENV, None)
        else:
            env[L.FLOW_YAML_ENV] = str(flow_override)
        return subprocess.run(
            [sys.executable, "-m", "pytest", node,
             "-q", "-p", "no:randomly", "--no-header", "-rf"],
            cwd=str(L.PLUGIN_ROOT), capture_output=True, text=True,
            timeout=_PYTEST_TIMEOUT_S, env=env)

    def failing_steps(proc):
        return {m.group(1) for m in
                re.finditer(rf"^FAILED .*::{name}\[step(.+?)\]\s*$",
                            proc.stdout, re.MULTILINE)}

    grown_run = run(grown)
    assert grown_run.returncode != 0, (
        f"the gate PASSED against a flow that grew a step. {node} is not "
        f"stopping anything.\n{grown_run.stdout[-3000:]}")
    assert CANARY_STEP_ID in grown_run.stdout, (
        f"the gate reddened on the grown flow but never named the new step, so "
        f"an author cannot act on it:\n{grown_run.stdout[-3000:]}")

    clean_run = run(None)
    grown_failed = failing_steps(grown_run)
    clean_failed = failing_steps(clean_run)
    assert grown_failed, (
        "the grown run named no failing step at all; the -rf summary this "
        f"control reads is missing:\n{grown_run.stdout[-3000:]}")
    assert CANARY_STEP_ID not in clean_failed, (
        f"the gate names the synthetic step even with the UNMODIFIED flow, so "
        f"the growth control above proves nothing — a gate that fails on "
        f"everything fails on a new step too.\n{clean_run.stdout[-4000:]}")
    assert grown_failed - clean_failed == {CANARY_STEP_ID}, (
        f"growing the flow by one step must change the gate's verdict by "
        f"exactly that step. clean={sorted(clean_failed)} "
        f"grown={sorted(grown_failed)}\n{grown_run.stdout[-3000:]}")
    assert clean_failed <= grown_failed, (
        f"the grown flow made the gate STOP naming "
        f"{sorted(clean_failed - grown_failed)}; splicing in a step may add a "
        f"finding and may never retire one")


def test_reverse_case_reordering_the_flow_does_not_trip_the_gate(tmp_path):
    """REVERSE CASE (must STILL pass): moving a step's DECLARATION does not
    change the population, so the gate must stay quiet.

    A gate that fires on any yaml edit is not a coverage gate, it is a diff
    alarm. The dimension-5 waiver closures landed by moving A6, DT2 and DT3 in
    the declaration order; that class of change must not cost anyone a red here.

    ORDER is what this measures, so the eight ARTEFACT entries are set aside
    where their published run is not in the checkout (see
    ``_artefact_names_when_unreadable``): they are unresolvable for a reason the
    reordering did not cause, and letting them redden this test would blame the
    yaml for a corpus that moved. With a corpus present nothing is set aside.
    """
    deaf = _artefact_names_when_unreadable()
    doc = copy.deepcopy(L.load_flow())
    steps = doc["steps"]
    steps.insert(0, steps.pop())            # last step declared first
    steps.append(steps.pop(1))              # and one from the middle to the end
    shuffled = tmp_path / "reordered_flow.yaml"
    shuffled.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")

    baseline = L.census(cell_states())
    old = os.environ.get(L.FLOW_YAML_ENV)
    os.environ[L.FLOW_YAML_ENV] = str(shuffled)
    try:
        rep = L.census(cell_states())
        bad = [u for u in L.unresolved() if u[0] not in deaf]
        assert not bad, (
            f"reordering the flow made {len(bad)} recorded edit "
            f"site(s) unresolvable; LOCK 1 must key off step ids, not order:\n"
            f"  - " + "\n  - ".join(f"{n} @ step {s}: {p}" for n, s, p in bad))
    finally:
        if old is None:
            os.environ.pop(L.FLOW_YAML_ENV, None)
        else:
            os.environ[L.FLOW_YAML_ENV] = old
    # UNCHANGED, not EMPTY. `assert not rep["uncovered"]` was a statement about
    # the live census's coverage, which is not what this test measures and not
    # what reordering can affect: once `0.5ic/d3` became honestly uncovered it
    # made this reverse case red for a reason the reordering did not cause —
    # precisely the failure mode the docstring above warns about one paragraph
    # earlier for the ARTEFACT entries. What must hold is that the SET does not
    # move: a reorder that covered a cell would be as wrong as one that
    # uncovered a cell, and both are caught by comparing sets.
    assert sorted(rep["uncovered"]) == sorted(baseline["uncovered"]), (
        f"reordering the flow changed which cells are uncovered: "
        f"{sorted(baseline['uncovered'])} -> {sorted(rep['uncovered'])}")
    assert rep["steps"] == len(F.step_ids())


def test_reverse_case_a_waived_or_na_cell_needs_no_mutation():
    """REVERSE CASE (must STILL pass): the gate speaks only about ENFORCED.

    WAIVED cells are strict xfails with a registered, evidence-backed reason and
    NA cells assert a live precondition; both are the coverage meta-test's
    business. Demanding a mutation for them would push authors toward calling a
    genuinely inapplicable cell ENFORCED, which is the opposite of the point.
    """
    states = cell_states()
    non_enforced = [k for k, v in states.items() if v != "ENFORCED"]
    assert non_enforced, (
        "no cell is WAIVED or NA anywhere in the grid; this reverse case is "
        "measuring nothing and must be re-pointed at a real one")
    rep = L.census(states)
    uncovered = set(rep["uncovered"])
    for sid, dim in non_enforced:
        assert f"{sid}/d{dim}" not in uncovered, (
            f"{sid}/d{dim} is {states[(sid, dim)]} yet the gate demands a "
            f"mutation for it")


# ══════════════════════════════════════════════════════════════════════
# 3. A MUTATION WRITTEN DOWN BUT NEVER RUN — LOCKS 1, 2, 3
# ══════════════════════════════════════════════════════════════════════
def test_lock1_every_recorded_edit_site_still_exists():
    """LOCK 1: re-resolve all 697 (entry, step) pairs against the live tree.

    An entry widened to a step whose gate is the wrong shape is refused here at
    the cost of one yaml parse — no pytest, no subprocess. This is also the
    anti-rot half: a refactor that moves the ``_STRUCTURAL_RTL_GATES`` literal
    or drops a step's ``files_exist`` key makes the recorded edit unreproducible
    and says so, instead of leaving a stale proof in place.

    ``L.unresolved()`` spans all three channels. The eight ARTEFACT entries in
    it resolve against a PUBLISHED RUN, so where the corpus is not in the
    checkout they are set aside here and asserted — unchanged, at full strength —
    by ``test_matrix_artefact_mutation_channel.py::
    test_lock1_the_entry_resolves_against_the_live_tree``, which skips naming the
    corpus in exactly the same condition. The 691 yaml/tree pairs are still
    re-resolved on every run, and with a corpus present this line is the one that
    was here before.
    """
    deaf = _artefact_names_when_unreadable()
    bad = [u for u in L.unresolved() if u[0] not in deaf]
    pairs = sum(len(m.applies_to) for m in L.MUTATIONS)
    assert pairs > 0
    assert not bad, (
        f"{len(bad)} of {pairs} recorded (mutation, step) pair(s) no longer "
        f"resolve against {L.flow_yaml_path()}:\n  - " +
        "\n  - ".join(f"{n} @ step {s}: {p}" for n, s, p in bad[:20]))


def test_lock3_every_entry_is_arithmetically_consistent_with_its_own_evidence():
    """LOCK 3: the recorded numbers must agree with the recorded lists.

    This is what makes a forged entry a lie about a number rather than an
    omission nobody sees. Widening ``applies_to`` without re-running forces the
    author to also alter ``reddened``, and to keep ``baseline_red`` a subset and
    ``stayed_green`` disjoint — all of it visible in one diff hunk.
    """
    assert len(L.MUTATIONS) >= 8, (
        f"the ledger holds {len(L.MUTATIONS)} entries. Every assertion in this "
        f"test is vacuously true over an empty tuple, and eight dimensions "
        f"cannot be carried by fewer than eight entries — an emptied ledger "
        f"must be a red here and not a quiet green.")
    problems: List[str] = []
    seen_names = set()
    for m in L.MUTATIONS:
        if m.name in seen_names:
            problems.append(f"{m.name}: duplicate entry name")
        seen_names.add(m.name)
        if m.dim not in range(1, 9):
            problems.append(f"{m.label}: dimension {m.dim} is outside 1..8")
        if m.channel not in L.CHANNELS:
            problems.append(f"{m.label}: unknown channel {m.channel!r}")
        if m.kind not in L.KINDS:
            problems.append(f"{m.label}: unknown kind {m.kind!r}")
        if not m.applies_to:
            problems.append(f"{m.label}: claims no step at all")
        if len(set(m.applies_to)) != len(m.applies_to):
            problems.append(f"{m.label}: applies_to has duplicates")
        if m.measured.reddened != len(m.applies_to):
            problems.append(
                f"{m.label}: measured.reddened={m.measured.reddened} but "
                f"applies_to lists {len(m.applies_to)} step(s) — the count and "
                f"the list cannot disagree")
        extra = set(m.measured.baseline_red) - set(m.applies_to)
        if extra:
            problems.append(
                f"{m.label}: baseline_red names {sorted(extra)}, which "
                f"applies_to does not — a cell cannot be 'already red' in a "
                f"sweep that never reddened it")
        overlap = set(m.measured.stayed_green) & set(m.applies_to)
        if overlap:
            problems.append(
                f"{m.label}: {sorted(overlap)} is recorded both red and green")
        if m.witness not in m.applies_to:
            problems.append(
                f"{m.label}: witness {m.witness!r} is not in applies_to, so the "
                f"replayed pair is not one the entry claims")
        if m.witness in m.measured.baseline_red:
            problems.append(
                f"{m.label}: witness {m.witness!r} is ALREADY red at baseline; "
                f"a replay against it can never show PASS -> FAIL")
        for field_name, floor in (("what", 30), ("breaks", 40),
                                  ("red_signal", 2)):
            value = getattr(m, field_name) or ""
            if len(value.strip()) < floor:
                problems.append(
                    f"{m.label}: {field_name} is under the {floor}-character "
                    f"floor — {value!r} cannot be checked by someone who has "
                    f"never seen the cell")
        if not m.measured.date or not m.measured.command:
            problems.append(f"{m.label}: measurement has no date or no command")
    assert not problems, (
        f"{len(problems)} ledger consistency problem(s):\n  - " +
        "\n  - ".join(problems))


def test_the_replay_lock_has_no_off_switch():
    """``VIBE_IC_MATRIX_MUTATION_REPLAY`` accepts two values and refuses the
    rest — including anything that would mean "skip the re-execution".

    An entry nobody re-executes is exactly the asserted-but-never-run mutation
    this whole file exists to refuse, so "off" cannot be spelled.
    """
    assert L.replay_mode() in L.REPLAY_MODES, (
        f"{L.REPLAY_ENV}={os.environ.get(L.REPLAY_ENV)!r} is not one of "
        f"{L.REPLAY_MODES}")
    for bad in ("off", "0", "no", "none", "skip"):
        with pytest.raises(ValueError):
            L.replay_plan(bad)
    # Both ledgers. The ARTEFACT_MUTATION channel has no witness subset — an
    # artefact entry claims exactly one cell — so it contributes its full length
    # to BOTH modes, and an off switch cannot be spelled for it either.
    assert len(L.replay_plan("witness")) == (
        len(L.MUTATIONS) + len(L.ARTEFACT_MUTATIONS)) > 0, (
        "the witness plan is empty; a lock that re-executes nothing is off in "
        "everything but name")
    assert len(L.replay_plan("all")) == sum(
        len(m.applies_to) for m in L.MUTATIONS) + len(L.ARTEFACT_MUTATIONS) > 0
    assert {d for d in (L.mutation(n).dim for n, _ in L.replay_plan("witness"))} \
        == set(range(1, 9)), (
        "the witness plan does not reach all eight dimensions, so a dimension "
        "could carry entries that are never re-executed")


def test_replay_witnesses_replays_the_witness_subset_not_everything(
        monkeypatch, record_property):
    """``--replay-witnesses`` selects the WITNESS subset. Pinned, not assumed.

    The tests above pass the mode EXPLICITLY — ``replay_plan("witness")`` and
    ``replay_plan("all")`` — so they measure the function and say nothing about
    which mode the CLI asks it for. That literal is a DIRECTION, and the module
    docstring argues it in as many words:

        "WHY NOT 'just replay everything, always'. Because it costs minutes,
        and a gate people disable is worse than a gate that states its own
        reach."

    Until this test existed the argument was prose. ``policy_direction_pin_check
    --verify-pins`` flipped the literal to ``'all'`` and reported
    ``changes nothing any test can see`` — the selector for the mechanism built
    to close finding #20 was itself unasserted. Flipping it does not merely
    make the gate slower: it silently turns a bounded, always-on lock into a
    minutes-long one, which is the "gate people disable" the docstring names.

    The plan is captured rather than executed — replaying it for real is the
    minutes this direction exists to avoid, and paying them here would make the
    test the very cost it is pinning.
    """
    seen: List[Sequence[Tuple[str, str]]] = []

    def _capture(plan, **kw):
        seen.append(tuple(plan))
        return ()

    monkeypatch.setattr(L, "replay_many", _capture)
    rc = L.main(["--replay-witnesses"])
    assert rc == 0, f"--replay-witnesses exited {rc} with the replay stubbed out"
    assert len(seen) == 1, (
        f"--replay-witnesses built {len(seen)} plans, expected exactly one")
    got = seen[0]

    witness_plan = L.replay_plan("witness")
    all_plan = L.replay_plan("all")

    # The denominator, disclosed rather than left for a reader to assume, and
    # refused if it is ever zero (a lock that re-executes nothing is off).
    record_property("replay_witnesses_pairs", len(got))
    assert len(got) > 0, (
        "--replay-witnesses built an EMPTY plan; a selector that selects "
        "nothing must refuse, not pass")
    assert len(witness_plan) < len(all_plan), (
        f"the two modes are the same size ({len(witness_plan)}), so this test "
        f"cannot tell them apart and pins nothing; the ledger must carry at "
        f"least one entry whose applies_to is longer than one step")

    assert got == witness_plan, (
        f"--replay-witnesses re-executed {len(got)} (entry, step) pair(s); the "
        f"witness subset is {len(witness_plan)} and the audit-grade 'all' mode "
        f"is {len(all_plan)}. This CLI flag selects the witness subset by "
        f"name — the bounded lock that runs on every invocation — and "
        f"'{L.REPLAY_ENV}=all' is the opt-in for the other one.")
    assert got != all_plan, (
        f"--replay-witnesses built the 'all' plan ({len(all_plan)} pairs). The "
        f"always-on lock would then cost minutes, and the module docstring's "
        f"reason for the default — 'a gate people disable is worse than a gate "
        f"that states its own reach' — would be describing a gate this "
        f"repository no longer ships.")


def test_control_removing_one_entry_uncovers_the_cells_it_carried(monkeypatch):
    """CONTROL: drop one ledger entry and the cells it carried must go uncovered.

    This is the pre-gate direction in miniature. It is the difference between a
    census that reports what is there and a census that would report "complete"
    over any input — and the whole ledger emptied is the same experiment at
    scale: with ``MUTATIONS = ()`` every one of the 63 step items reddens
    (measured 2026-08-06: 69 failed, 7 passed).
    """
    states = cell_states()
    victim = next(m for m in L.MUTATIONS
                  if any(states.get((s, m.dim)) == "ENFORCED"
                         for s in m.applies_to))
    orphaned = {f"{s}/d{victim.dim}" for s in victim.applies_to
                if states.get((s, victim.dim)) == "ENFORCED"
                and len(L.mutations_covering(s, victim.dim)) == 1}
    assert orphaned, (
        f"{victim.name} is the only entry for none of its cells, so removing "
        f"it proves nothing; re-point this control at an entry that is")
    monkeypatch.setattr(
        L, "MUTATIONS", tuple(m for m in L.MUTATIONS if m.name != victim.name))
    after = set(L.census(states)["uncovered"])
    assert orphaned <= after, (
        f"removed {victim.name} and the census still calls "
        f"{sorted(orphaned - after)} covered")


def test_replay_many_reports_only_finite_completed_units_in_result_order(
        monkeypatch):
    monkeypatch.setattr(L, "mutation", lambda name: name)
    monkeypatch.setattr(
        L, "replay", lambda name, step, timeout: f"{name}:{step}:{timeout}")
    progress = []
    result = L.replay_many(
        [("a", "s1"), ("b", "s2"), ("c", "s3")], jobs=3, timeout=7,
        progress_callback=lambda completed, total:
        progress.append((completed, total)),
    )
    assert result == ("a:s1:7", "b:s2:7", "c:s3:7")
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_replay_many_callback_failure_refuses_the_population(monkeypatch):
    monkeypatch.setattr(L, "mutation", lambda name: name)
    monkeypatch.setattr(L, "replay", lambda name, step, timeout: name)

    def refuse(completed, total):
        raise RuntimeError(f"relay refused {completed}/{total}")

    with pytest.raises(RuntimeError, match="relay refused 1/2"):
        L.replay_many(
            [("a", "s1"), ("b", "s2")], jobs=2,
            progress_callback=refuse)


def test_a_cut_off_replay_omits_unstarted_pairs_and_never_a_verdict():
    """BIDIRECTIONAL control on the total wall budget (vibe-ic#1410).

    The budget exists because ``timeout`` bounds one cell and nothing bounded
    the plan, so the aggregate outlives the harness and
    ``--timeout-method=thread`` takes the SESSION — 0 lines matching
    ``passed|failed|error`` in the whole output, which greps as zero failures.

    BOTH arms are asserted, because a budget that quietly swallowed pairs would
    be a worse bug than the one it fixes:

      * BOUNDED — the plan is cut off and the pairs that were never STARTED are
        OMITTED. Not fabricated, not scored, not skipped. The shortfall is what
        ``test_the_replay_actually_ran_and_is_not_starved`` reads.
      * UNBOUNDED (``budget=None``: the audit lane and every previous caller) —
        every pair runs. THIS ARM IS WHAT PROVES THE FIX DID NOT BUY ITS GREEN
        BY MAKING THE REPLAY DO LESS.

    And the boundary between omission and the module's NOT_REPLAYABLE doctrine
    is asserted too: a pair that WAS started keeps its result whatever that
    result says, because omission is only ever the answer for a replay that
    never happened.

    Driven against a stub rather than the real replay: what is under test is the
    SCHEDULING, and a real pair costs tens of seconds.
    """
    plan = tuple((f"M{i}", f"stub{i}") for i in range(12))
    seen_timeouts: List[int] = []

    def stub(mut, sid=None, timeout=900):
        seen_timeouts.append(int(timeout))
        time.sleep(0.2)
        return L.ReplayResult(str(mut), 1, str(sid), True, 0, 1, True, "")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(L, "mutation", lambda name: name)
        mp.setattr(L, "replay", stub)

        progress: List[Tuple[int, int]] = []
        cut = L.replay_many(plan, jobs=1, timeout=REPLAY_TIMEOUT, budget=0.7,
                            progress_callback=lambda c, t:
                            progress.append((c, t)))
        clamped = list(seen_timeouts)
        seen_timeouts.clear()
        full = L.replay_many(plan, jobs=1, timeout=REPLAY_TIMEOUT, budget=None)

        def unreadable(mut, sid=None, timeout=900):
            return L.ReplayResult(str(mut), 1, str(sid), True, None, None,
                                  False, "", 0.0, "REDDENED",
                                  "mutant arm: the bound fired")
        mp.setattr(L, "replay", unreadable)
        started = L.replay_many(plan[:2], jobs=1, timeout=REPLAY_TIMEOUT,
                                budget=30)

    assert 0 < len(cut) < len(plan), (
        f"a 0.7 s budget over {len(plan)} pairs of 0.2 s each returned "
        f"{len(cut)}; the budget either never fired or ate everything")
    assert [r.step_id for r in cut] == [p[1] for p in plan[:len(cut)]], (
        f"the surviving pairs are out of plan order: {[r.step_id for r in cut]}")
    assert all(r.proved for r in cut), (
        "a pair the budget DID reach must keep its real verdict; the budget "
        "may decide what RUNS, never what a run CONCLUDED")
    assert clamped and all(0 < t <= REPLAY_TIMEOUT for t in clamped), (
        f"per-cell clamp went outside (0, {REPLAY_TIMEOUT}]: {clamped}")
    # THE DENOMINATOR MUST NOT SHRINK TO MATCH WHAT WAS ACHIEVED. A cut-off run
    # that relayed `(3, 3)` would report itself complete.
    assert progress and all(total == len(plan) for _, total in progress), (
        f"progress denominator moved off the frozen plan size: {progress}")
    assert [c for c, _ in progress] == list(range(1, len(cut) + 1)), (
        f"progress counted pairs that produced no result: {progress}")
    assert len(full) == len(plan), (
        f"budget=None replayed {len(full)} of {len(plan)}; the unbounded path "
        f"is the audit lane and must be byte-for-byte what it was")
    assert len(started) == 2 and all(
        r.verdict == "NOT_REPLAYABLE" for r in started), (
        "a pair that WAS started and could not read its cell must keep its "
        "NOT_REPLAYABLE verdict; omission is only for a pair never started")


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


def test_replay_results_actually_hands_the_budget_to_the_replay():
    """The WIRING, not just the arithmetic.

    `replay_budget()` deriving a correct number proves nothing if the number is
    never passed to `replay_many` — and that one keyword is the whole fix. It is
    the cheapest thing in this change to delete by accident, and deleting it
    restores the session-killing behaviour with every other guard here still
    green. So the call is asserted, not the constant.
    """
    replay_results.cache_clear()
    captured = {}

    def spy(plan, **kwargs):
        captured.update(kwargs)
        captured["plan"] = tuple(plan)
        return ()

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(L, "replay_many", spy)
            mp.setattr(sys.modules[__name__], "_HARNESS_BOUND", 180.0)
            replay_results()
    finally:
        replay_results.cache_clear()

    assert "budget" in captured, (
        "replay_results() called replay_many WITHOUT a budget keyword; the "
        "plan is unbounded again and the harness will kill the session instead "
        "of the replay reporting a shortfall")
    assert captured["budget"] == 180.0 - REPLAY_BUDGET_HEADROOM, (
        f"replay_results() passed budget={captured['budget']!r} while the "
        f"harness bound was 180.0; it must pass replay_budget()")
    assert captured["timeout"] == REPLAY_TIMEOUT, (
        "the per-cell bound must still be forwarded; the total budget REPLACES "
        "nothing, it bounds the level that had no bound at all")


def test_the_shortfall_note_says_NOT_MEASURED_and_never_a_lost_proof():
    """The disclosure is the deliverable, so its WORDS are asserted.

    A short population has two causes that read identically — starved upstream,
    or cut off by this file's own budget — and they mean opposite things. If the
    note goes missing, the reds it annotates say "the recorded proof no longer
    holds" about pairs that were never run, which is the exact sentence that
    sent an author hunting a regression that did not happen (vibe-ic#1410).
    """
    replay_results.cache_clear()
    plan = L.replay_plan()
    kept = plan[:2]

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(L, "replay_many", lambda p, **k: tuple(
                L.ReplayResult(name, 1, sid, True, 0, 1, True, "")
                for name, sid in kept))
            mp.setattr(sys.modules[__name__], "_HARNESS_BOUND", 180.0)
            assert len(replay_results()) == len(kept)
            missing = replay_shortfall()
            note = _cut_off_note()
    finally:
        replay_results.cache_clear()

    assert missing == list(plan[2:]), (
        f"the shortfall must be every plan pair with no result, in plan order; "
        f"got {missing[:4]}")
    assert "NOT HAPPEN" in note and "CUT OFF" in note, (
        f"the note does not say the measurement did not happen: {note!r}")
    assert f"{len(plan) - len(kept)} of {len(plan)}" in note, (
        f"the note does not state the shortfall against the FULL plan "
        f"denominator: {note!r}")
    assert "do NOT re-record the ledger" in note, (
        f"the note must refuse the evidence-deleting repair by name: {note!r}")
    # And the reverse: a COMPLETE population must add no note at all, or every
    # ordinary red acquires a cut-off excuse it has not earned.
    replay_results.cache_clear()
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(L, "replay_many", lambda p, **k: tuple(
                L.ReplayResult(name, 1, sid, True, 0, 1, True, "")
                for name, sid in plan))
            assert replay_shortfall() == []
            assert _cut_off_note() == ""
    finally:
        replay_results.cache_clear()


def test_a_stub_population_never_escapes_the_test_that_installed_it():
    """The `finally` in the denominator test, driven in the failing direction.

    `replay_results` is `lru_cache`d for the session, and the denominator test
    drives it through a stub returning an empty population. Before this was in a
    `finally`, that test failing left `()` cached and every LOCK 2
    parametrisation after it reported `produced no replay result` — a verdict
    about mutations no replay had touched. Measured shape on clean
    `7c376e348` in `all` mode: 15 such parametrisations, 0 replays run.

    So this drives the denominator test in EXACTLY that failing direction and
    asserts the cache is clean afterwards. It fails if the `finally` is removed.
    """
    replay_results.cache_clear()
    with pytest.MonkeyPatch.context() as mp:
        # Make the denominator assertion legitimately false, which is what
        # `all` mode does in the field.
        #
        # DERIVED FROM THE PLAN, not written down. A literal here RACES the pin
        # in the test below, and on 2026-08-20 it lost that race: adding
        # `D5-PHANTOM-FALLBACK` moved the frozen plan from 24 to 25, the
        # hard-coded 25 became EQUAL to it, the inner assertion passed, and
        # `pytest.raises(AssertionError)` reported this test as broken —
        # i.e. a guard on the `finally` stopped driving the failing direction
        # and said so as if the `finally` had regressed. Deriving the wrong
        # count from the right one cannot go stale.
        wrong_denominator = len(L.replay_plan()) + 1
        mp.setattr(L, "replay_plan", lambda *a, **k: tuple(
            (f"M{i}", f"s{i}") for i in range(wrong_denominator)))
        with pytest.raises(AssertionError):
            test_witness_replay_relays_the_exact_frozen_plan_denominator(mp)
    assert replay_results.cache_info().currsize == 0, (
        "the denominator test failed and left its STUB population cached; "
        "every replay-driven test after it would read a population no replay "
        "produced, and report it as mutations that stopped reddening")


def test_witness_replay_relays_the_exact_frozen_plan_denominator(monkeypatch):
    """The relayed denominator is the FROZEN plan, not what the replay achieved.

    THE `finally` IS LOAD-BEARING (vibe-ic#1410). This test drives
    `replay_results()` through a STUB that returns an empty population, and
    `replay_results` is `lru_cache`d for the whole session. The trailing
    `cache_clear()` used to be an ordinary last statement, so ANY assertion
    here failing left the stub's `()` cached — and every replay-driven test
    after it then read a population that no replay ever produced.

    That is not hypothetical and it is not cosmetic. MEASURED on clean
    `7c376e348` with `VIBE_IC_MATRIX_MUTATION_REPLAY=all`, where the plan is 707
    pairs and the `== 24` below is legitimately false:

        16 failed, 94 passed, 2 skipped in 18.78s
        FAILED ...::test_witness_replay_relays_the_exact_frozen_plan_denominator
        FAILED ...::test_lock2_the_mutation_really_reddens_its_witness[...]  x15

    Fifteen LOCK 2 parametrisations reported `produced no replay result` — the
    shape that reads as "the mutation stopped reddening its witness" — on a tree
    where NO REPLAY HAD BEEN RUN AT ALL. A test's fixture leaked into the
    instrument the rest of the file measures with, and the instrument then
    reported verdicts about mutations it never touched. Restoring the cache in a
    `finally` is what confines the stub to this test.
    """
    replay_results.cache_clear()
    seen = []

    def fake_many(plan, **kwargs):
        frozen = tuple(plan)
        callback = kwargs["progress_callback"]
        for completed in range(1, len(frozen) + 1):
            callback(completed, len(frozen))
        return ()

    monkeypatch.setattr(L, "replay_many", fake_many)
    monkeypatch.setattr(
        sys.modules[__name__], "_domain_progress",
        lambda scope, completed, total:
        seen.append((scope, completed, total)))
    try:
        assert replay_results() == ()
        # 24 -> 25: `D5-PHANTOM-FALLBACK` joined the ledger (2026-08-20). It is
        # the first mutation to reach `closed_loop.fallback_to` — the flow's
        # CONVERGENCE edges, 19 of which had shipped with no reader in the
        # repository at all. Witness mode is one pair per entry, so the plan
        # grows by exactly one. Re-stated by hand rather than derived from
        # `len(L.MUTATIONS)`, because this pin exists to make a new entry force
        # a human to say the number.
        assert len(L.replay_plan()) == 25
        assert seen == [
            ("matrix-mutation-replays", completed, 25)
            for completed in range(1, 26)
        ]
    finally:
        replay_results.cache_clear()


@lru_cache(maxsize=1)
def replay_results() -> Tuple[L.ReplayResult, ...]:
    """Run the current mode's replay plan once, in parallel, and cache it."""
    plan = L.replay_plan()
    return L.replay_many(
        plan, jobs=8, timeout=REPLAY_TIMEOUT,
        progress_callback=lambda completed, total: _domain_progress(
            "matrix-mutation-replays", completed, total),
        budget=replay_budget(),
    )


def replay_shortfall() -> List[Tuple[str, str]]:
    """Plan pairs the replay never STARTED, in plan order.

    Non-empty ONLY when the total budget cut the plan off. These pairs were not
    measured, so they carry no verdict and appear in no scoring: they are
    reported as a shortfall, never as mutations that stopped reddening.
    """
    ran = {(r.mutation, r.step_id) for r in replay_results()}
    return [pair for pair in L.replay_plan() if pair not in ran]


def _cut_off_note() -> str:
    """Say WHICH of the two things a short population is, in the failure text.

    ``len(results) < len(plan)`` has two causes that read identically and mean
    opposite things: the replay was starved by something upstream, or the
    replay ran out of the budget this file gave it. Only the second is a
    measurement that did not happen, and only this function can tell them apart
    — so the distinction is stated in the assertion rather than left for the
    reader to guess from a count.
    """
    missing = replay_shortfall()
    if not missing:
        return ""
    return (f"\n\nTHE REPLAY WAS CUT OFF, so this is a measurement that did "
            f"NOT HAPPEN rather than a proof that stopped holding: "
            f"{len(missing)} of {len(L.replay_plan())} pair(s) were never "
            f"started under a total budget of {replay_budget()}s "
            f"(mode {L.replay_mode()!r}, harness bound {_HARNESS_BOUND}). "
            f"Nothing here says a mutation stopped reddening anything. Fix the "
            f"budget or the lane — do NOT re-record the ledger to match.\n"
            f"Unreached: {missing[:6]}{' ...' if len(missing) > 6 else ''}")


def _lock2_params():
    """One param per entry, corpus-gated for the ones whose WITNESS needs it.

    A replay proves nothing unless the witness cell it re-runs can reach a
    verdict. Dimension 3's cell test is answered out of the published corpus —
    ``test_matrix_d3_outputs_produced`` skips naming the corpus where there is
    none — so a dimension-3 entry replayed here watches a SKIP before the edit
    and a SKIP after it. That is a statement about the corpus, not about the
    ledger, so those entries skip for the corpus's own reason instead. Every
    other entry's witness is answered from the flow yaml and the plugin tree,
    both of which are here, and is left exactly as it was.

    THIS MARK IS NOT WHAT KEEPS THE VERDICT HONEST, and reading it as such is
    what vibe-ic#1421 cost. Until ``_cell_rc_from_report`` learned that a
    skipped cell has no colour, the pair underneath this mark was being SCORED
    ``STAYED_GREEN`` — "the recorded proof no longer holds" — and the mark only
    hid that verdict from this one assertion. ``replay_plan`` is not
    marker-gated: the pair still runs, still lands in ``replay_results()``, and
    is still read by the CLI, by the starvation guard, and by anyone who prints
    the plan. The scoring is fixed at the source now; this mark does the one job
    its name claims, which is to keep an assertion about the LEDGER from
    reporting a fact about the CHECKOUT.
    """
    out = []
    for m in L.MUTATIONS:
        marks = [needs_corpus] if m.dim == 3 else []
        out.append(pytest.param(m.name, marks=marks))
    return out


@pytest.mark.parametrize("name", _lock2_params())
def test_lock2_the_mutation_really_reddens_its_witness(name):
    """LOCK 2: perform the edit for real and watch the cell go PASS -> FAIL.

    This is the only lock that is proof rather than structure. The mutation is
    applied to an ISOLATED copy — a scratch flow yaml fed through
    ``VIBE_IC_MATRIX_FLOW_YAML``, or a ``cp -al`` hardlink mirror written with
    unlink-then-write — so the shared worktree is never touched. Three things
    must hold, and each rules out a different way of being wrong:

      * the unmutated run PASSES (an already-red cell proves nothing);
      * the mutated run FAILS (the mutation actually moved the predicate);
      * the failure text contains the entry's declared ``red_signal`` (it failed
        for the recorded reason, not because an import blew up).

    The FIRST of those three is a PRECONDITION of the assertion, not part of
    what the assertion concludes (#1432). A pair whose gate was red before the
    edit is UNMEASURABLE: it did not show the gate lost its teeth, it showed the
    gate cannot be measured on that step right now, and reporting it as "the
    recorded proof no longer holds" sends an author hunting a regression that
    does not exist. Those pairs are excluded HERE and counted, disclosed and
    ceilinged in ``test_the_replay_actually_ran_and_is_not_starved`` below.

    This is not a way for an entry to stop proving anything: every entry must
    still produce AT LEAST ONE genuinely proved pair, so an entry whose every
    step went unmeasurable still fails here rather than passing on an empty set.
    """
    results = {(r.mutation, r.step_id): r for r in replay_results()}
    mine = [r for (n, _), r in results.items() if n == name]
    assert mine, f"{name} produced no replay result{_cut_off_note()}"
    for r in mine:
        if r.unmeasurable:
            continue
        assert r.proved, (
            f"{name} @ step {r.step_id}: {r.verdict}.\n"
            f"The ledger says this edit reddens the cell; re-running it says "
            f"otherwise, so the recorded proof no longer holds.\n{r.detail}")
    assert any(r.proved for r in mine), (
        f"{name} produced {len(mine)} replay result(s) and NOT ONE of them "
        f"proved anything — every pair was unmeasurable "
        f"({[(r.step_id, r.baseline_rc) for r in mine]}). An entry that "
        f"demonstrates nothing is not covered by this lock, however honest the "
        f"reason; fix the reds under it or the entry is carrying no proof.")


@needs_corpus
def test_the_replay_actually_ran_and_is_not_starved(record_property):
    """Anti-starvation guard on LOCK 2's own instrument.

    The failure that convened this campaign was a checker reporting a clean run
    because its input had been emptied. A replay plan that silently produced
    zero pairs would make every assertion above vacuously true, so the plan's
    size is compared against the ledger and reported.

    CORPUS-GATED as a WHOLE, unlike LOCK 1 above, because there is nothing here
    to set aside: this is an AGGREGATE over ``L.replay_plan()``, whose expected
    size counts ``len(L.ARTEFACT_MUTATIONS)`` and whose UNMEASURABLE ratchet is
    a proportion of it. Eight of its members name a published run this checkout
    does not have, so the denominator itself is unreadable and every figure
    computed from it would be about a plan that could not be executed. Point
    ``VIBE_IC_BENCHMARK_DATA`` at a clone and it runs, ratchet and all.
    """
    results = replay_results()
    plan = L.replay_plan()
    expected = (len(L.MUTATIONS) if L.replay_mode() == "witness"
                else sum(len(m.applies_to) for m in L.MUTATIONS)
                ) + len(L.ARTEFACT_MUTATIONS)
    assert len(results) == len(plan) == expected > 0, (
        f"replayed {len(results)} pair(s) for a plan of {len(plan)}; mode "
        f"{L.replay_mode()!r} should re-execute {expected}"
        f"{_cut_off_note()}")
    assert len({(r.mutation, r.step_id) for r in results}) == len(results), (
        "the replay plan contains duplicate pairs, so the count overstates "
        "what was actually re-executed")
    proved = sum(1 for r in results if r.proved)
    unmeasurable = [r for r in results if r.unmeasurable]
    record_property("matrix_mutation_replay",
                    f"mode={L.replay_mode()} pairs={len(results)} "
                    f"proved={proved} unmeasurable={len(unmeasurable)} "
                    f"seconds={sum(r.seconds for r in results):.1f}")
    # `as_recorded`, not `proved`. For every FLOW_YAML and PLUGIN_TREE entry the
    # two are IDENTICAL — those channels record `REDDENED` and nothing else, and
    # `verdict == "REDDENED"` is definitionally `proved`. The distinction exists
    # only for ARTEFACT_MUTATION entries that RECORD `STAYED_GREEN`, where the
    # published finding is that the gate does not move; scoring those as
    # unproved would make the honest thing to do with a measured gap be to
    # delete the record of it.
    #
    # UNMEASURABLE pairs are excluded from THIS assertion and bounded by their
    # own one below (#1432) — a gate that was red before the edit has not shown
    # it stopped catching. They are excluded, never skipped: the count is
    # recorded as a property above and ceilinged below.
    failures = [r for r in results if not r.as_recorded and not r.unmeasurable]
    assert not failures, [
        f"{r.mutation}@{r.step_id}: expected {r.expected}, got {r.verdict}"
        for r in failures]
    # THE UNMEASURABLE RATCHET. Without this the ledger acquires exactly the
    # blind spot it exists to prevent: a gate that stops catching AND whose
    # witness happens to be red would be invisible in both assertions.
    ceiling = L.UNMEASURABLE_CEILING[L.replay_mode()]
    assert len(unmeasurable) <= ceiling, (
        f"{len(unmeasurable)} of {len(results)} pair(s) could not be measured "
        f"in mode {L.replay_mode()!r}, over the ceiling of {ceiling}. Each was "
        f"RED BEFORE its mutation was applied, so the ledger is measuring less "
        f"of itself than it believes. Fix the reds — do NOT raise the ceiling "
        f"to match, and do NOT re-record the entries.\n"
        + "\n".join(f"  {r.mutation} @ step {r.step_id}: "
                    f"baseline_rc={r.baseline_rc}" for r in unmeasurable))
    # Every dimension must be represented, or a whole dimension's entries could
    # be un-replayed while the count still looked healthy.
    dims = {r.dim for r in results}
    assert dims == set(range(1, 9)), (
        f"replay touched dimensions {sorted(dims)}; a dimension with no "
        f"re-executed witness has only structural locks on it")


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
def _result(**kw) -> L.ReplayResult:
    """A ReplayResult with the uninteresting fields defaulted."""
    base = dict(mutation="D3-UNDECLARED-ARTEFACT", dim=3, step_id="15",
                applied=True, baseline_rc=0, mutant_rc=1, signal_seen=True,
                detail="")
    return L.ReplayResult(**(base | kw))


def test_an_already_red_pair_is_UNMEASURABLE_not_a_failed_mutation():
    """#1432: baseline_rc != 0 means COULD NOT LOOK, not FOUND A DEFECT.

    The exact result the issue replayed to completion on ``24ff95307``:
    ``baseline_rc=1``, so the witness was red before the mutation was applied.
    Nothing was disproved; nothing could be.
    """
    r = _result(baseline_rc=1, mutant_rc=1, signal_seen=False)
    assert r.verdict == L.ALREADY_RED, r.verdict
    assert r.unmeasurable, (
        "a pair that was RED BEFORE the edit is not scored UNMEASURABLE, so "
        "the ledger still reads 'could not measure this gate' as 'this gate "
        "stopped catching' — the most expensive wrong answer the instrument "
        "the whole campaign is measured with can give")
    # The two that must NOT move: an already-red pair proves nothing, so it may
    # never be banked as proof either.
    assert not r.proved, "an already-red pair was banked as proof"
    assert not r.as_recorded, "an already-red pair was banked as reproduced"


def test_a_gate_that_genuinely_stops_catching_is_STILL_a_failure():
    """NEGATIVE CONTROL for the above. The teeth must survive the fix.

    Baseline GREEN and mutant GREEN is the real defect this ledger exists to
    catch — the gate no longer notices the edit. It must stay a failure, and it
    must NOT be absorbed into the new third state.
    """
    r = _result(mutant_rc=0, signal_seen=False)
    assert r.verdict == L.CANNOT_REDDEN, r.verdict
    assert not r.unmeasurable, (
        "a gate that went green->green was scored UNMEASURABLE; the fix for "
        "#1432 has swallowed the defect it was supposed to leave alone")
    assert not r.proved and not r.as_recorded
    # And it is still in the set the starvation guard asserts is empty.
    assert not (r.as_recorded or r.unmeasurable), (
        "a genuinely toothless gate would now pass the grid")


def test_a_red_for_another_reason_is_still_a_failure():
    """A mutant that fails WITHOUT the declared signal is not unmeasurable.

    It failed for some reason other than the recorded one — an import blowing
    up looks exactly like this — and it must keep failing.
    """
    r = _result(mutant_rc=1, signal_seen=False)
    assert r.verdict == "RED_FOR_ANOTHER_REASON", r.verdict
    assert not r.unmeasurable and not r.as_recorded


def test_NOT_REPLAYABLE_is_not_folded_into_unmeasurable():
    """Scope guard. #1432 is about ALREADY_RED and nothing else.

    A replay that never RAN is a different failure with its own handling; the
    fix must not quietly re-score it too.
    """
    r = _result(baseline_rc=1, not_replayable="the corpus run is absent")
    assert r.verdict == "NOT_REPLAYABLE", r.verdict
    assert not r.unmeasurable, (
        "NOT_REPLAYABLE was absorbed into UNMEASURABLE, so a replay that could "
        "not run at all now scores as a gate that could not be measured")
    assert not r.as_recorded


def test_ALREADY_RED_is_not_a_recordable_expectation():
    """PROHIBITION 2 of #1432: not a re-record.

    The ledger is the record of what the gates COULD catch. If an entry could
    DECLARE ``ALREADY_RED`` then the honest response to a measured gap would be
    to rewrite the entry to match current behaviour, which deletes the
    evidence. The verdict is an OUTCOME only.
    """
    assert L.ALREADY_RED not in L.ARTEFACT_EXPECTATIONS, (
        "ALREADY_RED became a declarable expectation; an entry could now be "
        "rewritten to expect its own gate's red instead of the red being fixed")
    declared = [(m.name, m.expected) for m in L.ARTEFACT_MUTATIONS
                if m.expected == L.ALREADY_RED]
    assert not declared, f"entries declare ALREADY_RED: {declared}"
    for m in L.ARTEFACT_MUTATIONS:
        assert m.expected in L.ARTEFACT_EXPECTATIONS, (
            f"{m.name} records {m.expected!r}, which is not a recordable "
            f"verdict")


def test_the_unmeasurable_ceiling_is_zero_for_witness_mode():
    """PROHIBITION 3 of #1432: not a reason to relax ``witness`` mode.

    Every witness is green on main, which is why the default mode is honest
    today. The unmeasurable pairs are all non-witness steps reached only by
    ``all``. A witness going red must therefore be a FAILURE, not a shrug.
    """
    assert set(L.UNMEASURABLE_CEILING) == set(L.REPLAY_MODES), (
        f"a replay mode has no unmeasurable ceiling: "
        f"{set(L.REPLAY_MODES) - set(L.UNMEASURABLE_CEILING)}")
    assert L.UNMEASURABLE_CEILING["witness"] == 0, (
        "the witness-mode ceiling left 0, so a witness could go red and the "
        "grid would absorb it silently")
    assert L.UNMEASURABLE_CEILING["all"] >= 0


def test_the_ceiling_actually_bites_when_it_is_breached():
    """PROHIBITION 1 of #1432: not a silent skip.

    Proves the ratchet is load-bearing rather than decorative by evaluating the
    grid's own predicate against a result set one over the ceiling. Without
    this, "counted and disclosed" could be true while nothing enforced it.
    """
    ceiling = L.UNMEASURABLE_CEILING["witness"]
    over = [_result(step_id=str(i), baseline_rc=1, mutant_rc=1,
                    signal_seen=False) for i in range(ceiling + 1)]
    assert all(r.unmeasurable for r in over)
    assert not len(over) <= ceiling, (
        "a result set one pair OVER the witness-mode ceiling satisfies the "
        "ratchet, so the ceiling cannot fail and enforces nothing")
    at = over[:ceiling]
    assert len(at) <= ceiling, "the ratchet fails at exactly the ceiling"


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
# The bound below is ONE SECOND: far under the 60 s ceiling (`180 // 3`) that
# `ci_harness_timeout_ceiling_check` permits one blocking call. These tests cost
# ~1 s each; they do not replay anything to completion and are not a second copy
# of LOCK 2.
_BOUND_THAT_ALWAYS_FIRES = 1

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
#: whose verdict is a property of the machine. A probe that sleeps for thirty
#: seconds cannot finish inside a one-second bound on any host, which makes the
#: kill a property of THIS FILE. Nothing about the claim under test — that a
#: killed child returns a reason instead of raising, and is never given a
#: colour — was ever about which cell was killed.
_A_CELL_THAT_CANNOT_FINISH = ("import time\n\n\n"
                              "def test_probe():\n"
                              "    time.sleep(30)\n")


@pytest.fixture()
def unkillable_cell(tmp_path, monkeypatch):
    """Point `cell_nodeid` at a probe that cannot answer inside the bound."""
    root = tmp_path / "slow"
    root.mkdir(parents=True)
    (root / "test_probe.py").write_text(_A_CELL_THAT_CANNOT_FINISH,
                                        encoding="utf-8")
    (root / "conftest.py").write_text("", encoding="utf-8")
    nodeid = f"{root / 'test_probe.py'}::test_probe"
    monkeypatch.setattr(L, "cell_nodeid", lambda dim, sid: nodeid)
    return root


def test_a_cell_that_blows_its_bound_is_UNREADABLE_not_a_colour(unkillable_cell):
    """The bound firing must RETURN a reason, not raise.

    `_cell_rc_from_report` already states the doctrine — "a replay that could
    not read its cell must be NOT_REPLAYABLE, never a quiet ALREADY_RED" — and
    implements it for a missing report, an unparseable report and a report with
    the wrong number of testcases. A killed child was the one unreadable path
    that escaped it, because `subprocess.run` raises instead of returning.

    Measured 2026-08-14 on 32 cores, uncontended, at a 60 s cell bound: the
    dimension-6 cell for step 21 blew it and `subprocess.TimeoutExpired`
    propagated out of `replay` -> `replay_many`'s `pool.map`, killing the test
    with a traceback and no verdict.
    """
    rc, out, why = L._run_cell(3, "D1", unkillable_cell, None,
                               _BOUND_THAT_ALWAYS_FIRES)
    assert rc is None, (
        f"a cell killed at {_BOUND_THAT_ALWAYS_FIRES}s reported rc={rc!r}. An "
        f"arm nobody waited for has NO COLOUR; giving it one is how 'could not "
        f"look' becomes 'looked and it was red'")
    assert str(_BOUND_THAT_ALWAYS_FIRES) in why and "bound" in why, (
        f"the reason does not name the bound that fired: {why!r}")
    assert "NOT MEASURED" in why, (
        f"the reason does not say the arm was not measured, so a reader still "
        f"cannot tell this from a gate that stopped catching: {why!r}")
    assert isinstance(out, str), f"partial output came back as {type(out)}"


def test_a_replay_whose_bound_fires_is_NOT_REPLAYABLE_and_still_FAILS(
        unkillable_cell):
    """End to end: the pair scores NOT_REPLAYABLE, and that is a failure.

    The two directions that matter, and they pull against each other:

      * it must not RAISE — an exception out of `replay_many` takes LOCK 2 down
        with no verdict at all, which is the defect;
      * it must not PASS — a bound that fired proves nothing, and a replay that
        could not run must never be scored as one that ran.

    The ENTRY is still a real one — `replay` performs its real edit on a real
    copy of the flow and checks the real blast radius — and only the CELL the
    two arms run is the probe that cannot answer in time. FLOW_YAML, so no
    `cp -al` mirror is built for a pair that is going to be killed anyway.
    """
    mut = L.mutation("D3-UNDECLARED-ARTEFACT")          # FLOW_YAML: no cp -al
    r = L.replay(mut, mut.witness, _BOUND_THAT_ALWAYS_FIRES)
    assert r.verdict == "NOT_REPLAYABLE", (
        f"a pair whose cells were killed scored {r.verdict!r}")
    assert not r.proved, "a replay that never ran was banked as proof"
    assert not r.as_recorded, "a replay that never ran was banked as reproduced"
    assert not r.unmeasurable, (
        "a timed-out replay was folded into UNMEASURABLE, which is the claim "
        "that the WITNESS was pre-reddened — this measurement supports no such "
        "claim, and the unmeasurable ceiling would then absorb it")
    assert "bound" in r.not_replayable, (
        f"the pair does not carry the reason: {r.not_replayable!r}")


def test_the_bound_reason_refuses_BOTH_evidence_deleting_repairs(
        unkillable_cell):
    """The message routes the reader, or #1403 happens again.

    #1403 was not a broken gate. It was a red whose text sent every reader to
    the wrong repair. The two repairs that must be named and refused are the
    same two the ALREADY_RED path refuses, for the same reason: both restore
    green by deleting the evidence rather than by measuring anything.
    """
    _, _, why = L._run_cell(3, "D1", unkillable_cell, None,
                            _BOUND_THAT_ALWAYS_FIRES)
    assert "re-record the ledger" in why, (
        f"the reason does not refuse re-recording the ledger: {why!r}")
    assert "re-pick the witness" in why, (
        f"the reason does not refuse re-picking the witness: {why!r}")
    assert "stopped catching" in why, (
        f"the reason does not deny the lost-gate reading, which is the one a "
        f"reader arrives with: {why!r}")


def test_a_TIMED_OUT_arm_is_still_distinguishable_from_a_TOOTHLESS_gate():
    """PAIRED GUARD. The fix must not blunt the finding it sits next to.

    A gate that genuinely stopped catching produces baseline GREEN, mutant
    GREEN and NO reason — it is measured, and it is the defect this ledger
    exists to publish. It must keep its own verdict and keep failing, or #1403
    would have been fixed by making every red say "could not measure".
    """
    timed_out = _result(baseline_rc=None, mutant_rc=None, signal_seen=False,
                        not_replayable="the cell exceeded its 60s bound")
    toothless = _result(mutant_rc=0, signal_seen=False)
    assert timed_out.verdict == "NOT_REPLAYABLE"
    assert toothless.verdict == L.CANNOT_REDDEN
    assert timed_out.verdict != toothless.verdict, (
        "a measurement that did not happen and a gate that lost its teeth now "
        "carry the SAME verdict; the reader is back where #1403 started")
    # And neither one may pass.
    assert not timed_out.proved and not timed_out.as_recorded
    assert not toothless.proved and not toothless.as_recorded


def test_the_canaries_a_mutation_plants_exist_nowhere_in_the_tree():
    """A canary that collides with a real path would redden a cell for the wrong
    reason, and the mutation would look proven while proving nothing.

    Checked against the flow yaml and the programs directory, which are the two
    places a mutation writes.
    """
    flow_text = L.flow_yaml_path().read_text(encoding="utf-8")
    hits: List[str] = []
    for token in L.CANARY_TOKENS:
        if token in flow_text:
            hits.append(f"{token!r} already appears in the flow yaml")
    programs = L.PLUGIN_ROOT / "programs"
    for token in (L.CANARY_PROGRAM,):
        if (programs / f"{token}.py").exists():
            hits.append(f"programs/{token}.py exists, so the orphan-registry "
                        f"mutation would not be an orphan")
    assert not hits, "\n  - ".join(hits)


# ══════════════════════════════════════════════════════════════════════
# 4. NOT-FALSIFIABLE IS PUBLISHED, NOT BURIED
# ══════════════════════════════════════════════════════════════════════
def test_not_falsifiable_cells_are_published_and_specific():
    """A cell nothing can redden is the FINDING. It must be a real cell, it must
    say what was tried, and it may not also be claimed as covered.

    The list is EMPTY as measured 2026-08-06 — all 481 ENFORCED cells were
    reddened by an executed mutation. The emptiness is asserted here so that
    adding an entry is a deliberate act with a visible diff, and so that a
    reader of this file learns the real number rather than inferring one.
    """
    live = {F.normalize_id(s) for s in F.step_ids()}
    problems: List[str] = []
    for nf in L.NOT_FALSIFIABLE:
        if nf.step_id not in live:
            problems.append(
                f"{nf.step_id}/d{nf.dim}: names a step the flow does not "
                f"declare, so the finding is about nothing")
        if nf.dim not in DIMENSIONS:
            problems.append(f"{nf.step_id}/d{nf.dim}: dimension out of range")
        if len(nf.tried) < 1:
            problems.append(
                f"{nf.step_id}/d{nf.dim}: records no mutation shape that was "
                f"tried; 'nothing worked' is not a finding until it names what "
                f"was attempted")
        if len((nf.observed or "").strip()) < 30:
            problems.append(
                f"{nf.step_id}/d{nf.dim}: observed={nf.observed!r} is too "
                f"short to tell anyone what the cell did instead of reddening")
        if L.mutations_covering(nf.step_id, nf.dim):
            problems.append(
                f"{nf.step_id}/d{nf.dim}: recorded NOT-FALSIFIABLE while "
                f"{[m.name for m in L.mutations_covering(nf.step_id, nf.dim)]} "
                f"claims to redden it")
    assert not problems, (
        f"{len(problems)} NOT-FALSIFIABLE record problem(s):\n  - " +
        "\n  - ".join(problems))
    assert len(L.NOT_FALSIFIABLE) == 0, (
        f"{len(L.NOT_FALSIFIABLE)} cell(s) are recorded as reddenable by no "
        f"mutation: "
        f"{[f'{n.step_id}/d{n.dim}' for n in L.NOT_FALSIFIABLE]}. That is a "
        f"real finding and it must be published — update this assertion in the "
        f"same change that adds the entry, and say in the commit body which "
        f"predicate is now known to be unfalsifiable.")


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


def test_the_ledger_names_every_dimension_it_does_not_cover():
    """A dimension outside this ledger must be DECLARED, never merely absent.

    `census()` derives its grid from `CELL_TESTS`, so a dimension with no entry
    there contributes no cells and no assertion notices. That is silent absence
    — "a cell with no test is not covered", one level up. This test makes the
    gap loud in both directions: a dimension that leaves the ledger must be
    named here, and one that JOINS it must be removed from this map in the same
    change, so the declaration cannot rot into a description of an older tree.
    """
    covered = set(L.CELL_TESTS)
    declared = set(DIMENSIONS)
    missing = declared - covered
    assert missing == set(LEDGER_DIMENSIONS_NOT_COVERED), (
        f"dimension(s) {sorted(missing)} of the live matrix carry no cells in "
        f"this ledger, and the declared set is "
        f"{sorted(LEDGER_DIMENSIONS_NOT_COVERED)}.\n"
        f"Undeclared: {sorted(missing - set(LEDGER_DIMENSIONS_NOT_COVERED))} — "
        f"their cells are contributing nothing to the coverage arithmetic and "
        f"nothing said so.\n"
        f"Stale: {sorted(set(LEDGER_DIMENSIONS_NOT_COVERED) - missing)} — now "
        f"covered; delete the entry in the change that covered it.")
    assert not (covered - declared), (
        f"CELL_TESTS names dimension(s) {sorted(covered - declared)} that the "
        f"matrix does not declare; the ledger would census cells that do not "
        f"exist")
    for dim, reason in LEDGER_DIMENSIONS_NOT_COVERED.items():
        assert len(reason.strip()) >= 60, (
            f"dimension {dim}'s exclusion reason is too short to check")


def test_the_cell_test_addresses_are_real_pytest_nodes():
    """Every address :data:`CELL_TESTS` names must collect, or a replay would be
    measuring nothing and reporting a tidy green.

    Collection is done by pytest itself, in one subprocess, over the eight
    nodeids the witnesses use.
    """
    nodes = [L.cell_nodeid(m.dim, m.witness) for m in L.MUTATIONS]
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop(L.FLOW_YAML_ENV, None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *nodes, "--collect-only", "-q",
         "-p", "no:randomly", "--no-header"],
        cwd=str(L.PLUGIN_ROOT), capture_output=True, text=True,
        timeout=_PYTEST_TIMEOUT_S, env=env)
    assert proc.returncode == 0, (
        f"pytest could not collect every witness cell address; a replay "
        f"against an address that does not exist proves nothing.\n"
        f"{proc.stdout[-3000:]}\n{proc.stderr[-1500:]}")
    collected = proc.stdout
    missing = [n for n in nodes if n.split("::", 1)[1] not in collected]
    assert not missing, (
        f"pytest exited 0 but never collected {missing}; a nodeid that "
        f"collects nothing runs nothing and reports a tidy green.\n"
        f"{collected[-3000:]}")
    assert f"{len(set(nodes))} tests collected" in collected or \
        f"{len(set(nodes))} test collected" in collected, (
        f"expected exactly {len(set(nodes))} collected item(s) for the "
        f"witness addresses; got:\n{collected[-1500:]}")


def test_the_ledger_forms_no_second_opinion_about_cell_state():
    """The ledger must not decide what state a cell is in — that belongs to the
    dimension module, and a second opinion is the adjacent measurement this
    campaign removes.

    Checked structurally: ``census()`` is a pure function of the states handed
    to it, so feeding it a different state map must change its answer.
    """
    states = dict(cell_states())
    victim = enforced_cells()[0]
    assert L.census(states)["considered"] == len(enforced_cells())
    states[victim] = "WAIVED"
    assert L.census(states)["considered"] == len(enforced_cells()) - 1, (
        "census() ignored the state map it was given, which means it is "
        "deciding cell state for itself somewhere")

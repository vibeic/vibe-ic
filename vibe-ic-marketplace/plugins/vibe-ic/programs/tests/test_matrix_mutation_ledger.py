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
from matrix_63x8.cells import DIMENSION_NAMES

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


@lru_cache(maxsize=1)
def cell_states() -> Dict[Tuple[str, int], str]:
    """``{(step, dim): state}`` — live, from the eight owning modules."""
    mods = dimension_modules()
    assert sorted(mods) == list(range(1, 9)), (
        f"expected eight dimension modules, found {sorted(mods)}; a dimension "
        f"with no module contributes {len(F.step_ids())} cells this gate can "
        f"neither state nor falsify")
    out: Dict[Tuple[str, int], str] = {}
    for dim, mod in mods.items():
        for sid in F.step_ids():
            out[(F.normalize_id(sid), dim)] = mod.matrix_cell_state(sid)
    return out


def enforced_cells() -> List[Tuple[str, int]]:
    return sorted(k for k, v in cell_states().items() if v == "ENFORCED")


# ══════════════════════════════════════════════════════════════════════
# The review gate on the ledger's own size
# ══════════════════════════════════════════════════════════════════════
def test_the_ledger_grid_matches_what_was_measured():
    """Steps, dimensions and the ENFORCED count are recomputed, then compared.

    Everything else in this file computes from the live flow. This one place
    compares the computed value against a number a human signed off on, for
    exactly the reason ``GRID_AS_MEASURED`` exists in the coverage meta-test: a
    64th step would be picked up everywhere and the arithmetic would keep
    partitioning tidily, which is precisely the silent shape to refuse.
    """
    states = cell_states()
    measured = (len(F.step_ids()), 8,
                sum(1 for v in states.values() if v == "ENFORCED"))
    assert measured == L.LEDGER_AS_MEASURED, (
        f"the ledger's grid changed: measured {measured} "
        f"(steps, dimensions, ENFORCED cells), pinned "
        f"{L.LEDGER_AS_MEASURED}.\n"
        f"steps now in the flow that no ledger entry was measured against: "
        f"{sorted(set(F.normalize_id(s) for s in F.step_ids()) - measured_steps())}\n"
        f"Every ENFORCED cell needs a mutation that was RUN against it. Run "
        f"`python3 programs/matrix_mutation_ledger.py --census --resolve`, add "
        f"the measured entries, then update LEDGER_AS_MEASURED in the same "
        f"change.")


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
    """
    grown = tmp_path / "grown_flow.yaml"
    grown.write_text(yaml.safe_dump(_flow_with_an_extra_step(), sort_keys=False,
                                    allow_unicode=True), encoding="utf-8")
    states = dict(cell_states())
    for dim in range(1, 9):
        states[(CANARY_STEP_ID, dim)] = "ENFORCED"

    before = L.census(cell_states())
    assert not before["uncovered"], before["uncovered"]

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
    assert sorted(after["uncovered"]) == sorted(
        f"{CANARY_STEP_ID}/d{d}" for d in range(1, 9)), (
        f"a 64th step must arrive with exactly its own 8 cells uncovered; "
        f"got {after['uncovered']}")


def test_the_gate_itself_reddens_on_a_grown_flow(tmp_path):
    """CONTROL (bidirectional, end to end): the REAL gate, on the REAL grown
    flow, in a subprocess.

    The previous test measures the ledger's arithmetic. This one measures the
    gate: it re-runs ``test_every_enforced_cell_carries_a_named_mutation``
    against a flow with a synthetic 64th step and requires a non-zero exit that
    NAMES the step. Without this the growth claim would rest on a census
    function agreeing with itself.

    The same invocation with the UNMODIFIED flow is asserted to exit 0, so the
    control runs in both directions and a gate that reddened on everything
    would be caught here.
    """
    grown = tmp_path / "grown_flow.yaml"
    grown.write_text(yaml.safe_dump(_flow_with_an_extra_step(), sort_keys=False,
                                    allow_unicode=True), encoding="utf-8")
    node = (str(Path("programs/tests") / Path(__file__).name) +
            "::test_every_enforced_cell_carries_a_named_mutation")

    def run(flow_override):
        env = dict(os.environ)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        if flow_override is None:
            env.pop(L.FLOW_YAML_ENV, None)
        else:
            env[L.FLOW_YAML_ENV] = str(flow_override)
        return subprocess.run(
            [sys.executable, "-m", "pytest", node,
             "-q", "-p", "no:randomly", "--no-header", "-rN"],
            cwd=str(L.PLUGIN_ROOT), capture_output=True, text=True,
            timeout=_PYTEST_TIMEOUT_S, env=env)

    grown_run = run(grown)
    assert grown_run.returncode != 0, (
        f"the gate PASSED against a flow that grew a step. {node} is not "
        f"stopping anything.\n{grown_run.stdout[-3000:]}")
    assert CANARY_STEP_ID in grown_run.stdout, (
        f"the gate reddened on the grown flow but never named the new step, so "
        f"an author cannot act on it:\n{grown_run.stdout[-3000:]}")

    clean_run = run(None)
    assert clean_run.returncode == 0, (
        f"the gate is red against the UNMODIFIED flow, so the growth control "
        f"above proves nothing — a gate that fails on everything fails on a "
        f"64th step too.\n{clean_run.stdout[-4000:]}")


def test_reverse_case_reordering_the_flow_does_not_trip_the_gate(tmp_path):
    """REVERSE CASE (must STILL pass): moving a step's DECLARATION does not
    change the population, so the gate must stay quiet.

    A gate that fires on any yaml edit is not a coverage gate, it is a diff
    alarm. The dimension-5 waiver closures landed by moving A6, DT2 and DT3 in
    the declaration order; that class of change must not cost anyone a red here.
    """
    doc = copy.deepcopy(L.load_flow())
    steps = doc["steps"]
    steps.insert(0, steps.pop())            # last step declared first
    steps.append(steps.pop(1))              # and one from the middle to the end
    shuffled = tmp_path / "reordered_flow.yaml"
    shuffled.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")

    old = os.environ.get(L.FLOW_YAML_ENV)
    os.environ[L.FLOW_YAML_ENV] = str(shuffled)
    try:
        rep = L.census(cell_states())
        assert not L.unresolved(), (
            f"reordering the flow made {len(L.unresolved())} recorded edit "
            f"site(s) unresolvable; LOCK 1 must key off step ids, not order")
    finally:
        if old is None:
            os.environ.pop(L.FLOW_YAML_ENV, None)
        else:
            os.environ[L.FLOW_YAML_ENV] = old
    assert not rep["uncovered"], rep["uncovered"]
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
    """
    bad = L.unresolved()
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


#: Headroom left between the replay's TOTAL budget and the per-test harness
#: bound it is running under. `REPLAY_TIMEOUT` above bounds ONE cell; nothing
#: bounded the whole plan, so the aggregate was `len(plan)` cells deep and
#: undeclared — and `--timeout-method=thread` does not fail the TEST when that
#: aggregate is exceeded, it takes the whole SESSION. MEASURED on this tree,
#: `VIBE_IC_MATRIX_MUTATION_REPLAY=all` under the pinned
#: `--timeout=180 --timeout-method=thread`:
#:
#:     lines matching `passed|failed|error` in the whole output:  0
#:
#: Seventy-plus tests had already passed and not one of them is reported, and a
#: script grepping that output for failures reads zero. An empty result is not a
#: zero. With a budget the same run keeps its summary line and names what it
#: could not reach.
#:
#: 20 s, not a round number picked by feel: the budget is checked BETWEEN pairs
#: and `replay_many` halves the per-cell clamp so one pair cannot overrun the
#: deadline by a whole cell, so the only thing this has to absorb is process
#: spawn/teardown noise on the last wave plus the dict-build and assertions that
#: follow the replay inside the same test (sub-second). It is deliberately NOT
#: proportional to the bound: the overrun it covers does not grow with it.
REPLAY_BUDGET_HEADROOM = 20

#: Set by :func:`_record_harness_bound` from the bound pytest is actually
#: enforcing. `None` means no per-test bound is in effect — the audit lane —
#: and the replay then runs unbounded exactly as it did before.
_HARNESS_BOUND: object = None


@pytest.fixture(scope="session", autouse=True)
def _record_harness_bound(pytestconfig):
    """Read the harness's own per-test bound rather than assuming 180.

    Assuming it would make this file wrong the day the harness moves, and would
    silently cut the audit lane — which sets no bound at all — down to a batch
    lane's budget.
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


@lru_cache(maxsize=1)
def replay_results() -> Tuple[L.ReplayResult, ...]:
    """Run the current mode's replay plan once, in parallel, and cache it."""
    plan = L.replay_plan()
    return L.replay_many(plan, jobs=8, timeout=REPLAY_TIMEOUT,
                         budget=replay_budget())


def replay_shortfall() -> List[Tuple[str, str]]:
    """Plan pairs the replay never reached, in plan order.

    Non-empty ONLY when the budget above cut the plan off. These pairs were not
    measured, so they carry no verdict: they are reported as a shortfall, never
    as mutations that stopped reddening.
    """
    ran = {(r.mutation, r.step_id) for r in replay_results()}
    return [pair for pair in L.replay_plan() if pair not in ran]


def _cut_off_note() -> str:
    missing = replay_shortfall()
    if not missing:
        return ""
    return (f"\n\nTHE REPLAY WAS CUT OFF, so this is a measurement that did "
            f"not happen rather than a proof that stopped holding: "
            f"{len(missing)} of {len(L.replay_plan())} pair(s) were never "
            f"started under a total budget of {replay_budget()}s "
            f"(mode {L.replay_mode()!r}, harness bound {_HARNESS_BOUND}). "
            f"Unreached: {missing[:6]}{' ...' if len(missing) > 6 else ''}")


@pytest.mark.parametrize("name", [m.name for m in L.MUTATIONS])
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
    """
    results = {(r.mutation, r.step_id): r for r in replay_results()}
    mine = [r for (n, _), r in results.items() if n == name]
    assert mine, f"{name} produced no replay result{_cut_off_note()}"
    for r in mine:
        assert r.proved, (
            f"{name} @ step {r.step_id}: {r.verdict}.\n"
            f"The ledger says this edit reddens the cell; re-running it says "
            f"otherwise, so the recorded proof no longer holds.\n{r.detail}")


def test_the_replay_actually_ran_and_is_not_starved(record_property):
    """Anti-starvation guard on LOCK 2's own instrument.

    The failure that convened this campaign was a checker reporting a clean run
    because its input had been emptied. A replay plan that silently produced
    zero pairs would make every assertion above vacuously true, so the plan's
    size is compared against the ledger and reported.
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
    record_property("matrix_mutation_replay",
                    f"mode={L.replay_mode()} pairs={len(results)} "
                    f"proved={proved} "
                    f"seconds={sum(r.seconds for r in results):.1f}")
    # `as_recorded`, not `proved`. For every FLOW_YAML and PLUGIN_TREE entry the
    # two are IDENTICAL — those channels record `REDDENED` and nothing else, and
    # `verdict == "REDDENED"` is definitionally `proved`. The distinction exists
    # only for ARTEFACT_MUTATION entries that RECORD `STAYED_GREEN`, where the
    # published finding is that the gate does not move; scoring those as
    # unproved would make the honest thing to do with a measured gap be to
    # delete the record of it.
    assert all(r.as_recorded for r in results), [
        f"{r.mutation}@{r.step_id}: expected {r.expected}, got {r.verdict}"
        for r in results if not r.as_recorded]
    # Every dimension must be represented, or a whole dimension's entries could
    # be un-replayed while the count still looked healthy.
    dims = {r.dim for r in results}
    assert dims == set(range(1, 9)), (
        f"replay touched dimensions {sorted(dims)}; a dimension with no "
        f"re-executed witness has only structural locks on it")


def test_a_cut_off_replay_reports_a_shortfall_and_never_a_verdict():
    """BIDIRECTIONAL control on the total budget, driven both ways.

    The budget exists because ``timeout`` bounds one cell and nothing bounded
    the plan, so in ``all`` mode the aggregate outlives the harness and
    ``--timeout-method=thread`` takes the SESSION — 0 lines matching
    ``passed|failed|error`` in the whole output, which greps as zero failures.

    Both arms are asserted here, because a budget that quietly swallowed pairs
    would be a worse bug than the one it fixes:

      * BOUNDED — the plan is cut off, and the pairs that were never started are
        OMITTED. Not fabricated, not scored, not skipped. The shortfall is what
        ``test_the_replay_actually_ran_and_is_not_starved`` reads.
      * UNBOUNDED (``budget=None``, the audit lane and every previous caller) —
        every pair runs. This arm is what proves the fix did not buy its green
        by making the replay do less.

    Driven against a stub rather than the real replay: what is under test is the
    scheduling, and a real pair costs tens of seconds.
    """
    victim = L.MUTATIONS[0]
    plan = tuple((victim.name, f"stub{i}") for i in range(12))

    def stub(mut, sid=None, timeout=900):
        seen.append(int(timeout))
        time.sleep(0.2)
        return L.ReplayResult(mut.name, mut.dim, str(sid), True, 0, 1, True, "")

    seen: List[int] = []
    original = L.replay
    try:
        L.replay = stub  # type: ignore[assignment]
        cut = L.replay_many(plan, jobs=1, timeout=REPLAY_TIMEOUT, budget=0.7)
        clamped = list(seen)
        seen.clear()
        full = L.replay_many(plan, jobs=1, timeout=REPLAY_TIMEOUT, budget=None)

        def boom(mut, sid=None, timeout=900):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=timeout)

        L.replay = boom  # type: ignore[assignment]
        expired = L.replay_many(plan, jobs=1, timeout=REPLAY_TIMEOUT, budget=5)
    finally:
        L.replay = original  # type: ignore[assignment]

    assert 0 < len(cut) < len(plan), (
        f"a 0.7 s budget over {len(plan)} pairs of 0.2 s each returned "
        f"{len(cut)}; the budget either did not fire or ate everything")
    assert all(r.proved for r in cut), (
        "a pair the budget DID reach must keep its real verdict; the budget "
        "may only decide what runs, never what a run concluded")
    assert clamped and all(0 < t <= REPLAY_TIMEOUT for t in clamped), (
        f"per-cell clamp went outside (0, {REPLAY_TIMEOUT}]: {clamped}")
    assert len(full) == len(plan), (
        f"budget=None replayed {len(full)} of {len(plan)}; the unbounded path "
        f"is the audit lane and must be untouched")
    assert expired == (), (
        "a pair whose own clamp fired was NOT measured, so it may not appear "
        "as a verdict; it belongs in the shortfall")


def test_the_replay_budget_is_below_the_harness_bound_that_would_kill_it():
    """The budget must be derived from the bound pytest is really enforcing.

    A budget at or above the harness bound is no budget at all — the session
    dies first and the replay never gets to stop itself. And with no bound in
    effect (the audit lane, which is where ``all`` mode belongs) there must be
    no budget, or this file would silently truncate the audit.
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
    assert budget == float(bound) - REPLAY_BUDGET_HEADROOM, (
        f"budget {budget}s is not {bound}s minus the declared "
        f"{REPLAY_BUDGET_HEADROOM}s of headroom")


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
        if nf.dim not in range(1, 9):
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

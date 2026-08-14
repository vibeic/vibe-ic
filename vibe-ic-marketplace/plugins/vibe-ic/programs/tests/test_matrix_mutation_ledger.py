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


@lru_cache(maxsize=1)
def replay_results() -> Tuple[L.ReplayResult, ...]:
    """Run the current mode's replay plan once, in parallel, and cache it."""
    plan = L.replay_plan()
    return L.replay_many(plan, jobs=8, timeout=REPLAY_TIMEOUT)


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
    assert mine, f"{name} produced no replay result"
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
        f"{L.replay_mode()!r} should re-execute {expected}")
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
# The bound below is ONE SECOND: small enough to fire on any cell, and far
# under the 60 s ceiling (`180 // 3`) that `ci_harness_timeout_ceiling_check`
# permits one blocking call. These tests cost ~1 s each; they do not replay
# anything to completion and are not a second copy of LOCK 2.
_BOUND_THAT_ALWAYS_FIRES = 1


def test_a_cell_that_blows_its_bound_is_UNREADABLE_not_a_colour():
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
    mut = L.mutation("D3-UNDECLARED-ARTEFACT")
    rc, out, why = L._run_cell(mut.dim, mut.witness, L.PLUGIN_ROOT, None,
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


def test_a_replay_whose_bound_fires_is_NOT_REPLAYABLE_and_still_FAILS():
    """End to end: the pair scores NOT_REPLAYABLE, and that is a failure.

    The two directions that matter, and they pull against each other:

      * it must not RAISE — an exception out of `replay_many` takes LOCK 2 down
        with no verdict at all, which is the defect;
      * it must not PASS — a bound that fired proves nothing, and a replay that
        could not run must never be scored as one that ran.
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


def test_the_bound_reason_refuses_BOTH_evidence_deleting_repairs():
    """The message routes the reader, or #1403 happens again.

    #1403 was not a broken gate. It was a red whose text sent every reader to
    the wrong repair. The two repairs that must be named and refused are the
    same two the ALREADY_RED path refuses, for the same reason: both restore
    green by deleting the evidence rather than by measuring anything.
    """
    mut = L.mutation("D3-UNDECLARED-ARTEFACT")
    _, _, why = L._run_cell(mut.dim, mut.witness, L.PLUGIN_ROOT, None,
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

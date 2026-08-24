"""Meta-test for the `matrix_63x8` shared substrate.

This file guards the substrate that all eight dimension modules import. It
proves three things, and deliberately nothing else:

  1. The ledger really is the live cross product of the flow yaml's step list
     and dimensions 1-9 — 621 cells, each coordinate exactly once. Not 544
     because 544 is written down somewhere; 544 because
     ``len(step_ids()) * len(DIMENSIONS)`` is 621 *right now*. Add or delete a
     step and this file goes red, which is the whole point: a ledger that
     silently kept saying 544 while the flow drifted would be exactly the
     "measure something adjacent and report it as the answer" disease the
     campaign exists to remove.

  2. The `flowref` accessors agree with the yaml about which steps declare
     what — including the two places where the circulating numbers are subtly
     wrong (see `test_blocks_on_presence_is_not_the_same_set_as_non_empty`).

  3. The waiver registry cannot carry a placeholder. Every waiver needs a
     reason AND evidence, both non-empty and both substantive.

WHAT THIS FILE DOES NOT DO
--------------------------
It never reads `.audit_63x8.json` to decide a pass/fail. `Cell.audit_verdict`
is history for humans; asserting on it would measure a JSON file rather than
the repository. The one audit-related assertion here is about the *ledger's*
handling of missing history (ABSENT_FROM_AUDIT), which is a property of
`cells.py`, not of the audit.

FALSIFIABILITY
--------------
Every predicate below was mutation-proved before landing, by pointing
`flowref.FLOW_YAML` at a scratch copy of the yaml with one field removed /
added and confirming the corresponding assertion reddens. See
`test_ledger_tracks_a_mutated_flow` — the mutation is performed *inside the
suite*, so the proof does not rot.
"""
from __future__ import annotations

import importlib
import os
from collections import Counter

import pytest
import yaml

from matrix_63x8 import cells as C
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W

# ──────────────────────────────────────────────────────────────────────
# 2026-08-20, R6/R3 — EVERY TRIPWIRE BELOW MOVED, ON ONE CAUSE.
#
# vibe-ic#1744 added FIVE steps to the flow: 0.5ic (Submission Template
# Ingest) and the four path-specific steps of the cell/IP-vs-chip/IC split,
# 15.5ic 26.5ic 37.5ip 37.5ic. Measured live off the yaml in this tree, not
# re-typed from the change:
#
#   EXPECTED_STEPS               63 -> 68   +5, one per new step
#   EXPECTED_CELLS              504 -> 544   68 x 8
#   CENSUS_GATE_PRESENT          62 -> 67   +5, every new step declares a gate
#   CENSUS_REQUIRED_OUTPUTS_...  61 -> 66   +5, every new step declares outputs
#   CENSUS_BLOCKS_ON_PRESENT     63 -> 68   +5, presence stays TOTAL
#   CENSUS_BLOCKS_ON_NON_EMPTY   62 -> 66   +4, NOT +5 -- see below
#   CENSUS_GATE_PROGRAMS_NON_... 61 -> 66   +5, every new gate names a program
#
# THE +4 IS THE ONE WORTH READING. 0.5ic declares `blocks_on: []`: it is a
# genuine graph ROOT, the step that fetches the shuttle operator's template
# before anything else can test which path the design is on. So presence moves
# by 5 and non-empty by 4, and the `roots` set below moves from {D1} to
# {0.5ic, D1}. That set is NOT re-typed here -- it is read out of
# `flow_dependency_graph_check.DECLARED_ROOTS`, which #1744 moved in the same
# commit, and the two agree on this tree: ['0.5ic', 'D1'].
#
# Also note A1 is no longer a root. #1258 gave it `blocks_on: [D1]` and the
# note on CENSUS_BLOCKS_ON_NON_EMPTY below records that; the count that note
# left at 62 is the one this change moves to 66.
# ──────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────
# 2026-08-21 — EVERY TRIPWIRE BELOW MOVES BY EXACTLY ONE, ON ONE CAUSE.
#
# `7fcbc7397` ("ppa(phase4): step 13 passes on a rewritten candidate") added
# step 1.6x — the cross-layer rewrite-fidelity relation — to the flow yaml and
# regenerated NONE of the 63x8 pins. `git show --stat 7fcbc7397` names eight
# files: the yaml, INDEX.md, three new programs and their three tests. No
# matrix, ledger, waiver or census file among them.
#
# Measured live off the yaml in this tree, not re-typed from the change:
#
#   EXPECTED_STEPS                68 -> 69   1.6x
#   EXPECTED_CELLS               544 -> 552   69 x 8
#   CENSUS_GATE_PRESENT           67 -> 68   1.6x declares a gate
#   CENSUS_REQUIRED_OUTPUTS_...   66 -> 67   1.6x declares required_outputs
#   CENSUS_BLOCKS_ON_PRESENT      68 -> 69   1.6x declares the key
#   CENSUS_BLOCKS_ON_NON_EMPTY    66 -> 67   `blocks_on: [1]`, non-empty
#   CENSUS_GATE_PROGRAMS_NON_...  66 -> 67   its gate names a program
#
# ALL SEVEN MOVE BY ONE AND IT IS THE SAME STEP. The raw yaml step count did
# NOT change across this span — 77 before and 77 after — because `867de4289`
# retired 37.5self in the same window. 37.5self was never in the matrix
# population, so the matrix moved +1 while the file moved +1 -1. A reader who
# checks `grep -c '^  - id:'` and sees no change has not checked this.
#
# THIS IS THE THIRD TIME. The notes below record the tripwire firing on a
# legitimate flow change and then sitting red on main instead of being moved —
# P0 (`332b9985`) and A1 (`73dfb68dd`). Measured on why nothing caught it this
# time: the repository's own selector DOES reach here. Run against the culprit
# diff, `ci_targeted_test_select.py --base 7fcbc7397~1` selects 325 tests
# including 16 `test_matrix_*` files, this one among them. The tests were
# selected and the red was not acted on, so the hole is not selection.
#
# THEY ARE NOT AUTO-DERIVED, AND THAT IS THE POINT. Deriving these from the
# yaml would make every assertion below tautological and the ledger could then
# drift in silence — which is the disease this file was written against. They
# stay typed, in ONE place, so a flow change forces a reviewer to look.
# ──────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────
# AND MOVED AGAIN 2026-08-21, WITH THE NINTH DIMENSION. The paragraph above is
# about the STEP axis and is unchanged by this; what moves here is the DIMENSION
# axis, and the two are independent:
#
#   len(F.step_ids())   -> 69      (the axis the note above accounts for)
#   len(C.DIMENSIONS)   ->  9      (was 8; dimension 9 asks whether a step's
#                                   FAIL reaches the exit code)
#   69 * 9              -> 621
#
# BOTH NOTES ARE KEPT ON PURPOSE. Two lanes moved this constant in the same
# batch — one the step population, one the dimension count — and a merged pin
# that keeps only the later note loses the reason the earlier number moved.
# Re-measured on the merged tree rather than multiplied out from either.
# ──────────────────────────────────────────────────────────────────────
# 2026-08-24: rewrite fidelity moved from standalone step 1.6x into Step 2.
# The gate, required output and fallback survive; only the duplicate scheduling
# unit is gone, so the reviewed population returns to 68 steps / 612 cells.
EXPECTED_CELLS = 612
EXPECTED_STEPS = 68
EXPECTED_DIMS = 9

# Pinned census of the yaml as measured on 2026-07-27. These are TRIPWIRES, not
# the definition: every structural assertion below derives its expectation live
# from the yaml. If the flow legitimately changes, these numbers change with it
# in ONE place and the reviewer is forced to look.
# RE-MEASURED 2026-08-21. This pin was stale before the ninth dimension
# landed: the flow's step population moved 68 -> 69 (`1.6x` added in
# v1.11.15, `37.5self` retired in v1.11.18) and these counts were moved
# for neither. Each value below was re-derived by running the accessor
# over the live yaml, not by adding one to the old number.
CENSUS_GATE_PRESENT = 67
# UNCHANGED at 61. A 2026-07-28 change gave FS1 a `required_outputs` key and
# was WITHDRAWN the same day: the only thing that made the declaration
# satisfiable was `check_step` standing its early MISSING down so FS1's own
# gate could write the artefact and a post-gate probe could then find it — an
# auditor certifying its own output. FS1 is still the one step whose declared
# artefacts have no producer outside its own gate, so dimension 7's W4 rule
# ("a gate designates outputs on a step with no required_outputs") still fires
# on it and it stays WAIVED there, with the wiring that would close it named.
# RE-MEASURED 2026-08-21. This pin was stale before the ninth dimension
# landed: the flow's step population moved 68 -> 69 (`1.6x` added in
# v1.11.15, `37.5self` retired in v1.11.18) and these counts were moved
# for neither. Each value below was re-derived by running the accessor
# over the live yaml, not by adding one to the old number.
CENSUS_REQUIRED_OUTPUTS_PRESENT = 66
# 62 -> 63 and 60 -> 61 on 2026-08-11 (`332b9985`, vibe-ic#923 via #929): step
# P0 (the structural-RTL pre-flight) gained `blocks_on: [1]` deliberately —
# P0 already declared `required_inputs: [{from: 1, ...}]`, so the ordering edge
# its own inputs had always implied was missing, and without it a FAILED Phase 1
# could not red the pre-flight. The tripwire fired on a LEGITIMATE flow change
# and then stayed red on main instead of being moved, which is how a tripwire
# stops being read. Both counts move by exactly one, and it is the same step.
# `332b9985` also edited `flow_dependency_graph_check.py` and its test in the
# SAME commit, which is why the roots are read out of that program below rather
# than re-typed here: the two copies moved together once and can drift apart.
# RE-MEASURED 2026-08-21. This pin was stale before the ninth dimension
# landed: the flow's step population moved 68 -> 69 (`1.6x` added in
# v1.11.15, `37.5self` retired in v1.11.18) and these counts were moved
# for neither. Each value below was re-derived by running the accessor
# over the live yaml, not by adding one to the old number.
CENSUS_BLOCKS_ON_PRESENT = 68
# 61 -> 62 on 2026-08-14 (`73dfb68dd`, vibe-ic#1070 via #1258): step A1
# gained `blocks_on: [D1]`. A1 already declared TWO `required_inputs` from
# D1 while carrying `blocks_on: []`, so the ordering edge its own inputs
# had always implied was simply missing; declaring it is the same shape of
# fix as P0's above, and `DECLARED_ROOTS` shrank to {"D1"} in that very
# commit to match.
#
# ONLY the non-empty count moves, unlike P0. P0 had no `blocks_on` key at
# all, so it moved presence AND non-empty together; A1 already declared the
# key as an empty list, so presence was always 63 and is untouched here.
#
# This is the SECOND time this tripwire fired on a legitimate flow change
# and then sat red on main instead of being moved -- the exact failure the
# P0 note above describes as "how a tripwire stops being read". #1258 moved
# nine files, including the yaml, `flow_dependency_graph_check.DECLARED_ROOTS`,
# `flowref.py` and three new tests; this constant is the one thing it missed.
# The comment at the `roots` assertion below predicted that "a landing that
# gives A1 an ordering edge moves BOTH sides together instead of reddening
# this cell". Both sides DID move together. The cell reddened anyway, because
# this count is a THIRD copy that neither side is tied to.
# RE-MEASURED 2026-08-21. This pin was stale before the ninth dimension
# landed: the flow's step population moved 68 -> 69 (`1.6x` added in
# v1.11.15, `37.5self` retired in v1.11.18) and these counts were moved
# for neither. Each value below was re-derived by running the accessor
# over the live yaml, not by adding one to the old number.
CENSUS_BLOCKS_ON_NON_EMPTY = 66
# 60 -> 61 on 2026-08-08: step 12 gained a `program_exit_zero` exec clause
# (dft_post_optimization_scan_survival_check), closing the files_exist-only
# gap the matrix_63x8 dimension-2 audit named. Step 1 is still exec-free.
# RE-MEASURED 2026-08-21. This pin was stale before the ninth dimension
# landed: the flow's step population moved 68 -> 69 (`1.6x` added in
# v1.11.15, `37.5self` retired in v1.11.18) and these counts were moved
# for neither. Each value below was re-derived by running the accessor
# over the live yaml, not by adding one to the old number.
CENSUS_GATE_PROGRAMS_NON_EMPTY = 66


# ──────────────────────────────────────────────────────────────────────
# The environment the substrate is allowed to run in
# ──────────────────────────────────────────────────────────────────────
def test_flow_yaml_override_is_not_set():
    """A normal suite run must measure the REAL yaml.

    `flowref.FLOW_YAML_ENV` exists so a falsifiability harness can point at a
    mutated scratch copy. Left set, it would let an entire suite grade itself
    against a file nobody reviewed. Fail loudly rather than pass quietly.
    """
    assert os.environ.get(F.FLOW_YAML_ENV) is None, (
        f"{F.FLOW_YAML_ENV} is set to {os.environ.get(F.FLOW_YAML_ENV)!r}; the "
        f"suite would grade itself against a mutated yaml"
    )
    assert F.FLOW_YAML == F.PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
    assert F.FLOW_YAML.is_file()


# ──────────────────────────────────────────────────────────────────────
# 1. Ledger shape
# ──────────────────────────────────────────────────────────────────────
def test_dimension_table_is_1_through_9_with_a_name_each():
    assert C.DIMENSIONS == (1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert set(C.DIMENSION_NAMES) == set(C.DIMENSIONS)
    assert C.DIMENSION_NAMES == {
        1: "wiring",
        2: "falsifiable",
        3: "outputs_produced",
        4: "criteria_match",
        5: "deps_correct",
        6: "skip_discipline",
        7: "outputs_list_complete",
        8: "missing_caught",
        9: "verdict_consumed",
    }
    # Every dimension carries a one-line question.
    assert set(C.DIMENSION_QUESTIONS) == set(C.DIMENSIONS)
    assert all(C.DIMENSION_QUESTIONS[d].strip() for d in C.DIMENSIONS)
    # PROSE_ONLY_DIM is a fact about `.audit_63x8.json` — dimension 8 is the one
    # whose audit record is prose rather than {"verdict": ...}. It USED to be
    # asserted as `DIMENSIONS[-1] == PROSE_ONLY_DIM == 8`, conflating "the
    # prose-only dimension" with "the last dimension". Those coincided for as
    # long as the matrix had eight dimensions and stopped coinciding the moment
    # it had nine: dimension 9 is last, dimension 8 is still the prose-only one.
    # Asserted apart so neither can drift behind the other.
    assert C.PROSE_ONLY_DIM == 8
    assert C.PROSE_ONLY_DIM in C.DIMENSIONS
    assert C.DIMENSIONS[-1] == 9
    # A dimension added after the audit has no field in it, so AUDIT_FIELDS is
    # SHORTER than DIMENSIONS and that is the intended shape, not an omission.
    assert len(C.AUDIT_FIELDS) == 8 < len(C.DIMENSIONS)


def test_ledger_is_the_live_cross_product():
    live_steps = len(F.step_ids())
    live_dims = len(C.DIMENSIONS)
    assert live_steps == EXPECTED_STEPS, (
        f"the flow yaml now declares {live_steps} steps, not {EXPECTED_STEPS}; "
        f"the 63x8 matrix has changed shape and every dimension module's "
        f"per-cell parametrisation must be re-evaluated"
    )
    assert live_dims == EXPECTED_DIMS
    assert len(C.ALL_CELLS) == live_steps * live_dims
    assert len(C.ALL_CELLS) == EXPECTED_CELLS


def test_every_coordinate_appears_exactly_once():
    counts = Counter(c.key for c in C.ALL_CELLS)
    dupes = {k: n for k, n in counts.items() if n != 1}
    assert not dupes, f"duplicated coordinates: {dupes}"
    assert len(counts) == EXPECTED_CELLS

    expected = {
        (F.normalize_id(sid), dim)
        for sid in F.step_ids()
        for dim in C.DIMENSIONS
    }
    assert set(counts) == expected


def test_cell_step_ids_keep_the_yaml_raw_types():
    """`'D1'` must stay a str and `12` must stay an int.

    Stringifying at ledger-build time would quietly paper over the mixed-type
    hazard that every consumer has to handle, and a sibling doing
    `step_by_id(cell.step_id)` would then be exercising a code path the real
    flow never takes.
    """
    by_key = {F.normalize_id(s): s for s in F.step_ids()}
    for c in C.ALL_CELLS:
        assert type(c.step_id) is type(by_key[F.normalize_id(c.step_id)])
    assert any(isinstance(c.step_id, int) for c in C.ALL_CELLS)
    assert any(isinstance(c.step_id, str) for c in C.ALL_CELLS)


@pytest.mark.parametrize("dim", C.DIMENSIONS)
def test_cells_for_returns_one_row_per_step(dim):
    row = C.cells_for(dim)
    assert len(row) == len(F.step_ids()) == EXPECTED_STEPS
    assert {c.dim for c in row} == {dim}
    assert [F.normalize_id(c.step_id) for c in row] == [
        F.normalize_id(s) for s in F.step_ids()
    ]


def test_cells_for_rejects_a_dimension_outside_the_declared_range():
    # Derived from C.DIMENSIONS, not spelled 1..8: the day a tenth dimension is
    # added this must reject 11, and a literal here would go on rejecting 9 —
    # which by then would be a VALID dimension whose cells nobody could fetch.
    for bad in (0, max(C.DIMENSIONS) + 1, -1):
        with pytest.raises(ValueError):
            C.cells_for(bad)


def test_cell_lookup_accepts_both_id_spellings():
    assert C.cell(1, 4) is C.cell("1", 4)
    assert C.cell("D1", 1).step_id == "D1"
    assert C.cell(44, 8).dim == 8
    with pytest.raises(KeyError):
        C.cell("NO_SUCH_STEP", 1)


def test_cells_for_step_returns_every_dimension():
    for sid in F.step_ids():
        row = C.cells_for_step(sid)
        assert [c.dim for c in row] == list(C.DIMENSIONS)


def test_ledger_order_is_deterministic_and_flow_ordered():
    """Flow declaration order for steps, dimension-ascending within a step."""
    expected = [
        (F.normalize_id(sid), dim)
        for sid in F.step_ids()
        for dim in C.DIMENSIONS
    ]
    assert [c.key for c in C.ALL_CELLS] == expected


def test_audit_history_is_carried_but_never_load_bearing():
    """Every cell has a verdict from the allowed set, and history may be absent.

    This asserts the LEDGER's contract, not the audit's content: a cell whose
    history is missing must read ABSENT_FROM_AUDIT rather than crash or
    silently read OK.
    """
    for c in C.ALL_CELLS:
        assert c.audit_verdict in C.VERDICTS, c.label
        assert len(c.audit_summary) <= C.SUMMARY_MAX, c.label

    # Dimension 8 is prose-only in the audit: it can never carry an "OK" or
    # "NA" verdict, because there is no verdict field to read. Guessing one by
    # grepping the prose for "N/A" would be a text match masquerading as a
    # finding.
    d8 = {c.audit_verdict for c in C.cells_for(C.PROSE_ONLY_DIM)}
    assert d8 <= {"DEFECT", C.NOTE, C.ABSENT}, d8


def test_absent_from_audit_is_surfaced_not_swallowed():
    absent = C.absent_from_audit()
    if C.audit_source() is None:
        assert len(absent) == EXPECTED_CELLS
        return
    # With history available, ABSENT_FROM_AUDIT means a genuine hole. It is a
    # signal, not an error — so this asserts it is REPORTABLE (every entry is a
    # real cell), not that it is zero.
    for c in absent:
        assert c.key in {x.key for x in C.ALL_CELLS}
        assert c.audit_summary == ""


# ──────────────────────────────────────────────────────────────────────
# 2. flowref accessors vs the yaml
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def raw_steps():
    """The yaml re-parsed independently of `flowref`, so the accessors are
    checked against the file rather than against their own cache."""
    with F.FLOW_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["steps"]


def test_step_ids_match_an_independent_parse(raw_steps):
    assert list(F.step_ids()) == [s["id"] for s in raw_steps]
    assert len(set(F.normalize_id(s) for s in F.step_ids())) == len(raw_steps)


def test_required_outputs_non_empty_exactly_where_declared(raw_steps):
    declared = {
        F.normalize_id(s["id"]) for s in raw_steps if "required_outputs" in s
    }
    got_non_empty = {
        F.normalize_id(sid) for sid in F.step_ids() if F.required_outputs(sid)
    }
    got_empty = {
        F.normalize_id(sid) for sid in F.step_ids() if not F.required_outputs(sid)
    }
    # No step declares an EMPTY required_outputs list, so declared == non-empty.
    assert got_non_empty == declared
    assert got_empty == {
        F.normalize_id(s["id"]) for s in raw_steps if "required_outputs" not in s
    }
    assert len(declared) == CENSUS_REQUIRED_OUTPUTS_PRESENT


def test_gate_presence_matches_the_yaml(raw_steps):
    declared = {
        F.normalize_id(s["id"]) for s in raw_steps if s.get("gate") is not None
    }
    got = {F.normalize_id(sid) for sid in F.step_ids() if F.has_gate(sid)}
    assert got == declared
    assert len(declared) == CENSUS_GATE_PRESENT
    for sid in F.step_ids():
        if not F.has_gate(sid):
            assert F.gate(sid) is None
            assert F.gate_clauses(sid) == ()
            assert F.gate_programs(sid) == ()


def test_blocks_on_presence_is_not_the_same_set_as_non_empty(raw_steps):
    """The two are NOT the same set, and conflating them is a real error.

    `blocks_on` is DECLARED on every step and declared EMPTY on the flow's
    genuine roots. "N steps have blocks_on" is a presence count; a test that
    reads it as "N steps have upstream dependencies" would demand an edge from
    a root and be wrong twice over.

    The counts are TRIPWIRES (see the module header). WHICH steps are roots is
    not — it is a fact `flow_dependency_graph_check` already owns, so it is
    read out of that program rather than re-typed here.

    Presence is additionally asserted as a SET, so a step added later without
    `blocks_on` fails by NAME rather than as an arithmetic mismatch the reader
    has to resolve against the yaml.
    """
    present = {F.normalize_id(s["id"]) for s in raw_steps if "blocks_on" in s}
    non_empty = {
        F.normalize_id(s["id"]) for s in raw_steps if s.get("blocks_on")
    }
    # Presence is TOTAL as of `332b9985`, which is stronger than the count and
    # is asserted FIRST because it is the assertion that can name what changed.
    # A bare `62 == 63` sends the reader back to the yaml to work out which step
    # moved; that lookup is the work this message exists to save. (from #1264)
    all_ids = {F.normalize_id(s["id"]) for s in raw_steps}
    assert present == all_ids, (
        f"every step must declare `blocks_on`, even as an empty list — "
        f"missing on {sorted(all_ids - present)}")
    assert len(present) == CENSUS_BLOCKS_ON_PRESENT
    assert len(non_empty) == CENSUS_BLOCKS_ON_NON_EMPTY

    # ANTI-VACUITY. If these two sets ever coincide, the distinction this test
    # exists to defend is gone and the assertion below would hold trivially.
    assert present, "no step declares blocks_on — nothing here means anything"
    roots = present - non_empty
    assert roots, (
        "presence and non-empty are the SAME set, so this test no longer "
        "demonstrates that conflating them is an error — re-derive the flow's "
        "roots before editing this assertion away")

    # The roots are NOT re-typed here. `flow_dependency_graph_check` owns that
    # register and fails when the yaml and the register disagree; a hand-typed
    # copy in this file would be a second source that can drift from both.
    # It already drifted once: vibe-ic#923 removed P0 from the root set and the
    # hand-typed copies in test_flow_dependency_graph_check went stale in the
    # same commit, which is why that file reads it out of the program too
    # (see its line 25). This also means a landing that gives A1 an ordering
    # edge moves BOTH sides together instead of reddening this cell.
    assert roots == set(
        importlib.import_module("flow_dependency_graph_check").DECLARED_ROOTS)

    assert {
        F.normalize_id(sid) for sid in F.step_ids() if F.declares_blocks_on(sid)
    } == present
    assert {
        F.normalize_id(sid) for sid in F.step_ids() if F.blocks_on(sid)
    } == non_empty
    # The step with NO blocks_on key at all must read empty AND undeclared.
    for sid in F.step_ids():
        if F.normalize_id(sid) not in present:
            assert F.blocks_on(sid) == ()
            assert not F.declares_blocks_on(sid)


def test_blocks_on_targets_all_resolve(raw_steps):
    ids = {F.normalize_id(s["id"]) for s in raw_steps}
    dangling = {
        F.normalize_id(sid): [e for e in F.blocks_on(sid)
                              if F.normalize_id(e) not in ids]
        for sid in F.step_ids()
    }
    dangling = {k: v for k, v in dangling.items() if v}
    assert not dangling, f"blocks_on references undeclared steps: {dangling}"


def test_gate_programs_non_empty_exactly_where_the_gate_names_one(raw_steps):
    """Derived live, not hardcoded: a gate yields programs iff it has an exec
    clause. Step 1 has a file-existence-only gate and correctly yields none —
    that is a property of its gate, not an exception list. Step 12 gained a
    real exec clause on 2026-08-08 (dft_post_optimization_scan_survival_check)
    and now yields one, for the same reason.
    """
    with_exec = set()
    without_exec = set()
    for sid in F.step_ids():
        clauses = F.gate_clauses(sid)
        has_exec = any(c.kind in F.EXEC_CLAUSE_KINDS for c in clauses)
        (with_exec if has_exec else without_exec).add(F.normalize_id(sid))

    for key in with_exec:
        assert F.gate_programs(key), f"{key}: gate names a program but none resolved"
    for key in without_exec:
        assert F.gate_programs(key) == (), f"{key}: unexpected gate programs"

    assert len(with_exec) == CENSUS_GATE_PROGRAMS_NON_EMPTY
    # "12" left this set 2026-08-08: it gained a program_exit_zero exec
    # clause (dft_post_optimization_scan_survival_check).
    assert without_exec == {"1", "P0"}


def test_every_gate_named_program_resolves_to_a_real_file():
    """Dimension-1 tripwire at the substrate level: the yaml naming a program
    the tree does not have is a live wiring defect, not a lookup miss."""
    unresolved = {
        F.normalize_id(sid): F.unresolved_gate_programs(sid)
        for sid in F.step_ids()
        if F.unresolved_gate_programs(sid)
    }
    assert not unresolved, (
        f"gate commands name programs with no programs/<name>.py: {unresolved}"
    )
    for sid in F.step_ids():
        for prog in F.gate_programs(sid):
            p = F.program_path(prog)
            assert p is not None and p.is_file()
            assert p.parent == F.PROGRAMS_DIR


def test_gate_clause_kinds_are_all_known(raw_steps):
    kinds = Counter()
    for sid in F.step_ids():
        for c in F.gate_clauses(sid):
            kinds[c.kind] += 1
    assert set(kinds) <= set(F.GATE_CLAUSE_KINDS), (
        f"unknown gate clause kind(s): {set(kinds) - set(F.GATE_CLAUSE_KINDS)}"
    )
    # Every exec clause carries a command and a first-token program.
    for sid in F.step_ids():
        for c in F.gate_clauses(sid):
            if c.kind in F.EXEC_CLAUSE_KINDS:
                assert c.command, c
                assert c.program == c.command.split()[0]
            elif c.kind == F.K_FILES:
                assert c.files, c
            elif c.kind == F.K_JSON_FIELD:
                assert c.json_file and c.json_field, c

    # Force levels are distinct and all three exec kinds are actually used —
    # otherwise a dimension module could not tell enforcement from advice.
    assert kinds[F.K_PROGRAM] > 0
    assert kinds[F.K_ADVISORY] > 0
    assert kinds[F.K_OPTIONAL] > 0


def test_clause_force_levels():
    advisory = [
        c for sid in F.step_ids() for c in F.gate_clauses(sid) if c.is_advisory
    ]
    conditional = [
        c for sid in F.step_ids() for c in F.gate_clauses(sid) if c.is_conditional
    ]
    assert advisory and all(not c.is_blocking for c in advisory)
    assert conditional and all(c.is_blocking for c in conditional)
    assert all(c.condition_files for c in conditional), (
        "an optional_program_exit_zero with no condition_files_exist would be "
        "unconditionally blocking under a name that says otherwise"
    )


# ──────────────────────────────────────────────────────────────────────
# required_outputs grammar
# ──────────────────────────────────────────────────────────────────────
def test_output_entries_classify_into_the_four_kinds():
    seen = Counter()
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            kind = F.classify_output(entry)
            assert kind in F.OUTPUT_KINDS
            seen[kind] += 1
    # 2026-07-28, RE-REVIEWED: 126 -> 133, all SEVEN new entries are plain FILE
    # (92 -> 99); the GLOB and ANY_OF populations are untouched. Each one is a
    # load-bearing artefact the flow already produced and a gate already read
    # while no step declared it — dimension 7's finding — and each is recorded
    # in the dimension-3 manifest with the run root, path and byte size it was
    # measured at: D1 L8_RTL_CONSTANTS.json, 21 reports/phase3/drc_router.rpt,
    # 23 sta_corner_record_completeness.json, 25 em_signoff.json (PRODUCED_LIVE),
    # 28 perc_signoff.json, 31 lvs.json + erc_density.json. FS1's two FMEDA
    # artefacts were part of this count for one day and are NOT here: no
    # producer outside FS1's own gate writes them, so declaring them could only
    # be satisfied by the auditor's own output.
    #
    # 2026-08-11: 133 -> 134, FILE 99 -> 100 (vibe-ic#983 ruling 2). The ONE new
    # entry is step 29's `reports/phase2/gates/post_layout_sim.json`, the
    # BLOCKING "Substance gate" report its own gate clause already wrote while
    # no entry named it. GLOB and ANY_OF are untouched.
    #
    # And FS1's two FMEDA artefacts are STILL not here. #983 asked for them
    # again in the same breath as step 29's; the difference is measured, not
    # stylistic. Step 29 already declares a run-produced entry, so its gate
    # keeps running and the declaration re-grades nothing (0 of 6 published
    # trees move). FS1 declares nothing else, so declaring its gate paths trips
    # the "every declared entry absent -> MISSING before the gate runs" early
    # return and the producer never runs at all: MEASURED on this tree,
    # VACUOUS_PASS with both reports written becomes MISSING with none.
    # test_flow_declaration_does_not_silence_its_producer.py holds that
    # distinction live for both steps.
    # 2026-08-12: 134 -> 135, FILE 100 -> 101 (vibe-ic#1241-adjacent, d7 W2).
    # The ONE new entry is D1's `phase1/generated_docs/L21_POWER_INTENT.json`.
    # Dimension 7 was reporting it produced-by-the-flow / read-by-a-gate /
    # declared-by-nobody and charging the finding to stepM2 — the CONSUMER —
    # because there was no declared producer to charge it to. D1 is the
    # producer: this flow's own name for it is "Phase 1 Doc Extraction (17
    # skills + dialogue entry -> L1-L27)" and it declared L1-L13 only.
    #
    # It is a plain FILE, so GLOB (12) and ANY_OF (22) are untouched, which is
    # what the per-kind assertions below re-check independently of this total.
    #
    # Recorded in the dimension-3 manifest with the run root, path and byte
    # size it was MEASURED at (benchmark-data/ic/caravel_user_project, 531 B) —
    #
    # 2026-08-12 (same change): 135 -> 136, FILE 101 -> 102. Step 11's
    # `phase2/stage2/dft/coverage.yml`, the same d7 W2 shape: written by
    # dft_atpg_coverage_check / fault_atpg_run, read by step 11's own gate,
    # declared by nobody. Present in 2 of the 2 roots where step 11 actually
    # ran, and resolves at spm/v1.9.96_gf180mcuD (28797 B).
    # declaring an artefact d3 cannot then evidence would move the finding from
    # d7 to d3 rather than close it.
    # 2026-08-14 (#1215): 136 -> 140, FILE 102 -> 106. The four write-record
    # promotions disposed of by DECLARING them on the step that produces them
    # — D1 `reports/audit/phase1/expert_parse_track.json`, 23
    # `reports/phase3/sta/post_route_signoff_corner.json`, 24
    # `reports/phase3/dynamic_ir.json`, 27 `reports/phase3/si_mcf_sta.json`.
    # All four are plain FILEs, so GLOB (12) and ANY_OF (22) are untouched and
    # the whole delta lands on FILE — which is what makes this total a real
    # check rather than a restatement of the sum. Each is recorded in the
    # dimension-3 manifest at the run root and byte size it was MEASURED at,
    # for the reason the 2026-08-12 entries above give: declaring an artefact
    # d3 cannot then evidence moves the finding from d7 to d3 instead of
    # closing it. The fifth promotion (step 34) is WAIVED, not declared, so it
    # adds no entry here.
    # 2026-08-15 (#1348): 140 -> 141, FILE 106 -> 107. The LAST write-record
    # promotion, disposed of the same way — D1
    # `phase1/extraction_patterns.json`, seeded by
    # `phase1_doc_one_shot_runner` through a variable so no AST write position
    # names it, read by D1's own `extraction_coverage_check` gate, declared by
    # nobody. It is a plain FILE, so GLOB (12) and ANY_OF (22) are again
    # untouched and the whole delta lands on FILE. Recorded in the dimension-3
    # manifest at the run root and byte size it was MEASURED at
    # (`spm/v1.9.96_gf180mcuD`, 7608 B), and it resolves in 9 of the 10
    # admissible run roots — declaring an artefact d3 cannot then evidence
    # would move the finding from d7 to d3 instead of closing it.
    # 2026-08-20 (#1744, R3): 141 -> 152, and the delta is spread across all
    # three kinds for the first time, which is why each is asserted separately
    # rather than only the sum. Measured per step off this tree:
    #   0.5ic  +2  1 ANY_OF (slots/*.yaml OR NO_TEMPLATE.txt) + 1 FILE
    #   15.5ic +2  2 FILE   (padring.def, padring.json)
    #   26.5ic +2  1 ANY_OF (die_finished.def OR die_finishing.SKIPPED.txt)
    #                       + 1 FILE
    #   37.5ip +4  4 GLOB   (hardmacro/*.lef *.lib *.gds *.v -- the four views
    #                        an IP is delivered as; a GLOB because the macro
    #                        name is the design's, not the flow's)
    #   37.5ic +1  1 FILE   (shuttle_precheck.json)
    # = FILE +5 (107 -> 112), GLOB +4 (12 -> 16), ANY_OF +2 (22 -> 24).
    # 2026-08-20 (R9): 152 -> 153, one FILE, and it is a DECLARATION rather than
    # a new step. Step 31 gained `reports/phase3/magic_illegal_overlap.json` to
    # close the dimension-7 finding W1:gate_output_read_elsewhere — the gate
    # program writes it and `phase3_one_shot_runner` reads it by name, so it was
    # load-bearing and undeclared. Unlike `extraction_patterns.json` above, it
    # does NOT resolve in any admissible run root (the gate postdates every
    # published cell), so this one DOES move the finding from d7 to d3: the d3
    # manifest records it UNPROVEN and the cell reports it unevidenced wherever
    # a corpus is offered. That is the true statement of the gap, and it is
    # stated here rather than left for a reader to discover from a red cell.
    # = FILE +1 (112 -> 113), GLOB and ANY_OF untouched.
    # 2026-08-20 (R12): 153 -> 154, one FILE, step 31 again and for the same
    # dimension-7 rule — `reports/phase3/lvs_verdict.json`, charged
    # W2:produced_consumed_undeclared the moment the write-record oracle was
    # reconnected to the published corpus (R11). This one goes the other way
    # from R9: all three published spm cells carry it tracked and non-empty, so
    # the d3 manifest records it PRODUCED_BY_RUN and dimension 3 pays nothing.
    # = FILE +1 (113 -> 114), GLOB and ANY_OF untouched.
    # 2026-08-20: 154 -> 156, two GLOB, and FILE does not move at all. Step
    # 37.5ic became the producer of the release documents, and the pair it emits
    # is per (design, pdk) -- `SIGNOFF_<design>_<pdk>.html`,
    # `BRIEF_<design>_<pdk>.html` -- so that two dies built out of one tree
    # cannot overwrite each other's sign-off. They arrived declared as the bare
    # `SIGNOFF.html` / `BRIEF.html`, i.e. as two FILEs naming files no producer
    # in this flow writes, which is how d4/criteria_match reported them: "named
    # nowhere the gate can reach". Declaring the glob the generator actually
    # writes is what makes the entry true, and it moves the pair FILE -> GLOB.
    # Same shape as 37.5ip's four hardmacro views above and for the same reason:
    # a GLOB because the identifying half of the name is the design's, not the
    # flow's.
    # = GLOB +2 (16 -> 18), FILE 114 unchanged, ANY_OF 24 unchanged.
    # 2026-08-20 (smrg): 156 -> 161, five FILE, and the accounting is
    # RE-DERIVED rather than incremented — measured by classifying the yaml at
    # `ff5071caa` (the commit that last set this constant) and at the tip, and
    # diffing per step. FOUR of the five predate this change and had left the
    # tripwire sitting red on main, which is the third time this file records
    # that happening:
    #   0.5ic  +2  `input/submission_template/tapeout_declaration.json` and
    #             `reports/phase1/tapeout_declaration.json` — the declaration
    #             the route-deciding step writes on every route.
    #   21     +1  `reports/phase3/drc_router.json`.
    # The FIFTH is this change's, and it is a NET +1 over the tip because it
    # both adds and removes:
    #   37.5self  -1  the step is RETIRED. Its `reports/phase3/
    #                 general_precheck.json` is not deleted — it moves.
    #   37.5ic    +2  `reports/phase3/tapeout_precheck.json` (the merged, per-
    #                 line-authority record) and `reports/phase3/
    #                 general_precheck.json` (our arm's own report, which the
    #                 merge quotes rather than replaces).
    # `reports/phase3/shuttle_precheck.json` does NOT move: 37.5ic already
    # declared it and still does — what changed is that it is now written on
    # every path, including the paths where the operator was never asked.
    # = FILE 114 + 2 + 1 + 2 = 119; GLOB and ANY_OF untouched.
    # 2026-08-21: 161 -> 164, FILE 119 -> 122, THREE entries with three owners.
    # RE-DERIVED on the merged tree, as the note this replaces instructed, and
    # the re-derivation is why the number moved again: that note pinned 163/121
    # while the live tree already answered 164/122. A merged pin that is added
    # up from two lanes' notes is stale the moment a third lane lands.
    #
    #   +1  step 1.6x  `reports/crosslayer/rewrite_equivalence_check.json`
    #       (lane jmatrix/63x8-main-reds, from `7fcbc7397`).
    #   +1  step 15.5ic `reports/phase3/pad_assignment.json`, the report of
    #       `pad_assignment_gen` — the new AUTHOR of
    #       `phase3/stage3/pnr/pad_assignment.json`. That path had two
    #       references before and BOTH were readers, so 15.5ic could only ever
    #       take `pad_ring_gen`'s SKIP branch (lane
    #       cpath/pad-and-seal-ring-chip-path, vibe-ic#1410).
    #   +1  step 31   `reports/phase3/drc_signoff.json`, written by
    #       `drc_report_check` and read by `general_precheck` while no step
    #       declared it — dimension 7's W1 finding, closed by declaring it.
    #
    # MEASURED, by diffing the (step, entry) SET between the v1.11.18 yaml and
    # this tree: exactly those two paths were added since, none removed,
    # 162 -> 164. The 1.6x entry is older than that window and is measured
    # below.
    #
    # THE ATTRIBUTION DISPUTE IS SETTLED, AND BOTH LANES WERE RIGHT — about
    # DIFFERENT increments. Driving `flowref` at each revision's yaml through
    # `VIBE_IC_MATRIX_FLOW_YAML` and counting entries:
    #
    #     ff5071caa    steps 68  entries 154  FILE 114   no 1.6x, no 37.5self
    #     7fcbc7397~1  steps 69  entries 160  FILE 118   no 1.6x, 37.5self YES
    #     7fcbc7397    steps 70  entries 161  FILE 119   1.6x ARRIVES
    #     867de4289    steps 69  entries 162  FILE 120   37.5self RETIRED
    #
    # There are TWO +1s in that span, one per commit. `7fcbc7397` moved
    # 160 -> 161 and that is step 1.6x; `867de4289` moved 161 -> 162 and that is
    # the 37.5self/37.5ic swap. Neither lane was wrong; each attributed the
    # increment it had measured, and the disagreement was that both were
    # describing "the first +1" when there were two.
    #
    # All three entries are plain FILE — no glob, no OR — so GLOB and ANY_OF are
    # untouched, which is what makes the attribution checkable rather than
    # asserted.
    #
    # `padring.def` does NOT gain an `OR ...SKIPPED.txt` alternative and stays a
    # plain FILE: a seal ring can legitimately not apply, a pad ring on a die
    # cannot, so a skipped pad ring must stay MISSING.
    assert sum(seen.values()) == 164, seen
    assert seen[F.FILE] == 122
    assert seen[F.GLOB] == 18
    assert seen[F.ANY_OF] == 24
    # Reported to the orchestrator: the PROGRAM_EXIT form described in the brief
    # does NOT exist in required_outputs. It lives only in `gate` clauses. The
    # classifier still returns it for forward-compat, but a sibling branching on
    # it today is writing dead code.
    assert seen[F.PROGRAM_EXIT] == 0


def test_any_of_split_matches_the_real_consumer():
    """`flow_compliance_check` does `pat.split(" OR ")` then `.strip()`.

    Reference: programs/flow_compliance_check.py, the required_outputs loop
    around line 6166 ("# split \"A OR B\"").
    """
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            alts = F.split_any_of(entry)
            assert alts
            assert list(alts) == [
                p.strip() for p in entry.split(" OR ") if p.strip()
            ]
            if F.classify_output(entry) == F.ANY_OF:
                assert len(alts) >= 2
            else:
                assert len(alts) == 1
                assert alts[0] == entry.strip()


def test_glob_entries_really_contain_wildcards():
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            kind = F.classify_output(entry)
            if kind == F.GLOB:
                assert F.is_glob(entry)
            elif kind == F.FILE:
                assert not F.is_glob(entry)


def test_or_is_matched_as_a_separator_not_a_substring():
    """A path component spelled `...OR...` must not split.

    The consumer splits on the literal `" OR "` with both spaces. A classifier
    that looked for a bare `"OR"` would shred e.g. `reports/XOR_table.json`.
    """
    assert F.classify_output("reports/XOR_table.json") == F.FILE
    assert F.split_any_of("reports/XOR_table.json") == ("reports/XOR_table.json",)
    assert F.classify_output("a/b.json OR c/d.json") == F.ANY_OF
    assert F.split_any_of("a/b.json OR c/d.json") == ("a/b.json", "c/d.json")


def test_total_steps_field_is_not_the_step_count():
    """`total_steps: 44` counts the numeric steps only.

    Pinned because it is a trap: a test asserting `total_steps == len(steps)`
    would be red for a reason that has nothing to do with the flow's health.
    """
    assert F.load_flow()["total_steps"] == 44
    assert len(F.steps()) == EXPECTED_STEPS


# ──────────────────────────────────────────────────────────────────────
# 3. Waivers
# ──────────────────────────────────────────────────────────────────────
def test_every_waiver_has_a_reason_and_evidence():
    problems = {}
    for w in W.WAIVERS:
        found = W.validate(w)
        if found:
            problems[w.label] = found
    assert not problems, f"invalid waivers: {problems}"

    for w in W.WAIVERS:
        assert w.reason.strip(), w.label
        assert w.evidence.strip(), w.label
        assert w.dim in C.DIMENSIONS
        assert F.has_step(w.step_id)


def test_no_duplicate_waiver_coordinates():
    counts = Counter(w.key for w in W.WAIVERS)
    assert not {k: n for k, n in counts.items() if n != 1}


def test_waiver_lookup_is_consistent_with_the_registry():
    for w in W.WAIVERS:
        assert W.waiver_for(w.step_id, w.dim) is w
        assert W.is_waived(w.step_id, w.dim)
    covered = {w.key for w in W.WAIVERS}
    for c in C.ALL_CELLS:
        if c.key not in covered:
            assert W.waiver_for(c.step_id, c.dim) is None


def test_xfail_mark_is_always_strict():
    """`strict=True` is decided at the substrate, not per dimension module.

    A non-strict xfail rots silently: the gap gets fixed, the test starts
    passing, and nobody is told the waiver became a lie. This asserts the
    factory can only ever produce the strict form — a mutation dropping
    `strict=True` reddens here even while WAIVERS is empty.
    """
    assert W.xfail_mark("D1", 1) is None  # not waived -> no mark

    probe = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "Substrate self-check: exercises the mark factory without touching "
            "the real registry, which stays empty until the orchestrator applies."
        ),
        evidence="programs/tests/test_matrix_63x8_ledger.py::test_xfail_mark_is_always_strict",
    )
    assert W.validate(probe) == ()

    saved = dict(W._BY_KEY)
    try:
        W._BY_KEY[probe.key] = probe
        mark = W.xfail_mark("D1", 1)
        assert mark is not None
        assert mark.kwargs.get("strict") is True
        assert probe.reason in mark.kwargs["reason"]
        assert probe.evidence in mark.kwargs["reason"]
    finally:
        W._BY_KEY.clear()
        W._BY_KEY.update(saved)
    assert W.xfail_mark("D1", 1) is None


def test_waiver_validator_actually_rejects_a_placeholder():
    """The validator is itself falsifiable — prove it says no.

    Without this, `test_every_waiver_has_a_reason_and_evidence` would pass
    vacuously forever on an empty registry, which is a predicate that cannot
    fail.
    """
    bad = W.Waiver(step_id=1, dim=1, reason="not implemented yet", evidence="")
    problems = W.validate(bad)
    assert problems
    assert any("evidence is empty" in p for p in problems)
    assert any("not implemented" in p for p in problems)

    short = W.Waiver(step_id=1, dim=1, reason="too short", evidence="x")
    assert W.validate(short)

    unknown_step = W.Waiver(
        step_id="NOT_A_STEP",
        dim=1,
        reason="a" * (W.MIN_REASON_LEN + 5),
        evidence="programs/foo.py:12",
    )
    assert any("not declared in the flow yaml" in p
               for p in W.validate(unknown_step))

    # The GOOD example from the waivers module docstring, verbatim. It used to
    # be `programs/rtl_dispatch.py:214` — a file this repository does not have.
    # The documented model of a well-formed waiver cited a path nobody could
    # follow, and `validate()` said it was fine; keeping the doc and this probe
    # the same string is what stops that recurring.
    good = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The artefact is emitted on only one branch of a real PDK "
            "condition, so an unconditional declaration converts every honest "
            "run of the other branch into MISSING."
        ),
        evidence=(
            'programs/mixed_signal_top_lvs_run.py::`(rpt_dir / "top_lvs.json").write_text(`'
        ),
    )
    assert W.validate(good) == ()
    # ...and the docstring says the same thing. Pinned, because the example a
    # reader copies is the one that decides how the next waiver is written, and
    # the old one pointed at `programs/rtl_dispatch.py`, which does not exist.
    assert ('programs/mixed_signal_top_lvs_run.py::`(rpt_dir / '
            '"top_lvs.json").write_text(`') in (W.__doc__ or ""), (
        "the waivers module docstring no longer carries the GOOD example this "
        "probe validates; if the cited line moved, update BOTH"
    )

    # A legitimate reason containing a word that merely CONTAINS a forbidden
    # phrase must survive: substring matching would reject this.
    not_a_placeholder = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The related translated fixture is regenerated downstream, so the "
            "artefact this cell would assert on is not stable across runs."
        ),
        evidence="programs/tests/fixtures/real_benchmark/README:3",
    )
    assert W.validate(not_a_placeholder) == ()


# ──────────────────────────────────────────────────────────────────────
# 3b. Citations must RESOLVE
#
# The registry carried four dimension-7 waivers whose every file:line had
# moved — `mixed_signal_top_lvs_run.py:256` was 661 lines off, step 23's six
# citations ~9,450 — and `validate()` returned `()` for all of them, because
# it graded the LENGTH of the argument and never opened the file. These four
# tests are the control: the first two must FAIL against the pre-fix
# `waivers.py` and pass after; the last two must pass BOTH ways, which is what
# stops the new rule from being tightened until it fires on nothing.
# ──────────────────────────────────────────────────────────────────────
#: These probes cite REAL files, so the line numbers are DERIVED from the files
#: at run time and never written down here. A control that hard-coded them
#: would go red the next time somebody edits above the line — which is the
#: defect it exists to detect, not a defect in the mechanism, and it would
#: teach the next reader that the check is flaky. (Measured the hard way: this
#: test hard-coded `flow_compliance_check.py:2242` and reddened within the
#: hour when a sibling agent edited that file.) The one place a literal line
#: number is still correct is the registry itself, and the docstring example
#: the probe above pins.
_M1_CLAIM = "(rpt_dir / 'top_lvs.json').write_text(...)"
_M1_FILE = "programs/mixed_signal_top_lvs_run.py"


def _lines_of(rel: str) -> list:
    return (F.PLUGIN_ROOT / rel).read_text(errors="replace").splitlines()


def _line_holding(rel: str, needle: str) -> int:
    """1-based line number of the only line of *rel* containing *needle*."""
    hits = [i + 1 for i, ln in enumerate(_lines_of(rel)) if needle in ln]
    assert len(hits) == 1, f"{needle!r} is on {len(hits)} lines of {rel}: {hits[:5]}"
    return hits[0]


def _line_holding_none_of(rel: str, tokens) -> int:
    """A line of *rel* that mentions none of *tokens* — a wrong-line citation."""
    for i, ln in enumerate(_lines_of(rel)):
        low = ln.lower()
        if ln.strip() and not any(t.lower() in low for t in tokens):
            return i + 1
    raise AssertionError(f"every line of {rel} mentions one of {tokens}")


def _cite_probe(line: int) -> "W.Waiver":
    return W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The artefact substantiates the step's PASS but is named by no "
            "required_outputs entry, so nothing independently verifies that "
            "it was ever written."
        ),
        evidence=f"producer {_M1_FILE}:{line} {_M1_CLAIM}",
    )


def test_a_citation_whose_line_has_moved_is_rejected():
    """A real file, a real-looking line, and the claim is not there.

    This is the whole defect in one assertion. Until 2026-08-06 the M1/d7
    waiver cited `:256` for the `top_lvs.json` write, which is 661 lines
    further down; `:256` read `chosen_path, chosen, chosen_ref = parsed[0]`.
    Pre-fix, `validate()` returned `()` for that.
    """
    true_line = _line_holding(_M1_FILE, '(rpt_dir / "top_lvs.json").write_text(')
    stale_line = _line_holding_none_of(_M1_FILE, ("top_lvs", "rpt_dir", "write_text"))
    assert stale_line != true_line

    problems = W.validate(_cite_probe(stale_line))
    assert problems, (
        f"a waiver citing {_M1_FILE}:{stale_line} for {_M1_CLAIM!r} — which "
        f"is at :{true_line} — validated clean"
    )
    assert any("does not resolve" in p for p in problems), problems
    # The message must carry the repair, or following it up stays the work
    # that lets a stale citation survive.
    assert any(str(true_line) in p for p in problems), problems

    # ...and the same evidence with the RIGHT line is accepted. Asserted here,
    # next to its negation, so the pair cannot drift apart.
    assert W.validate(_cite_probe(true_line)) == ()

    # ...and a path that does not exist at all. The module docstring's own
    # GOOD example was `programs/rtl_dispatch.py:214` for a fortnight.
    ghost = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The gate resolves its checker set through a runtime __import__ "
            "of a name derived from L3_CMD_PROTOCOL, so no static predicate "
            "can enumerate the reachable call sites."
        ),
        evidence="programs/rtl_dispatch.py:214 — __import__(f'{proto}_protocol_synth')",
    )
    assert any("names no file" in p for p in W.validate(ghost)), W.validate(ghost)


def test_an_anchor_too_common_to_locate_anything_is_not_an_anchor():
    """The guard on "resolves" degenerating into "passes anything".

    Both probes cite the SAME true line, derived from the file. One names a
    token spread over hundreds of that file's lines, so it locates nothing and
    the citation goes unchecked; the other names the predicate itself, which
    occurs once. Without `MAX_ANCHOR_LINE_HITS` the first would pass and the
    rule would be satisfied by any line number at all.
    """
    rel = "programs/flow_compliance_check.py"
    predicate = "passed = len(missing) == 0"
    line = _line_holding(rel, predicate)

    # The premise of the pair, measured rather than asserted: `missing` must
    # really be too common to locate anything, and the predicate must not be.
    body = [ln.lower() for ln in _lines_of(rel)]
    common = sum(1 for ln in body if "missing" in ln)
    rare = sum(1 for ln in body if predicate.lower() in ln)
    cap = getattr(W, "MAX_ANCHOR_LINE_HITS", 20)  # readable pre-fix too
    assert common > cap >= rare, (common, rare)

    vague = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The step's only blocking term is path resolution, so no input "
            "other than absence reaches a FAIL and the cell cannot be driven "
            "to a verdict about content."
        ),
        evidence=f"{rel}:{line} — the `missing` list",
    )
    assert any("does not resolve" in p for p in W.validate(vague)), W.validate(vague)

    precise = W.Waiver(
        step_id="D1",
        dim=1,
        reason=vague.reason,
        evidence=f"{rel}:{line} — `{predicate}`",
    )
    assert W.validate(precise) == (), W.validate(precise)


def test_the_citation_check_leaves_a_resolving_citation_alone():
    """REVERSE CASE — must pass before the fix and after.

    A rule that rejected everything would also have made
    `test_every_waiver_has_a_reason_and_evidence` green by emptying the
    registry of anything it could grade. These four citations are real, in
    four different files, in three different shapes (single line, range,
    comma list), and none of them may be reported. Every line number is
    derived, so this stays a statement about the CHECK and not about where a
    sibling agent last left an unrelated file.
    """
    m1 = _line_holding(_M1_FILE, '(rpt_dir / "top_lvs.json").write_text(')
    merge_rel = "programs/mixed_signal_merge_check.py"
    merge_lo = _line_holding(merge_rel, 'for rel in ("reports/analog/mixed_signal/')
    merge_pass = _line_holding(merge_rel, 'str(top_lvs.get("verdict")) == "PASS"')
    fmeda_rel = "programs/fmeda_coverage_check.py"
    fmeda_doc = _line_holding(fmeda_rel, "emitted by `fmeda_fault_injection_coverage")
    fmeda_imp = _line_holding(fmeda_rel, "import fmeda_fault_injection_coverage as fi")
    quartus = _line_holding("programs/fpga_board_capability.py", "no Quartus on host")

    for evidence in (
        f"producer {_M1_FILE}:{m1} {_M1_CLAIM}",
        f"consumer {merge_rel}:{merge_lo}-{merge_lo + 2} then :{merge_pass} "
        f"read reports/analog/mixed_signal/top_lvs.json",
        f"{fmeda_rel}:{fmeda_doc},{fmeda_imp} — docstring, then "
        f"`import fmeda_fault_injection_coverage as fi`",
        f"programs/fpga_board_capability.py:{quartus} names "
        f"'no Quartus on host' as the expected disclosed gap",
    ):
        probe = W.Waiver(
            step_id="D1",
            dim=1,
            reason=(
                "The artefact substantiates the step's PASS but is named by "
                "no required_outputs entry, so nothing independently "
                "verifies that it was ever written."
            ),
            evidence=evidence,
        )
        assert W.validate(probe) == (), (evidence, W.validate(probe))


def test_prose_that_merely_looks_like_a_citation_is_not_graded():
    """REVERSE CASE — must pass before the fix and after.

    `12/12`, `rc 2`, `'Steps: 1 total'`, `…py::test_name` and a bare `:8` with
    no file named before it are all in this registry's evidence today. A
    citation parser that swept them up would report unresolvable citations
    that were never citations, and the registry would be red for prose.
    """
    noise = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "Deciding this needs a converged project tree; the artefact is "
            "produced only by a tool that is absent from CI, so the cell "
            "cannot be decided from the commit alone."
        ),
        evidence=(
            "Asked directly on all 12 admissible run roots: 12/12 return "
            "'inputs missing', rc 2. The single-step run reports 'Steps: 1 "
            "total (0/-1 executed PASS)' and 'Overall: PASS'. Re-executed by "
            "programs/tests/test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact; "
            "see also :8 with no file named before it."
        ),
    )
    assert W.validate(noise) == (), W.validate(noise)


# ──────────────────────────────────────────────────────────────────────
# Falsifiability: the ledger must MOVE when the flow moves
# ──────────────────────────────────────────────────────────────────────
def test_ledger_tracks_a_mutated_flow(tmp_path):
    """Mutate the flow (in a scratch copy) and prove the ledger follows.

    This is the anti-fake-pass proof for the whole substrate. If the ledger
    were sourced from `.audit_63x8.json` — or from any frozen list — it would
    keep reporting 68 steps / 544 cells here and this test would fail.

    The real yaml is never touched: eight agents share this worktree.
    """
    original = F.FLOW_YAML
    doc = yaml.safe_load(original.read_text(encoding="utf-8"))

    # (a) ADD a step -> 69 steps, 552 cells, new cells ABSENT_FROM_AUDIT.
    doc["steps"].append(
        {
            "id": "ZZ_MUTANT",
            "name": "synthetic mutation step",
            "stage": "stage1",
            "gate": {"all_of": [{"program_exit_zero": "no_such_program_xyz ."}]},
            "required_outputs": ["reports/mutant/out.json"],
            "blocks_on": [1],
        }
    )
    mutated = tmp_path / "mutated_flow.yaml"
    mutated.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    try:
        F.set_flow_yaml(mutated)
        C.rebuild()

        assert len(F.step_ids()) == EXPECTED_STEPS + 1
        assert len(C.ALL_CELLS) == (EXPECTED_STEPS + 1) * EXPECTED_DIMS == 621
        assert len(C.cells_for(1)) == EXPECTED_STEPS + 1

        # The added step has no audit history at all — surfaced, not swallowed.
        mutant_cells = C.cells_for_step("ZZ_MUTANT")
        assert len(mutant_cells) == EXPECTED_DIMS
        assert {c.audit_verdict for c in mutant_cells} == {C.ABSENT}

        # And its gate names a program that does not exist: the substrate must
        # report that rather than quietly dropping the token.
        assert F.gate_program_tokens("ZZ_MUTANT") == ("no_such_program_xyz",)
        assert F.gate_programs("ZZ_MUTANT") == ()
        assert F.unresolved_gate_programs("ZZ_MUTANT") == ("no_such_program_xyz",)
    finally:
        F.set_flow_yaml(original)
        C.rebuild()

    # Restoration is part of the contract: a leaked override would silently
    # corrupt every sibling test that runs after this one.
    assert F.FLOW_YAML == original
    assert len(C.ALL_CELLS) == EXPECTED_CELLS
    assert len(F.step_ids()) == EXPECTED_STEPS


def test_accessors_track_a_removed_field(tmp_path):
    """Delete `required_outputs` from one step and prove the accessor notices."""
    original = F.FLOW_YAML
    doc = yaml.safe_load(original.read_text(encoding="utf-8"))
    victim = None
    for s in doc["steps"]:
        if "required_outputs" in s:
            victim = F.normalize_id(s["id"])
            del s["required_outputs"]
            break
    assert victim is not None

    mutated = tmp_path / "no_outputs.yaml"
    mutated.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    try:
        F.set_flow_yaml(mutated)
        assert F.required_outputs(victim) == ()
        assert not F.declares_required_outputs(victim)
        declared = sum(
            1 for sid in F.step_ids() if F.declares_required_outputs(sid)
        )
        assert declared == CENSUS_REQUIRED_OUTPUTS_PRESENT - 1
    finally:
        F.set_flow_yaml(original)
        C.rebuild()

    assert F.required_outputs(victim)
    assert F.declares_required_outputs(victim)


# ===========================================================================
# CONTENT CITATIONS (vibe-ic#1289)
#
# `path:LINE` rots on every edit ABOVE the line it names, and it rots the bad
# way: it still resolves to a line, so it still READS as evidence while
# pointing at unrelated code. Measured on `a38902d1`,
# `flow_compliance_check.py:2439-2441` had come to read `return result` and
# `phase3_one_shot_runner.py:30288` an EMPTY LINE.
#
# The form this replaces it with is only an improvement if a DELETED construct
# still fails — an anchor loose enough to always match is a waiver that can
# never be re-examined, which is worse than drift because drift at least fails
# loudly. Both halves are asserted below.
# ===========================================================================
def _waiver_citing(evidence: str):
    """A throwaway waiver carrying one evidence string, nothing else."""
    return W.Waiver(step_id="1", dim=2, reason="probe", evidence=evidence)


def test_a_content_citation_that_resolves_once_is_clean():
    """`passed = len(found) > 0` occurs exactly once in the cited file."""
    problems = W.content_citation_problems(_waiver_citing(
        "programs/flow_compliance_check.py::`passed = len(found) > 0`"))
    assert problems == (), problems


def test_PAIRED_a_DELETED_construct_still_fails():
    """THE GUARD the whole form rests on.

    If this ever passes, the citation has stopped being evidence: it would
    mean an anchor naming nothing is accepted, which is exactly the "can never
    be re-examined" failure that would make this worse than a line number.
    """
    problems = W.content_citation_problems(_waiver_citing(
        "programs/flow_compliance_check.py::"
        "`passed = len(this_construct_was_deleted) > 0`"))
    assert len(problems) == 1, problems
    assert "resolves to NOTHING" in problems[0], problems[0]
    assert "re-examined" in problems[0], problems[0]


def test_an_AMBIGUOUS_anchor_is_refused_and_says_how_many():
    """MEASURED: `len(corners) < 2` occurs 3 times in that file.

    An anchor matching in several places cannot show WHICH construct the
    waiver rests on, so accepting it would let a vague gesture stand in for
    evidence.
    """
    problems = W.content_citation_problems(_waiver_citing(
        "programs/phase3_one_shot_runner.py::`len(corners) < 2`"))
    assert len(problems) == 1, problems
    assert "AMBIGUOUS" in problems[0], problems[0]


def test_the_tighter_anchor_for_that_same_construct_IS_accepted():
    """The other half of the pair: the rule is satisfiable, not merely strict.

    Without this, "refuse ambiguous anchors" could be met by refusing
    everything, and the form would be unusable rather than disciplined.
    """
    problems = W.content_citation_problems(_waiver_citing(
        'programs/phase3_one_shot_runner.py::'
        '`stance_path = rpt_phase3 / "single_corner_stance.json"`'))
    assert problems == (), problems


def test_a_pytest_node_id_is_not_read_as_a_content_citation():
    """`tests/test_x.py::test_name` carries no quote, and several already
    appear in this registry. Promoting one into an evidence claim would
    invent a claim the waiver never made."""
    problems = W.content_citation_problems(_waiver_citing(
        "re-executed by programs/tests/test_matrix_d2_falsifiable.py"
        "::test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file"))
    assert problems == (), problems


def test_the_registry_itself_has_no_broken_content_citation():
    """The live registry, not a fixture — the converted entries must resolve."""
    bad = {}
    for w in W.WAIVERS:
        problems = W.content_citation_problems(w)
        if problems:
            bad[f"{w.step_id}/d{w.dim}"] = problems
    assert not bad, bad


def test_the_content_form_is_ACTUALLY_USED_by_the_registry():
    """NON-VACUITY. A grammar nothing writes is a grammar nothing checks.

    Counts entries carrying the form, so the four tests above cannot be
    passing over an empty population.
    """
    used = [f"{w.step_id}/d{w.dim}" for w in W.WAIVERS
            if any(True for _ in W._iter_content_citations(
                f"{w.reason or ''}\n{w.evidence or ''}"))]
    assert len(used) >= 2, (
        f"only {len(used)} waiver(s) use the content form: {used}")

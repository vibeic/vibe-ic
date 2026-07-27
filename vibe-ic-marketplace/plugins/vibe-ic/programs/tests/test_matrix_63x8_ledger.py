"""Meta-test for the `matrix_63x8` shared substrate.

This file guards the substrate that all eight dimension modules import. It
proves three things, and deliberately nothing else:

  1. The ledger really is the live cross product of the flow yaml's step list
     and dimensions 1-8 — 504 cells, each coordinate exactly once. Not 504
     because 504 is written down somewhere; 504 because
     ``len(step_ids()) * len(DIMENSIONS)`` is 504 *right now*. Add or delete a
     step and this file goes red, which is the whole point: a ledger that
     silently kept saying 504 while the flow drifted would be exactly the
     "measure something adjacent and report it as the answer" disease the
     campaign exists to remove.

  2. The `flowref` accessors agree with the yaml about which steps declare
     what — including the two places where the circulating numbers are subtly
     wrong (see `test_blocks_on_presence_is_62_but_non_empty_is_60`).

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

import os
from collections import Counter

import pytest
import yaml

from matrix_63x8 import cells as C
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W

EXPECTED_CELLS = 504
EXPECTED_STEPS = 63
EXPECTED_DIMS = 8

# Pinned census of the yaml as measured on 2026-07-27. These are TRIPWIRES, not
# the definition: every structural assertion below derives its expectation live
# from the yaml. If the flow legitimately changes, these numbers change with it
# in ONE place and the reviewer is forced to look.
CENSUS_GATE_PRESENT = 62
# 2026-07-28, RE-REVIEWED and changed 61 -> 62: FS1 gained a `required_outputs`
# key. It had none because `flow_compliance_check` returned MISSING before the
# gate ran, and FS1's gate IS the sole producer of its artefacts, so declaring
# anything made the step a permanent red. That ordering defect is fixed (the
# early exit stands down when EVERY missing entry is one of the step's own gate
# `--json` targets), and FS1 now declares both FMEDA artefacts. Dimension 7's
# W4 rule ("a gate designates outputs on a step with no required_outputs") no
# longer fires on it.
CENSUS_REQUIRED_OUTPUTS_PRESENT = 62
CENSUS_BLOCKS_ON_PRESENT = 62
CENSUS_BLOCKS_ON_NON_EMPTY = 60
CENSUS_GATE_PROGRAMS_NON_EMPTY = 60


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
def test_dimension_table_is_1_through_8_with_a_name_each():
    assert C.DIMENSIONS == (1, 2, 3, 4, 5, 6, 7, 8)
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
    }
    # Every dimension carries a one-line question; dimension 8 is the CATCHER
    # question and must stay last.
    assert set(C.DIMENSION_QUESTIONS) == set(C.DIMENSIONS)
    assert all(C.DIMENSION_QUESTIONS[d].strip() for d in C.DIMENSIONS)
    assert C.DIMENSIONS[-1] == C.PROSE_ONLY_DIM == 8


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


def test_cells_for_rejects_a_dimension_outside_1_8():
    for bad in (0, 9, -1):
        with pytest.raises(ValueError):
            C.cells_for(bad)


def test_cell_lookup_accepts_both_id_spellings():
    assert C.cell(1, 4) is C.cell("1", 4)
    assert C.cell("D1", 1).step_id == "D1"
    assert C.cell(44, 8).dim == 8
    with pytest.raises(KeyError):
        C.cell("NO_SUCH_STEP", 1)


def test_cells_for_step_returns_all_eight_dimensions():
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


def test_blocks_on_presence_is_62_but_non_empty_is_60(raw_steps):
    """The two are NOT the same set, and conflating them is a real error.

    `blocks_on` is DECLARED on 62 steps but declared EMPTY on D1 and A1 — the
    flow's two genuine roots. "62 steps have blocks_on" is a presence count; a
    test that reads it as "62 steps have upstream dependencies" would demand an
    edge from a root and be wrong twice over.
    """
    present = {F.normalize_id(s["id"]) for s in raw_steps if "blocks_on" in s}
    non_empty = {
        F.normalize_id(s["id"]) for s in raw_steps if s.get("blocks_on")
    }
    assert len(present) == CENSUS_BLOCKS_ON_PRESENT
    assert len(non_empty) == CENSUS_BLOCKS_ON_NON_EMPTY
    assert present - non_empty == {"D1", "A1"}

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
    clause. Steps 1 and 12 have file-existence-only gates and correctly yield
    none — that is a property of their gate, not an exception list.
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
    assert without_exec == {"1", "12", "P0"}


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
    # 2026-07-28, RE-REVIEWED: 126 -> 135, all NINE new entries are plain FILE
    # (92 -> 101); the GLOB and ANY_OF populations are untouched. Each one is a
    # load-bearing artefact the flow already produced and a gate already read
    # while no step declared it — dimension 7's finding — and each is recorded
    # in the dimension-3 manifest with the run root, path and byte size it was
    # measured at: D1 L8_RTL_CONSTANTS.json, 21 reports/phase3/drc_router.rpt,
    # 23 sta_corner_record_completeness.json, 25 em_signoff.json (PRODUCED_LIVE),
    # 28 perc_signoff.json, 31 lvs.json + erc_density.json, and FS1's two FMEDA
    # artefacts (FS1's whole required_outputs key is new).
    assert sum(seen.values()) == 135, seen
    assert seen[F.FILE] == 101
    assert seen[F.GLOB] == 12
    assert seen[F.ANY_OF] == 22
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

    good = W.Waiver(
        step_id="D1",
        dim=1,
        reason=(
            "The gate resolves its checker set through a runtime __import__ of "
            "a name derived from L3_CMD_PROTOCOL, so no static predicate can "
            "enumerate the reachable call sites."
        ),
        evidence="programs/rtl_dispatch.py:214",
    )
    assert W.validate(good) == ()

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
# Falsifiability: the ledger must MOVE when the flow moves
# ──────────────────────────────────────────────────────────────────────
def test_ledger_tracks_a_mutated_flow(tmp_path):
    """Mutate the flow (in a scratch copy) and prove the ledger follows.

    This is the anti-fake-pass proof for the whole substrate. If the ledger
    were sourced from `.audit_63x8.json` — or from any frozen list — it would
    keep reporting 63 steps / 504 cells here and this test would fail.

    The real yaml is never touched: eight agents share this worktree.
    """
    original = F.FLOW_YAML
    doc = yaml.safe_load(original.read_text(encoding="utf-8"))

    # (a) ADD a step -> 64 steps, 512 cells, new cells ABSENT_FROM_AUDIT.
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
        assert len(C.ALL_CELLS) == (EXPECTED_STEPS + 1) * EXPECTED_DIMS == 512
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

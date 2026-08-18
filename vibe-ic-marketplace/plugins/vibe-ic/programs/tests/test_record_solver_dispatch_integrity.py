"""test_record_solver_dispatch_integrity.py — the record-solver DISPATCH integrity gate.

The UNIFIED dispatch (`spec_artifact_registry.generate_from_record`) routes a record to
the FIRST record-level operation solver (in `_RECORD_SOLVER_NAMES` order) that fires; the
text-level registry `generate()` is the fall-through. `cvdp_atomic_bridge.solve` is the
thin driver that calls `generate_from_record` (supplying the record→ports text path).
The INVARIANT this file pins:

  for EVERY record, if ANY record solver fires STANDALONE
  (`<solver>.solve(record)` returns RTL), the dispatch MUST also return RTL.

A solver firing standalone yet the dispatch returning None is a ROUTING BUG — the solver
is not reachable. (A solver being SHADOWED by an EARLIER solver that also fires is fine —
first-firing wins — because the dispatch still returns RTL.)

ROOT-CAUSE THIS GUARDS AGAINST (the GP / table_lut bug): a record solver that references
a record-adapter MODULE-SCOPE attribute at its OWN import time (`table_lut_synth` does
`_COMPOSITE_RE = _bridge._COMPOSITE_RE`) was silently DROPPED from the dispatch list
because the solvers were imported while the adapter module was only half-initialized
(circular-import AttributeError swallowed by the loop `except`). The fix DEFERS the
record-solver import to the first `generate_from_record()` call, after every module is
fully defined. These tests assert (a) every NAMED solver is actually LOADED, (b) the GP
table_lut record routes through the dispatch, (c) the per-iteration deep-copy isolates a
hostile mutating solver, and (d) the full-dataset standalone==dispatch consistency
(0 routing bugs) when the real CVDP jsonl is present.

CHIP-AGNOSTIC: keyed on the dispatch structure, never on a design name. The dataset
consistency test is GATED on the real jsonl being on the host; the rest run anywhere.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import cvdp_atomic_bridge as B  # noqa: E402
import spec_artifact_registry as R  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
_GP_ID = "cvdp_copilot_Carry_Lookahead_Adder_0001"


def _strip_oracle(record: dict) -> dict:
    """Mirror `cvdp_atomic_bridge._strip_oracle`: a COPY of the record with the
    OFF-LIMITS oracle removed — the hidden test harness (`record["harness"]`:
    cocotb TB, `.env`) and the golden solution (`record["output"]`). The dispatch
    (`B.solve`) strips these up front so the deterministic solvers see ONLY
    `input.prompt` + `input.context` (CVDP official rule). Tests that compare a
    solver's STANDALONE firing against the dispatch must feed the SAME stripped
    record, or the comparison is not apples-to-apples (a standalone call handed a
    FULL record could read the harness and fire while the stripped dispatch does
    not — a false "routing bug")."""
    return {k: v for k, v in record.items() if k not in ("harness", "output")}


def _load_dataset():
    if not _DATASET.exists():
        pytest.skip("real CVDP dataset not on host")
    recs = [json.loads(l) for l in _DATASET.open() if l.strip()]
    if not recs:
        pytest.skip("empty CVDP dataset")
    return recs


# --------------------------------------------------------------------------- #
# (a) every NAMED solver is actually LOADED (the circular-import regression).
# --------------------------------------------------------------------------- #
def test_every_named_record_solver_is_loaded():
    """The whole point of the bug: a NAMED solver must not be silently dropped from
    the dispatch. Loaded names must equal the declared `_RECORD_SOLVER_NAMES`."""
    loaded = [m.__name__ for m in R._load_record_solvers()]
    declared = list(R._RECORD_SOLVER_NAMES)
    assert loaded == declared, (
        f"record-solver dispatch list drifted from the declared order/set.\n"
        f"declared={declared}\nloaded  ={loaded}\n"
        f"import_errors={R._RECORD_SOLVER_IMPORT_ERRORS}"
    )
    # no swallowed import error for any declared solver.
    assert R._RECORD_SOLVER_IMPORT_ERRORS == [], (
        f"record-solver import errors: {R._RECORD_SOLVER_IMPORT_ERRORS}")


def test_table_lut_is_in_the_dispatch_list():
    """`table_lut_synth` references `_bridge._COMPOSITE_RE` at module-import time;
    it is the solver the circular-import race dropped. It must be present now."""
    names = {m.__name__ for m in R._load_record_solvers()}
    assert "table_lut_synth" in names, (
        "table_lut_synth missing from the record-solver dispatch — the "
        "circular-import regression is back (it is dropped when imported "
        "mid-adapter-init)."
    )


def test_load_record_solvers_is_idempotent():
    """Re-loading restores the SAME declared order in place (no duplication / loss)."""
    before = [m.__name__ for m in R._load_record_solvers()]
    after = [m.__name__ for m in R._load_record_solvers()]
    assert before == after == list(R._RECORD_SOLVER_NAMES)


# --------------------------------------------------------------------------- #
# (b) the GP table_lut record now ROUTES through the dispatch.
# --------------------------------------------------------------------------- #
def test_table_lut_gp_record_routes_via_dispatch():
    """POSITIVE: the GP truth-table record fires `table_lut_synth` standalone AND
    routes through `bridge.solve` (the exact bug: standalone RTL, dispatch None)."""
    recs = _load_dataset()
    by_id = {r["id"]: r for r in recs}
    if _GP_ID not in by_id:
        pytest.skip("GP target record not in dataset")
    rec = by_id[_GP_ID]

    import table_lut_synth as T
    standalone = T.solve(copy.deepcopy(rec))
    assert standalone, "precondition: table_lut must fire standalone on the GP record"

    bridged = B.solve(copy.deepcopy(rec))
    assert bridged, "ROUTING BUG: table_lut fires standalone but dispatch returns None"
    # module must be named per the harness TOPLEVEL (GP).
    assert B.toplevel_name(rec) == "GP"
    assert "module GP" in bridged

    # the dispatch entry point itself solves it too (independent of the bridge driver).
    direct = R.generate_from_record(copy.deepcopy(rec))
    assert direct, "generate_from_record returns None for a record table_lut solves"


# --------------------------------------------------------------------------- #
# (c) the per-iteration deep-copy ISOLATES a hostile mutating solver.
# --------------------------------------------------------------------------- #
def test_dispatch_deepcopy_isolates_a_mutating_solver():
    """A solver that mutates `record['input']['prompt']` then declines must NOT corrupt
    a later solver nor the caller's record — the dispatch deep-copies per iteration."""
    recs = _load_dataset()
    by_id = {r["id"]: r for r in recs}
    if _GP_ID not in by_id:
        pytest.skip("GP target record not in dataset")
    rec = by_id[_GP_ID]

    class _Hostile:
        __name__ = "_hostile_mutator"

        @staticmethod
        def solve(r):
            r.setdefault("input", {})["prompt"] = "CORRUPTED-BY-EARLIER-SOLVER"
            return None  # declines — so a LATER solver must still see a clean prompt

    loaded = R._load_record_solvers()
    saved = list(loaded)
    before = json.dumps(rec, sort_keys=True)
    try:
        loaded.insert(0, _Hostile)
        bridged = B.solve(rec)  # pass the REAL record (no external copy)
    finally:
        loaded[:] = saved
    after = json.dumps(rec, sort_keys=True)

    assert bridged, "hostile front solver corrupted a later solver — deep-copy failed"
    assert before == after, "bridge.solve mutated the caller's record (deep-copy failed)"


def test_bridge_never_mutates_the_caller_record_over_dataset():
    """Over the WHOLE dataset, `bridge.solve(record)` must not mutate the record it is
    handed (the dispatch passes records to many solvers; none may leak a mutation out)."""
    recs = _load_dataset()
    mutated = []
    for r in recs:
        before = json.dumps(r, sort_keys=True)
        B.solve(r)
        if json.dumps(r, sort_keys=True) != before:
            mutated.append(r.get("id"))
    assert not mutated, f"bridge.solve mutated these records: {mutated}"


# --------------------------------------------------------------------------- #
# (d) FULL-DATASET standalone==dispatch consistency — 0 routing bugs for ALL solvers.
# --------------------------------------------------------------------------- #
def test_standalone_fires_implies_dispatch_solves_for_every_solver():
    """THE CORE INVARIANT. For each declared record solver, count records where the
    solver FIRES standalone but the dispatch returns None. That count MUST be 0 — a
    nonzero count is a routing bug (the solver is unreachable through the dispatch).

    APPLES-TO-APPLES: the dispatch (`B.solve`) strips the OFF-LIMITS oracle (harness
    + output) up front, so the solvers it dispatches to see ONLY prompt+context. We
    therefore call each solver STANDALONE on the SAME oracle-stripped record (via
    `_strip_oracle`). Comparing a standalone call on a FULL record — which could read
    the stripped harness and fire — against the stripped dispatch would flag a false
    routing bug. The invariant (standalone-fires ⟹ dispatch-solves) is still
    genuinely enforced, now on matched prompt+context-only records."""
    recs = _load_dataset()
    solvers = {m.__name__: m for m in R._load_record_solvers()}
    # bridge verdict per record (cached).
    bridge_hit = {r["id"]: bool(B.solve(copy.deepcopy(r))) for r in recs}

    routing_bugs = {}
    for name in R._RECORD_SOLVER_NAMES:
        S = solvers[name]
        bug_ids = []
        for r in recs:
            # Feed the solver the SAME oracle-stripped record the dispatch sees.
            stripped = _strip_oracle(copy.deepcopy(r))
            try:
                fired = bool(S.solve(stripped))
            except Exception:
                fired = False
            if fired and not bridge_hit[r["id"]]:
                bug_ids.append(r["id"])
        if bug_ids:
            routing_bugs[name] = bug_ids

    assert not routing_bugs, (
        "standalone-fires-but-dispatch-None routing bug(s) detected:\n"
        + "\n".join(f"  {k}: {v}" for k, v in routing_bugs.items())
    )


def test_bridge_solved_count_at_or_above_floor():
    """The dispatch must program-solve at least the known floor. Guards against a silent
    dispatch regression that drops solved records.

    The floor reflects the PROMPT+CONTEXT-ONLY compliant solve set: `B.solve` strips the
    OFF-LIMITS oracle (harness `.env` / cocotb `dut.<sig>` + `output` golden) BEFORE
    dispatching, so only records whose module name + interface are stated in
    `input.prompt` / `input.context` are program-solvable (records whose interface lived
    only in the harness now correctly SKIP — the intended compliant behavior, NOT a
    regression). Measured compliant solved count on the real 302-record CVDP dataset = 22
    (as of the oracle-strip cutover); the floor is set at that measured value."""
    recs = _load_dataset()
    solved = [r["id"] for r in recs if B.solve(copy.deepcopy(r))]
    assert len(solved) >= 22, (
        f"dispatch-solved count regressed to {len(solved)} (floor 22, the measured "
        f"prompt+context-only compliant solve count). solved={solved}"
    )
    assert _GP_ID in solved, "the GP table_lut record is no longer solved by the dispatch"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

"""test_cvdp_dispatch_integrity.py — the CVDP family-solver DISPATCH integrity gate.

The bridge (`cvdp_atomic_bridge.solve`) routes a record to the FIRST family solver
(in `_FAMILY_SOLVER_NAMES` order) that fires; the registry path is the fallback. The
INVARIANT this file pins:

  for EVERY record, if ANY family solver fires STANDALONE
  (`<solver>.solve(record)` returns RTL), the bridge MUST also return RTL.

A solver firing standalone yet the bridge returning None is a ROUTING BUG — the solver
is not reachable through the bridge. (A solver being SHADOWED by an EARLIER solver that
also fires is fine — first-firing wins — because the bridge still returns RTL.)

ROOT-CAUSE THIS GUARDS AGAINST (the GP / table_lut bug, fixed 2026-06-23): a family
solver that references a bridge MODULE-SCOPE attribute at its OWN import time
(`cvdp_table_lut_synth` does `_COMPOSITE_RE = _bridge._COMPOSITE_RE`) was silently
DROPPED from `_FAMILY_SOLVERS` because the bridge imported the solvers while the bridge
itself was only half-initialized (circular-import AttributeError swallowed by the loop
`except`). The fix DEFERS the family-solver import to the BOTTOM of the bridge module.
These tests assert (a) every NAMED solver is actually LOADED, (b) the GP table_lut
record routes through the bridge, (c) the per-iteration deep-copy isolates a hostile
mutating solver, and (d) the full-dataset standalone==bridge consistency (0 routing
bugs) when the real CVDP jsonl is present.

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

_DATASET = Path(
    "/home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/"
    "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl"
)
_GP_ID = "cvdp_copilot_Carry_Lookahead_Adder_0001"


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
def test_every_named_family_solver_is_loaded():
    """The whole point of the bug: a NAMED solver must not be silently dropped from
    `_FAMILY_SOLVERS`. Loaded names must equal the declared `_FAMILY_SOLVER_NAMES`."""
    loaded = [m.__name__ for m in B._FAMILY_SOLVERS]
    declared = list(B._FAMILY_SOLVER_NAMES)
    assert loaded == declared, (
        f"family-solver dispatch list drifted from the declared order/set.\n"
        f"declared={declared}\nloaded  ={loaded}\nimport_errors={B._IMPORT_ERRORS}"
    )
    # no swallowed import error for any declared solver.
    assert B._IMPORT_ERRORS == [], f"family-solver import errors: {B._IMPORT_ERRORS}"


def test_table_lut_is_in_the_dispatch_list():
    """`cvdp_table_lut_synth` references `_bridge._COMPOSITE_RE` at module-import time;
    it is the solver the circular-import race dropped. It must be present now."""
    names = {m.__name__ for m in B._FAMILY_SOLVERS}
    assert "cvdp_table_lut_synth" in names, (
        "cvdp_table_lut_synth missing from _FAMILY_SOLVERS — the circular-import "
        "regression is back (it is dropped when imported mid-bridge-init)."
    )


def test_load_family_solvers_is_idempotent():
    """Re-loading restores the SAME declared order in place (no duplication / loss)."""
    before = [m.__name__ for m in B._FAMILY_SOLVERS]
    B._load_family_solvers()
    after = [m.__name__ for m in B._FAMILY_SOLVERS]
    assert before == after == list(B._FAMILY_SOLVER_NAMES)


# --------------------------------------------------------------------------- #
# (b) the GP table_lut record now ROUTES through the bridge.
# --------------------------------------------------------------------------- #
def test_table_lut_gp_record_routes_via_bridge():
    """POSITIVE: the GP truth-table record fires `cvdp_table_lut_synth` standalone AND
    routes through `bridge.solve` (the exact bug: standalone RTL, bridge None)."""
    recs = _load_dataset()
    by_id = {r["id"]: r for r in recs}
    if _GP_ID not in by_id:
        pytest.skip("GP target record not in dataset")
    rec = by_id[_GP_ID]

    import cvdp_table_lut_synth as T
    standalone = T.solve(copy.deepcopy(rec))
    assert standalone, "precondition: table_lut must fire standalone on the GP record"

    bridged = B.solve(copy.deepcopy(rec))
    assert bridged, "ROUTING BUG: table_lut fires standalone but bridge returns None"
    # module must be named per the harness TOPLEVEL (GP).
    assert B.toplevel_name(rec) == "GP"
    assert "module GP" in bridged


# --------------------------------------------------------------------------- #
# (c) the per-iteration deep-copy ISOLATES a hostile mutating solver.
# --------------------------------------------------------------------------- #
def test_dispatch_deepcopy_isolates_a_mutating_solver():
    """A solver that mutates `record['input']['prompt']` then declines must NOT corrupt
    a later solver nor the caller's record — the bridge deep-copies per iteration."""
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

    saved = list(B._FAMILY_SOLVERS)
    before = json.dumps(rec, sort_keys=True)
    try:
        B._FAMILY_SOLVERS.insert(0, _Hostile)
        bridged = B.solve(rec)  # pass the REAL record (no external copy)
    finally:
        B._FAMILY_SOLVERS[:] = saved
    after = json.dumps(rec, sort_keys=True)

    assert bridged, "hostile front solver corrupted a later solver — deep-copy failed"
    assert before == after, "bridge.solve mutated the caller's record (deep-copy failed)"


def test_bridge_never_mutates_the_caller_record_over_dataset():
    """Over the WHOLE dataset, `bridge.solve(record)` must not mutate the record it is
    handed (the bridge passes records to many solvers; none may leak a mutation out)."""
    recs = _load_dataset()
    mutated = []
    for r in recs:
        before = json.dumps(r, sort_keys=True)
        B.solve(r)
        if json.dumps(r, sort_keys=True) != before:
            mutated.append(r.get("id"))
    assert not mutated, f"bridge.solve mutated these records: {mutated}"


# --------------------------------------------------------------------------- #
# (d) FULL-DATASET standalone==bridge consistency — 0 routing bugs for ALL solvers.
# --------------------------------------------------------------------------- #
def test_standalone_fires_implies_bridge_solves_for_every_solver():
    """THE CORE INVARIANT. For each of the declared family solvers, count records where
    the solver FIRES standalone but the bridge returns None. That count MUST be 0 — a
    nonzero count is a routing bug (the solver is unreachable through the bridge)."""
    recs = _load_dataset()
    solvers = {m.__name__: m for m in B._FAMILY_SOLVERS}
    # bridge verdict per record (cached).
    bridge_hit = {r["id"]: bool(B.solve(copy.deepcopy(r))) for r in recs}

    routing_bugs = {}
    for name in B._FAMILY_SOLVER_NAMES:
        S = solvers[name]
        bug_ids = []
        for r in recs:
            try:
                fired = bool(S.solve(copy.deepcopy(r)))
            except Exception:
                fired = False
            if fired and not bridge_hit[r["id"]]:
                bug_ids.append(r["id"])
        if bug_ids:
            routing_bugs[name] = bug_ids

    assert not routing_bugs, (
        "standalone-fires-but-bridge-None routing bug(s) detected:\n"
        + "\n".join(f"  {k}: {v}" for k, v in routing_bugs.items())
    )


def test_bridge_solved_count_at_or_above_floor():
    """The bridge must program-solve at least the known floor (29 after the table_lut
    GP routing fix; was 28 before). Guards against a silent dispatch regression that
    drops solved records."""
    recs = _load_dataset()
    solved = [r["id"] for r in recs if B.solve(copy.deepcopy(r))]
    assert len(solved) >= 29, (
        f"bridge-solved count regressed to {len(solved)} (floor 29). solved={solved}"
    )
    assert _GP_ID in solved, "the GP table_lut record is no longer solved by the bridge"

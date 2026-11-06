#!/usr/bin/env python3
"""Design-for-ECO readiness as a FEASIBILITY AXIS: the four arms and the
mutations.

THE DEFECT, MEASURED AND NOT HYPOTHESISED
=========================================
A published cross-layer place-and-route search over one design produced these
five arms (`area.design_report.um2` at `post_route`, spare population from each
arm's own `spare_cells.json`):

    shipped default              6594 um2   10 spares
    PnR-only winner              6136 um2    0 spares   <- all ten deleted
    cross-layer objective        5941 um2    0 spares
    cross-layer Pareto           6011 um2    0 spares
    cross-layer ECO-preserving   6106 um2   10 spares   <- all ten kept

The three winners bought part of their margin by deleting the design's whole
spare/ECO population -- the cells that make a bug found after tape-out fixable
by a metal-only ECO instead of a base-layer respin. The ECO-preserving arm gave
that margin back and was STILL ahead of the published PnR-only winner on both
area and power. The search had already found the right answer; nothing in the
verdict machinery stopped it publishing the wrong ones beside it, because the
spare count was a column in the record and not an axis over it.

Every test below is named after the thing that would go wrong without it.

ARMS
    POSITIVE          a declared requirement that IS met -> FEASIBLE
    NEGATIVE          a declared requirement that is NOT met -> INFEASIBLE
    VACUOUS           no evidence, or no declaration -> never a silent pass
    BAD INVOCATION    rc=3, distinct from rc=2
    MUTATION          each one RED: a gate that lost the rule fails here
"""
import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402

SPACE = _PROGRAMS / "ppa_pnr_search_space.py"

DIGEST = "sha256:" + "0" * 64
VIEW = {"stage": "post_route"}

#: What a tape-out-bound design declares. It lives in the TEST because it is a
#: statement about a design; nothing in the gate may contain these numbers.
DECL = {
    "required": True,
    "min_spare_cells": 10,
    "min_spare_cells_by_kind": {"inverter": 3, "nand2": 2, "nor2": 2,
                                "mux2": 1, "aoi": 1, "dff": 1},
    "min_distinct_positions": 3,
    "require_tie_off": True,
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------






def cand(cid, metrics, waivers=None):
    d = {"candidate_id": cid, "metrics": metrics}
    if waivers is not None:
        d["waivers"] = waivers
    return d


def policy(declaration=DECL, views=(VIEW,)):
    doc = {"required_views": [dict(v) for v in views]}
    if declaration is not None:
        doc["eco_readiness"] = declaration
    return F.policy_from_document(doc)


def axis_of(result, name=F.ECO_AXIS):
    return [a for a in result.axes if a.name == name][0]


PLAN_TEN = {
    "count": 10, "density": 0.02,
    "types": {"inverter": 3, "nand2": 2, "nor2": 2, "mux2": 1, "aoi": 1,
              "dff": 1},
    "tied_off": True,
    "instances": (
        [{"name": f"spare_inverter_{i}", "type": "inverter",
          "llx": 13 + 16 * i, "lly": 13} for i in range(3)]
        + [{"name": "spare_nand2_0", "type": "nand2", "llx": 61, "lly": 13},
           {"name": "spare_nand2_1", "type": "nand2", "llx": 13, "lly": 34},
           {"name": "spare_nor2_0", "type": "nor2", "llx": 29, "lly": 34},
           {"name": "spare_nor2_1", "type": "nor2", "llx": 45, "lly": 34},
           {"name": "spare_mux2_0", "type": "mux2", "llx": 61, "lly": 34},
           {"name": "spare_aoi_0", "type": "aoi", "llx": 13, "lly": 56},
           {"name": "spare_dff_0", "type": "dff", "llx": 29, "lly": 56}]),
    "spare_pads": [],
    "cell_map": {"inverter": "x", "nand2": "x", "nor2": "x", "mux2": "x",
                 "aoi": "x", "oai": "x", "dff": "x"},
    "tie_off": {"measured": True, "connected": 20, "candidates": 20,
                "tied_off": True, "reason": "measured 20/20"},
}
PLAN_NONE = {
    "count": 0, "density": 0.0, "types": {}, "tied_off": False,
    "instances": [], "spare_pads": [],
    "cell_map": dict(PLAN_TEN["cell_map"]),
    "tie_off": {"measured": False, "connected": None, "candidates": None,
                "tied_off": False,
                "reason": "no SPARE_TIEOFF_CONNECTED count in the PnR log"},
}


# ---------------------------------------------------------------------------
# POSITIVE
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# NEGATIVE
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# VACUOUS -- the arm that matters most
# ---------------------------------------------------------------------------






def test_vacuous_producer_on_a_missing_plan_emits_no_zero(tmp_path):
    out = tmp_path / "eco.json"
    doc = json.loads(out.read_text(encoding="utf-8"))
    for row in doc["records"]:
        assert row["status"] != "MEASURED", row
        assert "value" not in row, row




# ---------------------------------------------------------------------------
# BAD INVOCATION -- 3, and never 2
# ---------------------------------------------------------------------------




def test_bad_invocation_space_unknown_flag_is_3_not_2():
    r = subprocess.run([sys.executable, str(SPACE),
                        "--this-flag-does-not-exist"],
                       capture_output=True, text=True)
    assert r.returncode == 3


# ---------------------------------------------------------------------------
# MUTATIONS -- each must be RED
# ---------------------------------------------------------------------------














def test_M_ECO_8_a_named_declaration_that_cannot_be_read_blocks_the_space(
        tmp_path):
    """A requirement that was NAMED and could not be read must not become
    "no requirement". That is the failure that would publish an unbounded
    space from a document that forbids the very value."""
    bad = tmp_path / "eco.json"
    bad.write_text("{not json", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SPACE), "--json",
                        str(tmp_path / "space.json"),
                        "--eco-declaration", str(bad)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert not (tmp_path / "space.json").exists()




# ---------------------------------------------------------------------------
# the chip-AGNOSTIC guard, MEASURED over the source
# ---------------------------------------------------------------------------
def test_no_spare_count_or_density_is_hard_coded_in_the_gate():
    """Rule 1, enforced against the file rather than asserted in its docstring.

    `_ppa/feasibility.py` decides whether a spare population is sufficient. If
    it contained a number of its own -- ten spares, two percent -- that number
    would be a design decision living in chip-agnostic source, and a design
    that needed twelve would silently be graded against ten.

    The measurement is over the module's own AST: every numeric literal in the
    ECO section, and the allowed set is {0, 1}. 0 is the boundary a count is
    compared against for non-negativity; 1 is the floor a preservation
    obligation inherits when no explicit count was declared, and it is not a
    spare count -- it is "at least one, since you asked for preservation at
    all".
    """
    import ast
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    eco_names = {"eco_requirement_state", "eco_proofs_and_limits",
                 "_evaluate_eco_axis", "_eco_not_proved", "_pos_int",
                 "eco_metric_for_kind"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in eco_names:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(
                        sub.value, (int, float)) and not isinstance(
                            sub.value, bool):
                    found.add(sub.value)
    assert found <= {0, 1}, (
        f"the ECO section of the gate carries the literal(s) {sorted(found)}. "
        "A spare count or density here is a design decision in chip-agnostic "
        "source; every floor must come from the design's declaration.")


def test_the_gate_names_no_pdk_cell_and_the_producer_names_no_requirement():
    """Two halves of the same discipline, in the two files that could break it.

    The gate must name no standard cell (a cell name is a PDK, and a PDK is a
    design decision); the producer must name no requirement (a producer that
    knew the floor would be grading its own homework).
    """
    gate = pathlib.Path(F.__file__).read_text(encoding="utf-8").lower()
    for token in ("sky130", "gf180", "__inv_", "__nand2_", "__dfrtp"):
        assert token not in gate, token


# ---------------------------------------------------------------------------
# SURVIVAL -- the obligation that actually bears on a post-tape-out repair
# ---------------------------------------------------------------------------
#: The insertion count says what the placer put down. Every pass after it (CTS,
#: hold fixing, routing, ECO, metal fill) could have stripped a spare, and a
#: count of what was inserted cannot see that. `require_preservation` is the
#: declaration asking the SHIPPED artefacts instead.
DECL_PRESERVED = dict(DECL, require_preservation=True)












def test_an_obligation_with_no_proof_does_not_become_a_vacuous_pass():
    """The worst available failure mode, guarded before it can exist.

    The ECO axis's proof set is BUILT from the declaration, and a group with no
    proofs in it is SATISFIED vacuously. So an obligation added to
    `ECO_OBLIGATIONS` without a matching proof would turn this axis into an
    automatic pass for every design that declares it -- silently, and in the
    one direction nobody would notice. The guard is exercised here directly
    because no declaration can reach it today.
    """
    pol = F.FeasibilityPolicy(required_views=(VIEW,), eco_requirement=DECL)
    saved = F.eco_proofs_and_limits
    try:
        # a build in which every declared obligation has lost its proof
        F.eco_proofs_and_limits = lambda decl: ((), {}, [])
        a = F._evaluate_eco_axis([], pol)
    finally:
        F.eco_proofs_and_limits = saved
    assert a.status == F.AXIS_UNDETERMINED
    assert a.codes == (F.C_ECO_REQUIREMENT_EMPTY,)


# ---------------------------------------------------------------------------
# WIRED -- the axis proves from the flow's OWN artefacts, not only from a fixture
# ---------------------------------------------------------------------------
#: An axis nothing produces evidence for is an axis that reads UNDETERMINED on
#: every real run however good the design is. That was the state the other seven
#: physical axes were in before `ppa_signoff_records.py`, and it was the state
#: `eco_readiness` arrived in. These tests are the statement that it is not any
#: more, and they drive the SHIPPED bundle rather than a hand-built record list.


def _run_tree(root, plan=PLAN_TEN, preservation=None):
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    if plan is not None:
        (pnr / "spare_cells.json").write_text(json.dumps(plan),
                                              encoding="utf-8")
    if preservation is not None:
        rep = root / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "spare_preservation.json").write_text(
            json.dumps(preservation), encoding="utf-8")
    return root

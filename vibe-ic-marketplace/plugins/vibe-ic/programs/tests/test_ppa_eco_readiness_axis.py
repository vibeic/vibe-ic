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
import ppa_eco_spare_records as P  # noqa: E402

CHECK = _PROGRAMS / "ppa_feasibility_check.py"
PRODUCER = _PROGRAMS / "ppa_eco_spare_records.py"
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
def rec(metric, value, unit="count", status="MEASURED", scope=None,
        reason=None):
    r = {"schema": F.METRIC_SCHEMA, "metric": metric, "status": status,
         "scope": dict(scope or VIEW),
         "source": {"path": "phase3/stage3/pnr/spare_cells.json",
                    "sha256": DIGEST, "tool": "phase3_one_shot_runner",
                    "parser": "ppa_eco_spare_records.py"}}
    if status == "MEASURED":
        r["value"] = value
        r["unit"] = unit
    else:
        r["reason"] = reason or "the artefact does not state it"
    return r


def clean_nine(scope=None):
    """Every axis but `eco_readiness`, satisfied. The point of this fixture is
    that ECO readiness is the ONLY thing that can be wrong below."""
    s = dict(scope or VIEW)
    return [
        rec("timing.setup.wns_ns", 0.05, "ns", scope=s),
        rec("timing.hold.wns_ns", 0.01, "ns", scope=s),
        rec("timing.drv.violations", 0, scope=s),
        rec("physical.drc.violations", 0, scope=s),
        rec("physical.lvs.verdict", "CLEAN", "verdict", scope=s),
        rec("physical.antenna.violations", 0, scope=s),
        rec("power.ir.violations", 0, scope=s),
        rec("reliability.em.violations", 0, scope=s),
        rec("equivalence.verdict", "PROVEN", "verdict", scope=s),
    ]


def spares(count=10, by_kind=None, positions=10, tied="TIED_OFF"):
    """The ECO records a run with `count` spares would produce."""
    by_kind = by_kind if by_kind is not None else dict(
        DECL["min_spare_cells_by_kind"])
    out = [rec(F.ECO_M_COUNT, count),
           rec(F.ECO_M_POSITIONS, positions)]
    for kind, n in sorted(by_kind.items()):
        out.append(rec(F.eco_metric_for_kind(kind), n))
    if tied is not None:
        out.append(rec(F.ECO_M_TIE_OFF, tied, "verdict"))
    return out


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


def run_cli(tmp_path, doc, *extra):
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "feas.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p),
                        "--json", str(out), *extra],
                       capture_output=True, text=True)
    payload = json.loads(out.read_text(encoding="utf-8")) if out.exists() \
        else None
    return r, payload


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
def test_positive_a_declared_requirement_that_is_met_is_feasible():
    r = F.promotion_verdict(cand("keeps", clean_nine() + spares()), policy())
    assert r.verdict == F.FEASIBLE, r.codes
    a = axis_of(r)
    assert a.status == F.AXIS_SATISFIED
    assert a.applicability["state"] == F.ECO_REQUIRED


def test_positive_the_row_states_what_it_did_not_prove():
    """Rule 3. An axis that proved a count must not read as having proved ECO
    readiness. Three properties no artefact of this flow can answer are named
    unconditionally, and every declared obligation that was NOT asked for is
    named too."""
    r = F.promotion_verdict(cand("keeps", clean_nine() + spares()), policy())
    named = {row.get("property") or row.get("obligation")
             for row in axis_of(r).applicability["not_proved"]}
    assert {"eco_reachability", "kind_sufficiency", "post_eco_timing"} <= named
    # this declaration asks for no pad count and no preservation proof, and
    # the row says so rather than letting a reader assume they were checked
    assert {"min_spare_pads", "require_preservation"} <= named


def test_positive_a_design_that_declares_none_is_not_thereby_failing():
    r = F.promotion_verdict(cand("no-eco", clean_nine()),
                            policy({"required": False}))
    assert r.verdict == F.FEASIBLE
    a = axis_of(r)
    assert a.status == F.AXIS_NOT_APPLICABLE
    assert a.applicability["state"] == F.ECO_NOT_REQUIRED
    assert a.codes == (F.C_ECO_NOT_REQUIRED,)


def test_positive_the_two_ways_of_declaring_none_do_not_share_a_code():
    """Rule 1. "nobody stated a requirement" and "somebody stated there is
    none" are different facts about a design. A single NOT_APPLICABLE for both
    hides which one a reader is looking at, and only one of them is a decision
    somebody made."""
    silent = axis_of(F.promotion_verdict(cand("s", clean_nine()),
                                         policy(None)))
    stated = axis_of(F.promotion_verdict(cand("d", clean_nine()),
                                         policy({"required": False})))
    assert silent.status == stated.status == F.AXIS_NOT_APPLICABLE
    assert silent.codes != stated.codes
    assert silent.applicability["state"] == F.ECO_NOT_DECLARED
    assert stated.applicability["state"] == F.ECO_NOT_REQUIRED
    assert silent.applicability["declaration_present"] is False
    assert stated.applicability["declaration_present"] is True


# ---------------------------------------------------------------------------
# NEGATIVE
# ---------------------------------------------------------------------------
def test_negative_a_deleted_spare_population_is_infeasible():
    r = F.promotion_verdict(
        cand("deleted", clean_nine() + spares(
            count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
            positions=0, tied=None)),
        policy())
    assert r.verdict == F.INFEASIBLE, r.codes
    assert not r.eligible_for_promotion
    assert axis_of(r).status == F.AXIS_VIOLATED
    # and every other axis is still clean: the refusal is about the spares
    assert all(a.status == F.AXIS_SATISFIED for a in r.axes
               if a.name != F.ECO_AXIS)


def test_negative_the_right_kind_matters_not_only_the_count():
    """Rule 3. Ten spares that are all inverters cannot repair a bug that
    needs a flop, so a population that clears the total and misses a declared
    kind is refused."""
    wrong = {"inverter": 10, "nand2": 0, "nor2": 0, "mux2": 0, "aoi": 0,
             "dff": 0}
    r = F.promotion_verdict(
        cand("wrong-kinds", clean_nine() + spares(count=10, by_kind=wrong)),
        policy())
    assert r.verdict == F.INFEASIBLE
    assert axis_of(r).status == F.AXIS_VIOLATED


def test_negative_spares_with_floating_inputs_are_refused():
    r = F.promotion_verdict(
        cand("floating", clean_nine() + spares(tied="NOT_TIED_OFF")), policy())
    assert r.verdict == F.INFEASIBLE
    assert axis_of(r).status == F.AXIS_VIOLATED


def test_negative_via_the_cli_is_rc1_and_names_the_axis(tmp_path):
    r, doc = run_cli(tmp_path, {
        "required_views": [VIEW], "eco_readiness": DECL,
        "candidates": [cand("deleted", clean_nine() + spares(
            count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
            positions=0, tied=None))]})
    assert r.returncode == F.RC_FAIL, r.stdout + r.stderr
    axes = {a["axis"]: a["status"] for a in doc["candidates"][0]["axes"]}
    assert axes["eco_readiness"] == "VIOLATED"
    assert "eco_readiness: REQUIRED" in r.stdout


# ---------------------------------------------------------------------------
# VACUOUS -- the arm that matters most
# ---------------------------------------------------------------------------
def test_vacuous_no_spare_evidence_is_undetermined_not_zero_and_not_pass():
    """Rule 2, in both directions at once. A candidate with NO spare records
    at all must not be read as having zero spares (which would convict a run
    nobody looked at) and must not be read as passing (which is the empty-tree
    lie)."""
    r = F.promotion_verdict(cand("silent", clean_nine()), policy())
    assert r.verdict == F.UNDETERMINED, r.codes
    assert not r.eligible_for_promotion
    a = axis_of(r)
    assert a.status == F.AXIS_UNDETERMINED
    assert F.C_METRIC_ABSENT in a.codes


def test_vacuous_a_not_measured_spare_count_is_undetermined(tmp_path):
    ms = clean_nine() + [
        rec(F.ECO_M_COUNT, None, status="NOT_MEASURED",
            reason="the spare plan could not be read")]
    r, doc = run_cli(tmp_path, {"required_views": [VIEW],
                                "eco_readiness": DECL,
                                "candidates": [cand("unread", ms)]})
    assert r.returncode == F.RC_UNDETERMINED
    axes = {a["axis"]: a["status"] for a in doc["candidates"][0]["axes"]}
    assert axes["eco_readiness"] == "UNDETERMINED"


def test_vacuous_a_declaration_that_requires_nothing_is_refused_not_passed():
    """`required: true` with no floor, no kind and no other obligation asserts
    that this design needs ECO readiness and then says nothing checkable. A
    requirement with nothing to check is not a satisfied one."""
    r = F.promotion_verdict(cand("empty-decl", clean_nine() + spares()),
                            policy({"required": True}))
    assert r.verdict == F.UNDETERMINED
    a = axis_of(r)
    assert a.status == F.AXIS_UNDETERMINED
    assert a.applicability["state"] == F.ECO_UNREADABLE
    assert a.codes == (F.C_ECO_REQUIREMENT_EMPTY,)


def test_vacuous_a_declaration_that_is_not_an_object_is_refused():
    for junk in ("yes", 10, ["required"]):
        r = F.promotion_verdict(cand("junk", clean_nine() + spares()),
                                policy(junk))
        assert r.verdict == F.UNDETERMINED, junk
        assert axis_of(r).codes == (F.C_ECO_DECLARATION_UNREADABLE,), junk


def test_vacuous_producer_on_a_missing_plan_emits_no_zero(tmp_path):
    out = tmp_path / "eco.json"
    r = subprocess.run([sys.executable, str(PRODUCER),
                        "--spare-plan", str(tmp_path / "nope.json"),
                        "--stage", "post_route", "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == P.RC_UNDETERMINED, r.stdout + r.stderr
    assert P.MARK_CANNOT in r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    for row in doc["records"]:
        assert row["status"] != "MEASURED", row
        assert "value" not in row, row


def test_vacuous_the_unreadable_plan_makes_the_gate_undetermined(tmp_path):
    """End to end: the producer's honest absence must survive into the
    verdict. This is the join the two halves are separately correct about and
    could still get wrong between them."""
    out = tmp_path / "eco.json"
    subprocess.run([sys.executable, str(PRODUCER), "--spare-plan",
                    str(tmp_path / "nope.json"), "--stage", "post_route",
                    "--json", str(out)], capture_output=True, text=True)
    recs = json.loads(out.read_text(encoding="utf-8"))["records"]
    r = F.promotion_verdict(cand("unread", clean_nine() + recs), policy())
    assert r.verdict == F.UNDETERMINED
    assert axis_of(r).status == F.AXIS_UNDETERMINED


# ---------------------------------------------------------------------------
# BAD INVOCATION -- 3, and never 2
# ---------------------------------------------------------------------------
def test_bad_invocation_producer_unknown_flag_is_3_not_2():
    r = subprocess.run([sys.executable, str(PRODUCER), "--spare-plan", "x",
                        "--stage", "s", "--this-flag-does-not-exist"],
                       capture_output=True, text=True)
    assert r.returncode == P.RC_BAD_INVOCATION


def test_bad_invocation_producer_help_is_0_not_3():
    r = subprocess.run([sys.executable, str(PRODUCER), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_bad_invocation_space_unknown_flag_is_3_not_2():
    r = subprocess.run([sys.executable, str(SPACE),
                        "--this-flag-does-not-exist"],
                       capture_output=True, text=True)
    assert r.returncode == 3


# ---------------------------------------------------------------------------
# MUTATIONS -- each must be RED
# ---------------------------------------------------------------------------
def test_M_ECO_1_a_better_number_everywhere_does_not_buy_the_deletion():
    """THE MEASURED DEFECT. The candidate is better on every axis a PPA report
    prints and it has no spare population. It is not a cheaper candidate; it
    is one that cannot be repaired without a new mask set."""
    ms = clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied=None)
    for m in ms:                       # every timing number, dramatically better
        if m["metric"].startswith("timing.") and m["status"] == "MEASURED":
            m["value"] = 9.9
    r = F.promotion_verdict(cand("winner", ms), policy())
    assert r.verdict == F.INFEASIBLE
    assert not r.eligible_for_promotion


def test_M_ECO_2_absent_and_zero_do_not_produce_the_same_verdict():
    """The bidirectional pair. If these two ever agree, one of them is wrong:
    a run nobody measured is being convicted, or a real deletion is being
    excused."""
    absent = F.promotion_verdict(cand("absent", clean_nine()), policy())
    zero = F.promotion_verdict(
        cand("zero", clean_nine() + spares(
            count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
            positions=0, tied=None)), policy())
    assert absent.verdict == F.UNDETERMINED
    assert zero.verdict == F.INFEASIBLE
    assert absent.verdict != zero.verdict


def test_M_ECO_3_an_unowned_waiver_does_not_rescue_the_deletion():
    ms = clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied=None)
    r = F.promotion_verdict(
        cand("waived", ms, waivers=[{"waiver_id": "w1",
                                     "axis": F.ECO_AXIS,
                                     "justification": "we need the area"}]),
        policy())
    assert r.verdict == F.INFEASIBLE
    assert axis_of(r).status == F.AXIS_VIOLATED


def test_M_ECO_4_a_waiver_may_not_be_applied_to_an_unmeasured_population():
    """A waiver is one named owner accepting a KNOWN violation. Applying one
    to an axis nobody could measure converts an unknown into a pass."""
    r = F.promotion_verdict(
        cand("waive-the-unknown", clean_nine(),
             waivers=[{"waiver_id": "w2", "axis": F.ECO_AXIS,
                       "owner": "someone", "justification": "trust me"}]),
        policy())
    assert r.verdict == F.UNDETERMINED
    assert axis_of(r).status == F.AXIS_UNDETERMINED
    codes = [w.get("code") for w in r.waivers]
    assert F.C_WAIVER_ON_UNMEASURED in codes


def test_M_ECO_5_a_plan_that_contradicts_itself_is_invalid_not_believed():
    """A plan claiming ten spares while listing none must not have the
    flattering field believed. Somebody looked and the artefact cannot answer:
    that is INVALID, and INVALID is UNDETERMINED at the gate."""
    bad = dict(PLAN_TEN, instances=[])
    src = {"path": "phase3/stage3/pnr/spare_cells.json", "sha256": DIGEST,
           "tool": "phase3_one_shot_runner",
           "parser": "ppa_eco_spare_records.py"}
    recs = P.records_from_plan(bad, VIEW, src, None)
    count = [r for r in recs if r["metric"] == F.ECO_M_COUNT][0]
    assert count["status"] == "INVALID"
    r = F.promotion_verdict(cand("contradicts", clean_nine() + recs), policy())
    assert r.verdict == F.UNDETERMINED
    assert axis_of(r).status == F.AXIS_UNDETERMINED


def test_M_ECO_6_the_declaration_is_what_refuses_not_the_gate_itself():
    """THE NEGATIVE CONTROL, and it is the one that makes the rest mean
    something. The SAME candidate with no declaration is not refused. So the
    refusal above comes from the design's stated requirement and not from a
    rule that would fire on every design regardless -- which would be a gate
    nobody could ever satisfy, and equally useless."""
    ms = clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied=None)
    required = F.promotion_verdict(cand("c", ms), policy())
    undeclared = F.promotion_verdict(cand("c", ms), policy(None))
    assert required.verdict == F.INFEASIBLE
    assert undeclared.verdict == F.FEASIBLE
    assert axis_of(undeclared).status == F.AXIS_NOT_APPLICABLE


def test_M_ECO_7_the_search_space_refuses_the_value_that_deletes_them(tmp_path):
    """The stronger half of the fix: stop the candidate being GENERATED. With
    a declared requirement, `--values spare_cell_density=0` is refused before
    a place-and-route run is spent producing something the gate must reject."""
    decl = tmp_path / "eco.json"
    decl.write_text(json.dumps({"eco_readiness": DECL}), encoding="utf-8")
    args = [sys.executable, str(SPACE), "--json", str(tmp_path / "space.json"),
            "--values", "spare_cell_density=0.00,0.02"]
    without = subprocess.run(args, capture_output=True, text=True,
                             cwd=str(tmp_path))
    withd = subprocess.run(args + ["--eco-declaration", str(decl)],
                           capture_output=True, text=True, cwd=str(tmp_path))
    assert without.returncode == 0, without.stderr      # negative control
    assert withd.returncode == 1, withd.stdout + withd.stderr
    assert "metal-only ECO" in withd.stderr


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


def test_M_ECO_9_a_zero_the_runner_produces_by_clamping_is_still_refused(
        tmp_path):
    """The check runs on what the runner would APPLY, not on how the caller
    spelled it. `-1` is clamped to 0 by the runner's own guard, and a rule
    that looked at the literal would have let it through."""
    decl = tmp_path / "eco.json"
    decl.write_text(json.dumps({"eco_readiness": DECL}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SPACE), "--json",
                        str(tmp_path / "space.json"),
                        "--eco-declaration", str(decl),
                        "--values", "spare_cell_density=-1"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr


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
    prod = pathlib.Path(P.__file__).read_text(encoding="utf-8").lower()
    for token in ("min_spare_cells", "required_kinds", "target_density",
                  "0.02"):
        assert token not in prod, (
            f"{token!r} appears in the producer. Whether a population is "
            "sufficient is the declaration's question and the gate's "
            "comparison, never the producer's.")


# ---------------------------------------------------------------------------
# SURVIVAL -- the obligation that actually bears on a post-tape-out repair
# ---------------------------------------------------------------------------
#: The insertion count says what the placer put down. Every pass after it (CTS,
#: hold fixing, routing, ECO, metal fill) could have stripped a spare, and a
#: count of what was inserted cannot see that. `require_preservation` is the
#: declaration asking the SHIPPED artefacts instead.
DECL_PRESERVED = dict(DECL, require_preservation=True)


def test_preservation_a_shipped_population_that_survived_is_satisfied():
    ms = clean_nine() + spares() + [rec(F.ECO_M_SURVIVING, 10)]
    r = F.promotion_verdict(cand("survived", ms), policy(DECL_PRESERVED))
    assert r.verdict == F.FEASIBLE, r.codes
    assert axis_of(r).status == F.AXIS_SATISFIED


def test_preservation_spares_inserted_and_then_stripped_are_refused():
    """The failure the insertion count cannot see. Ten spares were placed and
    nine reached the shipped netlist: the design has nine, whatever the plan
    said it inserted, and nine is below the declared floor of ten."""
    ms = clean_nine() + spares() + [rec(F.ECO_M_SURVIVING, 9)]
    r = F.promotion_verdict(cand("stripped", ms), policy(DECL_PRESERVED))
    assert r.verdict == F.INFEASIBLE
    assert axis_of(r).status == F.AXIS_VIOLATED
    # the INSERTION count still reads ten and is still satisfied; the refusal
    # comes from the shipped artefacts and not from a re-reading of the plan
    ev = {e["metric"]: e.get("value") for e in axis_of(r).detail
          if "value" in e}
    assert ev[F.ECO_M_COUNT] == 10
    assert ev[F.ECO_M_SURVIVING] == 9


def test_preservation_required_but_never_measured_is_undetermined():
    """A declaration that asks for survival and a run with no preservation
    report is UNDETERMINED. It is NOT satisfied by the insertion count -- that
    substitution is the entire reason survival is a separate obligation."""
    ms = clean_nine() + spares() + [
        rec(F.ECO_M_SURVIVING, None, status="NOT_MEASURED",
            reason="no spare-preservation report was supplied")]
    r = F.promotion_verdict(cand("unproven", ms), policy(DECL_PRESERVED))
    assert r.verdict == F.UNDETERMINED
    assert axis_of(r).status == F.AXIS_UNDETERMINED


def test_preservation_is_not_proved_when_the_declaration_does_not_ask():
    """And the same records under the declaration that does NOT ask for
    survival are SATISFIED, with the omission stated by name. Only what the
    declaration asks for is proved; what it did not ask for is disclosed."""
    ms = clean_nine() + spares() + [
        rec(F.ECO_M_SURVIVING, None, status="NOT_MEASURED",
            reason="no spare-preservation report was supplied")]
    r = F.promotion_verdict(cand("not-asked", ms), policy())
    assert r.verdict == F.FEASIBLE
    a = axis_of(r)
    assert a.status == F.AXIS_SATISFIED
    assert "require_preservation" in {row.get("obligation")
                                      for row in a.applicability["not_proved"]}


def test_preservation_a_no_witness_report_does_not_vouch_for_anything():
    """`spare_cell_preservation_check` says NO_WITNESS when it could read no
    name-bearing final artefact. Nothing vouched for any spare, so the producer
    must emit an absence and not the report's `survived` number."""
    src = {"path": "reports/spare_preservation.json", "sha256": DIGEST,
           "tool": "phase3_one_shot_runner",
           "parser": "ppa_eco_spare_records.py"}
    row = P.survival_record(
        {"inserted": 10, "survived": 10,
         "artefact_agreement": {"status": "NO_WITNESS"}}, VIEW, src, None)
    assert row["status"] == "NOT_MEASURED"
    assert "value" not in row
    r = F.promotion_verdict(cand("no-witness", clean_nine() + spares() + [row]),
                            policy(DECL_PRESERVED))
    assert r.verdict == F.UNDETERMINED

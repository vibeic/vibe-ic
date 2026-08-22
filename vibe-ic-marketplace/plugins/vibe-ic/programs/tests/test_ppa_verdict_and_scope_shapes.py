#!/usr/bin/env python3
"""A verdict is not a count, and a null scope field is not a scope field.

F-18: `derive_feasibility` required an integer `violations` on every floor
check, so an arm valid against `comparison.v2` declaring `status: CLEAN`
everywhere derived as NOT_CHECKED -- and LVS, which produces a verdict about a
named circuit and not a population, could only be expressed by writing
`violations: 0` about it.

The same type error existed one layer down: `_ppa/metrics.validate` required a
numeric value, so `physical.lvs.verdict` and `equivalence.verdict` -- two of the
nine axes `_ppa/feasibility.py` proves -- could not be expressed in the
canonical record shape the gate reads at all.

F-8: the power record now carries the PVT its own liberty file names. The half
of that fix that matters is what it must NOT do: put `process: None` into scope
and let two arms that know nothing about their corner compare as the same corner.
"""
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import benchmark as B   # noqa: E402
from _ppa import metrics as M     # noqa: E402
from _ppa import power as P       # noqa: E402

FLOOR = list(B.FEASIBILITY_FLOOR)


def arm(checks, flow="ours"):
    return {"flow": flow, "feasibility": {"checks": checks}}


# ==========================================================================
# F-18 -- the check shape
# ==========================================================================
def test_status_clean_everywhere_derives_feasible():
    """THE DEFECT. `comparison.v2` documents `status` as a first-class
    alternative to `violations`; this function ignored it, so a record valid
    against the shipped schema derived as NOT_CHECKED and the arm was refused."""
    v, d = B.derive_feasibility(arm({k: {"status": "CLEAN"} for k in FLOOR}))
    assert v == "FEASIBLE", d


def test_an_lvs_clean_arm_can_say_so_without_writing_a_count():
    checks = {k: {"violations": 0} for k in FLOOR if k != "lvs"}
    checks["lvs"] = {"verdict": "MATCH", "top_cell": "core"}
    assert B.derive_feasibility(arm(checks))[0] == "FEASIBLE"


def test_an_lvs_mismatch_is_infeasible_and_not_merely_unchecked():
    checks = {k: {"violations": 0} for k in FLOOR if k != "lvs"}
    checks["lvs"] = {"verdict": "MISMATCH"}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "INFEASIBLE" and "lvs" in d["violating"]


def test_the_accept_set_is_the_one_the_feasibility_axis_declares():
    """One statement in this repository of what an LVS pass looks like."""
    from _ppa import feasibility as F
    for name, accepted in B.VERDICT_CLEAN.items():
        axis = next(a for a in F.DEFAULT_AXES if a.name == name)
        declared = set()
        for group in axis.groups:
            for proof in group:
                if proof.kind == F.KIND_VERDICT_IN:
                    declared |= {a.upper() for a in proof.accept}
        assert {a.upper() for a in accepted} == declared, name


def test_a_verdict_on_a_check_that_has_no_verdict_spelling_is_not_a_clean():
    """`drc: {"verdict": "looks fine"}` must not buy a pass off a free-text
    string this module has no accept set for."""
    checks = {k: {"violations": 0} for k in FLOOR if k != "drc"}
    checks["drc"] = {"verdict": "looks fine"}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "NOT_CHECKED" and "drc" in d["not_checked"]
    assert "no verdict spelling" in d["reasons"]["drc"]


def test_a_check_stating_nothing_at_all_is_not_checked():
    checks = {k: {"violations": 0} for k in FLOOR}
    checks["drv"] = {"source": "somewhere.rpt"}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "NOT_CHECKED" and "drv" in d["not_checked"]


def test_status_not_checked_outranks_a_leftover_count():
    """An explicit 'I did not check this' must not be resurrected by a count
    left over from an earlier run."""
    checks = {k: {"violations": 0} for k in FLOOR}
    checks["hold"] = {"status": "NOT_CHECKED", "violations": 0}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "NOT_CHECKED" and "hold" in d["not_checked"]


def test_a_self_contradicting_check_is_decided_by_the_measured_count():
    """`status: CLEAN` beside `violations: 3` is an assertion beside its own
    evidence, which is exactly where this module says a record has room to be
    dishonest cheaply. The count decides and the disagreement is named."""
    checks = {k: {"violations": 0} for k in FLOOR}
    checks["drc"] = {"status": "CLEAN", "violations": 3}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "INFEASIBLE"
    assert d["violating"]["drc"] == 3
    assert d["contradicting"] == ["drc"]


def test_a_verdict_contradicting_a_count_is_not_silently_reconciled():
    checks = {k: {"violations": 0} for k in FLOOR}
    checks["lvs"] = {"verdict": "MATCH", "violations": 5}
    v, d = B.derive_feasibility(arm(checks))
    assert v == "INFEASIBLE" and d["contradicting"] == ["lvs"]


def test_a_missing_floor_check_is_still_not_checked():
    """The floor is a floor. This change must not make an arm that was never
    asked about DRV look like one that was."""
    v, d = B.derive_feasibility(
        arm({k: {"status": "CLEAN"} for k in FLOOR if k != "drv"}))
    assert v == "NOT_CHECKED" and d["not_checked"] == ["drv"]


def test_a_count_shaped_arm_derives_exactly_as_it_did_before():
    """Every record written before this change must adjudicate identically."""
    assert B.derive_feasibility(
        arm({k: {"violations": 0} for k in FLOOR}))[0] == "FEASIBLE"
    assert B.derive_feasibility(
        arm({**{k: {"violations": 0} for k in FLOOR},
             "drc": {"violations": 2}}))[0] == "INFEASIBLE"
    assert B.derive_feasibility(arm({}))[0] == "NOT_CHECKED"
    assert B.derive_feasibility({"flow": "x"})[0] == "NOT_CHECKED"


def test_the_schema_documents_all_three_shapes():
    """The schema and the deriver disagreeing is what produced F-18."""
    import json
    schema = json.loads((_PROGRAMS.parent / "schemas" / "ppa" /
                         "comparison.v2.schema.json").read_text())
    check = schema["$defs"]["feasibility"]["properties"]["checks"][
        "additionalProperties"]
    assert set(check["properties"]) >= {"violations", "status", "verdict"}
    required = {tuple(x["required"])[0] for x in check["anyOf"]}
    assert required == {"violations", "status", "verdict"}


# ==========================================================================
# F-18, one layer down -- the canonical record shape
# ==========================================================================
def _verdict_record(value="MATCH", unit=None, metric="physical.lvs.verdict"):
    return {"schema": M.SCHEMA_ID, "metric": metric, "status": "MEASURED",
            "unit": M.VERDICT_UNIT if unit is None else unit,
            "value": value, "scope": {"stage": "post_route_extracted"},
            "source": {"path": "reports/phase3/lvs_verdict.json",
                       "sha256": "sha256:" + "0" * 64, "tool": "netgen"}}


def test_a_verdict_record_is_a_valid_canonical_record():
    """Before this, `validate` refused it VALUE_NOT_A_NUMBER -- so two of the
    nine axes the gate proves could not be expressed in the shape it reads."""
    assert M.validate(_verdict_record()) == []
    assert M.is_verdict_metric("physical.lvs.verdict")
    assert M.is_verdict_metric("equivalence.verdict")
    assert not M.is_verdict_metric("physical.drc.violations")


def test_a_verdict_encoded_as_a_number_is_refused():
    """'matched' as the integer 0 is a number downstream."""
    codes = [c for c, _ in M.validate(_verdict_record(value=0))]
    assert "VERDICT_NOT_A_STRING" in codes


def test_an_empty_verdict_is_refused():
    """Two empty strings compare EQUAL, so two circuits nobody compared would
    read as agreeing."""
    codes = [c for c, _ in M.validate(_verdict_record(value="  "))]
    assert "VERDICT_SENTINEL" in codes


def test_a_verdict_may_not_name_a_physical_unit():
    codes = [c for c, _ in M.validate(_verdict_record(unit="ns"))]
    assert "VERDICT_UNIT_WRONG" in codes


def test_a_number_may_not_borrow_the_verdict_unit():
    """A number whose unit is 'verdict' is a number with no unit at all."""
    rec = {"schema": M.SCHEMA_ID, "metric": "physical.drc.violations",
           "status": "MEASURED", "unit": M.VERDICT_UNIT, "value": 0,
           "scope": {"stage": "signed_off_gds"},
           "source": {"path": "x.json", "sha256": "sha256:" + "0" * 64,
                      "tool": "t"}}
    codes = [c for c, _ in M.validate(rec)]
    assert "VERDICT_UNIT_ON_A_NUMBER" in codes


def test_two_verdicts_are_never_subtracted():
    """'MATCH' minus 'MATCH' is not 0, and a delta of 0 printed for two
    verdicts reads as 'no regression' on a pair that were never numbers."""
    out = M.compare(_verdict_record(), _verdict_record())
    assert out["verdict"] == M.CMP_NOT_NUMERIC
    assert "delta_b_minus_a" not in out
    assert out["equal"] is True
    assert out["winner"] is None if "winner" in out else True


def test_two_different_verdicts_report_as_unequal_and_still_have_no_delta():
    out = M.compare(_verdict_record("MATCH"), _verdict_record("MISMATCH"))
    assert out["verdict"] == M.CMP_NOT_NUMERIC and out["equal"] is False
    assert "delta_b_minus_a" not in out


def test_numeric_records_still_compare_normally():
    """The exemption must not leak into the numeric path."""
    def num(v):
        return {"schema": M.SCHEMA_ID, "metric": "physical.drc.violations",
                "status": "MEASURED", "unit": "count", "value": v,
                "scope": {"stage": "signed_off_gds"},
                "source": {"path": "x.json", "sha256": "sha256:" + "0" * 64,
                           "tool": "t"}}
    out = M.compare(num(2), num(5))
    assert out["verdict"] == M.CMP_OK and out["delta_b_minus_a"] == 3


# ==========================================================================
# F-8 -- the power record's PVT scope
# ==========================================================================
def _report(liberty):
    return {"liberty": liberty, "tool": "opensta",
            "activity": {"basis": "vectorless_sdc"},
            "rows": [{"group": "Total", "internal_w": 1e-3,
                      "switching_w": 2e-4, "leakage_w": 1e-9, "total_w": 1.2e-3,
                      "internal_raw": "1e-3", "switching_raw": "2e-4",
                      "leakage_raw": "1e-9", "total_raw": "1.2e-3"}]}


def test_the_pvt_the_liberty_names_reaches_the_scope():
    """`REQUIRED_SCOPE["power_mw"]` needs process, voltage_v and temperature_c
    before two power numbers may be compared. This module emitted none of them
    while carrying, in `scope.liberty`, the file name that states all three --
    and while the same lane shipped the parser for it."""
    rec = P.metric_records(_report("sky130_fd_sc_hd__tt_025C_1v80.lib"),
                           stage="post_route_extracted")[0]
    assert rec["scope"]["process"] == "tt"
    assert rec["scope"]["voltage_v"] == pytest.approx(1.8)
    assert rec["scope"]["temperature_c"] == pytest.approx(25.0)


def test_an_unreadable_liberty_stem_leaves_the_keys_OUT_and_says_why():
    """THE HALF THAT MATTERS. `check_scope_parity` tests required keys for
    PRESENCE, so `process: None` would satisfy the key check and then compare
    equal to another None -- two records that say nothing about their corner,
    passing as the same corner. That is worse than the refusal it replaces."""
    rec = P.metric_records(_report("mystery.lib"), stage="x")[0]
    for key in ("process", "voltage_v", "temperature_c"):
        assert key not in rec["scope"], key
    assert rec["provenance"]["liberty_pvt_gaps"]["process"] == "absent"


def test_an_ambiguous_stem_is_refused_rather_than_guessed():
    """The parser refuses on disagreement, and this must carry that through: a
    wrong corner is worse than an absent one because it makes two incomparable
    numbers look comparable."""
    rec = P.metric_records(_report("lib__ss_025C_1v80_and_1v20.lib"),
                           stage="x")[0]
    assert "voltage_v" not in rec["scope"]
    assert rec["provenance"]["liberty_pvt_gaps"]["voltage_v"].startswith(
        "ambiguous")


def test_the_head_to_head_still_refuses_a_power_scope_with_no_mode():
    """`mode` is the fourth key REQUIRED_SCOPE wants and no power artefact
    states one. The refusal is correct and it stays."""
    rec = P.metric_records(_report("sky130_fd_sc_hd__tt_025C_1v80.lib"),
                           stage="post_route_extracted")[0]
    assert "mode" not in rec["scope"]
    missing = [k for k in B.REQUIRED_SCOPE["power_mw"]
               if k not in rec["scope"]]
    assert missing == ["mode"]


def test_a_caller_supplied_mode_completes_the_required_scope():
    rec = P.metric_records(_report("sky130_fd_sc_hd__tt_025C_1v80.lib"),
                           stage="post_route_extracted",
                           extra_scope={"mode": "functional"})[0]
    assert all(k in rec["scope"] for k in B.REQUIRED_SCOPE["power_mw"])


TIMING_SCOPE = {"stage": "post_route", "mode": "functional", "process": "ss",
                "voltage_v": 1.6, "temperature_c": 100.0,
                "rc_corner": "max", "check": "setup"}
POWER_SCOPE = {"stage": "post_route", "mode": "functional", "process": "tt",
               "voltage_v": 1.8, "temperature_c": 25.0,
               "activity_basis": "vectorless_sdc"}


def _arms(power_scope):
    """Two arms complete on every axis, differing only in the power scope."""
    return [{"flow": flow, "measurement_basis": "post_route_sta",
             "ppa": {
                 "area_um2": {"value": 100.0,
                              "scope": {"stage": "post_route"}},
                 "timing_wns_ns": {"value": 0.2,
                                   "scope": dict(TIMING_SCOPE)},
                 "power_mw": {"value": 1.0, "scope": dict(power_scope)}}}
            for flow in ("ours", "theirs")]


def test_a_present_but_null_required_scope_key_is_refused():
    """The SCOPE_INCOMPLETE hole one step in: `k not in sc` is satisfied by
    `{"mode": None}`, and two arms declaring null then compare EQUAL and buy
    the parity they were meant to be refused."""
    with pytest.raises(B.Refusal) as exc:
        B.check_scope_parity(_arms(dict(POWER_SCOPE, mode=None)))
    assert exc.value.code == "SCOPE_SENTINEL"
    assert "mode" in str(exc.value)


def test_an_empty_string_scope_key_is_refused_the_same_way():
    with pytest.raises(B.Refusal) as exc:
        B.check_scope_parity(_arms(dict(POWER_SCOPE, process="")))
    assert exc.value.code == "SCOPE_SENTINEL"


def test_a_stated_scope_on_both_arms_still_passes_parity():
    """The guard must refuse nulls without refusing a legitimate pair."""
    B.check_scope_parity(_arms(POWER_SCOPE))

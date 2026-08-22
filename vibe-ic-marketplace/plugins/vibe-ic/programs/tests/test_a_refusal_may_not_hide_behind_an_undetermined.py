#!/usr/bin/env python3
"""A finding about a record outranks a report that the record could not be read.

WHY THIS FILE EXISTS. `ppa_head_to_head_check.evaluate` ran
`check_scope_parity` (which raises at RC_UNDETERMINED, 2) BEFORE
`check_stage_basis_agreement` (which raises at RC_REFUSED, 1). A record that
trips both was therefore reported as `[UNDETERMINED] ... SCOPE_INCOMPLETE`
and its REFUSAL was never printed.

MEASURED on this repo's own published corpora, three records were in exactly
that state, all one shape -- a `power_mw` taken at `stage='synth'` cited under
`measurement_basis='post_route_sta'`:

    ppa-crosslayer/records/h2h_A.json    both arms
    ppa-crosslayer/records/h2h_B.json    both arms
    ppa-e2e/records/head_to_head.json    both arms

Each says, on its face, that it holds a sign-off measurement; each actually
holds a pre-physical synthesis estimate. `STAGE_CONTRADICTS_BASIS` exists to
say so and could not be reached. Both wired rows reported rc 2 -- NOT CHECKED
-- while a finding sat behind them, and an rc 2 that swallows an rc 1 is the
failure mode this layer exists to end. It is the THIRD instance in this
family; `run_coverage` and `ppa_problem_integrity_check` carried the same
inversion and were repaired earlier in this lane.

WHAT IS PINNED, and why it is not simply "1 outranks 2". The two checks read
DIFFERENT things:

    check_stage_basis_agreement   INTRA-arm. One arm's declared basis against
                                  its own recorded stage. No other arm is
                                  consulted; the contradiction is established
                                  whatever any comparison does.
    check_scope_parity            INTER-arm. Whether two arms are comparable
                                  at all.

So "these two records could not be compared" is not a reason to withhold "this
record contradicts itself". That asymmetry -- not the rc ordering alone -- is
what makes the order correct, and it is asserted below in BOTH directions:
a record with only a scope defect must STILL be undetermined, so the rule
cannot be satisfied by a checker that has learned to refuse everything.

chip-AGNOSTIC: no design, PDK, vendor, node or codename literal.
"""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROGRAMS))

from _ppa import benchmark as B  # noqa: E402
from _ppa import canonical_json as cj  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_mask_hh", PROGRAMS / "ppa_head_to_head_check.py")
HH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HH)

#: The two corpora the wired rows read. Absent on a checkout without the
#: campaign trees, which is a SKIP and not a pass -- the fixture tests below
#: carry the rule on their own.
CORPORA = (REPO / "ppa-crosslayer", REPO / "ppa-e2e")

_PHYS = "post_route_extracted"
_PROXY = "synth"          # a stage `post_route_sta` may not cite
_SIGNOFF = "post_route_sta"

_DESIGN = {"spec_sha256": "a" * 64, "pdk": "PDK_UNDER_TEST",
           "clock_target_ns": 10.0, "corners": ["c_slow", "c_typ"]}
_CONTRACT_BODY = dict(_DESIGN, floorplan={"utilisation_target": 0.55},
                      permitted_cells="the PDK's own default set, unmodified")
_CONTRACT_SHA = cj.digest_of(_CONTRACT_BODY)

_AREA_SCOPE = {"stage": _PHYS}
_TIMING_SCOPE = {"stage": _PHYS, "mode": "functional", "process": "PROC_SLOW",
                 "voltage_v": 1.62, "temperature_c": 125.0,
                 "rc_corner": "max", "check": "setup", "clock": "clk"}
_POWER_SCOPE = {"stage": _PHYS, "mode": "functional", "process": "PROC_SLOW",
                "voltage_v": 1.62, "temperature_c": 125.0,
                "activity_basis": "vectorless"}


def _metric(value, unit, scope):
    return {"status": "MEASURED", "value": value, "unit": unit,
            "scope": copy.deepcopy(scope)}


def _ppa(area, wns, power):
    return {"area_um2": _metric(area, "um^2", _AREA_SCOPE),
            "timing_wns_ns": _metric(wns, "ns", _TIMING_SCOPE),
            "power_mw": _metric(power, "mW", _POWER_SCOPE)}


def _feasible():
    return {"checks": {n: {"violations": 0, "source": f"<{n} report>"}
                       for n in B.FEASIBILITY_FLOOR}}


def _tuning(ours):
    return {"supported": True, "performed": True,
            "budget": {"trials": 200, "cpu_hours": 96.0},
            "search_space": {
                "source": "authored_for_this_comparison" if ours else "official",
                "ref": "this project's own" if ours else "the opponent's own",
                "authored_by_this_project": bool(ours)}}


def _arm(role, ppa):
    ours = role == "subject"
    return {"flow": f"{role}-flow", "role": role, "version": "x",
            "design": dict(_DESIGN),
            "contract": {"sha256": _CONTRACT_SHA,
                         "body": copy.deepcopy(_CONTRACT_BODY)},
            "measurement_basis": _SIGNOFF,
            "config_source": "upstream default config, unmodified",
            "tuned_by_this_project": ours,
            "ppa": ppa, "feasibility": _feasible(), "tuning": _tuning(ours)}


def _doc(subject_ppa=None, baseline_ppa=None):
    return {"schema": "vibeic.ppa.comparison.v2",
            "arms": [_arm("subject", subject_ppa or _ppa(1000.0, -0.10, 5.00)),
                     _arm("baseline", baseline_ppa or _ppa(1200.0, -0.30, 6.00))]}


def _run(tmp_path, doc, name="rec.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return HH.evaluate(p)


def _with_proxy_power(ppa):
    """The real defect: a synthesis power number under a sign-off basis."""
    out = copy.deepcopy(ppa)
    out["power_mw"]["scope"]["stage"] = _PROXY
    return out


def _with_scope_defect(ppa):
    """An INTER-arm defect only: a required scope key declared with no value.

    `rc_corner: None` is the sentinel `check_scope_parity` refuses, and it is
    the exact shape carried by the records this file was written for.
    """
    out = copy.deepcopy(ppa)
    out["timing_wns_ns"]["scope"]["rc_corner"] = None
    return out


# ---------------------------------------------------------------------------
# The rule, and its paired half.
# ---------------------------------------------------------------------------

def test_a_basis_contradiction_alone_is_refused(tmp_path):
    """The premise, and it was ALWAYS caught -- including before the fix.

    BOTH arms carry the proxy stage, so the scopes still MATCH each other and
    `check_scope_parity` has nothing to say. Only the intra-arm contradiction
    remains, and it was reachable in either order. Stated separately so the
    negative control below is not credited with a red it did not earn: this
    test stays green when the ordering is reverted, and that is correct.

    It is also the shape the three real records have -- both arms at `synth`,
    agreeing with each other perfectly, and both wrong about what they hold.
    """
    proxy = _with_proxy_power(_ppa(1000.0, -0.10, 5.00))
    rc, rep = _run(tmp_path, _doc(
        subject_ppa=proxy,
        baseline_ppa=_with_proxy_power(_ppa(1200.0, -0.30, 6.00))))
    assert rc == B.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "STAGE_CONTRADICTS_BASIS", rep


def test_a_scope_defect_alone_is_still_UNDETERMINED(tmp_path):
    """THE PAIRED HALF.

    Without it, every assertion in this file is satisfied by a checker that
    has simply learned to refuse everything, and the STILL-CANNOT verdict --
    which is correct wherever it is earned -- would be quietly destroyed.
    """
    rc, rep = _run(tmp_path, _doc(baseline_ppa=_with_scope_defect(
        _ppa(1200.0, -0.30, 6.00))))
    assert rc == B.RC_UNDETERMINED, rep
    assert rep["refusal"]["code"].startswith("SCOPE_"), rep


def test_a_record_with_BOTH_is_refused_and_not_reported_undetermined(tmp_path):
    """The defect this file is named for.

    The record contradicts itself AND cannot be compared. It must be reported
    as the finding, because the self-contradiction is established without
    reference to the other arm.
    """
    rc, rep = _run(tmp_path, _doc(
        subject_ppa=_with_proxy_power(_ppa(1000.0, -0.10, 5.00)),
        baseline_ppa=_with_scope_defect(
            _with_proxy_power(_ppa(1200.0, -0.30, 6.00)))))
    assert rc == B.RC_REFUSED, (
        "a record that contradicts its own declared basis was reported as "
        "merely undetermined. An rc 2 that swallows an rc 1 is the failure "
        f"mode this layer exists to end. got rc={rc} {rep.get('refusal')}")
    assert rep["refusal"]["code"] == "STAGE_CONTRADICTS_BASIS", rep


def test_the_refusal_names_the_stage_and_the_basis_it_contradicts(tmp_path):
    """An rc 1 a reader cannot act on is barely better than an rc 2."""
    _, rep = _run(tmp_path, _doc(
        subject_ppa=_with_proxy_power(_ppa(1000.0, -0.10, 5.00)),
        baseline_ppa=_with_scope_defect(
            _with_proxy_power(_ppa(1200.0, -0.30, 6.00)))))
    msg = rep["refusal"]["message"]
    assert _PROXY in msg and _SIGNOFF in msg, msg
    assert "power_mw" in msg, msg


# ---------------------------------------------------------------------------
# THE WIDER CLASS. The basis contradiction was one instance; a scope defect
# could mask every rc-1 refusal whose evidence is INDEPENDENT of the
# comparison, including three of the four rigged-benchmark refusals #1121
# exists to enforce. Each of these was MEASURED at 1 alone and 2 the moment an
# unrelated `rc_corner` sentinel was added.
# ---------------------------------------------------------------------------

def _infeasible(doc):
    doc["arms"][1]["feasibility"]["checks"]["drc"] = {"violations": 3,
                                                      "source": "<drc report>"}


def _underbudgeted(doc):
    doc["arms"][1]["tuning"]["budget"] = {"trials": 1, "cpu_hours": 0.1}


def _our_search_space(doc):
    doc["arms"][1]["tuning"]["search_space"]["authored_by_this_project"] = True


def _not_tuned(doc):
    doc["arms"][1]["tuning"]["performed"] = False


@pytest.mark.parametrize("mutate,code", [
    (_infeasible, "ARM_INFEASIBLE"),
    (_underbudgeted, "OPPONENT_UNDERBUDGETED"),
    (_our_search_space, "BASELINE_TUNING_CONTRADICTS_ROLE"),
    (_not_tuned, "OPPONENT_NOT_TUNED"),
])
def test_a_parity_independent_refusal_survives_a_scope_defect(
        tmp_path, mutate, code):
    """An arm with DRC violations is infeasible whether or not two scopes line
    up, and an opponent handed a smaller budget than ours is under-budgeted
    whether or not two scopes line up. Both are read off ONE arm's own block.

    THE PAIRED HALF IS THE NEXT TEST: this must not be achieved by making
    parity stop refusing.
    """
    doc = _doc(baseline_ppa=_with_scope_defect(_ppa(1200.0, -0.30, 6.00)))
    mutate(doc)
    rc, rep = _run(tmp_path, doc)
    assert rc == B.RC_REFUSED, (
        f"{code} is demonstrable from the record itself, and an unrelated "
        f"incomplete scope key hid it. got rc={rc} {rep.get('refusal')}")
    assert rep["refusal"]["code"] == code, rep


@pytest.mark.parametrize("mutate,code", [
    (_infeasible, "ARM_INFEASIBLE"),
    (_underbudgeted, "OPPONENT_UNDERBUDGETED"),
    (_our_search_space, "BASELINE_TUNING_CONTRADICTS_ROLE"),
    (_not_tuned, "OPPONENT_NOT_TUNED"),
])
def test_the_same_refusal_is_raised_with_no_scope_defect_present(
        tmp_path, mutate, code):
    """THE PREMISE for the test above. If these codes did not fire on a clean
    record either, the test above would be asserting nothing about masking.
    """
    doc = _doc()
    mutate(doc)
    rc, rep = _run(tmp_path, doc)
    assert rc == B.RC_REFUSED and rep["refusal"]["code"] == code, rep


def test_a_verdict_refusal_DELIBERATELY_stays_below_parity(tmp_path):
    """THE ONE THAT IS NOT MOVED, AND IT IS A DECISION RATHER THAN A LEFTOVER.

    `derive_verdict` / `check_asserted_verdict` compare the NUMBERS. A verdict
    refusal derived from two arms that were never shown comparable is not
    independently demonstrable -- it is a conclusion drawn from a comparison
    the checker just said it could not make. So when parity fails, the honest
    answer is the rc 2, and this test exists so that "finish the job and move
    the verdict check up too" is refused with a reason rather than done.
    """
    doc = _doc(baseline_ppa=_with_scope_defect(_ppa(1200.0, -0.30, 6.00)))
    doc["verdict"] = {"pareto": "SUBJECT_DOMINATES"}
    rc, rep = _run(tmp_path, doc)
    assert rc == B.RC_UNDETERMINED, rep
    assert rep["refusal"]["code"].startswith("SCOPE_"), rep


# ---------------------------------------------------------------------------
# THE FAMILY'S ONE DELIBERATE INVERSION, AND THE CLAIM THAT LICENSES IT.
#
# `_ppa/feasibility.py` inverts this file's rule ON PURPOSE at SET level: an
# UNDETERMINED candidate outranks an INFEASIBLE one, so the CLI returns 2 and
# not 1. Its stated reason is sound -- "rc=1 asserts a complete finding about
# the design, and a run that could not see all of its evidence must not make
# one" -- and this file does NOT try to overturn it.
#
# What it does is enforce the sentence that LICENSES it, which was argued in a
# docstring and pinned by nothing:
#
#     "Nothing is lost: both block, every per-candidate verdict is in the JSON,
#      and every finding is printed regardless of which code is returned."
#
# That is the entire reason the inversion is acceptable rather than the defect
# this file exists to end. If a future change stops printing the INFEASIBLE
# line whenever the set returns 2, the justification silently becomes false and
# a measured DRC violation disappears behind a NOT CHECKED -- with the
# docstring still claiming otherwise. MEASURED as true today; pinned here so it
# stays a fact rather than a promise.
# ---------------------------------------------------------------------------

def test_the_set_level_inversion_still_prints_and_records_every_finding(
        tmp_path):
    feas_tests = Path(__file__).resolve().parent / "test_ppa_feasibility.py"
    if not feas_tests.exists():
        pytest.skip("the feasibility fixture module is not in this checkout")
    _s = importlib.util.spec_from_file_location("_feas_fx", feas_tests)
    FX = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(FX)

    violated = FX.clean_metrics()
    violated[3]["value"] = 5                 # a real, MEASURED DRC violation
    unmeasured = FX.clean_metrics()
    unmeasured[6]["status"] = "NOT_MEASURED"  # an axis nobody looked at
    unmeasured[6].pop("value")

    doc = {"required_views": [dict(FX.VIEW)],
           "candidates": [FX.candidate("cand_violated", metrics=violated),
                          FX.candidate("cand_unmeasured", metrics=unmeasured)]}
    cand = tmp_path / "candidates.json"
    cand.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "feas.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "ppa_feasibility_check.py"),
         "--candidates", str(cand), "--json", str(out)],
        capture_output=True, text=True)

    # The inversion itself, asserted so the test is anchored to it rather than
    # silently passing if the precedence ever changed underneath.
    assert r.returncode == B.RC_UNDETERMINED, (
        "the documented set-level precedence (UNDETERMINED over INFEASIBLE) "
        f"no longer holds; got rc={r.returncode}. If that is a deliberate "
        "change, this whole block needs rewriting, not re-pointing.")

    text = r.stdout + r.stderr
    assert "INFEASIBLE" in text, (
        "the set returned 2 and the INFEASIBLE finding was NOT printed. That "
        "is the sentence licensing the inversion, and it is now false: a "
        "measured violation is hidden behind a NOT CHECKED.")
    assert "cand_violated" in text, (
        "the INFEASIBLE candidate is not NAMED on stdout, so a reader cannot "
        "act on the finding the docstring promises is printed.")

    assert out.exists(), "no JSON was written, so 'it is in the JSON' is false"
    verdicts = {}

    def _collect(o):
        if isinstance(o, dict):
            if "candidate_id" in o and "verdict" in o:
                verdicts[o["candidate_id"]] = o["verdict"]
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for v in o:
                _collect(v)

    _collect(json.loads(out.read_text(encoding="utf-8")))
    assert verdicts.get("cand_violated") == "INFEASIBLE", verdicts
    assert verdicts.get("cand_unmeasured") == "UNDETERMINED", verdicts


def test_the_frontier_gate_makes_the_same_licensed_inversion_and_keeps_it(
        tmp_path):
    """THE SECOND deliberate inversion, licensed by the SAME unpinned sentence.

    `_ppa/pareto.frontier_exit_code` inverts exactly as the feasibility CLI
    does, and says so: "UNDETERMINED outranks REFUSED ... Both block, and every
    finding is printed whichever code is returned." Same design, same reason,
    and until now the same clause carried by prose alone.

    MEASURED as the pure function: a FAIL-material code alone is 1, an
    undetermined-material code alone is 2, and both together are 2.

    The set below is the shape that matters -- a PUBLISHED frontier that
    disagrees with the recomputation (rc-1 material) while a second candidate
    has an unmeasured objective (which drives the rc to 2). If the findings
    stopped being emitted, a published frontier known to be WRONG would sit
    behind a NOT CHECKED.
    """
    pareto_tests = Path(__file__).resolve().parent / "test_ppa_pareto.py"
    if not pareto_tests.exists():
        pytest.skip("the pareto fixture module is not in this checkout")
    _s = importlib.util.spec_from_file_location("_pareto_fx", pareto_tests)
    FX = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(FX)
    from _ppa import pareto as P  # noqa: E402

    clean = FX.cand("cand_clean", 100.0, 1.0, 0.05)
    unmeasured = FX.cand("cand_unmeasured", 120.0, 2.0, 0.05)
    for m in unmeasured["metrics"]:
        if m.get("metric") == "area.total_um2":
            m["status"] = "NOT_MEASURED"
            m.pop("value", None)

    published = {"schema": P.PARETO_SCHEMA, "frontier": ["cand_unmeasured"]}
    r, doc = FX.run(tmp_path, [clean, unmeasured], frontier=published)

    assert r.returncode == B.RC_UNDETERMINED, (
        "the documented frontier precedence (UNDETERMINED over REFUSED) no "
        f"longer holds; got rc={r.returncode}")
    assert doc is not None, "no JSON was written"
    codes = {f.get("code") for f in doc.get("findings", [])}
    assert "PARETO_FRONTIER_DISAGREES" in codes, (
        "the premise is gone: this set no longer produces the rc-1-material "
        f"finding the test is about. got {sorted(codes)}")

    text = r.stdout + r.stderr
    for code in sorted(codes):
        assert code in text, (
            f"{code} is in the JSON but was NOT printed while the gate "
            "returned 2. That is the sentence licensing this inversion, and "
            "it is now false: a published frontier known to be wrong is "
            "sitting behind a NOT CHECKED.")


# ---------------------------------------------------------------------------
# The same rule, over the corpora the wired rows actually read.
# ---------------------------------------------------------------------------

def _comparison_records():
    for root in CORPORA:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*.json")):
            try:
                d = json.loads(f.read_text("utf-8", errors="replace"))
            except Exception:
                continue
            if (isinstance(d, dict)
                    and str(d.get("schema", "")).startswith(
                        "vibeic.ppa.comparison")):
                yield f, d


def test_no_published_record_hides_a_refusal_behind_an_undetermined():
    """The corpus-level guard that would have caught the original bug.

    For every committed comparison record: if the record contradicts its own
    declared basis, the checker's verdict must be the REFUSAL. A record that
    trips the intra-arm check and is nonetheless reported `NOT CHECKED` is the
    exact state three published records were in.
    """
    records = list(_comparison_records())
    if not records:
        pytest.skip("neither campaign corpus is present in this checkout")
    masked = []
    for path, doc in records:
        arms = doc.get("arms") or []
        try:
            B.check_stage_basis_agreement(arms)
        except B.Refusal:
            rc, rep = HH.evaluate(path)
            if rc != B.RC_REFUSED:
                masked.append((str(path), rc, rep.get("refusal", {}).get("code")))
    assert not masked, (
        "these published records contradict their own declared measurement "
        "basis and the checker reported something OTHER than the refusal, so "
        "the finding never reached a reader: " + repr(masked))


def test_the_premise_holds_the_corpus_still_contains_the_contradiction():
    """Pins the guard above against passing by finding nothing.

    If every record were repaired this test is the one that must be updated,
    deliberately, rather than the guard silently becoming vacuous.
    """
    records = list(_comparison_records())
    if not records:
        pytest.skip("neither campaign corpus is present in this checkout")
    contradicting = []
    for path, doc in records:
        try:
            B.check_stage_basis_agreement(doc.get("arms") or [])
        except B.Refusal:
            contradicting.append(path.name)
    assert contradicting, (
        "no published comparison record contradicts its basis any more. If "
        "that is a real repair, this file's guard is now vacuous and the "
        "fixture tests above are carrying it alone -- say so explicitly "
        "rather than leaving a green test that measures nothing.")

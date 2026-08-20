#!/usr/bin/env python3
"""The five v2 fairness conditions, each tested the only way a refusal can be
tested honestly: DIFFERENTIALLY. vibe-ic#1121, spec section 12.2.

    SAME RTL, SAME PDK, LOWER POWER, HIGHER PERFORMANCE, SMALLER AREA -- THAT IS
    BETTER.

Every test below exists because that sentence has an argument against it, and
the test is what closes the argument. So each one comes in a pair: the same
record with and without the one offending field. A single-arm assertion can only
ever say "this record is refused", which is equally true of a checker that
refuses everything -- and a checker that refuses everything is a ban, not a
check. `test_the_clean_v2_record_passes` is the paired half for all of them at
once: if the checker refused unconditionally, every refusal test here would
still be green and the file would mean nothing.

Four things are proven for every condition, per `docs/PPA_INTERFACES.md`
section 7:

    positive   the clean record is green
    negative   the offending record is RED, with the right code
    vacuous    a record that carries no evidence for the condition is rc=2 with
               a printed marker -- never rc=0 and never rc=1
    mutation   proved outside this file, by running it against a worktree at the
               base revision; see RESULT.md

THE VACUOUS COLUMN IS NOT PAPERWORK. A condition whose declared invocation exits
2 on absent input can never fail, and this repository has shipped that twice. So
for each condition there is a test that DELETES its evidence and asserts rc=2
AND asserts that a reader is told so in words.
"""
import copy
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_pphth_v2", PROGRAMS / "ppa_head_to_head_check.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

from _ppa import benchmark as B          # noqa: E402
from _ppa import canonical_json as cj    # noqa: E402


# ---------------------------------------------------------------------------
# The fixture. Deliberately built from helpers rather than written out once, so
# that a test which changes one thing can be SEEN to change one thing.
# ---------------------------------------------------------------------------
_CONTRACT_BODY = {
    "spec_sha256": "a" * 64,
    "pdk": "PDK_UNDER_TEST",
    "clock_target_ns": 10.0,
    "corners": ["c_slow", "c_typ"],
    "floorplan": {"utilisation_target": 0.55},
    "permitted_cells": "the PDK's own default set, unmodified",
}
_CONTRACT_SHA = cj.digest_of(_CONTRACT_BODY)

_DESIGN = {"spec_sha256": "a" * 64, "pdk": "PDK_UNDER_TEST",
           "clock_target_ns": 10.0, "corners": ["c_slow", "c_typ"]}

_PHYS = "post_route_extracted"
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
    return {"checks": {name: {"violations": 0, "source": f"<{name} report>"}
                       for name in B.FEASIBILITY_FLOOR}}


def _arm(flow, role, ppa, *, tuned_by_us, config_source, tuning):
    return {
        "flow": flow, "role": role, "version": "v",
        "design": dict(_DESIGN),
        "contract": {"sha256": _CONTRACT_SHA,
                     "body": copy.deepcopy(_CONTRACT_BODY)},
        "measurement_basis": "signed_off_gds",
        "config_source": config_source,
        "tuned_by_this_project": tuned_by_us,
        "ppa": ppa,
        "feasibility": _feasible(),
        "tuning": copy.deepcopy(tuning),
    }


_SUBJECT_TUNING = {"supported": True, "performed": True,
                   "budget": {"trials": 200, "cpu_hours": 96.0},
                   "search_space": {"source": "authored_for_this_comparison",
                                    "ref": "this project's own search space",
                                    "authored_by_this_project": True}}
_BASELINE_TUNING = {"supported": True, "performed": True,
                    "budget": {"trials": 200, "cpu_hours": 96.0},
                    "search_space": {"source": "official",
                                     "ref": "the opponent's own published space",
                                     "authored_by_this_project": False}}


def clean():
    """A record that should pass every condition. Fresh each call: a shared
    mutable fixture makes one test's mutation another test's premise."""
    return {
        "schema": B.SCHEMA_V2,
        "arms": [
            _arm("subject-flow", "subject", _ppa(1000.0, -0.10, 5.00),
                 tuned_by_us=True, config_source="this repo",
                 tuning=_SUBJECT_TUNING),
            _arm("baseline-flow", "baseline", _ppa(1200.0, -0.30, 6.00),
                 tuned_by_us=False,
                 config_source="upstream default config, unmodified",
                 tuning=_BASELINE_TUNING),
        ],
    }


def run(tmp_path, doc, name="rec.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return C.evaluate(p)


def code_of(rep):
    return (rep.get("refusal") or {}).get("code")


# ---------------------------------------------------------------------------
# THE PAIRED HALF for the whole file
# ---------------------------------------------------------------------------
def test_the_clean_v2_record_passes(tmp_path):
    rc, rep = run(tmp_path, clean())
    assert rc == C.RC_OK, rep
    assert rep["ok"] is True
    assert rep["declared_schema"] == B.SCHEMA_V2


def test_the_clean_record_wins_on_all_three_axes(tmp_path):
    """The fixture is a clean SWEEP on purpose, so that any test which flips one
    axis is visibly flipping one axis and not repairing an accident."""
    rc, rep = run(tmp_path, clean())
    assert rc == C.RC_OK
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert per["pareto"] == "SUBJECT_DOMINATES"
    for axis in B.AXES:
        assert per[axis]["verdict"] == "SUBJECT_BETTER"


# ---------------------------------------------------------------------------
# F1 -- ONE CONTRACT, PROVEN BY HASH
# ---------------------------------------------------------------------------
def test_two_arms_with_different_contract_hashes_are_UNDETERMINED(tmp_path):
    """The lane's named negative fixture: the checker refuses rather than
    picking one. A hash mismatch says the contracts differ without saying HOW,
    so a checker that chose a winner would be inventing the missing half."""
    doc = clean()
    other = dict(_CONTRACT_BODY, permitted_cells="a narrower set")
    doc["arms"][1]["contract"] = {"sha256": cj.digest_of(other),
                                  "body": other}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "CONTRACT_DIVERGED"


def test_the_diverged_contract_message_names_BOTH_and_picks_neither(tmp_path):
    doc = clean()
    other = dict(_CONTRACT_BODY, permitted_cells="a narrower set")
    doc["arms"][1]["contract"] = {"sha256": cj.digest_of(other), "body": other}
    rc, rep = run(tmp_path, doc)
    msg = rep["refusal"]["message"]
    assert "subject-flow" in msg and "baseline-flow" in msg
    assert _CONTRACT_SHA in msg and cj.digest_of(other) in msg
    assert "no winner" in msg
    text = C.format_report(rc, rep)
    assert "[CANNOT CHECK]" in text, (
        "an rc=2 must carry the contract's own marker, or it reads as a "
        "silent skip")


def test_the_contract_hash_catches_what_C1s_four_fields_cannot(tmp_path):
    """WHY THE HASH IS NOT ALREADY COVERED BY C1.

    Here the four fields C1 compares -- spec digest, PDK, clock target, corner
    set -- are IDENTICAL in both arms, so C1 passes and reports the same
    problem. The contracts still differ, in a key C1 never looks at. Without
    this condition the record is a green comparison of two different problems.
    """
    doc = clean()
    other = dict(_CONTRACT_BODY, floorplan={"utilisation_target": 0.75})
    doc["arms"][1]["contract"] = {"sha256": cj.digest_of(other), "body": other}
    # C1's own inputs are untouched and still agree:
    assert doc["arms"][0]["design"] == doc["arms"][1]["design"]
    assert C.check_same_problem(doc["arms"])          # C1 is satisfied
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "CONTRACT_DIVERGED"


def test_a_contract_hash_that_is_not_its_own_bodys_hash_is_REFUSED(tmp_path):
    """rc=1, not rc=2, and the difference is the whole exit-code contract: this
    defect IS demonstrable from the record alone, by recomputing the digest."""
    doc = clean()
    for arm in doc["arms"]:
        arm["contract"]["sha256"] = "sha256:" + "0" * 64
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "CONTRACT_HASH_WRONG"
    assert cj.digest_of(_CONTRACT_BODY) in rep["refusal"]["message"]


def test_a_body_less_contract_is_taken_at_its_word(tmp_path):
    """The differential half of the test above. A record may carry the hash
    alone -- the contract can live elsewhere -- and then there is nothing to
    recompute and nothing to refuse."""
    doc = clean()
    for arm in doc["arms"]:
        arm["contract"] = {"sha256": _CONTRACT_SHA, "source": "elsewhere"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda a: a.pop("contract"), id="no-contract-at-all"),
    pytest.param(lambda a: a["contract"].pop("sha256"), id="contract-without-hash"),
])
def test_VACUOUS_an_undeclared_contract_is_rc2_not_rc0_and_not_rc1(
        tmp_path, mutate):
    doc = clean()
    mutate(doc["arms"][1])
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert rc != C.RC_OK and rc != C.RC_REFUSED
    assert code_of(rep) == "CONTRACT_UNDECLARED"
    assert "[CANNOT CHECK]" in C.format_report(rc, rep)


# ---------------------------------------------------------------------------
# F2/F3/F4 -- ONE SCOPE PER AXIS: stage, corner/mode, activity basis
# ---------------------------------------------------------------------------
def test_synthesis_area_is_not_post_route_area(tmp_path):
    """THE SAME STAGE. The baseline's area is taken at synthesis and the
    subject's after routing; the subject is 'smaller' only because the two
    numbers are not the same quantity."""
    doc = clean()
    doc["arms"][1]["ppa"]["area_um2"]["scope"]["stage"] = "synthesis"
    doc["arms"][1]["measurement_basis"] = "post_route_sta"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) in ("SCOPE_DIVERGED", "STAGE_CONTRADICTS_BASIS")


def test_the_stage_divergence_is_reported_as_a_stage_divergence(tmp_path):
    doc = clean()
    for arm in doc["arms"]:
        arm["measurement_basis"] = "post_route_sta"
        for axis in B.AXES:
            arm["ppa"][axis]["scope"]["stage"] = "post_route"
    doc["arms"][1]["ppa"]["area_um2"]["scope"]["stage"] = "post_route_extracted"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_DIVERGED"
    assert "stage" in rep["refusal"]["message"]
    assert "area_um2" in rep["refusal"]["message"]


@pytest.mark.parametrize("key,value", [
    ("process", "PROC_TYPICAL"),
    ("voltage_v", 1.98),
    ("temperature_c", 25.0),
    ("rc_corner", "min"),
    ("mode", "scan"),
    ("check", "hold"),
])
def test_a_different_corner_or_mode_is_not_a_comparison(tmp_path, key, value):
    """THE SAME CORNER/MODE. Six keys, one condition: the scopes must be equal.
    Parametrised rather than written six times because the CHECK is one check --
    writing six would suggest six places a seventh key could be forgotten."""
    doc = clean()
    doc["arms"][1]["ppa"]["timing_wns_ns"]["scope"][key] = value
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_DIVERGED"
    assert key in rep["refusal"]["message"]


def test_vectorless_power_is_not_VCD_power(tmp_path):
    """THE SAME ACTIVITY BASIS. Two power numbers taken under different
    switching assumptions are different metrics, and the difference between
    them is routinely larger than the difference a flow produces.

    This is not hypothetical for the opponent in front of us: LibreLane
    3.1.0.dev1 contains zero occurrences of read_vcd / set_power_activity /
    SAIF and computes power with a bare `report_power -corner <c>`, so a
    LibreLane arm is vectorless by construction. See
    `_ppa/backends/librelane.py`."""
    doc = clean()
    doc["arms"][0]["ppa"]["power_mw"]["scope"]["activity_basis"] = "vcd"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_DIVERGED"
    assert "activity_basis" in rep["refusal"]["message"]


def test_the_same_divergence_repaired_passes(tmp_path):
    """The differential half of all three above: one key back in agreement and
    the record is green, so the refusals are about that key and not about the
    record."""
    doc = clean()
    doc["arms"][0]["ppa"]["power_mw"]["scope"]["activity_basis"] = "vcd"
    doc["arms"][1]["ppa"]["power_mw"]["scope"]["activity_basis"] = "vcd"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep


def test_an_unknown_scope_key_is_compared_without_anyone_adding_a_clause(
        tmp_path):
    """WHY EQUALITY AND NOT A LIST OF KEYS. A scope key nobody has thought of
    yet is compared the moment it exists. A checker built from three
    hand-written comparisons would pass this record and acquire its fourth
    blind spot silently."""
    doc = clean()
    for arm in doc["arms"]:
        arm["ppa"]["timing_wns_ns"]["scope"]["derate_ocv"] = 0.05
    doc["arms"][1]["ppa"]["timing_wns_ns"]["scope"]["derate_ocv"] = 0.00
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_DIVERGED"
    assert "derate_ocv" in rep["refusal"]["message"]


def test_VACUOUS_a_v1_bare_float_axis_is_rc2_because_it_carries_no_scope(
        tmp_path):
    """The v1 shape, exactly. A bare float cannot say which stage, corner or
    activity basis produced it, so it cannot be shown comparable -- and an
    unshowable comparison is UNDETERMINED, never a win."""
    doc = clean()
    doc["arms"][0]["ppa"]["area_um2"] = 1000.0
    doc["arms"][1]["ppa"]["area_um2"] = 1200.0
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_UNDECLARED"
    assert "[CANNOT CHECK]" in C.format_report(rc, rep)


def test_VACUOUS_both_arms_declaring_an_EMPTY_scope_does_not_buy_equality(
        tmp_path):
    """The degenerate way to satisfy an equality check is for both sides to say
    nothing. Two numbers that say nothing about themselves are not thereby
    comparable, and `REQUIRED_SCOPE` is what makes that true in code."""
    doc = clean()
    for arm in doc["arms"]:
        arm["ppa"]["area_um2"]["scope"] = {}
    assert (doc["arms"][0]["ppa"]["area_um2"]["scope"]
            == doc["arms"][1]["ppa"]["area_um2"]["scope"]), "equal, and useless"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_INCOMPLETE"
    assert "stage" in rep["refusal"]["message"]


@pytest.mark.parametrize("status",
                         ["NOT_MEASURED", "ESTIMATED", "DERIVED",
                          "NOT_APPLICABLE", "INVALID"])
def test_only_a_MEASURED_number_may_enter_the_comparison(tmp_path, status):
    doc = clean()
    doc["arms"][0]["ppa"]["power_mw"]["status"] = status
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "AXIS_NOT_COMPARABLE"


# ---------------------------------------------------------------------------
# F3 -- STAGE AND BASIS MUST AGREE (the proxy that keeps being mistaken for it)
# ---------------------------------------------------------------------------
def test_a_signoff_basis_may_not_cite_a_synthesis_number(tmp_path):
    """THE AREA LANE'S NEGATIVE FIXTURE, from the comparison side: a candidate
    that wins on a synthesis proxy must not be reported as smaller.

    Both arms are moved to the synthesis stage together, so scope PARITY is
    satisfied and this is the only refusal left. That matters: a comparison
    between arms cannot catch a proxy standing in for the property when BOTH
    arms use the proxy."""
    doc = clean()
    for arm in doc["arms"]:
        arm["ppa"]["area_um2"]["scope"]["stage"] = "synthesis"
    assert (doc["arms"][0]["ppa"]["area_um2"]["scope"]
            == doc["arms"][1]["ppa"]["area_um2"]["scope"])
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "STAGE_CONTRADICTS_BASIS"
    assert "PROXY" in rep["refusal"]["message"]


def test_a_post_route_sta_basis_may_not_cite_a_signed_off_gds_stage(tmp_path):
    """The rule is not 'proxy bad'; it is that a basis may cite only the stages
    it covers. An arm that only ran STA cannot claim a signed-off measurement.
    """
    doc = clean()
    for arm in doc["arms"]:
        arm["measurement_basis"] = "post_route_sta"
        for axis in B.AXES:
            arm["ppa"][axis]["scope"]["stage"] = "signed_off_gds"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "STAGE_CONTRADICTS_BASIS"


# ---------------------------------------------------------------------------
# F4 -- BOTH ARMS FEASIBLE, OVER THE SAME QUESTION
# ---------------------------------------------------------------------------
def test_SMALLER_AREA_WITH_DRC_VIOLATIONS_IS_NOT_SMALLER(tmp_path):
    """The headline of this condition, and the cheapest possible false win:
    relax until it fits, then publish the area. The subject here wins every
    axis and does not close, and the checker must not report the win."""
    doc = clean()
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 100.0        # by far the best
    doc["arms"][0]["feasibility"]["checks"]["drc"] = {
        "violations": 17, "source": "<drc report>"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "ARM_INFEASIBLE"
    assert "not smaller" in rep["refusal"]["message"]


def test_an_infeasible_BASELINE_is_refused_too(tmp_path):
    """The condition is about the COMPARISON, not about us. Beating an opponent
    whose implementation does not close is not beating the opponent."""
    doc = clean()
    doc["arms"][1]["feasibility"]["checks"]["lvs"] = {
        "violations": 3, "source": "<lvs report>"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "ARM_INFEASIBLE"
    assert "baseline-flow" in rep["refusal"]["message"]


def test_asking_the_two_arms_DIFFERENT_feasibility_questions_is_refused(
        tmp_path):
    """The subtle half. Both arms report clean; they were asked different
    questions, and the one asked less looks exactly as good as the one asked
    more."""
    doc = clean()
    doc["arms"][0]["feasibility"]["checks"]["ir_drop"] = {
        "violations": 0, "source": "<ir report>"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "FEASIBILITY_ASYMMETRIC"
    assert "ir_drop" in rep["refusal"]["message"]


def test_a_campaign_that_runs_MORE_checks_is_held_to_more_and_still_passes(
        tmp_path):
    """The differential half: the same extra check on BOTH arms is fine. The
    floor is a floor, not a ceiling."""
    doc = clean()
    for arm in doc["arms"]:
        arm["feasibility"]["checks"]["ir_drop"] = {
            "violations": 0, "source": "<ir report>"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    assert "ir_drop" in rep["feasibility"]["subject-flow"]["checked"]


def test_an_asserted_feasibility_verdict_that_its_own_checks_deny_is_refused(
        tmp_path):
    doc = clean()
    doc["arms"][0]["feasibility"]["verdict"] = "FEASIBLE"
    doc["arms"][0]["feasibility"]["checks"]["antenna"] = {
        "violations": 4, "source": "<antenna report>"}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "FEASIBILITY_CONTRADICTED"


def test_an_asserted_feasibility_verdict_that_agrees_is_accepted(tmp_path):
    doc = clean()
    for arm in doc["arms"]:
        arm["feasibility"]["verdict"] = "FEASIBLE"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep


@pytest.mark.parametrize("mutate,why", [
    pytest.param(lambda a: a.pop("feasibility"), "no feasibility block at all",
                 id="absent"),
    pytest.param(lambda a: a["feasibility"].update(checks={}),
                 "an empty checks object", id="empty-checks"),
    pytest.param(lambda a: a["feasibility"]["checks"].pop("lvs"),
                 "a floor check missing", id="floor-check-missing"),
    pytest.param(lambda a: a["feasibility"]["checks"].__setitem__(
                     "drc", {"status": "NOT_CHECKED"}),
                 "a check that says it did not run", id="explicit-not-checked"),
])
def test_VACUOUS_unestablished_feasibility_is_rc2_not_rc0_and_not_rc1(
        tmp_path, mutate, why):
    """Each of these is a record that did not look. rc=2 with the missing thing
    NAMED -- because "I could not look" and "I looked and it was clean" must
    never produce the same verdict, and a zero over an unnamed population is
    not a measurement."""
    doc = clean()
    mutate(doc["arms"][1])
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, (why, rep)
    assert rc != C.RC_OK and rc != C.RC_REFUSED
    assert code_of(rep) == "FEASIBILITY_NOT_CHECKED"
    assert "baseline-flow" in rep["refusal"]["message"]
    assert "[CANNOT CHECK]" in C.format_report(rc, rep)


# ---------------------------------------------------------------------------
# F5 -- A TUNED ARM MUST BE ALLOWED TO TUNE
# ---------------------------------------------------------------------------
def test_an_untuned_opponent_that_ships_a_tuner_is_refused(tmp_path):
    doc = clean()
    doc["arms"][1]["tuning"]["performed"] = False
    doc["arms"][1]["tuning"].pop("search_space")
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "OPPONENT_NOT_TUNED"


def test_a_starved_opponent_is_refused(tmp_path):
    doc = clean()
    doc["arms"][1]["tuning"]["budget"] = {"trials": 5, "cpu_hours": 96.0}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "OPPONENT_UNDERBUDGETED"
    assert "trials" in rep["refusal"]["message"]


def test_a_starved_opponent_passes_EVERY_v1_refusal(tmp_path):
    """WHY THIS CONDITION IS NOT ALREADY COVERED BY C3.

    The record below declares `tuned_by_this_project: false` truthfully -- we
    did not touch the opponent's config -- names a config source, runs the same
    problem, carries the full triple and a simulated basis. All four of #1121's
    refusals are satisfied. The opponent got five trials against our two
    hundred. This is the polite kind of rigging, and v1 publishes it."""
    doc = clean()
    doc["arms"][1]["tuning"]["budget"] = {"trials": 5, "cpu_hours": 2.0}
    arms = doc["arms"]
    assert arms[1]["tuned_by_this_project"] is False
    assert C.check_same_problem(arms)                     # C1 satisfied
    C.check_triple(arms)                                  # C2 satisfied
    assert C.check_baseline_is_theirs(arms)                # C3 satisfied
    assert C.check_measurement_basis(arms)                 # C4 satisfied
    rc, rep = run(tmp_path, doc)                           # v2 is not
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "OPPONENT_UNDERBUDGETED"


def test_an_opponent_given_MORE_budget_than_us_is_fine(tmp_path):
    """The condition protects the opponent from being weakened; being generous
    to them does not make our win less credible. A rule that fired here would
    be a rule about symmetry rather than about fairness."""
    doc = clean()
    doc["arms"][1]["tuning"]["budget"] = {"trials": 2000, "cpu_hours": 960.0}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep


def test_a_search_space_we_wrote_for_the_opponent_is_refused(tmp_path):
    """A tuner can only find what its search space contains, so a space we chose
    is a result we chose. This is the weakening `tuned_by_this_project: false`
    is honestly compatible with."""
    doc = clean()
    doc["arms"][1]["tuning"]["search_space"] = {
        "source": "authored_for_this_comparison",
        "ref": "our own idea of what their knobs should be",
        "authored_by_this_project": False}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "OPPONENT_SEARCH_SPACE_NOT_OFFICIAL"


def test_a_baseline_claiming_untouched_while_we_wrote_its_search_space(
        tmp_path):
    """Self-contradiction inside one record, and the cheapest kind to close."""
    doc = clean()
    doc["arms"][1]["tuning"]["search_space"]["authored_by_this_project"] = True
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "BASELINE_TUNING_CONTRADICTS_ROLE"


def test_the_SUBJECT_may_search_a_space_it_wrote(tmp_path):
    """It is our flow. Refusing this would refuse the point of the exercise --
    the same argument C3 makes for a tuned subject."""
    assert (clean()["arms"][0]["tuning"]["search_space"]
            ["authored_by_this_project"] is True)
    rc, rep = run(tmp_path, clean())
    assert rc == C.RC_OK, rep


def test_a_flow_with_no_tuner_is_not_weakened_by_not_being_tuned(tmp_path):
    doc = clean()
    doc["arms"][1]["tuning"] = {"supported": False}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    assert rep["tuning"]["baseline-flow"]["supported"] is False


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda a: a.pop("tuning"), id="no-tuning-block"),
    pytest.param(lambda a: a["tuning"].pop("supported"), id="no-supported-key"),
    pytest.param(lambda a: a["tuning"].pop("search_space"),
                 id="tuned-but-no-search-space"),
])
def test_VACUOUS_an_undeclared_tuning_state_is_rc2_not_rc0_and_not_rc1(
        tmp_path, mutate):
    """"We do not know whether the opponent was allowed to tune" is exactly the
    state this condition exists to end, so it cannot be the state that passes.
    """
    doc = clean()
    mutate(doc["arms"][1])
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert rc != C.RC_OK and rc != C.RC_REFUSED
    assert code_of(rep) == "TUNING_UNDECLARED"
    assert "[CANNOT CHECK]" in C.format_report(rc, rep)


def test_VACUOUS_budgets_with_no_shared_dimension_are_rc2(tmp_path):
    doc = clean()
    doc["arms"][1]["tuning"]["budget"] = {"wall_hours": 1.0}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "BUDGET_INCOMPARABLE"


# ---------------------------------------------------------------------------
# PARETO -- the relation, never a scalar
# ---------------------------------------------------------------------------
def test_a_mixed_triple_is_INCOMPARABLE_and_says_so(tmp_path):
    doc = clean()
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 5000.0     # ours much worse
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert per["pareto"] == "INCOMPARABLE"
    text = C.format_report(rc, rep)
    assert "INCOMPARABLE is a RESULT" in text
    assert "trade-off" in text


def test_an_asserted_pareto_relation_the_numbers_deny_is_refused(tmp_path):
    """Without this, the collapsed figure the record may not CARRY simply
    arrives through the verdict: one word, quotable, and unchecked."""
    doc = clean()
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 5000.0
    doc["verdict"] = {"baseline-flow": {"pareto": "SUBJECT_DOMINATES"}}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert code_of(rep) == "VERDICT_CONTRADICTED"
    assert "INCOMPARABLE" in rep["refusal"]["message"]


def test_an_asserted_pareto_relation_that_agrees_is_accepted(tmp_path):
    """The differential half: same record, relation corrected."""
    doc = clean()
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 5000.0
    doc["verdict"] = {"baseline-flow": {"pareto": "INCOMPARABLE"}}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep


@pytest.mark.parametrize("subject,baseline,expect", [
    ({"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     {"area_um2": 2.0, "timing_wns_ns": 0.0, "power_mw": 2.0},
     "SUBJECT_DOMINATES"),
    ({"area_um2": 2.0, "timing_wns_ns": 0.0, "power_mw": 2.0},
     {"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     "BASELINE_DOMINATES"),
    ({"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     {"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     "EQUAL"),
    ({"area_um2": 1.0, "timing_wns_ns": 0.0, "power_mw": 1.0},
     {"area_um2": 2.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     "INCOMPARABLE"),
    # A tie on one axis with a win on another is still domination: nothing is
    # worse. Getting this wrong would report a real sweep as a trade-off.
    ({"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0},
     {"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 2.0},
     "SUBJECT_DOMINATES"),
])
def test_the_pareto_relation_over_the_triple(subject, baseline, expect):
    assert B.pareto_relation(subject, baseline) == expect


def test_the_pareto_relation_respects_that_HIGHER_slack_is_better():
    """Timing is the axis where higher is better. A relation that treated all
    three the same would pass most of the cases above and still be wrong."""
    worse_timing = {"area_um2": 1.0, "timing_wns_ns": -1.0, "power_mw": 1.0}
    better_timing = {"area_um2": 1.0, "timing_wns_ns": 0.0, "power_mw": 1.0}
    assert B.pareto_relation(better_timing, worse_timing) == "SUBJECT_DOMINATES"
    assert B.pareto_relation(worse_timing, better_timing) == "BASELINE_DOMINATES"


# ---------------------------------------------------------------------------
# STRUCTURAL PROPERTIES -- the ones a future author could quietly remove
# ---------------------------------------------------------------------------
def test_the_scorer_cannot_see_the_records_asserted_verdict():
    """An INDEPENDENT scorer, guaranteed by a signature rather than a promise.

    `score` takes `arms` and nothing else, so there is no parameter through
    which the record's own claim could reach it. A future author who wants the
    scorer to agree with the record has to widen the signature, and that is
    visible in a diff in a way that reading one more key off a dict is not.
    """
    params = list(inspect.signature(B.score).parameters)
    assert params == ["arms"], (
        "the scorer grew a parameter; if it can see the record's verdict it is "
        "no longer independent of it")


def test_the_scorer_gets_the_same_answer_whatever_the_record_asserts(tmp_path):
    """The behavioural half of the test above."""
    doc = clean()
    honest = B.score(doc["arms"])
    doc["verdict"] = {"baseline-flow": {"pareto": "BASELINE_DOMINATES"}}
    assert B.score(doc["arms"]) == honest


def test_a_v1_record_cannot_buy_a_pass_by_declaring_v1(tmp_path):
    """A gate that can be switched off by a field in its own input is not a
    gate. Declaring v1 changes what the report CALLS the document and nothing
    else: the conditions still run, and a scope-less record is still rc=2."""
    doc = clean()
    doc["schema"] = B.SCHEMA_V1
    for arm in doc["arms"]:
        arm["ppa"] = {"area_um2": 1.0, "timing_wns_ns": 1.0, "power_mw": 1.0}
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "SCOPE_UNDECLARED"


def test_an_unknown_schema_is_UNDETERMINED_not_refused(tmp_path):
    """Rules this program does not have are not rules the record broke."""
    doc = clean()
    doc["schema"] = "vibeic.ppa.comparison.v9"
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert code_of(rep) == "UNKNOWN_SCHEMA"


def test_a_refusal_raised_by_a_fairness_condition_is_CAUGHT_not_raised(
        tmp_path):
    """One `Refusal` type across the CLI and the library.

    If this file's checker defined its own, a refusal raised inside a fairness
    condition would escape `evaluate`'s `except Refusal` as a traceback -- and a
    traceback exits 1. rc=1 here means "the record cannot support its claim", a
    finding about silicon, so a crash would publish a hard finding over a bug.
    """
    assert C.Refusal is B.Refusal
    doc = clean()
    doc["arms"][1]["tuning"]["budget"] = {"trials": 1}
    rc, rep = run(tmp_path, doc)          # would raise, not return, if unbound
    assert rc == C.RC_REFUSED
    assert code_of(rep) == "OPPONENT_UNDERBUDGETED"


@pytest.mark.parametrize("module", ["_ppa/benchmark.py",
                                    "_ppa/backends/librelane.py"])
def test_the_library_is_chip_and_pdk_and_vendor_agnostic(module):
    """No design, PDK, vendor or process literal may steer the logic. Every
    domain value here is compared to the other arm's and never interpreted."""
    src = (PROGRAMS / module).read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]        # strip the module docstring
    for literal in ("sky130", "gf180", "asap7", "nangate", "ihp", "tsmc",
                    "samsung", "globalfoundries", "intel"):
        assert literal not in body.lower(), (
            f"{literal!r} appears in {module}'s logic; this library must not "
            "know any PDK, vendor or process name")


def test_the_corpus_glob_still_finds_a_v2_record(tmp_path):
    """The flow wires this gate as `optional_program_exit_zero` with
    `condition_files_exist: ["**/*head_to_head*.json"]`, and the checker's own
    `_RECORD_GLOB` is the same pattern -- deliberately, so condition-unmet and
    corpus-empty are the same set by construction and no record can hide behind
    the condition. A v2 record that the glob does not match would reintroduce
    exactly that gap."""
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "ppa_head_to_head_v2.json").write_text(json.dumps(clean()),
                                                encoding="utf-8")
    assert [p.name for p in C.corpus_records(d)] == ["ppa_head_to_head_v2.json"]
    assert C.check_corpus(d) == C.RC_OK


# ---------------------------------------------------------------------------
# THE UNQUOTABLE PERCENTAGE -- found by reading the first v2 report, not by a
# test. It is here so it cannot come back.
# ---------------------------------------------------------------------------
def test_an_improvement_in_negative_slack_does_not_print_MINUS_66_PERCENT(
        tmp_path):
    """The rendering this exists for, verbatim from the first v2 report:

        timing_wns_ns  subject=-0.1  baseline=-0.3  (higher better) -66.67%
                                                             -> SUBJECT_BETTER

    A minus sixty-six percent beside the word BETTER. The arithmetic is right
    and the figure is unquotable: (s-o)/o takes its SIGN from the baseline's
    sign, so one 0.2 ns improvement prints positive against a positive baseline
    and negative against a negative one. Negative slack is the normal state of
    an arm that has not closed, which is exactly when a comparison is
    published, so this was the common rendering and not the rare one.
    """
    doc = clean()
    doc["arms"][0]["ppa"]["timing_wns_ns"]["value"] = -0.10
    doc["arms"][1]["ppa"]["timing_wns_ns"]["value"] = -0.30
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    row = rep["derived_verdict"]["per_baseline"]["baseline-flow"]["timing_wns_ns"]
    assert row["verdict"] == "SUBJECT_BETTER"
    assert row["delta"] == pytest.approx(0.2)
    assert row["delta_pct"] is None
    assert row["delta_pct_reason"]
    text = C.format_report(rc, rep)
    assert "-66.67%" not in text
    assert "interval-scale" in text


def test_the_same_axis_prints_a_percentage_where_one_is_meaningful(tmp_path):
    """The differential half: area and power ARE ratio-scale -- a true zero and
    no negative values -- so a percentage is a statement about the quantity and
    it is printed."""
    rc, rep = run(tmp_path, clean())
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert per["area_um2"]["delta_pct"] == pytest.approx(-16.6667, abs=1e-3)
    assert per["power_mw"]["delta_pct"] == pytest.approx(-16.6667, abs=1e-3)
    assert "delta_pct_reason" not in per["area_um2"]
    assert "-16.67%" in C.format_report(rc, rep)


def test_a_zero_or_negative_baseline_on_a_ratio_axis_states_why_not(tmp_path):
    """No numeric sentinel: a percentage that has no denominator is None WITH A
    REASON, never a 0 and never an omitted key. A reader must be able to tell
    "no percentage is meaningful here" from "the percentage is zero"."""
    doc = clean()
    doc["arms"][1]["ppa"]["power_mw"]["value"] = 0.0
    rc, rep = run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    row = rep["derived_verdict"]["per_baseline"]["baseline-flow"]["power_mw"]
    assert row["delta_pct"] is None
    assert "no denominator" in row["delta_pct_reason"]


def test_every_axis_declares_its_measurement_scale():
    """A new axis added without a scale would silently inherit whichever branch
    the code happens to fall into. Declaring it is what makes the omission an
    error rather than a rendering."""
    assert set(B.AXIS_SCALE) == set(B.AXES)
    assert set(B.AXIS_SCALE.values()) <= {"ratio", "interval"}

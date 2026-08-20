#!/usr/bin/env python3
"""The PPA objective: the ported ORFS algebra, the two anti-cheating terms, and
the one thing that is ours — the weights are DECLARED, and an inherited ratio
says so in words.

Every test here is written so it can FAIL. The algebra tests carry golden values
computed by hand from the ORFS source (`PPAImprov.get_ppa`, fetched 2026-08-21),
so a transcription error in either direction is caught rather than a
self-consistent re-derivation of whatever the code happens to do. The
anti-cheating tests are DIFFERENTIAL: they assert that the cheating run scores
WORSE than the honest one, which is unsatisfiable if the term is dropped.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppa_objective import (AXES, INHERITED_PHRASE, NOT_MEASURED, ORFS_WEIGHTS,
                           REASON_ABSENT, REASON_KEY_ABSENT, REASON_UNREADABLE,
                           Refusal, evaluate, get_ppa, progress_step,
                           read_metrics, resolve_weights)

# A reference and a run that improves on it in every axis. Chosen so the golden
# numbers below are computable by hand rather than by running the code.
REF = {"clk_period": 10.0, "worst_slack": 0.0, "total_power": 1.0e-3,
       "final_util": 50.0, "num_drc": 0}
RUN = {"clk_period": 10.0, "worst_slack": 1.0, "total_power": 0.9e-3,
       "final_util": 40.0, "num_drc": 0}


# --------------------------------------------------------------------------
# The weights are declared — and an inherited ratio is never printed as chosen
# --------------------------------------------------------------------------
def test_no_declaration_inherits_orfs_and_says_so():
    got = resolve_weights({"fields": {}}, "L19")
    assert got["weights"] == ORFS_WEIGHTS
    assert got["source"] == "inherited"
    assert INHERITED_PHRASE in got["provenance"], (
        "an inherited weight printed as if the design chose it is a lie about "
        "who made the value judgement; the phrase must be in the record")
    assert got["declared_by"] is None


def test_declared_weights_are_used_and_not_labelled_inherited():
    got = resolve_weights(
        {"fields": {"ppa_weights": {"performance": 1, "power": 5, "area": 2}}},
        "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
    assert got["weights"] == {"performance": 1.0, "power": 5.0, "area": 2.0}
    assert got["source"] == "declared"
    assert INHERITED_PHRASE not in got["provenance"]
    assert got["declared_by"].endswith("L19_CONSTRAINTS_PDK.json")


def test_declared_weights_actually_change_the_score():
    """A declared preference that does not move the ranking is decoration.

    The reference here MISSES timing (worst_slack -2.0), so ORFS lengthens its
    effective clock period to 12 ns and the run's 10 ns is a real +16.7%
    performance term — otherwise the performance axis is flat and the test
    could not tell a weight change from a no-op.
    """
    ref = dict(REF, worst_slack=-2.0)
    power_first = {"performance": 1.0, "power": 10000.0, "area": 1.0}
    a = evaluate(RUN, ref, dict(ORFS_WEIGHTS), step=10, stages_total=14)
    b = evaluate(RUN, ref, power_first, step=10, stages_total=14)
    assert a["terms"]["performance"] == pytest.approx(100 * 2 / 12)
    assert a["score"] != b["score"]
    assert a["weighted"]["performance"] > a["weighted"]["power"]
    assert b["weighted"]["power"] > b["weighted"]["performance"]


@pytest.mark.parametrize("declared", [
    {"performance": 1, "power": 1},                    # partial
    {"performance": 1, "power": 1, "area": "wide"},    # non-numeric
    {"performance": 1, "power": -1, "area": 1},        # negative
    {"performance": 0, "power": 0, "area": 0},         # degenerate
    ["performance", "power", "area"],                  # not an object
])
def test_malformed_declaration_is_refused_never_completed(declared):
    with pytest.raises(Refusal):
        resolve_weights({"fields": {"ppa_weights": declared}}, "L19")


def test_partial_declaration_is_not_silently_topped_up_from_orfs():
    with pytest.raises(Refusal) as exc:
        resolve_weights(
            {"fields": {"ppa_weights": {"performance": 3, "power": 1}}}, "L19")
    assert exc.value.code == "WEIGHTS_PARTIAL"
    assert "area" in exc.value.message


# --------------------------------------------------------------------------
# The ported algebra — golden values from the ORFS source, not from this code
# --------------------------------------------------------------------------
def test_get_ppa_matches_hand_computed_orfs_values():
    # performance = percent(10.0, 9.0)              = 10.0
    #   (run worst_slack +1.0 is NOT subtracted; ORFS only subtracts when < 0,
    #    so eff = 10.0 for the run and 10.0 for the ref)   -> percent(10,10) = 0
    # power       = percent(1.0e-3, 0.9e-3)         = 10.0
    # area        = percent(100-50, 100-40)         = (50-60)/50*100 = -20.0
    parts = get_ppa(RUN, REF, dict(ORFS_WEIGHTS))
    assert parts["terms"]["performance"] == pytest.approx(0.0)
    assert parts["terms"]["power"] == pytest.approx(10.0)
    assert parts["terms"]["area"] == pytest.approx(-20.0)
    assert parts["ppa_upper_bound"] == pytest.approx((10000 + 100 + 100) * 100)
    # ppa = upper - (0*10000 + 10*100 + -20*100) = 1_020_000 - (1000 - 2000)
    assert parts["ppa"] == pytest.approx(1_020_000 - (1000 - 2000))


def test_negative_slack_lengthens_the_effective_clock_period():
    """ORFS `eff_clk_period -= worst_slack` when the slack is negative. A run
    that misses timing must not be scored as if it met it."""
    met = dict(RUN, worst_slack=0.0)
    missed = dict(RUN, worst_slack=-2.0)
    a = get_ppa(met, REF, dict(ORFS_WEIGHTS))
    b = get_ppa(missed, REF, dict(ORFS_WEIGHTS))
    assert b["effective_clk_period"] == pytest.approx(12.0)
    assert b["ppa"] > a["ppa"], "lower ppa is better; missing timing must cost"


# --------------------------------------------------------------------------
# Anti-cheating term 1: num_drc is a PENALTY
# --------------------------------------------------------------------------
def test_drc_violations_cost_the_score():
    clean = evaluate(dict(RUN, num_drc=0), REF, dict(ORFS_WEIGHTS), 14, 14)
    dirty = evaluate(dict(RUN, num_drc=25), REF, dict(ORFS_WEIGHTS), 14, 14)
    assert dirty["score"] > clean["score"], (
        "a configuration that wins by producing violations must not win")
    assert clean["drc_penalty"] == 0
    assert dirty["drc_penalty"] == pytest.approx(dirty["gamma"] * 25)


def test_a_better_ppa_bought_with_drc_can_lose_to_a_clean_worse_one():
    """The penalty has to be big enough to actually reorder, not just to exist."""
    # ORFS's area term is percent(100 - ref_util, 100 - util), which reduces to
    # (util - ref_util)/(100 - ref_util)*100 — so HIGHER instance utilisation
    # scores BETTER (the same logic packed into less core). The cheating run is
    # therefore the DENSE one, and density bought with violations is precisely
    # what the penalty exists to refuse.
    cheat = dict(RUN, final_util=80.0, num_drc=40)   # much better area…
    honest = dict(RUN, final_util=45.0, num_drc=0)   # …but filthy
    c = evaluate(cheat, REF, dict(ORFS_WEIGHTS), 14, 14)
    h = evaluate(honest, REF, dict(ORFS_WEIGHTS), 14, 14)
    assert c["ppa"] < h["ppa"], "premise: the cheating run has the better ppa"
    assert c["score"] > h["score"], "and it must still lose on score"


def test_unmeasured_drc_blocks_rather_than_scoring_zero():
    with pytest.raises(Refusal) as exc:
        evaluate(dict(RUN, num_drc=NOT_MEASURED), REF, dict(ORFS_WEIGHTS),
                 14, 14)
    assert exc.value.code == "METRIC_NOT_MEASURED"


# --------------------------------------------------------------------------
# Anti-cheating term 2: (step/100)**-1 — scored on how far it got
# --------------------------------------------------------------------------
def test_stopping_early_costs_more_than_it_saves():
    full = evaluate(RUN, REF, dict(ORFS_WEIGHTS),
                    step=progress_step(14, 14), stages_total=14)
    early = evaluate(RUN, REF, dict(ORFS_WEIGHTS),
                     step=progress_step(3, 14), stages_total=14)
    assert early["score"] > full["score"], (
        "crashing out of an expensive stage must not be a way to look fast")
    assert full["progress_multiplier"] == pytest.approx(1.0)
    # 14/3 up to the integer-percent rounding `progress_step` applies.
    assert early["progress_multiplier"] == pytest.approx(14 / 3, rel=0.05)


def test_a_longer_ladder_cannot_buy_a_better_multiplier():
    """MEASURED: the phase-3 ladder was 14 steps on one run and 20 on another.
    With the RAW count fed to `(step/100)**-1`, 18-of-20 beats a COMPLETE
    14-of-14 — the exact inversion the term exists to prevent."""
    complete = evaluate(RUN, REF, dict(ORFS_WEIGHTS), progress_step(14, 14), 14)
    longer_but_unfinished = evaluate(RUN, REF, dict(ORFS_WEIGHTS),
                                     progress_step(18, 20), 20)
    assert longer_but_unfinished["score"] > complete["score"]
    # and the raw-count form, which is what goes wrong:
    assert (100 / 18) < (100 / 14), "premise: raw counts favour the long ladder"


def test_progress_step_is_a_percentage_of_the_run_s_own_ladder():
    assert progress_step(14, 14) == 100
    assert progress_step(20, 20) == 100
    assert progress_step(18, 20) == 90
    assert progress_step(1, 20) == 5
    assert progress_step(0, 20) == 0
    assert progress_step(5, 0) == 0
    assert progress_step(1, 10_000) == 1, "clamped to a finite reciprocal"


def test_a_raw_stage_count_is_refused_rather_than_silently_rewarded():
    with pytest.raises(Refusal) as exc:
        evaluate(RUN, REF, dict(ORFS_WEIGHTS), step=140, stages_total=200)
    assert exc.value.code == "STEP_OUT_OF_RANGE"


def test_step_zero_is_refused_not_ranked_last():
    with pytest.raises(Refusal) as exc:
        evaluate(RUN, REF, dict(ORFS_WEIGHTS), step=0, stages_total=14)
    assert exc.value.code == "STEP_ZERO"


def test_step_semantics_are_stated_in_every_result():
    got = evaluate(RUN, REF, dict(ORFS_WEIGHTS), 14, 14)
    assert "completed/declared" in got["step_semantics"]
    assert "Ray" in got["step_semantics"], (
        "the deviation from ORFS's own meaning of `step` must be stated where "
        "the number is, not only in a docstring")


# --------------------------------------------------------------------------
# Unmeasured is not clean
# --------------------------------------------------------------------------
def test_any_unmeasured_axis_blocks_the_score():
    for axis in ("clk_period", "worst_slack", "total_power", "final_util"):
        with pytest.raises(Refusal) as exc:
            evaluate(dict(RUN, **{axis: NOT_MEASURED}), REF,
                     dict(ORFS_WEIGHTS), 14, 14)
        assert exc.value.code == "METRIC_NOT_MEASURED", axis


def test_degenerate_reference_is_refused_not_divided_by():
    for bad in ({"total_power": 0.0}, {"final_util": 100.0}):
        with pytest.raises(Refusal) as exc:
            get_ppa(RUN, dict(REF, **bad), dict(ORFS_WEIGHTS))
        assert exc.value.code == "REFERENCE_DEGENERATE"


def test_absent_and_unreadable_are_different_answers(tmp_path):
    """Header rule 9. `read_metrics` must not report the same thing for an
    artefact that is missing and one it could not parse.

    The reasons are asserted as LITERAL STRINGS, not against the module's own
    constants: comparing `reason == REASON_UNREADABLE` is satisfied by any
    renaming that collapses the two, including one that makes them equal, so it
    cannot fail in the direction that matters. The emitted JSON is what a reader
    sees, and these are the words it has to carry.
    """
    absent = read_metrics(tmp_path)
    assert absent["metrics"]["final_util"] is NOT_MEASURED
    assert absent["unmeasured"]["final_util"]["reason"] in ("ABSENT",
                                                           "KEY_ABSENT")

    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "density.json").write_text("{not json")
    broken = read_metrics(tmp_path)
    assert broken["unmeasured"]["final_util"]["reason"] == "UNREADABLE"
    assert "density.json" in broken["unmeasured"]["final_util"]["detail"], (
        "an unreadable artefact must name itself; a generic 'nothing carries "
        "this metric' is the answer a MISSING file gets")
    assert (broken["unmeasured"]["final_util"]["reason"]
            != absent["unmeasured"]["final_util"]["reason"]), (
        "'I could not read it' and 'it was not there' must not produce the "
        "same verdict")
    assert REASON_UNREADABLE != REASON_ABSENT != REASON_KEY_ABSENT


def test_a_measured_number_carries_the_artefact_that_declared_it(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "density.json").write_text(
        json.dumps({"core_utilization_pct": 37.5}))
    got = read_metrics(tmp_path)
    assert got["metrics"]["final_util"] == 37.5
    src = got["sources"]["final_util"]
    assert src["path"] == "reports/density.json"
    assert len(src["sha256"]) == 64, (
        "a figure quoted across a boundary carries something that pins WHICH "
        "run tree produced it")


def test_unreadable_declared_channel_file_is_reported_not_swallowed(tmp_path):
    m = tmp_path / "reports" / "metrics"
    m.mkdir(parents=True)
    (m / "21.json").write_text("{broken")
    got = read_metrics(tmp_path)
    assert "reports/metrics/21.json" in got["unreadable_declared_channel"]


def test_declared_channel_is_preferred_over_the_step_report(tmp_path):
    """#1080's channel is the one emitted by the computer of the number."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "density.json").write_text(
        json.dumps({"core_utilization_pct": 11.0}))
    m = tmp_path / "reports" / "metrics"
    m.mkdir()
    (m / "21.json").write_text(
        json.dumps({"21__design__instance__utilization": 22.0}))
    got = read_metrics(tmp_path)
    assert got["metrics"]["final_util"] == 22.0
    assert got["sources"]["final_util"]["channel"] == "step_metrics(#1080)"


def test_die_area_is_reported_but_never_blocks(tmp_path):
    got = read_metrics(tmp_path)
    assert got["metrics"]["die_area"] is NOT_MEASURED
    assert got["unmeasured"]["die_area"]["non_blocking"] is True


def test_die_area_is_derived_from_the_declared_micron_string(tmp_path):
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "pnr_args.json").write_text(json.dumps({"effective_die_um": "203x203"}))
    got = read_metrics(tmp_path)
    assert got["metrics"]["die_area"] == pytest.approx(203 * 203)

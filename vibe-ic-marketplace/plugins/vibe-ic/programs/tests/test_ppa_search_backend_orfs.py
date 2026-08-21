#!/usr/bin/env python3
"""`_ppa/backends/orfs.py` — the lies an ORFS result row tells, refused.

Every constant asserted here was MEASURED against the AutoTuner source at ORFS
`3476215b9` (`tools/AutoTuner/src/autotuner/{utils.py,distributed.py}`), not
assumed. Each test names the one-line wrong implementation it prevents.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import search as S  # noqa: E402
from _ppa.backends import orfs  # noqa: E402

ROUTED = "post_route_extracted"


def _by_name(records):
    return {r["metric"]: r for r in records}


def _parse(row, **kw):
    return _by_name(orfs.parse_row(row, **kw)["records"])


# ---------------------------------------------------------------------------
# TRAP 1 — `step` is a Ray Tune training iteration, not flow progress
# ---------------------------------------------------------------------------
def test_step_never_becomes_a_stage():
    """MUTATION TARGET. Add "step" to `STAGE_KEYS` and this goes red.

    The wrong implementation is `completed_stage = row["step"]`. Measured:
    `distributed.py:163` is `self.step_ += 1` and `distributed.py:253` feeds it
    into the objective — it counts objective reports, not flow progress.
    """
    stage, why = orfs.completed_stage_of({"step": 42, "num_drc": 0})
    assert stage is None
    assert "step" in why and "flow progress" in why


def test_training_iteration_is_refused_the_same_way():
    stage, why = orfs.completed_stage_of({"training_iteration": 9})
    assert stage is None
    assert "iteration counter" in why


def test_a_numeric_value_in_a_stage_key_is_refused_not_stringified():
    """A tuner counter written into a field called `stage` is still a tuner
    counter, and `str(3)` would make it look like a stage name."""
    stage, why = orfs.completed_stage_of({"stage": 3})
    assert stage is None
    assert "not a stage name" in why


def test_an_explicitly_stated_stage_is_used_and_its_source_recorded():
    stage, why = orfs.completed_stage_of({"flow_stage": "cts", "step": 5})
    assert stage == "cts"
    assert "flow_stage" in why


def test_no_stage_anywhere_says_so_rather_than_guessing():
    stage, why = orfs.completed_stage_of({"total_power": 0.1})
    assert stage is None
    assert "states no flow stage" in why


def test_a_row_with_no_stage_yields_no_MEASURED_ordinary_metric():
    """A number without a scope cannot enter a comparison (contract §2), so it
    is NOT_MEASURED rather than MEASURED-with-a-blank-scope."""
    recs = _parse({"step": 3, "worst_slack": -0.1, "design_area": 10.0})
    assert recs["timing.setup.wns_ns"]["status"] == "NOT_MEASURED"
    assert recs["area.design_um2"]["status"] == "NOT_MEASURED"
    assert "step" in recs["area.design_um2"]["reason"]


def test_a_scoped_row_does_yield_MEASURED_metrics():
    """The positive half: without it every NOT_MEASURED assertion here could be
    passing because the parser measures nothing at all."""
    recs = _parse({"worst_slack": -0.1, "design_area": 10.0}, stage=ROUTED)
    assert recs["timing.setup.wns_ns"]["status"] == "MEASURED"
    assert recs["timing.setup.wns_ns"]["value"] == -0.1
    assert recs["area.design_um2"]["value"] == 10.0
    assert recs["area.design_um2"]["scope"]["stage"] == ROUTED


def test_a_caller_stage_and_a_row_stage_that_disagree_are_recorded():
    out = orfs.parse_row({"flow_stage": "cts"}, stage=ROUTED)
    assert out["completed_stage"] == ROUTED
    assert "disagreement is recorded" in out["completed_stage_reason"]


def test_the_stage_the_parser_returns_survives_the_candidate_guard():
    """End-to-end: whatever `parse_row` calls a stage must be assignable, and
    whatever it refuses must stay refused."""
    c = S.Candidate(knobs={}, space_digest="sha256:" + "0" * 64)
    c.set_completed_stage(orfs.parse_row({"flow_stage": "cts"})
                          ["completed_stage"])
    assert c.completed_stage == "cts"

    c2 = S.Candidate(knobs={}, space_digest="sha256:" + "0" * 64)
    c2.set_completed_stage(orfs.parse_row({"step": 11})["completed_stage"])
    assert c2.completed_stage is None


# ---------------------------------------------------------------------------
# TRAP 2 — `num_drc` is detailed-route DRC only
# ---------------------------------------------------------------------------
def test_num_drc_produces_two_records_not_one():
    """MUTATION TARGET. Make `_drc_records` return only the detailed-route
    record and this goes red.

    With one record a manifest holds a row saying `drc: 0` and every reader,
    human and program, takes it for a sign-off result.
    """
    recs = _parse({"num_drc": 0}, stage=ROUTED)
    assert "drc.detailed_route.violations" in recs
    assert "drc.signoff.violations" in recs


def test_the_signoff_record_is_NOT_MEASURED_with_the_reason():
    recs = _parse({"num_drc": 0}, stage=ROUTED)
    signoff = recs["drc.signoff.violations"]
    assert signoff["status"] == "NOT_MEASURED"
    assert "value" not in signoff, \
        "NOT_MEASURED carries a reason, never a value — not even a null"
    for term in ("LVS", "antenna", "IR", "EM", "equivalence"):
        assert term in signoff["reason"]


def test_the_signoff_refusal_cites_where_num_drc_comes_from():
    """MEASURED: `utils.py:427-428` reads `route__drc_errors` from the
    `detailedroute` stage."""
    r = _parse({"num_drc": 3}, stage=ROUTED)["drc.signoff.violations"]
    assert "route__drc_errors" in r["reason"]


def test_a_real_zero_at_a_routed_stage_IS_measured():
    """The positive half of the early-stop rule below. Without it, refusing
    every zero would look identical to refusing the sentinel."""
    r = _parse({"num_drc": 0}, stage=ROUTED)["drc.detailed_route.violations"]
    assert r["status"] == "MEASURED"
    assert r["value"] == 0


def test_the_detailed_route_record_is_scoped_to_detailed_route():
    """Not to whatever stage the row belongs to: the number IS a
    detailed-route number, and scoping it to the row's stage would let it be
    compared with a sign-off count."""
    recs = _parse({"num_drc": 7}, stage=ROUTED)
    assert recs["drc.detailed_route.violations"]["scope"]["stage"] == \
        "detailed_route"
    assert recs["drc.signoff.violations"]["scope"]["stage"] == "signoff"


def test_the_detailed_route_record_warns_against_its_own_misuse():
    note = _parse({"num_drc": 0}, stage=ROUTED)[
        "drc.detailed_route.violations"]["note"]
    assert "not a sign-off verdict" in note
    assert "eligibility term" in note


def test_drc_key_is_not_reachable_through_the_plain_numeric_table():
    """Structural: a future editor adding a metric must not be able to give
    `num_drc` the ordinary treatment by adding one line."""
    assert orfs.DRC_KEY not in orfs.NUMERIC_METRICS
    assert orfs.DERIVED_KEY not in orfs.NUMERIC_METRICS


# ---------------------------------------------------------------------------
# SENTINEL S2 — `num_drc = wirelength = 0` on an early stop (utils.py:418-419)
# ---------------------------------------------------------------------------
def test_a_zero_below_the_routed_stages_is_NOT_MEASURED_not_clean():
    """MUTATION TARGET. Drop the `_ROUTED_STAGES` check in `_drc_records` and
    this goes red.

    MEASURED, `utils.py:418-419`:  `if stop_stage != "finish": num_drc = 0`.
    A trial that stopped at floorplan reports zero violations. And
    `distributed.py:253` is `score = ppa * ... + (gamma * metrics["num_drc"])`,
    so reading that zero as real gives a trial that never routed a ZERO DRC
    PENALTY — a better score than one that routed honestly and found
    violations. The objective rewards early termination; this refusal is what
    stops the reward reaching our manifest.
    """
    r = _parse({"num_drc": 0}, stage="floorplan")[
        "drc.detailed_route.violations"]
    assert r["status"] == "NOT_MEASURED"
    assert "stopped before" in r["reason"]
    assert "value" not in r


def test_a_zero_with_no_stage_at_all_is_NOT_MEASURED():
    """"I cannot tell a real zero from the sentinel" is not "clean"."""
    r = _parse({"num_drc": 0})["drc.detailed_route.violations"]
    assert r["status"] == "NOT_MEASURED"


def test_a_nonzero_count_below_the_routed_stages_is_still_MEASURED():
    """The sentinel is specifically ZERO. Refusing every early-stage count
    would discard real numbers, and this pins that it does not."""
    r = _parse({"num_drc": 5}, stage="floorplan")[
        "drc.detailed_route.violations"]
    assert r["status"] == "MEASURED" and r["value"] == 5


def test_wirelength_carries_the_same_early_stop_zero():
    """`utils.py:419` sets `num_drc = wirelength = 0` in one statement, so the
    same sentinel applies to both."""
    early = _parse({"wirelength": 0}, stage="floorplan")[
        "route.wirelength_um"]
    routed = _parse({"wirelength": 0}, stage=ROUTED)["route.wirelength_um"]
    assert early["status"] == "NOT_MEASURED"
    assert routed["status"] == "MEASURED" and routed["value"] == 0


# ---------------------------------------------------------------------------
# SENTINEL S1 — ERROR_METRIC = 9e99 (utils.py:73)
# ---------------------------------------------------------------------------
def test_the_error_metric_constant_matches_the_measured_source():
    assert orfs.ERROR_METRIC == 9e99


def test_a_failed_trial_marker_is_never_published_as_a_measurement():
    """MUTATION TARGET. Remove the `is_error_metric` guard and this goes red.

    MEASURED: `distributed.py:151-154` returns
    `{METRIC: 9e99, effective_clk_period: 9e99, num_drc: 9e99, die_area: 9e99}`
    for an invalid config, and `distributed.py:250` / `utils.py:82` return four
    of them for a failed run. 9e99 is a number, so it survives every
    is-it-numeric check and lands in a manifest as a measurement.
    """
    recs = _parse({"num_drc": 9e99, "die_area": 9e99,
                   "effective_clk_period": 9e99}, stage=ROUTED)
    for name in ("drc.detailed_route.violations", "area.die_um2",
                 "timing.effective_clock_period_ns"):
        assert recs[name]["status"] == "NOT_MEASURED", name
        assert "ERROR_METRIC" in recs[name]["reason"]
        assert "value" not in recs[name]


def test_is_error_metric_is_a_magnitude_test_not_an_equality_test():
    assert orfs.is_error_metric(9e99)
    assert orfs.is_error_metric(-9e99)
    assert orfs.is_error_metric(1e100)
    assert not orfs.is_error_metric(0)
    assert not orfs.is_error_metric(1234.5)
    assert not orfs.is_error_metric(True), "a bool is not a metric value"


# ---------------------------------------------------------------------------
# SENTINEL S3 — clk_period = 9999999 (utils.py:410)
# ---------------------------------------------------------------------------
def test_no_clock_constraint_is_not_a_9999999ns_clock():
    """MEASURED: `utils.py:410` initialises `clk_period = 9999999` and leaves
    it there when no clock constraint was found."""
    r = _parse({"clk_period": 9999999}, stage=ROUTED)[
        "timing.clock_period_ns"]
    assert r["status"] == "NOT_MEASURED"
    assert "no clock constraint" in r["reason"]


def test_a_real_clock_period_is_still_measured():
    r = _parse({"clk_period": 10.0}, stage=ROUTED)["timing.clock_period_ns"]
    assert r["status"] == "MEASURED" and r["value"] == 10.0


# ---------------------------------------------------------------------------
# SENTINEL S4 — "ERR" string initialisers (utils.py:411-417)
# ---------------------------------------------------------------------------
def test_the_ERR_string_is_INVALID_not_skipped_and_not_zero():
    for key, metric in (("total_power", "power.total_w"),
                        ("design_area", "area.design_um2"),
                        ("worst_slack", "timing.setup.wns_ns")):
        r = _parse({key: "ERR"}, stage=ROUTED)[metric]
        assert r["status"] == "INVALID", key
        assert "value" not in r


def test_a_non_numeric_num_drc_is_INVALID_not_zero():
    recs = _parse({"num_drc": "ERR"}, stage=ROUTED)
    assert recs["drc.detailed_route.violations"]["status"] == "INVALID"
    assert "value" not in recs["drc.detailed_route.violations"]
    assert "drc.signoff.violations" in recs, \
        "the sign-off refusal survives a broken detailed-route number"


def test_a_boolean_is_not_a_number():
    assert _parse({"design_area": True}, stage="synth")[
        "area.design_um2"]["status"] == "INVALID"


# ---------------------------------------------------------------------------
# `worst_slack` IS setup, and hold is never read (utils.py:431-432)
# ---------------------------------------------------------------------------
def test_worst_slack_is_recorded_as_setup_because_that_is_what_orfs_reads():
    """MEASURED, and it CORRECTS my own earlier conservative note. The source
    reads `timing__setup__ws`, so the check is not unknown — it is setup."""
    r = _parse({"worst_slack": 0.4}, stage=ROUTED)["timing.setup.wns_ns"]
    assert r["scope"]["check"] == "setup"
    assert "timing__setup__ws" in r["note"]


def test_hold_is_declared_missing_alongside_every_setup_number():
    """MUTATION TARGET. Drop the hold companion in `_numeric_records` and this
    goes red.

    The AutoTuner never reads a hold number at all. A search optimising
    `worst_slack` is optimising setup alone — the same shape as `num_drc`, one
    term standing in for a vector — so the absence is stated, not implied.
    """
    recs = _parse({"worst_slack": 0.4}, stage=ROUTED)
    hold = recs["timing.hold.wns_ns"]
    assert hold["status"] == "NOT_MEASURED"
    assert hold["scope"]["check"] == "hold"
    assert "never reads a hold number" in hold["reason"]


def test_the_hold_companion_appears_even_when_setup_is_INVALID():
    """A broken setup number does not make hold measured."""
    recs = _parse({"worst_slack": "ERR"}, stage=ROUTED)
    assert recs["timing.setup.wns_ns"]["status"] == "INVALID"
    assert recs["timing.hold.wns_ns"]["status"] == "NOT_MEASURED"


# ---------------------------------------------------------------------------
# `effective_clk_period` is DERIVED (distributed.py:254)
# ---------------------------------------------------------------------------
def test_a_tuner_computed_number_is_DERIVED_and_carries_its_formula():
    """Contract §3: hash the value you PARSED, never one you recomputed; a
    computed number is DERIVED and states its formula. MEASURED:
    `distributed.py:254`, `clk_period - worst_slack`."""
    r = _parse({"effective_clk_period": 9.8}, stage=ROUTED)[
        "timing.effective_clock_period_ns"]
    assert r["status"] == "DERIVED"
    assert r["value"] == 9.8
    assert r["formula"] == "clk_period - worst_slack"


def test_a_derived_number_is_not_MEASURED():
    r = _parse({"effective_clk_period": 9.8}, stage=ROUTED)[
        "timing.effective_clock_period_ns"]
    assert r["status"] != "MEASURED", \
        "DERIVED must not enter a comparison as if it had been parsed"


# ---------------------------------------------------------------------------
# the metric table matches the measured source
# ---------------------------------------------------------------------------
def test_the_numeric_table_is_exactly_the_keys_read_metrics_returns():
    """MEASURED at `utils.py:443-454`. Pinned so an invented key cannot be
    added, and a removed one is noticed."""
    measured = {"clk_period", "worst_slack", "total_power", "core_util",
                "final_util", "design_area", "core_area", "die_area",
                "wirelength", "num_drc"}
    assert set(orfs.NUMERIC_METRICS) | {orfs.DRC_KEY} == measured


# ---------------------------------------------------------------------------
# version honesty and the parse contract
# ---------------------------------------------------------------------------
def test_an_unrecognised_key_is_named_not_dropped():
    """An ORFS field rename must surface as a named unread key, not as a report
    that quietly got shorter."""
    out = orfs.parse_row({"some_new_metric": 1.0, "design_area": 2.0},
                         stage="synth")
    assert out["unmapped_keys"] == ["some_new_metric"]


def test_tuner_bookkeeping_is_ignored_but_listed_separately():
    """An ignored key and an unrecognised key are different facts."""
    out = orfs.parse_row({"step": 1, "trial_id": "abc", "time_total_s": 9.0},
                         stage="synth")
    assert out["unmapped_keys"] == []
    assert set(out["tuner_keys"]) == {"step", "trial_id", "time_total_s"}
    assert out["records"] == [], "no tuner key is a design metric"


def test_every_record_carries_the_parser_and_tool_identity():
    for r in orfs.parse_row({"num_drc": 0, "design_area": 1.0},
                            stage=ROUTED)["records"]:
        assert r["source"]["tool"] == "orfs"
        assert r["source"]["parser"] == orfs.PARSER
        assert r["schema"] == "vibeic.ppa.metric.v1"


def test_the_caller_source_is_preserved_alongside_the_parser_identity():
    r = orfs.parse_row({"design_area": 1.0}, stage="synth",
                       source={"path": "flow/logs/metrics.json"})["records"][0]
    assert r["source"]["path"] == "flow/logs/metrics.json"
    assert r["source"]["parser"] == orfs.PARSER


def test_a_row_that_is_not_an_object_yields_nothing_and_says_why():
    out = orfs.parse_row(["not", "a", "row"])
    assert out["records"] == []
    assert out["completed_stage"] is None
    assert "not an object" in out["completed_stage_reason"]


def test_parse_rows_over_a_non_list_is_empty_never_a_guess():
    assert orfs.parse_rows({"num_drc": 0}) == []
    assert len(orfs.parse_rows([{"num_drc": 0}, {"num_drc": 1}])) == 2


# ---------------------------------------------------------------------------
# the backend holds no policy (PPA_INTERFACES §4)
# ---------------------------------------------------------------------------
def test_the_backend_emits_no_verdict_vocabulary():
    """MUTATION TARGET for the §4 rule. A backend that says PASS/FAIL/ELIGIBLE
    has moved a threshold into a parser, and the next tool added will either
    duplicate it or contradict it. Refusing a SENTINEL is not a threshold: it
    is the parser declining to claim the tool said something it did not say.
    """
    out = orfs.parse_row({"num_drc": 0, "worst_slack": 0.5}, stage=ROUTED)
    for rec in out["records"]:
        assert rec["status"] in ("MEASURED", "NOT_MEASURED", "NOT_APPLICABLE",
                                 "INVALID", "ESTIMATED", "DERIVED")
        assert "verdict" not in rec

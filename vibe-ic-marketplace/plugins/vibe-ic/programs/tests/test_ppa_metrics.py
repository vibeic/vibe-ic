#!/usr/bin/env python3
"""The metric record's shape, and the four ways this system has historically
turned "nobody measured it" into a number.

Every test here is the NEGATIVE of a plausible implementation. Somebody writing
this module without the contract in front of them would reach for `value: 0` as
a default, for `value: null` as an absence, for the metric NAME as the identity
of a measurement, and for "render the rows I have" as a report. Each of those is
a defect that reads as a clean result, which is why each one gets a test that
goes red rather than a comment saying not to.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import metrics as M  # noqa: E402

SCOPE_SYNTH = {"stage": "synthesis"}
SCOPE_ROUTE = {"stage": "post_route_extracted", "process": "ss",
               "voltage_v": 1.62, "temperature_c": 125}
SRC = {"path": "phase3/stage3/sta/sta.rpt", "tool": "opensta"}


def a_measured(metric="timing.setup.wns_ns", value=-0.124, unit="ns",
               scope=None, source=None):
    return M.measured(metric, value, unit, scope or dict(SCOPE_ROUTE),
                      source or dict(SRC))


def raw_measured(**over):
    """A MEASURED record assembled WITHOUT the constructor.

    The constructors validate, so they cannot be used to build the malformed
    records `validate` has to catch -- and a test that only ever exercises
    records the constructor produced would never see a document written by
    another producer, which is the only kind this module will actually be fed.
    """
    rec = {"schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
           "status": M.MEASURED, "value": -0.124, "unit": "ns",
           "scope": dict(SCOPE_ROUTE), "source": dict(SRC)}
    rec.update(over)
    return rec


# ---------------------------------------------------------------- positive

def test_a_measured_record_is_the_shape_the_contract_froze():
    """PPA_INTERFACES §2, key for key."""
    rec = a_measured()
    assert rec["schema"] == "vibeic.ppa.metric.v1"
    assert rec["status"] == M.MEASURED
    assert rec["value"] == -0.124
    assert rec["unit"] == "ns"
    assert rec["scope"]["stage"] == "post_route_extracted"
    assert rec["source"]["tool"] == "opensta"
    assert M.validate(rec) == []
    assert M.is_comparable(rec)


def test_every_constructor_produces_a_record_that_validates():
    for rec in (
        a_measured(),
        M.not_measured("power.total_mw", "no VCD was produced", SCOPE_ROUTE),
        M.not_applicable("power.total_mw", "the block has no switching logic",
                         SCOPE_SYNTH),
        M.invalid("area.die_um2", "the report ended mid-table", SCOPE_SYNTH),
        M.estimated("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH,
                    basis="cell-count regression"),
        M.derived("power.density_mw", 3.0, "mW", SCOPE_ROUTE,
                  formula="total_mw / area_mm2", inputs=["power.total_mw"]),
    ):
        assert M.validate(rec) == [], rec


# ---------------------- negative: 0, -1 and "" never mean "not measured"

@pytest.mark.parametrize("sentinel", [0, 0.0, -1, -1.0, ""])
def test_a_non_measurement_may_not_carry_a_value_at_all(sentinel):
    """THE FOURTH INVARIANT, and the reason it is a shape rule and not advice.

    Every one of these sentinels is a legitimate reading of the metric it would
    sit on: 0 slack is "exactly met", 0 mW is "draws nothing", -1 is a
    violation somebody would try to fix. There is no value of `value` that a
    NOT_MEASURED row can carry without being readable as a measurement, so the
    key is refused outright.
    """
    rec = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    rec["value"] = sentinel
    codes = [c for c, _ in M.validate(rec)]
    assert "VALUE_ON_A_NON_MEASUREMENT" in codes


def test_value_null_is_not_an_absence_either():
    """`null` is a PRESENT key. It survives `.get("value")`, it survives
    `"value" in rec`, and it re-enters arithmetic the first time somebody
    writes `rec.get("value") or 0` — which is the same defect with an extra
    step, and harder to see."""
    rec = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    rec["value"] = None
    assert "VALUE_ON_A_NON_MEASUREMENT" in [c for c, _ in M.validate(rec)]


def test_a_missing_number_is_a_record_with_a_reason():
    rec = M.not_measured("power.total_mw", "no VCD was produced", SCOPE_ROUTE)
    assert "value" not in rec
    assert rec["reason"]
    assert not M.is_comparable(rec)


def test_a_non_measurement_without_a_reason_is_refused():
    """A row saying NOT_MEASURED and nothing else is indistinguishable from a
    row nobody thought about."""
    rec = M.not_measured("power.total_mw", "x", SCOPE_ROUTE)
    rec["reason"] = "   "
    assert "NO_REASON" in [c for c, _ in M.validate(rec)]


def test_the_empty_string_is_not_a_unit():
    """Two empty units compare EQUAL, so two numbers in different units pass a
    unit check."""
    rec = a_measured()
    rec["unit"] = ""
    assert "NO_UNIT" in [c for c, _ in M.validate(rec)]


def test_an_empty_scope_field_is_the_same_sentinel_one_level_in():
    rec = raw_measured(scope={"stage": "post_route_extracted", "process": ""})
    assert "SCOPE_SENTINEL" in [c for c, _ in M.validate(rec)]
    with pytest.raises(M.MetricError):
        M.measured("timing.setup.wns_ns", -0.1, "ns",
                   {"stage": "post_route_extracted", "process": ""}, SRC)


# ---------------------------------------------------- negative: status enum

def test_an_unrecognised_status_is_refused_not_assumed_safe():
    rec = a_measured()
    rec["status"] = "PROBABLY_FINE"
    assert "BAD_STATUS" in [c for c, _ in M.validate(rec)]


def test_estimated_never_enters_a_comparison():
    """§2: 'ESTIMATED — never in final PPA'."""
    rec = M.estimated("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH,
                      basis="cell-count regression")
    assert M.validate(rec) == []
    assert M.ESTIMATED not in M.COMPARABLE_STATUSES
    assert not M.is_comparable(rec)


def test_derived_must_state_its_formula():
    rec = M.derived("power.density_mw", 3.0, "mW", SCOPE_ROUTE,
                    formula="a/b")
    rec.pop("formula")
    assert "NO_FORMULA" in [c for c, _ in M.validate(rec)]


def test_a_measured_number_must_name_its_source():
    rec = a_measured()
    rec.pop("source")
    assert "NO_SOURCE" in [c for c, _ in M.validate(rec)]


def test_nan_and_infinity_are_not_metrics():
    for bad in (float("nan"), float("inf"), float("-inf")):
        rec = dict(a_measured())
        rec["value"] = bad
        assert "VALUE_NOT_FINITE" in [c for c, _ in M.validate(rec)]


def test_true_is_not_a_number():
    """`bool` is an `int` in Python, so a naive isinstance check accepts it and
    `True + 1 == 2` never complains."""
    rec = dict(a_measured())
    rec["value"] = True
    assert "VALUE_NOT_A_NUMBER" in [c for c, _ in M.validate(rec)]


def test_a_unit_suffix_in_the_name_must_agree_with_the_unit_field():
    """`area.die_um2` recorded as mm^2 is six orders of magnitude, and every
    consumer downstream trusts `unit` over the name."""
    rec = raw_measured(metric="area.die_um2", value=12000.0, unit="mm^2",
                       scope=dict(SCOPE_SYNTH))
    assert "UNIT_CONTRADICTS_NAME" in [c for c, _ in M.validate(rec)]


def test_a_unit_that_contradicts_the_metric_name_is_refused_at_construction():
    with pytest.raises(M.MetricError) as exc:
        M.measured("area.die_um2", 12000.0, "mm^2", SCOPE_SYNTH, SRC)
    assert exc.value.code == "UNIT_CONTRADICTS_NAME"


def test_a_name_with_no_unit_suffix_makes_no_unit_claim():
    """The cross-check must not become a requirement that every metric name
    encode its unit — the taxonomy is not this module's to define."""
    assert M.unit_suffix_of("area.utilisation") is None
    rec = M.measured("area.utilisation", 0.62, "1", SCOPE_SYNTH, SRC)
    assert M.validate(rec) == []


# ------------------------------------- identity: scope, not the metric name

def test_two_records_with_the_same_metric_and_different_scope_are_two_facts():
    """The load-bearing one. Synthesis area and post-route area both say
    `area.die_um2`, and neither number bounds the other."""
    synth = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    route = M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC)
    assert synth["metric"] == route["metric"]
    assert M.record_key(synth) != M.record_key(route)


def test_scope_identity_does_not_depend_on_key_order():
    one = {"stage": "post_route_extracted", "process": "ss"}
    two = {"process": "ss", "stage": "post_route_extracted"}
    assert M.scope_digest(one) == M.scope_digest(two)


def test_scope_identity_uses_the_one_serializer():
    """Never a hand-rolled json.dumps: two authors would disagree about what a
    scope IS and every comparison built on the difference would be silent."""
    scope = {"stage": "synthesis", "mode": "functional"}
    assert M.scope_digest(scope) == cj.digest_of(scope)


def test_a_record_with_no_scope_can_be_compared_to_anything():
    rec = dict(a_measured())
    rec["scope"] = {}
    assert "NO_SCOPE" in [c for c, _ in M.validate(rec)]


def test_scope_must_name_its_stage():
    """Without it a synthesis number and a post-route number are one fact."""
    rec = raw_measured(scope={"process": "ss"})
    assert "SCOPE_INCOMPLETE" in [c for c, _ in M.validate(rec)]


# ------------------------------------------------------------------- index

def test_the_index_refuses_two_records_claiming_to_be_one_fact():
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    with pytest.raises(M.MetricError) as exc:
        idx.add(M.measured("area.die_um2", 15400.0, "um^2", SCOPE_SYNTH, SRC))
    assert exc.value.code == "CONFLICTING_RECORD"


def test_an_identical_duplicate_is_refused_and_not_silently_deduplicated():
    """Silently deduplicating makes a set's size depend on how many times a
    producer ran, which is a denominator nobody can reproduce."""
    idx = M.MetricIndex()
    rec = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    idx.add(rec)
    with pytest.raises(M.MetricError) as exc:
        idx.add(dict(rec))
    assert exc.value.code == "DUPLICATE_RECORD"


def test_the_same_metric_under_two_scopes_coexists():
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    idx.add(M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC))
    assert len(idx) == 2
    assert len(idx.by_metric("area.die_um2")) == 2
    assert idx.get("area.die_um2", SCOPE_SYNTH)["value"] == 12000.0


def test_the_index_digest_is_independent_of_insertion_order():
    def build(order):
        idx = M.MetricIndex()
        for rec in order:
            idx.add(rec)
        return idx.digest()
    a = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    b = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)
    assert build([a, b]) == build([b, a])


def test_the_index_refuses_an_invalid_record_at_the_door():
    idx = M.MetricIndex()
    bad = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    bad["value"] = 0
    with pytest.raises(M.MetricError):
        idx.add(bad)


# ---------------------------------------------------------------- coverage

def _idx(*recs):
    idx = M.MetricIndex()
    for rec in recs:
        idx.add(rec)
    return idx


EXPECT_THREE = [
    {"metric": "area.die_um2", "scope": SCOPE_SYNTH},
    {"metric": "power.total_mw", "scope": SCOPE_ROUTE},
    {"metric": "timing.setup.wns_ns", "scope": SCOPE_ROUTE},
]


def test_coverage_positive_all_three_measured():
    idx = _idx(
        M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
        M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC),
        M.measured("timing.setup.wns_ns", -0.124, "ns", SCOPE_ROUTE, SRC),
    )
    cov = M.coverage(idx, EXPECT_THREE)
    assert cov.expected == 3
    assert cov.count(M.COVERED) == 3
    assert cov.complete
    assert M.coverage_rc(cov) == 0


def test_coverage_NEGATIVE_an_omitted_row_is_caught():
    """THE ONE THIS LANE EXISTS FOR.

    The bundle carries two perfectly good records. Nothing in it is wrong.
    `timing.setup.wns_ns` was owed and is simply not there, and without the
    declared denominator there is nothing to notice — the report would render
    two rows and read as two facts.
    """
    idx = _idx(
        M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
        M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC),
    )
    cov = M.coverage(idx, EXPECT_THREE)
    assert [r.metric for r in cov.absent] == ["timing.setup.wns_ns"]
    assert cov.worst == M.ABSENT
    assert M.coverage_rc(cov) == 1


def test_the_report_prints_the_absent_row_literally():
    """§2: 'A report prints the literal NOT_MEASURED row; it does not omit
    it.' Rendering only rows that have values is how a coverage gap becomes an
    implied zero in the reader's head."""
    idx = _idx(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
               M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE))
    text = M.format_coverage(M.coverage(idx, EXPECT_THREE))
    assert "timing.setup.wns_ns" in text
    assert "ABSENT" in text
    assert "power.total_mw" in text
    assert "no VCD" in text


def test_a_declared_absence_is_undetermined_and_an_omission_is_a_finding():
    """The whole distinction, in one test. Same hole; one is visible."""
    declared = _idx(
        M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
        M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC),
        M.not_measured("timing.setup.wns_ns", "STA did not run", SCOPE_ROUTE),
    )
    omitted = _idx(
        M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
        M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC),
    )
    assert M.coverage_rc(M.coverage(declared, EXPECT_THREE)) == 2
    assert M.coverage_rc(M.coverage(omitted, EXPECT_THREE)) == 1


def test_a_measurement_at_the_wrong_scope_does_not_cover_the_expectation():
    """A post-route number does not satisfy an expectation of a synthesis
    number, however good it is."""
    idx = _idx(M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC))
    cov = M.coverage(idx, [{"metric": "area.die_um2", "scope": SCOPE_SYNTH}])
    assert cov.absent[0].metric == "area.die_um2"
    assert len(cov.unexpected) == 1


def test_an_estimate_does_not_cover_a_measurement():
    idx = _idx(M.estimated("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH,
                           basis="regression"))
    cov = M.coverage(idx, [{"metric": "area.die_um2", "scope": SCOPE_SYNTH}])
    assert cov.count(M.UNUSABLE) == 1
    assert M.coverage_rc(cov) == 1


def test_coverage_refuses_an_empty_expectation_set():
    """Computed from the records alone it can only ever be 100%."""
    with pytest.raises(M.MetricError) as exc:
        M.coverage(_idx(), [])
    assert exc.value.code == "NO_EXPECTATION_SET"


def test_an_expectation_without_a_scope_is_refused():
    with pytest.raises(M.MetricError) as exc:
        M.coverage(_idx(), [{"metric": "area.die_um2"}])
    assert exc.value.code == "BAD_EXPECTATION"


def test_coverage_states_its_denominator():
    idx = _idx(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    text = M.format_coverage(M.coverage(idx, EXPECT_THREE))
    assert "3 expected" in text


def test_adding_a_record_can_never_subtract_a_finding():
    """The aggregator trap this repo already paid for once, in
    `ppa_head_to_head_check`: rc 2 is the LARGER integer and the WEAKER
    verdict, so `max()` over exit codes promotes a refusal to a pass."""
    absent_only = M.coverage(
        _idx(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)),
        EXPECT_THREE)
    assert M.coverage_rc(absent_only) == 1
    plus_a_declared_absence = M.coverage(
        _idx(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
             M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)),
        EXPECT_THREE)
    assert M.coverage_rc(plus_a_declared_absence) == 1


# --------------------------------------------------------------- compare

def test_compare_refuses_across_differing_scope():
    """THE REFUSAL. Same metric, both valid, both real — and the more
    favourable one is the one somebody would rather quote."""
    synth = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    route = M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC)
    out = M.compare(synth, route)
    assert out["verdict"] == M.CMP_DIFFERENT_SCOPE
    assert "winner" not in out
    assert any(d["field"] == "stage" for d in out["scope_diff"])


def test_compare_across_one_differing_corner_field_is_still_a_refusal():
    hot = M.measured("timing.setup.wns_ns", -0.124, "ns",
                     dict(SCOPE_ROUTE), SRC)
    cool = dict(SCOPE_ROUTE)
    cool["temperature_c"] = 25
    out = M.compare(hot, M.measured("timing.setup.wns_ns", 0.31, "ns",
                                    cool, SRC))
    assert out["verdict"] == M.CMP_DIFFERENT_SCOPE


def test_compare_positive_same_scope():
    a = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    b = M.measured("area.die_um2", 11000.0, "um^2", SCOPE_SYNTH,
                   {"path": "b.rpt", "tool": "yosys"})
    out = M.compare(a, b, better="lower")
    assert out["verdict"] == M.CMP_OK
    assert out["winner"] == "b"
    assert out["delta_b_minus_a"] == -1000.0


def test_compare_names_no_winner_without_a_declared_direction():
    """'lower is better' is wrong for slack and for frequency, and which way is
    better is domain policy, not the shape module's."""
    a = M.measured("timing.setup.wns_ns", -0.1, "ns", SCOPE_ROUTE, SRC)
    b = M.measured("timing.setup.wns_ns", 0.2, "ns", SCOPE_ROUTE,
                   {"path": "b.rpt", "tool": "opensta"})
    out = M.compare(a, b)
    assert out["verdict"] == M.CMP_OK
    assert out["winner"] is None


def test_missing_is_not_winning():
    a = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)
    b = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    out = M.compare(a, b, better="lower")
    assert out["verdict"] == M.CMP_NOT_MEASURED
    assert out.get("winner") is None


def test_compare_refuses_a_unit_mismatch_at_the_same_scope():
    """Both records are individually valid -- the metric name carries no unit
    suffix, so neither one contradicts itself. The mismatch is only visible
    when the two are put side by side, and comparing the numbers would hide
    which of the two is wrong."""
    a = M.measured("power.total", 3.0, "mW", SCOPE_ROUTE, SRC)
    b = M.measured("power.total", 3.0, "W", SCOPE_ROUTE,
                   {"path": "b.rpt", "tool": "openroad"})
    assert M.validate(a) == [] and M.validate(b) == []
    assert M.compare(a, b)["verdict"] == M.CMP_UNIT_MISMATCH


def test_compare_refuses_two_different_quantities():
    a = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)
    b = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_ROUTE, SRC)
    assert M.compare(a, b)["verdict"] == M.CMP_DIFFERENT_METRIC


def test_compare_refuses_an_invalid_record_before_looking_at_numbers():
    a = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)
    b = dict(a)
    b.pop("source")
    assert M.compare(a, b)["verdict"] == M.CMP_INVALID


# ---------------------------------------------------------------- bundle

def test_a_bundle_carries_its_denominator_with_it():
    idx = _idx(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    doc = M.bundle(idx, expected=EXPECT_THREE)
    assert doc["schema"] == M.BUNDLE_SCHEMA_ID
    assert doc["records_digest"] == idx.digest()
    assert len(doc["expected"]) == 3
    assert M.validate_bundle(doc) == []


def test_an_unreadable_document_is_not_an_empty_one():
    """Rule 9. Returning `[]` for an unrecognised document makes 'I could not
    read it' and 'I read it and it was empty' identical to every caller."""
    with pytest.raises(M.MetricError) as exc:
        M.records_from_document({"schema": "something.else.v1"})
    assert exc.value.code == "UNRECOGNISED_DOCUMENT"


def test_a_bundle_with_no_records_list_is_malformed_not_empty():
    with pytest.raises(M.MetricError) as exc:
        M.records_from_document({"schema": M.BUNDLE_SCHEMA_ID})
    assert exc.value.code == "NO_RECORDS"


def test_records_from_document_accepts_the_three_producer_shapes():
    rec = a_measured()
    assert M.records_from_document(rec) == [rec]
    assert M.records_from_document([rec]) == [rec]
    idx = _idx(rec)
    assert M.records_from_document(M.bundle(idx)) == [rec]


def test_the_refusal_NAMES_the_sentinel_it_found():
    """"0 is not a measurement" and "the empty string is not a unit" are
    different sentences to whoever has to fix the producer, and a generic
    "must not carry a value" makes them one."""
    rec = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    rec["value"] = 0
    msg = dict(M.validate(rec))["VALUE_ON_A_NON_MEASUREMENT"]
    assert "sentinel" in msg and "6.1" in msg
    rec["value"] = 42.5
    msg = dict(M.validate(rec))["VALUE_ON_A_NON_MEASUREMENT"]
    assert "sentinel" not in msg, (
        "42.5 is not a sentinel; calling it one would teach a reader that the "
        "rule is about three magic numbers rather than about the key existing")


def test_the_whole_bundle_document_has_one_identity_whatever_the_read_order():
    """`records_digest` was already order-independent while the `records` array
    it describes was not, so two assemblers reading the same files in different
    directory order produced two documents with the same digest inside and
    different bytes outside. Two artefacts describing one set must not disagree
    about whether order matters."""
    a = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    b = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)
    one, two = M.bundle(_idx(a, b)), M.bundle(_idx(b, a))
    assert cj.dumps(one) == cj.dumps(two)
    assert one["records_digest"] == two["records_digest"]

#!/usr/bin/env python3
"""E2E finding F-4 / F-5: the producers and the canonical consumer, AS A PAIR.

WHY THE EXISTING SUITES CANNOT REACH THIS
=========================================
`_ppa/timing.py`, `_ppa/power.py` and `_ppa/area.py` each PRODUCE records
carrying `"schema": "vibeic.ppa.metric.v1"`. `_ppa/metrics.py` is the module
that DEFINES that shape and the only one entitled to say whether a record is
one. Each lane tested itself:

    test_ppa_power.py    builds a power record and checks power's own rules
    test_ppa_timing.py   builds a timing row and checks timing's own rules
    test_ppa_area.py     builds an area record and checks area's own rules
    test_ppa_metrics.py  builds a record WITH `metrics.measured()` and validates it

Every one of those passes. Not one of them ever hands a producer's output to
`metrics.validate`, so the only property that makes the shared schema string
mean anything -- that the producers emit what the consumer accepts -- was
tested by nobody. That is F-4's shape exactly, and it is why the defect
survived fourteen lanes of green tests.

WHAT IT FINDS, MEASURED ON `e36d81c0a` (v1.11.33)
=================================================
    power    48 of 48 records built from power's OWN shipped fixtures are
             REFUSED: `SCOPE_SENTINEL: scope.liberty is None`. `metric_records`
             writes `"liberty": report.get("liberty")` into every scope, and a
             report that does not name a liberty file puts None there.
             `metrics.validate` refuses a None scope field, and it is right to:
             two records with `liberty: None` compare EQUAL, so two runs
             against different libraries silently become the same measurement.

    timing   `MetricIndex.add` RAISES on a row from a real STA report:
             `scope.stage is required` plus four SCOPE_SENTINEL. So the index
             every consumer builds cannot hold a timing row at all.

    area     3 of 14 area metrics, and that is F-5: the unit the area lane
             DECLARES contradicts the unit the metric NAME requires --
             `area.proxy.cell_count` says `cells` where the name says `count`.
             Each module was self-consistent; the pair was not.

WHAT THIS FILE ASSERTS, AND WHAT IT DELIBERATELY DOES NOT
=========================================================
It does not assert which side is right. Whether `liberty: None` should be
dropped from scope or whether `validate` should permit a declared-absent scope
field is the record-envelope lane's decision, and either resolution makes these
tests green. What it asserts is that THE TWO AGREE -- because a producer and a
consumer that disagree about the shared shape mean the shared shape is not
shared, and every hash, index and comparison built on it is describing
something the other half would refuse.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

from _ppa import area as A          # noqa: E402
from _ppa import metrics as M       # noqa: E402
from _ppa import power as P         # noqa: E402
from _ppa import timing as T        # noqa: E402

FIX = _TESTS / "fixtures" / "ppa"

# A source block good enough that nothing below fails for a provenance reason.
SRC = {"path": "artefact.rpt", "sha256": "sha256:" + "ab" * 32,
       "tool": "opensta", "parser": "probe.py",
       "parser_sha256": "sha256:" + "cd" * 32}


# ---------------------------------------------------------------------------
# CROSS-OWNERSHIP PINS -- F-4 and F-5 live in the record-envelope lane's files
# ---------------------------------------------------------------------------
# `_ppa/metrics.py`, `_ppa/area.py`, `_ppa/power.py` and `_ppa/timing.py` all
# belong to the record-envelopes/units lane, which is working these findings
# now. PPA_INTERFACES §6 says a change needed in another lane's file is written
# down rather than made, so every arm below that is red today is pinned
# `xfail(strict=True)` and handed over in RESULT.md.
#
# STRICT is the whole point: the moment that lane lands its fix, an xpass turns
# this file RED and the pin must be deleted. A pin that survives its bug is a
# second bug, and it is the one that hides the first.
#
# Measured on `e36d81c0a` (v1.11.33), by this file:
#     F-5  3 of 14 area metrics declare a unit the metric name refuses
#     F-4  the same 3 area records are refused by metrics.validate
#     F-4  48 of 48 power records from power's own fixtures are refused
#     F-4  every timing row is refused, and MetricIndex.add raises on one
# F-5 IS FIXED AND THE SET IS EMPTY. It held the three `*_count` area metrics
# that declared 'cells' / 'wires' / 'wire_bits' where the metric NAME requires
# 'count'. `_ppa/area.py` — the record lane's file, handed over in RESULT.md
# per PPA_INTERFACES §6 — now declares 'count' for all three, and all six
# pinned arms xpassed. This file's own instruction at that point is to delete
# the pin: "a pin that survives its bug is a second bug, and it is the one
# that hides the first".
#
# THE SET IS KEPT, EMPTY, RATHER THAN THE BRANCH BEING DELETED, because the
# next disagreement of this shape is named by adding one string here. It is
# checked against the taxonomy below so it can never rot into a list of names
# that no longer exist.
_F5_AREA_UNIT_DISAGREES: set = set()


def _pin(finding, detail):
    return pytest.mark.xfail(
        strict=True,
        reason=f"{finding}: {detail}. The fix is in the record-envelope "
               f"lane's file (PPA_INTERFACES §6); handed to the lander in "
               f"RESULT.md rather than edited here. Strict: this goes red the "
               f"moment the fix lands.")


def _fmt(errs):
    return "; ".join(f"{c}: {m}" for c, m in errs)


# ---------------------------------------------------------------------------
# the shared schema string -- the thing that makes the pairing a contract
# ---------------------------------------------------------------------------
def test_every_producer_claims_the_consumers_schema():
    """If these ever diverge, everything below is testing two shapes and the
    disagreement it finds is not a defect but a category error."""
    assert A.SCHEMA == M.SCHEMA_ID
    assert T.SCHEMA == M.SCHEMA_ID
    assert P.SCHEMA_METRIC == M.SCHEMA_ID


# ---------------------------------------------------------------------------
# F-5 -- the unit the producer DECLARES vs the unit the NAME requires
# ---------------------------------------------------------------------------
# The whole taxonomy, read from the area lane's own table rather than from a
# list here -- a metric added tomorrow is covered without editing this file,
# and a metric REMOVED cannot silently shrink the denominator unnoticed
# because the count is asserted below.
AREA_METRICS = sorted(A.AREA_METRICS)


def test_the_area_metric_taxonomy_is_not_empty():
    """The denominator for the parametrized arm below. An empty taxonomy makes
    every unit check vacuously green."""
    assert len(AREA_METRICS) >= 14, AREA_METRICS


def test_the_f5_pin_names_only_metrics_that_exist():
    """A pin list that outlives its metric names stops pinning anything and
    nothing says so. Empty is the expected state now that F-5 has landed."""
    unknown = _F5_AREA_UNIT_DISAGREES - set(AREA_METRICS)
    assert not unknown, (
        f"_F5_AREA_UNIT_DISAGREES names metrics the area taxonomy no longer "
        f"has, so those pins can never fire: {sorted(unknown)}")


@pytest.mark.parametrize("metric", AREA_METRICS)
def test_area_declared_unit_matches_the_unit_the_name_requires(metric, request):
    """F-5. `metrics.unit_suffix_of` derives a REQUIRED unit from the metric
    name; `area.unit_of` declares what the area lane will actually emit. Where
    they differ, every record the area lane produces for that metric is
    refused by the consumer -- which is what happens today for the three
    `*_count` metrics.
    """
    if metric in _F5_AREA_UNIT_DISAGREES:
        request.node.add_marker(_pin(
            "F-5", f"area declares {A.unit_of(metric)!r} for {metric} where "
                   f"the metric name requires {M.unit_suffix_of(metric)!r}"))
    declared = A.unit_of(metric)
    required = M.unit_suffix_of(metric)
    if required is None:
        pytest.skip(f"{metric} has no unit suffix the name constrains")
    assert declared == required, (
        f"F-5: area declares unit {declared!r} for {metric!r} but the metric "
        f"NAME requires {required!r}. A record carrying the declared unit is "
        f"refused by metrics.validate with UNIT_CONTRADICTS_NAME, so the area "
        f"lane cannot emit this metric into the canonical index at all.")


@pytest.mark.parametrize("metric", AREA_METRICS)
def test_area_record_is_accepted_by_the_canonical_consumer(metric, request):
    """F-4 for the area producer: build it the way the lane builds it, then
    hand it to the module that owns the shape."""
    if metric in _F5_AREA_UNIT_DISAGREES:
        request.node.add_marker(_pin(
            "F-4", f"the F-5 unit disagreement makes every {metric} record "
                   f"UNIT_CONTRADICTS_NAME to the canonical consumer"))
    rec = A.area_record(metric, "MEASURED", value=1.0,
                        scope={"stage": "post_route_extracted"}, source=SRC)
    errs = M.validate(rec)
    assert not errs, (
        f"F-4: area.area_record({metric!r}) emits a record the canonical "
        f"consumer REFUSES: {_fmt(errs)}")


# ---------------------------------------------------------------------------
# F-4 -- POWER, driven from the power lane's OWN shipped fixtures
# ---------------------------------------------------------------------------
POWER_REPORTS = sorted((FIX / "power" / "activity_basis_pair").glob("*.rpt"))


def test_the_power_fixture_pair_is_present():
    """Absence here would turn the arm below into a green loop over nothing."""
    assert len(POWER_REPORTS) == 2, [p.name for p in POWER_REPORTS]


@pytest.mark.parametrize("rpt", POWER_REPORTS, ids=lambda p: p.name)
def test_power_records_are_accepted_by_the_canonical_consumer(rpt):
    """F-4. Measured on `e36d81c0a`: 24 records per fixture, 24 refused, both
    fixtures. `metric_records` put `liberty: None` and `tool: None` into every
    scope, and `validate` refuses a None scope field.

    THE PIN IS GONE BECAUSE THE DISAGREEMENT IS. The producer took the first of
    the two resolutions this docstring named: `_ppa/power.py` reads the
    provenance block in BOTH spellings the flow ships, so these artefacts --
    which STATE their liberty and their tool -- establish both; and a condition
    an artefact does not state is now OMITTED from scope with its reason in
    `provenance.scope_gaps`, never nulled. The consumer was not touched: a
    MEASURED record off an artefact that names no tool is still refused
    SOURCE_UNTOOLED.
    """
    report = P.read_power_report(rpt)
    assert report is not None, f"{rpt.name} did not parse"
    recs = P.metric_records(report, stage="post_route_extracted")
    assert recs, f"{rpt.name} produced no records; nothing was checked"
    refused = [(r["metric"], M.validate(r)) for r in recs]
    refused = [(m, e) for m, e in refused if e]
    assert not refused, (
        f"F-4: {len(refused)} of {len(recs)} power records from "
        f"{rpt.name} are REFUSED by metrics.validate. First: "
        f"{refused[0][0]} -> {_fmt(refused[0][1])}")


# ---------------------------------------------------------------------------
# F-4 -- TIMING, driven from a real STA report
# ---------------------------------------------------------------------------
STA_VIEWS = sorted((FIX / "sta" / "known_answer" / "views").glob("*.rpt"))


def test_the_sta_view_fixtures_are_present():
    assert len(STA_VIEWS) == 2, [p.name for p in STA_VIEWS]


def _rows_from_a_real_tree(tmp_path):
    """Lay the shipped STA reports out where `timing.discover_reports` looks.

    The fixture tree stores them under `views/`, which is not one of
    `timing._STA_DIRS`, so calling `timing_rows` on the fixture directory
    itself opens ZERO artefacts and returns an empty list -- which would make
    every assertion below vacuously true. This is the trap the vacuous arm
    exists to catch, and it is why the row count is asserted first.
    """
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True)
    for i, v in enumerate(STA_VIEWS):
        (d / f"sta_view_{i}.rpt").write_bytes(v.read_bytes())
    return T.timing_rows(tmp_path)


@_pin("F-4", "timing rows carry no `scope.stage` and four None scope fields; "
             "every row is refused by metrics.validate")
def test_timing_rows_are_accepted_by_the_canonical_consumer(tmp_path):
    """F-4 for the timing producer. Measured: `MetricIndex.add` RAISES."""
    rows, notes = _rows_from_a_real_tree(tmp_path)
    assert rows, (
        f"no timing rows were produced, so nothing was checked. notes={notes}")
    refused = [(r["metric"], M.validate(r)) for r in rows]
    refused = [(m, e) for m, e in refused if e]
    assert not refused, (
        f"F-4: {len(refused)} of {len(rows)} timing rows are REFUSED by "
        f"metrics.validate. First: {refused[0][0]} -> {_fmt(refused[0][1])}")


@_pin("F-4", "MetricIndex.add raises on a timing row from a real STA report")
def test_a_timing_row_can_enter_the_canonical_index(tmp_path):
    """The consequence, stated as the thing a consumer actually does.

    `MetricIndex` is what every coverage count, comparison and report is built
    from. A producer whose rows cannot enter it is not producing canonical
    records, whatever their `schema` key says.
    """
    rows, notes = _rows_from_a_real_tree(tmp_path)
    assert rows, f"no rows; nothing was checked. notes={notes}"
    idx = M.MetricIndex()
    try:
        for r in rows:
            idx.add(r)
    except M.MetricError as exc:
        pytest.fail(
            f"F-4: MetricIndex.add REJECTED a timing row from a real STA "
            f"report: {exc}. Every coverage count and every comparison is "
            f"built on this index, so the timing lane's output cannot reach "
            f"any of them.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

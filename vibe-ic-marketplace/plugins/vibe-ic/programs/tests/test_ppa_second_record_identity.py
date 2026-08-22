#!/usr/bin/env python3
"""`docs/PPA_INTERFACES.md` §2.1 — what a SECOND record under one
`(metric, scope)` identity means.

THE DEFECT THIS FILE EXISTS FOR
===============================
Every second record for an identity was refused as `CONFLICTING_RECORD` with
the message "two numbers claiming to be the same fact", INCLUDING when the two
numbers were equal. Measured 2026-08-21 driving `_ppa/backends/openroad.py`
over a real PnR directory: `route.drc.violation.count` read `0` from
`openroad.log` and `0` from `openroad.metrics.json`, and two artefacts
CORROBORATING one fact took down the entire record set -- so
`ppa_report_gen.py` returned rc=1 and no report could be generated from a
default run at all.

Agreement is not a conflict. Disagreement still is, and it must stay detected:
the backend emits BOTH readings on purpose and settling which is right is a
declared authority decision, never an index's.

    positive   two artefacts that agree -> one record, corroboration recorded
    negative   two artefacts that disagree -> refused, and the refusal names both
    vacuous    a record whose source states no hash cannot claim SAME_ARTEFACT
    mutation   revert `_states_the_same_fact` and the corroboration tests go red

chip-AGNOSTIC: synthetic records and one synthetic tool log.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from _ppa import metrics as M                    # noqa: E402

SCOPE = {"stage": "detailed_route", "tool": "openroad"}


def src(path, sha=None, **kw):
    out = {"path": path, "tool": "openroad"}
    if sha is not None:
        out["sha256"] = "sha256:" + sha * 64
    out.update(kw)
    return out


def rec(value, path, sha=None, unit="um", status=None, metric="route.wirelength.um"):
    if status in (None, M.MEASURED):
        return M.measured(metric, value, unit, SCOPE, src(path, sha))
    # Built directly: `M.not_measured` fixes `source=None`, and this test needs
    # a NOT_MEASURED row that names the artefact it failed to read it from.
    out = {"schema": M.SCHEMA_ID, "metric": metric, "status": M.NOT_MEASURED,
           "unit": unit, "scope": dict(SCOPE), "source": src(path, sha),
           "reason": "the artefact printed no such line"}
    M.validate_or_raise(out)
    return out


# ───────────────────────────── positive ─────────────────────────────────────

def test_two_artefacts_that_AGREE_are_corroboration_not_conflict():
    """THE F-9 GUARD. The pair that was refused on a real run."""
    idx = M.MetricIndex()
    idx.add(rec(0, "openroad.log", "a", unit="1",
                metric="route.drc.violation.count"))
    idx.add(rec(0, "openroad.metrics.json", "b", unit="1",
                metric="route.drc.violation.count"))
    assert len(idx) == 1, "the fact is one fact and must be kept once"
    corr = idx.corroborations()
    assert len(corr) == 1
    (entries,) = corr.values()
    assert entries[0]["basis"] == "SECOND_ARTEFACT"
    assert entries[0]["source"]["path"] == "openroad.metrics.json"


def test_corroboration_names_the_artefact_that_confirmed_it():
    """A confirmation nobody can see is not evidence. The document has to say
    which artefact agreed, or a reader cannot tell a corroborated number from
    one that was stated once."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "a.log", "a"))
    idx.add(rec(12704.0, "b.log", "b"))
    doc = M.bundle(idx)
    assert "corroborations" in doc
    key = next(iter(doc["corroborations"]))
    assert key.startswith("route.wirelength.um@sha256:")
    assert doc["corroborations"][key][0]["source"]["path"] == "b.log"


def test_a_set_with_nothing_corroborated_carries_no_corroborations_key():
    """The common case must not gain a decorative empty block."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "a.log", "a"))
    assert "corroborations" not in M.bundle(idx)


def test_an_integral_float_and_an_int_are_ONE_measurement():
    """12704 and 12704.0 are one number written two ways. Refusing the pair
    would resurrect the defect for every producer that writes one of each."""
    idx = M.MetricIndex()
    idx.add(rec(12704, "a.log", "a"))
    idx.add(rec(12704.0, "b.log", "b"))
    assert len(idx) == 1


def test_the_SAME_bytes_read_twice_is_recorded_as_such():
    """F-10: the runner publishes one report into two directories. Two paths,
    one artefact -- and the basis says so, so an auditor is not left thinking
    two independent tools agreed."""
    idx = M.MetricIndex()
    idx.add(rec(5.2, "phase3/stage3/sta/x.rpt", "a", unit="ns",
                metric="timing.setup.wns_ns"))
    idx.add(rec(5.2, "reports/phase3/x.rpt", "a", unit="ns",
                metric="timing.setup.wns_ns"))
    assert len(idx) == 1
    (entries,) = idx.corroborations().values()
    assert entries[0]["basis"] == "SAME_ARTEFACT"


# ───────────────────────────── negative ─────────────────────────────────────

def test_two_artefacts_that_DISAGREE_are_still_refused():
    """The other half of F-9, and it must not regress: the OpenROAD log and
    its metrics JSON really do state different wirelengths, reproducibly."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "openroad.log", "a"))
    with pytest.raises(M.MetricError) as exc:
        idx.add(rec(12722.0, "openroad.metrics.json", "b"))
    assert exc.value.code == "CONFLICTING_RECORD"


def test_the_conflict_names_BOTH_sources():
    """A conflict a reader cannot attribute is a conflict nobody can settle."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "openroad.log", "a"))
    with pytest.raises(M.MetricError) as exc:
        idx.add(rec(12722.0, "openroad.metrics.json", "b"))
    assert "openroad.log" in exc.value.message
    assert "openroad.metrics.json" in exc.value.message


@pytest.mark.parametrize("second,code", [
    (dict(value=12722.0), "CONFLICTING_RECORD"),
    (dict(value=12704.0, unit="mm"), "CONFLICTING_RECORD"),
])
def test_a_differing_value_or_unit_is_a_conflict(second, code):
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "a.log", "a"))
    other = M.measured("route.wirelength.um", second.get("value"),
                       second.get("unit", "um"), SCOPE, src("b.log", "b"))
    with pytest.raises(M.MetricError) as exc:
        idx.add(other)
    assert exc.value.code == code


def test_a_differing_STATUS_is_a_conflict_not_corroboration():
    """MEASURED 0 and NOT_MEASURED are not the same fact, and the second must
    never be absorbed into the first."""
    idx = M.MetricIndex()
    idx.add(rec(0.0, "a.log", "a"))
    with pytest.raises(M.MetricError) as exc:
        idx.add(rec(None, "b.log", "b", status=M.NOT_MEASURED))
    assert exc.value.code == "CONFLICTING_RECORD"


def test_the_SAME_bytes_giving_TWO_values_is_a_parser_defect():
    """Named apart from a tool disagreement on purpose: identical bytes cannot
    support two numbers, so this is a fact about the parser and sending its
    reader to look for a tool disagreement wastes their time."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "x.rpt", "a"))
    with pytest.raises(M.MetricError) as exc:
        idx.add(rec(12722.0, "x-copy.rpt", "a"))
    assert exc.value.code == "SAME_ARTEFACT_TWO_VALUES"


def test_a_byte_identical_record_is_still_a_DUPLICATE():
    """Unchanged, and it must stay unchanged: silently de-duplicating makes a
    set's size depend on how many times a producer ran."""
    idx = M.MetricIndex()
    r = rec(12704.0, "a.log", "a")
    idx.add(r)
    with pytest.raises(M.MetricError) as exc:
        idx.add(dict(r))
    assert exc.value.code == "DUPLICATE_RECORD"


# ───────────────────────────── vacuous ──────────────────────────────────────

def test_vacuous_no_source_hash_cannot_claim_SAME_ARTEFACT():
    """`_same_artefact` compares hashes. Two records that state no hash are not
    thereby the same artefact -- absent must never compare equal to absent."""
    idx = M.MetricIndex()
    idx.add(rec(12704.0, "a.log"))
    idx.add(rec(12704.0, "b.log"))
    (entries,) = idx.corroborations().values()
    assert entries[0]["basis"] == "SECOND_ARTEFACT"
    with pytest.raises(M.MetricError) as exc:
        idx2 = M.MetricIndex()
        idx2.add(rec(12704.0, "a.log"))
        idx2.add(rec(12722.0, "b.log"))
    assert exc.value.code == "CONFLICTING_RECORD"

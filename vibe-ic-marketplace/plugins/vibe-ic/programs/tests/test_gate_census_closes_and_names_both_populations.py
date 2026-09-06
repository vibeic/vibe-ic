#!/usr/bin/env python3
"""The published gate census did not close, and two populations shared a field name.

MEASURED DEFECT — A
===================
`phase23_completion_audit.json` published, on a real run:

    registered_gate_count 246 | invoked_gate_count 246
    passed_gate_count     182 | failed_gate_count      1
    not_invocable_gate_count 0

182 + 1 + 0 is not 246. The umbrella's own records held the other 63 — SKIP 36,
BLOCKED 11, INCOMPLETE 16 — and NO published field counted them. So a reader
could take `invoked_gate_count: 246` as coverage and be wrong by 63 gates that
made no statement about the design: `invoked` counts everything that was not
NOT_INVOCABLE, so a gate whose input was absent and a gate whose dependency
never produced one are both "invoked".

MEASURED DEFECT — B
===================
The same file carries `gate_execution_ledger`, and it is a DIFFERENT
population. Measured on one run: 246 registry names, 66 ledger names, 10 in
both — and ALL FIVE of that run's ledger FAILs were outside the registry. So
the artifact said `failed_gate_count: 1` beside five failing gates; both
numbers were right about different things and nothing in the file said which.

WHAT IS BLOCKING AND WHAT IS NOT — declared, not implied
========================================================
* the census closure is BLOCKING. It compares the numerators this audit
  publishes against the records they project. It cannot be false while the
  projection is correct, so it costs nothing today and catches the day one of
  them drifts. It is a defect in the AUDIT, and it forces the verdict through
  the existing `structural_fail_lines` -> `forced_fail` path.
* the population reconciliation is ADVISORY. Making a ledger FAIL blocking
  would redden runs whose gates are advisory by design; that is a ruling about
  policy, not a defect in arithmetic.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flow_compliance_check as F  # noqa: E402


def _records(**counts):
    out, n = [], 0
    for verdict, k in counts.items():
        for _ in range(k):
            n += 1
            out.append({"name": f"gate_{n}_check", "verdict": verdict,
                        "message": "", "evidence": {}})
    return out


def test_the_census_partitions_every_registered_gate():
    """The 63 that had no bucket now have one, and the total closes."""
    recs = _records(PASS=182, FAIL=1, SKIP=36, BLOCKED=11, INCOMPLETE=16)
    c = F.p0_gate_census(recs)
    assert c["registered"] == 246
    assert c["by_verdict"] == {"BLOCKED": 11, "FAIL": 1, "INCOMPLETE": 16,
                               "NOT_INVOCABLE": 0, "PASS": 182, "SKIP": 36}
    assert c["published_total"] == 246
    assert c["unaccounted"] == 0
    assert c["closes"] is True
    assert c["buckets_disagreeing_with_records"] == []
    # The reading the old shape invited is refused in the artifact itself, and
    # it names the two buckets that make `invoked` differ from coverage.
    note = c["invoked_is_not_coverage"]
    assert "SKIP" in note and "BLOCKED" in note and "invoked_gate_count" in note


def test_a_numerator_that_stops_projecting_the_records_reddens_by_name():
    """MUTATION — the check's whole purpose. `closes` goes False and NAMES the
    bucket that drifted; a check that cannot fail is not a check."""
    recs = _records(PASS=10, FAIL=1, SKIP=2)
    assert F.p0_gate_census(recs)["closes"] is True
    orig = F._p0_passed_count
    F._p0_passed_count = lambda rs: orig(rs) - 1
    try:
        c = F.p0_gate_census(recs)
    finally:
        F._p0_passed_count = orig
    assert c["closes"] is False
    assert c["buckets_disagreeing_with_records"] == ["PASS"]
    assert c["unaccounted"] == 1


def test_an_unrecognised_verdict_is_named_rather_than_dropped():
    """A record the projection does not recognise must still be COUNTED, under
    a name. Silently dropping it is how the 63 went missing."""
    recs = _records(PASS=2) + [{"name": "odd_check", "verdict": None}]
    c = F.p0_gate_census(recs)
    assert c["by_verdict"]["UNKNOWN"] == 1
    assert c["closes"] is True
    assert c["registered"] == 3


def test_no_umbrella_is_not_a_census_of_zero():
    """Stage 3/4: the umbrella did not run. `None` is the answer, not 0 —
    'could not look' is not 'looked and found nothing'."""
    assert F.p0_gate_census(None) is None


def test_the_two_populations_are_told_apart_by_name():
    """The ledger is not the registry, and a ledger FAIL appears in NO census
    count in the file. Say so, in the file."""
    recs = _records(PASS=2) + [{"name": "shared_check", "verdict": "FAIL"}]
    ledger = [{"gate": "shared_check", "verdict": "PASS", "rc": 0},
              {"gate": "outside_a_check", "verdict": "FAIL", "rc": 1},
              {"gate": "outside_b_check", "verdict": "FAIL", "rc": 1}]
    r = F.gate_population_reconciliation(recs, ledger)
    assert r["p0_registry_gates"] == 3
    assert r["ledger_gates"] == 3
    assert r["in_both"] == ["shared_check"]
    assert r["ledger_only"] == 2
    assert r["p0_registry_failed_gates"] == ["shared_check"]
    assert r["ledger_failed_gates"] == ["outside_a_check", "outside_b_check"]
    assert r["ledger_failures_outside_the_published_census"] == [
        "outside_a_check", "outside_b_check"]
    assert r["declared"].startswith("ADVISORY")


def test_the_reconciliation_survives_an_absent_umbrella():
    """Stage 3/4 again: the ledger still has something to say."""
    r = F.gate_population_reconciliation(
        None, [{"gate": "a_check", "verdict": "FAIL", "rc": 1}])
    assert r["p0_registry_gates"] == 0
    assert r["ledger_failed_gates"] == ["a_check"]
    assert r["ledger_failures_outside_the_published_census"] == ["a_check"]

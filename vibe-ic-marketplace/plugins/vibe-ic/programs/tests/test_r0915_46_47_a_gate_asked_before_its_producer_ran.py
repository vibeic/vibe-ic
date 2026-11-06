"""R-0915-46 / R-0915-47: a gate asked before the thing it measures exists.

MEASURED 2026-09-16 (lane icspm3) on the SPM verdict candidate, run28 /
`spm23`. Two rows kept the run non-green, and neither was a fact about the
design:

  `gate_evidence_completeness_check` booked INCOMPLETE — "examined nothing
  (reason: no FINAL_REPORT.md or flow-compliance JSON in this run)". It books
  that for the absence of the completion audit's OWN record, which the audit
  it is a component of writes only after it passes. CIRCULAR: on a first run
  it can never be satisfied. MEASURED: `find_report(spm23)` returned None
  while `reports/audit/phase23_completion_audit.json` sat on disk with a
  246-entry `gate_execution_ledger`.

  `klayout_deck_mode_check` booked INCOMPLETE in flight — "[skipped] no
  KLayout DRC artefacts found" — and on the completed tree's re-audit the same
  gate is "[PASS] 14 DRC artefact(s); real rule deck attested by 3 of them".
  The P0 umbrella asks before phase-3 DRC has produced them.

Both are the R-0915-38 deadlock family: a gate demanding an artefact produced
after it.

TWO FIXES, AND THE SECOND ONE MATTERS AS MUCH AS THE FIRST. Teaching the
completeness gate to read the audit record turned its circular INCOMPLETE into
a FAIL naming 14 of 17 PASS gates as unevidenced — including
`yosys_hilomap_required_check`, while `reports/phase2/gates/yosys_hilomap.json`
sat on disk. The evidence locator globbed `reports/gates/*.json`, and THIS
FLOW WRITES `reports/phase2/gates/`. Shipping the lookup alone would have
replaced a circular INCOMPLETE with a FALSE FAIL, which is worse.

THE GRANT IS NARROW. `ASKED_BEFORE_PRODUCER` applies only to a registered
gate, and only while the tree shows the producer has NOT run. Once it has, an
absent subject keeps whatever non-green verdict the gate gave it — that is the
negative control, and it is what stops this becoming a blanket excuse.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as T  # noqa: E402

REGISTERED = ("klayout_deck_mode_check", "gate_evidence_completeness_check")


def _audit(proj, ledger):
    """Write the completion audit's own record. Rows may carry `cmd`, which
    is how a gate DECLARES the artefact its PASS rests on."""
    p = proj / "reports" / "audit" / "phase23_completion_audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"gate_execution_ledger": ledger}))
    return p


def _gate_report(proj, rel, payload=None):
    p = proj / "reports" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload or {"verdict": "PASS"}))
    return p


# ── R-0915-46: the gate reads the population the audit is building ───────


# ── R-0915-47: the grant, and the limit on it ────────────────────────────


def test_the_class_is_skip_eligible_and_clears_P0():
    assert T.ASKED_BEFORE_PRODUCER in T.REASON_CLASS_SET
    assert T.ASKED_BEFORE_PRODUCER in T.SKIP_ELIGIBLE
    assert T.ASKED_BEFORE_PRODUCER not in T.INCOMPLETE
    assert T.record_verdict(T.ASKED_BEFORE_PRODUCER) == "SKIP"
    assert T.p0_tier_for_reason_classes({T.ASKED_BEFORE_PRODUCER}) == "PASS"
    assert T.p0_tier_for_reason_classes(
        {T.ASKED_BEFORE_PRODUCER, T.EXECUTION_ERROR}) == "INCOMPLETE"


def test_the_grant_actually_reaches_the_classifier():
    """The channel, end to end. An earlier attempt of mine put a class into
    the evidence dict that `normalise()` rejected because it was not in
    `REASON_CLASSES`, so the grant was inert while looking correct."""
    with_grant = T.infer_nonverdict_reason(
        verdict="SKIP", message="[skipped] no KLayout DRC artefacts found",
        evidence={"reason_class": T.ASKED_BEFORE_PRODUCER})
    without = T.infer_nonverdict_reason(
        verdict="SKIP", message="[skipped] no KLayout DRC artefacts found",
        evidence={})
    assert with_grant == T.ASKED_BEFORE_PRODUCER
    assert without == T.EXECUTION_ERROR
    assert with_grant in T.SKIP_ELIGIBLE and without not in T.SKIP_ELIGIBLE

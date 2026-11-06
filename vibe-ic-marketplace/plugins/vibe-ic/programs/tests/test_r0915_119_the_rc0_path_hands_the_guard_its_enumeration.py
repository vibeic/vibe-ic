"""R-0915-119's guard is only as good as the ENUMERATION it is handed — and
the enumeration is only as good as the scan that produced it.

MEASURED on spm run22 (lane icspm5, 2026-09-23). Step 2's
`internal_vs_external_timing_check` exits 0, prints nothing, and publishes
verdict VACUOUS_PASS / reason_class NOT_APPLICABLE_BY_STRUCTURE with
structural_absence {scanned 13, found 0}. The ledger row read verdict
INCOMPLETE / reason_class EXECUTION_ERROR and step 2 read NOT_MEASURED /
partial_population — "the gate reports its input was applicable and was NOT
examined" over a checker that had enumerated thirteen containers and said so.

The first cut of this change handed the guard the evidence at the rc-0 call
site and stopped there. THE PRE-LANDING REVIEW REFUSED IT, and it was right:
the fail-closed default was masking a defect in the GATE's own escape, so
removing the mask without fixing the escape would have turned a bad
enumeration into a PASS. Three things were wrong in the gate and one in the
ledger, and this file pins all four BY BEHAVIOUR.

  1. the escape never read L2. Its own comment says it fires "when L2 says
     NOTHING", but the condition did not look — so a design DECLARING
     protocol_overview.half_duplex=true, whose L8 emitted its canonical
     containers empty (a producible shape), was certified as a structural
     absence while the gate's own check() answered FAIL on the same input.
  2. `scanned` counted NAMES, not containers. It listed all three canonical
     containers whether or not the document had them. A container that is
     absent was never examined.
  3. the scan read top-level key names only, while check() prefers the nested
     `timing_groups` mapping — so a real RX/TX split, stored the canonical
     way, could be enumerated as if it were not there.
  4. `_record_gate_execution` re-runs the taxonomy and was not given the
     evidence either, so the published row carried verdict NOT_APPLICABLE
     beside reason_class EXECUTION_ERROR: one gate, two answers, one record.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as _t  # noqa: E402
import _structural_absence as _sa  # noqa: E402


def _project(tmp_path, l8, l2=None):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8))
    (docs / "L8_RTL_CONSTANTS.json").write_text("{}")
    if l2 is not None:
        (docs / "L2_FRS.json").write_text(json.dumps(l2))
    return docs


_EMPTY_L8 = {"timing_windows": [], "timing_constants": [], "waveforms": []}


# ------------------------------------------------- the GATE, by behaviour


# ------------------------------------- the TAXONOMY call, by behaviour

def _report(scanned=13, found=0, reason_class="NOT_APPLICABLE_BY_STRUCTURE"):
    return {"verdict": "VACUOUS_PASS", "reason_class": reason_class,
            _sa.EVIDENCE_KEY: {"population": "containers", "scanned": scanned,
                               "found": found,
                               "scanned_names": [f"c{i}" for i in range(scanned)]}}


def test_the_enumerated_absence_is_classified_as_absence_not_as_a_crash():
    rep = _report()
    got = _t.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message="",
        evidence={_sa.EVIDENCE_KEY: _sa.evidence_of(rep)},
        explicit=_t.report_reason_class(rep))
    assert got == _t.NOT_APPLICABLE_BY_STRUCTURE
    assert got in _t.SKIP_ELIGIBLE and got not in _t.INCOMPLETE


def test_a_bare_token_with_no_enumeration_is_still_refused():
    """The fail-closed default is NOT removed — it is given its evidence."""
    assert _t.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message="", evidence=None,
        explicit="NOT_APPLICABLE_BY_STRUCTURE") == _t.EXECUTION_ERROR


def test_an_enumeration_that_found_its_subject_is_refused():
    rep = _report(found=4)
    assert _t.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message="",
        evidence={_sa.EVIDENCE_KEY: _sa.evidence_of(rep)},
        explicit=_t.report_reason_class(rep)) == _t.EXECUTION_ERROR


def test_a_report_declaring_execution_error_stays_incomplete():
    rep = _report(reason_class="EXECUTION_ERROR")
    got = _t.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message="",
        evidence={_sa.EVIDENCE_KEY: _sa.evidence_of(rep)},
        explicit=_t.report_reason_class(rep))
    assert got == _t.EXECUTION_ERROR and got in _t.INCOMPLETE


# --------------------------------------------- the LEDGER ROW, by behaviour

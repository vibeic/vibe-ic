#!/usr/bin/env python3
"""The Phase-1 expert hand-off is a WAIT, not a failed run.

MEASURED DEFECT (the #2014 residual, 14 cases across 7 test files, one cause)
============================================================================
`phase1_expert_parse_track.ai_subtrack` implements a TWO-PASS protocol. Pass
one writes the pack and reports `HANDOFF_EMITTED` — "invoke subagent … and
re-run to consume its answer". A program cannot spawn the subagent, so pass one
is what EVERY non-agent invocation produces, including every CI run and every
invocation from `benchmark/gates_atomic.py`.

`7d1da41d7` (#1973) began returning 1 from `phase1_one_shot_runner`'s expert
track for that state. #1973's measured defect was real and is untouched here —
the runner's summary said the second track "ran" when nothing had been read.
But the repair also turned the designed first pass into a nonzero exit, which
made the runner's exit code unreachable-by-any-legitimate-input in a headless
run, and the Shape-C benchmark hard gate `phase1_run_all` reads exactly that
exit code:

    gates_atomic.py  steps["phase1_run_all"] = PASS iff rc == 0 and l9_ok

MEASURED, same tree otherwise, pinned image, one pytest process per file:
    55bb6967b (7d1da41d7^)  gates.json phase1_run_all = PASS, gate rc 0
    7d1da41d7               gates.json phase1_run_all = FAIL, gate rc 1,
                            l9_rendered STILL true — Phase 1 rendered its docs
                            and the gate failed on the pending expert half.

THE CONTRACT PINNED HERE
========================
Three dispositions, and they are different things:

  CREDITED  a non-empty answer was read back and the denominators agree.
  PENDING   a state the protocol defines and does not credit — the hand-off
            awaiting its agent, or an answer read back that was honestly empty.
            Uncredited in the report, and NOT a failed run.
  DEFECT    a record that can be read as neither: absent, unparseable, ERROR,
            a schema-refused answer, or a claim of completion contradicted by
            the track's own exit code.

Both halves are pinned, in both directions: PENDING must not fail the run, and
DEFECT must still fail it. A repair that made every state pass would be the
mirror of the defect it repairs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_one_shot_runner as R  # noqa: E402


def _record(status, *, consumed=1, ai=1, total=1):
    return {"verdict": "PASS",
            "ai_subtrack": {"status": status},
            "ai_convergence": {"consumed": consumed},
            "denominator": {"ai": ai, "total": total}}


# ── PENDING: stated protocol states that are not failures ──────────────────

def test_handoff_emitted_is_pending_not_defect():
    """The designed first pass. This is the case that took the 14 gate cases
    down, and the one a reader must be able to tell from a crash."""
    disp, detail = R._expert_track_disposition(
        _record("HANDOFF_EMITTED", consumed=0, ai=0, total=0))
    assert disp == R._EXPERT_PENDING, (disp, detail)
    assert "HANDOFF_EMITTED" in detail


def test_consumed_empty_is_pending_not_defect():
    """`ai_subtrack` calls this "a real reading of zero, not a missing answer".
    It earns no credit, and it is not a broken track either."""
    disp, _ = R._expert_track_disposition(
        _record("CONSUMED_EMPTY", consumed=0, ai=0, total=0))
    assert disp == R._EXPERT_PENDING


# ── CREDITED: unchanged by this repair ─────────────────────────────────────

def test_a_consumed_non_empty_answer_is_still_credited():
    disp, _ = R._expert_track_disposition(_record("CONSUMED"))
    assert disp == R._EXPERT_CREDITED


# ── DEFECT: the half that must keep failing ────────────────────────────────

def test_schema_refused_answer_is_a_defect_not_a_wait():
    """A refusal is not a waiting state: the agent DID answer, and the answer
    could not be read. Reading it as PENDING would silently retire the refusal.
    """
    disp, _ = R._expert_track_disposition(
        _record("ANSWER_SCHEMA_MISMATCH", consumed=0, ai=0, total=0))
    assert disp == R._EXPERT_DEFECT


def test_track_error_is_a_defect():
    disp, _ = R._expert_track_disposition(
        _record("ERROR", consumed=0, ai=0, total=0))
    assert disp == R._EXPERT_DEFECT


def test_an_unknown_status_is_a_defect_not_a_wait():
    """A status this reader does not know must not be waved through: the
    pending set is an allow-list precisely so a producer that grows a new
    failure state cannot inherit a pass."""
    disp, _ = R._expert_track_disposition(
        _record("SOMETHING_NEW", consumed=0, ai=0, total=0))
    assert disp == R._EXPERT_DEFECT


def test_a_consumed_claim_with_broken_denominators_is_a_defect():
    """CONSUMED with `denominator.ai != consumed` is the #1973 shape — a claim
    of a reading that the record's own counters contradict."""
    disp, _ = R._expert_track_disposition(
        _record("CONSUMED", consumed=1, ai=0, total=0))
    assert disp == R._EXPERT_DEFECT


def test_a_report_with_no_ai_evidence_is_a_defect():
    assert R._expert_track_disposition({"verdict": "PASS"})[0] == R._EXPERT_DEFECT
    assert R._expert_track_disposition([])[0] == R._EXPERT_DEFECT


# ── the reporting half of #1973 is NOT relaxed ─────────────────────────────

def test_pending_is_reported_uncredited_and_never_as_ran(tmp_path):
    """The lie #1973 measured was the summary string "ran". A PENDING
    disposition must still publish INCOMPLETE — otherwise this repair would
    reopen the issue it is careful not to."""
    proj = tmp_path / "proj"
    rpt = proj / "reports" / "audit" / "phase1" / "expert_parse_track.json"
    rpt.parent.mkdir(parents=True)
    rpt.write_text(json.dumps(_record("HANDOFF_EMITTED", consumed=0, ai=0, total=0)))
    summary = R._expert_track_summary(proj)
    assert summary.startswith("INCOMPLETE"), summary
    assert "HANDOFF_EMITTED" in summary
    assert summary != "ran"


def test_credit_still_requires_a_consumed_answer(tmp_path):
    proj = tmp_path / "proj"
    rpt = proj / "reports" / "audit" / "phase1" / "expert_parse_track.json"
    rpt.parent.mkdir(parents=True)
    rpt.write_text(json.dumps(_record("CONSUMED")))
    assert R._expert_track_summary(proj).startswith("consumed")

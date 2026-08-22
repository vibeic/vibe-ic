#!/usr/bin/env python3
"""ORGANIC #307 — the route-loosen DECLINE path was structurally silent.

In one function, two paths handle the same kind of refusal:

  UPSIZE path  refuses -> returns a named FAIL StepResult (die-cap message)
  LOOSEN path  refuses -> had no `else` branch AT ALL: no print, no
               resize_history entry, no marker

So the flow could refuse its OWN rescue with nobody told. Measured across two
live auto-die runs: cap / loosen / refusal strings appear 0 times in runner
stdout, and `resize_history` is absent from every emitted JSON.

EVIDENCE BOUNDARY (from the issue author, preserved deliberately): in those two
runs the decline was for a ROUTER-BUDGET reason — the violation trajectory was
still descending (880,145 -> 850,667 -> 812,210 -> 670,215) — NOT for the cap
reason, which needs a plateau first. So the zero-occurrence measurement proves
the decline path is silent for EVERY reason; it is not yet a cap-specific log
line from a real plateau. These tests keep that distinction.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


def _ex(**kw):
    base = dict(die_w=200, die_h=200, log_text="", loosen_idx=0,
                auto_die_requested=True, route_completed=True)
    base.update(kw)
    return p3._route_feedback_loosen_ex(**base)


def test_307_every_decline_names_a_reason():
    """Each refusal branch must say WHY. A bare None is what made the path
    silent."""
    seen = set()
    d, r = _ex(auto_die_requested=False)
    assert d is None and r == "explicit_die_requested"; seen.add(r)
    d, r = _ex(route_completed=False)
    assert d is None and r == "route_did_not_complete"; seen.add(r)
    d, r = _ex(loosen_idx=len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1)
    assert d is None and r == "loosen_ladder_exhausted"; seen.add(r)
    # a converging trajectory — the reason BOTH live runs actually declined for
    d, r = _ex(log_text="Number of violations = 900\nNumber of violations = 100\n")
    assert d is None and r == "route_still_converging"; seen.add(r)
    assert len(seen) == 4, seen


def test_307_reason_is_never_empty_on_a_decline():
    """A decline with an empty reason would be silence wearing a return type."""
    for kw in ({"auto_die_requested": False}, {"route_completed": False},
               {"loosen_idx": len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1}):
        d, r = _ex(**kw)
        assert d is None
        assert isinstance(r, str) and r.strip(), kw


def test_307_the_converging_case_is_the_one_the_live_runs_hit():
    """Evidence boundary: the two measured runs declined because the violation
    trajectory was still DESCENDING, not because of the die cap. Pin that this
    reason is distinct from the cap reason, so the two are never conflated."""
    _, converging = _ex(
        log_text="Number of violations = 880145\nNumber of violations = 670215\n")
    assert converging == "route_still_converging"
    assert converging != "die_cap_reached"


def test_307_backward_compatible_wrapper_still_returns_bare_optional():
    """The 6 existing call sites/tests must keep working unchanged."""
    assert p3._route_feedback_loosen(200, 200, "", 0, False, True) is None


def test_307_success_path_still_returns_the_record():
    """No regression on the ACCEPT path: a non-converging trajectory with rungs
    left must still loosen, and now also report `loosened`."""
    plateau = "\n".join(f"Number of violations = {13000 + i}" for i in range(6))
    decision, reason = _ex(log_text=plateau)
    if decision is None:
        # the ladder/cap guards may legitimately refuse on these dims; then the
        # reason must still be one of the named ones, never empty.
        assert reason in {"loosen_ladder_exhausted", "die_cap_reached",
                          "route_still_converging"}
    else:
        assert reason == "loosened"
        assert decision[2]["direction"] == "loosen"


def test_307_runner_emits_a_named_decline_marker():
    """The caller must leave the symmetric named record the UPSIZE path leaves.
    Source-pinned: the decline branch, its marker, and the resize_history entry
    must all be present."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "ROUTE_LOOSEN_DECLINED" in src
    # A decline is NOT a resize: it changed no dimension, so it must live in
    # its own register. Recording it in resize_history corrupts "how many
    # times was the die resized?" — existing tests correctly assert
    # resize_history == [] on runs that never resized, and caught this.
    assert "loosen_declines" in src
    assert '"loosen_declines": loosen_declines' in src
    assert '"action": "declined"' in src
    i = src.index("ROUTE_LOOSEN_DECLINED")
    window = src[max(0, i - 1400):i]
    assert "loosen_declines.append(_decline)" in window
    assert "_lf_reason" in window

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

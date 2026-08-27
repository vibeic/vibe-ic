#!/usr/bin/env python3
"""test_a_phase1_timeout_is_undetermined_not_a_failing_verdict.py

THE DEFECT. `phase1_one_shot_runner` had TWO handlers that caught a subprocess
timeout, printed the correct diagnosis at the scene —

    "a timeout is not a verdict, and an unevaluated track cannot pass"
    "a timeout is not a verdict, and an undispatched producer cannot pass"

— and then `return 1`. The prose and the exit code disagreed, and the exit code
is the half every machine reads. Phase 1 published `verdict: FAIL` about a
design whose expert track it had just killed mid-run: a wall clock decided that
a chip was bad.

THE FIX is one line each — the repo's own rc 2 UNDETERMINED convention, already
in use by `gatekeeper_review`, `_corpus_location` and the landing gate, which
maps a review killed at its budget onto exactly this because "a review that
could not decide must never reach the stamp as a review that decided nothing
was wrong".

BOTH DIRECTIONS ARE ASSERTED HERE, because a guard that stopped refusing is a
deletion and not a fix:

  * REFUSES STILL — a track that never finished still stops Phase 1. rc is
    non-zero, the verdict is not PASS, and nothing downstream can read the run
    as clean. `test_a_killed_track_still_stops_phase1` and
    `test_the_undetermined_rc_is_not_a_pass_anywhere_it_is_combined`.
  * NO LONGER ACCUSES — the rc and the published verdict say "not measured",
    not "failed". `test_a_killed_track_is_not_recorded_as_a_design_failure`.

AND THE LAUNDERING DIRECTION, which introducing a second non-zero rc creates:
`max()` combined the component rcs, and `max(1, 2) == 2` would have turned a
MEASURED Phase-1 failure into "could not decide" — a worse defect than the one
being fixed, in the opposite direction.
`test_a_measured_failure_is_never_laundered_into_undetermined` is that control.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_phase1_timeout_is_undetermined_not_a_failing_verdict.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_one_shot_runner as R              # noqa: E402
import _path_layout as _pl                      # noqa: E402


# ── the constructed violation ───────────────────────────────────────────────
#
# A track program that never returns. `subprocess.run(..., timeout=600)` is
# what the runner does with it, so rather than wait ten minutes for the real
# bound we make the SAME exception the real bound raises. The subject under
# test is the HANDLER, not the clock: what the runner does once it has been
# told "this did not finish" is the entire question, and it is answered
# identically however that fact arrived.

def _project(tmp_path: Path, name: str = "proj") -> Path:
    p = tmp_path / name
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "reports").mkdir(parents=True)
    return p


def _a_track_that_never_finishes(tmp_path: Path) -> Path:
    """A PROGRAMS_DIR whose expert track is a real, real-slow program."""
    d = tmp_path / "programs"
    d.mkdir()
    (d / R._EXPERT_TRACK).write_text(
        "import time\nwhile True:\n    time.sleep(3600)\n")
    return d


def _timing_out(*_a, **_kw):
    raise subprocess.TimeoutExpired(cmd="the track", timeout=600)


# ── direction 1: it still refuses ───────────────────────────────────────────

def test_a_killed_track_still_stops_phase1(tmp_path):
    """THE HALF THAT MUST NOT MOVE. An unevaluated second track is not a pass,
    and this test is what stands between the fix and a deletion."""
    p = _project(tmp_path)
    with mock.patch.object(R, "PROGRAMS_DIR",
                           _a_track_that_never_finishes(tmp_path)), \
            mock.patch.object(R.subprocess, "run", _timing_out):
        rc = R._run_expert_track(p)
    assert rc != 0, (
        "a track that never finished reported a clean run — the timeout stopped "
        "refusing, which is a deletion of the guard and not a fix")


def test_a_killed_producer_still_stops_phase1(tmp_path):
    """The same half for step 0.5ic's producers."""
    p = _project(tmp_path)
    with mock.patch.object(R.subprocess, "run", _timing_out):
        rc = R._run_step_0_5ic(p)
    assert rc != 0, "an undispatched route producer reported a clean run"


def test_the_undetermined_rc_is_not_a_pass_anywhere_it_is_combined(tmp_path):
    """Every site that folds a component rc into Phase 1's own must keep it
    non-zero. A 2 that any combiner flattened to 0 would be the same green run
    by a longer route."""
    assert R._worst_rc(0, R.RC_UNDETERMINED) == R.RC_UNDETERMINED
    assert R._worst_rc(R.RC_UNDETERMINED, 0) == R.RC_UNDETERMINED
    assert R._worst_rc(R.RC_UNDETERMINED, R.RC_UNDETERMINED) != 0
    assert R._worst_rc(0, 0) == 0, "and a clean run is still clean"


# ── direction 2: it no longer accuses ───────────────────────────────────────

def test_a_killed_track_is_not_recorded_as_a_design_failure(tmp_path):
    """THE FIX. The exit code now agrees with the sentence printed beside it."""
    p = _project(tmp_path)
    with mock.patch.object(R, "PROGRAMS_DIR",
                           _a_track_that_never_finishes(tmp_path)), \
            mock.patch.object(R.subprocess, "run", _timing_out):
        rc = R._run_expert_track(p)
    assert rc == R.RC_UNDETERMINED, (
        f"rc {rc}: a track that was KILLED is being reported with the same "
        f"code as a track that RAN and found the design wanting")


def test_a_killed_producer_is_not_recorded_as_a_design_failure(tmp_path):
    p = _project(tmp_path)
    with mock.patch.object(R.subprocess, "run", _timing_out):
        assert R._run_step_0_5ic(p) == R.RC_UNDETERMINED


def test_the_published_verdict_has_a_word_for_not_measured(tmp_path):
    """`reports/phase1_one_shot.json` is what a human and every downstream
    reader see. "PASS if rc == 0 else FAIL" had no word for "the delegate was
    killed", so it used the one that blames the design."""
    assert R._delegated_verdict(0) == "PASS"
    assert R._delegated_verdict(1) == "FAIL"
    assert R._delegated_verdict(R.RC_UNDETERMINED) == R.VERDICT_UNDETERMINED
    assert R._delegated_verdict(R.RC_UNDETERMINED) != "FAIL", (
        "the published verdict still accuses the design of failing a check "
        "that never ran")
    # And the step-0.5ic summary line, same defect one field over.
    assert R._step_0_5ic_note(0) == "ran"
    assert R._step_0_5ic_note(1) == "FAILED to run"
    assert "NOT MEASURED" in R._step_0_5ic_note(R.RC_UNDETERMINED)


def test_a_track_that_actually_failed_is_still_a_failure(tmp_path):
    """NON-VACUITY. The new code must not have turned every non-zero exit into
    UNDETERMINED — a track that RAN and returned 3 examined the design and did
    not complete, and that is a measured failure."""
    p = _project(tmp_path)
    d = tmp_path / "programs"
    d.mkdir()
    (d / R._EXPERT_TRACK).write_text(
        "import sys; sys.stderr.write('boom\\n'); sys.exit(3)\n")
    with mock.patch.object(R, "PROGRAMS_DIR", d):
        assert R._run_expert_track(p) == 1


# ── the laundering control ──────────────────────────────────────────────────

def test_a_measured_failure_is_never_laundered_into_undetermined():
    """THE DANGER THE SECOND RC INTRODUCES, and the reason `max()` had to go.

    `max(1, 2) == 2`. Every combination site used `max`, so the first run with
    both a REAL Phase-1 failure and a killed second track would have published
    "could not decide" over the top of a measured red. That is the same defect
    as the one being fixed, pointing the other way, and it is worse: it hides a
    finding somebody actually made.
    """
    assert R._worst_rc(1, R.RC_UNDETERMINED) == 1
    assert R._worst_rc(R.RC_UNDETERMINED, 1) == 1
    assert R._worst_rc(0, 1, R.RC_UNDETERMINED) == 1
    # And the shape a plain `max` would have got right by accident, so the
    # control is not satisfied by the old code either way.
    assert max(1, R.RC_UNDETERMINED) == R.RC_UNDETERMINED, (
        "if this ever stops being true the control above has lost its point")


def test_worst_rc_is_total_over_codes_this_runner_does_not_emit_yet():
    """An rc nobody planned for lands on the MEASURED-FAILURE side, never on 0.
    A combiner that fell through to a green on an unrecognised code would be
    the failure mode this whole file is about, one refactor later."""
    assert R._worst_rc(0, 7) == 7
    assert R._worst_rc(R.RC_UNDETERMINED, 7) == 7
    assert R._worst_rc(None, 0) == 0


# ── the pre-fix control ─────────────────────────────────────────────────────

def test_this_file_would_have_failed_against_the_pre_fix_runner():
    """THE CONTROL, written so the PRE-FIX tree can RUN it and answer wrongly.

    `getattr` rather than a direct reference: against the old module
    `RC_UNDETERMINED` and `_worst_rc` do not exist, and an AttributeError is a
    test that observed nothing. The old runner HAD `max` at every combination
    site and `return 1` in both handlers, so it answers this question — and the
    answer is the defect.
    """
    rc_undetermined = getattr(R, "RC_UNDETERMINED", None)
    combine = getattr(R, "_worst_rc", max)
    assert rc_undetermined == 2, (
        "the pre-fix runner has no rc for 'not measured' at all; every timeout "
        "is spelled the same as a finding")
    assert combine(1, 2) == 1, (
        "this is `max`: the pre-fix combiner laundered a measured failure into "
        "an inconclusive as soon as a second rc existed")

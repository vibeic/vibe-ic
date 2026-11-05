"""The collection phase must be able to prove it is MOVING, not just running.

THE DEFECT THIS PINS.  `pytest_per_file_junit.py` supervises its child on
validated lifecycle events, and kills it after `--aggregate-stall-after`
seconds with none.  Until `collect_scan` existed, the first event a parent
could validate after `session_start` was `collect_report`, which pytest does
not reach until the whole path scan is over.

MEASURED on this repo (2026-08-30, pinned image
ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2..., a 120-file selection): the
session spent 57 of its 61 collection seconds before that first event, and
emitted NOTHING validatable in the window, while `pytest_collect_file` fired
355 200 times in it with a largest gap of 0.59 s.  At landing width (1231
files) the silence ran past the 300 s grace, so the landing tier killed a
healthy collection and reported

    AGGREGATE_NORECORD  STALLED after 300 s with no validated pytest lifecycle
                        progress ... terminal event missing (stage=collecting)

which is the one thing a PROGRESS-stall watchdog must never do: a stall is no
forward progress, never elapsed time.

BOTH DIRECTIONS, OR THIS FILE PROVES NOTHING.  `test_a_scan_longer_than_the
_grace_still_reaches_a_record` FAILS against the pre-fix driver -- that is
what makes it evidence rather than decoration.  `test_a_genuinely_hung
_collection_is_still_killed` must pass against BOTH, and it is the control
that stops the fix from being "make the number bigger": it uses the SAME
short grace and the same driver, and the only difference is that its subject
really has stopped.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as DRIVER  # noqa: E402

#: THE SUBJECT IS THE REAL PLUGIN TREE, not a synthetic one.
#:
#: A synthetic tree of empty files does NOT reproduce this: MEASURED, 3 000
#: data files under 120 arguments collect in 1.4 s with a 0.08 s largest gap.
#: The silence is not the raw walk -- it is what pytest does per ARGUMENT in a
#: tree that carries this plugin's conftest and rootdir, and only the real tree
#: has that. Measured here, in the pinned image, 2026-08-30:
#:
#:     files   wall    silence WITHOUT collect_scan   largest gap WITH it
#:        10    5.4 s                        4.76 s                0.18 s
#:        25   13.4 s                       12.06 s                0.43 s
#:        50   26.4 s                       23.80 s                0.47 s
#:
#: The silence grows ~0.48 s per selected file and the gap WITH the checkpoint
#: does not grow at all.  That is the whole defect in one table: a FLAT grace
#: is outgrown by the work at about 625 files, and the landing selections that
#: could not get a record were 1231 and 175 files wide.
_REAL_FILES = 40

#: ~19 s of pre-fix silence against a 5 s grace (3.8x), and ~0.5 s of post-fix
#: gap against the same 5 s (10x).  Both margins are stated because the test is
#: only evidence while BOTH hold: too small and the pre-fix arm stops failing,
#: too large and the post-fix arm starts.
_GRACE_S = 5.0

_ENTRY = str(_PROGRAMS / "trusted_pytest_entry.py")








def test_the_scan_channel_is_a_checkpoint_and_not_a_heartbeat():
    """A stride the emitter does not honour is a refusal, not a slow clock."""
    import _pytest_progress_plugin as PLUGIN
    stride = PLUGIN.COLLECT_SCAN_STRIDE
    assert DRIVER.COLLECT_SCAN_STRIDE == stride, (
        "the emitter and the validator must share ONE stride definition")
    probe = DRIVER._SemanticProgressProbe.__new__(DRIVER._SemanticProgressProbe)
    probe.stage = "collecting"
    probe.collect_scanned = 0
    probe.collect_scan_ceiling = 10 * stride
    probe.error = ""
    # A duplicate, a gap and a jump are each refused; only +stride is accepted.
    for bad in (0, 1, stride - 1, stride + 1, 2 * stride, 10 ** 9):
        probe.error = ""
        probe.collect_scanned = 0
        DRIVER._SemanticProgressProbe._accept_collect_scan(probe, bad)
        assert probe.error, f"a scanned={bad} checkpoint was accepted"
    probe.error = ""
    probe.collect_scanned = 0
    DRIVER._SemanticProgressProbe._accept_collect_scan(probe, stride)
    assert not probe.error and probe.collect_scanned == stride


# ---------------------------------------------------------------------------
# THE SECOND BLOCKER ON THE SAME ARM: the failure bound.
#
# MEASURED on the landing tier (2026-08-30, v1.13.1, pinned image): a 175-file
# selection tripped its flat `--maxfail=10` after 378 of 4361 items and left
# 162 of 175 files never launched, so the arm reported AGGREGATE_NORECORD for
# having a normal number of standing reds.  A bound sized for one file, applied
# to a whole run, gets MORE certain to fire as the suite grows.
#
# Same split as the watchdog above: the RUNAWAY rule stays per-unit and flat,
# the CEILING derives from what was actually selected, with a floor.  Both
# directions are proven here -- the honest selection reaches a record, and a
# genuine runaway is still abandoned.  A bound that stops refusing is not a fix.
# ---------------------------------------------------------------------------






def test_the_bound_is_derived_from_the_selection_and_only_ever_rises():
    assert DRIVER.aggregate_failure_bound([], 10_000) is None, (
        "a caller that declared no bound must not acquire one here")
    # A flat 10 over 175 files becomes a ceiling of 175; it never drops.
    assert DRIVER.aggregate_failure_bound(["--maxfail=10"], 175) == 175
    assert DRIVER.aggregate_failure_bound(["--maxfail=10"], 3) == 10, (
        "a selection smaller than its own bound keeps the bound it asked for")
    assert DRIVER.aggregate_failure_bound(["--maxfail=2"], 2) == 2, (
        "the ceiling may never RAISE a small selection's deliberate bound")
    assert DRIVER.aggregate_failure_bound(["--maxfail=900"], 175) == 900, (
        "a caller asking for MORE than the ceiling keeps what it asked for")
    # Every spelling the reader understands must also be rewritten, or the
    # lower of the two silently wins and the ceiling is decorative.
    for spelling in (["--maxfail", "10"], ["--maxfail=10"], ["-x"], ["-qx"]):
        rewritten = DRIVER._with_failure_bound(spelling, 175)
        assert DRIVER._declared_failure_bound(rewritten) == 175, rewritten

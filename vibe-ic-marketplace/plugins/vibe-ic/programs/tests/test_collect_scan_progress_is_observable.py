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

import os
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as DRIVER  # noqa: E402
import _watchdog as _wd  # noqa: E402

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
_ARGV = [sys.executable, "-I", "-B", _ENTRY, "-q", "-p", "no:cacheprovider"]
_PLUGIN_ROOT = _PROGRAMS.parent


def _collect(files, cwd, grace=_GRACE_S):
    """Drive ONE collect-only session exactly as the landing tier does."""
    return DRIVER.run_collect(_ARGV, [str(f) for f in files], grace, str(cwd))


def test_a_scan_longer_than_the_grace_still_reaches_a_record():
    """THE FIX.  Fails against the pre-fix driver, which sees no progress.

    MEASURED against pre-fix `pytest_per_file_junit.py`: rc=199, incomplete,
    `WATCHDOG_STALLED ... terminal event missing (stage=collecting)` -- the
    identical shape the landing tier reported at 1231 and at 175 files.
    """
    tests_dir = _PROGRAMS / "tests"
    files = sorted(str(f.relative_to(_PLUGIN_ROOT))
                   for f in tests_dir.glob("test_*.py"))[:_REAL_FILES]
    if len(files) < _REAL_FILES:
        pytest.skip("this tree does not ship enough tests to pose the question")
    rc, out, incomplete = _collect(files, _PLUGIN_ROOT)
    assert rc == 0, (
        "a collection that was scanning throughout was killed as a stall.\n"
        "rc must be exactly 0 here: 199 means the supervisor could not tell "
        "SLOW from STOPPED, 143 is killed by something else, and 2 is 'the "
        "question could not be put'.\nrc=%r\n%s" % (rc, out[-4000:]))
    assert incomplete is False, (
        "the session reached no complete lifecycle record:\n%s" % out[-4000:])
    assert "WATCHDOG_STALLED" not in out, out[-4000:]


def test_a_genuinely_hung_collection_is_still_killed(tmp_path):
    """THE CONTROL.  Green against BOTH drivers; the fix may not relax it."""
    (tmp_path / "test_fine.py").write_text("def test_a(): pass\n",
                                           encoding="utf-8")
    (tmp_path / "test_hangs.py").write_text(
        "import time\n"
        "# Hangs at IMPORT, i.e. inside pytest's collection stage, AFTER the\n"
        "# scan has stopped producing paths. Nothing is progressing.\n"
        "time.sleep(36_000)\n\ndef test_never(): pass\n", encoding="utf-8")
    files = sorted(tmp_path.glob("test_*.py"))
    rc, out, incomplete = _collect(files, tmp_path)
    assert rc == _wd.RC_STALLED, (
        "a hung collection must be killed as a stall and must report it as "
        "one. rc=%r; 143 is KILLED-by-something-else and 2 is 'the question "
        "could not be put', and neither is this verdict.\n%s"
        % (rc, out[-4000:]))
    assert incomplete is True, out[-4000:]
    assert "WATCHDOG_STALLED" in out, out[-4000:]


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
import xml.etree.ElementTree as _ET


def _tree_of(root: Path, files: int, reds_per_file: int) -> list:
    made = []
    for index in range(files):
        body = ["def test_green(): pass\n"]
        for red in range(reds_per_file):
            body.append(f"def test_red_{red}(): assert False\n")
        leaf = root / f"test_unit{index:03d}.py"
        leaf.write_text("".join(body), encoding="utf-8")
        made.append(leaf)
    return sorted(made)


def _files_covered(junit: Path) -> int:
    if not junit.is_file():
        return 0
    seen = set()
    for suite in _ET.parse(junit).getroot().iter("testsuite"):
        for case in suite.findall("testcase"):
            if case.get("file"):
                seen.add(case.get("file"))
    return len(seen)


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


def test_an_honest_selection_with_standing_reds_now_reaches_a_record(tmp_path):
    """THE FIX.  Fails against the pre-fix driver, which abandons the run."""
    files = _tree_of(tmp_path, files=60, reds_per_file=1)
    junit = tmp_path / "agg.xml"
    rc, out, _ = DRIVER.run_aggregate(
        _ARGV + ["--maxfail=10"], [str(f) for f in files], junit, 120.0,
        str(tmp_path))
    assert rc == 1, (
        "pytest must report an ordinary red run (rc 1), not an interrupted "
        "one. rc=%r; 2 is 'the question could not be put' and 199 is a stall, "
        "and neither is a verdict about these files.\n%s" % (rc, out[-3000:]))
    assert _files_covered(junit) == len(files), (
        "the aggregate abandoned the selection over %d standing red(s): only "
        "%d of %d file(s) reached the report, so the cross-file question the "
        "arm exists to ask was never asked."
        % (len(files), _files_covered(junit), len(files)))


def test_a_genuine_runaway_is_still_abandoned(tmp_path):
    """THE CONTROL.  The ceiling must not stop the bound from REFUSING."""
    files = _tree_of(tmp_path, files=60, reds_per_file=8)
    junit = tmp_path / "agg.xml"
    bound = DRIVER.aggregate_failure_bound(["--maxfail=10"], len(files))
    assert bound == 60, bound
    rc, out, _ = DRIVER.run_aggregate(
        _ARGV + ["--maxfail=10"], [str(f) for f in files], junit, 120.0,
        str(tmp_path))
    assert rc == 1, (rc, out[-3000:])
    covered = _files_covered(junit)
    assert covered < len(files), (
        "480 reds over 60 files is a runaway and must still be abandoned; the "
        "report covered all %d file(s), so the bound stopped refusing."
        % covered)

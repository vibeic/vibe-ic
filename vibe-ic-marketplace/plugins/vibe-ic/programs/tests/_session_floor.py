"""programs/tests/_session_floor.py — the MEASURED cost of an empty pytest session.

WHY THIS EXISTS
===============
`pytest_per_file_junit` starts a forward-progress lease the moment it spawns a
subject (`_watchdog.supervise`: ``last_progress = start``), and the subject's
first validated lifecycle event — ``session_start`` from
``_pytest_progress_plugin`` — can only arrive once the interpreter and pytest
have finished starting.  Nothing the subject does can renew a window that
expires before that point.  A stall-window test whose window is shorter than
this environment's start-up is therefore not measuring renewal at all: it
measures the interpreter, and its colour is decided by which box runs it.

MEASURED 2026-09-02 at 14de9b8a36 (v1.15.97).  In the pinned image
(``vibeic-eda@sha256:66c33ff2…``, ``PYTHONDONTWRITEBYTECODE=1``) a bare
``python3 -m pytest`` reaches its own argument parser 0.43–0.45 s after spawn;
on 8HD-9's host python, 0.48 s.  The stall-window tests in
``test_pytest_per_file_junit.py`` and ``test_flow_matrix_coverage.py`` declared
windows of 0.25 / 0.30 / 0.35 / 0.45 / 0.50 s.  The three shortest were red on
BOTH lanes, 3 of 3 runs each, every one with

    WATCHDOG_STALLED: … did not advance for > 0.35s
    PROGRESS_PROTOCOL_INCOMPLETE: no pytest progress stream was produced

and an elapsed time equal to the window: killed before pytest existed.  The
0.45 / 0.50 windows flipped with host load (red in 3 of 6 container runs).
Neither the driver nor the plugin is involved: both behaved exactly as
declared, and neither is changed for this.

WHAT THIS IS NOT
================
Not a bound, and not a relaxation.  The window the driver receives is still the
number a test hands it, and every ratio the test relies on — how much of the
window one renewal consumes, how many windows the run must outlive — is
asserted by the test itself against whatever window it ends up with.
``stall_window(nominal)`` returns ``nominal`` wherever the interpreter starts
inside it, and lifts it to a fixed multiple of the MEASURED floor where it
cannot.  The kill direction is untouched: a subject that never renews is still
stopped one window after its last event, and the tests that assert THAT
direction run at the same derived window.

The floor is a reading of THIS box under THIS load, taken moments before the
test that uses it; it is cached per process so one file shares one reading.
The multiple covers the interval between the reading and the run, not host
speed — host speed is what the reading is.
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]

#: How many measured floors a too-short window is lifted to.
FLOOR_MULTIPLE = 2.0

#: Environment a subject inherits from an ENCLOSING per-file driver.  The
#: calibration session must not see these: with them set, the progress plugin
#: would append this session's stream into the enclosing driver's private
#: progress directory, and that driver would then be validating a stream it
#: never spawned.  ``PYTEST_ADDOPTS`` is dropped because the tests that set it
#: (``-s``) are configuring their SUBJECT, not the floor.
_INHERITED = (
    "VIBEIC_PYTEST_PROGRESS_DIR",
    "VIBEIC_PYTEST_PROGRESS_NONCE",
    "VIBEIC_PYTEST_RUNTIME_IDENTITY",
    "PYTEST_ADDOPTS",
)


def _one_trivial_session_s(cwd: Path) -> float:
    """Spawn-to-exit seconds of a green one-test session, the driver's shape."""
    env = {k: v for k, v in os.environ.items() if k not in _INHERITED}
    env["PYTHONPATH"] = (
        str(_PROGRAMS) if not env.get("PYTHONPATH")
        else str(_PROGRAMS) + os.pathsep + env["PYTHONPATH"])
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider", "-p", "_pytest_progress_plugin",
         "test_floor.py"],
        cwd=str(cwd), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, (
        "the calibration session must be a green one-test session, or the "
        f"floor is a reading of a failure, not of start-up; rc={proc.returncode}"
        f"\n{proc.stdout[-2000:]}")
    return elapsed


@functools.lru_cache(maxsize=None)
def trivial_session_s() -> float:
    """Seconds an empty one-test pytest session costs HERE, spawn to exit.

    The larger of two consecutive measurements, so one lucky start does not set
    the floor for the whole file.  An upper bound on spawn-to-``session_start``:
    the calibration session also collects, runs and tears down one item.
    """
    with tempfile.TemporaryDirectory(prefix="vibeic-session-floor-") as d:
        cwd = Path(d)
        (cwd / "test_floor.py").write_text(
            "def test_floor():\n    assert True\n", encoding="utf-8")
        return max(_one_trivial_session_s(cwd) for _ in range(2))


def stall_window(nominal: float, *, starts: int = 1) -> float:
    """``nominal`` where the interpreter starts inside it; else lifted.

    The lift is to ``FLOOR_MULTIPLE`` measured floors PER INTERPRETER START,
    never to a constant, so a fast host keeps the nominal window and a slow one
    gets exactly what its own start-up requires.  Callers scale their renewal
    cadence from the value returned, which keeps every ratio they assert intact.

    ``starts`` is how many interpreter start-ups happen IN SERIES between this
    lease's spawn and the first validated event that can renew it.  A subject
    pytest is one.  A subject that is itself a test which drives the per-file
    driver is two: the driver's interpreter, then the pytest it spawns, and
    only that grandchild's events reach the outer relay -- MEASURED at load 27
    on 8HD-9 (floor 0.73 s): the nested tests' outer lease at 2x the floor
    expired at 0.91 s with `terminal event missing (stage=running)` while the
    grandchild was still starting.
    """
    if not isinstance(starts, int) or starts < 1:
        raise ValueError(f"starts must be a positive int, got {starts!r}")
    return max(float(nominal), FLOOR_MULTIPLE * starts * trivial_session_s())

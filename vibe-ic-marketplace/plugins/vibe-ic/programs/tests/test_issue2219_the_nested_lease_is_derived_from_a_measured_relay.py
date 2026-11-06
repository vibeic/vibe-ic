"""The lease over a NESTED DRIVER LANE is derived from a measured relay
(vibe-ic#2219).

WHAT WAS WRONG. `test_nested_validated_progress_is_relayed_to_the_outer_session`
held its subject under `stall_window(2.5, starts=2)`. Every event that can
renew THAT lease arrives through the subject's `--progress-relay`, and
`stall_window` has no term that grows when the relay lane gets slower: its lift
is `FLOOR_MULTIPLE * starts * trivial_session_s()`, and `trivial_session_s` is
a bare pytest session. Whether that product happened to cover the lane was
decided by how fast this box starts an interpreter, which is why the test was
RED at `--cpus=1` and GREEN at `--cpus=4` on main and on `next/cyregress`
alike.

MEASURED 2026-09-09 on 8HD-9, live main 6883a9c93 (v1.20.7), pinned image
`vibeic-eda@sha256:89a8fd72…`, `--cpus=1 --memory=8g --pids-limit=1024`. The
driver deletes its private progress directory; it was kept, and every
inter-event gap of the outer lease read off it:

    1.1059  SPAWN -> session_start                     one interpreter start
    0.4705  collect_scan -> item_collected
    0.0002  item_collected -> collection_finish
    2.9234  collection_finish -> matrix-outcome-relay 1        <-- THE SILENCE
    0.0000  x82 relay scores, all sub-millisecond
    1.3084  matrix-outcome-modules 2 -> relay 83  the 2nd wave's lane, warm

`pytest_runtest_logstart` emits NOTHING (it only records the nodeid), so the
whole item preamble is silent BY CONSTRUCTION: between `collection_finish` and
the first relayed score there is no event the protocol could produce. In that
2.9234 s the subject starts, runs its OWN `stall_window(0.45)` — two more
pytest sessions, because the floor is `max(... for _ in range(2))` — and then
starts a driver, which starts a pytest, whose first event becomes a relay score
one probe poll later and an outer `domain_progress` one reader poll after that.

`FLOOR_MULTIPLE * 2 * trivial_session_s` covers 2.9234 s only when
`trivial_session_s >= 0.7308`. The same host read 0.7375 and 0.7990 and 0.7770
within one hour. The colour was the machine's, which is the defect.

BOTH DIRECTIONS ON THE REAL SUBJECT, made deterministic by pinning the box to
each side of that line instead of re-rolling the die (`--cpus=1`, load 13):

    window 2.5   (what the old expression yields at session=0.60)
        rc 199, incomplete, WATCHDOG_STALLED … since_last_progress_s=2.518
    window 5.0262 (`relay_window(2.5)`, same box, same run)
        rc 0, complete, elapsed 15.826 s

The RED arm reproduces the issue's own failure line to the third decimal.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _session_floor as _floor            # noqa: E402


class _pinned:
    """Pin the two floors to declared readings for the length of a block."""

    def __init__(self, *, session: float, relay: float):
        self._session, self._relay = session, relay

    def __enter__(self):
        self._real = (_floor.trivial_session_s, _floor.trivial_relay_s)
        _floor.trivial_session_s = lambda *a, **k: self._session
        _floor.trivial_relay_s = lambda *a, **k: self._relay
        return self

    def __exit__(self, *exc):
        _floor.trivial_session_s, _floor.trivial_relay_s = self._real
        return False



def _old_model(nominal: float, starts: int) -> float:
    """What ``stall_window(nominal, starts=N)`` COMPUTED before #2219's second
    half refused it.

    Reproduced from the module's own constants rather than called, because the
    call now raises -- which is the repair, not a loss of coverage. The
    property these tests assert is untouched and is stated here as plainly as
    before: this number reads ``trivial_session_s`` and therefore cannot move
    when the relay lane does.
    """
    return max(float(nominal),
               _floor.FLOOR_MULTIPLE * starts * _floor.trivial_session_s())


def test_the_window_moves_with_the_NESTED_LANE_and_the_old_model_cannot():
    """THE LOAD-BEARING GUARD, and the one a revert reddens.

    Hold the interpreter start-up FIXED and make only the nested relay lane
    slower. The quantity the lease must cover has changed; a derivation that
    reads the lane moves with it and one that reads a bare pytest session
    cannot. `stall_window(..., starts=2)` returning the SAME number for both
    boxes is not a rounding difference — it is the whole defect, stated as an
    equality so it cannot be argued with.
    """
    with _pinned(session=0.40, relay=0.50):
        old_fast = _old_model(2.5, starts=2)
        new_fast = _floor.relay_window(2.5)
    with _pinned(session=0.40, relay=5.00):
        old_slow = _old_model(2.5, starts=2)
        new_slow = _floor.relay_window(2.5)

    assert old_fast == old_slow, (old_fast, old_slow)
    assert new_slow > new_fast, (new_fast, new_slow)
    # And it does not merely move -- it covers the lane it was told about.
    assert new_slow >= _floor.FLOOR_MULTIPLE * 5.00, new_slow
    # The measured case: a lane of 2.2041 s is NOT covered by the old model on
    # a box whose pytest start-up is 0.60 s, and IS covered by the new one.
    with _pinned(session=0.60, relay=2.2041):
        assert _old_model(2.5, starts=2) < 2.9234
        assert _floor.relay_window(2.5) > 2.9234


def test_a_nominal_above_the_measured_relay_floor_is_DECLARED_not_lifted():
    """Nothing is relaxed and nothing is inflated.

    The sibling assertion of `test_a_window_below_the_measured_session_floor_
    is_lifted_not_declared`: on a box where the lane arrives well inside the
    nominal window, the caller keeps EXACTLY the window it declared, so a fast
    host still runs the tight bound the test author chose.
    """
    with _pinned(session=0.40, relay=0.50):
        assert _floor.relay_window(2.5) == 2.5
        assert _floor.relay_window(100.0) == 100.0
    with _pinned(session=0.40, relay=1.25):
        # Exactly at the boundary the lift and the nominal agree, and the
        # function must not step past it.
        assert _floor.relay_window(2.5) == 2.5


def test_a_calibration_that_relays_NOTHING_refuses_instead_of_reading_zero(
        tmp_path, monkeypatch):
    """An unmeasured quantity must not arrive as a measured zero.

    A green nested lane that never wrote a relay byte is not "a lane that
    relayed instantly"; it is a lane nobody observed. `_one_trivial_relay_s`
    must say so rather than return a number, because a 0 here would silently
    make `relay_window` the identity and put the whole defect back with a
    measurement's name on it.
    """
    silent = tmp_path / "silent_driver.py"
    silent.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    monkeypatch.setattr(_floor, "_DRIVER", silent)
    with pytest.raises(AssertionError, match="NO relayed score"):
        _floor._one_trivial_relay_s(tmp_path)


def test_the_relay_floor_is_a_READING_of_a_real_nested_lane(tmp_path):
    """The number is taken, not modelled — proven by taking it.

    This really spawns the pytest that computes a floor and drives a real
    `pytest_per_file_junit.py` through `--progress-relay`, and the reading is
    bounded BELOW by the wall time that took: a stub that returned a constant
    could satisfy every other assertion in this file and would fail here.
    """
    import time
    started = time.monotonic()
    reading = _floor._one_trivial_relay_s(tmp_path)
    wall = time.monotonic() - started
    assert reading > 0.0, reading
    # The reading is the span up to the FIRST relayed score, so it can only be
    # a part of the wall time the whole calibration took -- never more, and
    # never a constant unrelated to it.
    assert reading <= wall, (reading, wall)
    assert reading >= 0.5 * _floor.trivial_session_s(), (
        reading, _floor.trivial_session_s())

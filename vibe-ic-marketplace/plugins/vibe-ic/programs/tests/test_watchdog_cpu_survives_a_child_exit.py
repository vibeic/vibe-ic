"""The progress watchdog must not go blind when a measured child exits.

MEASURED, chip-AGNOSTIC. A 780k-cell synthesis was killed by
`_watchdog.run_supervised` with

    WATCHDOG_STALLED: no forward progress (output+CPU idle) for > 1800s
                      — killed as hung, not slow.

while the tool was pegged at 100% CPU, in state `R`, with zero voluntary
context switches. The claim in that message was false, and the mechanism is
entirely general:

  * `_docker_watchdog.container_cpu_seconds` sums the CPU of the process TREE
    that is ALIVE RIGHT NOW under the marked root.
  * `yosys` performs its heavy work in a child, `yosys-abc`, and invokes it
    ONCE PER ABC PASS — i.e. as a sequence of children, not one long one.
  * When ABC #1 exits, its CPU-seconds leave the live-tree sum, so the probe's
    reading FALLS by however much that child had burned.
  * `ProgressMeter` used to fold CPU in as a running MAXIMUM. A fall therefore
    froze the fused score until the next child re-earned the whole drop.
  * `yosys` emits nothing while ABC runs (block-buffered), so output and the
    tee'd log are both flat. CPU was the only live signal, and it had been
    blinded — the supervisor then killed a perfectly healthy job.

The tool class is what makes this general: ANY supervised tool that spawns its
work as successive children (a compiler driver, a partitioned solver, a
per-corner STA loop) has the same shape. The regression below is written
against the PUBLIC behaviour — the fused score and the supervisor's verdict —
not against the internal attribute names, so an alternative correct fix passes
it too.

No design, PDK, vendor or benchmark identifier appears in this file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _watchdog as wd  # noqa: E402


POLL = 30.0
GRACE = 1800.0


def _drive(cpu_readings, *, size=1000.0, log=(1000, 1.0)):
    """Feed a fixed CPU sequence through a meter with a FROZEN output+log
    (the measured condition — the tool is silent while its child computes)."""
    seq = list(cpu_readings)
    box = {"i": 0}

    def cpu_fn():
        i = min(box["i"], len(seq) - 1)
        box["i"] += 1
        return seq[i]

    meter = wd.ProgressMeter(size_fn=lambda: size,
                             log_fn=lambda: log,
                             cpu_fn=cpu_fn)
    return [meter.sample() for _ in range(len(seq))]


def test_a_child_exit_does_not_freeze_the_score():
    """The regression itself: child #1 burns a lot, exits, child #2 starts."""
    child1 = [100.0 + k * POLL for k in range(60)]      # 1800 CPU-s accrued
    # child #1 exits -> its CPU leaves the live-tree sum -> the reading FALLS
    child2 = [100.0 + k * POLL for k in range(60)]
    # premise check on the FIXTURE: the raw probe really does drop at the seam
    assert child2[0] < child1[-1], "fixture does not model a child exit"

    scores = _drive(child1 + child2)
    after_drop = scores[len(child1):]
    # Every subsequent poll must ADVANCE — the second child is burning CPU.
    for a, b in zip(after_drop, after_drop[1:]):
        assert b > a, (
            "the fused score froze after a measured child exited; the CPU "
            "signal has gone blind and a healthy job will be killed as hung")


def test_the_supervisor_does_not_kill_a_child_that_is_burning_cpu():
    """End-to-end through the plugin's own supervise(), with a fake clock."""
    child1 = [100.0 + k * POLL for k in range(300)]     # 9000 CPU-s
    child2 = [100.0 + k * POLL for k in range(300)]
    seq = child1 + child2
    box = {"i": 0}

    def cpu_fn():
        i = min(box["i"], len(seq) - 1)
        box["i"] += 1
        return seq[i]

    meter = wd.ProgressMeter(size_fn=lambda: 1000.0,
                             log_fn=lambda: (1000, 1.0),
                             cpu_fn=cpu_fn)

    class _Proc:
        def wait(self, timeout=None):
            raise wd.subprocess.TimeoutExpired("x", timeout)

    clock = {"t": 0.0}
    killed = {}

    def _wait(proc, timeout):
        clock["t"] += timeout
        # Stop once the whole sequence has been consumed: the job "finished".
        return 0 if box["i"] >= len(seq) else None

    outcome, _rc = wd.supervise(
        _Proc(), meter.sample, lambda p, r: killed.setdefault("r", r),
        poll_s=POLL, stall_grace_s=GRACE, hard_ceiling_s=10 * 3600.0,
        wait_fn=_wait, clock=lambda: clock["t"])

    assert outcome != "stalled", (
        f"a job burning CPU throughout was killed as stalled "
        f"(kill reason {killed.get('r')!r}) — the CPU progress signal is blind "
        f"across a child exit")
    assert "r" not in killed, killed


def test_a_genuinely_hung_job_is_still_killed():
    """The property the ratchet existed to protect must survive the fix."""
    frozen = [500.0] * 200                     # CPU pegged at a constant: hung
    box = {"i": 0}

    def cpu_fn():
        i = min(box["i"], len(frozen) - 1)
        box["i"] += 1
        return frozen[i]

    meter = wd.ProgressMeter(size_fn=lambda: 1000.0,
                             log_fn=lambda: (1000, 1.0),
                             cpu_fn=cpu_fn)

    class _Proc:
        def wait(self, timeout=None):
            raise wd.subprocess.TimeoutExpired("x", timeout)

    clock = {"t": 0.0}
    killed = {}

    def _wait(proc, timeout):
        clock["t"] += timeout
        return None

    outcome, _rc = wd.supervise(
        _Proc(), meter.sample, lambda p, r: killed.setdefault("r", r),
        poll_s=POLL, stall_grace_s=GRACE, hard_ceiling_s=10 * 3600.0,
        wait_fn=_wait, clock=lambda: clock["t"])

    assert outcome == "stalled", outcome
    assert killed.get("r") == "stalled", killed
    assert clock["t"] >= GRACE


def test_a_none_flapping_probe_is_still_not_progress():
    """The other property the ratchet protected: None <-> frozen must not
    reset the grace clock (the docstring's stated invariant)."""
    flap = []
    for _ in range(200):
        flap.extend([None, 500.0])
    box = {"i": 0}

    def cpu_fn():
        i = min(box["i"], len(flap) - 1)
        box["i"] += 1
        return flap[i]

    meter = wd.ProgressMeter(size_fn=lambda: 1000.0,
                             log_fn=lambda: (1000, 1.0),
                             cpu_fn=cpu_fn)
    scores = [meter.sample() for _ in range(len(flap))]
    assert len(set(scores[2:])) == 1, (
        "a probe alternating None/frozen produced a CHANGING score — that "
        "resets the grace clock every poll and lets a hung job squat")


def test_the_score_is_monotonic_non_decreasing_under_a_falling_probe():
    """The class contract: whatever the raw probe does, the score never falls."""
    readings = [0.0, 100.0, 400.0, 900.0, 50.0, 60.0, 70.0, 10.0, 20.0]
    scores = _drive(readings)
    for a, b in zip(scores, scores[1:]):
        assert b >= a, (scores,)


@pytest.mark.parametrize("child_cpu", [60.0, 1800.0, 7400.0])
def test_the_freeze_window_does_not_scale_with_the_departed_childs_cpu(
        child_cpu):
    """The severity tell: under the defect the blind window equalled the
    exited child's CPU, so BIGGER jobs were killed and small ones were not.
    After the fix the first post-exit poll advances regardless of size."""
    n = int(child_cpu / POLL)
    child1 = [100.0 + k * POLL for k in range(n)]
    child2 = [100.0 + k * POLL for k in range(4)]
    scores = _drive(child1 + child2)
    tail = scores[len(child1):]
    assert tail[1] > tail[0], (
        f"after a child worth {child_cpu:g} CPU-s exited, the very next poll "
        f"did not register progress — the blind window still scales with the "
        f"departed child's CPU")

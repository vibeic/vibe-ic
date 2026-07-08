"""tests/test_watchdog.py — the GENERAL, reusable progress-stall primitive
(`_watchdog.py`), tested in ISOLATION from phase3/EDA (owner directive v1.3.47).

Proves the primitive on its own — with injected fake progress + kill callbacks
and (for the real-launch path) plain host sub-processes — so it is demonstrably
reusable by ANY future caller (`loop_guard`, other runners), not only through
phase3. Four headline behaviours + the None-flap fix + carry-forward fusion:
  1. progressing-not-killed   — output/CPU advances past the grace → natural.
  2. hung-killed              — silent + idle past the grace → RC_STALLED.
  3. cpu-silent-not-killed    — busy loop, no output → CPU-advance keeps it
                                alive; only the ceiling stops it (OR-of-signals).
  4. fast-normal-natural-rc   — a quick process returns its rc; no kill.
All timing is injected (fake clock/wait) or compressed so the suite runs fast.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _watchdog as W  # noqa: E402


def _local_cpu_ticks(pid: int):
    """utime+stime (ticks) of a local pid from /proc/<pid>/stat, or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            after = f.read().rsplit(")", 1)[1].split()
        return int(after[11]) + int(after[12])
    except Exception:
        return None


class _KillCounter:
    def __init__(self, proc=None):
        self.proc = proc
        self.calls = []

    def __call__(self, proc, reason):
        self.calls.append(reason)
        try:
            (self.proc or proc).kill()
        except Exception:
            pass


# ── ProgressMeter: fusion, carry-forward, strict-increase, None-flap ─────────

def test_meter_output_growth_is_progress():
    box = {"n": 0}
    m = W.ProgressMeter(size_fn=lambda: box["n"])
    a = m.sample()
    box["n"] = 10
    assert m.sample() > a


def test_meter_cpu_counts_only_strict_increase_and_carries_forward():
    seq = iter([0.0, 100.0, 100.0, 90.0, 150.0])
    m = W.ProgressMeter(size_fn=lambda: 0, cpu_fn=lambda: next(seq))
    s = [m.sample() for _ in range(5)]
    assert s == [0.0, 100.0, 100.0, 100.0, 150.0], s


def test_meter_none_flap_is_never_progress():
    """A CPU probe flapping None ↔ FROZEN value must NOT register progress
    every poll (the defect that would let a hung job squat until the ceiling).
    After the first reading the score is pinned."""
    seq = iter([None, 500.0, None, 500.0, None, 500.0])
    m = W.ProgressMeter(size_fn=lambda: 0, cpu_fn=lambda: next(seq, 500.0))
    s = [m.sample() for _ in range(6)]
    assert s == [0.0, 500.0, 500.0, 500.0, 500.0, 500.0], s
    assert len(set(s[1:])) == 1


def test_meter_log_event_counts_on_change():
    box = {"sig": (0, 0.0)}
    m = W.ProgressMeter(log_fn=lambda: box["sig"])
    a = m.sample()               # primes last_log
    box["sig"] = (10, 1.0)
    b = m.sample()               # size+mtime changed → +1 event
    box["sig"] = (10, 2.0)
    c = m.sample()               # mtime advanced → +1 event
    assert b > a and c > b


# ── supervise(): deterministic fake-clock control-loop proofs ────────────────

class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def advance(self, dt):
        self.t += dt
        return self.t

    def __call__(self):
        return self.t


class _RunningProc:
    """poll()/wait() report 'still running' until `finish_at` polls elapse."""
    def __init__(self, finish_after=None):
        self.finish_after = finish_after
        self.polls = 0
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.polls += 1
        if self.finish_after is not None and self.polls >= self.finish_after:
            return 0
        raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)

    def kill(self):
        self.killed = True


def test_supervise_hung_is_stalled_with_fake_clock():
    clk = _FakeClock()
    proc = _RunningProc()          # never finishes

    def wait_fn(p, t):
        clk.advance(t)             # advance fake clock by the poll window
        return None                # never exits

    meter = W.ProgressMeter(size_fn=lambda: 0)   # no signal ever
    killer = _KillCounter(proc)
    outcome, rc = W.supervise(
        proc, meter.sample, killer,
        poll_s=10, stall_grace_s=100, hard_ceiling_s=100_000,
        wait_fn=wait_fn, clock=clk)
    assert outcome == "stalled"
    assert killer.calls == ["stalled"]
    assert clk.t <= 200            # near the grace, not the ceiling
    assert proc.killed


def test_supervise_progressing_runs_to_natural_exit():
    clk = _FakeClock()
    state = {"cpu": 0.0}
    proc = _RunningProc()

    def wait_fn(p, t):
        clk.advance(t)
        p.polls += 1
        return 0 if p.polls >= 20 else None   # natural exit after 20 polls

    def cpu():
        state["cpu"] += 5.0        # strictly increasing → always progress
        return state["cpu"]

    meter = W.ProgressMeter(size_fn=lambda: 0, cpu_fn=cpu)
    killer = _KillCounter(proc)
    outcome, rc = W.supervise(
        proc, meter.sample, killer,
        poll_s=10, stall_grace_s=100, hard_ceiling_s=100_000,
        wait_fn=wait_fn, clock=clk)
    assert outcome == "natural"
    assert rc == 0
    assert killer.calls == []


def test_supervise_ceiling_backstops_cpu_burning_loop():
    clk = _FakeClock()
    proc = _RunningProc()
    state = {"cpu": 0.0}

    def wait_fn(p, t):
        clk.advance(t)
        return None

    def cpu():
        state["cpu"] += 1.0        # always burning → never stalls
        return state["cpu"]

    meter = W.ProgressMeter(size_fn=lambda: 0, cpu_fn=cpu)
    killer = _KillCounter(proc)
    outcome, rc = W.supervise(
        proc, meter.sample, killer,
        poll_s=10, stall_grace_s=100, hard_ceiling_s=1000,
        wait_fn=wait_fn, clock=clk)
    assert outcome == "ceiling"
    assert killer.calls == ["ceiling"]
    assert clk.t > 100             # lived well past the grace


# ── run_supervised(): real host sub-processes + injected cpu_probe ───────────

def test_run_supervised_progressing_output_not_killed():
    """A process printing to STDOUT every 0.2s for ~3s (well past the grace)
    is kept alive by the captured-output-growth signal → natural exit rc=0."""
    child = ("import sys,time\n"
             "for i in range(15):\n"
             "    sys.stdout.write('line %d\\n'%i); sys.stdout.flush()\n"
             "    time.sleep(0.2)\n")
    res = W.run_supervised(
        [sys.executable, "-c", child],
        stall_grace_s=1.0, poll_s=0.3, hard_ceiling_s=60.0)
    assert res.outcome == "natural", res.err
    assert res.rc == 0
    assert "line 14" in res.out


def test_run_supervised_hung_is_stalled():
    res = W.run_supervised(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stall_grace_s=1.0, poll_s=0.2, hard_ceiling_s=60.0)
    assert res.outcome == "stalled"
    assert res.rc == W.RC_STALLED
    assert res.elapsed_s < 6.0
    assert "WATCHDOG_STALLED" in res.err


def test_run_supervised_cpu_silent_not_killed_before_ceiling():
    """A silent busy loop (no stdout) is kept alive by the injected CPU probe;
    only the ceiling stops it — proves progress = output OR CPU."""
    proc_pid = {"pid": None}

    def cpu_probe(proc):
        proc_pid["pid"] = proc.pid
        return _local_cpu_ticks(proc.pid)

    res = W.run_supervised(
        [sys.executable, "-c", "x=0\nwhile True:\n    x+=1"],
        stall_grace_s=1.5, poll_s=0.3, hard_ceiling_s=4.5, cpu_probe=cpu_probe)
    assert res.outcome == "ceiling", res.err
    assert res.rc == W.RC_CEILING
    assert res.elapsed_s > 2.5     # CPU signal carried it past the 1.5s grace


def test_run_supervised_fast_normal_natural_rc_no_kill():
    res = W.run_supervised(
        [sys.executable, "-c", "print('done')"],
        stall_grace_s=5.0, poll_s=0.3, hard_ceiling_s=60.0)
    assert res.outcome == "natural"
    assert res.rc == 0
    assert "done" in res.out


def test_run_supervised_nonzero_rc_propagates():
    res = W.run_supervised(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        stall_grace_s=5.0, poll_s=0.3, hard_ceiling_s=60.0)
    assert res.outcome == "natural"
    assert res.rc == 7


def test_run_supervised_bytes_output_decoded_to_str():
    """Non-UTF8 bytes in the captured stream are decoded (never returned as
    bytes) so callers' `out + err` never raises — the v0.2.36 hygiene, now in
    the shared module."""
    child = (r"import sys,os" "\n"
             r"os.write(1, b'partial \xff route output')" "\n")
    res = W.run_supervised([sys.executable, "-c", child],
                           stall_grace_s=5.0, poll_s=0.3, hard_ceiling_s=60.0)
    assert isinstance(res.out, str) and isinstance(res.err, str)
    _ = res.out + res.err          # must not raise
    assert "partial" in res.out


def test_run_supervised_launch_error_returns_127():
    res = W.run_supervised(["/no/such/binary/xyzzy"],
                           stall_grace_s=5.0, poll_s=0.3, hard_ceiling_s=60.0)
    assert res.rc == 127
    assert res.outcome == "launch_error"
    assert "COMMAND_NOT_FOUND" in res.err


def test_run_supervised_custom_kill_callback_invoked():
    calls = []

    def kill(proc, reason):
        calls.append(reason)
        proc.kill()

    res = W.run_supervised(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stall_grace_s=1.0, poll_s=0.2, hard_ceiling_s=60.0, kill=kill)
    assert res.rc == W.RC_STALLED
    assert calls == ["stalled"]


def test_public_api_constants():
    assert W.RC_STALLED == 199 and W.RC_STALLED != W.RC_CEILING
    assert W.RC_CEILING == 124
    assert W.DEFAULT_STALL_GRACE_S == 1800
    assert W.DEFAULT_HARD_CEILING_S == 86_400
    assert W.DEFAULT_POLL_S == 30

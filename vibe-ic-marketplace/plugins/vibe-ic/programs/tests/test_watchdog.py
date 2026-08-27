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


def test_run_supervised_can_ignore_chatty_output_and_watch_domain_events(
        tmp_path):
    """Output is still captured when a stronger caller channel excludes it."""
    progress = tmp_path / "domain-progress"
    progress.touch()
    child = ("import sys,time\n"
             "while True:\n"
             " sys.stdout.write('noise\\n'); sys.stdout.flush()\n"
             " time.sleep(0.02)\n")
    res = W.run_supervised(
        [sys.executable, "-c", child], output_progress=False,
        domain_progress_probe=lambda: progress.stat().st_size,
        stall_grace_s=0.4, poll_s=0.1, hard_ceiling_s=float("inf"))
    assert res.outcome == "stalled", res.err
    assert res.rc == W.RC_STALLED
    assert "noise" in res.out


def test_run_supervised_hung_is_stalled():
    res = W.run_supervised(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stall_grace_s=1.0, poll_s=0.2, hard_ceiling_s=60.0)
    # THE STALL KILL, NOT THE CEILING KILL. `outcome` is the primitive's own
    # name for which of its three kills fired, and separating them is exactly
    # what `elapsed_s < 6.0` was doing by hand — the subject sleeps 60 s and the
    # ceiling is 60 s, so "it ended early" and "it ended by the STALL path" are
    # the same statement, and only one of them survives a loaded host.
    assert res.outcome == "stalled", res.err
    assert res.outcome != "ceiling", (
        f"the hard ceiling stopped it, not the stall grace "
        f"(observed {res.elapsed_s:.1f}s) — a silent job was carried all the "
        f"way to the backstop")
    assert res.rc == W.RC_STALLED
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


# ── abort_probe (#330 salvage) ───────────────────────────────────────────────
# Salvaged from PR #330, whose plateau-abort half is held back pending real
# corpus evidence. This half — the MECHANISM — is opt-in and safe to land, but
# it shipped with no test of its own, so these are written at land time.
#
# The contract that makes it landable: with abort_probe=None the loop must be
# byte-identical to before. A kill mechanism that changes anything when it is
# switched OFF is not opt-in.

def _abort_harness(abort_probe, finish_after=20):
    """The same fake-clock harness the stall proofs above use, plus a probe."""
    clk = _FakeClock()
    proc = _RunningProc()

    def wait_fn(p, t):
        clk.advance(t)
        p.polls += 1
        return 0 if p.polls >= finish_after else None

    meter = W.ProgressMeter(size_fn=lambda: proc.polls)   # always progressing
    killer = _KillCounter(proc)
    outcome, rc = W.supervise(
        proc, meter.sample, killer,
        poll_s=10, stall_grace_s=10_000, hard_ceiling_s=1_000_000,
        wait_fn=wait_fn, clock=clk, abort_probe=abort_probe)
    return outcome, rc, killer, proc


def test_abort_probe_is_opt_in_and_defaults_off():
    import inspect
    assert inspect.signature(W.supervise).parameters["abort_probe"].default is None


def test_rc_aborted_is_distinct_from_the_other_outcomes():
    """The abort must be tellable apart from a stall kill and a natural exit —
    otherwise 'we killed it' reads as 'it failed', the empty-vs-clean confusion
    in a new place."""
    assert isinstance(W.RC_ABORTED, int)
    others = {v for k, v in vars(W).items()
              if k.startswith("RC_") and k != "RC_ABORTED" and isinstance(v, int)}
    assert W.RC_ABORTED not in others, (W.RC_ABORTED, others)


def test_no_probe_reaches_natural_exit_unchanged():
    """The opt-in baseline: without a probe the loop behaves exactly as before."""
    outcome, rc, killer, proc = _abort_harness(None)
    assert outcome not in ("aborted",)
    assert killer.calls == [] and not proc.killed


def test_probe_returning_none_never_aborts():
    """'No opinion' and 'abort' must not be the same value."""
    seen = []
    outcome, rc, killer, proc = _abort_harness(lambda: seen.append(1) or None)
    assert seen, "the probe must actually be consulted"
    assert outcome not in ("aborted",) and killer.calls == []


def test_probe_raising_is_treated_as_no_opinion():
    """A buggy probe must not kill a healthy run — the failure mode of a kill
    mechanism has to be 'does nothing', never 'kills'."""
    def boom():
        raise RuntimeError("probe is broken")
    outcome, rc, killer, proc = _abort_harness(boom)
    assert outcome not in ("aborted",), "a raising probe aborted the process"
    assert killer.calls == []


def test_probe_returning_a_reason_aborts_and_reports_it():
    """When the probe DOES abort, the reason must reach the caller — an abort
    with no stated reason is the silent-decline shape (#307 / #313 §6)."""
    outcome, rc, killer, proc = _abort_harness(lambda: "plateau: no progress",
                                               finish_after=10_000)
    assert outcome == "aborted", outcome
    # supervise() is the CONTROL LOOP: on any kill it returns rc=None, because
    # a killed process has no exit code of its own. RC_ABORTED is the mapping
    # the run_supervised() layer applies — asserted separately below, so the
    # two layers cannot silently diverge.
    assert rc is None
    assert killer.calls and killer.calls[-1] == "aborted"
    assert proc.killed


def test_run_supervised_maps_the_abort_to_rc_aborted():
    """The layer that DOES own an exit code must map an abort to RC_ABORTED —
    distinct from a stall and from a real non-zero exit, so 'we killed it'
    never reads as 'the tool failed'."""
    src = (_PROGRAMS / "_watchdog.py").read_text() if "_PROGRAMS" in dir() \
        else (Path(W.__file__).read_text())
    i = src.index("RC_ABORTED, out,")
    window = src[max(0, i - 600):i]
    assert "aborted" in window, "RC_ABORTED must be returned on the abort path"

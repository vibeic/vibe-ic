"""v1.3.47 — phase3 GLUE for the progress-stall watchdog.

The general supervision primitive lives in `_watchdog.py` (tested end-to-end in
tests/test_watchdog.py). This file covers ONLY the docker/EDA-specific glue that
phase3 injects into it:
  • `_container_cpu_seconds` — the in-container CPU probe (marker-matched `ps`).
  • `_docker_exec` DISPATCH — marker=None → simple raw wall-clock; marker set →
    the SHARED supervised path (`_docker_watchdog.run_docker_supervised`, which
    drives `_watchdog.run_supervised`) with NO outer clock.
  • `_pnr_hard_ceiling_s` — the retired size ESTIMATE repurposed as a HIGH
    backstop ceiling that can never wall-clock-kill a live job.
"""
import inspect
import shlex
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import _watchdog as W  # noqa: E402
import _docker_watchdog as DW  # noqa: E402

# A stamp path pinned for the dispatch assertions; the real one is random.
PIDFILE = "/tmp/.vibeic-job-fedcba9876543210.pid"


# ── _container_cpu_seconds parsing (marker-matched CPU sum) ───────────────────













# ── _docker_exec DISPATCH: raw (short) vs watchdog (long, marker) ─────────────

def test_docker_exec_no_marker_uses_raw(monkeypatch):
    """A plain call (no marker) routes to _docker_exec_raw — the simple bounded
    wall-clock path — untouched, so the ~40 short call sites are unchanged."""
    seen = {}

    def fake_raw(container, cmd, timeout=1800):
        seen["raw"] = (container, timeout)
        return (0, "raw-out", "")

    monkeypatch.setattr(R, "_docker_exec_raw", fake_raw)
    # If it wrongly took the watchdog path this would call run_supervised.
    monkeypatch.setattr(W, "run_supervised",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not supervise a marker-less call")))
    rc, out, err = R._docker_exec("cont", "command -v openroad", timeout=10)
    assert (rc, out) == (0, "raw-out")
    assert seen["raw"] == ("cont", 10)


def test_docker_exec_with_marker_uses_watchdog(monkeypatch):
    """A call WITH a marker routes to _watchdog.run_supervised, and the stall /
    ceiling return codes propagate as (rc, out, err)."""
    captured = {}

    def fake_supervised(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return W.SupervisedResult(W.RC_STALLED, "part-out", "part-err\nWATCHDOG_STALLED",
                                  "stalled", 12.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    monkeypatch.setattr(DW, "new_job_pidfile", lambda: PIDFILE)
    tool = "openroad -exit /p/pnr.tcl"
    rc, out, err = R._docker_exec(
        "cont", tool, marker="/p/pnr.tcl",
        log_path=Path("/p/openroad.log"), stall_grace_s=1234.0,
        hard_ceiling_s=4321.0)
    assert rc == W.RC_STALLED
    assert out == "part-out"
    assert "WATCHDOG_STALLED" in err
    # the injected callbacks + windows were threaded through
    # NEITHER WINDOW MAY BE A DEFAULT — see the same note in
    # test_docker_watchdog.py. `== 1800` is `_WATCHDOG_STALL_GRACE_S`, so it
    # held even with the caller's value dropped (vibe-ic#2097).
    assert captured["kw"]["stall_grace_s"] == 1234.0
    assert R._WATCHDOG_STALL_GRACE_S != 1234.0, "the window went back to a default"
    assert captured["kw"]["hard_ceiling_s"] == 4321.0
    assert R._WATCHDOG_HARD_CEILING_S != 4321.0, "the budget went back to a default"
    assert captured["kw"]["log_path"] == Path("/p/openroad.log")
    assert callable(captured["kw"]["cpu_probe"])
    assert callable(captured["kw"]["kill"])
    # NO OUTER CLOCK on the dispatched command. This line read
    # `"timeout --kill-after=5" in captured["cmd"][-1]` and pinned the wrap
    # #2051 removed and v1.18.28 took out of this file's private dispatch;
    # it is the same stale contract vibe-ic#2097 names in
    # `test_docker_watchdog.py`, one file over.
    inner = captured["cmd"][-1]
    assert "timeout" not in inner, inner
    assert "--kill-after" not in inner, inner
    # the tool is the DIRECT target of `exec`, so the stamped pid is its pid
    sent = R._tool_status_not_the_log_sinks(tool)
    assert inner.rstrip().endswith("exec bash -lc " + shlex.quote(sent)), inner
    # ...and the stamp the reap selects on is what is there instead of a clock
    assert PIDFILE in inner, inner
    assert inner == DW.supervised_container_command(sent, PIDFILE), inner


def test_docker_exec_watchdog_cpu_probe_reads_container(monkeypatch):
    """The injected cpu_probe delegates to the SHARED in-container CPU probe,
    `_docker_watchdog.container_cpu_seconds(container, marker, raw_exec)` — the
    transport glue, not the general module.

    THE SEAM MOVED, AND THIS TEST MOVED WITH IT (vibe-ic#2097, adjacent).
    Until v1.18.28 this file drove its OWN supervised dispatch and injected a
    probe built over `R._container_cpu_seconds`; the dispatch is now the shared
    `_docker_watchdog.run_docker_supervised`, whose `_cpu_probe` calls the
    shared probe directly. `R._container_cpu_seconds` survives as a thin
    delegate for its other callers, so a double placed on IT is no longer on
    this path: the probe returned None and the red read as a broken probe
    rather than as a moved seam. The assertion moves to where the reading is
    actually taken — which is also the stricter direction, because it now fails
    if phase3 ever grows a second, private probe again.

    THE DOUBLE IS CHECKED AGAINST THE REAL SIGNATURE BEFORE IT REPLACES IT.
    The probe gained a `pidfile=` parameter when the reap became
    identity-anchored, and `_cpu_probe` passes it by keyword. A stand-in that
    does not accept it does not make this test measure the glue less — it makes
    the glue raise TypeError inside the closure, so the test fails for the
    stand-in's shape rather than for anything about the transport. Binding the
    parameter names first turns the next such drift into a named refusal here
    instead of a TypeError in the code under test.
    """
    _real_params = set(inspect.signature(DW.container_cpu_seconds).parameters)

    def _cpu_double(container, marker, docker_exec_raw, timeout=15,
                    pidfile=None):
        return 42.0 if marker == "/p/x.tcl" else None

    assert set(inspect.signature(_cpu_double).parameters) >= _real_params, (
        "the cpu-probe stand-in no longer accepts every parameter the real "
        "_docker_watchdog.container_cpu_seconds takes: missing "
        f"{sorted(_real_params - set(inspect.signature(_cpu_double).parameters))}")
    monkeypatch.setattr(DW, "container_cpu_seconds", _cpu_double)
    grabbed = {}

    def fake_supervised(cmd, **kw):
        grabbed["cpu"] = kw["cpu_probe"](object())
        return W.SupervisedResult(0, "", "", "natural", 1.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    R._docker_exec("cont", "tool /p/x.tcl", marker="/p/x.tcl")
    assert grabbed["cpu"] == 42.0


# ── hard-ceiling repurpose: NEVER a wall-clock kill budget ────────────────────





def test_phase3_constants_bind_shared_module():
    assert R._RC_STALLED == W.RC_STALLED == 199
    assert R._WATCHDOG_STALL_GRACE_S == W.DEFAULT_STALL_GRACE_S == 1800
    assert R._WATCHDOG_HARD_CEILING_S == W.DEFAULT_HARD_CEILING_S == 86_400

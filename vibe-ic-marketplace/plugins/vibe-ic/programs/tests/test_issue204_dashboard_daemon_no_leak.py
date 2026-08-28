#!/usr/bin/env python3
"""Regression for #204 — flow_dashboard daemons must not leak, and two
concurrent runs must each get a live dashboard on a DISTINCT port.

Two defects, per the issue:

  1. PROCESS LEAK. Tests (and any caller) that spawn the web dashboard through
     `vibe_ic_one_shot_runner._launch_dashboard` used to leak a DETACHED
     (`start_new_session=True`) daemon that outlives the process — the argv
     shape observed in the wild was pytest-fixture tmp dirs, i.e. the SUITE
     itself leaked ~30 orphan daemons across two hosts. A leaked daemon squats
     the port and stalls later runs. Fix: `_launch_dashboard` honours
     `VIBE_IC_NO_DASHBOARD`, and an autouse conftest fixture sets it for the
     whole suite so no test can ever spawn a real daemon. A dedicated fixture
     (`_dashboard_daemon`) is the ONLY sanctioned way to spawn a real daemon in
     a test — and it REAPS its child on teardown.

  2. HARDCODED PORT. The daemon bound a hardcoded 8787; two legitimate
     concurrent runs collided. v1.3.83 added a retry sweep, but `--port 0`
     (OS-assigned, the robust answer the issue asks for) recorded `:0` instead
     of the real port. Fix: `serve` reads the actually-bound port from the
     socket (`server_address`), so `--port 0` works and the recorded URL is
     always the true port.

A leak check that cannot observe the leak is the bug this repo keeps
re-learning — so every test here BOTH asserts the property AND reaps any child
it spawned, even on the failing path, so the test can never itself leak.

chip-AGNOSTIC: synthetic generic project dirs only; no chip/PDK/vendor literal.
"""
from __future__ import annotations

import contextlib
import os
import signal
import sys
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import vibe_ic_one_shot_runner as orch  # noqa: E402
import _watchdog  # noqa: E402

#: How often the waits below LOOK, never how long they may take. Every bound in
#: this file used to be a wall-clock guess about a HOST — "≤10 s to bind", a 5 s
#: socket timeout — and each of them, on expiry, made the test report the
#: dashboard as broken. That is the manufactured verdict: a daemon that is slow
#: to bind on a loaded box is not a daemon that failed to bind.
_LOOK_S = 0.1
#: Consecutive looks with NO forward progress from the thing being waited on
#: before it is called hung. For the daemon that reading is its own /proc tree
#: (CPU + I/O); for the in-process server it is this process's CPU.
_STALL_LOOKS = 300
#: Pathological backstop, counted in LOOKS, not seconds. A daemon that keeps
#: making progress is never stopped by it.
_MAX_LOOKS = 200_000


#: CLK_TCK once — `/proc` reports thread CPU in clock ticks.
_TICK = float(os.sysconf("SC_CLK_TCK") or 100)


def _server_cpu_s():
    """CPU seconds burned by every thread of this process EXCEPT this one.

    THE WAITER CANNOT BE ITS OWN PROGRESS SIGNAL. The first version of this used
    `sum(os.times()[:2])` — whole-process CPU — and that is wrong in the one
    direction that matters: the retry loop asking "is the server done yet?" also
    burns CPU, so the counter advances on the WAITER's account and a completely
    wedged server keeps looking busy. The stall could then never fire and the
    wait would run to its iteration cap — a hang introduced while removing a
    false verdict. MEASURED: the falsification probe for this shape did not
    terminate until the signal was narrowed to the lines below.

    Excluding the calling thread leaves exactly the server's own work —
    `serve_forever` plus the per-request thread `ThreadingHTTPServer` spawns.
    Returns None when nothing is readable, which `ProgressMeter` carries forward
    rather than mistaking for a reset."""
    me = str(threading.get_native_id())
    total = 0.0
    seen = False
    try:
        tids = os.listdir("/proc/self/task")
    except OSError:
        return None
    for tid in tids:
        if tid == me:
            continue
        try:
            with open(f"/proc/self/task/{tid}/stat", "rb") as fh:
                fields = fh.read().rsplit(b")", 1)[1].split()
            total += (int(fields[11]) + int(fields[12])) / _TICK
            seen = True
        except (OSError, IndexError, ValueError):
            continue
    return total if seen else None


def _await(name, ready, progress_fn, alive=None):
    """Wait for `ready()` bounded by NO FORWARD PROGRESS.

    Returns True the moment `ready()` is true. Returns False only when the
    subject stopped progressing (or `alive()` went false) — never because a
    clock ran out. The caller can then say which of the two happened, instead
    of a fixed poll count silently turning "still starting" into "never
    started"."""
    guard = _watchdog.loop_guard(name, max_iter=_MAX_LOOKS,
                                 stall_iters=_STALL_LOOKS,
                                 progress_fn=progress_fn)
    for _ in guard:
        if ready():
            return True
        if alive is not None and not alive():
            return False
        time.sleep(_LOOK_S)
    return False


def _fetch(url):
    """GET `url` and return the response. NO wall-clock bound, and no retry.

    RUNG 2 (structural assertion). Rung 1 for an HTTP wait would mean demoting
    the socket timeout to a LOOK INTERVAL and retrying while the server still
    makes progress. That cannot work here, and the reason is MEASURED rather
    than assumed: a retry ABANDONS the request in flight and starts a new one,
    so when the honest answer legitimately takes longer than one look, every
    attempt is abandoned and none ever completes. That is a LIVELOCK, and it
    bites in exactly the case the old bound was manufacturing verdicts for — a
    handler slower than the guess. The stall detector does not rescue it either:
    the abandoned handlers keep burning CPU, so the progress signal reports the
    server as working and the loop ends only at its iteration cap. Measured: a
    6 s handler under a 0.5 s look returned NO response at all, while one
    blocking GET against the same server answered 200 in 6.0 s.

    (The signal itself is sound — it stops on a wedge wherever the waiter does
    not touch the subject, which is why the file and bind polls in this campaign
    KEPT rung 1. It is the retry that is unavailable, not the watchdog.)

    So the 5 s bound is gone and nothing replaces it with another clock. What is
    asserted is the thing meant: the server ANSWERED, and with what. A genuinely
    wedged server now blocks, and the outer progress-supervised session ends it
    — the only layer that can tell a wedge from a slow host."""
    return urllib.request.urlopen(url)


# ---------------------------------------------------------------------------
# process helpers — reaping must be robust because the daemon runs in its own
# session (start_new_session=True), i.e. its own process group.
# ---------------------------------------------------------------------------
def _alive(pid: int) -> bool:
    """True only if the process is actually RUNNING. A zombie (already dead,
    awaiting a parent reap) is NOT alive — it squats no port, so it is not the
    leak we are checking for. `os.kill(pid, 0)` cannot tell the two apart, so
    read the process state from /proc and treat Z/X as dead."""
    if not pid:
        return False
    try:
        with open("/proc/%d/stat" % pid) as fh:
            # state char is the token right after the ')' that closes comm
            state = fh.read().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X", "x")
    except FileNotFoundError:
        return False
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


def _reap(pid: int) -> None:
    """Terminate a spawned daemon, wait for it to actually exit, and reap the
    zombie so nothing lingers. Never raises — a reap that fails to reap is worse
    than useless."""
    if not pid:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _alive(pid):
            break
        try:
            os.killpg(os.getpgid(pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
        for _ in range(50):                     # ≤5 s per signal
            if not _alive(pid):
                break
            time.sleep(0.1)
    # Reap the zombie (we are its OS parent when it was Popen'd from this
    # process); WNOHANG so a not-our-child pid can't block us.
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


@contextlib.contextmanager
def _dashboard_daemon(project: Path, port: int = 0):
    """Spawn a REAL flow_dashboard web daemon on *port* (0 = OS-assigned) and
    guarantee it is reaped on exit. Yields (proc, bound_port).

    This is the only sanctioned way to spawn a real daemon in a test; it is the
    fixture the issue asks for — a fixture that starts a subprocess MUST stop it
    on teardown."""
    import subprocess
    project = Path(project)
    (project / "reports").mkdir(parents=True, exist_ok=True)
    dash = _PROGRAMS / "flow_dashboard.py"
    log = open(project / "reports" / ".dashboard_test.log", "ab")
    proc = subprocess.Popen(
        [sys.executable, str(dash), str(project), "--web",
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        url_f = project / "reports" / "dashboard_web.url"
        bound = None

        def _recorded():
            if not url_f.is_file():
                return False
            tail = url_f.read_text().strip().rsplit(":", 1)[-1]
            return tail.isdigit()

        # No "≤10 s to bind": the daemon is watched by its own forward progress
        # (CPU + I/O over its /proc tree), so a slow start on a loaded host is
        # waited out and a daemon that wedges before binding still ends the wait.
        _await("dashboard-bind", _recorded,
               progress_fn=lambda: _watchdog.host_tree_progress(proc.pid),
               alive=lambda: proc.poll() is None)
        if _recorded():
            bound = int(url_f.read_text().strip().rsplit(":", 1)[-1])
        yield proc, bound
    finally:
        # Reap through the Popen object so the child is fully waited (no
        # lingering zombie), signalling the whole session it leads.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            # The first bound is an ESCALATION step, not a verdict: when it
            # expires nothing is recorded, the signal is upgraded to SIGKILL and
            # the reap is retried. It is kept exactly as it was.
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            # The second one is NOT an escalation — there is nothing left to
            # escalate to — so its expiry propagated out of teardown and errored
            # the test. What is meant here is "the child has been reaped", which
            # is what an unbounded wait after SIGKILL asserts directly.
            proc.wait()
        log.close()


# ---------------------------------------------------------------------------
# DEFECT 1 — process leak. _launch_dashboard must honour VIBE_IC_NO_DASHBOARD.
# ---------------------------------------------------------------------------
def test_launch_dashboard_honors_no_dashboard_env(tmp_path, monkeypatch):
    """With VIBE_IC_NO_DASHBOARD set, the runner must NOT spawn a daemon
    (returns None). Without it, it DOES spawn (control) — reaped here so the
    control path can never leak."""
    project = tmp_path / "generic_proj"
    project.mkdir()

    # Guarded: no spawn, no pid, nothing to leak. Reap defensively so that even
    # the RED path (unfixed impl DOES spawn) cannot itself leak the daemon it
    # is checking for.
    monkeypatch.setenv("VIBE_IC_NO_DASHBOARD", "1")
    pid = orch._launch_dashboard(project, "127.0.0.1", 0)
    try:
        assert pid is None, (
            "VIBE_IC_NO_DASHBOARD must suppress the daemon spawn "
            f"(got pid {pid} — the suite would leak it)")
    finally:
        _reap(pid)

    # Unguarded control: it really does spawn — prove it, then reap it so this
    # very test does not become the leak it is checking for.
    monkeypatch.delenv("VIBE_IC_NO_DASHBOARD", raising=False)
    pid = orch._launch_dashboard(project, "127.0.0.1", 0)
    try:
        assert pid is not None and _alive(pid), (
            "unguarded _launch_dashboard is expected to spawn a live daemon")
    finally:
        _reap(pid)
        assert not _alive(pid)


def test_dashboard_daemon_fixture_reaps_on_teardown(tmp_path):
    """A fixture that starts the dashboard asserts NO surviving process after
    teardown — the permanent leak check the issue wants."""
    project = tmp_path / "reap_proj"
    with _dashboard_daemon(project) as (proc, bound):
        assert bound is not None, "daemon must bind and record its port"
        assert _alive(proc.pid), "daemon must be alive inside the fixture"
        pid = proc.pid
    # Context exited → teardown ran → the child must be gone.
    assert not _alive(pid), (
        "flow_dashboard daemon survived fixture teardown — this is the leak")


# ---------------------------------------------------------------------------
# DEFECT 2 — hardcoded port. Two concurrent daemons must each serve on a
# distinct port; --port 0 must record the real OS-assigned port.
# ---------------------------------------------------------------------------
def test_two_dashboards_serve_on_distinct_ports(tmp_path):
    """Two dashboards started concurrently must BOTH serve, on distinct
    ports — the concurrency the hardcoded 8787 broke."""
    p1 = tmp_path / "proj_a"
    p2 = tmp_path / "proj_b"
    with _dashboard_daemon(p1) as (a, pa), _dashboard_daemon(p2) as (b, pb):
        assert pa and pb, f"both daemons must bind a port (got {pa!r}, {pb!r})"
        assert pa != pb, (
            f"concurrent dashboards must serve on DISTINCT ports (both {pa})")
        for port in (pa, pb):
            resp = _fetch(f"http://127.0.0.1:{port}/")
            assert resp.status == 200, f"dashboard on {port} must serve"
        pid_a, pid_b = a.pid, b.pid
    assert not _alive(pid_a) and not _alive(pid_b), (
        "both concurrent daemons must be reaped on teardown")


def test_serve_records_actual_port_for_port_zero(tmp_path):
    """serve(port=0) must record the REAL OS-assigned port (not ':0') and
    serve on it — the robust port answer the issue asks for."""
    import threading
    import flow_dashboard_web as fdw
    (tmp_path / "reports").mkdir()
    t = threading.Thread(
        target=lambda: fdw.serve(str(tmp_path), port=0, host="127.0.0.1"),
        daemon=True)
    t.start()
    url_f = tmp_path / "reports" / "dashboard_web.url"
    # The server is a thread of THIS process, so this process's CPU advancing is
    # the "it is working" reading; a fixed 80-look budget was a reading of the
    # host instead.
    _await("serve-bind", url_f.is_file,
           progress_fn=_server_cpu_s,
           alive=t.is_alive)
    assert url_f.is_file(), "daemon must record its actually-bound URL"
    rec = url_f.read_text().strip()
    bound = int(rec.rsplit(":", 1)[-1])
    assert bound != 0, "port-0 must resolve to a real OS-assigned port, not :0"
    assert _fetch(rec).status == 200


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

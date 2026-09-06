#!/usr/bin/env python3
"""The runner pool dies with the coordinator, and with its own timeout.

MEASURED 2026-09-06 (RTLLM run, finding BR-07): killing
``benchmark_dispatch --solve`` left 21 runner processes running for about 15
minutes against an abandoned run dir, at host load 22+. A pool that outlives
the run it belongs to is burning a shared machine on work nobody will read.

`_RunnerBudget.run` used `subprocess.run`, which neither propagates the
coordinator's death nor, on timeout, kills anything but the DIRECT child --
and the runner spawns its own tools, so the grandchildren are the pool. Each
invocation now gets its own process GROUP, live groups are registered, and the
coordinator signals them on SIGTERM/SIGINT/SIGHUP and at exit.

TWO limits, stated rather than papered over. SIGKILL is NOT covered: it runs no
handler, and surviving `kill -9` needs PR_SET_PDEATHSIG per child, which from
CPython means `preexec_fn` -- documented as unsafe with threads, and this pool
IS threads. And the per-invocation wall-clock ceiling still kills only the
DIRECT child: once `subprocess.run` reaps it, its tools are reparented away and
are no longer children of this process, so nothing here can find them. Both are
real gaps; neither is claimed to be closed.

Every process here is identified by a RECORDED PID. No pattern matching: every
lane on this fleet runs the same script names.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]

# The "runner": records its own pid and a grandchild's, then waits.
_FAKE_RUNNER = '''
import os, subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c",
                               "import time; time.sleep(300)"])
open(sys.argv[1], "w").write(f"{os.getpid()} {grandchild.pid}\\n")
time.sleep(300)
'''

# The coordinator: drives ONE runner invocation through the real budget.
_COORDINATOR = '''
import sys, threading, time
sys.path.insert(0, {programs!r})
import benchmark_dispatch as bd
# Exactly what main() does for --solve/--resume: install on the MAIN thread,
# before any worker exists.
bd._install_orphan_guard()
budget = bd._RunnerBudget(1, 1, 0)
threading.Thread(
    target=budget.run,
    args=([sys.executable, {runner!r}, {pidfile!r}],),
    daemon=True).start()
time.sleep(300)
'''


def _alive(pid: int) -> bool:
    """Alive and not a reaped zombie, by PID -- never by name."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return status.rsplit(")", 1)[-1].split()[0] != "Z"


def _wait_gone(pids, deadline_s=20.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        if not any(_alive(p) for p in pids):
            return True
        time.sleep(0.2)
    return False


def _reap(pids) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.fixture
def pool(tmp_path):
    """Start a real coordinator driving a real runner with a real grandchild."""
    runner = tmp_path / "fake_runner.py"
    runner.write_text(_FAKE_RUNNER)
    pidfile = tmp_path / "pids.txt"
    coordinator = tmp_path / "coordinator.py"
    coordinator.write_text(_COORDINATOR.format(
        programs=str(PROGRAMS), runner=str(runner), pidfile=str(pidfile)))
    parent = subprocess.Popen([sys.executable, str(coordinator)])
    deadline = time.time() + 30
    while time.time() < deadline and not pidfile.exists():
        time.sleep(0.1)
    if not pidfile.exists():
        parent.kill()
        pytest.fail("NOT_MEASURED: the fake runner never recorded its pids")
    child_pid, grandchild_pid = (int(x) for x in pidfile.read_text().split())
    assert _alive(child_pid) and _alive(grandchild_pid)
    try:
        yield parent, child_pid, grandchild_pid
    finally:
        try:
            parent.kill()
            parent.wait(timeout=10)
        except OSError:
            pass
        _reap([child_pid, grandchild_pid])


def test_sigterm_to_the_coordinator_takes_the_whole_pool_with_it(pool):
    """The BR-07 scenario itself: kill the parent, the pool must not survive."""
    parent, child_pid, grandchild_pid = pool
    parent.send_signal(signal.SIGTERM)
    parent.wait(timeout=20)
    assert _wait_gone([child_pid, grandchild_pid]), (
        f"orphaned pool: child alive={_alive(child_pid)}, "
        f"grandchild alive={_alive(grandchild_pid)}")


def test_sigint_to_the_coordinator_takes_the_whole_pool_with_it(pool):
    parent, child_pid, grandchild_pid = pool
    parent.send_signal(signal.SIGINT)
    parent.wait(timeout=20)
    assert _wait_gone([child_pid, grandchild_pid])


def test_signalling_no_children_is_zero_not_an_error(monkeypatch):
    """"Nothing to signal" is a measured zero, never an exception."""
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    monkeypatch.setattr(bd, "_own_child_pids", list)
    assert bd._kill_live_runner_groups() == 0


def test_a_finished_run_leaves_no_child_to_signal(tmp_path):
    """The population is the kernel's, so it empties itself: a run that has
    returned has no children, and the exit handler signals nobody."""
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    outcome = bd._RunnerBudget(1, 1, 0).run([sys.executable, "-c", "pass"])
    assert outcome.rc == 0
    assert bd._kill_live_runner_groups() == 0


def test_the_children_population_is_the_kernels_not_a_name_pattern():
    """Every lane on this fleet runs the same script names, so a name pattern
    is how one run kills another's work. The population is /proc's children
    of THIS pid, and it contains a child we started and nothing else."""
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    before = set(bd._own_child_pids())
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                             start_new_session=True)
    try:
        assert child.pid in set(bd._own_child_pids()) - before
    finally:
        child.kill()
        child.wait(timeout=10)
    assert child.pid not in set(bd._own_child_pids())


@pytest.mark.parametrize("verb", ["--solve", "--resume"])
def test_the_front_door_installs_the_guard_on_the_main_thread(
        tmp_path, monkeypatch, verb):
    """The mechanism is only worth what the front door actually calls.

    Every other test here installs the guard itself. If `main()` stopped doing
    so the pool would go back to outliving its coordinator with every one of
    those tests still green -- the guard would be installed by the tests and
    by nobody else.
    """
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415

    called = []
    monkeypatch.setattr(bd, "_install_orphan_guard", lambda: called.append(1))
    # Stop at the argument check that follows the install, so nothing runs.
    monkeypatch.setattr(bd.sys, "argv",
                        ["benchmark_dispatch.py", "rtllm", verb])
    with pytest.raises(SystemExit):
        bd.main()
    assert called == [1], f"main() did not install the orphan guard for {verb}"


def test_the_coordinators_own_group_is_never_signalled(monkeypatch):
    """The cleanup must not become the outage.

    Every child gets a session of its own, so a registered group is never the
    coordinator's. If that ever stopped being true -- a dropped
    `start_new_session`, a platform that refuses it -- signalling the
    registered group would kill the coordinator and everything sharing its
    terminal. This asserts the guard directly rather than trusting the
    invariant that makes it unnecessary today.
    """
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415

    killed = []
    monkeypatch.setattr(bd.os, "killpg",
                        lambda pgid, sig: killed.append((pgid, sig)))
    # A "child" that shares our group: exactly what a dropped
    # start_new_session would produce.
    monkeypatch.setattr(bd, "_own_child_pids", lambda: [os.getpid()])
    assert bd._kill_live_runner_groups() == 0
    assert killed == [], f"the guard signalled its own group: {killed}"

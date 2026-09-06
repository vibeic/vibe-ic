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

import contextlib
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
# before any worker exists. getattr, because on a tree that has no guard at
# all the coordinator must still RUN and still spawn its pool -- that is the
# RED arm, and it has to reach the assertion to fail instead of timing out
# waiting for a pidfile that would never be written.
getattr(bd, "_install_orphan_guard", lambda: None)()
budget = bd._RunnerBudget(1, 1, 0)
threading.Thread(
    target=budget.run,
    args=([sys.executable, {runner!r}, {pidfile!r}],),
    daemon=True).start()
time.sleep(300)
'''


#: A FIXED number of polls, deliberately not a wall clock. A wall-clock wait
#: is a loop that cannot say "never": it reports how long it was willing to
#: wait, and on a loaded host it either flakes or hides a survivor behind a
#: longer deadline. A poll budget terminates on every host, so the RED arm
#: FAILS rather than hanging.
_POLL_BUDGET = 60
_POLL_INTERVAL_S = 0.2


def _alive(pid: int) -> bool:
    """Alive and not a reaped zombie, by PID -- never by name."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return status.rsplit(")", 1)[-1].split()[0] != "Z"


def _argv(pid: int) -> str:
    """A survivor's own command line, so a failure NAMES what is still running."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return "<exited>"
    return " ".join(raw.decode("utf-8", "replace").split("\0")).strip() or "<no argv>"


def _survivors(pids) -> list[str]:
    """Which of these are STILL RUNNING, reported by pid and argv."""
    return [f"pid {p}: {_argv(p)}" for p in pids if _alive(p)]


def _drain(pids) -> list[str]:
    """Spend the whole poll budget, then report whoever is left.

    Returns [] when the pool is gone. The budget is a COUNT, so this returns
    on every host rather than waiting on a clock nobody can bound.
    """
    for _ in range(_POLL_BUDGET):
        left = _survivors(pids)
        if not left:
            return []
        time.sleep(_POLL_INTERVAL_S)
    return _survivors(pids)


def _reap(pids) -> None:
    """Kill what this test spawned, by RECORDED pid -- never a name pattern.

    The group first, because the runner's own children are the pool: leaving
    them is exactly the defect under test, and a test that demonstrates an
    orphan by creating one is not a test anyone should run twice.

    NEVER our own group. MEASURED on the RED arm: with no `start_new_session`
    the child shares the process group of whoever started it -- which here is
    pytest -- so `killpg` on it killed the test runner itself (rc=137). That is
    the same foot-gun the production guard refuses, and the reaper needs it
    too: on that arm the pids are killed individually instead.
    """
    own = os.getpgrp()
    for pid in pids:
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = None
        if pgid is not None and pgid != own:
            with contextlib.suppress(OSError):
                os.killpg(pgid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    for _ in range(_POLL_BUDGET):
        if not any(_alive(p) for p in pids):
            return
        time.sleep(_POLL_INTERVAL_S)


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
    pids: list[int] = []
    try:
        for _ in range(_POLL_BUDGET):
            if pidfile.exists():
                break
            time.sleep(_POLL_INTERVAL_S)
        if not pidfile.exists():
            # NOT a hidden pass and not a hang: the arm could not be set up,
            # so it is reported as unmeasured rather than scored either way.
            pytest.fail("NOT_MEASURED: the fake runner never recorded its "
                        f"pids within {_POLL_BUDGET} polls")
        pids = [int(x) for x in pidfile.read_text().split()]
        assert len(pids) == 2 and all(_alive(p) for p in pids), _survivors(pids)
        yield parent, pids[0], pids[1]
    finally:
        # Reap on BOTH arms. On the red arm the survivors are the whole point,
        # and leaving them behind would make the test the thing it is meant to
        # catch: this fixture must not be able to orphan a pool either.
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            parent.kill()
            parent.wait(timeout=10)
        _reap(pids)
        assert not _survivors(pids), (
            "the test itself leaked processes: " + "; ".join(_survivors(pids)))


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_killing_the_coordinator_takes_the_whole_pool_with_it(pool, sig):
    """The BR-07 scenario itself: kill the parent, the pool must not survive.

    The assertion is on the SURVIVOR SET, spent against a fixed poll budget:
    an empty set is the pass, and anything left is named by pid and argv. A
    test that demonstrated the orphaned pool by waiting for it would be a loop
    that cannot say "never" -- on a tree with no guard this FAILS, naming the
    processes that outlived their coordinator.
    """
    parent, child_pid, grandchild_pid = pool
    parent.send_signal(sig)
    parent.wait(timeout=20)
    survivors = _drain([child_pid, grandchild_pid])
    assert survivors == [], (
        f"the pool outlived its coordinator ({sig!r}); still running after "
        f"{_POLL_BUDGET} polls: " + "; ".join(survivors))


def test_signalling_no_children_is_zero_not_an_error(monkeypatch):
    """"Nothing to signal" is a measured zero, never an exception."""
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    monkeypatch.setattr(bd, "_own_child_pids", list)
    assert bd._kill_live_runner_groups() == 0


def test_a_finished_run_leaves_no_child_to_signal(tmp_path):
    """A run that has RETURNED leaves nothing behind, stated as a DELTA.

    This asserted `_kill_live_runner_groups() == 0` and was a red on main
    (v1.17.96, reported from a pinned-image run over four modules). That form
    is a claim about the WHOLE PROCESS, not about the run: the guard counts
    every child of this pytest process that sits in its own process group, and
    in a shared session such a child routinely exists for reasons that have
    nothing to do with a Program re-entry.

    MEASURED on main e812321b0, in the pinned image on a clean clone: with ONE
    unrelated foreign-group child alive, the old form reads 1 and FAILS, while
    the delta form below passes. The production guard is correct -- signalling
    every runner group is exactly its job when the coordinator is dying; only
    the assertion was wrong about what it measured.

    The old form was also destructive: calling the guard SIGTERMed that
    unrelated child. A test must not signal a process it did not start.
    """
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    before = set(bd._own_child_pids())
    outcome = bd._RunnerBudget(1, 1, 0).run([sys.executable, "-c", "pass"])
    assert outcome.rc == 0
    leaked = set(bd._own_child_pids()) - before
    assert leaked == set(), (
        "the finished run left a child behind: "
        + "; ".join(_survivors(sorted(leaked))))


def test_the_finished_run_test_does_not_signal_anyone(monkeypatch):
    """The guard is never CALLED to prove a run is finished.

    Pinning the fix, not just the symptom: the sibling above asks the kernel
    who this process's children are and compares two sets. If it ever went back
    to calling `_kill_live_runner_groups()`, it would resume signalling
    processes it did not start -- which is how it became a red on someone
    else's machine rather than on mine.
    """
    sys.path.insert(0, str(PROGRAMS))
    import benchmark_dispatch as bd                      # noqa: PLC0415
    signalled = []
    monkeypatch.setattr(bd.os, "killpg",
                        lambda pgid, sig: signalled.append((pgid, sig)))
    stray = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             start_new_session=True)
    try:
        before = set(bd._own_child_pids())
        assert stray.pid in before
        outcome = bd._RunnerBudget(1, 1, 0).run([sys.executable, "-c", "pass"])
        assert outcome.rc == 0
        # The run is finished and nothing it started remains ...
        assert set(bd._own_child_pids()) - before == set()
        # ... and establishing that signalled NOBODY, stray included.
        assert signalled == [], signalled
        assert _alive(stray.pid), "the test killed a process it did not start"
    finally:
        stray.kill()
        stray.wait(timeout=10)


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

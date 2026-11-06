"""A bounded Phase-3 window re-enters its parent's project lock (#588).

The orchestrator (``vibe_ic_one_shot_runner --entry-step 15 --exit-step
38``) holds ``<project>/.runner.lock`` and hands its child the
re-entrancy token.  The window child must make the SAME re-entrancy
decision ``_runner_lock.acquire_or_reenter`` makes -- read-only, since a
window never writes into the project -- and a private copy of the
project must not inherit the parent's live lock and refuse its own
enclosing run.  A genuinely concurrent holder must still be refused.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import _runner_lock
import phase3_one_shot_runner as p3

DEADLINE_S = 300


def _running(pid: int) -> bool:
    """A process that still runs. `kill(pid, 0)` (`_runner_lock._pid_alive`)
    also succeeds on a zombie -- a child the group kill took down that no
    one has reaped yet, as under a subreaper that reaps only at the end."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[-1].split()[0] not in ("Z", "X", "x")


def _write_lock(project: Path, pid: int) -> bytes:
    lock = project / _runner_lock.LOCK_FILENAME
    lock.write_text(json.dumps({"pid": pid, "timestamp": "x",
                                "runner": "vibe_ic_one_shot_runner"}))
    return lock.read_bytes()


def _run_window(project: Path, token):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop(_runner_lock.REENTRANCY_ENV, None)
    if token is not None:
        env[_runner_lock.REENTRANCY_ENV] = token
    return subprocess.run(
        [sys.executable, str(Path(p3.__file__)), str(project),
         "--entry-step", "15", "--exit-step", "38"],
        env=env, capture_output=True, text=True, check=False,
        timeout=DEADLINE_S)


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def stranger():
    proc = subprocess.Popen(["sleep", "120"])
    yield proc.pid
    proc.kill()
    proc.wait(timeout=30)




def _assert_refusal_discloses(cp, project: Path, holder: int, why: str):
    assert cp.returncode == 3
    line = [l for l in cp.stderr.splitlines()
            if l.startswith("CONCURRENT_RUN_REFUSED")]
    assert line, cp.stderr
    line = line[0]
    assert f"pid={holder}" in line
    assert "runner=vibe_ic_one_shot_runner" in line and "since=x" in line
    assert str(project / _runner_lock.LOCK_FILENAME) in line
    assert why in line, line
    assert _runner_lock.REENTRANCY_ENV in line.split(why, 1)[1]


def test_window_without_token_still_refuses_live_lock(project):
    lock_bytes = _write_lock(project, os.getpid())
    cp = _run_window(project, None)
    _assert_refusal_discloses(cp, project, os.getpid(), "no "
                              + _runner_lock.REENTRANCY_ENV + " token")
    assert (project / _runner_lock.LOCK_FILENAME).read_bytes() == lock_bytes


def test_window_token_for_other_project_still_refuses(project, tmp_path):
    _write_lock(project, os.getpid())
    other = (tmp_path / 'other').resolve()
    cp = _run_window(project, f"{os.getpid()}:{other}")
    _assert_refusal_discloses(cp, project, os.getpid(),
                              f"names project {other}")


def test_window_token_not_naming_the_live_holder_still_refuses(project,
                                                                stranger):
    _write_lock(project, stranger)
    cp = _run_window(project, f"{os.getpid()}:{project.resolve()}")
    _assert_refusal_discloses(
        cp, project, stranger,
        f"names pid {os.getpid()}, but the lock is held by pid {stranger}")


def test_reentrant_holder_pid_is_the_acquire_or_reenter_decision(
        project, stranger, monkeypatch):
    env = _runner_lock.REENTRANCY_ENV
    _write_lock(project, os.getpid())
    monkeypatch.setenv(env, f"{os.getpid()}:{project.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) == os.getpid()
    monkeypatch.setenv(env, f"{os.getpid()}:{project.parent.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) is None
    monkeypatch.delenv(env)
    assert _runner_lock.reentrant_holder_pid(project) is None
    monkeypatch.setenv(env, "garbage")
    assert _runner_lock.reentrant_holder_pid(project) is None
    (project / _runner_lock.LOCK_FILENAME).write_text('{"pid": "x"}')
    monkeypatch.setenv(env, f"{os.getpid()}:{project.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) is None
    _write_lock(project, stranger)
    assert _runner_lock.reentrant_holder_pid(project) is None


















def test_a_zombie_is_not_a_surviving_orphan():
    """The liveness read the hang test relies on: an exited, unreaped child
    is a zombie, which `kill(pid, 0)` still reports alive."""
    child = subprocess.Popen(["true"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{child.pid}/stat").read_text()
        except OSError:
            break
        if state.rsplit(")", 1)[-1].split()[0] == "Z":
            break
        time.sleep(0.05)
    try:
        assert _runner_lock._pid_alive(child.pid)
        assert not _running(child.pid)
    finally:
        child.wait(timeout=10)
    assert not _running(child.pid)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        assert _running(sleeper.pid)
    finally:
        sleeper.kill()
        sleeper.wait(timeout=10)


#: What `main` prints once admission and PDK resolution are done (the run
#: banner), spelled as the runner prints it.
BANNER = "=== phase3_one_shot_runner — pdk=x top=top ==="

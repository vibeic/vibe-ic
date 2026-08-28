#!/usr/bin/env python3
"""v0.3.1 — ORGANIC-20260606 #498 (MEDIUM, Bucket A+B): single-driver
project lock for the one-shot runners.

現象 (issue): two concurrent orchestrator invocations raced on the SAME
project dir — an orphaned background runner plus the successor agent's
runner — both concurrently writing run logs / manifests / provenance.
The runner had NO mechanism to refuse a second concurrent invocation.

FIX (Bucket A): a new ``programs/_runner_lock.py`` module acquires
``<proj>/.runner.lock`` (pid + ISO timestamp + runner name). A second
invocation against a project whose lock pid is ALIVE prints a named
``CONCURRENT_RUN_REFUSED`` message (naming the holder pid) and exits
non-zero. A lock whose pid is DEAD is treated as stale: removed with a
named ``STALE_RUNNER_LOCK`` note, then the runner proceeds. Released on
normal exit AND best-effort on signal/atexit. Wired into
``vibe_ic_one_shot_runner.py`` main entry ONLY (phase runners are owned
by another agent; a follow-up can wire the shared helper into them).

## 驗收 (executed verbatim, see test_acceptance_*):
  start a long-running first invocation (or simulate: write a live-pid
  lock) → second invocation:
      python3 programs/vibe_ic_one_shot_runner.py <same proj> ...;
      echo exit=$?
  → named CONCURRENT_RUN_REFUSED naming the holder pid, non-zero exit;
  write a dead-pid lock → runner cleans the stale lock and starts
  normally.

DENY-LIST DISCIPLINE: all fixtures use generic ``proj`` tmp dirs — no
chip/vendor/SKU literal appears in this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent
RUNNER = PROGRAMS_DIR / "vibe_ic_one_shot_runner.py"
LOCK_NAME = ".runner.lock"

sys.path.insert(0, str(PROGRAMS_DIR))
import _runner_lock  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# --------------------------------------------------------------------------
# A dead pid: spawn a trivial child, wait for it, then reuse its pid. The
# OS does not immediately recycle it, so os.kill(dead, 0) → ProcessLookupError.
# --------------------------------------------------------------------------
def _dead_pid() -> int:
    cp = subprocess.run([sys.executable, "-c", "pass"])
    dead = cp.pid if hasattr(cp, "pid") else None
    if dead is None:
        # subprocess.run() doesn't expose pid pre-3.? — use Popen.
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        dead = p.pid
        p.wait()
    # Sanity: a freshly-reaped child should not be alive.
    if _runner_lock._pid_alive(dead):
        pytest.skip("OS recycled the pid too fast to test the dead-pid path")
    return dead


def _write_lock(project: Path, pid: int, runner: str = "some_runner") -> Path:
    path = project / LOCK_NAME
    path.write_text(json.dumps({
        "pid": pid,
        "timestamp": "2026-06-06T00:00:00Z",
        "runner": runner,
    }) + "\n")
    return path


# ==========================================================================
# Unit-level: _runner_lock.acquire() behaviour
# ==========================================================================
def test_acquire_on_clean_project_takes_lock(tmp_path, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    lock = _runner_lock.acquire(project)
    assert lock is not None
    lockfile = project / LOCK_NAME
    assert lockfile.is_file()
    data = json.loads(lockfile.read_text())
    assert data["pid"] == os.getpid()
    assert data["runner"] == "vibe_ic_one_shot_runner" or "runner" in data
    lock.release()
    assert not lockfile.exists()


def test_acquire_named_runner_recorded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    lock = _runner_lock.acquire(project, "my_named_runner")
    data = json.loads((project / LOCK_NAME).read_text())
    assert data["runner"] == "my_named_runner"
    lock.release()


def test_acquire_refuses_when_live_holder(tmp_path, capsys):
    """Live holder → None + CONCURRENT_RUN_REFUSED naming the pid."""
    project = tmp_path / "proj"
    project.mkdir()
    live = os.getpid()  # this test process is, definitionally, alive
    _write_lock(project, live, runner="orphaned_runner")
    lock = _runner_lock.acquire(project)
    assert lock is None
    err = capsys.readouterr().err
    assert "CONCURRENT_RUN_REFUSED" in err
    assert str(live) in err
    assert "orphaned_runner" in err
    # The live lock must NOT be removed by a refused newcomer.
    assert (project / LOCK_NAME).is_file()


def test_acquire_cleans_stale_dead_holder(tmp_path, capsys):
    """Dead holder → STALE_RUNNER_LOCK note + lock retaken."""
    project = tmp_path / "proj"
    project.mkdir()
    dead = _dead_pid()
    _write_lock(project, dead, runner="crashed_runner")
    lock = _runner_lock.acquire(project)
    assert lock is not None
    err = capsys.readouterr().err
    assert "STALE_RUNNER_LOCK" in err
    # The lock is now OURS.
    data = json.loads((project / LOCK_NAME).read_text())
    assert data["pid"] == os.getpid()
    lock.release()


def test_acquire_cleans_unparseable_lock(tmp_path, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    (project / LOCK_NAME).write_text("{ this is not json")
    lock = _runner_lock.acquire(project)
    assert lock is not None
    err = capsys.readouterr().err
    assert "STALE_RUNNER_LOCK" in err
    assert "unparseable" in err
    lock.release()


def test_release_only_removes_own_lock(tmp_path):
    """release() must not delete a lock another runner legitimately re-took."""
    project = tmp_path / "proj"
    project.mkdir()
    lock = _runner_lock.acquire(project)
    # Simulate another runner stealing the file after a stale-cleanup race.
    _write_lock(project, 999999, runner="other_runner")
    lock.release()
    # Our release saw a foreign pid → it must leave the file intact.
    assert (project / LOCK_NAME).is_file()


def test_pid_alive_self_true_and_dead_false(tmp_path):
    assert _runner_lock._pid_alive(os.getpid()) is True
    assert _runner_lock._pid_alive(-1) is False
    assert _runner_lock._pid_alive(0) is False
    assert _runner_lock._pid_alive(_dead_pid()) is False


# ==========================================================================
# 驗收 — end-to-end against the real runner entry point.
# ==========================================================================
def _run_runner(project: Path, timeout: int = 60):
    """Invoke the runner verbatim: python3 programs/vibe_ic_one_shot_runner.py
    <proj> --skip-phase1 --skip-analog --skip-phase3."""
    return _pr.run(
        [sys.executable, str(RUNNER), str(project),
         "--skip-phase1", "--skip-analog", "--skip-phase3"],
        capture_output=True, text=True, cwd=str(PROGRAMS_DIR),
    )


def test_acceptance_live_lock_refuses_second_invocation(tmp_path):
    """驗收 part 1: simulate a long-running first invocation by writing a
    LIVE-pid lock → second invocation refuses by name with non-zero exit."""
    project = tmp_path / "proj"
    project.mkdir()
    live = os.getpid()  # stand-in for the still-running first invocation
    _write_lock(project, live, runner="vibe_ic_one_shot_runner")

    cp = _run_runner(project)
    # echo exit=$? → non-zero
    assert cp.returncode != 0, f"expected non-zero, got {cp.returncode}"
    combined = cp.stdout + cp.stderr
    assert "CONCURRENT_RUN_REFUSED" in combined
    assert str(live) in combined, "holder pid must be named in the message"
    # The live holder's lock must survive the refused invocation.
    assert (project / LOCK_NAME).is_file()


def test_acceptance_dead_lock_cleaned_and_runner_starts(tmp_path):
    """驗收 part 2: write a DEAD-pid lock → runner cleans the stale lock and
    starts normally (proceeds past the lock; no CONCURRENT_RUN_REFUSED)."""
    project = tmp_path / "proj"
    project.mkdir()
    dead = _dead_pid()
    _write_lock(project, dead, runner="crashed_runner")

    cp = _run_runner(project)
    combined = cp.stdout + cp.stderr
    # Stale lock was cleaned (named note), and the runner did NOT refuse.
    assert "STALE_RUNNER_LOCK" in combined
    assert "CONCURRENT_RUN_REFUSED" not in combined
    # The runner proceeded into the flow and emitted its aggregate report
    # (it FAILs at phase2 on an empty project — that's the normal path,
    # proving the lock did not block startup).
    rep = (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json")
    assert rep.is_file(), "runner must have proceeded past the lock"
    # On normal exit the runner releases its own lock.
    assert not (project / LOCK_NAME).exists()


def test_acceptance_clean_project_runs_and_releases(tmp_path):
    """A clean project (no prior lock) runs and releases its lock on exit."""
    project = tmp_path / "proj"
    project.mkdir()
    cp = _run_runner(project)
    combined = cp.stdout + cp.stderr
    assert "CONCURRENT_RUN_REFUSED" not in combined
    rep = (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json")
    assert rep.is_file()
    # Lock released on normal exit.
    assert not (project / LOCK_NAME).exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

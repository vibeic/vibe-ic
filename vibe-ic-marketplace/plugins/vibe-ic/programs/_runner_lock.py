#!/usr/bin/env python3
"""_runner_lock.py — single-driver project lock for the one-shot runners.

WHY (ORGANIC-20260606 #498): two concurrent orchestrator invocations
raced on the SAME project directory — an orphaned background runner that
was never killed/awaited, plus the successor agent's fresh runner — and
both concurrently wrote run logs / manifests / provenance into the same
``reports/`` tree, corrupting the run record. The runners had NO
mechanism to refuse a second concurrent invocation on a project already
being driven.

WHAT this module provides: a best-effort, PID-based project lock.

  - ``acquire(project, runner_name)`` writes ``<project>/.runner.lock``
    containing the holder pid + an ISO-8601 timestamp + the runner name.
      * If the lock already exists and its pid is ALIVE → print a named
        ``CONCURRENT_RUN_REFUSED`` message (naming the holder pid) and
        return None. The caller exits non-zero.
      * If the lock exists but its pid is DEAD (stale lock left by a
        crashed / killed runner) → print a named ``STALE_RUNNER_LOCK``
        note, remove the stale file, and proceed to take the lock.
  - The lock is released on normal exit AND best-effort on
    signal (SIGINT / SIGTERM) and ``atexit``.

This is the deterministic enforcement of the field-agent-loop
**single-driver principle**: at most one runner drives a given project
directory at a time. It is chip-AGNOSTIC — it keys only on the project
path and the OS pid; nothing about any chip / vendor / SKU.

DESIGN NOTES
  - Liveness is probed with ``os.kill(pid, 0)`` (POSIX): no signal is
    delivered, but ESRCH means the process is gone and EPERM means it
    exists but is owned by another user (still ALIVE for our purposes).
  - The lock is advisory: it is NOT a kernel flock, so a truly racing
    pair that both pass the existence check in the same microsecond
    could both proceed. That window is negligible for the human/agent
    orchestration cadence this guards (seconds-to-minutes), and the
    primary failure mode (#498) — an abandoned long-lived runner versus
    a brand-new one — is fully covered: the abandoned runner's lock is
    present and its pid is alive, so the newcomer is refused by name.
  - Best-effort throughout: any filesystem error while reading/writing
    the lock degrades to "proceed" rather than crashing the flow, so the
    lock can never itself become a hard outage.
"""
from __future__ import annotations

import atexit
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOCK_FILENAME = ".runner.lock"

# ORGANIC #588 — re-entrancy token. The top orchestrator holds the
# project lock, then spawns the standalone phase runners as child
# processes. Those children now ALSO acquire the lock (so a standalone
# phase3 re-run on a live project is refused), which would deadlock the
# orchestrator against its own lock. The orchestrator therefore exports
# this env var carrying "<holder_pid>:<project_path>"; a child whose
# token matches the live lock on the SAME project re-enters (no-op lock)
# instead of being refused. chip-AGNOSTIC: pid + path only.
REENTRANCY_ENV = "VIBE_IC_RUNNER_LOCK_TOKEN"


def _token_for(project: Path, pid: int) -> str:
    return f"{pid}:{Path(project).resolve()}"

# Module-level registry of the lock this process currently holds so the
# atexit / signal handlers can release exactly what we acquired (and only
# what we acquired — never a lock another process re-took in the gap).
_HELD: Optional["RunnerLock"] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pid_alive(pid: int) -> bool:
    """Return True if `pid` names a live process on this host.

    POSIX ``os.kill(pid, 0)`` delivers no signal but performs the
    permission/existence check:
      - no error            → process exists and we may signal it → ALIVE
      - PermissionError     → process exists, owned by another user → ALIVE
      - ProcessLookupError  → no such process → DEAD
      - other OSError       → treat as DEAD (cannot prove liveness)
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_path(project: Path) -> Path:
    return Path(project) / LOCK_FILENAME


def _read_lock(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        # Unparseable/garbage lock file — treat as a stale artifact.
        return None


class RunnerLock:
    """A held project lock. Use via :func:`acquire`; release via
    :meth:`release` (also fired automatically on exit/signal)."""

    def __init__(self, project: Path, runner_name: str):
        self.project = Path(project)
        self.runner_name = runner_name
        self.pid = os.getpid()
        self.path = _lock_path(self.project)
        self._released = False

    def _write(self) -> None:
        payload = {
            "pid": self.pid,
            "timestamp": _now_iso(),
            "runner": self.runner_name,
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    def release(self) -> None:
        """Remove our lock file if (and only if) it is still OURS."""
        global _HELD
        if self._released:
            return
        self._released = True
        try:
            data = _read_lock(self.path)
            # Only delete a lock we still own — never one another runner
            # legitimately re-took after a stale-cleanup race.
            if data is not None and int(data.get("pid", -1)) == self.pid:
                self.path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            # Best-effort release — never raise out of cleanup.
            pass
        if _HELD is self:
            _HELD = None


class ReentrantLock:
    """ORGANIC #588 — a no-op lock returned when a child runner re-enters
    a project its parent orchestrator already locked. Releasing it does
    NOT touch the parent's lock file (the parent owns the lifecycle)."""

    def __init__(self, project: Path, runner_name: str, holder_pid: int):
        self.project = Path(project)
        self.runner_name = runner_name
        self.pid = os.getpid()
        self.holder_pid = holder_pid
        self.path = _lock_path(self.project)
        self.reentrant = True
        self._released = True  # never deletes the parent's file

    def release(self) -> None:
        return  # parent owns the lock lifecycle


def child_env(project: Path, held_lock=None,
              base_env: Optional[dict] = None) -> dict:
    """Return an env dict (copy of ``base_env`` or os.environ) carrying
    the re-entrancy token a spawned standalone phase runner uses to
    re-enter the live project lock rather than being refused (#588).

    When ``held_lock`` is a real :class:`RunnerLock` THIS process owns,
    the token names this pid. When it is a :class:`ReentrantLock` (this
    process is itself a delegated sub-run under a parent), the EXISTING
    token is propagated unchanged so the grandchild re-enters the
    original top holder, not this non-holding pid."""
    env = dict(os.environ if base_env is None else base_env)
    if isinstance(held_lock, ReentrantLock):
        # Propagate the inherited token (set by the real top holder).
        existing = env.get(REENTRANCY_ENV) or os.environ.get(REENTRANCY_ENV)
        if existing:
            env[REENTRANCY_ENV] = existing
            return env
    env[REENTRANCY_ENV] = _token_for(project, os.getpid())
    return env


def _install_release_handlers(lock: RunnerLock) -> None:
    """Wire atexit + SIGINT/SIGTERM so the lock is freed on the common
    teardown paths. Best-effort: a SIGKILL or hard crash leaves a stale
    lock, which the NEXT invocation cleans via the dead-pid path."""
    atexit.register(lock.release)

    def _handler(signum, _frame):
        lock.release()
        # Re-raise the default disposition so the process still exits
        # with the conventional signal semantics.
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:
            sys.exit(1)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Not in main thread, or platform without the signal — skip.
            pass


def acquire(project: Path, runner_name: str = "vibe_ic_one_shot_runner",
            stream=None) -> Optional[RunnerLock]:
    """Acquire the single-driver lock for ``project``.

    Returns a :class:`RunnerLock` on success, or ``None`` when the
    project is already being driven by a LIVE runner (caller must then
    exit non-zero). Messages are written to ``stream`` (default stderr).

    Behaviour:
      - live holder  → print ``CONCURRENT_RUN_REFUSED`` (naming holder
        pid + runner + timestamp), return None.
      - dead holder  → print ``STALE_RUNNER_LOCK`` note, remove stale
        file, take the lock, return it.
      - no holder    → take the lock, return it.
    """
    global _HELD
    if stream is None:
        stream = sys.stderr
    project = Path(project)
    path = _lock_path(project)

    if path.exists():
        data = _read_lock(path)
        holder_pid = -1
        if data is not None:
            try:
                holder_pid = int(data.get("pid", -1))
            except (TypeError, ValueError):
                holder_pid = -1
        if data is not None and holder_pid > 0 and _pid_alive(holder_pid):
            holder_runner = data.get("runner", "?")
            holder_ts = data.get("timestamp", "?")
            print(
                f"CONCURRENT_RUN_REFUSED: project {project} is already "
                f"being driven by a live runner (holder pid={holder_pid}, "
                f"runner={holder_runner}, since={holder_ts}, "
                f"lock={path}). Single-driver principle: at most one "
                f"runner per project directory. Kill or wait for the "
                f"holder before re-invoking.",
                file=stream,
            )
            return None
        # Stale lock: garbage file, or dead/unknown holder pid.
        reason = ("unparseable lock file" if data is None
                  else f"holder pid={holder_pid} is not alive")
        print(
            f"STALE_RUNNER_LOCK: removing stale {path} ({reason}); "
            f"proceeding.",
            file=stream,
        )
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            # Could not remove — fall through and overwrite on _write().
            pass

    lock = RunnerLock(project, runner_name)
    try:
        lock._write()
    except Exception as exc:
        # If we cannot even write the lock, degrade to "proceed without
        # lock" rather than blocking the flow — the lock is best-effort.
        # Return the holder anyway so the caller proceeds; release() is a
        # no-op when no file was written.
        print(
            f"RUNNER_LOCK_WRITE_FAILED: could not write {path} ({exc}); "
            f"proceeding WITHOUT a lock.",
            file=stream,
        )
        lock._released = True  # nothing to clean up
        return lock
    _HELD = lock
    _install_release_handlers(lock)
    return lock


def acquire_or_reenter(project: Path,
                       runner_name: str,
                       stream=None) -> Optional[object]:
    """ORGANIC #588 — the single entry point ALL four runners call
    (orchestrator + standalone phase1/2/3).

    Re-entrancy: when the ``VIBE_IC_RUNNER_LOCK_TOKEN`` env var names
    THIS project AND the named holder pid still owns a live lock file on
    it, return a :class:`ReentrantLock` (the parent orchestrator's lock
    already covers this child) instead of refusing. Otherwise behave
    exactly like :func:`acquire`:
      * live foreign holder → ``CONCURRENT_RUN_REFUSED``, return None;
      * stale holder        → ``STALE_RUNNER_LOCK``, clean + take;
      * no holder           → take the lock.

    This closes the hole where a standalone phase runner neither took
    nor honored the lock: a second standalone phase3 on a live project
    is now refused by name, while the orchestrator's own delegated
    sub-runs re-enter cleanly via the token."""
    if stream is None:
        stream = sys.stderr
    project = Path(project)
    token = os.environ.get(REENTRANCY_ENV, "")
    if token:
        try:
            holder_pid_s, holder_proj = token.split(":", 1)
            holder_pid = int(holder_pid_s)
        except (ValueError, AttributeError):
            holder_pid, holder_proj = -1, ""
        if (holder_proj == str(project.resolve())
                and holder_pid > 0 and _pid_alive(holder_pid)):
            data = _read_lock(_lock_path(project))
            # Re-enter only when a live lock file genuinely exists for
            # the named holder — a stale token must not bypass a real
            # foreign lock.
            if data is not None and int(data.get("pid", -1)) == holder_pid:
                print(
                    f"RUNNER_LOCK_REENTRANT: {runner_name} re-enters the "
                    f"lock held by parent pid={holder_pid} on {project} "
                    f"(#588 delegated sub-run).",
                    file=stream,
                )
                return ReentrantLock(project, runner_name, holder_pid)
    return acquire(project, runner_name, stream=stream)

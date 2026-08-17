#!/usr/bin/env python3
"""One-job Linux supervisor with attributable descendant ownership.

The caller intentionally starts one instance of this helper for each job.  That
process boundary is load-bearing: Linux child-subreaper state and ``waitpid(-1)``
are process-global, so neither is safe inside the threaded hygiene dispatcher.

An owned job is identified by PID *and* ``/proc`` starttime.  Session-detached
and double-forked descendants adopt to this helper, are retained by a fresh
descendant census, and are signalled through pidfds.  A terminal result is
published only after a complete final census explicitly contains zero owned
processes.  There is no whole-run wall timeout; the underlying watchdog uses
forward progress, and post-SIGKILL completion waits on kernel exit events.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import os
import select
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import _watchdog as _wd
from _atomic_artefact import write_json

_PR_SET_CHILD_SUBREAPER = 36
_PROTOCOL = 1
_TERM_GRACE_S = 2.0
Identity = Tuple[int, int]  # (pid, /proc starttime)


@dataclass(frozen=True)
class OwnedRunResult:
    protocol: int
    rc: int
    body: str
    problem: Optional[str]
    outcome: str
    launched: bool
    census_ok: bool
    final_descendants: List[Dict[str, int]]
    observed: List[Dict[str, int]]
    capability_error: str = ""


@dataclass(frozen=True)
class CleanupResult:
    observed: Set[Identity]
    survivors: Set[Identity]
    census_ok: bool


_ACTIVE_JOB: Optional[Tuple[subprocess.Popen, Identity, Set[Identity]]] = None
_IN_SHUTDOWN = False


def _identity_rows(identities: Iterable[Identity]) -> List[Dict[str, int]]:
    return [{"pid": pid, "starttime": start}
            for pid, start in sorted(set(identities))]


def _enable_subreaper() -> bool:
    if os.name != "posix" or not Path("/proc").is_dir():
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (AttributeError, OSError):
        return False


def _read_proc_identity(pid: int) -> Optional[Tuple[int, int]]:
    """Return ``(ppid, starttime)``; None means the PID vanished."""
    path = Path(f"/proc/{pid}/stat")
    try:
        raw = path.read_text(errors="replace")
        fields = raw[raw.rfind(")") + 2:].split()
        return int(fields[1]), int(fields[19])
    except FileNotFoundError:
        return None


def _proc_snapshot_checked() -> Tuple[Dict[int, Tuple[int, int]], bool]:
    out: Dict[int, Tuple[int, int]] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return {}, False
    complete = True
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            identity = _read_proc_identity(int(entry.name))
            if identity is not None:
                out[int(entry.name)] = identity
        except (OSError, ValueError, IndexError):
            try:
                if entry.exists():
                    complete = False
            except OSError:
                complete = False
    return out, complete


def _descendants(snapshot: Dict[int, Tuple[int, int]], root: int) -> Set[int]:
    found: Set[int] = set()
    frontier = {root}
    while frontier:
        children = {pid for pid, (ppid, _start) in snapshot.items()
                    if ppid in frontier and pid not in found}
        found.update(children)
        frontier = children
    return found


def _job_processes_checked(
        root: Identity, baseline: Set[Identity]) -> Tuple[Set[Identity], bool]:
    """Census root descendants plus newly-adopted helper descendants."""
    snapshot, complete = _proc_snapshot_checked()
    root_pid, root_starttime = root
    pids: Set[int] = set()
    if root_pid in snapshot:
        if snapshot[root_pid][1] == root_starttime:
            pids.update(_descendants(snapshot, root_pid))
            pids.add(root_pid)
        else:
            # Never walk a same-number replacement as if it were the launched
            # root.  The mismatch makes the result fail closed even if the
            # helper later proves that all truly-owned children are gone.
            complete = False
    # Once a wrapper exits, a setsid/double-fork descendant is no longer below
    # root_pid.  As this helper launches exactly one job, every identity newly
    # below the helper is attributable to that job; pre-launch identities are
    # the only exclusions.
    for pid in _descendants(snapshot, os.getpid()):
        identity = (pid, snapshot[pid][1])
        if identity not in baseline:
            pids.add(pid)
    return ({(pid, snapshot[pid][1]) for pid in pids if pid in snapshot},
            complete)


def _reap_adopted() -> None:
    """Reap only inside the one-job helper, never the threaded dispatcher."""
    # watchdog-exempt: WNOHANG returns zero after the finite exited-child queue
    # is drained; this loop never waits for a running process.
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _open_identity_pidfd(identity: Identity) -> Tuple[Optional[int], bool]:
    """Open a stable handle and prove it still names the observed starttime.

    ``False`` means a PID-reuse/census error occurred.  A process that simply
    vanished is benign and returns ``(None, True)``.
    """
    pid, starttime = identity
    try:
        before = _read_proc_identity(pid)
    except (OSError, ValueError, IndexError):
        return None, False
    if before is None:
        return None, True
    if before[1] != starttime:
        return None, False
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        return None, True
    except OSError:
        return None, False
    try:
        after = _read_proc_identity(pid)
    except (OSError, ValueError, IndexError):
        os.close(pidfd)
        return None, False
    if after is None:
        os.close(pidfd)
        return None, True
    if after[1] != starttime:
        # The PID was reused across pidfd_open.  Never signal that replacement.
        os.close(pidfd)
        return None, False
    return pidfd, True


def _open_pidfds(identities: Iterable[Identity]
                 ) -> Tuple[Dict[int, Identity], bool]:
    handles: Dict[int, Identity] = {}
    complete = True
    for identity in sorted(set(identities)):
        pidfd, ok = _open_identity_pidfd(identity)
        complete = complete and ok
        if pidfd is not None:
            handles[pidfd] = identity
    return handles, complete


def _signal_pidfds(handles: Iterable[int], sig: int) -> bool:
    complete = True
    for pidfd in list(handles):
        try:
            signal.pidfd_send_signal(pidfd, sig)
        except ProcessLookupError:
            pass
        except OSError as exc:
            if exc.errno != errno.ESRCH:
                complete = False
    return complete


def _wait_pidfds_until(handles: Dict[int, Identity], deadline: float
                       ) -> Dict[int, Identity]:
    """Give SIGTERM a policy grace; return only handles still executing."""
    remaining = dict(handles)
    poller = select.poll()
    for pidfd in remaining:
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while remaining:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        events = poller.poll(max(1, int(left * 1000)))
        for pidfd, _event in events:
            if pidfd in remaining:
                poller.unregister(pidfd)
                remaining.pop(pidfd, None)
    return remaining


def _wait_pidfds(handles: Dict[int, Identity]) -> None:
    """Wait for kernel exit events, with no guessed wall-clock deadline."""
    remaining = set(handles)
    if not remaining:
        return
    poller = select.poll()
    for pidfd in remaining:
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while remaining:
        for pidfd, _event in poller.poll():
            if pidfd in remaining:
                poller.unregister(pidfd)
                remaining.remove(pidfd)


def _close_pidfds(handles: Iterable[int]) -> None:
    for pidfd in handles:
        try:
            os.close(pidfd)
        except OSError:
            pass


def _cleanup_job(proc: subprocess.Popen, root: Identity,
                 baseline: Set[Identity],
                 *, term_grace_s: float = _TERM_GRACE_S) -> CleanupResult:
    """Stop every attributable identity and prove a complete final zero.

    The TERM interval is a shutdown policy, not an estimate of job runtime.
    Once SIGKILL is sent, completion is driven solely by pidfd exit events.
    Newly-forked/adopted identities are censused in subsequent kill waves.
    """
    observed: Set[Identity] = set()
    census_ok = True
    current, scan_ok = _job_processes_checked(root, baseline)
    census_ok = census_ok and scan_ok
    observed.update(current)

    term_handles, open_ok = _open_pidfds(current)
    census_ok = census_ok and open_ok
    census_ok = _signal_pidfds(term_handles, signal.SIGTERM) and census_ok
    remaining = _wait_pidfds_until(
        term_handles, time.monotonic() + term_grace_s)
    census_ok = _signal_pidfds(remaining, signal.SIGKILL) and census_ok
    _wait_pidfds(remaining)
    _close_pidfds(term_handles)

    # The root's pidfd event is ready now.  Let Popen own its wait status before
    # waitpid(-1) reaps adopted grandchildren; this avoids false rc=0 rewrites.
    try:
        proc.wait()
    except ChildProcessError:
        census_ok = False
    _reap_adopted()

    # watchdog-exempt: after SIGKILL, each wave blocks on kernel pidfd exit
    # events and a fresh complete census; an iteration/runtime cap would permit
    # returning before the required final attributable census is exactly zero.
    while True:
        current, scan_ok = _job_processes_checked(root, baseline)
        census_ok = census_ok and scan_ok
        observed.update(current)
        if not current:
            # A second complete pass is the load-bearing final-zero record.
            final, final_ok = _job_processes_checked(root, baseline)
            census_ok = census_ok and final_ok
            observed.update(final)
            if not final:
                return CleanupResult(observed, set(), census_ok)
            current = final

        handles, open_ok = _open_pidfds(current)
        census_ok = census_ok and open_ok
        # A same-PID/new-starttime replacement is never signalled through the
        # stale identity.  The fresh census supplies its own verified pidfd.
        if not handles:
            time.sleep(0.01)
            continue
        census_ok = _signal_pidfds(handles, signal.SIGKILL) and census_ok
        _wait_pidfds(handles)
        _close_pidfds(handles)
        _reap_adopted()


def _capability_error() -> str:
    if os.name != "posix" or not Path("/proc").is_dir():
        return "Linux /proc process identities are unavailable"
    if not hasattr(os, "pidfd_open"):
        return "os.pidfd_open is unavailable"
    if not hasattr(signal, "pidfd_send_signal"):
        return "signal.pidfd_send_signal is unavailable"
    if not hasattr(select, "poll"):
        return "select.poll is unavailable"
    try:
        probe = os.pidfd_open(os.getpid())
    except OSError as exc:
        return f"pidfd_open kernel probe failed: {exc}"
    else:
        os.close(probe)
    if not _enable_subreaper():
        return "PR_SET_CHILD_SUBREAPER is unavailable"
    snapshot, complete = _proc_snapshot_checked()
    if not complete or os.getpid() not in snapshot:
        return "complete /proc PID/starttime census is unavailable"
    return ""


def _shutdown_handler(signum, _frame) -> None:
    global _IN_SHUTDOWN
    if not _IN_SHUTDOWN:
        _IN_SHUTDOWN = True
        active = _ACTIVE_JOB
        if active is not None:
            _cleanup_job(active[0], active[1], active[2])
    raise SystemExit(128 + int(signum))


def run_owned(argv: Sequence[str], cwd: Path, env: Dict[str, str], *,
              progress_path: Optional[Path], stall_grace_s: float,
              poll_s: float) -> OwnedRunResult:
    """Run one job and return only after its final owned census is zero."""
    global _ACTIVE_JOB
    capability_error = _capability_error()
    if capability_error:
        return OwnedRunResult(
            _PROTOCOL, 2, "",
            "OWNERSHIP_UNAVAILABLE: " + capability_error,
            "ownership_unavailable", False, False, [], [], capability_error)

    snapshot, initial_ok = _proc_snapshot_checked()
    baseline = {(pid, start) for pid, (_ppid, start) in snapshot.items()
                if pid in _descendants(snapshot, os.getpid())}
    if not initial_ok:
        return OwnedRunResult(
            _PROTOCOL, 2, "", "OWNERSHIP_CENSUS_INCOMPLETE: initial census",
            "ownership_unavailable", False, False, [], [],
            "initial census incomplete")

    old_term = signal.signal(signal.SIGTERM, _shutdown_handler)
    old_int = signal.signal(signal.SIGINT, _shutdown_handler)
    holder: Dict[str, subprocess.Popen] = {}
    root_identity: Dict[str, Identity] = {}
    launch_identity_ok = True
    cleanups: List[CleanupResult] = []

    def _popen(command, **kwargs):
        global _ACTIVE_JOB
        nonlocal launch_identity_ok
        kwargs.pop("stderr", None)
        proc = subprocess.Popen(
            command, cwd=str(cwd), start_new_session=True,
            stderr=subprocess.STDOUT, **kwargs)
        try:
            observed = _read_proc_identity(proc.pid)
        except (OSError, ValueError, IndexError):
            observed = None
        if observed is None:
            # The helper is still the direct parent, so its adopted-descendant
            # census can clean the job.  The missing root starttime nevertheless
            # makes the ownership record fail closed.
            root = (proc.pid, -1)
            launch_identity_ok = False
        else:
            root = (proc.pid, observed[1])
        holder["proc"] = proc
        root_identity["value"] = root
        _ACTIVE_JOB = (proc, root, baseline)
        return proc

    def _kill(proc, _reason):
        cleanups.append(_cleanup_job(
            proc, root_identity["value"], baseline))

    try:
        result = _wd.run_supervised(
            list(argv), env=env, log_path=progress_path,
            stall_grace_s=stall_grace_s, poll_s=poll_s,
            hard_ceiling_s=float("inf"), popen_factory=_popen, kill=_kill)
        proc = holder.get("proc")
        observed: Set[Identity] = set()
        census_ok = initial_ok and launch_identity_ok
        for cleanup in cleanups:
            observed.update(cleanup.observed)
            census_ok = census_ok and cleanup.census_ok

        leaked_after_natural: Set[Identity] = set()
        if proc is not None:
            _reap_adopted()
            root = root_identity["value"]
            live, live_ok = _job_processes_checked(root, baseline)
            census_ok = census_ok and live_ok
            observed.update(live)
            if result.outcome == "natural" and live:
                leaked_after_natural = set(live)
            if live or not live_ok:
                cleanup = _cleanup_job(proc, root, baseline)
                cleanups.append(cleanup)
                observed.update(cleanup.observed)
                census_ok = census_ok and cleanup.census_ok

        _reap_adopted()
        final: Set[Identity] = set()
        final_ok = True
        if proc is not None:
            final, final_ok = _job_processes_checked(
                root_identity["value"], baseline)
            observed.update(final)
        census_ok = census_ok and final_ok
        if final:
            # Never publish a terminal protocol record with owned work alive.
            # The exception path performs another event-driven cleanup; the
            # outer dispatcher then receives NORECORD rather than a verdict.
            raise RuntimeError(
                "final owned descendant census is non-zero: "
                f"{_identity_rows(final)}")

        body = (result.out or "") + (result.err or "")
        problems: List[str] = []
        if result.outcome != "natural":
            problems.append(
                f"progress watchdog outcome={result.outcome}, rc={result.rc}; "
                "the shard did not complete naturally")
        if leaked_after_natural:
            problems.append(
                "LIVE_DESCENDANTS_CLEANED: natural exit left owned work; "
                f"cleaned={_identity_rows(leaked_after_natural)}")
        if not census_ok:
            problems.append(
                "OWNERSHIP_CENSUS_INCOMPLETE: PID/starttime ownership could "
                "not be proved continuously")
        return OwnedRunResult(
            _PROTOCOL, result.rc, body,
            "; ".join(problems) if problems else None,
            result.outcome, proc is not None, census_ok,
            _identity_rows(final), _identity_rows(observed))
    except BaseException:
        # A helper/probe exception is NO RECORD, but it still must not abandon
        # the child it already owns.  Cleanup remains event-driven and will not
        # return from this exception path before the attributable census is zero.
        proc = holder.get("proc")
        root = root_identity.get("value")
        if proc is not None and root is not None:
            _cleanup_job(proc, root, baseline)
        raise
    finally:
        _ACTIVE_JOB = None
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--stall-grace", type=float, required=True)
    parser.add_argument("--poll", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command or args.stall_grace <= 0 or args.poll <= 0:
        parser.error("a command and positive progress windows are required")
    result = run_owned(
        command, args.cwd, os.environ.copy(), progress_path=args.progress,
        stall_grace_s=args.stall_grace, poll_s=args.poll)
    write_json(args.result, asdict(result), ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

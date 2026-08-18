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
forward progress.  A durable termination-pending transition releases the outer
dispatcher with rc 2 while this isolated helper continues to own and reap work
until kernel exit events plus a complete final census prove zero descendants.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import select
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import _watchdog as _wd
import _semantic_child_progress as _semantic_progress
import gate_process_attestation as _attest
from _atomic_artefact import write_json

_PR_SET_CHILD_SUBREAPER = 36
_PROTOCOL = 1
_TERM_GRACE_S = 2.0
_KILL_CONFIRM_GRACE_S = 1.0
_REAPER_POLL_MS = 100
Identity = Tuple[int, int]  # (pid, /proc starttime)
PendingNotifier = Callable[[str, Set[Identity], bool], None]
_MAX_ATTESTATION_PROGRESS_BYTES = 64 * 1024 * 1024


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


@dataclass(frozen=True)
class ActiveJob:
    proc: subprocess.Popen
    root: Identity
    baseline: Set[Identity]
    root_pidfd: Optional[int]
    pending_notifier: Optional[PendingNotifier]


_ACTIVE_JOB: Optional[ActiveJob] = None
_IN_SHUTDOWN = False
_SHUTDOWN_CLEANUP: Optional[CleanupResult] = None


class _AttestationProgressProbe:
    """Count only complete, digest-valid, append-only gate attestations."""

    def __init__(self, path: Path, expected_labels: Sequence[str]):
        self.path = path
        self.expected = frozenset(expected_labels)
        if len(self.expected) != len(expected_labels):
            raise ValueError("expected progress labels are not unique")
        self.identity: Optional[Tuple[int, int]] = None
        self.size = 0
        self.rows: List[str] = []
        self.error = ""

    def _fail(self, reason: str) -> None:
        if not self.error:
            self.error = reason

    def sample(self, *, final: bool = False) -> int:
        if self.error:
            return len(self.rows)
        try:
            st = self.path.stat()
        except FileNotFoundError:
            if self.identity is not None:
                self._fail("attestation progress file disappeared")
            return len(self.rows)
        except OSError as exc:
            self._fail(f"attestation progress file unreadable: {exc}")
            return len(self.rows)
        observed = (st.st_dev, st.st_ino)
        if self.identity is None:
            self.identity = observed
        elif observed != self.identity:
            self._fail("attestation progress file identity changed")
            return len(self.rows)
        if st.st_size < self.size:
            self._fail("attestation progress file was truncated")
            return len(self.rows)
        if st.st_size > _MAX_ATTESTATION_PROGRESS_BYTES:
            self._fail("attestation progress file exceeds resource limit")
            return len(self.rows)
        try:
            raw = self.path.read_bytes()
            complete, separator, tail = raw.rpartition(b"\n")
            if not separator:
                complete = b""
                tail = raw
            if final and tail:
                raise ValueError("truncated final attestation record")
            records = []
            for lineno, line in enumerate(complete.splitlines(), 1):
                if not line.strip():
                    raise ValueError(
                        f"empty attestation progress line {lineno}")
                record = _attest.strict_loads(line.decode("utf-8"))
                records.append(_attest.validate_record(record, lineno))
        except (OSError, ValueError, TypeError, UnicodeDecodeError,
                json.JSONDecodeError) as exc:
            self._fail(f"invalid attestation progress protocol: {exc}")
            return len(self.rows)
        if len(records) > len(self.expected):
            self._fail("attestation progress exceeds assigned gate count")
            return len(self.rows)
        canonical = [json.dumps(row, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":")) for row in records]
        if canonical[:len(self.rows)] != self.rows:
            self._fail("attestation progress history was rewritten")
            return len(self.rows)
        labels = [str(row.get("label")) for row in records]
        if len(labels) != len(set(labels)):
            self._fail("duplicate gate label in attestation progress")
            return len(self.rows)
        unexpected = set(labels) - self.expected
        if unexpected:
            self._fail(
                "unassigned gate label in attestation progress: "
                + ", ".join(sorted(unexpected)[:3]))
            return len(self.rows)
        self.rows = canonical
        self.size = st.st_size
        return len(self.rows)

    def complete(self) -> str:
        self.sample(final=True)
        if not self.error and {_attest.strict_loads(row)["label"]
                               for row in self.rows} \
                != self.expected:
            missing = self.expected - {
                str(_attest.strict_loads(row).get("label"))
                for row in self.rows}
            self._fail(
                "attestation progress ended before assigned gates completed: "
                + ", ".join(sorted(missing)[:3]))
        return self.error


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
    """Reap on kernel exit events with a finite observability cadence.

    The loop has no total runtime estimate: a D-state task may retain its
    dedicated helper for as long as the kernel needs.  Each individual poll is
    bounded, however, so the helper remains inspectable and never disappears
    into an unobservable ``poll(None)`` wait.
    """
    remaining = set(handles)
    if not remaining:
        return
    poller = select.poll()
    for pidfd in remaining:
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while remaining:
        for pidfd, _event in poller.poll(_REAPER_POLL_MS):
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
                 *, root_pidfd: Optional[int] = None,
                 pending_notifier: Optional[PendingNotifier] = None,
                 term_grace_s: float = _TERM_GRACE_S) -> CleanupResult:
    """Stop every attributable identity and prove a complete final zero.

    The TERM interval is a shutdown policy, not an estimate of job runtime.
    Once SIGKILL is sent, completion is driven solely by pidfd exit events.
    Newly-forked/adopted identities are censused in subsequent kill waves.
    """
    def notify(reason: str, identities: Set[Identity], complete: bool) -> None:
        if pending_notifier is not None:
            try:
                pending_notifier(reason, set(identities), complete)
            except Exception:
                # Observability must be louder, never more destructive: a
                # sidecar/pipe failure cannot abort the only subreaper that
                # still owns live work.  The production notifier has an
                # independent pipe fallback; this guard protects cleanup from
                # injected or future notifier failures as well.
                pass

    observed: Set[Identity] = set()
    census_ok = True
    current, scan_ok = _job_processes_checked(root, baseline)
    census_ok = census_ok and scan_ok
    observed.update(current)
    if not scan_ok:
        notify("census_incomplete", current, False)

    term_handles, open_ok = _open_pidfds(current)
    census_ok = census_ok and open_ok
    if (root_pidfd is not None and proc.poll() is None
            and root not in term_handles.values()):
        try:
            term_handles[os.dup(root_pidfd)] = root
        except OSError:
            census_ok = False
            notify("root_pidfd_dup_failed", current or {root}, False)
    census_ok = _signal_pidfds(term_handles, signal.SIGTERM) and census_ok
    remaining = _wait_pidfds_until(
        term_handles, time.monotonic() + term_grace_s)
    census_ok = _signal_pidfds(remaining, signal.SIGKILL) and census_ok
    kill_pending = _wait_pidfds_until(
        remaining, time.monotonic() + _KILL_CONFIRM_GRACE_S)
    if kill_pending:
        notify("sigkill_pending", set(kill_pending.values()), census_ok)
        # This helper remains the attributable subreaper.  The outer dispatcher
        # has already received a named rc=2 state and need not wait; this loop is
        # event-driven and keeps ownership until the kernel confirms exit.
        _wait_pidfds(kill_pending)
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
        if not scan_ok:
            # UNKNOWN is not zero.  Tell the dispatcher immediately, then keep
            # this isolated helper alive until a complete census recovers.
            notify("census_incomplete", current, False)
        if not current and scan_ok:
            # A second complete pass is the load-bearing final-zero record.
            final, final_ok = _job_processes_checked(root, baseline)
            census_ok = census_ok and final_ok
            observed.update(final)
            if not final and final_ok:
                return CleanupResult(observed, set(), census_ok)
            if not final_ok:
                notify("census_incomplete", final, False)
            current = final
        if not current:
            time.sleep(_REAPER_POLL_MS / 1000.0)
            continue

        handles, open_ok = _open_pidfds(current)
        census_ok = census_ok and open_ok
        # A same-PID/new-starttime replacement is never signalled through the
        # stale identity.  The fresh census supplies its own verified pidfd.
        if not handles:
            notify("pidfd_unavailable", current, False)
            time.sleep(_REAPER_POLL_MS / 1000.0)
            continue
        census_ok = _signal_pidfds(handles, signal.SIGKILL) and census_ok
        kill_pending = _wait_pidfds_until(
            handles, time.monotonic() + _KILL_CONFIRM_GRACE_S)
        if kill_pending:
            notify("sigkill_pending", set(kill_pending.values()), census_ok)
            _wait_pidfds(kill_pending)
        _close_pidfds(handles)
        _reap_adopted()


def _capability_error() -> str:
    if os.name != "posix" or not Path("/proc").is_dir():
        return "Linux /proc process identities are unavailable"
    if not hasattr(os, "pidfd_open"):
        return "os.pidfd_open is unavailable"
    if not hasattr(signal, "pidfd_send_signal"):
        return "signal.pidfd_send_signal is unavailable"
    if not hasattr(signal, "pthread_sigmask"):
        return "signal.pthread_sigmask is unavailable"
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
    global _IN_SHUTDOWN, _SHUTDOWN_CLEANUP
    if _IN_SHUTDOWN:
        # A second TERM/INT must not interrupt the cleanup already retaining
        # reaper ownership.  SIGKILL remains the caller's explicit hard stop.
        return
    _IN_SHUTDOWN = True
    signal.pthread_sigmask(
        signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    active = _ACTIVE_JOB
    if active is not None:
        _SHUTDOWN_CLEANUP = _cleanup_job(
            active.proc, active.root, active.baseline,
            root_pidfd=active.root_pidfd,
            pending_notifier=active.pending_notifier)
    raise SystemExit(128 + int(signum))


def run_owned(argv: Sequence[str], cwd: Path, env: Dict[str, str], *,
              progress_path: Optional[Path], stall_grace_s: float,
              poll_s: float,
              output_progress: bool = True,
              semantic_progress: bool = False,
              expected_progress_labels: Optional[Sequence[str]] = None,
              semantic_progress_monitor: Optional[
                  _semantic_progress.ParentMonitor] = None,
              pending_notifier: Optional[PendingNotifier] = None
              ) -> OwnedRunResult:
    """Run one job and return only after its final owned census is zero."""
    global _ACTIVE_JOB, _IN_SHUTDOWN, _SHUTDOWN_CLEANUP
    _IN_SHUTDOWN = False
    _SHUTDOWN_CLEANUP = None
    if semantic_progress_monitor is not None and (
            progress_path is not None or output_progress
            or semantic_progress or expected_progress_labels is not None):
        return OwnedRunResult(
            _PROTOCOL, 2, "",
            "INVALID_PROGRESS_POLICY: semantic child progress is exclusive "
            "with stdout and generic/attestation renewal",
            "policy_refused", False, False, [], [],
            "semantic/output/log/attestation progress policies are exclusive")
    if progress_path is not None and (
            output_progress or not semantic_progress
            or expected_progress_labels is None):
        return OwnedRunResult(
            _PROTOCOL, 2, "",
            "INVALID_PROGRESS_POLICY: a progress path is accepted only as "
            "an explicit semantic attestation channel with output disabled",
            "policy_refused", False, False, [], [],
            "atomic/output/attestation progress policies are exclusive")
    if progress_path is None and expected_progress_labels is not None:
        return OwnedRunResult(
            _PROTOCOL, 2, "",
            "INVALID_PROGRESS_POLICY: assigned progress labels were supplied "
            "without a semantic progress channel",
            "policy_refused", False, False, [], [],
            "orphan expected-progress manifest")
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
    root_pidfd_holder: Dict[str, int] = {}
    launch_identity_ok = True
    cleanups: List[CleanupResult] = []

    def _popen(command, **kwargs):
        global _ACTIVE_JOB
        nonlocal launch_identity_ok
        kwargs.pop("stderr", None)
        try:
            previous_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        except (AttributeError, OSError):
            raise RuntimeError(
                "shutdown signals cannot be blocked during ownership launch")
        try:
            # A forked child inherits the calling thread's signal mask.  Restore
            # the pre-critical-section mask in this dedicated, single-threaded
            # helper's child so TERM remains a real graceful-shutdown phase for
            # the supervised job instead of being silently blocked forever.
            def restore_child_signal_mask() -> None:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

            proc = subprocess.Popen(
                command, cwd=str(cwd), start_new_session=True,
                stderr=subprocess.STDOUT,
                preexec_fn=restore_child_signal_mask, **kwargs)
            if semantic_progress_monitor is not None:
                semantic_progress_monitor.bind_pid(proc.pid)
            holder["proc"] = proc
            root = (proc.pid, -1)
            root_identity["value"] = root
            try:
                root_fd = os.pidfd_open(proc.pid)
            except OSError:
                root_fd = None
                launch_identity_ok = False
            else:
                root_pidfd_holder["value"] = root_fd

            # Register a directly-signalable child BEFORE the fallible /proc
            # starttime read and before pending TERM/INT can be delivered.
            _ACTIVE_JOB = ActiveJob(
                proc, root, baseline, root_fd, pending_notifier)
            try:
                observed = _read_proc_identity(proc.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            if observed is None:
                # The stable root pidfd remains enough to stop the direct child;
                # census integrity is still marked false until ancestry recovers.
                launch_identity_ok = False
            else:
                root = (proc.pid, observed[1])
                root_identity["value"] = root
                _ACTIVE_JOB = ActiveJob(
                    proc, root, baseline, root_fd, pending_notifier)
            return proc
        finally:
            # A TERM/INT received anywhere after Popen is delivered only after
            # `_ACTIVE_JOB` owns a pidfd-backed cleanup path.
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def _kill(proc, _reason):
        cleanups.append(_cleanup_job(
            proc, root_identity["value"], baseline,
            root_pidfd=root_pidfd_holder.get("value"),
            pending_notifier=pending_notifier))

    try:
        attestation_probe = (
            _AttestationProgressProbe(
                progress_path, list(expected_progress_labels or ()))
            if progress_path is not None else None)
        result = _wd.run_supervised(
            list(argv), env=env, log_path=None,
            output_progress=output_progress,
            domain_progress_probe=(
                attestation_probe.sample if attestation_probe is not None
                else semantic_progress_monitor.sample
                if semantic_progress_monitor is not None else None),
            abort_probe=(
                (lambda: semantic_progress_monitor.error or None)
                if semantic_progress_monitor is not None else None),
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
                cleanup = _cleanup_job(
                    proc, root, baseline,
                    root_pidfd=root_pidfd_holder.get("value"),
                    pending_notifier=pending_notifier)
                cleanups.append(cleanup)
                observed.update(cleanup.observed)
                census_ok = census_ok and cleanup.census_ok

        _reap_adopted()
        final: Set[Identity] = set()
        final_ok = True
        if proc is not None:
            while True:
                final, final_ok = _job_processes_checked(
                    root_identity["value"], baseline)
                observed.update(final)
                if not final and final_ok:
                    break
                cleanup = _cleanup_job(
                    proc, root_identity["value"], baseline,
                    root_pidfd=root_pidfd_holder.get("value"),
                    pending_notifier=pending_notifier)
                cleanups.append(cleanup)
                observed.update(cleanup.observed)
                census_ok = census_ok and cleanup.census_ok
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
        if attestation_probe is not None:
            progress_error = attestation_probe.complete()
            if progress_error:
                problems.append(
                    "PROGRESS_PROTOCOL_INCOMPLETE: "
                    + progress_error)
        if semantic_progress_monitor is not None:
            progress_error = semantic_progress_monitor.complete()
            if progress_error:
                problems.append(
                    "SEMANTIC_PROGRESS_NORECORD: " + progress_error)
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
            _cleanup_job(
                proc, root, baseline,
                root_pidfd=root_pidfd_holder.get("value"),
                pending_notifier=pending_notifier)
        raise
    finally:
        _ACTIVE_JOB = None
        root_fd = root_pidfd_holder.get("value")
        if root_fd is not None:
            try:
                os.close(root_fd)
            except OSError:
                pass
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--event-fd", type=int)
    parser.add_argument("--cwd", type=Path, required=True)
    progress_mode = parser.add_mutually_exclusive_group()
    progress_mode.add_argument("--progress", type=Path)
    progress_mode.add_argument(
        "--atomic", action="store_true",
        help="treat natural child completion as the only progress transition; "
             "stdout/CPU cannot renew the no-record lease")
    progress_mode.add_argument("--semantic-progress-manifest", type=Path)
    parser.add_argument("--expected-progress-labels", type=Path)
    parser.add_argument("--stall-grace", type=float, required=True)
    parser.add_argument("--poll", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command or args.stall_grace <= 0 or args.poll <= 0:
        parser.error("a command and positive progress windows are required")
    if (args.progress is None) != (args.expected_progress_labels is None):
        parser.error("--progress and --expected-progress-labels are required together")
    expected_progress_labels = None
    if args.expected_progress_labels is not None:
        try:
            expected_doc = _attest.strict_loads(
                args.expected_progress_labels.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"unreadable expected progress labels: {exc}")
        if (not isinstance(expected_doc, dict)
                or set(expected_doc) != {"schema", "labels"}
                or expected_doc.get("schema") != 1
                or not isinstance(expected_doc.get("labels"), list)
                or not all(isinstance(label, str) and label
                           for label in expected_doc["labels"])
                or len(expected_doc["labels"])
                != len(set(expected_doc["labels"]))):
            parser.error("expected progress labels have the wrong schema")
        expected_progress_labels = expected_doc["labels"]
    event_fd = args.event_fd
    if event_fd is not None:
        # The dispatcher passed this descriptor only to the helper.  Restore
        # CLOEXEC before launching the supervised command so an adversarial
        # descendant cannot forge supervisor state on the private channel.
        os.set_inheritable(event_fd, False)
    own_identity = _read_proc_identity(os.getpid())
    own_starttime = own_identity[1] if own_identity is not None else -1
    if args.status is not None:
        write_json(args.status, {
            "protocol": _PROTOCOL,
            "state": "running",
            "reaper_pid": os.getpid(),
            "reaper_starttime": own_starttime,
        }, ensure_ascii=False)
    pending_events: List[Dict[str, object]] = []
    announced: Set[Tuple[str, Tuple[Identity, ...]]] = set()

    def emit_private_event(event: Dict[str, object]) -> None:
        if event_fd is None:
            return
        payload = (json.dumps(event, ensure_ascii=True, sort_keys=True)
                   + "\n").encode("ascii")
        while payload:
            written = os.write(event_fd, payload)
            if written <= 0:
                raise BrokenPipeError(
                    "private semantic progress relay made no progress")
            payload = payload[written:]

    def notify_progress(scope: str, completed: int, total: int) -> None:
        # This descriptor is private to the trusted supervisor.  The direct
        # child writes only its nonce-bound journal and never inherits the
        # relay channel consumed by the outer parent.
        emit_private_event({
            "protocol": _semantic_progress.SCHEMA,
            "state": "domain_progress",
            "scope": scope,
            "completed": completed,
            "total": total,
        })

    def notify_pending(reason: str, identities: Set[Identity],
                       census_ok: bool) -> None:
        key = (reason, tuple(sorted(identities)))
        if key in announced:
            return
        announced.add(key)
        event: Dict[str, object] = {
            "protocol": _PROTOCOL,
            "state": "termination_pending",
            "reason": reason,
            "reaper_pid": os.getpid(),
            "reaper_starttime": own_starttime,
            "pending_descendants": _identity_rows(identities),
            "census_ok": bool(census_ok),
        }
        pending_events.append(event)
        if args.status is not None:
            try:
                write_json(args.status, {
                    "protocol": _PROTOCOL,
                    "state": "termination_pending",
                    "events": pending_events,
                }, ensure_ascii=False)
            except (OSError, TypeError, ValueError) as exc:
                # The private pipe is an independent state channel.  Report
                # the durable-record failure there, keep cleanup running, and
                # let the outer dispatcher retain this helper with rc=2.
                event["status_error"] = (
                    f"{type(exc).__name__}: {exc}")
        if event_fd is not None:
            try:
                emit_private_event(event)
            except (BrokenPipeError, OSError):
                # The dispatcher may already have returned rc=2.  The durable
                # sidecar remains inspectable and this helper keeps ownership.
                pass

    semantic_monitor = None
    if args.semantic_progress_manifest is not None:
        try:
            semantic_monitor = _semantic_progress.ParentMonitor.from_manifest(
                args.semantic_progress_manifest, notify_progress)
        except (OSError, ValueError,
                _semantic_progress.ProgressProtocolError) as exc:
            parser.error(f"unreadable semantic progress manifest: {exc}")

    try:
        result = run_owned(
            command, args.cwd, os.environ.copy(), progress_path=args.progress,
            stall_grace_s=args.stall_grace, poll_s=args.poll,
            output_progress=(not args.atomic and args.progress is None
                             and semantic_monitor is None),
            semantic_progress=args.progress is not None,
            expected_progress_labels=expected_progress_labels,
            semantic_progress_monitor=semantic_monitor,
            pending_notifier=notify_pending)
    except SystemExit as exc:
        # A failed private relay requests helper shutdown.  The signal handler
        # retains subreaper ownership until its event-driven cleanup proves a
        # final zero census; publish that proof before propagating the exit.
        cleanup = _SHUTDOWN_CLEANUP
        if args.status is not None:
            write_json(args.status, {
                "protocol": _PROTOCOL,
                "state": "shutdown_complete",
                "reaper_pid": os.getpid(),
                "reaper_starttime": own_starttime,
                "exit_code": int(exc.code) if type(exc.code) is int else 1,
                "census_ok": (cleanup.census_ok
                              if cleanup is not None else False),
                "final_descendants": (_identity_rows(cleanup.survivors)
                                      if cleanup is not None else None),
                "observed": (_identity_rows(cleanup.observed)
                             if cleanup is not None else None),
            }, ensure_ascii=False)
        if event_fd is not None:
            try:
                os.close(event_fd)
            except OSError:
                pass
        raise
    write_json(args.result, asdict(result), ensure_ascii=False)
    if pending_events and args.status is not None:
        write_json(args.status, {
            "protocol": _PROTOCOL,
            "state": "reaper_complete",
            "events": pending_events,
            "result": asdict(result),
        }, ensure_ascii=False)
    elif args.status is not None:
        write_json(args.status, {
            "protocol": _PROTOCOL,
            "state": "complete",
            "reaper_pid": os.getpid(),
            "reaper_starttime": own_starttime,
            "result": asdict(result),
        }, ensure_ascii=False)
    if event_fd is not None:
        try:
            os.close(event_fd)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

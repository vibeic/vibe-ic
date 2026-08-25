#!/usr/bin/env python3
"""Run repo hygiene as a fail-closed local parallel DAG.

ENFORCEMENT: blocking — incomplete ownership, termination-pending work, missing
records, or an undecided gate returns rc 2 and stops the hygiene tier.

Phase A assigns every gate except host-independence to exactly one measured
shard.  Phase B runs host-independence alone after deterministically merging
the exact process attestations produced by A.  This preserves the dependency
(``host`` consumes every Arm-A record) while removing every false serial edge.

No worker record, no verdict: missing/truncated summaries, duplicate or absent
labels, mismatched declarations, and incomplete attestations all return rc 2.
"""
from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import hashlib
import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import _crash_safe_scratch as _scratch
import _owned_process_supervisor as _owned
import _semantic_child_progress as _semantic_progress
import gate_process_attestation as _gate_attestation
from _atomic_artefact import write_json, write_text
from hygiene_shard_plan import load_profile, plan
# THE OTHER HALF OF #1144, AND IT HAD NO CALLER.
# `hygiene_shard_plan` splits the gates and this module has imported it since
# the day it landed; `hygiene_shard_aggregate` — the program that answers "did
# every gate the plan assigned actually get decided, exactly once, by a shard
# that agrees it was sharded" — was authored, tested and merged beside it and
# then reached by nothing. `merge_records` below answers a NEIGHBOURING
# question: it reconciles the shard records against the dispatcher's own
# `--list`. The aggregate answers it against the PLAN, which is the denominator
# that came from outside the records being checked, and that is the distinction
# its header is written about: "deriving the denominator from the records
# themselves would let a run that lost a shard agree with itself."
import hygiene_shard_aggregate as _shard_aggregate
from policy_direction_pin_check import acquire_run_lock, recover_all_journals

HOST_LABEL = "gates are host-independent"
_LEGACY_ROUTED_CORPUS = "published cells carrying a routed DEF"
_LEGACY_ROUTED_EMPTY_LABEL = (
    'corpus "published cells carrying a routed DEF" is EMPTY — '
    'nothing was checked over it')
_WORKER_GATE_STATES = frozenset({
    "PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS", "OUT_OF_SCOPE",
    "OTHER_SHARD",
})
_TERMINAL_GATE_STATES = frozenset(
    {"PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS"})
# This gate already runs three pytest children concurrently and enforces a
# 60-second starvation bound.  Co-scheduling it with either the mutation farms
# or its opposite A/B arm made BOTH copies time out; the exact d6 subprocess
# completes in 43s alone.  It is therefore a resource-isolated A-then-B wave,
# not a logical dependency.  Every ordinary gate and both policy farms remain
# pipelined across A/B.
LOAD_SENSITIVE_LABELS = ("63x8 census freshness",)
DEFAULT_JOBS = 8
DEFAULT_STALL_GRACE_S = 300
DEFAULT_POLL_S = 5
_FRESH_PREFIX = "hygiene-fresh-"
_OWNED_REAPER_PREFIX = "hygiene-owned-reaper-"
_PENDING_REAPERS: Dict[
    Tuple[int, int], Tuple[subprocess.Popen, int | None, Path]
] = {}
_PENDING_REAPERS_LOCK = threading.Lock()
_ACTIVE_REAPER_SCRATCH: set[Path] = set()


def _legacy_empty_without_process(reference: Dict[str, Any],
                                  label: str) -> bool:
    """Recognize the one phase-1 bootstrap row that predates attestations.

    This is deliberately not a generic "empty corpus" escape hatch.  It names
    the existing routed corpus and requires its exact denominator/declaration
    shape, so a candidate cannot add a new synthetic gate and obtain a
    process-attestation exemption.  Phase 2 replaces this row with the trusted
    manifest's non-empty expansion.

    AND IT COVERS A CORPUS THAT WAS *READ*, NEVER ONE THAT WAS NEVER OPENED
    (vibe-ic#1764).  The row it waives says a population was MEASURED and the
    measurement is 0.  Until the dispatcher grew a separate row, a corpus that
    resolved to nothing arrived here wearing this exact label and this exact
    `expansion`, so the waiver answered for it too and `_summary_rc` returned 0
    over a corpus nobody opened -- an enforcement figure covering a measurement
    nobody took.  That reach is bounded: this module's only production caller
    binds the corpus before the set, so the waiver was reachable in that state
    only by running this module directly.  BOTH the label and `expansion ==
    "EXPANDED"` are load-bearing against that: an absent corpus is recorded
    `NO_CORPUS` and fails the shape check even if some future caller hands it
    this label.  Do not widen either one.
    """
    if label != _LEGACY_ROUTED_EMPTY_LABEL:
        return False
    corpora = reference.get("corpora")
    gates = reference.get("gates")
    if not isinstance(corpora, list) or not isinstance(gates, list):
        return False
    matches = [row for row in corpora if isinstance(row, dict)
               and row.get("name") == _LEGACY_ROUTED_CORPUS]
    rows = [row for row in gates if isinstance(row, dict)
            and row.get("label") == label]
    if len(matches) != 1 or len(rows) != 1:
        return False
    corpus, gate = matches[0], rows[0]
    return (corpus == {
                "name": _LEGACY_ROUTED_CORPUS,
                "items": 0,
                "gates": 1,
                "expansion": "EXPANDED",
            }
            and gate.get("state") in {"NOT_CHECKED", "LISTED"}
            and gate.get("corpus") == _LEGACY_ROUTED_CORPUS
            and gate.get("corpus_item") == 0
            and gate.get("corpus_items") == 0
            and gate.get("exempt_until") is None
            and gate.get("exempt_reason") is None
            and gate.get("scope") is None)


def _reap_completed_reaper_records() -> None:
    """Remove only attributed records whose exact reaper identity is gone."""
    tmp_root = Path(tempfile.gettempdir())
    for scratch in tmp_root.glob(_OWNED_REAPER_PREFIX + "*"):
        with _PENDING_REAPERS_LOCK:
            if scratch in _ACTIVE_REAPER_SCRATCH:
                continue
        status = scratch / "reaper-status.json"
        try:
            doc = _load_json(status)
            if doc.get("state") == "reaper_complete":
                events = doc.get("events") or []
                last = events[-1]
                pid = int(last["reaper_pid"])
                starttime = int(last["reaper_starttime"])
            elif doc.get("state") == "complete":
                pid = int(doc["reaper_pid"])
                starttime = int(doc["reaper_starttime"])
            else:
                continue
        except (OSError, ValueError, TypeError, KeyError, IndexError,
                json.JSONDecodeError):
            continue
        try:
            live = _owned._read_proc_identity(pid)
        except (OSError, ValueError, IndexError):
            continue
        if live is None or live[1] != starttime:
            shutil.rmtree(scratch, ignore_errors=True)


def _retain_pending_reaper(helper: subprocess.Popen, helper_pidfd: int | None,
                           scratch: Path, starttime: int) -> None:
    """Keep a strong, inspectable owner until its SIGKILL-pending tree exits."""
    key = (helper.pid, starttime)
    with _PENDING_REAPERS_LOCK:
        _PENDING_REAPERS[key] = (helper, helper_pidfd, scratch)

    def finish() -> None:
        try:
            helper.wait()
        finally:
            if helper_pidfd is not None:
                try:
                    os.close(helper_pidfd)
                except OSError:
                    pass
            with _PENDING_REAPERS_LOCK:
                _PENDING_REAPERS.pop(key, None)
                _ACTIVE_REAPER_SCRATCH.discard(scratch)
            # Keep the tiny status/result directory as termination evidence.
            # A later invocation may reap completed records; deleting it here
            # would race the caller that is reporting the rc=2 sidecar path.

    threading.Thread(
        target=finish, name=f"owned-reaper-{helper.pid}", daemon=True).start()


def _unregister_fresh(scratch: Path) -> None:
    wt = scratch / "wt"
    if not wt.exists():
        return
    subprocess.run(["git", "-C", str(wt), "worktree", "unlock", str(wt)],
                   capture_output=True, text=True)
    subprocess.run(["git", "-C", str(wt), "worktree", "remove", "--force",
                    str(wt)], capture_output=True, text=True)


def _release_fresh(res: Any, repo: Path) -> None:
    _unregister_fresh(res.path)
    res.release()
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"],
                   capture_output=True, text=True)


def _strict_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_loads(payload: str) -> Any:
    return json.loads(payload, object_pairs_hook=_strict_object,
                      parse_constant=_reject_json_constant)


def _load_json(path: Path) -> Dict[str, Any]:
    doc = _strict_loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("top-level JSON is not an object")
    return doc


def _exact_identity_rows(value: object) -> bool:
    if not isinstance(value, list):
        return False
    identities = []
    for row in value:
        if (not isinstance(row, dict)
                or set(row) != {"pid", "starttime"}
                or type(row.get("pid")) is not int or row["pid"] <= 0
                or type(row.get("starttime")) is not int
                or row["starttime"] < 0):
            return False
        identities.append((row["pid"], row["starttime"]))
    return len(identities) == len(set(identities))


def _owned_final_zero(doc: object) -> bool:
    """Strict trusted-helper terminal record usable as an atomic proof."""
    fields = {
        "protocol", "rc", "body", "problem", "outcome", "launched",
        "census_ok", "final_descendants", "observed", "capability_error",
    }
    return (isinstance(doc, dict) and set(doc) == fields
            and type(doc.get("protocol")) is int and doc["protocol"] == 1
            and type(doc.get("rc")) is int
            and isinstance(doc.get("body"), str)
            and (doc.get("problem") is None
                 or isinstance(doc.get("problem"), str))
            and doc.get("outcome") in {
                "natural", "stalled", "ceiling", "aborted"}
            and doc.get("launched") is True
            and doc.get("census_ok") is True
            and doc.get("final_descendants") == []
            and _exact_identity_rows(doc.get("observed"))
            and isinstance(doc.get("capability_error"), str))


def _shutdown_final_zero(doc: object, *, helper_pid: int,
                         helper_starttime: int | None,
                         helper_rc: int | None) -> bool:
    fields = {
        "protocol", "state", "reaper_pid", "reaper_starttime", "exit_code",
        "census_ok", "final_descendants", "observed",
    }
    return (isinstance(doc, dict) and set(doc) == fields
            and type(doc.get("protocol")) is int and doc["protocol"] == 1
            and doc.get("state") == "shutdown_complete"
            and type(doc.get("reaper_pid")) is int
            and doc["reaper_pid"] == helper_pid
            and type(doc.get("reaper_starttime")) is int
            and doc["reaper_starttime"] >= 0
            and (helper_starttime is None
                 or doc["reaper_starttime"] == helper_starttime)
            and type(doc.get("exit_code")) is int
            and doc["exit_code"] == 128 + signal.SIGTERM
            and helper_rc == doc["exit_code"]
            and doc.get("census_ok") is True
            and doc.get("final_descendants") == []
            and _exact_identity_rows(doc.get("observed")))


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = _strict_loads(line)
            if not isinstance(row, dict) or row.get("complete") is not True:
                raise ValueError(f"line {lineno} is not a complete attestation")
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, "".join(json.dumps(row, ensure_ascii=True,
                                         sort_keys=True) + "\n" for row in rows))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _run(argv: List[str], cwd: Path, env: Dict[str, str], *,
         progress_path: Path | None = None,
         expected_progress_labels: Sequence[str] | None = None,
         stall_grace_s: float = DEFAULT_STALL_GRACE_S,
         atomic: bool = False,
         owned_result_sink: Dict[str, Any] | None = None,
         semantic_progress_scope: str | None = None,
         semantic_progress_units: Sequence[str] | None = None,
         domain_progress_callback: Callable[[str, int, int], None] | None = None):
    """Run until natural completion while supervising FORWARD PROGRESS.

    There is deliberately no whole-run timeout. Existing callers retain their
    explicit output/attestation/atomic policy. Supplying ``semantic_progress_*``
    selects the stricter issue-1710 mode: only exact parent-manifest checkpoints
    renew the lease; stdout, CPU and generic log activity cannot. Validated
    checkpoints are relayed while the direct child is still running.
    """
    # Subreaper state and waitpid(-1) are process-global.  `_run` is called by
    # several dispatcher threads, so each job gets a dedicated one-job helper.
    # The private pipe is the semantic state channel: the outer thread waits on
    # either a helper-exit pidfd event or an explicit termination-pending event,
    # never on an estimated whole-job deadline.
    semantic_requested = (semantic_progress_scope is not None
                          or semantic_progress_units is not None)
    if (semantic_progress_scope is None) != (semantic_progress_units is None):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress scope "
                "and finite unit manifest must be supplied together")
    if domain_progress_callback is not None and not semantic_requested:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: domain progress callback "
                "has no semantic child channel")
    if semantic_requested and (progress_path is not None or atomic):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress is "
                "exclusive with attestation/log or atomic renewal")
    if not hasattr(os, "pidfd_open") or not hasattr(select, "poll"):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: dispatcher pidfd "
                "exit events are unavailable")
    if atomic and progress_path is not None:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: atomic completion-only "
                "mode cannot accept a progress channel")
    if (progress_path is None) != (expected_progress_labels is None):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress path "
                "and assigned-label manifest must be supplied together")
    try:
        probe_pidfd = os.pidfd_open(os.getpid())
    except OSError as exc:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: dispatcher cannot open "
                f"pidfd exit events: {exc}")
    else:
        os.close(probe_pidfd)

    _reap_completed_reaper_records()
    scratch = Path(tempfile.mkdtemp(prefix=_OWNED_REAPER_PREFIX))
    with _PENDING_REAPERS_LOCK:
        _ACTIVE_REAPER_SCRATCH.add(scratch)
    result_path = scratch / "owned-result.json"
    status_path = scratch / "reaper-status.json"
    expected_progress_path = scratch / "expected-progress-labels.json"
    diagnostic_path = scratch / "helper.log"
    event_read = -1
    event_write = -1
    helper: subprocess.Popen | None = None
    helper_pidfd: int | None = None
    diagnostic_fh = None
    retained = False
    try:
        semantic_plan = None
        relay = None
        helper_env = env
        if semantic_requested:
            try:
                semantic_plan = _semantic_progress.prepare_parent(
                    scratch, str(semantic_progress_scope),
                    list(semantic_progress_units or ()), env)
                relay = _semantic_progress.RelayValidator(
                    semantic_plan.scope, len(semantic_plan.units),
                    domain_progress_callback)
                helper_env = semantic_plan.env
            except (OSError, ValueError,
                    _semantic_progress.ProgressProtocolError) as exc:
                return (2, "", "OWNED_SUPERVISOR_NORECORD: cannot prepare "
                        f"semantic child progress: {exc}")
        event_read, event_write = os.pipe()
        os.set_blocking(event_read, False)
        diagnostic_fh = diagnostic_path.open("wb")
        helper_argv = [
            sys.executable, str(Path(_owned.__file__).resolve()),
            "--result", str(result_path),
            "--status", str(status_path),
            "--event-fd", str(event_write),
            "--cwd", str(cwd.resolve()),
            "--stall-grace", str(stall_grace_s),
            "--poll", str(DEFAULT_POLL_S),
        ]
        if progress_path is not None:
            write_json(expected_progress_path, {
                "schema": 1,
                "labels": list(expected_progress_labels or ()),
            }, ensure_ascii=False)
            expected_progress_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            helper_argv.extend([
                "--progress", str(progress_path.resolve()),
                "--expected-progress-labels",
                str(expected_progress_path.resolve()),
            ])
        elif atomic:
            helper_argv.append("--atomic")
        if semantic_plan is not None:
            helper_argv.extend([
                "--semantic-progress-manifest",
                str(semantic_plan.manifest_path),
            ])
        helper_argv.extend(["--", *argv])
        helper = subprocess.Popen(
            helper_argv, env=helper_env, stdout=diagnostic_fh,
            stderr=subprocess.STDOUT, pass_fds=(event_write,),
            start_new_session=True)
        diagnostic_fh.close()
        os.close(event_write)
        event_write = -1
        try:
            helper_pidfd = os.pidfd_open(helper.pid)
        except OSError as exc:
            helper.send_signal(signal.SIGTERM)
            helper_diagnostic = diagnostic_path.read_text(
                encoding="utf-8", errors="replace")
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            starttime = observed[1] if observed is not None else -1
            _retain_pending_reaper(helper, None, scratch, starttime)
            retained = True
            helper = None
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: cannot own helper pidfd: "
                    f"{exc}")

        poller = select.poll()
        poller.register(event_read,
                        select.POLLIN | select.POLLHUP | select.POLLERR)
        poller.register(helper_pidfd,
                        select.POLLIN | select.POLLHUP | select.POLLERR)
        event_buffer = b""
        pending: Dict[str, Any] | None = None
        helper_exited = False
        channel_failed = False
        channel_failure = ""

        def drain_pending_events() -> None:
            nonlocal event_buffer, pending, channel_failed, channel_failure
            while True:
                try:
                    chunk = os.read(event_read, 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                event_buffer += chunk
                while b"\n" in event_buffer:
                    raw, event_buffer = event_buffer.split(b"\n", 1)
                    if not raw:
                        channel_failed = True
                        channel_failure = "empty private supervisor event"
                        continue
                    try:
                        candidate = _semantic_progress.strict_loads(
                            raw.decode("ascii"))
                    except (UnicodeDecodeError, ValueError,
                            json.JSONDecodeError):
                        candidate = {"state": "invalid"}
                    if (isinstance(candidate, dict)
                            and candidate.get("state")
                            == "termination_pending"):
                        pending = candidate
                    elif (isinstance(candidate, dict)
                          and candidate.get("state") == "domain_progress"):
                        if relay is None:
                            channel_failed = True
                            channel_failure = "unexpected domain-progress relay"
                        else:
                            relay.accept(candidate)
                            if relay.error:
                                channel_failed = True
                                channel_failure = relay.error
                    else:
                        channel_failed = True
                        channel_failure = "invalid private supervisor event"

        while not pending and not helper_exited:
            # Both watched objects are kernel events.  There is deliberately no
            # wall-clock estimate for how long a healthy helper may run.
            events = poller.poll()
            pipe_events = [event for fd, event in events
                           if fd == event_read]
            if pipe_events:
                drain_pending_events()
                if event_buffer and any(
                        event & (select.POLLHUP | select.POLLERR)
                        for event in pipe_events):
                    channel_failed = True
                    channel_failure = "truncated private supervisor event"
                if pending is None and any(
                        event & (select.POLLHUP | select.POLLERR)
                        for event in pipe_events):
                    # The sidecar is written before the pipe event.  Recover a
                    # transition if the helper closed between those operations.
                    try:
                        durable = _load_json(status_path)
                    except (OSError, ValueError, json.JSONDecodeError):
                        durable = {}
                    events_doc = durable.get("events")
                    if isinstance(events_doc, list):
                        for candidate in reversed(events_doc):
                            if (isinstance(candidate, dict)
                                    and candidate.get("state")
                                    == "termination_pending"):
                                pending = candidate
                                break
                    if pending is None:
                        if (result_path.is_file()
                                or durable.get("state") == "complete"):
                            # Normal helper shutdown writes its result/status
                            # before closing the channel.  Stop watching the
                            # now-permanent HUP and await its pidfd exit event.
                            poller.unregister(event_read)
                        else:
                            channel_failed = True
            if pending is not None:
                break
            if channel_failed:
                break
            if any(fd == helper_pidfd for fd, _event in events):
                # The helper can publish a pending transition immediately before
                # exit.  Drain the private channel before classifying the pidfd
                # event so a fast reaper completion cannot hide that rc=2 state.
                drain_pending_events()
                helper_exited = pending is None

        if helper_exited and event_buffer and not channel_failed:
            channel_failed = True
            channel_failure = "truncated private supervisor event"

        if channel_failed:
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            expected_starttime = observed[1] if observed is not None else None
            if helper.poll() is None:
                try:
                    helper.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass

            # A semantic callback is part of an enclosing atomic test lease.
            # On relay failure retain ownership here, drain the helper-only
            # pipe, and wait only on pidfd exit until the helper has published
            # a trusted final-zero cleanup record. There is no elapsed bound.
            pipe_registered = True
            while helper.poll() is None:
                for fd, event in poller.poll():
                    if fd == event_read and pipe_registered:
                        while True:
                            try:
                                chunk = os.read(event_read, 65536)
                            except BlockingIOError:
                                break
                            if not chunk:
                                break
                        if event & (select.POLLHUP | select.POLLERR):
                            poller.unregister(event_read)
                            pipe_registered = False
                    if fd == helper_pidfd:
                        helper.wait()
                        break
            helper.wait()
            helper_diagnostic = diagnostic_path.read_text(
                encoding="utf-8", errors="replace")

            cleanup_proof = ""
            cleanup_verified = False
            try:
                status_doc = _semantic_progress.strict_loads(
                    status_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError,
                    json.JSONDecodeError) as exc:
                status_doc = None
                cleanup_proof = f"unreadable final-zero status: {exc}"
            if isinstance(status_doc, dict):
                if _shutdown_final_zero(
                        status_doc, helper_pid=helper.pid,
                        helper_starttime=expected_starttime,
                        helper_rc=helper.returncode):
                    cleanup_proof = "shutdown_complete/final_descendants=[]"
                    cleanup_verified = True
                else:
                    cleanup_proof = "final-zero status differs"
            if not cleanup_verified and result_path.is_file():
                try:
                    result_doc = _semantic_progress.strict_loads(
                        result_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError,
                        json.JSONDecodeError) as exc:
                    cleanup_proof = (
                        f"unreadable natural final-zero result: {exc}")
                else:
                    if helper.returncode == 0 and _owned_final_zero(result_doc):
                        cleanup_proof = "natural/final_descendants=[]"
                        cleanup_verified = True
            if not cleanup_verified:
                cleanup_proof = "UNPROVED: " + (cleanup_proof or "missing")
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: private supervisor channel "
                    "failed before a terminal record"
                    + (f": {channel_failure}" if channel_failure else "")
                    + f"; atomic cleanup={cleanup_proof}")
        helper_diagnostic = diagnostic_path.read_text(
            encoding="utf-8", errors="replace")
        if pending is not None:
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            expected_start = pending.get("reaper_starttime")
            violations: List[str] = []
            try:
                status_doc = _load_json(status_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                status_doc = {}
                violations.append(f"unreadable durable pending status: {exc}")
            if status_doc.get("state") not in (
                    "termination_pending", "reaper_complete"):
                violations.append("durable sidecar has no pending state")
            if pending.get("protocol") != 1:
                violations.append("unknown pending protocol")
            if pending.get("reaper_pid") != helper.pid:
                violations.append("pending record names a different reaper PID")
            if not isinstance(expected_start, int) or expected_start < 0:
                violations.append("pending record has no reaper starttime")
            if (observed is not None and isinstance(expected_start, int)
                    and observed[1] != expected_start):
                violations.append("reaper PID/starttime identity changed")
            if not isinstance(pending.get("reason"), str):
                violations.append("pending record has no reason")
            if not isinstance(pending.get("pending_descendants"), list):
                violations.append("pending record has no descendant census")
            if pending.get("status_error"):
                violations.append(
                    "durable pending sidecar failed: "
                    f"{pending['status_error']}")
            if violations:
                if helper.poll() is None:
                    # A pending transition proves cleanup is already active.
                    # Retain that unique subreaper; do not interrupt it with a
                    # nested signal-handler cleanup merely because one of its
                    # observability records was malformed.
                    retain_start = (
                        observed[1] if observed is not None else
                        expected_start if isinstance(expected_start, int)
                        else -1)
                    _retain_pending_reaper(
                        helper, helper_pidfd, scratch, int(retain_start))
                    retained = True
                    helper = None
                    helper_pidfd = None
                return (2, helper_diagnostic,
                        "OWNED_SUPERVISOR_NORECORD: invalid pending state: "
                        + "; ".join(violations))

            # Transfer the live Popen/pidfd objects to a background waiter.  The
            # helper is a session-isolated subreaper and continues to own the
            # SIGKILL-pending tree; the dispatcher can now fail closed with rc2.
            _retain_pending_reaper(
                helper, helper_pidfd, scratch, int(expected_start))
            retained = True
            helper = None
            helper_pidfd = None
            reason = str(pending["reason"])
            descendants = pending.get("pending_descendants")
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_TERMINATION_PENDING: "
                    f"reason={reason}; reaper={pending['reaper_pid']}/"
                    f"{expected_start}; descendants={descendants!r}; "
                    f"status={status_path}")

        helper.wait()
        if helper.returncode != 0 or not result_path.is_file():
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: helper did not publish its "
                    f"terminal census (helper rc={helper.returncode})")
        try:
            record = _load_json(result_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return (2, helper_diagnostic,
                    f"OWNED_SUPERVISOR_NORECORD: invalid result: {exc}")
    except BaseException:
        if helper is not None and helper.poll() is None:
            # The helper is session-isolated, so explicitly request its cleanup
            # when this dispatcher thread is cancelled.
            helper.send_signal(signal.SIGTERM)
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            starttime = observed[1] if observed is not None else -1
            _retain_pending_reaper(
                helper, helper_pidfd, scratch, starttime)
            retained = True
            helper = None
            helper_pidfd = None
        raise
    finally:
        if event_read >= 0:
            try:
                os.close(event_read)
            except OSError:
                pass
        if event_write >= 0:
            try:
                os.close(event_write)
            except OSError:
                pass
        if diagnostic_fh is not None and not diagnostic_fh.closed:
            diagnostic_fh.close()
        if helper_pidfd is not None:
            try:
                os.close(helper_pidfd)
            except OSError:
                pass
        if not retained:
            shutil.rmtree(scratch, ignore_errors=True)
            with _PENDING_REAPERS_LOCK:
                _ACTIVE_REAPER_SCRATCH.discard(scratch)

    body = str(record.get("body") or "")
    if helper_diagnostic:
        body += helper_diagnostic
    violations: List[str] = []
    if record.get("protocol") != 1:
        violations.append("unknown ownership protocol")
    if not isinstance(record.get("rc"), int):
        violations.append("missing integer child rc")
    if not isinstance(record.get("launched"), bool):
        violations.append("missing launch state")
    if not isinstance(record.get("census_ok"), bool):
        violations.append("missing census integrity state")
    if not isinstance(record.get("outcome"), str):
        violations.append("missing supervisor outcome")
    if not isinstance(record.get("observed"), list):
        violations.append("missing observed-identity census")
    final = record.get("final_descendants")
    if final != []:
        violations.append(f"final descendant census is not zero: {final!r}")
    if record.get("launched") and record.get("census_ok") is not True:
        violations.append("PID/starttime census was not continuously provable")
    recorded_problem = record.get("problem")
    if recorded_problem is not None and not isinstance(recorded_problem, str):
        violations.append("malformed problem record")
        recorded_problem = None
    if (isinstance(recorded_problem, str)
            and "SEMANTIC_PROGRESS_NORECORD:" in recorded_problem):
        violations.append(
            "semantic child progress did not reach its exact terminal FSM")
    if relay is not None and (
            relay.error or relay.completed != relay.total):
        violations.append(
            "incomplete domain-progress relay "
            f"({relay.completed}/{relay.total})"
            + (f": {relay.error}" if relay.error else ""))
    if (record.get("launched") is False
            and (record.get("rc") == 0 or not recorded_problem)):
        violations.append("helper reported success without launching the job")
    if violations:
        violations.insert(0, "OWNED_SUPERVISOR_REFUSED")
    problem = "; ".join(
        [item for item in [recorded_problem, *violations] if item]) or None
    rc = (2 if violations else
          record.get("rc") if isinstance(record.get("rc"), int) else 2)
    if owned_result_sink is not None:
        owned_result_sink.clear()
        owned_result_sink.update(record)
    return rc, body, problem


def _validate_declarations(reference: Dict[str, Any], doc: Dict[str, Any],
                           where: str) -> List[str]:
    problems: List[str] = []
    reference_gates = reference.get("gates") or []
    worker_gates = doc.get("gates") or []
    want = [str(g.get("label")) for g in reference_gates]
    got = [str(g.get("label")) for g in worker_gates]
    if got != want:
        problems.append(f"{where}: declaration order/set differs from --list")
    for index, (declared, observed) in enumerate(
            zip(reference_gates, worker_gates)):
        immutable = lambda row: {
            key: value for key, value in row.items()
            if key not in {"state", "seconds"}
        }
        if immutable(observed) != immutable(declared):
            problems.append(
                f"{where}: gate {index} immutable declaration differs from "
                "--list")
    for key in ("corpora", "corpus_inputs", "undisclosed_loops"):
        if doc.get(key) != reference.get(key):
            problems.append(f"{where}: {key} differs from --list declaration")
    if doc.get("listed_only"):
        problems.append(f"{where}: worker reported listed_only instead of running")
    if doc.get("shard") is None:
        problems.append(f"{where}: worker ignored its shard assignment")
    for index, gate in enumerate(doc.get("gates") or []):
        state = gate.get("state")
        if state not in _WORKER_GATE_STATES:
            problems.append(
                f"{where}: gate {index} has non-terminal/unknown worker "
                f"state {state!r}")
        if state == "OUT_OF_SCOPE":
            scope = gate.get("scope")
            changed = os.environ.get("GATEKEEPER_CHANGED_PATHS")
            if not isinstance(scope, str) or not scope.strip():
                problems.append(
                    f"{where}: gate {index} is OUT_OF_SCOPE without a scope")
            elif not changed or not Path(changed).is_file():
                problems.append(
                    f"{where}: gate {index} is OUT_OF_SCOPE without a "
                    "measurable changed-path set")
            else:
                try:
                    paths = [line for line in Path(changed).read_text(
                        encoding="utf-8").splitlines() if line]
                except OSError as exc:
                    problems.append(
                        f"{where}: changed-path set is unreadable: {exc}")
                    paths = []
                prefixes = scope.split()
                if not paths:
                    problems.append(
                        f"{where}: gate {index} is OUT_OF_SCOPE against an "
                        "empty changed-path set")
                elif any(path.startswith(prefix) for path in paths
                         for prefix in prefixes):
                    problems.append(
                        f"{where}: gate {index} is OUT_OF_SCOPE although a "
                        "changed path intersects its scope")
    return problems


def _attestation_problem(row: object) -> str | None:
    """Validate the complete process record even for direct API callers."""
    try:
        _gate_attestation.validate_record(row)
    except (TypeError, ValueError, KeyError) as exc:
        return str(exc)
    return None


def merge_records(reference: Dict[str, Any], docs: List[Tuple[Path, Dict[str, Any]]],
                  attestations: List[Dict[str, Any]], elapsed: int,
                  problems: List[str], worker_docs: int | None = None
                  ) -> Dict[str, Any]:
    """Build the dispatcher's full summary schema from exactly-once shards."""
    labels = [str(g["label"]) for g in reference.get("gates") or []]
    chosen: Dict[str, List[Dict[str, Any]]] = {label: [] for label in labels}
    for path, doc in docs:
        problems.extend(_validate_declarations(reference, doc, str(path)))
        for gate in doc.get("gates") or []:
            if gate.get("state") != "OTHER_SHARD":
                chosen.setdefault(str(gate.get("label")), []).append(gate)

    gates: List[Dict[str, Any]] = []
    for label in labels:
        rows = chosen.get(label, [])
        if len(rows) != 1:
            problems.append(
                f"{label!r}: expected one owning shard record, got {len(rows)}")
            # Preserve the declared denominator even in the refusal artefact.
            template = next(g for g in reference["gates"]
                            if str(g["label"]) == label)
            row = dict(template)
            row["state"] = "NOT_CHECKED"
            row["seconds"] = 0
            gates.append(row)
        else:
            gates.append(rows[0])
    extras = sorted(set(chosen) - set(labels))
    if extras:
        problems.append("unplanned labels ran: " + ", ".join(extras[:6]))

    by_label: Dict[str, List[Dict[str, Any]]] = {}
    for index, row in enumerate(attestations):
        invalid = _attestation_problem(row)
        if invalid:
            problems.append(f"process attestation {index}: {invalid}")
            continue
        by_label.setdefault(str(row.get("label")), []).append(row)
    for label, gate in zip(labels, gates):
        legacy_no_process = _legacy_empty_without_process(reference, label)
        should_have = (gate.get("state") in _TERMINAL_GATE_STATES
                       and not legacy_no_process)
        count = len(by_label.get(label, []))
        if should_have and count != 1:
            problems.append(
                f"{label!r}: expected one process attestation, got {count}")
        if not should_have and count != 0:
            problems.append(
                f"{label!r}: skipped/nonterminal gate has {count} process "
                "attestation(s), expected zero")
        if should_have and count == 1:
            attestation = by_label[label][0]
            state = gate.get("state")
            rc = attestation["returncode"]
            recorded_state = attestation.get("state")
            if recorded_state not in ("", state):
                problems.append(
                    f"{label!r}: attestation state {recorded_state!r} "
                    f"contradicts summary state {state!r}")
            if ((state == "PASS" and rc != 0)
                    or (state == "NOT_CHECKED" and rc != 2)):
                problems.append(
                    f"{label!r}: summary state {state} contradicts process "
                    f"returncode {rc}")
            findings = attestation["finding_identities"]
            verdict = attestation["verdict_line"]
            verdict_is_failure = _gate_attestation._is_finding_line(verdict)
            if state == "PASS" and (findings or verdict_is_failure):
                problems.append(
                    f"{label!r}: PASS carries failure semantics in its "
                    "process attestation")
            if (state == "FAIL" and rc == 0 and not findings
                    and not verdict_is_failure):
                problems.append(
                    f"{label!r}: FAIL has neither a nonzero return code nor "
                    "a failure verdict/finding identity")
    att_extra = sorted(set(by_label) - set(labels))
    if att_extra:
        problems.append("unplanned process attestations: "
                        + ", ".join(att_extra[:6]))

    count = lambda state: sum(g.get("state") == state for g in gates)
    wiring = sorted({str(item) for _, doc in docs
                     for item in (doc.get("wiring_errors") or [])})
    today = {str(doc.get("today")) for _, doc in docs}
    if len(today) != 1:
        problems.append("shards disagree on the run date")
    if worker_docs is None:
        # Compatibility for direct callers: count documents that do not own
        # the dependent host-comparison gate.  The main DAG passes the measured
        # Arm-A document count explicitly, including when the host phase never
        # launches; `len(docs) - 1` reported seven workers when eight worker
        # records existed but the host record did not.
        worker_docs = sum(
            not any(g.get("label") == HOST_LABEL
                    and g.get("state") != "OTHER_SHARD"
                    for g in (doc.get("gates") or []))
            for _, doc in docs)
    ran = sum(count(s) for s in _TERMINAL_GATE_STATES)
    out_of_scope = count("OUT_OF_SCOPE")
    if ran + out_of_scope != len(gates) or count("OTHER_SHARD"):
        problems.append(
            "merged terminal accounting is incomplete: "
            f"ran={ran}, declared={len(gates)}, "
            f"out_of_scope={out_of_scope}, "
            f"other_shard={count('OTHER_SHARD')}")
    return {
        "listed_only": False,
        "declared": len(gates),
        "ran": ran,
        "decided": count("PASS") + count("FAIL"),
        "passed": count("PASS"),
        "failed": count("FAIL"),
        "not_checked": count("NOT_CHECKED"),
        "not_checked_unexempted": [str(g["label"]) for g in gates
                                    if g.get("state") == "NOT_CHECKED"
                                    and not g.get("exempt_until")],
        "exemptions_expired": [str(g["label"]) for g in gates
                               if g.get("exemption_expired")],
        "wiring_errors": wiring + [f"parallel coverage: {p}" for p in problems],
        "today": next(iter(today), str(reference.get("today") or "")),
        "wrote_corpus": count("WROTE_CORPUS"),
        "deferred": count("LISTED"),
        "other_shard": count("OTHER_SHARD"),
        "out_of_scope": out_of_scope,
        "shard": None,
        "corpora": reference.get("corpora") or [],
        "corpus_inputs": reference.get("corpus_inputs") or {
            "benchmark_data_sha": None,
        },
        "undisclosed_loops": reference.get("undisclosed_loops") or [],
        "seconds": elapsed,
        "gates": gates,
        "process_attestations": attestations,
        "parallel": {"workers": worker_docs,
                     "phases": ["pipelined-a-b", "load-sensitive-wave",
                                "host-attestation-compare"],
                     "complete": not problems},
    }


def _summary_rc(doc: Dict[str, Any]) -> int:
    if doc.get("wiring_errors") or not int(doc.get("declared") or 0):
        return 2
    if doc.get("failed") or doc.get("wrote_corpus") \
            or doc.get("exemptions_expired"):
        return 1
    unexempted = doc.get("not_checked_unexempted")
    if unexempted:
        # Preserve the truthful legacy list in the record (and therefore HDF's
        # strict schema) while keeping phase 1's already-shipped closing rc.
        # This is not a generic unexempted-NOT_CHECKED waiver: the list must be
        # exactly the one historical routed EMPTY identity and the complete
        # corpus/gate shape must prove it is the no-process bootstrap row.
        #
        # THIS IS THE ONE PLACE A POPULATION REFUSAL CAN BECOME A PASS, so it
        # is where vibe-ic#1764's collapse was worth closing. An absent corpus
        # reached this waiver wearing the EMPTY row's label and the EMPTY row's
        # expansion, so the waiver answered for it too. Re-measured 2026-08-22
        # on `81cd5321b` (the commit before the fix) and on `a4caccefe` (this
        # tree), real producer through the real `_gate_dispatch.sh`:
        #
        #     before   ABSENT -> _summary_rc 0   read-empty -> 0   IDENTICAL
        #     after    ABSENT -> _summary_rc 2   read-empty -> 0
        #
        # LATENT, NOT LIVE, and the difference is worth stating rather than
        # letting the comment imply the stronger thing. This module's only
        # production caller is `gatekeeper_review.repo_hygiene_gate`, which
        # binds the corpus BEFORE the set and returns rc 2 with a named remedy
        # if it cannot (pinned by `test_every_unresolvable_corpus_is_an_ERROR_
        # and_the_set_never_runs`), so an absent corpus never arrived here on
        # that path. `gate_dispatch_finish` -- the closing rc of the shipped
        # `repo_hygiene_gates.sh`, which is what `lane_hygiene` runs -- was
        # measured at 2 in BOTH states on BOTH commits, so no lane's exit code
        # moved. What the fix buys is that this waiver no longer DEPENDS on
        # that one binding being correct, which is the only thing that made it
        # safe.
        #
        # `_legacy_empty_without_process` refuses an absent corpus on
        # `expansion`, and `test_an_absent_corpus_does_not_close_the_hygiene_
        # dag_green` drives both states end to end so the pair cannot re-merge.
        if not (unexempted == [_LEGACY_ROUTED_EMPTY_LABEL]
                and _legacy_empty_without_process(
                    doc, _LEGACY_ROUTED_EMPTY_LABEL)):
            return 2
    if not int(doc.get("decided") or 0):
        return 2
    return 0


def _completion_message(doc: Dict[str, Any], elapsed: int) -> str:
    prefix = "PASS" if _summary_rc(doc) == 0 else "FAIL"
    return (f"[{prefix}] parallel hygiene DAG completed {doc['decided']} of "
            f"{doc['declared']} gate verdict(s) in {elapsed}s; "
            f"failed={doc['failed']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary-json", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--stall-grace", type=int, default=DEFAULT_STALL_GRACE_S,
                    help="seconds with neither output nor a completed gate "
                         "record before a shard is classified STALLED; this "
                         "is not a whole-run runtime limit")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[4]
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    profile_path = Path(__file__).resolve().parent / "hygiene_gate_profile.json"
    if args.jobs < 1 or args.stall_grace < 1:
        print("[ERROR] jobs and stall-grace must be positive", file=sys.stderr)
        return 2
    started = time.monotonic()
    problems: List[str] = []

    with tempfile.TemporaryDirectory(prefix="hygiene-parallel-") as td:
        tmp = Path(td)
        list_json = tmp / "list.json"
        list_env = os.environ.copy()
        list_env.pop("GATE_DISPATCH_ATTESTATION_FILE", None)
        list_rc, list_out, list_err = _run(
            ["bash", str(script), "--list", "--summary-json", str(list_json)],
            root, list_env, stall_grace_s=args.stall_grace)
        if list_err or list_rc != 0 or not list_json.is_file():
            print("[ERROR] could not establish the hygiene denominator: "
                  + (list_err or list_out[-300:]), file=sys.stderr)
            return 2
        try:
            reference = _load_json(list_json)
        except (OSError, ValueError) as exc:
            print(f"[ERROR] unreadable denominator record: {exc}", file=sys.stderr)
            return 2
        labels = [str(g.get("label")) for g in reference.get("gates") or []]
        if labels.count(HOST_LABEL) != 1:
            print(f"[ERROR] expected exactly one {HOST_LABEL!r} declaration, "
                  f"got {labels.count(HOST_LABEL)}", file=sys.stderr)
            return 2
        phase_a_labels = [label for label in labels if label != HOST_LABEL]
        sensitive = [label for label in LOAD_SENSITIVE_LABELS
                     if label in phase_a_labels]
        primary_labels = [label for label in phase_a_labels
                          if label not in set(sensitive)]
        try:
            profile = load_profile(profile_path)
            jobs = min(args.jobs, len(primary_labels))
            buckets, unprofiled = plan(primary_labels, profile, jobs)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] cannot construct measured shard plan: {exc}",
                  file=sys.stderr)
            return 2
        if unprofiled:
            print("[INFO] unprofiled gates assigned with conservative cost: "
                  + ", ".join(unprofiled[:8]))

        # One lock protects the broad orphan-journal recovery for BOTH policy
        # arms.  The two policy parents then use keyed recovery and may overlap;
        # without this cohort the second parent can "repair" the first one's
        # live mutant underneath pytest.
        try:
            acquire_run_lock()
            recovery_rc, recovery_lines = recover_all_journals()
        except OSError as exc:
            print(f"[ERROR] cannot lock/recover policy mutation journals: {exc}",
                  file=sys.stderr)
            return 2
        for line in recovery_lines:
            print(line, file=sys.stderr if recovery_rc else sys.stdout)
        if recovery_rc:
            print("[ERROR] an abandoned policy mutation could not be recovered",
                  file=sys.stderr)
            return 2

        fresh_res, _ = _scratch.reserve(
            _FRESH_PREFIX, remover=_unregister_fresh)
        fresh_root = fresh_res.path / "wt"
        add = subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "-q", "--detach",
             str(fresh_root), "HEAD"], capture_output=True, text=True,
        )
        if add.returncode != 0:
            fresh_res.release()
            print("[ERROR] could not create the pipelined fresh tree: "
                  + (add.stderr or add.stdout).strip()[:240], file=sys.stderr)
            return 2
        cleanup = lambda: _release_fresh(fresh_res, root)
        atexit.register(cleanup)

        total_shards = jobs + (1 if sensitive else 0) + 1
        requested_progress = os.environ.get("GATE_DISPATCH_ATTESTATION_FILE")
        if requested_progress:
            progress_path = Path(requested_progress).resolve()
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                progress_path.unlink()
            except FileNotFoundError:
                pass
        else:
            progress_path = None

        workers = []
        reference_by_label = {
            str(g.get("label")): g for g in (reference.get("gates") or [])}
        changed_path_file = os.environ.get("GATEKEEPER_CHANGED_PATHS")
        try:
            changed_paths = ([line for line in Path(changed_path_file).read_text(
                encoding="utf-8").splitlines() if line]
                if changed_path_file and Path(changed_path_file).is_file()
                and Path(changed_path_file).stat().st_size > 0 else None)
        except OSError:
            changed_paths = None

        def expected_executed_labels(bucket_labels):
            expected = []
            for label in bucket_labels:
                if _legacy_empty_without_process(reference, label):
                    continue
                scope = reference_by_label.get(label, {}).get("scope")
                if (not isinstance(scope, str) or not scope.strip()
                        or changed_paths is None
                        or any(path.startswith(prefix)
                               for path in changed_paths
                               for prefix in scope.split())):
                    expected.append(label)
            return expected

        for i, bucket in enumerate(buckets):
            labels_path = tmp / f"labels-{i}.txt"
            labels_path.write_text("\n".join(bucket) + "\n", encoding="utf-8")
            for arm, arm_root in (("A", root), ("B", fresh_root)):
                summary = tmp / f"summary-{arm}-{i}.json"
                attest = tmp / f"attest-{arm}-{i}.jsonl"
                env = os.environ.copy()
                env["GATE_DISPATCH_ATTESTATION_FILE"] = str(attest)
                if arm == "A" and progress_path is not None:
                    env["GATE_DISPATCH_PROGRESS_FILE"] = str(progress_path)
                else:
                    env.pop("GATE_DISPATCH_PROGRESS_FILE", None)
                env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
                arm_script = arm_root / "tools" / "ci" / "repo_hygiene_gates.sh"
                argv_i = ["bash", str(arm_script), "--shard",
                          f"{i}/{total_shards}", "--shard-labels",
                          str(labels_path), "--summary-json", str(summary)]
                workers.append((arm, i, bucket, arm_root, summary, attest,
                                argv_i, env))

        def run_worker(row):
            arm, i, bucket, arm_root, summary, attest, argv_i, env = row
            rc, out, err = _run(
                argv_i, arm_root, env, progress_path=attest,
                expected_progress_labels=expected_executed_labels(bucket),
                stall_grace_s=args.stall_grace)
            return arm, i, bucket, summary, attest, rc, out, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs * 2) as pool:
            results = list(pool.map(run_worker, workers))

        # Resource wave 2.  The census owns its machine while each arm runs.
        # A/B concurrency here reproducibly pushes a 43s-alone subprocess past
        # its honest 60s hang bound, so sequence the two outer arms while
        # retaining the census' measured three-way internal parallelism.
        if sensitive:
            sensitive_i = jobs
            labels_path = tmp / "labels-sensitive.txt"
            labels_path.write_text("\n".join(sensitive) + "\n",
                                   encoding="utf-8")
            sensitive_workers = []
            for arm, arm_root in (("A", root), ("B", fresh_root)):
                summary = tmp / f"summary-{arm}-sensitive.json"
                attest = tmp / f"attest-{arm}-sensitive.jsonl"
                env = os.environ.copy()
                env["GATE_DISPATCH_ATTESTATION_FILE"] = str(attest)
                if arm == "A" and progress_path is not None:
                    env["GATE_DISPATCH_PROGRESS_FILE"] = str(progress_path)
                else:
                    env.pop("GATE_DISPATCH_PROGRESS_FILE", None)
                env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
                arm_script = arm_root / "tools" / "ci" / "repo_hygiene_gates.sh"
                argv_i = ["bash", str(arm_script), "--shard",
                          f"{sensitive_i}/{total_shards}", "--shard-labels",
                          str(labels_path), "--summary-json", str(summary)]
                sensitive_workers.append(
                    (arm, sensitive_i, sensitive, arm_root, summary, attest,
                     argv_i, env))
            for row in sensitive_workers:
                results.append(run_worker(row))

        docs: List[Tuple[Path, Dict[str, Any]]] = []
        arm_a_doc_count = 0
        a_attestations: List[Dict[str, Any]] = []
        b_attestations: List[Dict[str, Any]] = []
        for arm, i, bucket, summary, attest, rc, out, err in sorted(results):
            print(f"=== hygiene arm {arm} shard {i}/{total_shards}: "
                  f"{len(bucket)} gate(s), rc={rc} ===")
            if out:
                print(out, end="" if out.endswith("\n") else "\n")
            if err:
                problems.append(f"arm {arm} shard {i}: {err}")
            if not summary.is_file():
                problems.append(f"arm {arm} shard {i}: no summary (rc={rc})")
                continue
            try:
                doc = _load_json(summary)
                rows = _load_jsonl(attest)
            except (OSError, ValueError) as exc:
                problems.append(
                    f"arm {arm} shard {i}: incomplete machine record: {exc}")
                continue
            problems.extend(_validate_declarations(
                reference, doc, f"arm {arm} shard {i}"))
            if arm == "B" and doc.get("wiring_errors"):
                problems.append(
                    f"arm B shard {i}: dispatcher wiring error(s): "
                    + "; ".join(str(x) for x in doc["wiring_errors"][:3]))
            if arm == "A":
                docs.append((summary, doc))
                arm_a_doc_count += 1
                a_attestations.extend(rows)
            else:
                b_attestations.extend(rows)

        # Establish exact A/B coverage before allowing the dependent comparison.
        a_by_label: Dict[str, List[Dict[str, Any]]] = {}
        b_by_label: Dict[str, List[Dict[str, Any]]] = {}
        for row in a_attestations:
            a_by_label.setdefault(str(row.get("label")), []).append(row)
        for row in b_attestations:
            b_by_label.setdefault(str(row.get("label")), []).append(row)
        process_labels = [
            label for label in phase_a_labels
            if not _legacy_empty_without_process(reference, label)]
        for label in process_labels:
            if len(a_by_label.get(label, [])) != 1:
                problems.append(
                    f"Arm A {label!r}: expected one attestation, got "
                    f"{len(a_by_label.get(label, []))}")
            if len(b_by_label.get(label, [])) != 1:
                problems.append(
                    f"Arm B {label!r}: expected one attestation, got "
                    f"{len(b_by_label.get(label, []))}")
        if set(a_by_label) - set(process_labels):
            problems.append("Arm A produced unplanned attestations")
        if set(b_by_label) - set(process_labels):
            problems.append("Arm B produced unplanned attestations")

        requested_attest = requested_progress
        merged_attest = (Path(requested_attest).resolve() if requested_attest
                         else tmp / "merged-attest.jsonl")
        fresh_attest = tmp / "fresh-attest.jsonl"
        if not problems:
            ordered_a = [a_by_label[label][0] for label in process_labels]
            ordered_b = [b_by_label[label][0] for label in process_labels]
            _write_jsonl(merged_attest, ordered_a)
            _write_jsonl(fresh_attest, ordered_b)
            host_labels = tmp / "labels-host.txt"
            host_labels.write_text(HOST_LABEL + "\n", encoding="utf-8")
            host_summary = tmp / "summary-host.json"
            host_env = os.environ.copy()
            host_env["GATE_DISPATCH_ATTESTATION_FILE"] = str(merged_attest)
            host_env["VIBEIC_HOST_FRESH_ATTESTATIONS"] = str(fresh_attest)
            host_env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
            host_i = jobs + (1 if sensitive else 0)
            host_argv = ["bash", str(script), "--shard",
                         f"{host_i}/{total_shards}", "--shard-labels",
                         str(host_labels), "--summary-json", str(host_summary)]
            hrc, hout, herr = _run(
                host_argv, root, host_env, progress_path=merged_attest,
                expected_progress_labels=[*process_labels, HOST_LABEL],
                stall_grace_s=args.stall_grace)
            print(f"=== hygiene dependent shard {host_i}/{total_shards}: "
                  f"1 gate, rc={hrc} ===")
            if hout:
                print(hout, end="" if hout.endswith("\n") else "\n")
            if herr:
                problems.append(f"host-independence shard: {herr}")
            if not host_summary.is_file():
                problems.append(f"host-independence shard: no summary (rc={hrc})")
            else:
                try:
                    docs.append((host_summary, _load_json(host_summary)))
                    all_attestations = _load_jsonl(merged_attest)
                except (OSError, ValueError) as exc:
                    problems.append(
                        f"host-independence shard: incomplete record: {exc}")
                    all_attestations = ordered_a
        else:
            print("[ERROR] dependent host-independence phase not launched: "
                  "Arm A coverage is incomplete", file=sys.stderr)
            all_attestations = a_attestations

        # COVERAGE, AGAINST THE PLAN RATHER THAN AGAINST THE RECORDS.
        # `labels` is what the dispatcher DECLARED and `buckets` + the sensitive
        # wave + HOST_LABEL are what the planner ASSIGNED; the aggregate is
        # given the latter, written out, and every Arm-A shard record. It
        # refuses a run that lost a shard, ran a gate twice, ran one nobody
        # planned, or was aggregated as sharded while a host ignored its
        # assignment — each of which is a smaller run wearing a full
        # denominator. Its refusal joins `problems`, which already means the
        # run returns 2 and prints "coverage loss is not a result".
        planned = [*(l for b in buckets for l in b), *sensitive, HOST_LABEL]
        expect_path = tmp / "planned-labels.txt"
        expect_path.write_text("\n".join(planned) + "\n", encoding="utf-8")
        coverage_rc = _shard_aggregate.main(
            [*(str(path) for path, _ in docs), "--expect", str(expect_path),
             "--shards", str(total_shards)])
        if coverage_rc != 0:
            problems.append(
                "hygiene_shard_aggregate refused the run's coverage against "
                "the measured plan (see the [COVERAGE] lines above)")

        elapsed = int(time.monotonic() - started)
        final = merge_records(reference, docs, all_attestations, elapsed,
                              problems, worker_docs=arm_a_doc_count)
        write_json(args.summary_json, final, ensure_ascii=False)
        _release_fresh(fresh_res, root)
        atexit.unregister(cleanup)
        rc = _summary_rc(final)
        if problems:
            for problem in problems:
                print(f"  [COVERAGE] {problem}", file=sys.stderr)
            print(f"[ERROR] parallel hygiene incomplete after {elapsed}s; "
                  "coverage loss is not a result", file=sys.stderr)
            return 2
        print(_completion_message(final, elapsed))
        return rc


if __name__ == "__main__":
    raise SystemExit(main())

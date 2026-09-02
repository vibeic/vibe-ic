"""Private pytest liveness plugin: append completed lifecycle events.

The per-file landing driver watches this structured sidecar instead of treating
subject stdout/stderr or CPU activity as pytest progress.  This is a liveness
channel, not verdict evidence and not a privilege boundary: the plugin and the
tests necessarily run in the same Python process.  JUnit plus the OS process
return code remain the inputs to the landing verdict.

Each emitting PROCESS owns its own stream file inside the directory the parent
names, so a parallel pytest session (pytest-xdist) produces N independent
streams rather than one interleaved one.  No record field changes: the record
schema is identical to the single-process case, and every parent-side clause
keeps validating one process's stream.
"""
from __future__ import annotations

import json
import os
import threading
import time


_DIR_ENV = "VIBEIC_PYTEST_PROGRESS_DIR"
_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_IDENTITY_ENV = "VIBEIC_PYTEST_RUNTIME_IDENTITY"
_SCHEMA = 1
_seq = 0
_current_nodeid = None
_emit_lock = threading.Lock()

#: This process's own stream file, chosen once in ``pytest_configure``.
#:
#: ONE PROCESS OWNS ONE STREAM.  ``seq`` is a module global and therefore a
#: per-interpreter fact; ``monotonic_ns`` and the lifecycle stage machine are
#: likewise per-process.  Writing every process into one shared file is what
#: forces the parent to demultiplex N interleaved emitters.  Giving each
#: process its own file keeps every parent-side clause a per-process
#: statement, exactly as it was before pytest-xdist existed.
#:
#: ``None`` means "this process must stay silent": either the parent did not
#: ask for progress, or this is the xdist CONTROLLER, whose stream is a
#: different shape (it reports every test_finish but never collects) and is
#: therefore not a stream the protocol can validate.  The workers between them
#: report the whole session, so nothing is lost by the controller's silence.
_path = None
_WORKER_ID_OK = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

#: Scanned paths between two ``collect_scan`` checkpoints.
#:
#: WHY THIS EVENT EXISTS.  Until it did, this plugin's first event after
#: ``session_start`` was ``collect_report``, which pytest does not reach until
#: the whole path scan is over.  MEASURED on this repo (2026-08-30, pinned
#: image 0.3.6, a 120-file selection): the session spends 57 of its 61
#: collection seconds before the first ``collect_report`` and emits NOTHING a
#: parent can validate in that window.  The landing tier's supervisor watches
#: exactly this channel, so it saw zero forward progress and killed a healthy
#: collection at its 300 s grace -- `AGGREGATE_NORECORD ... (stage=collecting)`.
#: A 1231-file selection scales that silence to ~10 min, so at real landing
#: width the targeted lane could not return a verdict at all.
#:
#: Over the SAME silent window ``pytest_collect_file`` fires 355 200 times with
#: a LARGEST gap between any two calls of 0.59 s.  The phase that costs the
#: time can prove it is moving; it simply was never asked to.
#:
#: A CHECKPOINT, NEVER A HEARTBEAT -- the same rule ``domain_progress`` above
#: is written to.  The event is emitted when the COUNT crosses a stride, never
#: on a clock, so a process that has stopped scanning stops emitting and its
#: grace correctly expires.  The parent accepts only exact ``+STRIDE``
#: transitions, so neither a duplicate nor a fabricated jump keeps a stuck
#: session alive.  The stride is what keeps the channel small: 355 200 scanned
#: paths cost 355 events, not 355 200.
#:
#: NOT GUARDED BY ``_emit_lock``: pytest performs collection on the main
#: thread, and the lock is not reentrant, so taking it here and again in
#: ``_emit`` would deadlock.  A miscount cannot manufacture progress -- the
#: parent's exact-stride clause rejects any value that is not the next one.
COLLECT_SCAN_STRIDE = 1000

_scanned = 0
_scan_emitted = 0


def _own_ppid() -> int:
    """Parent pid as of THIS call, read without trusting a cached value."""
    return os.getppid()


def _is_xdist_worker(config) -> bool:
    # Same duck-typed test the xdist library itself uses
    # (xdist.plugin.is_xdist_worker) and the same one this repo already uses
    # in suite_write_guard.py; it needs no import of xdist.
    return hasattr(config, "workerinput")


def _is_xdist_controller(config) -> bool:
    # ``dist`` only exists as an option once the xdist plugin is registered,
    # so the default matters: without xdist there is no controller at all.
    return (not _is_xdist_worker(config)
            and getattr(config.option, "dist", "no") != "no")


def pytest_configure(config) -> None:
    """Claim this process's own stream file, or decide to stay silent."""
    global _path
    directory = os.environ.get(_DIR_ENV)
    nonce = os.environ.get(_NONCE_ENV)
    if not directory or not nonce:
        return
    if _is_xdist_controller(config):
        return
    if _is_xdist_worker(config):
        worker = str(config.workerinput.get("workerid", ""))
        if (not worker or len(worker) > 32
                or not set(worker) <= _WORKER_ID_OK):
            # An unnameable stream is not a stream. Staying silent makes the
            # parent refuse the session rather than accept an unattributable
            # one.
            return
        name = f"w.{worker}.{os.getpid()}.{_own_ppid()}.jsonl"
    else:
        name = f"m.{os.getpid()}.{_own_ppid()}.jsonl"
    _path = os.path.join(directory, name)


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in out:
            raise ValueError("duplicate or non-string runtime identity key")
        out[key] = value
    return out


def _reject_nonfinite(value):
    raise ValueError(f"non-finite runtime identity number {value!r}")


def _emit(event: str, **fields) -> None:
    global _seq
    path = _path
    nonce = os.environ.get(_NONCE_ENV)
    if not path or not nonce:
        return
    with _emit_lock:
        _seq += 1
        record = {
            "schema": _SCHEMA,
            "nonce": nonce,
            "pid": os.getpid(),
            "seq": _seq,
            "event": event,
            "monotonic_ns": time.monotonic_ns(),
            **fields,
        }
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":"))
                   + "\n").encode("utf-8")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        except OSError:
            # The parent treats a missing/stalled/malformed channel as NORECORD.
            # Raising here could prevent pytest teardown from preserving JUnit.
            pass


def pytest_sessionstart(session) -> None:
    fields = {}
    identity = os.environ.get(_IDENTITY_ENV)
    if identity is not None:
        # The parent performs the strict schema and expected-runtime check.  A
        # decoded object, rather than an opaque string, prevents a second
        # parser with different duplicate-key/non-finite semantics from being
        # introduced at the trust boundary.
        fields["runtime_identity"] = json.loads(
            identity,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    _emit("session_start", **fields)


def _count_scanned_path() -> None:
    """Count one scanned path; checkpoint when the count crosses the stride."""
    global _scanned, _scan_emitted
    _scanned += 1
    if _scanned - _scan_emitted >= COLLECT_SCAN_STRIDE:
        _scan_emitted += COLLECT_SCAN_STRIDE
        _emit("collect_scan", scanned=_scan_emitted)


def pytest_collect_file(file_path, parent):
    """Liveness only.  Counts the path and expresses NO opinion on collecting
    it: this hook is not ``firstresult``, and returning ``None`` leaves the
    collection decision exactly where it was."""
    _count_scanned_path()
    return None


def pytest_collect_directory(path, parent):
    """Liveness only, as ``pytest_collect_file`` above."""
    _count_scanned_path()
    return None


def pytest_collectreport(report) -> None:
    # An EMPTY nodeid is the session/root collector. When a file is collected
    # OUTSIDE the pytest rootdir -- a repo-tools file (tools/...) run under the
    # plugin's OWN rootdir, which is what happens when the per-file driver is
    # pointed at one from `cd $PLUGIN` -- pytest cannot express that file's path
    # relative to the rootdir and reports its collector with the SAME empty
    # nodeid as the session. Two empty-nodeid collect_reports then reach the
    # validator as `duplicate/out-of-order collect_report`, NORECORDing a file
    # that in fact collected and ran cleanly (MEASURED: every tools/ file
    # NORECORDs this way from `cd $PLUGIN`). The empty-nodeid collectreport
    # carries no per-node signal the progress protocol needs -- collection
    # success is already carried by `collection_finish` and the process exit rc
    # -- so it is not emitted. Every real (non-empty) collectreport is
    # unchanged, so the rootdir-internal shape the landing actually uses
    # (`cd $ROOT`, where the file's nodeid is non-empty) is byte-identical.
    nodeid = str(report.nodeid)
    if not nodeid:
        return
    _emit("collect_report", nodeid=nodeid, outcome=str(report.outcome))


def pytest_itemcollected(item) -> None:
    _emit("item_collected", nodeid=str(item.nodeid))


def pytest_collection_finish(session) -> None:
    # pytest_itemcollected runs before -k/-m deselection. Carry both counts so
    # the parent can validate a legitimate selected subset without treating it
    # as a truncated collection.
    _emit("collection_finish", selected_items=len(session.items))


def _is_collect_only(session) -> bool:
    """Return pytest's own collect-only mode without guessing from argv."""
    return bool(getattr(getattr(session, "config", None), "option", None)
                and session.config.option.collectonly)


def pytest_runtest_logstart(nodeid, location) -> None:
    global _current_nodeid
    _current_nodeid = str(nodeid)


def domain_progress(scope: str, completed: int, total: int) -> None:
    """Record finite, monotonic progress inside one long pytest item.

    This is deliberately an explicit checkpoint, not a heartbeat.  The parent
    validates a fixed total and exact ``+1`` transitions, so output, CPU use or
    an accidental duplicate cannot keep a stuck item alive indefinitely.
    """
    if _current_nodeid is None:
        return
    _emit("domain_progress", nodeid=_current_nodeid, scope=str(scope),
          completed=int(completed), total=int(total))


def pytest_runtest_logfinish(nodeid, location) -> None:
    global _current_nodeid
    _emit("test_finish", nodeid=str(nodeid))
    _current_nodeid = None


def pytest_sessionfinish(session, exitstatus) -> None:
    # A collect-only session intentionally runs zero test items, so the normal
    # ``test_finish == selected_items`` terminal proof cannot apply.  Emit a
    # distinct terminal transition only after pytest reached session finish;
    # the parent FSM binds its count to the earlier collection declaration.
    if _is_collect_only(session):
        _emit("collection_only_finish", selected_items=len(session.items))
    _emit("session_finish", exitstatus=int(exitstatus))

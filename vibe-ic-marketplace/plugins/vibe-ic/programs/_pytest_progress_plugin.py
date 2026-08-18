"""Private pytest liveness plugin: append completed lifecycle events.

The per-file landing driver watches this structured sidecar instead of treating
subject stdout/stderr or CPU activity as pytest progress.  This is a liveness
channel, not verdict evidence and not a privilege boundary: the plugin and the
tests necessarily run in the same Python process.  JUnit plus the OS process
return code remain the inputs to the landing verdict.
"""
from __future__ import annotations

import json
import os
import threading
import time


_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_IDENTITY_ENV = "VIBEIC_PYTEST_RUNTIME_IDENTITY"
_SCHEMA = 1
_seq = 0
_current_nodeid = None
_emit_lock = threading.Lock()


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
    path = os.environ.get(_PATH_ENV)
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


def pytest_collectreport(report) -> None:
    _emit("collect_report", nodeid=str(report.nodeid),
          outcome=str(report.outcome))


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

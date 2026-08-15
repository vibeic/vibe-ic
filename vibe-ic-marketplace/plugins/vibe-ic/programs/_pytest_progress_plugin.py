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
import time


_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_SCHEMA = 1
_seq = 0


def _emit(event: str, **fields) -> None:
    global _seq
    path = os.environ.get(_PATH_ENV)
    nonce = os.environ.get(_NONCE_ENV)
    if not path or not nonce:
        return
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
    _emit("session_start")


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


def pytest_runtest_logfinish(nodeid, location) -> None:
    _emit("test_finish", nodeid=str(nodeid))


def pytest_sessionfinish(session, exitstatus) -> None:
    _emit("session_finish", exitstatus=int(exitstatus))

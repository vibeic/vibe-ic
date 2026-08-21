"""Private pytest liveness plugin: append completed lifecycle events.

The per-file landing driver watches this structured sidecar instead of treating
subject stdout/stderr or CPU activity as pytest progress.  This is a liveness
channel, not verdict evidence and not a privilege boundary: the plugin and the
tests necessarily run in the same Python process.  JUnit plus the OS process
return code remain the inputs to the landing verdict.

ONE WRITER, AND IT IS THE PROCESS THE SUPERVISOR IS WATCHING
============================================================
`pytest_per_file_junit._SemanticProgressProbe` accepts an event only when its
``pid`` field equals the pid of the pytest process it spawned, and only in a
strict session_start -> item_collected* -> collection_finish -> test_finish* ->
session_finish order.  That is deliberate: a second writer could keep a stalled
session looking alive.

Under `pytest-xdist` there ARE other processes -- one controller (the spawned
pid) and N workers -- and the workers are the ones that collect.  Measured on
2026-08-17 with `-n 2 --dist loadfile` over two selected files, hooks by process:

    controller  configure(worker=False) sessionstart
                pytest_xdist_node_collection_finished x2 (ids identical, n=15)
                logstart/logfinish x15   sessionfinish
    each worker configure(worker=True)  sessionstart collectreport itemcollected
                collection_finish  logstart/logfinish (its share) sessionfinish

So the naive shape emits from three pids and the supervisor refuses the run:
``PROGRESS_PROTOCOL_INCOMPLETE: schema/nonce/pid mismatch`` ->
``AGGREGATE_NORECORD``, which is a landing refusal, not a false green.  Two
changes keep exactly ONE writer and the same state machine:

  * a worker (``config.workerinput``) never emits.  Its lifecycle is reported to
    the controller anyway, so nothing is lost;
  * the controller publishes the collection that the workers performed, once,
    from ``pytest_xdist_node_collection_finished``.  xdist calls that hook per
    node BEFORE any test is scheduled (scheduling waits for every node to have
    collected and for the collections to be identical), so the events still
    arrive strictly before the first ``test_finish``.

``domain_progress`` has no controller-side channel under xdist: it is called by
subject code, which runs in a worker.  It is not needed there -- with N workers
the controller sees a ``test_finish`` from every other worker while one long
item runs, and each item is separately bounded by ``--timeout``.  It keeps
working unchanged in the single-process (non-xdist) shape, which is the one that
has a single item as its only liveness source.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest


_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_SCHEMA = 1
_seq = 0
_current_nodeid = None
_emit_lock = threading.Lock()
#: True in an xdist WORKER. Set in `pytest_configure`, which pytest calls before
#: `pytest_sessionstart`, so no event can escape a worker ahead of it.
_muted = False
#: The controller publishes the workers' collection exactly once.
_xdist_collection_published = False


def _emit(event: str, **fields) -> None:
    global _seq
    if _muted:
        return
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


def pytest_configure(config) -> None:
    global _muted
    _muted = hasattr(config, "workerinput")


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


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids) -> None:
    """Publish, ONCE, the collection the xdist workers performed.

    `optionalhook` because this hookspec only exists when xdist is loaded, and
    the landing session loads it by name (`-p xdist`) rather than by autoload.
    Without the marker pytest refuses to register this plugin at all in the
    single-process shape.
    """
    global _xdist_collection_published
    if _xdist_collection_published:
        return
    _xdist_collection_published = True
    for nodeid in ids:
        _emit("item_collected", nodeid=str(nodeid))
    _emit("collection_finish", selected_items=len(ids))


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
    _emit("session_finish", exitstatus=int(exitstatus))

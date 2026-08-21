"""Private pytest liveness plugin: append completed lifecycle events.

The per-file landing driver watches this structured sidecar instead of treating
subject stdout/stderr or CPU activity as pytest progress.  This is a liveness
channel, not verdict evidence and not a privilege boundary: the plugin and the
tests necessarily run in the same Python process.  JUnit plus the OS process
return code remain the inputs to the landing verdict.

SCHEMA 2 -- ONE SIDECAR, MANY EMITTERS.  Under pytest-xdist the selection is
executed by N worker PROCESSES, all appending to this one file, so `seq` cannot
be a single global counter and `pid` cannot be a single expected value.  Every
record therefore carries the identity of its own emitter:

  ``role``  which of the three legal stream shapes this process produces --
            ``solo`` (no xdist: collects and runs), ``worker`` (collects the
            whole selection, runs its share) or ``controller`` (collects
            nothing, observes every test finishing).  Declared rather than
            guessed, so the parent validates against a named state machine
            instead of inferring one from the events it happens to see.
  ``ppid``  the parent pid captured at IMPORT, i.e. before any reparenting can
            rewrite it.  For the process the driver launched this is the driver;
            for an xdist worker it is the launched controller.  It is what lets
            the parent refuse an emitter that is not a child of this launch.

`seq` stays per PROCESS, which needs no code here: `_seq` is a module global in
a freshly imported interpreter, so each worker starts at 1 by construction and
its own substream is exactly 1..n in file order.  `_emit_lock` spans the
increment AND the write, and each record is one `os.write` to an O_APPEND fd, so
concurrent emitters interleave whole lines and never tear one.
"""
from __future__ import annotations

import json
import os
import threading
import time


_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_SCHEMA = 2
_seq = 0
_current_nodeid = None
_emit_lock = threading.Lock()
#: Captured at import, which happens during pytest startup in every process
#: (controller and each xdist worker).  Reading it later would report the
#: subreaper instead of the real parent if the parent had already exited.
_PPID = os.getppid()
_role = "solo"


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
            "ppid": _PPID,
            "role": _role,
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


def _detect_role(config) -> str:
    """Name this process's stream shape the way pytest-xdist itself does.

    ``xdist.is_xdist_worker`` is literally ``hasattr(config, "workerinput")``
    and ``is_xdist_controller`` adds ``config.option.dist != "no"``; this repo
    already relies on the same duck-typed check in
    ``programs/suite_write_guard.py``.  Doing it without importing xdist keeps
    this plugin loadable in a session that has no xdist installed.

    Read at sessionstart rather than at ``pytest_configure`` so it cannot race
    xdist's own configure-time normalisation of ``dist``.
    """
    if hasattr(config, "workerinput"):
        return "worker"
    dist = getattr(getattr(config, "option", None), "dist", "no")
    return "controller" if dist and str(dist) != "no" else "solo"


def pytest_sessionstart(session) -> None:
    global _role
    try:
        _role = _detect_role(session.config)
    except Exception:  # nosec — an unreadable config must not break liveness
        _role = "solo"
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

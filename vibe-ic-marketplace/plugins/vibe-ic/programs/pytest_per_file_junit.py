#!/usr/bin/env python3
"""pytest_per_file_junit.py — run the whole selection once, then recover with
ONE pytest session per selected file only when that aggregate record is lost, so
a file that HANGS costs its own diagnostic record and not every neighbour's,
while the whole-selection answer remains an absolute requirement
(vibe-ic#1654).

THIS PROGRAM MEASURES. It forms no landing opinion; `landing_merge_verdict.py`
still decides. What it changes is whether that decision has anything to read.

THE DEFECT
==========
The landing gate runs the whole targeted selection as ONE pytest session with
ONE ``--junitxml``. `--timeout-method=thread` cannot interrupt a blocking
``waiter.acquire()``; pytest-timeout dumps every thread's stack and takes the
PROCESS down, and a process that dies never writes its junit. MEASURED on
2026-08-15 at 1adbf3444 with three files — one green, one hanging in the exact
shape of `test_matrix_mutation_ledger.py:689` (``Future.result`` ->
``Condition.wait`` -> ``waiter.acquire``), one green after it::

    $ timeout 300 env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \\
        -p pytest_timeout --timeout=180 --timeout-method=thread \\
        -o junit_family=xunit1 --junitxml=/tmp/junit_repro_1654.xml \\
        test_green_neighbour.py test_hangs_like_replay.py test_green_after.py
    PYTEST_RC=1
    +++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++
    $ ls -l /tmp/junit_repro_1654.xml
    ls: cannot access '/tmp/junit_repro_1654.xml': No such file or directory

`test_green_neighbour.py::test_i_am_green` had already PASSED and its record was
destroyed anyway. In the run that opened #1654 the hanging file was 1 of 91, so
the blast radius was the other 90 files' results — on BOTH arms, which is worse
than it sounds: the differential the merge gate computes is the candidate's
failing SET minus the base's, and both sets come from junit.

WHY THIS AND NOT A BIGGER BOUND
===============================
Raising `--timeout` moves the cliff; it does not remove it. And the bound is not
the property at issue: `_REVIEWED_ADVISORY_RESIDUAL` in
`programs/tests/test_ci_harness_timeout_ceiling_check.py` already records, with
a sound measurement, that `REPLAY_TIMEOUT=900` cannot simply be lowered to the
60 s ceiling because the worst MEASURED call is 42.61 s and 60 s would fire on
passing work. That entry reasons about DURATION. This program is about the
EVIDENCE: what the expiry does to the record. Two different properties, and the
second one is what makes an absent record readable as a clean one.

WHAT AN ABSENT RECORD MUST MEAN
===============================
"I could not look" — never "nothing was there". So a file whose session died
without writing a junit is deliberately kept ABSENT from the merged report and
named on stdout as ``NORECORD``. A synthetic red `<testcase>` for NORECORD was
considered and REJECTED: the merge gate compares two arms, so a red that both
arms produce is scored PRE-EXISTING and would let a hang that fires on both
sides land as "not this PR's" — the exact false-clean this program exists to
prevent. Absence keeps `landing_merge_verdict.decide`'s existing refusal
(``SELECTED TEST FILE(S) PRODUCED NO TEST CASE``) firing, and now it fires
naming the ONE file instead of all 91.

A different shape *does* have a complete record: every testcase is green, then
a session-level guard such as ``suite_write_guard`` sets pytest's process status
to 1. Junit has no native place for that verdict. The merge therefore adds a
stable ``pytest_per_file_process::<path>::process_exit`` testcase for every
complete session, including rc=0, and stores the exact rc as a property. This is
not invented evidence: the process returned that measured status. Keeping the
same key on both arms lets rc=1 -> rc=0 be a fix, while still preventing a
green testcase XML from erasing a session-level refusal.

PROGRESS SUPERVISION, NOT A RUNTIME GUESS
=========================================
There is deliberately no pytest-timeout guard on the landing path. A fixed
elapsed limit kills the session rather than measuring a test and makes
healthy-but-slow work indistinguishable from a hang. The outer supervisor does
not guess how long a file or the aggregate selection should take. A private
pytest plugin appends completed collection/test lifecycle events to a structured
sidecar and the supervisor watches ONLY validated, strictly ordered events.
Captured output and CPU activity are deliberately not progress: an import loop
can log or burn CPU forever without completing collection. A progressing
process may finish no matter how long the whole run takes; a session with no
pytest event for the stall window is NORECORD, which REFUSES the landing.

The sidecar is a liveness protocol, not verdict evidence or a privilege
boundary: pytest hooks and subject code necessarily share one Python process.
It removes accidental stdout/CPU false-progress. JUnit and the OS process rc
remain authoritative for the result, and missing/malformed/incomplete sidecar
state fails closed as NORECORD.

ONE PROCESS OWNS ONE STREAM.  The sidecar is a parent-owned private directory
and each emitting process writes its own file in it, so a parallel session
(pytest-xdist) is N independent streams rather than one interleaved one. Every
clause -- nonce, pid, strictly ``+1`` sequence, strictly increasing monotonic
stamp, the lifecycle stage machine, the resource ceilings -- keeps validating
exactly one process, unchanged.  Two questions the single-process shape could
answer implicitly are answered explicitly instead: WHICH processes belong to
this launch (a stream is admitted only if it is the launched process itself or
a direct child of it), and WHETHER EVERY SELECTED ITEM FINISHED (no worker can
say, because each runs only the share the controller hands it, so the
assertion is re-sited to a join over the workers' finished sets).  That join is
what keeps a ``--maxfail`` prefix a NORECORD instead of a complete failure set.

The driver is also a Linux child subreaper.  After a NATURAL pytest exit it
first reaps adopted zombies, then performs a fresh pid/starttime census.  Dead
children that merely awaited their subreaper do not erase a complete verdict.
Any descendant still LIVE at that point is a real asynchronous leak: it is
terminated and verified gone so it cannot contaminate the next arm, but the
session remains NORECORD because killing unfinished work cannot turn it green.
An unreadable census or any survivor is likewise NORECORD.  The outer verifier
independently checks both isolated test worktrees after cleanup, so a late child
write cannot be mistaken for an immutable measurement.

chip-AGNOSTIC: pure process and XML plumbing. No design, PDK, vendor or process
literal appears here.

USAGE
-----
    python3 pytest_per_file_junit.py --selection SEL --junit OUT
        [--stall-after SECONDS] [--stop-after-failures N] [--cwd DIR]
        [--aggregate-check] [--aggregate-only]
        [--aggregate-stall-after SECONDS] [--fallback-jobs N]
        [--fallback-rescue-jobs N]
        -- <the full pytest command, e.g. python3 -m pytest -q>

The command after ``--`` is run VERBATIM with ``-o junit_family=xunit1``, a
per-file ``--junitxml`` and the one file appended. It is passed in rather than
built here so callers can pin their pytest environment without granting this
driver authority to invent a verdict-affecting elapsed-time limit.

With ``--aggregate-check`` the command first runs once over the entire selection.
Its testcase ids are namespaced under ``pytest_aggregate`` and its exact process
rc is recorded under a stable process key. That preserves the single-process
order/global-state semantics of the command this driver replaced. A complete
aggregate is the whole answer, so no per-file sessions are launched. An aggregate
stall or missing/partial XML is ``AGGREGATE_NORECORD`` and remains an absolute
landing refusal; only then are isolated per-file sessions launched to preserve
every recoverable neighbouring record and name any individual ``NORECORD``.
Those recovery sessions run in bounded process pools. Each worker owns a
separate semantic supervisor/subreaper; process-global cleanup state is never
shared through threads. The first wave is a deterministic stratified probe across
the ordered selection, including both ends. It is an early diagnostic only: even
when every probe returns semantic NORECORD, that sample is never allowed to infer
the result of an untried file. Every remaining file is attempted through a
resource-aware high-parallel rescue. Its simultaneous-worker width is the minimum
of explicit request, CPU fan-out, available-memory reservation, cgroup PID
headroom, and an absolute process ceiling. A systemic collection hang therefore
costs bounded parallel waves rather than one stall window per selected file,
without trading away the only recoverable record. Results are emitted and merged
in the original selection order regardless of which indices ran first.

``--aggregate-only`` disables that diagnostic recovery. It remains available for
callers that need exactly one whole-selection attempt, but the landing callers do
not use it: after aggregate NORECORD they retain per-file evidence while still
returning ``RC_NORECORD``. Recovery therefore adds no work to the successful
critical path and can never turn UNKNOWN into a landing pass.

EXIT CODES
----------
    0  every executed session produced a complete record and nothing was red
    1  every executed session produced a complete record, some verdict was red
    2  AT LEAST ONE REQUIRED SESSION PRODUCED NO COMPLETE RECORD
    3  the question could not be put (no selection, unusable arguments)
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import importlib.util
import json
import os
import re
import select
import selectors
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import _watchdog as _wd
# ONE DEFINITION OF THE STRIDE, imported rather than restated.  The emitter
# checkpoints on it and the clause below accepts only exact `+STRIDE` steps;
# two copies of that number would let the channel drift into accepting a
# heartbeat the emitter never promised.
from _pytest_progress_plugin import COLLECT_SCAN_STRIDE

RC_OK = 0
RC_RED = 1
RC_NORECORD = 2
RC_CANNOT_ASK = 3

#: No-pytest-progress grace, not a duration estimate. The inner pytest guard is
#: 180 s in both callers, so 300 s permits its diagnostics and teardown while a
#: healthy session that keeps completing pytest stages can run indefinitely.
DEFAULT_STALL_AFTER = 300
DEFAULT_AGGREGATE_STALL_AFTER = 300
DEFAULT_FALLBACK_JOBS = 8
DEFAULT_FALLBACK_RESCUE_JOBS = 32
DEFAULT_POLL_S = 2

# Parallel fallback is diagnostic work after landing is already an absolute
# RC_NORECORD refusal.  It should be broad enough to rescue a sparse good file,
# but it must not fork according to corpus size.  These are concurrency limits,
# never estimates of how long a healthy pytest session may run.
MAX_FALLBACK_PROCESSES = 64
_FALLBACK_CPU_FANOUT_PER_CORE = 2
_FALLBACK_MEMORY_PER_JOB_BYTES = 512 * 1024 * 1024
_FALLBACK_MEMORY_RESERVE_BYTES = 1024 * 1024 * 1024
_FALLBACK_PIDS_PER_JOB = 8
_FALLBACK_PID_RESERVE = 32
_FALLBACK_UNMEASURED_RESOURCE_CAP = 4

_PROGRESS_DIR_ENV = "VIBEIC_PYTEST_PROGRESS_DIR"
_PROGRESS_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_REQUIRE_RUNTIME_IDENTITY_ENV = "VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY"
_PROGRESS_PLUGIN = "_pytest_progress_plugin"
_PROGRAMS_DIR = Path(__file__).resolve().parent
_PROGRESS_SCHEMA = 1
_MAX_PROGRESS_BYTES = 64 * 1024 * 1024
_MAX_PROGRESS_EVENTS = 1_000_000
_MAX_PROGRESS_LINE = 64 * 1024
_MAX_DOMAIN_PROGRESS_TOTAL = 10_000
#: A RUNAWAY EMITTER IS ONE TEST INVENTING SCOPES, NOT A BIG HONEST SELECTION.
#:
#: MEASURED 2026-08-24, differential arm over 209 selected files / 5167 collected
#: cases: the aggregate session reached 59% and then died with
#:
#:     PROGRESS_PROTOCOL_INCOMPLETE: domain progress scope resource limit exceeded
#:     WATCHDOG_STALLED: ... did not advance for > 300s — killed as hung, not slow.
#:
#: in that order, and the order is the whole story. The protocol validator hit a
#: FLAT cap of 64 distinct `(nodeid, scope)` keys, stopped accepting progress,
#: and the watchdog then correctly reported that no progress was arriving. The
#: watchdog was right; it was reporting a silence this cap created.
#:
#: 64 is a per-FILE number applied to a whole-SELECTION session. The key is
#: `(nodeid, scope)`, so it is consumed per emitting TEST: one parametrised
#: module (125 cases) can exhaust it alone. A flat cap therefore guarantees the
#: aggregate arm can never finish, and guarantees it harder as the suite grows —
#: which is exactly backwards, because the aggregate arm exists to answer the
#: cross-file/order question that only a large selection can pose.
#:
#: So the guard is split into the two things it was conflating:
#:   * PER NODE — how many distinct scopes ONE test may open. This is the actual
#:     runaway shape and it stays small and flat.
#:   * IN TOTAL — bounded by what was actually COLLECTED, so an honest selection
#:     is never refused for being large, with a floor for tiny sessions.
_MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE = 8
_MAX_DOMAIN_PROGRESS_SCOPES_FLOOR = 64
#: One stream per emitting process. A parallel pytest session opens one per
#: worker, so this is a concurrency bound, never an estimate of how many
#: workers a healthy run may use.
#: The scan channel's runaway cap.  PER UNIT AND FLAT, with a FLOOR -- the
#: shape a runaway rule has to have, as distinct from a stall grace, which is
#: about forward progress and stays flat in seconds.
#:
#: MEASURED on this repo (2026-08-30, pinned image 0.3.6): a 120-file selection
#: makes pytest scan 355 200 paths, i.e. ~2 960 per selected file, because the
#: tree is re-walked per argument.  8 192 leaves ~2.8x headroom on the measured
#: rate while still bounding a runaway emitter, and the floor keeps a
#: one-file selection from being capped below a legitimate scan.
_COLLECT_SCAN_PATHS_PER_UNIT = 8192
_COLLECT_SCAN_FLOOR = 1_000_000

_MAX_PROGRESS_STREAMS = 256
#: Absolute ceiling over ALL streams. The per-stream ceiling stays
#: `_MAX_PROGRESS_BYTES`, so the set's budget is that times the number of
#: emitters -- N processes legitimately cost N times as much. That scaling is
#: not a convenience: MEASURED, every xdist worker re-emits `item_collected`
#: for the WHOLE selection, so the volume is O(workers x selected items) --
#: 1600 tests cost 0.5 MiB at `-n 0` and 7.7 MiB at `-n 32`. A flat total
#: would therefore start refusing HEALTHY wide runs on a large selection,
#: which is a new block rather than a preserved refusal. This absolute cap is
#: what keeps it a bound at all.
_MAX_PROGRESS_TOTAL_BYTES = 1024 * 1024 * 1024

_PR_SET_CHILD_SUBREAPER = 36
_ACTIVE_JOB: Optional[Tuple[int, Set[Tuple[int, int]]]] = None
_ACTIVE_FALLBACK_BASELINE: Optional[Set[Tuple[int, int]]] = None
_IN_SHUTDOWN = False
_CLEANUP_ACTIVE = False
_PENDING_SHUTDOWN_SIGNAL: Optional[int] = None
_SHUTDOWN_SIGNAL_READER: Optional[socket.socket] = None
_SHUTDOWN_SIGNAL_WRITER: Optional[socket.socket] = None
_KILL_CONFIRM_GRACE_S = 1.0
_REAPER_POLL_MS = 100
_FALLBACK_WORKER_FLAG = "--_fallback-worker-spec"
_FALLBACK_WORKER_ENV = "VIBEIC_PYTEST_FALLBACK_WORKER"
_COLLECT_WORKER_FLAG = "--_collect-worker-spec"

#: Outcomes that count toward `--stop-after-failures`, matching what
#: `landing_merge_verdict.RED` counts.
_RED_TAGS = ("failure", "error")

#: Written to the merged report even when every arm failed, because the report
#: IS the deliverable: a run that produced no file at all is indistinguishable
#: from a run that never happened.
_ROOT_TAG = "testsuites"


def _load_hermetic_progress_emitter():
    """Load the exact helper from this protected runtime, never the subject."""
    runtime_root = _PROGRAMS_DIR.parents[3]
    path = runtime_root / "tools" / "ci" / "hermetic_progress_emit.py"
    spec = importlib.util.spec_from_file_location(
        "_vibeic_hermetic_pytest_progress", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("hermetic progress emitter is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_hermetic_progress_planner():
    """Load the BASE-owned nested-domain plan from this protected runtime."""
    runtime_root = _PROGRAMS_DIR.parents[3]
    path = runtime_root / "tools" / "ci" / "trusted_test_selection.py"
    spec = importlib.util.spec_from_file_location(
        "_vibeic_hermetic_pytest_plan", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("hermetic pytest progress planner is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _HermeticAggregateProgress:
    """Relay only BASE-planned nested domains and completed pytest items."""

    def __init__(self, selection: Sequence[str], emitter=None, planner=None):
        self.selection = list(selection)
        self.emitter = emitter or _load_hermetic_progress_emitter()
        self.planner = planner or _load_hermetic_progress_planner()
        self.completed: Set[str] = set()
        self.nodes_by_file: Dict[str, List[str]] = {}
        self.schedule: List[Tuple[str, str, str, int, str, str, int, int]] = []
        for test_file in self.selection:
            spec = self.planner.HERMETIC_TEST_PROGRESS.get(test_file)
            if spec is not None:
                by_ordinal: Dict[int, List[Tuple[str, str, int]]] = {}
                for ordinal, nodeid, scope, total in spec["domains"]:
                    by_ordinal.setdefault(ordinal, []).append(
                        (nodeid, scope, total))
                for ordinal in range(1, spec["items"] + 1):
                    for nodeid, scope, total in by_ordinal.get(ordinal, ()):
                        for completed in range(1, total + 1):
                            self.schedule.append((
                                "domain",
                                self.planner.domain_progress_unit(
                                    test_file, nodeid, scope, completed, total),
                                test_file, ordinal, nodeid, scope, completed,
                                total,
                            ))
                    self.schedule.append((
                        "item",
                        self.planner.test_progress_unit(
                            test_file, ordinal, spec["items"]),
                        test_file, ordinal, "", "", 0, spec["items"],
                    ))
            self.schedule.append((
                "file", "pytest:" + test_file, test_file, 0, "", "", 0,
                0))
        self.emitted = 0
        self.collection_emitted = False
        self.problem = ""

    def _emit(self, state: str, unit: Optional[str] = None) -> bool:
        if self.problem:
            return False
        try:
            sys.stdout.flush()
            self.emitter.emit(state, unit)
            sys.stdout.flush()
            return True
        except BaseException as exc:
            self.problem = f"hermetic progress relay refused: {exc}"
            return False

    def start(self) -> bool:
        return self._emit("start")

    def observe(self, probe: "_SemanticProgressProbe") -> None:
        if self.problem or probe.error or probe.declared_items is None:
            return
        if not self.collection_emitted:
            if not self._emit("checkpoint", "pytest:collection-complete"):
                return
            self.collection_emitted = True
        for test_file in self.selection:
            spec = self.planner.HERMETIC_TEST_PROGRESS.get(test_file)
            ordered_nodes = [
                nodeid for nodeid in probe.item_order
                if nodeid == test_file or nodeid.startswith(test_file + "::")
            ]
            if spec is not None:
                if len(ordered_nodes) != spec["items"]:
                    self.problem = (
                        "parent-owned pytest item denominator differs for "
                        + test_file)
                    return
                for ordinal, nodeid, _scope, _total in spec["domains"]:
                    if ordered_nodes[ordinal - 1] != nodeid:
                        self.problem = (
                            "parent-owned nested domain nodeid/ordinal differs")
                        return
                for _ordinal, nodeid, scope, expected_total in spec["domains"]:
                    observed = probe.domain_progress.get((nodeid, scope))
                    if (observed is not None
                            and observed[1] != expected_total):
                        self.problem = (
                            "parent-owned nested domain denominator differs")
                        return
                self.nodes_by_file[test_file] = ordered_nodes
            if test_file in self.completed:
                continue
            nodes = set(ordered_nodes)
            if nodes and nodes <= probe.finished:
                self.completed.add(test_file)
        # Preserve the exact parent-owned schedule.  A nested checkpoint is
        # available only after the strict pytest FSM accepted the exact
        # nodeid/scope/total/+1 transition.  If that test or the whole file
        # finishes before consuming every optional liveness slot, fill the
        # unused suffix only then: a fast FAIL remains a complete record, while
        # those terminal backfills cannot prolong a running process.
        while self.emitted < len(self.schedule):
            (kind, unit, test_file, ordinal, nodeid, scope, completed,
             expected_total) = self.schedule[self.emitted]
            if kind == "file":
                ready = test_file in self.completed
            elif kind == "item":
                ordered_nodes = self.nodes_by_file.get(test_file, [])
                ready = bool(
                    len(ordered_nodes) >= ordinal
                    and ordered_nodes[ordinal - 1] in probe.finished)
            elif kind == "domain":
                observed = probe.domain_progress.get((nodeid, scope))
                if observed is not None and observed[1] != expected_total:
                    self.problem = (
                        "parent-owned nested domain denominator differs")
                    return
                ready = bool(
                    observed is not None and observed[0] >= completed
                    or nodeid in probe.finished
                    or test_file in self.completed)
            else:  # pragma: no cover - schedule is built locally above
                self.problem = "unknown parent-owned progress schedule kind"
                return
            if not ready:
                break
            if not self._emit("checkpoint", unit):
                return
            self.emitted += 1

    def finish(self) -> bool:
        if (self.problem or not self.collection_emitted
                or self.emitted != len(self.schedule)):
            if not self.problem:
                self.problem = (
                    "not every selected file reached a validated test_finish")
            return False
        if not self._emit("checkpoint", "pytest:record-published"):
            return False
        return self._emit("terminal")


def _reject_json_pairs(pairs):
    out = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in out:
            raise ValueError("duplicate or non-string JSON key")
        out[key] = value
    return out


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON number {value!r}")


def _runtime_identity(value: object) -> Optional[dict]:
    """Return the exact isolated-entry identity or ``None`` on any ambiguity."""
    if not isinstance(value, dict) or set(value) != {
            "schema", "python", "entry", "plugin", "modules"}:
        return None
    if type(value["schema"]) is not int or value["schema"] != 1:
        return None

    def file_row(row: object, *, named: bool = False) -> Optional[dict]:
        keys = {"path", "sha256", "size"} | ({"name"} if named else set())
        if not isinstance(row, dict) or set(row) != keys:
            return None
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("size")
        if (not isinstance(path, str) or not path.startswith("/")
                or "\x00" in path or "\n" in path or "\r" in path
                or not isinstance(digest, str) or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)
                or type(size) is not int or size < 0):
            return None
        result = {"path": path, "sha256": digest, "size": size}
        if named:
            name = row.get("name")
            if not isinstance(name, str):
                return None
            result["name"] = name
        return result

    python = file_row(value["python"])
    entry = file_row(value["entry"])
    plugin = file_row(value["plugin"])
    modules_raw = value["modules"]
    if (python is None or entry is None or plugin is None
            or not isinstance(modules_raw, list)):
        return None
    modules = [file_row(row, named=True) for row in modules_raw]
    if (any(row is None for row in modules)
            or [row["name"] for row in modules if row is not None]
            != ["pytest", "_pytest", "pluggy"]):
        return None
    return {"schema": 1, "python": python, "entry": entry,
            "plugin": plugin, "modules": modules}


class FileResult:
    """What one file's own pytest session produced."""

    def __init__(self, path: str, rc: Optional[int], killed: bool,
                 suite: Optional[ET.Element], cases: int, red: int,
                 skipped_by_stop: bool = False,
                 norecord_reason: str = ""):
        self.path = path
        self.rc = rc
        self.killed = killed
        self.suite = suite
        self.cases = cases
        self.red = red
        self.skipped_by_stop = skipped_by_stop
        self.norecord_reason = norecord_reason

    @property
    def has_record(self) -> bool:
        return self.suite is not None


@dataclass
class _FallbackJob:
    """One process-isolated per-file recovery worker."""

    index: int
    test_file: str
    junit_path: Path
    meta_path: Path
    log_path: Path
    proc: subprocess.Popen
    pidfd: Optional[int] = None


@dataclass
class _FallbackOutcome:
    """A recovered file result plus its captured deterministic-order log."""

    result: FileResult
    log: str


@dataclass(frozen=True)
class _FallbackCapacity:
    """Auditable simultaneous-worker ceiling from three host resources."""

    jobs: int
    requested: int
    cpu_cap: int
    memory_cap: int
    pid_cap: int
    hard_cap: int = MAX_FALLBACK_PROCESSES


class _SemanticProgressProbe:
    """Parse only valid, finite-state pytest lifecycle events as progress."""

    _FIELDS = {
        "session_start": set(),
        "collect_scan": {"scanned"},
        "collect_report": {"nodeid", "outcome"},
        "item_collected": {"nodeid"},
        "collection_finish": {"selected_items"},
        "collection_only_finish": {"selected_items"},
        "domain_progress": {"nodeid", "scope", "completed", "total"},
        "test_finish": {"nodeid"},
        "session_finish": {"exitstatus"},
    }
    _COMMON = {"schema", "nonce", "pid", "seq", "event", "monotonic_ns"}

    def __init__(self, path: Path, nonce: str, pid_fn, *, collect_only=False,
                 require_runtime_identity=False,
                 partial_session: bool = False,
                 collect_scan_ceiling: int = _COLLECT_SCAN_FLOOR):
        self.path = path
        self.nonce = nonce
        self.pid_fn = pid_fn
        #: A pytest-xdist WORKER legitimately collects the whole selection and
        #: runs only the share the controller hands it, so its own
        #: ``session_finish`` cannot assert "every selected item finished".
        #: That assertion is not dropped -- it is RE-SITED to the session, in
        #: ``_ProgressStreamSet.complete``, as a join over every worker's
        #: finished set.  A stream opened with ``partial_session=True`` is only
        #: ever complete as part of that join.
        self.partial_session = partial_session
        self.file = path.open("rb", buffering=0)
        st = os.fstat(self.file.fileno())
        self.identity = (st.st_dev, st.st_ino)
        self.offset = 0
        self.tail = b""
        self.seq = 0
        self.score = 0
        self.stage = "initial"
        self.last_ns = 0
        self.error = ""
        self.collect_reports: Set[str] = set()
        #: Paths this process has checkpointed scanning.  Advances during the
        #: phase that used to emit nothing at all; see `collect_scan` below.
        self.collect_scanned = 0
        self.collect_scan_ceiling = collect_scan_ceiling
        self.items: Set[str] = set()
        self.item_order: List[str] = []
        self.finished: Set[str] = set()
        self.declared_items: Optional[int] = None
        self.domain_progress: Dict[Tuple[str, str], Tuple[int, int]] = {}
        self.collect_only = bool(collect_only)
        self.require_runtime_identity = bool(require_runtime_identity)
        self.runtime_identity: Optional[dict] = None

    def close(self) -> None:
        self.file.close()

    def _fail(self, reason: str) -> None:
        if not self.error:
            self.error = reason

    def _accept(self, record: object) -> None:
        if not isinstance(record, dict):
            self._fail("record is not an object")
            return
        event = record.get("event")
        if event not in self._FIELDS:
            self._fail(f"unknown event {event!r}")
            return
        expected_fields = self._COMMON | self._FIELDS[event]
        actual_fields = set(record)
        if (event == "session_start"
                and actual_fields == expected_fields | {"runtime_identity"}):
            pass
        elif actual_fields != expected_fields:
            self._fail(f"wrong fields for {event}")
            return
        pid = self.pid_fn()
        if (record.get("schema") != _PROGRESS_SCHEMA
                or record.get("nonce") != self.nonce
                or not isinstance(pid, int) or record.get("pid") != pid):
            self._fail("schema/nonce/pid mismatch")
            return
        seq = record.get("seq")
        stamp = record.get("monotonic_ns")
        if (not isinstance(seq, int) or seq != self.seq + 1
                or not isinstance(stamp, int) or stamp <= self.last_ns):
            self._fail("non-monotonic sequence or timestamp")
            return
        if seq > _MAX_PROGRESS_EVENTS:
            self._fail("event resource limit exceeded")
            return

        if event == "session_start":
            if self.stage != "initial":
                self._fail("duplicate/out-of-order session_start")
                return
            identity = record.get("runtime_identity")
            if identity is not None:
                self.runtime_identity = _runtime_identity(identity)
                if self.runtime_identity is None:
                    self._fail("invalid trusted pytest runtime identity")
                    return
            elif self.require_runtime_identity:
                self._fail("trusted pytest runtime identity is missing")
                return
            self.stage = "collecting"
        elif event == "collect_scan":
            self._accept_collect_scan(record.get("scanned"))
            if self.error:
                return
        elif event == "collect_report":
            nodeid = record.get("nodeid")
            if (self.stage != "collecting" or not isinstance(nodeid, str)
                    or nodeid in self.collect_reports):
                self._fail("duplicate/out-of-order collect_report")
                return
            self.collect_reports.add(nodeid)
        elif event == "item_collected":
            nodeid = record.get("nodeid")
            if (self.stage != "collecting" or not isinstance(nodeid, str)
                    or not nodeid or nodeid in self.items):
                self._fail("duplicate/out-of-order item_collected")
                return
            self.items.add(nodeid)
            self.item_order.append(nodeid)
        elif event == "collection_finish":
            count = record.get("selected_items")
            if (self.stage != "collecting" or not isinstance(count, int)
                    or count < 0 or count > len(self.items)):
                self._fail("collection count/state mismatch")
                return
            self.declared_items = count
            self.stage = "running"
        elif event == "domain_progress":
            nodeid = record.get("nodeid")
            scope = record.get("scope")
            completed = record.get("completed")
            total = record.get("total")
            key = (nodeid, scope)
            previous = self.domain_progress.get(key)
            if (self.stage != "running" or nodeid not in self.items
                    or nodeid in self.finished or not isinstance(scope, str)
                    or not scope or len(scope) > 160
                    or not isinstance(completed, int)
                    or not isinstance(total, int)
                    or total < 1 or total > _MAX_DOMAIN_PROGRESS_TOTAL
                    or completed < 1 or completed > total):
                self._fail("invalid/out-of-order domain_progress")
                return
            if previous is None:
                per_node = sum(1 for k in self.domain_progress if k[0] == nodeid)
                if per_node >= _MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE:
                    self._fail(
                        f"one test opened more than "
                        f"{_MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE} distinct "
                        f"domain-progress scopes ({nodeid})")
                    return
                # Bounded by what this session actually COLLECTED, never by a
                # flat number: a selection is allowed to be large.
                ceiling = max(
                    _MAX_DOMAIN_PROGRESS_SCOPES_FLOOR,
                    len(self.items) * _MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE)
                if len(self.domain_progress) >= ceiling:
                    self._fail("domain progress scope resource limit exceeded")
                    return
            if ((previous is None and completed != 1)
                    or (previous is not None
                        and (total != previous[1]
                             or completed != previous[0] + 1))):
                self._fail("non-monotonic domain_progress")
                return
            self.domain_progress[key] = (completed, total)
        elif event == "collection_only_finish":
            count = record.get("selected_items")
            if (not self.collect_only or self.stage != "running" or self.finished
                    or not isinstance(count, int)
                    or self.declared_items is None
                    or count != self.declared_items):
                self._fail("collect-only terminal count/state mismatch")
                return
            self.stage = "collection_only_finished"
        elif event == "test_finish":
            nodeid = record.get("nodeid")
            if (self.collect_only or self.stage != "running"
                    or nodeid not in self.items
                    or nodeid in self.finished):
                self._fail("unknown/duplicate/out-of-order test_finish")
                return
            self.finished.add(nodeid)
        elif event == "session_finish":
            expected_stage = (
                "collection_only_finished" if self.collect_only else "running")
            if (self.stage != expected_stage
                    or not isinstance(
                    record.get("exitstatus"), int)
                    or self.declared_items is None):
                self._fail("out-of-order session_finish")
                return
            complete_enough = (
                len(self.finished) <= self.declared_items
                if self.partial_session
                else len(self.finished) == self.declared_items)
            if not self.collect_only and not complete_enough:
                self._fail(
                    "session finished before every selected item completed "
                    f"({len(self.finished)}/{self.declared_items})")
                return
            self.stage = "finished"

        self.seq = seq
        self.last_ns = stamp
        self.score += 1

    def _accept_collect_scan(self, scanned) -> None:
        """THE PHASE THAT COSTS THE TIME, MADE OBSERVABLE.

        Before this clause the FSM's first event after `session_start` was
        `collect_report`, which pytest does not reach until the whole path
        scan is done -- MEASURED, 57 of 61 s on a 120-file selection, and past
        any flat grace at landing width.  The supervisor then killed a process
        that was scanning thousands of paths a second and called it a stall,
        which is the one thing a progress-stall watchdog must never do.

        EXACT `+STRIDE` TRANSITIONS, exactly as `domain_progress` below.  A
        stuck session cannot hold its grace open: to emit the next value it
        must really scan another STRIDE paths.  A duplicate, a gap or a jump
        is a refusal, not a slower clock.
        """
        if (self.stage != "collecting" or not isinstance(scanned, int)
                or isinstance(scanned, bool)
                or scanned != self.collect_scanned + COLLECT_SCAN_STRIDE):
            self._fail("duplicate/out-of-order collect_scan")
            return
        if scanned > self.collect_scan_ceiling:
            self._fail(
                f"collect_scan exceeded the scan ceiling "
                f"({scanned} > {self.collect_scan_ceiling})")
            return
        self.collect_scanned = scanned

    def sample(self) -> int:
        """Return a monotonic score; invalid bytes freeze it until refusal."""
        if self.error:
            return self.score
        try:
            current = os.stat(self.path)
            held = os.fstat(self.file.fileno())
        except OSError as exc:
            self._fail(f"sidecar unavailable: {exc}")
            return self.score
        if ((current.st_dev, current.st_ino) != self.identity
                or (held.st_dev, held.st_ino) != self.identity):
            self._fail("sidecar inode changed")
            return self.score
        if held.st_size < self.offset or held.st_size > _MAX_PROGRESS_BYTES:
            self._fail("sidecar truncated or resource limit exceeded")
            return self.score
        try:
            self.file.seek(self.offset)
            chunk = self.file.read(held.st_size - self.offset)
        except OSError as exc:
            self._fail(f"sidecar read failed: {exc}")
            return self.score
        self.offset += len(chunk)
        data = self.tail + chunk
        lines = data.split(b"\n")
        self.tail = lines.pop()
        if len(self.tail) > _MAX_PROGRESS_LINE:
            self._fail("partial event exceeds line limit")
            return self.score
        for raw in lines:
            if not raw or len(raw) > _MAX_PROGRESS_LINE:
                self._fail("empty/oversized event")
                break
            try:
                record = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_reject_json_pairs,
                    parse_constant=_reject_json_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self._fail("malformed event")
                break
            self._accept(record)
            if self.error:
                break
        return self.score

    def complete(self) -> Tuple[bool, str]:
        self.sample()
        if not self.error and self.tail:
            self._fail("truncated final event")
        if not self.error and self.stage != "finished":
            self._fail(f"terminal event missing (stage={self.stage})")
        if self.error:
            return False, self.error
        return True, ""


class _ProgressStreamSet:
    """Validate one protocol instance per emitting process, then join them.

    WHY A SET AND NOT A SMARTER VALIDATOR.  Every clause in
    ``_SemanticProgressProbe`` -- ``seq`` strictly ``+1``, ``monotonic_ns``
    strictly increasing, the initial->collecting->running->finished stage
    machine, the per-event resource ceilings -- is a statement about ONE
    interpreter.  A parallel pytest session does not break any of them; it
    breaks the assumption that one FILE carries one interpreter.  Giving each
    process its own file restores that assumption, so the validator is reused
    unchanged rather than taught to demultiplex.

    WHAT THIS CLASS OWNS, AND ONLY THIS.
      * ADMISSION -- which files in the parent-owned directory are streams of
        THIS launch at all.  The pid clause inside the probe still says "every
        record in this stream came from the one process that owns it"; this
        class says which processes this launch owns.  Measured on pytest-xdist
        3.8.0: a ``-n N`` worker is a DIRECT child of the launched process, so
        the test is local and race-free.
      * THE SESSION JOIN -- "every selected item finished", which no single
        worker can assert because each runs only its share.  The assertion is
        re-sited here, not relaxed: it is what makes a ``--maxfail`` prefix a
        NORECORD instead of a complete failure set.

    Captured output and CPU activity are still not progress: the score is the
    sum of per-stream scores, so it advances only when some process completed
    a validated lifecycle event, and freezes when every process stops.
    """

    _MAIN_RE = re.compile(r"\Am\.(\d{1,9})\.(\d{1,9})\.jsonl\Z")
    _WORKER_RE = re.compile(
        r"\Aw\.([A-Za-z0-9_]{1,32})\.(\d{1,9})\.(\d{1,9})\.jsonl\Z")

    def __init__(self, directory: Path, nonce: str, pid_fn, *,
                 collect_only: bool = False,
                 require_runtime_identity: bool = False,
                 collect_scan_ceiling: int = _COLLECT_SCAN_FLOOR):
        # Forwarded UNCHANGED to each per-process probe below. This class
        # demultiplexes streams; it does not relax any clause the probe
        # enforces, so every option the probe takes must reach it.
        self._collect_only = collect_only
        self._require_runtime_identity = require_runtime_identity
        self._collect_scan_ceiling = collect_scan_ceiling
        self.directory = directory
        self.nonce = nonce
        self.pid_fn = pid_fn
        self.dir_fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
        st = os.fstat(self.dir_fd)
        self.identity = (st.st_dev, st.st_ino)
        self.streams: Dict[str, _SemanticProgressProbe] = {}
        self.kinds: Dict[str, str] = {}
        self.error = ""
        self.score = 0

    # THE READ SIDE OF THE JOIN.  `_HermeticProgressRelay.observe` is written
    # against ONE interpreter's probe: it reads `declared_items`, `item_order`,
    # `finished` and `domain_progress`.  Substituting this set for that probe
    # without these four accessors raised AttributeError inside the watchdog
    # sample, which the relay never sees as its own refusal — the arm simply
    # died with no terminal progress record and the hermetic runner reported
    # "candidate ended without the exact semantic terminal record".
    #
    # THE JOIN IS CONSERVATIVE, NEVER OPTIMISTIC.  `declared_items` is the
    # relay's own gate: it stays None (relay silent) until EVERY admitted
    # stream has declared the same collected selection in the same order, so a
    # half-collected or disagreeing session cannot make the relay compute a
    # denominator from a partial view.  `complete()` below is unchanged and is
    # still the only thing that decides whether the session finished.
    def _declared_streams(self) -> Optional[List["_SemanticProgressProbe"]]:
        probes = list(self.streams.values())
        if self.error or not probes:
            return None
        first = probes[0]
        if first.declared_items is None:
            return None
        for probe in probes[1:]:
            if (probe.declared_items != first.declared_items
                    or probe.item_order != first.item_order):
                return None
        return probes

    @property
    def declared_items(self) -> Optional[int]:
        probes = self._declared_streams()
        return None if probes is None else probes[0].declared_items

    @property
    def item_order(self) -> List[str]:
        probes = self._declared_streams()
        return [] if probes is None else list(probes[0].item_order)

    @property
    def finished(self) -> Set[str]:
        # Each worker runs only its share; the set of items this SESSION has
        # finished is their union.  A single-main session degenerates to that
        # main's own set.
        out: Set[str] = set()
        for probe in self.streams.values():
            out |= probe.finished
        return out

    @property
    def domain_progress(self) -> Dict[Tuple[str, str], Tuple[int, int]]:
        # A nested domain belongs to whichever process ran that item, so at
        # most one stream carries a given key in a distributed session.  Keep
        # the furthest-advanced observation if two ever report the same key;
        # the enclosing relay only ever compares it forward.
        merged: Dict[Tuple[str, str], Tuple[int, int]] = {}
        for probe in self.streams.values():
            for key, value in probe.domain_progress.items():
                current = merged.get(key)
                if current is None or value[0] > current[0]:
                    merged[key] = value
        return merged

    def close(self) -> None:
        for probe in self.streams.values():
            try:
                probe.close()
            except OSError:
                pass
        try:
            os.close(self.dir_fd)
        except OSError:
            pass

    def _fail(self, reason: str) -> None:
        if not self.error:
            self.error = reason

    def _admit(self, name: str, launched: Optional[int]) -> None:
        """Open one new stream, or refuse the whole set."""
        worker = self._WORKER_RE.match(name)
        main = None if worker else self._MAIN_RE.match(name)
        if not worker and not main:
            self._fail(f"unexpected file in progress directory: {name!r}")
            return
        if launched is None:
            # The probe's own pid clause refuses anything written before the
            # child exists; keep that property for the directory too, so a
            # pre-launch writer cannot seed a stream.
            self._fail(f"progress stream {name!r} appeared before launch")
            return
        if worker:
            pid = int(worker.group(2))
            claimed_ppid = int(worker.group(3))
            if claimed_ppid != launched:
                self._fail(f"foreign progress stream {name!r}: parent "
                           f"{claimed_ppid} is not the launched process "
                           f"{launched}")
                return
        else:
            pid = int(main.group(1))
            if pid != launched:
                self._fail(f"foreign progress stream {name!r}: pid {pid} is "
                           f"not the launched process {launched}")
                return
        path = self.directory / name
        try:
            lst = os.lstat(path)
        except OSError as exc:
            self._fail(f"progress stream {name!r} unavailable: {exc}")
            return
        if not stat.S_ISREG(lst.st_mode):
            self._fail(f"progress stream {name!r} is not a regular file")
            return
        try:
            probe = _SemanticProgressProbe(
                path, self.nonce, (lambda captured: lambda: captured)(pid),
                partial_session=worker is not None,
                collect_scan_ceiling=self._collect_scan_ceiling,
                collect_only=self._collect_only,
                require_runtime_identity=self._require_runtime_identity)
        except OSError as exc:
            self._fail(f"progress stream {name!r} unavailable: {exc}")
            return
        self.streams[name] = probe
        self.kinds[name] = "worker" if worker else "main"

    def _scan(self) -> None:
        try:
            current = os.stat(self.directory)
            held = os.fstat(self.dir_fd)
            # REWIND FIRST.  `os.listdir(fd)` is `fdopendir(dup(fd))`, and a
            # dup SHARES the file offset, so the second listing of the same
            # directory fd resumes where the first one stopped -- at
            # end-of-directory.  On ext4 the kernel re-seeds the readdir cursor
            # and the defect is invisible; on TMPFS it is not, and the hermetic
            # candidate profile mounts `/tmp` as a tmpfs.
            #
            # MEASURED inside that container: `os.listdir(self.dir_fd)` -> []
            # at the same instant `os.listdir(self.directory)` ->
            # ['m.7.1.jsonl'].  Every re-list ran ONE CALL BEHIND, so a pytest
            # arm that finished inside two poll intervals had its stream
            # admitted only by `complete()` -- after the last observer sample.
            # The hermetic relay therefore emitted no checkpoint and no
            # terminal record, `hermetic_candidate_runner` refused with
            # "candidate ended without the exact semantic terminal record",
            # no B1 receipt was written, and `gatekeeper-verify-merge.sh`
            # answered rc=2 to a known-GOOD branch and a known-BAD one alike:
            # 22 reds in `test_landing_merge_verdict`, and a merge gate that
            # could not discriminate.  A green fast arm and a hung arm are not
            # allowed to look the same.
            #
            # The fd still pins the directory INODE (the identity clause
            # below), so rewinding relaxes no property this class enforces.
            os.lseek(self.dir_fd, 0, os.SEEK_SET)
            names = sorted(os.listdir(self.dir_fd))
        except OSError as exc:
            self._fail(f"progress directory unavailable: {exc}")
            return
        if ((current.st_dev, current.st_ino) != self.identity
                or (held.st_dev, held.st_ino) != self.identity):
            self._fail("progress directory inode changed")
            return
        launched = self.pid_fn()
        launched = launched if isinstance(launched, int) else None
        for name in names:
            if name in self.streams:
                continue
            if len(self.streams) >= _MAX_PROGRESS_STREAMS:
                self._fail("progress stream resource limit exceeded")
                return
            self._admit(name, launched)
            if self.error:
                return

    def sample(self) -> int:
        """Sum of validated per-process progress; frozen once anything fails."""
        if self.error:
            return self.score
        self._scan()
        if self.error:
            return self.score
        total = 0
        total_bytes = 0
        for name, probe in self.streams.items():
            total += probe.sample()
            if probe.error:
                self._fail(f"{name}: {probe.error}")
                return self.score
            total_bytes += probe.offset
        budget = min(_MAX_PROGRESS_BYTES * max(1, len(self.streams)),
                     _MAX_PROGRESS_TOTAL_BYTES)
        if total_bytes > budget:
            self._fail("progress streams exceeded the total byte limit")
            return self.score
        self.score = total
        return self.score

    def complete(self) -> Tuple[bool, str]:
        self.sample()
        for name, probe in self.streams.items():
            ok, why = probe.complete()
            if not ok:
                self._fail(f"{name}: {why}")
        if self.error:
            return False, self.error
        workers = [p for n, p in self.streams.items()
                   if self.kinds[n] == "worker"]
        mains = [p for n, p in self.streams.items()
                 if self.kinds[n] == "main"]
        if not self.streams:
            return False, "no pytest progress stream was produced"
        if workers and mains:
            return False, ("conflicting progress stream shapes: "
                           f"{len(mains)} main and {len(workers)} worker")
        if mains:
            if len(mains) != 1:
                return False, f"{len(mains)} main progress streams, expected 1"
            # A single-process session already asserted finished == declared
            # inside its own session_finish clause.
            return True, ""
        # SESSION JOIN. Each worker collected the same selection and finished
        # only its share; the session is complete only if their shares cover
        # the whole declared selection exactly once over.
        declared = {p.declared_items for p in workers}
        if len(declared) != 1 or None in declared:
            return False, ("workers disagree on the selected item count "
                           f"{sorted(d for d in declared if d is not None)}")
        expected = declared.pop()
        items = workers[0].items
        for probe in workers[1:]:
            if probe.items != items:
                return False, "workers disagree on the collected item set"
        finished: Set[str] = set()
        for probe in workers:
            finished |= probe.finished
        if not finished <= items:
            return False, "a worker finished an item nobody collected"
        if len(finished) != expected:
            return False, ("session finished before every selected item "
                           f"completed ({len(finished)}/{expected})")
        return True, ""

    def item_counts(self) -> Tuple[Optional[int], Optional[int]]:
        """(items finished, items the session declared), or (None, None).

        The two numbers the SESSION JOIN above compares, exposed so a caller can
        say WHY a record is incomplete from the supervisor's OWN state instead
        of searching the child's output for a marker the child may legitimately
        print.  MEASURED, why that matters: the driver's own test file prints
        `WATCHDOG_STALLED:` inside its assertion dumps, and a substring
        classifier therefore reported a 44-second run as a 300 s stall, twice.

        (None, None) whenever the shape is anything other than one main stream
        or a consistent set of workers -- an unknown count must never be read as
        a known one.
        """
        mains = [pr for n, pr in self.streams.items()
                 if self.kinds[n] == "main"]
        workers = [pr for n, pr in self.streams.items()
                   if self.kinds[n] == "worker"]
        if len(mains) == 1 and not workers:
            return len(mains[0].finished), mains[0].declared_items
        if workers and not mains:
            declared = {pr.declared_items for pr in workers}
            if len(declared) == 1 and None not in declared:
                finished: Set[str] = set()
                for probe in workers:
                    finished |= probe.finished
                return len(finished), declared.pop()
        return None, None


def read_selection(path: Path) -> List[str]:
    return [l.strip() for l in
            path.read_text(errors="replace").splitlines() if l.strip()]


def _file_identity(path: str, cwd: Optional[str]) -> Optional[str]:
    """Return one lexical/real file identity in the pytest working tree.

    Pytest's xunit1 ``file`` attribute is normally relative to its cwd while a
    selector is also allowed to emit an absolute path.  Comparing raw strings
    would therefore call the same file missing (or allow the same file twice)
    solely because the two producers chose different spellings.  Resolution is
    used only for identity; pytest still receives the selector's original
    argument verbatim.
    """
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate if cwd else Path.cwd() / candidate
        return os.path.normcase(str(candidate.resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        return None


def _selection_identity_problem(selection: Sequence[str],
                                cwd: Optional[str]) -> str:
    """Reject an ambiguous selector denominator before launching pytest."""
    identities: Dict[str, str] = {}
    for raw in selection:
        identity = _file_identity(raw, cwd)
        if identity is None:
            return f"selected path has no stable identity: {raw!r}"
        previous = identities.get(identity)
        if previous is not None:
            return ("selection names the same file more than once: "
                    f"{previous!r}, {raw!r}")
        identities[identity] = raw
    return ""


def _aggregate_coverage(suites: Sequence[ET.Element],
                       selection: Sequence[str],
                       cwd: Optional[str],
                       ) -> Tuple[str, List[str], List[str]]:
    """(identity error or "", selected-but-absent, reported-but-unselected).

    ONE definition of "did every selected file contribute a testcase", so the
    human-facing refusal below and any caller that needs the COUNTS cannot
    drift apart.  When the first element is non-empty the two lists are empty
    and mean nothing: identity could not be established, which is never a pass.
    """
    selected: Dict[str, str] = {}
    for raw in selection:
        identity = _file_identity(raw, cwd)
        if identity is None:
            return f"selected path has no stable identity: {raw!r}", [], []
        if identity in selected:
            return ("selection names the same file more than once: "
                    f"{selected[identity]!r}, {raw!r}"), [], []
        selected[identity] = raw

    reported: Dict[str, str] = {}
    for suite in suites:
        for testcase in suite.iter("testcase"):
            raw = testcase.get("file")
            if not isinstance(raw, str) or not raw:
                return ("aggregate JUnit contains a testcase with no file "
                        "identity"), [], []
            identity = _file_identity(raw, cwd)
            if identity is None:
                return ("aggregate JUnit testcase has no stable file identity: "
                        f"{raw!r}"), [], []
            reported[identity] = raw

    missing = [selected[key] for key in sorted(set(selected) - set(reported))]
    extra = [reported[key] for key in sorted(set(reported) - set(selected))]
    return "", missing, extra


def _aggregate_coverage_problem(suites: Sequence[ET.Element],
                                selection: Sequence[str],
                                cwd: Optional[str]) -> str:
    """Prove every selected file contributed at least one aggregate testcase.

    A normal rc=0 plus a valid JUnit is insufficient: pytest is also happy when
    one selected file collects zero items.  That shape used to disappear from
    the report and let a two-file denominator look like a one-file green run.
    Extra files are equally invalid because they answer a different selection.
    """
    problem, missing, extra = _aggregate_coverage(suites, selection, cwd)
    if problem:
        return problem
    if missing or extra:
        return ("aggregate JUnit does not exactly cover the selected files "
                f"(missing={missing}, extra={extra})")
    return ""


def _count(suite: ET.Element) -> Tuple[int, int]:
    """(test cases, red cases) in one parsed per-file report."""
    cases = 0
    red = 0
    for tc in suite.iter("testcase"):
        cases += 1
        for child in tc:
            if child.tag.rsplit("}", 1)[-1] in _RED_TAGS:
                red += 1
                break
    return cases, red


def _load_suites(path: Path) -> Optional[List[ET.Element]]:
    """The `<testsuite>` elements of one per-file report, or None.

    None means NO RECORD and is returned for a missing file, an empty file, an
    unparseable one and one carrying no `<testsuite>` at all. All four are "I
    could not look": a half-written XML left behind by a killed process is not a
    partial answer, it is no answer, and reading it as one is how a truncated
    record becomes a clean one.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError:
        return None
    tag = root.tag.rsplit("}", 1)[-1]
    suites = [root] if tag == "testsuite" else list(root.iter("testsuite"))
    return suites or None


def _enable_subreaper() -> bool:
    """Make escaped grandchildren adopt to this driver instead of PID 1.

    A pytest fixture can call ``start_new_session=True`` and leave the original
    process group. Process-group cleanup alone then leaks a daemon into the next
    arm. Linux's child-subreaper contract keeps that daemon attributable to this
    driver even after its immediate parent exits.
    """
    if os.name != "posix" or not Path("/proc").is_dir():
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (AttributeError, OSError):
        return False


def _proc_snapshot() -> Dict[int, Tuple[int, int, int]]:
    """pid -> (ppid, starttime, cpu_ticks), from one coherent-ish /proc pass."""
    return _proc_snapshot_checked()[0]


def _proc_snapshot_checked() -> Tuple[Dict[int, Tuple[int, int, int]], bool]:
    """Return a process snapshot and whether the census was trustworthy.

    A process disappearing between ``iterdir`` and ``read_text`` is a normal
    race.  Any other unreadable/malformed live entry means the supervisor
    cannot prove that its descendant set is empty and must fail closed.
    """
    out: Dict[int, Tuple[int, int, int]] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return {}, False
    complete = True
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(errors="replace")
            fields = raw[raw.rfind(")") + 2:].split()
            # fields starts at proc stat field 3 (state).
            out[int(entry.name)] = (
                int(fields[1]), int(fields[19]),
                int(fields[11]) + int(fields[12]))
        except FileNotFoundError:
            continue
        except (OSError, ValueError, IndexError):
            # Do not turn a permission/parsing failure for a still-live PID
            # into proof that it does not exist.  A vanished entry is benign.
            try:
                if entry.exists():
                    complete = False
            except OSError:
                complete = False
    return out, complete


def _descendants(snapshot: Dict[int, Tuple[int, int, int]], root: int) -> Set[int]:
    found: Set[int] = set()
    frontier = {root}
    while frontier:
        children = {pid for pid, (ppid, _start, _cpu) in snapshot.items()
                    if ppid in frontier and pid not in found}
        found.update(children)
        frontier = children
    return found


def _job_processes(root_pid: int,
                   baseline: Set[Tuple[int, int]]) -> Dict[int, int]:
    """Processes attributable to this one pytest launch, including escapees."""
    return _job_processes_checked(root_pid, baseline)[0]


def _job_processes_checked(
        root_pid: int,
        baseline: Set[Tuple[int, int]]) -> Tuple[Dict[int, int], bool]:
    """Return attributable pid/starttime identities plus census integrity."""
    snap, complete = _proc_snapshot_checked()
    pids = _descendants(snap, root_pid)
    if root_pid in snap:
        pids.add(root_pid)
    # A double-forked/session-detached daemon is reparented to this subreaper,
    # so it is no longer below root_pid. Anything newly below the driver is part
    # of the current (sequential) launch; baseline identities are excluded.
    for pid in _descendants(snap, os.getpid()):
        ident = (pid, snap[pid][1])
        if ident not in baseline:
            pids.add(pid)
    return ({pid: snap[pid][1] for pid in pids if pid in snap}, complete)


def _signal_identities(identities: Dict[int, int], sig: int) -> None:
    """Signal only the exact pid/starttime identities originally observed."""
    snap = _proc_snapshot()
    for pid, starttime in identities.items():
        if pid == os.getpid() or pid not in snap or snap[pid][1] != starttime:
            continue
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _reap_adopted() -> None:
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


@dataclass(frozen=True)
class CleanupResult:
    observed: Set[int]
    survivors: Set[int]
    census_ok: bool


def _open_identity_pidfd(identity: Tuple[int, int]
                         ) -> Tuple[Optional[int], bool]:
    """Open a stable handle and prove it still names ``pid/starttime``.

    A process that vanished before the handle opened is already clean.  A
    census error or PID reuse is not evidence of cleanliness and makes the
    returned completeness flag false.
    """
    pid, starttime = identity
    before_snapshot, before_complete = _proc_snapshot_checked()
    if not before_complete:
        return None, False
    before = before_snapshot.get(pid)
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
    after_snapshot, after_complete = _proc_snapshot_checked()
    if not after_complete:
        os.close(pidfd)
        return None, False
    after = after_snapshot.get(pid)
    if after is None:
        os.close(pidfd)
        return None, True
    if after[1] != starttime:
        os.close(pidfd)
        return None, False
    return pidfd, True


def _open_pidfds(identities: Dict[int, int]
                  ) -> Tuple[Dict[int, Tuple[int, int]], bool]:
    handles: Dict[int, Tuple[int, int]] = {}
    complete = True
    for identity in sorted(identities.items()):
        pidfd, ok = _open_identity_pidfd(identity)
        complete = complete and ok
        if pidfd is not None:
            handles[pidfd] = identity
    return handles, complete


def _signal_pidfds(handles: Sequence[int], sig: int) -> bool:
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


def _wait_pidfds_until(
        handles: Dict[int, Tuple[int, int]], deadline: float
        ) -> Dict[int, Tuple[int, int]]:
    """Give SIGTERM a policy grace; return handles still executing."""
    remaining = dict(handles)
    poller = select.poll()
    for pidfd in remaining:
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while remaining:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        for pidfd, _event in poller.poll(max(1, int(left * 1000))):
            if pidfd in remaining:
                poller.unregister(pidfd)
                remaining.pop(pidfd, None)
    return remaining


def _wait_pidfds(handles: Dict[int, Tuple[int, int]]) -> None:
    """Wait on kernel exit events with no elapsed-runtime cutoff."""
    remaining = set(handles)
    poller = select.poll()
    for pidfd in remaining:
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while remaining:
        for pidfd, _event in poller.poll(_REAPER_POLL_MS):
            if pidfd in remaining:
                poller.unregister(pidfd)
                remaining.remove(pidfd)


def _close_pidfds(handles: Sequence[int]) -> None:
    for pidfd in handles:
        try:
            os.close(pidfd)
        except OSError:
            pass


def _cleanup_job_owned(root_pid: int, baseline: Set[Tuple[int, int]],
                       *, term_grace_s: float) -> CleanupResult:
    """Terminate descendants and retain ownership through exact final zero.

    The TERM grace is shutdown policy, not a runtime verdict.  After SIGKILL,
    this subreaper waits on pidfd exit events without a total elapsed bound,
    reaps adopted children, and repeats complete censuses until two successive
    reads prove that no attributable identity remains.  In particular, a slow
    or D-state descendant cannot outlive a returned arm as an unowned process.
    """
    identities, census_ok = _job_processes_checked(root_pid, baseline)
    observed = set(identities)
    term_handles, open_ok = _open_pidfds(identities)
    census_ok = census_ok and open_ok
    census_ok = _signal_pidfds(
        list(term_handles), signal.SIGTERM) and census_ok
    remaining = _wait_pidfds_until(
        term_handles, time.monotonic() + term_grace_s)
    census_ok = _signal_pidfds(
        list(remaining), signal.SIGKILL) and census_ok
    kill_pending = _wait_pidfds_until(
        remaining, time.monotonic() + _KILL_CONFIRM_GRACE_S)
    if kill_pending:
        # No duration guess can prove when a SIGKILL-pending D-state task will
        # leave the kernel.  The driver remains its subreaper and waits only on
        # stable kernel exit events before it is permitted to return.
        _wait_pidfds(kill_pending)
    _close_pidfds(list(term_handles))
    _reap_adopted()

    # watchdog-exempt: each non-empty wave is killed through stable pidfds and
    # awaited by kernel events; a fixed iteration/time cap would recreate the
    # exact orphan hole this final-zero loop closes.
    while True:
        current, scan_ok = _job_processes_checked(root_pid, baseline)
        census_ok = census_ok and scan_ok
        observed.update(current)
        if not current and scan_ok:
            final, final_ok = _job_processes_checked(root_pid, baseline)
            census_ok = census_ok and final_ok
            observed.update(final)
            if not final and final_ok:
                return CleanupResult(observed, set(), census_ok)
            current = final
        if not current:
            time.sleep(_REAPER_POLL_MS / 1000.0)
            continue
        handles, open_ok = _open_pidfds(current)
        census_ok = census_ok and open_ok
        if not handles:
            time.sleep(_REAPER_POLL_MS / 1000.0)
            continue
        census_ok = _signal_pidfds(
            list(handles), signal.SIGKILL) and census_ok
        kill_pending = _wait_pidfds_until(
            handles, time.monotonic() + _KILL_CONFIRM_GRACE_S)
        if kill_pending:
            _wait_pidfds(kill_pending)
        _close_pidfds(list(handles))
        _reap_adopted()


def _cleanup_job(root_pid: int, baseline: Set[Tuple[int, int]],
                 *, term_grace_s: float = 2.0) -> CleanupResult:
    """Non-reentrant entry to the event-driven owned cleanup."""
    global _CLEANUP_ACTIVE
    if _CLEANUP_ACTIVE:
        raise RuntimeError("owned descendant cleanup is already active")
    _CLEANUP_ACTIVE = True
    try:
        return _cleanup_job_owned(
            root_pid, baseline, term_grace_s=term_grace_s)
    finally:
        _CLEANUP_ACTIVE = False
        _honor_pending_shutdown()


def _block_shutdown_signals() -> Optional[Set[signal.Signals]]:
    if hasattr(signal, "pthread_sigmask"):
        return signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    return None


def _restore_signal_mask(previous: Optional[Set[signal.Signals]]) -> None:
    if previous is not None:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _first_queued_shutdown_signal(fallback: int) -> int:
    """Peek the kernel-delivery order before a Python handler can re-enter."""
    reader = _SHUTDOWN_SIGNAL_READER
    if reader is not None:
        try:
            queued = reader.recv(4096, socket.MSG_PEEK)
        except BlockingIOError:
            queued = b""
        for value in queued:
            if value in (signal.SIGTERM, signal.SIGINT):
                return value
    return int(fallback)


def _drain_shutdown_signal_queue() -> None:
    reader = _SHUTDOWN_SIGNAL_READER
    if reader is None:
        return
    while True:
        try:
            if not reader.recv(4096):
                return
        except BlockingIOError:
            return


def _honor_pending_shutdown() -> None:
    """Exit for the first signal latched during an owned final-zero census."""
    global _IN_SHUTDOWN, _PENDING_SHUTDOWN_SIGNAL
    previous_mask = _block_shutdown_signals()
    if _PENDING_SHUTDOWN_SIGNAL is None or _IN_SHUTDOWN:
        _restore_signal_mask(previous_mask)
        return
    signum = _PENDING_SHUTDOWN_SIGNAL
    _IN_SHUTDOWN = True
    raise SystemExit(128 + signum)


def _shutdown_handler(signum, _frame) -> None:
    """On verifier cancellation, clean the active cross-session process tree."""
    global _IN_SHUTDOWN, _PENDING_SHUTDOWN_SIGNAL
    first_signum = _first_queued_shutdown_signal(signum)
    previous_mask = _block_shutdown_signals()
    if _IN_SHUTDOWN:
        _drain_shutdown_signal_queue()
        _restore_signal_mask(previous_mask)
        return
    if _PENDING_SHUTDOWN_SIGNAL is not None:
        _drain_shutdown_signal_queue()
        _restore_signal_mask(previous_mask)
        return
    _PENDING_SHUTDOWN_SIGNAL = first_signum
    _drain_shutdown_signal_queue()
    if _CLEANUP_ACTIVE:
        _restore_signal_mask(previous_mask)
        return
    _IN_SHUTDOWN = True
    job = _ACTIVE_JOB
    if job is not None:
        _cleanup_job(job[0], job[1])
    # Parallel recovery never calls the process-global supervisor from threads:
    # each file lives in its own supervisor process.  This parent is itself a
    # subreaper, so every worker and any session-detached grandchild is a new
    # descendant relative to the frozen pre-pool baseline.  Root -1 selects no
    # ordinary process but lets `_job_processes_checked` collect exactly that
    # attributable post-baseline set for TERM/KILL/final-zero verification.
    fallback_baseline = _ACTIVE_FALLBACK_BASELINE
    if fallback_baseline is not None:
        _cleanup_job(-1, fallback_baseline)
    raise SystemExit(128 + first_signum)


def _install_shutdown_handlers() -> None:
    global _SHUTDOWN_SIGNAL_READER, _SHUTDOWN_SIGNAL_WRITER
    if (_SHUTDOWN_SIGNAL_READER is None
            and hasattr(signal, "set_wakeup_fd")):
        reader, writer = socket.socketpair()
        reader.setblocking(False)
        writer.setblocking(False)
        try:
            previous = signal.set_wakeup_fd(
                writer.fileno(), warn_on_full_buffer=False)
        except (OSError, ValueError):
            reader.close()
            writer.close()
        else:
            if previous == -1:
                _SHUTDOWN_SIGNAL_READER = reader
                _SHUTDOWN_SIGNAL_WRITER = writer
            else:
                signal.set_wakeup_fd(previous)
                reader.close()
                writer.close()
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)


def _red_node_ids(suites: Sequence[ET.Element]) -> List[str]:
    """`classname::name` for every red testcase, in report order."""
    ids: List[str] = []
    for suite in suites:
        for testcase in suite.iter("testcase"):
            for child in testcase:
                if child.tag.rsplit("}", 1)[-1] in _RED_TAGS:
                    classname = testcase.get("classname") or ""
                    name = testcase.get("name") or ""
                    ids.append(f"{classname}::{name}" if classname else name)
                    break
    return ids


#: THE AGGREGATE ARM'S ABANDON CEILING, DERIVED FROM WHAT WAS SELECTED.
#:
#: THE DEFECT.  The aggregate arm inherited the SAME flat `--maxfail` the
#: per-file arm uses, and a flat bound applied to a whole run gets MORE certain
#: to fire the larger the suite grows -- which is backwards for the one arm
#: whose entire purpose is the cross-file question only a large selection can
#: pose.  MEASURED on the landing tier (2026-08-30, v1.13.1, pinned image): a
#: 175-file selection tripped its bound at 10 reds after 378 of 4361 items and
#: ABANDONED 162 of 175 files, so the tier reported
#:
#:     AGGREGATE_NORECORD: aggregate session stopped at its own DECLARED
#:     FAILURE BOUND ... cross-file/order semantics are UNKNOWN, not clean
#:
#: and no landing of any width could get an answer out of that arm.
#:
#: THE SHAPE OF THE FIX, and it is the same shape as the stall grace above: a
#: RUNAWAY rule is per-unit and FLAT, a CEILING scales with the work.  The
#: per-file arm keeps the caller's flat bound -- one file, N reds, unchanged.
#: The aggregate arm gets `max(FLOOR, selected_files * PER_UNIT)`.  It STILL
#: REFUSES: a genuine runaway, where the reds keep coming file after file,
#: reaches the ceiling and is abandoned exactly as before.  What it no longer
#: does is abandon a selection for having a normal number of standing reds.
#:
#: PER_UNIT is 1.  The measured aggregate carried ~25 items per selected file,
#: so "one red per selected file, on average" is already a suite in trouble and
#: is the right place to stop believing the run.
#:
#: THE FLOOR IS THE CALLER'S OWN BOUND, not a second constant.  A flat floor was
#: written here first and it was wrong in the one direction that matters: it
#: RAISED a bound the caller had deliberately set small, so a 2-file selection
#: asking for `--maxfail=2` stopped being truncated at all.  Two tests in this
#: tree caught it. The ceiling may only ever move a bound UP toward the size of
#: the work, and never past what a small selection asked for.
_AGGREGATE_FAILURE_BOUND_PER_UNIT = 1


def aggregate_failure_bound(pytest_argv: Sequence[str],
                            selected: int) -> Optional[int]:
    """The bound the AGGREGATE arm actually runs under.

    THIS IS A ONE-WAY RATCHET AND THE DIRECTION IS THE WHOLE POINT.  Read the
    `max` below as a rule, not as arithmetic:

        it may RAISE a bound toward the size of the work    -- always allowed
        it may LOWER a bound the caller asked for           -- NEVER

    A caller that declared no bound acquires none here (`None` in, `None`
    out): this function widens a refusal threshold, it never invents one.

    THE ASYMMETRY WAS LEARNED, NOT ASSUMED.  A flat floor was written here
    first -- `max(declared, FLOOR, selected * PER_UNIT)` with FLOOR=50 -- and
    it was wrong in exactly the forbidden direction: it RAISED the deliberate
    `--maxfail=2` of a 2-file selection to 50, so that selection stopped being
    truncated at all and two tests in this tree went red catching it.  A
    ceiling that scales with the work must still stop at what a small
    selection asked for, and `declared` is therefore the floor -- there is no
    second constant, because a second constant is what got this wrong.

    `test_the_bound_is_derived_from_the_selection_and_only_ever_rises` pins
    both directions; this comment exists so the next reader does not have to
    rediscover the rule by breaking it.
    """
    declared = _declared_failure_bound(pytest_argv)
    if declared is None:
        return None
    # `max`, and never `min`: see the ratchet above.
    return max(declared, int(selected) * _AGGREGATE_FAILURE_BOUND_PER_UNIT)


def _with_failure_bound(pytest_argv: Sequence[str],
                        bound: Optional[int]) -> List[str]:
    """`pytest_argv` with every failure-bound flag replaced by `bound`.

    Every spelling `_declared_failure_bound` READS is removed here, or the
    lowest of the two would silently win and the ceiling would be decorative.
    """
    argv = list(pytest_argv)
    out: List[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--maxfail" and index + 1 < len(argv):
            index += 2
            continue
        if arg.startswith("--maxfail=") or arg == "--exitfirst":
            index += 1
            continue
        if (len(arg) > 1 and arg[0] == "-" and arg[1] != "-"
                and "x" in arg[1:]):
            stripped = "-" + arg[1:].replace("x", "")
            if stripped != "-":
                out.append(stripped)
            index += 1
            continue
        out.append(arg)
        index += 1
    if bound is not None:
        out.append(f"--maxfail={bound}")
    return out


def _declared_failure_bound(pytest_argv: Sequence[str]) -> Optional[int]:
    """The failure bound THIS driver was told to hand pytest, or None.

    Read from the driver's OWN argument vector.  The child's output is not
    consulted: pytest prints `stopping after N failures`, but so can any test
    that quotes it, and a classifier that greps the subject for its own markers
    is the defect this function exists to avoid repeating.
    """
    argv = list(pytest_argv)
    bound: Optional[int] = None

    def _bind(value: int) -> None:
        nonlocal bound
        if value >= 1:
            bound = value if bound is None else min(bound, value)

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--maxfail" and index + 1 < len(argv):
            try:
                _bind(int(argv[index + 1]))
            except ValueError:
                pass
            index += 2
            continue
        if arg.startswith("--maxfail="):
            try:
                _bind(int(arg.split("=", 1)[1]))
            except ValueError:
                pass
        elif arg == "--exitfirst" or (
                len(arg) > 1 and arg[0] == "-" and arg[1] != "-"
                and "x" in arg[1:]):
            _bind(1)
        index += 1
    return bound


def _maxfail_truncation(bound: Optional[int], rc: Optional[int], red: int,
                        sink: Dict[str, object], covered: int, total: int,
                        extra: Sequence[str]) -> Optional[str]:
    """Name a session that stopped at its OWN declared failure bound.

    WHY THIS IS NOT A RELAXATION.  The verdict does not move: a truncated
    session is still an absolute refusal, because the failures it recorded are a
    PREFIX of the failure set and a prefix cannot be differenced against another
    arm.  What moves is what the reader is told.  MEASURED at 288dc9fc8 on a
    116-file selection, the landing gate said `aggregate JUnit does not exactly
    cover the selected files (missing=[108 paths])` -- "cross-file/order
    semantics are UNKNOWN" -- when the truth was "ten tests in file 8 of 116
    failed and pytest stopped there, as `--maxfail=10` told it to".  One reading
    sends the reader to the harness; the other sends them to ten named tests.
    The condition was reproduced byte-identically in five landing rounds and
    nobody chased it, which is what an unknowable-looking refusal costs.

    EVERY CLAUSE IS SUPERVISOR-SIDE and every one must hold, so an unknown is
    never dressed up as a known:
      * the bound is the one THIS driver declared (`_declared_failure_bound`);
      * the process exited normally (`natural_exit`), so the stall lease did not
        fire -- a genuine hang stays `AGGREGATE_NORECORD`;
      * nothing leaked and the descendant census closed;
      * the lifecycle join reported fewer finished items than the session
        declared, which is what a truncation IS;
      * pytest's status is exactly 1 (ran, had failures) and the JUnit carries
        exactly `bound` red cases -- one fewer or one more is a different event;
      * no EXTRA file was reported, because an unselected file in the report
        means the run answered a different question and the bound explains none
        of it.
    """
    if bound is None or bound < 1 or rc != 1 or red != bound or extra:
        return None
    if (sink.get("natural_exit") is not True
            or sink.get("leaked") is not False
            or sink.get("cleanup_ok") is not True
            or sink.get("protocol_complete") is not False):
        return None
    finished = sink.get("items_finished")
    declared = sink.get("items_declared")
    if not isinstance(finished, int) or not isinstance(declared, int):
        return None
    if finished >= declared:
        return None
    return (f"{bound} failures reached at file {covered}/{total}, "
            f"{finished}/{declared} items — the recorded failures are a "
            "PREFIX of the failure set, not the failure set; REFUSED")


def _sink_protocol_error(sink: Dict[str, object]) -> str:
    """The lifecycle join's OWN complaint, or "" when it did not make one."""
    if sink.get("protocol_complete") is not False:
        return ""
    detail = sink.get("protocol_error")
    return detail if isinstance(detail, str) and detail else ""


def _norecord_reason(rc: Optional[int], out: str, incomplete: bool,
                     stall_after: float, *, stalled: bool,
                     protocol_error: str) -> str:
    """Explain UNKNOWN without calling every instrumentation refusal a stall.

    ``stalled`` IS THE SUPERVISOR'S OWN VERDICT -- ``_watchdog``'s
    ``outcome == "stalled"``, carried here through the outcome sink -- and it is a
    REQUIRED argument because what it replaces was a substring test on the CHILD'S
    OUTPUT, and the child is entitled to print anything at all.

    MEASURED on clean origin/main 49d2b3328, with this driver unchanged,
    ``programs/tests/test_pytest_per_file_junit.py`` driven one file at a time
    exactly as the landing gate drives it:

        10 failed, 11 passed in 24.13s
        PROGRESS_PROTOCOL_INCOMPLETE: m.16.1.jsonl: session finished before every
                                      selected item completed (21/72)
        AGGREGATE_NORECORD  STALLED after 300 s with no validated pytest lifecycle
                            progress

    A 24-second run, a natural exit, truncated by its own ``--maxfail`` bound --
    reported as a 300-second hang.  The whole 440-line buffer held exactly ONE
    ``WATCHDOG_STALLED:`` and it sat inside a pytest assertion dump belonging to
    that file's own test OF THE STALL DETECTOR.  The watchdog never fired.  The
    label sent two readers hunting a hang that does not exist and hid the real
    cause, which was a failure bound.

    ``test_protocol_refusal_is_not_mislabeled_as_a_stall`` existed throughout and
    passed throughout, because it only ever exercised the half where the marker is
    ABSENT.  The half that matters is pinned now.
    """
    if stalled:
        return (f"STALLED after {stall_after:g} s with no validated pytest "
                "lifecycle progress")
    # THE DETAIL COMES FROM THE PROBE, NOT FROM THE BUFFER, for the same reason
    # `stalled` does. MEASURED on this file with only the `stalled` half repaired:
    # the per-file arm reported "no pytest progress stream was produced" for a
    # session whose OWN probe had just said "session finished before every selected
    # item completed (29/83)" -- because the first `PROGRESS_PROTOCOL_INCOMPLETE:`
    # in the buffer belonged to a NESTED driver run this file spawns as its
    # subject. An empty `protocol_error` means the supervisor did not supply one,
    # which falls through to the liveness sentence below rather than guessing.
    if protocol_error:
        return f"pytest progress protocol incomplete: {protocol_error}"
    if "DESCENDANT_CLEANUP_INCOMPLETE:" in out:
        return "pytest descendant cleanup could not prove a final empty census"
    if "LIVE_DESCENDANTS_CLEANED:" in out:
        return "pytest exited with unfinished live descendants"
    if incomplete:
        return "pytest supervision ended without a complete liveness record"
    return f"the session exited rc={rc} without writing a complete junit"


def _run_progress_supervised(
        cmd: Sequence[str], stall_after: float,
        cwd: Optional[str], *,
        progress_relay_path: Optional[Path] = None,
        progress_observer: Optional[
            Callable[["_SemanticProgressProbe"], None]] = None,
        poll_s: Optional[float] = None,
        collect_only: bool = False,
        scan_units: int = 1,
        outcome_sink: Optional[Dict[str, object]] = None,
        ) -> Tuple[Optional[int], str, bool]:
    """Run until natural completion; stop only after semantic events stall.

    ``outcome_sink`` is filled, when supplied, with the supervisor's OWN view of
    how the session ended -- natural exit, leak, cleanup, the lifecycle join and
    its item counts -- so a caller can classify an incomplete record without
    grepping the child's output.  It is left untouched on the early refusals
    below (no subreaper, no pidfd, no census): a caller that finds no keys must
    treat the shape as unknown, which is the fail-closed direction.
    """
    global _ACTIVE_JOB, _IN_SHUTDOWN
    _IN_SHUTDOWN = False
    if not _enable_subreaper():
        return None, "SUBREAPER_UNAVAILABLE: descendant cleanup is not provable\n", True
    if (not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
            or not hasattr(select, "poll")):
        return (None, "PIDFD_UNAVAILABLE: event-driven final-zero cleanup "
                "is not provable\n", True)

    snap, initial_census_ok = _proc_snapshot_checked()
    if not initial_census_ok:
        return (None, "PROCESS_CENSUS_UNAVAILABLE: /proc could not be read "
                "completely\n", True)
    baseline = {(pid, start) for pid, (_ppid, start, _cpu) in snap.items()
                if pid in _descendants(snap, os.getpid())}
    holder: Dict[str, subprocess.Popen] = {}
    killed: Set[int] = set()
    cleanup_census_ok = True
    cleanup_survivors: Set[int] = set()

    def _popen(argv, **kwargs):
        global _ACTIVE_JOB
        kwargs.pop("stderr", None)
        # Publish the frozen pre-launch baseline before fork/exec. Root -1
        # selects no old process but attributes every process created in the
        # handoff if cancellation arrives before Popen returns the exact PID.
        _ACTIVE_JOB = (-1, baseline)
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, start_new_session=True,
                stderr=subprocess.STDOUT, **kwargs)
        except BaseException:
            _ACTIVE_JOB = None
            raise
        holder["proc"] = proc
        _ACTIVE_JOB = (proc.pid, baseline)
        return proc

    def _kill(proc, _reason: str) -> None:
        nonlocal cleanup_census_ok, cleanup_survivors
        cleanup = _cleanup_job(proc.pid, baseline)
        killed.update(cleanup.observed)
        cleanup_census_ok = cleanup_census_ok and cleanup.census_ok
        cleanup_survivors.update(cleanup.survivors)

    # A private 0700 directory, not a file: one emitting process owns one
    # stream inside it. Created before the child exists and removed in the
    # `finally` below, so a stream from any other run cannot appear in it.
    progress_name = tempfile.mkdtemp(prefix="vibeic-pytest-progress-")
    progress_path = Path(progress_name)
    nonce = secrets.token_hex(16)
    probe = _ProgressStreamSet(
        progress_path, nonce,
        lambda: holder["proc"].pid if "proc" in holder else None,
        collect_only=collect_only,
        collect_scan_ceiling=max(
            _COLLECT_SCAN_FLOOR,
            int(scan_units) * _COLLECT_SCAN_PATHS_PER_UNIT),
        require_runtime_identity=(
            os.environ.get(_REQUIRE_RUNTIME_IDENTITY_ENV) == "1"))
    child_env = os.environ.copy()
    child_env[_PROGRESS_DIR_ENV] = progress_name
    child_env[_PROGRESS_NONCE_ENV] = nonce
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (
        str(_PROGRAMS_DIR) if not old_pythonpath else
        str(_PROGRAMS_DIR) + os.pathsep + old_pythonpath)
    relayed_score = 0

    def _progress_sample() -> int:
        nonlocal relayed_score
        score = probe.sample()
        if progress_observer is not None:
            progress_observer(probe)
        if progress_relay_path is not None and score > relayed_score:
            try:
                fd = os.open(
                    progress_relay_path,
                    os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
                try:
                    # One probe sample can consume a burst of lifecycle
                    # records.  The outer strict domain protocol accepts exact
                    # +1 transitions, so preserve every finite transition
                    # rather than collapsing (for example) 2..37 into 37.
                    payload = "".join(
                        f"{value}\n"
                        for value in range(relayed_score + 1, score + 1)
                    ).encode("ascii")
                    while payload:
                        payload = payload[os.write(fd, payload):]
                finally:
                    os.close(fd)
                relayed_score = score
            except OSError:
                # Relay is optional liveness composition, never verdict
                # evidence.  Its owner will stall/refuse if it cannot read it;
                # do not corrupt this session's own complete JUnit/OS record.
                pass
        return score
    try:
        requested_poll = DEFAULT_POLL_S if poll_s is None else poll_s
        effective_poll = min(
            requested_poll, max(0.01, stall_after / 4.0))
        result = _wd.run_supervised(
            list(cmd), output_progress=False,
            domain_progress_probe=_progress_sample,
            stall_grace_s=stall_after,
            poll_s=effective_poll,
            hard_ceiling_s=float("inf"), kill=_kill,
            popen_factory=_popen, env=child_env)
        # A short natural session can start and exit between watchdog polls.
        # Consume and relay its terminal protocol before validating it; without
        # this validator-owned final sample, complete sub-poll work looks like
        # "no nested progress" to the enclosing semantic lease.
        _progress_sample()
        protocol_complete, protocol_error = probe.complete()
        # BEFORE `probe.close()` below: the counts live in the probe.
        items_finished, items_declared = probe.item_counts()
    finally:
        probe.close()
        shutil.rmtree(progress_path, ignore_errors=True)
    proc = holder.get("proc")
    leaked: Set[int] = set()
    post_exit_cleanup_ok = cleanup_census_ok and not cleanup_survivors
    if proc is not None:
        # Linux subreapers adopt already-dead grandchildren as zombies.  Reap
        # them BEFORE asking whether pytest left unfinished work; the former is
        # bookkeeping, while a process still present after this reap is live
        # asynchronous work and makes the pytest verdict incomplete.
        _reap_adopted()
        live, live_census_ok = _job_processes_checked(proc.pid, baseline)
        leaked = set(live)
        if leaked or not live_census_ok:
            cleanup = _cleanup_job(proc.pid, baseline)
            killed.update(cleanup.observed)
            cleanup_census_ok = cleanup_census_ok and cleanup.census_ok
            cleanup_survivors.update(cleanup.survivors)
        post_exit_cleanup_ok = (live_census_ok and cleanup_census_ok
                                and not cleanup_survivors)
    _ACTIVE_JOB = None
    _reap_adopted()
    out = (result.out or "") + (result.err or "")
    if leaked and post_exit_cleanup_ok:
        out += ("\nLIVE_DESCENDANTS_CLEANED: pytest exited with unfinished "
                "descendant process(es); final census is empty, but killing "
                "unfinished work cannot make the record complete; "
                f"cleaned pids={sorted(killed or leaked)}\n")
    elif not post_exit_cleanup_ok:
        out += ("\nDESCENDANT_CLEANUP_INCOMPLETE: final empty census was not "
                f"proved; observed={sorted(killed or leaked)}; "
                f"survivors={sorted(cleanup_survivors)}; "
                f"census_ok={cleanup_census_ok}\n")
    if not protocol_complete:
        out += f"\nPROGRESS_PROTOCOL_INCOMPLETE: {protocol_error}\n"
    incomplete = (result.outcome != "natural" or bool(leaked)
                  or not post_exit_cleanup_ok or not protocol_complete)
    if outcome_sink is not None:
        outcome_sink.update({
            "natural_exit": result.outcome == "natural",
            # `_watchdog` outcome vocabulary: natural | stalled | ceiling |
            # aborted. "stalled" is the ONLY one that means the forward-progress
            # lease expired, and it is the fact `_norecord_reason` needs.
            "stalled": result.outcome == "stalled",
            "leaked": bool(leaked),
            "cleanup_ok": bool(post_exit_cleanup_ok),
            "protocol_complete": bool(protocol_complete),
            "protocol_error": protocol_error,
            "items_finished": items_finished,
            "items_declared": items_declared,
        })
    return result.rc, out, incomplete


def _declared_rootdir(pytest_argv: Sequence[str],
                      cwd: Optional[str]) -> List[str]:
    """Make the selection and the JUnit share ONE coordinate system.

    The aggregate coverage check compares the paths the caller SELECTED against
    the ``file`` attributes pytest REPORTED.  The selection is resolved against
    this session's working directory; pytest's ``file`` attribute is relative to
    its ``rootdir``, which pytest infers from the arguments' nearest ini file.
    When those two directories differ, every selected file is simultaneously
    "missing" and "extra" and a completely green session is refused as UNKNOWN.

    MEASURED at 49d2b3328 on the landing gate's ``full:unselectable-tests``
    lane: 111 files selected as ``vibe-ic-marketplace/plugins/vibe-ic/...`` with
    cwd at the repository root, ``rc=0``, 852 cases, ``784 passed, 60 skipped,
    5 xfailed, 3 xpassed``, ZERO failures -- and refused, ``missing=111`` of 111
    with ``extra=110``, because the plugin subtree carries its own ``pytest.ini``
    and the repository root carries none, so rootdir was the plugin and every
    reported path came back plugin-relative.  The comparison matched nothing, so
    that lane's aggregate arm had never measured anything, and "UNKNOWN" and
    "broken" look the same from outside.

    The frame is therefore DECLARED to pytest rather than inferred on either
    side.  MEASURED, same tree: the ini file is still discovered and applied
    with rootdir moved (``rootdir: <repo root>``, ``configfile:
    vibe-ic-marketplace/plugins/vibe-ic/pytest.ini``), so ``addopts`` and the
    conftest-loaded plugins -- ``suite_write_guard`` among them -- are
    unaffected; only the frame the report is written in moves.  ``testpaths`` IS
    resolved against rootdir and does move, which cannot matter here: it applies
    only when no argument is given, and this driver always names every file
    explicitly and refuses an empty selection (rc 3).

    A caller that already declared a rootdir keeps it.  This adds a frame; it
    never overrides one.
    """
    for arg in pytest_argv:
        if arg == "--rootdir" or arg.startswith("--rootdir="):
            return []
    anchor = Path(cwd).resolve() if cwd else Path.cwd()
    return [f"--rootdir={anchor}"]


#: Files pytest accepts as a config source, in ITS order of precedence. A
#: `pytest.ini` counts even when empty; the other three count only when they
#: carry the section that declares them a pytest config.
_INI_SECTION = {
    "pytest.ini": None,
    ".pytest.ini": None,
    "pyproject.toml": "[tool.pytest.ini_options]",
    "tox.ini": "[pytest]",
    "setup.cfg": "[tool:pytest]",
}


def _is_pytest_config(path: Path) -> bool:
    """True when pytest would accept `path` as this session's config file."""
    section = _INI_SECTION.get(path.name, "")
    if section is None:
        return True
    if not section:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return section in text


def _declared_configfile(pytest_argv: Sequence[str], cwd: Optional[str],
                         targets: Sequence[str]) -> List[str]:
    """Carry the ini that `_declared_rootdir` strands.

    DECLARING `--rootdir` ALSO DROPS THE CONFIG FILE. pytest finds the ini by
    walking up from the arguments' common ancestor, and it performs that search
    as part of inferring rootdir; with rootdir DECLARED the search does not
    happen, no `configfile` is selected, and every `addopts` in that ini
    silently stops applying to the session.

    The docstring on `_declared_rootdir` recorded the opposite -- "the ini file
    is still discovered and applied with rootdir moved ... so `addopts` and the
    conftest-loaded plugins are unaffected". That claim is FALSE and this is the
    measurement that falsifies it. Same tree (7074db3f5), the unselectable
    corpus, 133 files, cwd at the repository root, one pytest process:

        --rootdir=<repo root>                          rc=2   75 collection errors
        --rootdir=<repo root> -c <plugin>/pytest.ini   rc=0   1221 passed
        --rootdir=<repo root> --import-mode=importlib  rc=0   1221 passed

    THE 75 ARE ONE DEFECT, NOT 75. `plugins/vibe-ic/pytest.ini` carries
    `addopts = --import-mode=importlib`. Stranded, the session falls back to
    pytest's default `prepend` mode, which inserts a test file's own directory
    at the front of `sys.path` and imports the file under a module name derived
    from its BASENAME alone whenever that directory has no `__init__.py` -- none
    of these do. The corpus holds 70 files named `test_compliance.py` and 7
    named `test_verdict_boundary.py`. The first of each binds that bare name in
    `sys.modules`; for every later file `_pytest.pathlib.import_path` finds the
    name already held by a different `__file__` and raises
    `ImportPathMismatchError` ("import file mismatch"). 69 + 6 = 75. Collection
    errors abort the session, so pytest exits 2 -- and rc=2 is correctly "the
    question could not be put". The aggregate arm had simply stopped being able
    to put it, while the same 133 files one-per-session stayed 133/133 green,
    which is what makes this the aggregation and not the code.

    RESTORING THE INI IS PREFERRED over pinning an import mode here. It returns
    the session to the configuration it would have had rather than adding a
    second, competing declaration of it, and it keeps this frame-moving helper
    from quietly becoming a place where suite-wide pytest policy is set.
    `testpaths` returns with it and stays inert: it applies only when no
    argument is given, and every caller here names its files explicitly.

    THE SEARCH IS PER-ARGUMENT, NOT PER-COMMON-ANCESTOR, because pytest's is.
    `_pytest.config.locate_config` walks EACH argument's own ancestors in turn
    and takes the first config file it meets; it never intersects the arguments.
    That distinction is the whole reason the ini applies here at all: this
    corpus spans `docs/capture/...` as well as the plugin, so the common
    ancestor is the repository root, which carries no config -- and a search
    written against the common ancestor finds NOTHING and silently restores
    NOTHING. Walking each argument, the first plugin-resident file in the
    selection reaches `plugins/vibe-ic/pytest.ini`, which is exactly the file
    pytest would have used. Matching pytest's algorithm is the point: the goal
    is to restore the config the session WOULD have had, not to pick a
    defensible one.

    Nothing is added when the caller already declared `-c`, or when no ini would
    have been found -- the `tools/` corpus anchored at the repository root finds
    none, so that lane's command is byte-for-byte the one it has always issued.
    """
    for arg in pytest_argv:
        if arg in ("-c", "--config-file"):
            return []
        if arg.startswith(("-c=", "-c", "--config-file=")) and arg != "-c":
            if arg.startswith("--config-file=") or len(arg) > 2:
                return []
    anchor = Path(cwd).resolve() if cwd else Path.cwd()
    for target in targets:
        argpath = Path(target)
        if not argpath.is_absolute():
            argpath = anchor / argpath
        argpath = argpath.resolve()
        for base in (argpath, *argpath.parents):
            for name in _INI_SECTION:
                found = base / name
                if found.is_file() and _is_pytest_config(found):
                    return ["-c", str(found)]
    return []


def run_one(pytest_argv: Sequence[str], test_file: str, junit_path: Path,
            stall_after: float, cwd: Optional[str], *,
            progress_relay_path: Optional[Path] = None,
            outcome_sink: Optional[Dict[str, object]] = None,
            ) -> Tuple[Optional[int], str, bool]:
    """One pytest session for one file, supervised by forward progress."""
    cmd = list(pytest_argv) + _declared_rootdir(pytest_argv, cwd) \
        + _declared_configfile(pytest_argv, cwd, [test_file]) + [
        "-p", _PROGRESS_PLUGIN,
        # xunit1 CARRIES THE `file` ATTRIBUTE and xunit2 drops it. The merge
        # gate answers "did every file we selected actually run" off that
        # attribute, so it is appended here rather than left to the caller: a
        # caller that forgot it would produce a report in which a file that
        # never ran is indistinguishable from one that did.
        "-o", "junit_family=xunit1",
        f"--junitxml={junit_path}",
        test_file,
    ]
    return _run_progress_supervised(
        cmd, stall_after, cwd, progress_relay_path=progress_relay_path,
        scan_units=1, outcome_sink=outcome_sink)


def run_aggregate(pytest_argv: Sequence[str], test_files: Sequence[str],
                  junit_path: Path, stall_after: float,
                  cwd: Optional[str], *,
                  progress_relay_path: Optional[Path] = None,
                  progress_observer: Optional[
                      Callable[["_SemanticProgressProbe"], None]] = None,
                  outcome_sink: Optional[Dict[str, object]] = None,
                  ) -> Tuple[Optional[int], str, bool]:
    """Run the original whole-selection pytest shape as a semantics canary."""
    # THE ONE PLACE THE CEILING IS APPLIED.  The classification below asks
    # `aggregate_failure_bound` the same question with the same inputs, so the
    # arm and the verdict can never disagree about the bound that was in force.
    pytest_argv = _with_failure_bound(
        pytest_argv, aggregate_failure_bound(pytest_argv, len(test_files)))
    cmd = list(pytest_argv) + _declared_rootdir(pytest_argv, cwd) \
        + _declared_configfile(pytest_argv, cwd, test_files) + [
        "-p", _PROGRESS_PLUGIN,
        "-o", "junit_family=xunit1", f"--junitxml={junit_path}",
        *test_files,
    ]
    return _run_progress_supervised(
        cmd, stall_after, cwd, progress_relay_path=progress_relay_path,
        progress_observer=progress_observer, scan_units=len(test_files),
        outcome_sink=outcome_sink)


def run_collect(pytest_argv: Sequence[str], test_files: Sequence[str],
                stall_after: float, cwd: Optional[str], *,
                progress_relay_path: Optional[Path] = None,
                poll_s: Optional[float] = None,
                outcome_sink: Optional[Dict[str, object]] = None,
                ) -> Tuple[Optional[int], str, bool]:
    """Run one collect-only session with the strict lifecycle protocol.

    Collection has its own terminal event because zero ``test_finish`` events
    are expected.  Natural process exit alone is not enough: the nonce-bound
    FSM must also observe a count-preserving collect-only terminal followed by
    ``session_finish``.
    """
    cmd = list(pytest_argv) + _declared_rootdir(pytest_argv, cwd) \
        + _declared_configfile(pytest_argv, cwd, test_files) + [
        "-p", _PROGRESS_PLUGIN, "--collect-only", *test_files,
    ]
    return _run_progress_supervised(
        cmd, stall_after, cwd, progress_relay_path=progress_relay_path,
        poll_s=poll_s, collect_only=True, scan_units=len(test_files),
        outcome_sink=outcome_sink)


def _write_json_atomic(path: Path, payload: object) -> None:
    """Publish one private worker record with the completeness marker last."""
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def _fallback_worker_main(spec_path: Path) -> int:
    """Run one per-file supervisor in its own OS process.

    `_run_progress_supervised` owns process-global subreaper and signal state, so
    it must never be called concurrently in threads.  The pool parent therefore
    launches this private entry point once per selected file.  The raw pytest
    JUnit and an atomic metadata sidecar travel back to the parent; only the
    parent performs the deterministic selection-order merge.
    """
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        required = {
            "schema", "test_file", "junit", "meta", "stall_after", "cwd",
            "progress_relay", "pytest_argv",
        }
        if (not isinstance(spec, dict) or set(spec) != required
                or spec.get("schema") != 1
                or not isinstance(spec.get("test_file"), str)
                or not isinstance(spec.get("junit"), str)
                or not isinstance(spec.get("meta"), str)
                or not isinstance(spec.get("stall_after"), (int, float))
                or spec.get("stall_after") <= 0
                or spec.get("cwd") is not None
                and not isinstance(spec.get("cwd"), str)
                or spec.get("progress_relay") is not None
                and not isinstance(spec.get("progress_relay"), str)
                or not isinstance(spec.get("pytest_argv"), list)
                or not all(isinstance(v, str)
                           for v in spec.get("pytest_argv", []))):
            raise ValueError("wrong fallback worker spec shape")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"FALLBACK_WORKER_NORECORD: unusable worker spec at "
              f"{spec_path}: {exc}", file=sys.stderr, flush=True)
        return RC_CANNOT_ASK

    test_file = spec["test_file"]
    junit_path = Path(spec["junit"])
    meta_path = Path(spec["meta"])
    relay = (Path(spec["progress_relay"])
             if spec["progress_relay"] is not None else None)
    _install_shutdown_handlers()
    rc: Optional[int] = None
    out = ""
    killed = True
    suites: Optional[List[ET.Element]] = None
    cases = 0
    red = 0
    sink: Dict[str, object] = {}
    try:
        rc, out, killed = run_one(
            spec["pytest_argv"], test_file, junit_path,
            float(spec["stall_after"]), spec["cwd"],
            progress_relay_path=relay, outcome_sink=sink)
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        suites = _load_suites(junit_path)
        if killed or rc not in (0, 1):
            suites = None
        if suites is not None:
            for suite in suites:
                n_cases, n_red = _count(suite)
                cases += n_cases
                red += n_red
    except Exception as exc:  # fail closed; shutdown signals are SystemExit
        out += f"\nFALLBACK_WORKER_NORECORD: supervisor raised {exc!r}\n"
        print(out.splitlines()[-1], file=sys.stderr, flush=True)
        killed = True
        suites = None

    has_record = suites is not None
    reason = ("" if has_record else
              _norecord_reason(rc, out, killed, float(spec["stall_after"]),
                               stalled=sink.get("stalled") is True,
                               protocol_error=_sink_protocol_error(sink)))
    try:
        _write_json_atomic(meta_path, {
            "schema": 1,
            "test_file": test_file,
            "pytest_rc": rc,
            "killed": bool(killed),
            "cases": cases,
            "red": red,
            "has_record": has_record,
            "norecord_reason": reason,
        })
    except OSError as exc:
        print(f"FALLBACK_WORKER_NORECORD: metadata publish failed: {exc}",
              file=sys.stderr, flush=True)
        return RC_NORECORD
    if not has_record:
        return RC_NORECORD
    return RC_RED if red or rc != 0 else RC_OK


def _collect_worker_main(spec_path: Path) -> int:
    """Own one collect-only pytest child and publish its terminal evidence."""
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        required = {
            "schema", "test_files", "meta", "stall_after", "cwd",
            "poll_s", "progress_relay", "pytest_argv",
        }
        if (not isinstance(spec, dict) or set(spec) != required
                or spec.get("schema") != 1
                or not isinstance(spec.get("test_files"), list)
                or not spec.get("test_files")
                or not all(isinstance(v, str) and v
                           for v in spec.get("test_files", []))
                or not isinstance(spec.get("meta"), str)
                or not isinstance(spec.get("stall_after"), (int, float))
                or spec.get("stall_after") <= 0
                or not isinstance(spec.get("poll_s"), (int, float))
                or spec.get("poll_s") <= 0
                or spec.get("poll_s") >= spec.get("stall_after")
                or spec.get("cwd") is not None
                and not isinstance(spec.get("cwd"), str)
                or spec.get("progress_relay") is not None
                and not isinstance(spec.get("progress_relay"), str)
                or not isinstance(spec.get("pytest_argv"), list)
                or not all(isinstance(v, str)
                           for v in spec.get("pytest_argv", []))):
            raise ValueError("wrong collect worker spec shape")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"COLLECT_WORKER_NORECORD: unusable worker spec at "
              f"{spec_path}: {exc}", file=sys.stderr, flush=True)
        return RC_CANNOT_ASK

    meta_path = Path(spec["meta"])
    relay = (Path(spec["progress_relay"])
             if spec["progress_relay"] is not None else None)
    _install_shutdown_handlers()
    rc: Optional[int] = None
    out = ""
    incomplete = True
    sink: Dict[str, object] = {}
    try:
        rc, out, incomplete = run_collect(
            spec["pytest_argv"], spec["test_files"],
            float(spec["stall_after"]), spec["cwd"],
            progress_relay_path=relay, poll_s=float(spec["poll_s"]),
            outcome_sink=sink)
        sys.stdout.write(out)
        if out and not out.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception as exc:  # fail closed; shutdown signals are SystemExit
        out += f"\nCOLLECT_WORKER_NORECORD: supervisor raised {exc!r}\n"
        print(out.splitlines()[-1], file=sys.stderr, flush=True)
        incomplete = True

    reason = ("" if not incomplete else
              _norecord_reason(rc, out, incomplete,
                               float(spec["stall_after"]),
                               stalled=sink.get("stalled") is True,
                               protocol_error=_sink_protocol_error(sink)))
    try:
        _write_json_atomic(meta_path, {
            "schema": 1,
            "complete": True,
            "pytest_rc": rc,
            "semantic_record_complete": not incomplete,
            "norecord_reason": reason,
        })
    except OSError as exc:
        print(f"COLLECT_WORKER_NORECORD: metadata publish failed: {exc}",
              file=sys.stderr, flush=True)
        return RC_NORECORD
    if incomplete:
        return RC_NORECORD
    return RC_OK if rc == 0 else RC_RED


def _fallback_no_record(test_file: str, reason: str) -> FileResult:
    return FileResult(test_file, None, True, None, 0, 0,
                      norecord_reason=reason)


def _cgroup_v2_nodes() -> List[Path]:
    """Return the current cgroup-v2 leaf through mount root, most local first."""
    try:
        relative: Optional[str] = None
        for line in Path("/proc/self/cgroup").read_text(
                encoding="ascii").splitlines():
            fields = line.split(":", 2)
            if len(fields) == 3 and fields[0] == "0":
                relative = fields[2]
                break
        if relative is None:
            return []
        root = Path("/sys/fs/cgroup").resolve()
        leaf = (root / relative.lstrip("/")).resolve()
        try:
            leaf.relative_to(root)
        except ValueError:
            return []
        nodes = []
        node = leaf
        while True:
            nodes.append(node)
            if node == root:
                return nodes
            node = node.parent
    except (OSError, UnicodeError):
        return []


def _available_cpu_count() -> Optional[int]:
    """Return the tightest affinity/cgroup CPU allowance, rounded to cores."""
    counts: List[int] = []
    if hasattr(os, "sched_getaffinity"):
        try:
            counts.append(len(os.sched_getaffinity(0)))
        except OSError:
            pass
    host_count = os.cpu_count()
    if host_count is not None:
        counts.append(int(host_count))
    for node in _cgroup_v2_nodes():
        try:
            fields = (node / "cpu.max").read_text(
                encoding="ascii").split()
            if len(fields) == 2 and fields[0] != "max":
                quota, period = (int(value) for value in fields)
                if quota >= 0 and period > 0:
                    counts.append(max(1, (quota + period - 1) // period))
        except (FileNotFoundError, ValueError):
            pass
    positive = [count for count in counts if count > 0]
    return min(positive) if positive else None


def _available_memory_bytes() -> Optional[int]:
    """Return the tightest host/cgroup memory headroom available now."""
    available: List[int] = []
    try:
        lines = Path("/proc/meminfo").read_text(
            encoding="ascii").splitlines()
        for line in lines:
            fields = line.split()
            if len(fields) == 3 and fields[0] == "MemAvailable:" \
                    and fields[2] == "kB":
                value = int(fields[1]) * 1024
                if value >= 0:
                    available.append(value)
                break
    except (OSError, UnicodeError, ValueError):
        pass
    for node in _cgroup_v2_nodes():
        try:
            maximum = (node / "memory.max").read_text(
                encoding="ascii").strip()
            current = int((node / "memory.current").read_text(
                encoding="ascii").strip())
            if maximum != "max":
                available.append(max(0, int(maximum) - current))
        except (FileNotFoundError, ValueError):
            pass
    return min(available) if available else None


def _cgroup_pid_headroom() -> Optional[int]:
    """Return the tightest finite cgroup-v2 PID headroom for this process.

    A leaf scope can have a permissive ``pids.max`` while an ancestor is tight,
    so inspect the leaf and every ancestor up to the cgroup mount. ``max`` is
    unbounded at that level and contributes no finite cap.
    """
    headrooms: List[int] = []
    for node in _cgroup_v2_nodes():
        try:
            maximum = (node / "pids.max").read_text(
                encoding="ascii").strip()
            current = int((node / "pids.current").read_text(
                encoding="ascii").strip())
            if maximum != "max":
                headrooms.append(max(0, int(maximum) - current))
        except (FileNotFoundError, ValueError):
            # The cgroup mount root commonly has no pids controller file even
            # when every delegated descendant does. Keep finite caps observed.
            pass
    return min(headrooms) if headrooms else None


def _fallback_capacity(requested: int, remaining: int) -> _FallbackCapacity:
    """Choose a hard simultaneous-worker ceiling from CPU, memory and PIDs.

    The memory and PID terms are reservations for the supervisor, pytest child,
    and ordinary helper descendants. They constrain *concurrency*, not healthy
    runtime. An unavailable measurement is loud in the emitted cap values and
    falls back to four workers rather than silently treating the resource as
    unlimited.
    """
    cores = _available_cpu_count()
    cpu_cap = (_FALLBACK_UNMEASURED_RESOURCE_CAP if cores is None else
               max(1, int(cores) * _FALLBACK_CPU_FANOUT_PER_CORE))

    available_memory = _available_memory_bytes()
    if available_memory is None:
        memory_cap = _FALLBACK_UNMEASURED_RESOURCE_CAP
    else:
        usable_memory = max(
            0, available_memory - _FALLBACK_MEMORY_RESERVE_BYTES)
        memory_cap = max(1, usable_memory // _FALLBACK_MEMORY_PER_JOB_BYTES)

    pid_headroom = _cgroup_pid_headroom()
    if pid_headroom is None:
        pid_cap = _FALLBACK_UNMEASURED_RESOURCE_CAP
    else:
        usable_pids = max(0, pid_headroom - _FALLBACK_PID_RESERVE)
        pid_cap = max(1, usable_pids // _FALLBACK_PIDS_PER_JOB)

    jobs = max(1, min(
        max(1, remaining), requested, MAX_FALLBACK_PROCESSES,
        cpu_cap, memory_cap, pid_cap))
    return _FallbackCapacity(
        jobs=jobs, requested=requested, cpu_cap=cpu_cap,
        memory_cap=memory_cap, pid_cap=pid_cap)


def _print_fallback_capacity(phase: str, capacity: _FallbackCapacity) -> None:
    print(
        f"FALLBACK_RESOURCE_CAP  phase={phase} "
        f"requested={capacity.requested} selected={capacity.jobs} "
        f"cpu_cap={capacity.cpu_cap} memory_cap={capacity.memory_cap} "
        f"pid_cap={capacity.pid_cap} hard_cap={capacity.hard_cap} "
        f"memory_reservation_mib="
        f"{_FALLBACK_MEMORY_PER_JOB_BYTES // (1024 * 1024)} "
        f"pid_reservation={_FALLBACK_PIDS_PER_JOB}",
        flush=True)


def _stratified_probe_indices(total: int, jobs: int) -> List[int]:
    """Return deterministic 1-based probes spanning an ordered selection.

    The first fallback wave is the only wave allowed to classify a loss as
    systemic. Sampling the first ``jobs`` paths would make that classification a
    property of lexical path clustering, because the production selector emits a
    sorted list. For a multi-file selection the configured width must therefore
    permit both endpoints; interior probes use integer half-up rounding over the
    full span so the result is platform-independent and contains no duplicates.
    """
    if total <= 0 or jobs <= 0:
        return []
    width = min(total, jobs)
    if width == 1:
        return [1]
    span = total - 1
    gaps = width - 1
    return [1 + (probe * span + gaps // 2) // gaps
            for probe in range(width)]


def _read_fallback_outcome(job: _FallbackJob) -> _FallbackOutcome:
    """Validate a worker's atomic metadata against its raw pytest JUnit."""
    try:
        log = job.log_path.read_text(errors="replace")
    except OSError as exc:
        log = f"FALLBACK_WORKER_NORECORD: log unreadable: {exc}\n"
    reason = "fallback supervisor produced no complete worker record"
    try:
        meta = json.loads(job.meta_path.read_text(encoding="utf-8"))
        required = {
            "schema", "test_file", "pytest_rc", "killed", "cases", "red",
            "has_record", "norecord_reason",
        }
        if (not isinstance(meta, dict) or set(meta) != required
                or meta.get("schema") != 1
                or meta.get("test_file") != job.test_file
                or meta.get("pytest_rc") is not None
                and not isinstance(meta.get("pytest_rc"), int)
                or not isinstance(meta.get("killed"), bool)
                or not isinstance(meta.get("cases"), int)
                or meta.get("cases") < 0
                or not isinstance(meta.get("red"), int)
                or meta.get("red") < 0
                or not isinstance(meta.get("has_record"), bool)
                or not isinstance(meta.get("norecord_reason"), str)):
            raise ValueError("wrong worker metadata shape")
        reason = meta["norecord_reason"] or reason
        suites = _load_suites(job.junit_path)
        pytest_rc = meta["pytest_rc"]
        if (not meta["has_record"] or meta["killed"]
                or pytest_rc not in (0, 1) or suites is None
                or job.proc.returncode not in (RC_OK, RC_RED)):
            return _FallbackOutcome(
                _fallback_no_record(job.test_file, reason), log)
        cases = 0
        red = 0
        for suite in suites:
            n_cases, n_red = _count(suite)
            cases += n_cases
            red += n_red
        if cases != meta["cases"] or red != meta["red"]:
            raise ValueError(
                "worker metadata/JUnit count mismatch "
                f"({meta['cases']}/{meta['red']} vs {cases}/{red})")
        expected_worker_rc = RC_RED if red or pytest_rc != 0 else RC_OK
        if job.proc.returncode != expected_worker_rc:
            raise ValueError(
                "worker process verdict mismatch "
                f"({job.proc.returncode} vs {expected_worker_rc})")
        return _FallbackOutcome(
            FileResult(job.test_file, pytest_rc, False, suites, cases, red),
            log)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if log and not log.endswith("\n"):
            log += "\n"
        log += f"FALLBACK_WORKER_NORECORD: {exc}\n"
        return _FallbackOutcome(
            _fallback_no_record(job.test_file, reason), log)


def _run_fallback_batch(
        pytest_argv: Sequence[str], indexed_files: Sequence[Tuple[int, str]],
        tmp: Path, stall_after: float, cwd: Optional[str], *,
        progress_relay_path: Optional[Path] = None,
        ) -> List[_FallbackOutcome]:
    """Recover one fixed-width batch in independent supervisor processes."""
    global _ACTIVE_FALLBACK_BASELINE
    if not _enable_subreaper():
        return [_FallbackOutcome(
            _fallback_no_record(path,
                                "fallback parent subreaper is unavailable"),
            "SUBREAPER_UNAVAILABLE: parallel recovery is not provable\n")
                for _index, path in indexed_files]
    snap, initial_census_ok = _proc_snapshot_checked()
    if not initial_census_ok:
        return [_FallbackOutcome(
            _fallback_no_record(path,
                                "fallback parent process census is unavailable"),
            "PROCESS_CENSUS_UNAVAILABLE: parallel recovery is not provable\n")
                for _index, path in indexed_files]
    baseline = {(pid, start) for pid, (_ppid, start, _cpu) in snap.items()
                if pid in _descendants(snap, os.getpid())}
    _ACTIVE_FALLBACK_BASELINE = baseline
    jobs: Dict[int, _FallbackJob] = {}
    selector: Optional[selectors.BaseSelector] = None
    use_pidfds = hasattr(os, "pidfd_open")
    if use_pidfds:
        selector = selectors.DefaultSelector()
    outcomes: Dict[int, _FallbackOutcome] = {}
    normal_completion = False
    try:
        for index, test_file in indexed_files:
            stem = f"fallback-{index:05d}"
            junit_path = tmp / f"{stem}.xml"
            meta_path = tmp / f"{stem}.json"
            log_path = tmp / f"{stem}.log"
            spec_path = tmp / f"{stem}.spec.json"
            _write_json_atomic(spec_path, {
                "schema": 1,
                "test_file": test_file,
                "junit": str(junit_path),
                "meta": str(meta_path),
                "stall_after": stall_after,
                "cwd": cwd,
                "progress_relay": (str(progress_relay_path)
                                   if progress_relay_path is not None else None),
                "pytest_argv": list(pytest_argv),
            })
            child_env = os.environ.copy()
            child_env[_FALLBACK_WORKER_ENV] = "1"
            try:
                with log_path.open("wb") as log_file:
                    proc = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()),
                         _FALLBACK_WORKER_FLAG, str(spec_path)],
                        stdout=log_file, stderr=subprocess.STDOUT,
                        start_new_session=True, env=child_env)
            except OSError as exc:
                outcomes[index] = _FallbackOutcome(
                    _fallback_no_record(
                        test_file,
                        f"fallback supervisor could not start: {exc}"),
                    f"FALLBACK_WORKER_NORECORD: could not start: {exc}\n")
                continue
            job = _FallbackJob(index, test_file, junit_path, meta_path,
                               log_path, proc)
            jobs[proc.pid] = job
            if selector is not None:
                try:
                    job.pidfd = os.pidfd_open(proc.pid, 0)
                    selector.register(job.pidfd, selectors.EVENT_READ, proc.pid)
                except OSError:
                    use_pidfds = False
                    continue

        if not use_pidfds and selector is not None:
            selector.close()
            selector = None
            for job in jobs.values():
                if job.pidfd is not None:
                    os.close(job.pidfd)
                    job.pidfd = None

        pending = set(jobs)
        while pending:
            finished: List[int] = []
            if selector is not None:
                for key, _mask in selector.select():
                    finished.append(int(key.data))
            else:
                finished = [pid for pid in pending
                            if jobs[pid].proc.poll() is not None]
                if not finished:
                    # watchdog-exempt: this poll never declares a verdict or
                    # kills work; every worker has its own semantic supervisor.
                    time.sleep(0.05)
                    continue
            for pid in finished:
                if pid not in pending:
                    continue
                job = jobs[pid]
                job.proc.wait()
                if selector is not None and job.pidfd is not None:
                    selector.unregister(job.pidfd)
                    os.close(job.pidfd)
                    job.pidfd = None
                pending.remove(pid)
                outcomes[job.index] = _read_fallback_outcome(job)
                print(f"FALLBACK_PROGRESS  completed={len(outcomes)}/"
                      f"{len(indexed_files)}", flush=True)

        _reap_adopted()
        live, live_census_ok = _job_processes_checked(-1, baseline)
        cleanup = CleanupResult(set(), set(), True)
        if live or not live_census_ok:
            cleanup = _cleanup_job(-1, baseline)
        cleanup_ok = (live_census_ok and cleanup.census_ok
                      and not cleanup.survivors and not live)
        if not cleanup_ok or live:
            detail = ("parallel fallback could not prove an empty descendant "
                      f"census; observed={sorted(cleanup.observed or set(live))}; "
                      f"survivors={sorted(cleanup.survivors)}")
            for index, test_file in indexed_files:
                previous = outcomes.get(index)
                log = previous.log if previous is not None else ""
                if log and not log.endswith("\n"):
                    log += "\n"
                outcomes[index] = _FallbackOutcome(
                    _fallback_no_record(test_file, detail),
                    log + f"FALLBACK_WORKER_NORECORD: {detail}\n")
        normal_completion = True
    finally:
        if selector is not None:
            selector.close()
        for job in jobs.values():
            if job.pidfd is not None:
                try:
                    os.close(job.pidfd)
                except OSError:
                    pass
                job.pidfd = None
        if not normal_completion:
            _cleanup_job(-1, baseline)
            for job in jobs.values():
                try:
                    job.proc.wait(timeout=0.1)
                except (subprocess.TimeoutExpired, ChildProcessError):
                    pass
        _ACTIVE_FALLBACK_BASELINE = None
        _reap_adopted()
    return [outcomes.get(index, _FallbackOutcome(
        _fallback_no_record(path, "fallback worker result is absent"),
        "FALLBACK_WORKER_NORECORD: result is absent\n"))
            for index, path in indexed_files]


def _append_process_case(root: ET.Element, *, classname: str, name: str,
                         file_name: str, rc: int) -> None:
    """Append one stable-key process-status testcase (present on both arms)."""
    suite = ET.Element(
        "testsuite",
        {"name": name, "tests": "1", "failures": str(int(rc != 0)),
         "errors": "0", "skipped": "0"},
    )
    case = ET.SubElement(
        suite, "testcase",
        {"classname": classname, "name": name, "file": file_name},
    )
    props = ET.SubElement(case, "properties")
    ET.SubElement(props, "property", {"name": "process_rc", "value": str(rc)})
    if rc != 0:
        failure = ET.SubElement(
            case, "failure",
            {"type": "pytest.session.ExitCode",
             "message": f"pytest session exited rc={rc}"},
        )
        failure.text = (
            "The pytest process verdict is non-zero. The process_rc property "
            "is compared exactly across the base and candidate arms."
        )
    root.append(suite)


def _aggregate_copy(suite: ET.Element) -> ET.Element:
    """Deep-copy and namespace an aggregate suite away from per-file ids."""
    copied = ET.fromstring(ET.tostring(suite, encoding="unicode"))
    copied.set("name", f"aggregate::{copied.get('name') or 'pytest'}")
    for tc in copied.iter("testcase"):
        tc.set("classname", "pytest_aggregate." + (tc.get("classname") or ""))
    return copied


def merge(results: Sequence[FileResult], out_path: Path,
          aggregate_suites: Optional[Sequence[ET.Element]] = None,
          aggregate_rc: Optional[int] = None) -> int:
    """Write ONE xunit1 report carrying every file that produced a record.

    A file with no record contributes NOTHING — not an empty suite, not a
    synthetic case. `landing_merge_verdict` derives the ran-file set from the
    `testcase` elements' `file` attribute, so an empty suite would be invisible
    to it anyway; keeping it out makes the report say exactly what it measured.
    """
    root = ET.Element(_ROOT_TAG, {"name": "pytest tests"})
    total = 0
    for r in results:
        if r.suite is None:
            continue
        for s in r.suite:
            # NAMED BY FILE. pytest names every suite "pytest", so a merged
            # report of 91 of them is 91 identically-named blocks and a reader
            # cannot tell which arm of the run any block came from.
            s.set("name", r.path)
            root.append(s)
            total += len(list(s.iter("testcase")))
        # Present on BOTH arms, including rc=0. A failure-only synthetic would
        # become ABSENT after a fix and the differential would call that
        # SILENCED. The stable key + exact `process_rc` outcome allows rc=1 -> 0
        # to be FIXED and rc=1 -> -9 to be a changed failure that still blocks.
        if r.cases > 0 and r.rc is not None:
            _append_process_case(
                root, classname="pytest_per_file_process",
                name=f"{r.path}::process_exit", file_name=r.path, rc=r.rc)
            total += 1
    if aggregate_suites is not None:
        aggregate_cases = 0
        for suite in aggregate_suites:
            copied = _aggregate_copy(suite)
            root.append(copied)
            n = len(list(copied.iter("testcase")))
            aggregate_cases += n
            total += n
        if aggregate_cases and aggregate_rc is not None:
            _append_process_case(
                root, classname="pytest_aggregate_process",
                name="whole_selection::process_exit",
                file_name="<aggregate>", rc=aggregate_rc)
            total += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(out_path), encoding="utf-8",
                               xml_declaration=True)
    return total


def main(argv: Optional[Sequence[str]] = None) -> int:
    parsed_argv = list(sys.argv[1:] if argv is None else argv)
    if (len(parsed_argv) == 2
            and parsed_argv[0] == _FALLBACK_WORKER_FLAG):
        return _fallback_worker_main(Path(parsed_argv[1]))
    if (len(parsed_argv) == 2
            and parsed_argv[0] == _COLLECT_WORKER_FLAG):
        return _collect_worker_main(Path(parsed_argv[1]))

    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selection", required=True,
                    help="file with one test path per line")
    ap.add_argument("--junit", required=True,
                    help="the MERGED xunit1 report to write")
    ap.add_argument("--stall-after", type=float, default=DEFAULT_STALL_AFTER,
                    help=f"seconds with no validated pytest lifecycle event "
                         f"before a per-file session is classified hung (default "
                         f"{DEFAULT_STALL_AFTER}); this is not a runtime bound")
    ap.add_argument("--stop-after-failures", type=int, default=0,
                    help="stop launching files once this many red test cases "
                         "have been seen in ordinary non-aggregate per-file "
                         "mode; 0 means never stop. Diagnostic recovery after "
                         "aggregate NORECORD always attempts every selected "
                         "file, because an untried file cannot be inferred "
                         "from a sample. Other files not launched are NAMED "
                         "and stay out of the report")
    ap.add_argument("--aggregate-check", action="store_true",
                    help="run the whole selection first in one pytest process; "
                         "on a complete record stop there, otherwise run "
                         "per-file diagnostic recovery while preserving the "
                         "aggregate NORECORD refusal")
    ap.add_argument("--aggregate-only", action="store_true",
                    help="run only the whole-selection session, disabling "
                         "per-file diagnostic recovery; implies "
                         "--aggregate-check")
    ap.add_argument("--aggregate-stall-after", type=float,
                    default=DEFAULT_AGGREGATE_STALL_AFTER,
                    help="seconds with no validated pytest lifecycle event before "
                         "the whole-selection canary is classified hung "
                         f"(default {DEFAULT_AGGREGATE_STALL_AFTER}); this is "
                         "not a runtime bound")
    ap.add_argument("--fallback-jobs", type=int,
                    default=DEFAULT_FALLBACK_JOBS,
                    help="requested maximum independent supervisor processes "
                         "in the initial per-file recovery probe after aggregate "
                         f"NORECORD (default {DEFAULT_FALLBACK_JOBS}); the actual "
                         "width is resource-capped")
    ap.add_argument("--fallback-rescue-jobs", type=int,
                    default=DEFAULT_FALLBACK_RESCUE_JOBS,
                    help="requested high-parallel width for all remaining files "
                         "when the initial probe recovered zero complete records "
                         f"(default {DEFAULT_FALLBACK_RESCUE_JOBS}); CPU, memory, "
                         "PID and absolute hard caps still apply")
    ap.add_argument("--cwd", default=None,
                    help="run each pytest session from here")
    ap.add_argument("--progress-relay", default=None,
                    help="optional append-only semantic score relay for a "
                         "supervising parent; liveness only, never verdict "
                         "evidence")
    ap.add_argument(
        "--hermetic-progress", action="store_true",
        help="relay exact completed selected files and the published JUnit to "
             "the parent-owned hermetic container progress protocol; requires "
             "aggregate-check plus aggregate-only")
    ap.add_argument("pytest_argv", nargs=argparse.REMAINDER,
                    help="-- followed by the full pytest command")
    a = ap.parse_args(parsed_argv)

    if a.aggregate_only:
        a.aggregate_check = True
    if a.hermetic_progress and not a.aggregate_only:
        ap.error("--hermetic-progress requires --aggregate-only")

    if a.stall_after <= 0 or a.aggregate_stall_after <= 0:
        ap.error("stall windows must be positive")
    if a.fallback_jobs <= 0 or a.fallback_jobs > MAX_FALLBACK_PROCESSES:
        ap.error(f"--fallback-jobs must be between 1 and "
                 f"{MAX_FALLBACK_PROCESSES}")
    if (a.fallback_rescue_jobs <= 0
            or a.fallback_rescue_jobs > MAX_FALLBACK_PROCESSES):
        ap.error(f"--fallback-rescue-jobs must be between 1 and "
                 f"{MAX_FALLBACK_PROCESSES}")

    pytest_argv = list(a.pytest_argv)
    if pytest_argv and pytest_argv[0] == "--":
        pytest_argv = pytest_argv[1:]
    if not pytest_argv:
        print("[SKIP] pytest_per_file_junit: no pytest command was given after "
              "`--`, so nothing was run — that is NOT an empty selection and "
              "NOT a pass.", file=sys.stderr)
        return RC_CANNOT_ASK

    sel_path = Path(a.selection)
    try:
        selection = read_selection(sel_path)
    except OSError as exc:
        print(f"[SKIP] pytest_per_file_junit: the selection at {sel_path} could "
              f"not be read ({exc}) — the run could not be asked for.",
              file=sys.stderr)
        return RC_CANNOT_ASK
    if not selection:
        # An empty corpus is a VACUOUS pass, not a pass — the same rule
        # `gatekeeper-land.sh` applies to its own discovery.
        print("[SKIP] pytest_per_file_junit: the selection is EMPTY, so no file "
              "was run. An empty corpus is not evidence that anything passed.",
              file=sys.stderr)
        return RC_CANNOT_ASK
    selection_problem = _selection_identity_problem(selection, a.cwd)
    if selection_problem:
        print("[SKIP] pytest_per_file_junit: the selection denominator is "
              f"ambiguous ({selection_problem}) — nothing was run.",
              file=sys.stderr)
        return RC_CANNOT_ASK
    tmp = Path(tempfile.mkdtemp(prefix="perfile_junit_"))
    _install_shutdown_handlers()
    results: List[FileResult] = []
    red_total = 0
    aggregate_suites: Optional[List[ET.Element]] = None
    aggregate_rc: Optional[int] = None
    aggregate_red = 0
    aggregate_cases = 0
    aggregate_incomplete = False
    hermetic_progress = (
        _HermeticAggregateProgress(selection) if a.hermetic_progress else None)
    if hermetic_progress is not None and not hermetic_progress.start():
        print(f"AGGREGATE_NORECORD  {hermetic_progress.problem}")
        return RC_NORECORD
    try:
        # Aggregate FIRST. It is the authoritative whole-selection question,
        # and a complete answer avoids N redundant pytest starts. If its record
        # is lost, per-file sessions run only as diagnostic recovery below; they
        # preserve neighbouring records but never clear aggregate_incomplete.
        if a.aggregate_check:
            aggregate_path = tmp / "aggregate.xml"
            print(f"=== [aggregate] {len(selection)} file(s) in one pytest "
                  "process", flush=True)
            aggregate_sink: Dict[str, object] = {}
            aggregate_rc, out, aggregate_killed = run_aggregate(
                pytest_argv, selection, aggregate_path,
                a.aggregate_stall_after, a.cwd,
                progress_relay_path=(Path(a.progress_relay)
                                     if a.progress_relay else None),
                progress_observer=(hermetic_progress.observe
                                   if hermetic_progress is not None else None),
                outcome_sink=aggregate_sink)
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            aggregate_suites = _load_suites(aggregate_path)
            aggregate_coverage_problem = ""
            aggregate_missing: List[str] = []
            aggregate_extra: List[str] = []
            if aggregate_suites is not None:
                for suite in aggregate_suites:
                    cases, red = _count(suite)
                    aggregate_cases += cases
                    aggregate_red += red
                (aggregate_coverage_problem, aggregate_missing,
                 aggregate_extra) = _aggregate_coverage(
                    aggregate_suites, selection, a.cwd)
                if not aggregate_coverage_problem and (aggregate_missing
                                                       or aggregate_extra):
                    aggregate_coverage_problem = (
                        "aggregate JUnit does not exactly cover the selected "
                        f"files (missing={aggregate_missing}, "
                        f"extra={aggregate_extra})")
            # rc 0/1 are pytest's complete normal outcomes. Everything else is
            # interrupted/internal/usage/no-collection and cannot certify the
            # whole-selection semantics even if a partial XML happened to parse.
            if (aggregate_killed or aggregate_suites is None
                    or aggregate_cases == 0
                    or aggregate_rc not in (0, 1)
                    or aggregate_coverage_problem):
                aggregate_incomplete = True
                # NAME THE CAUSE FIRST when it is knowable. `AGGREGATE_NORECORD`
                # is still printed underneath, unchanged: `tools/gatekeeper-land.sh`
                # and `landing_merge_verdict` key the absolute refusal off that
                # exact marker, and this line adds information rather than
                # renaming the verdict — the landing refuses either way.
                if aggregate_suites is not None:
                    truncation = _maxfail_truncation(
                        aggregate_failure_bound(pytest_argv, len(selection)),
                        aggregate_rc,
                        aggregate_red, aggregate_sink,
                        len(selection) - len(aggregate_missing),
                        len(selection), aggregate_extra)
                    if truncation is not None:
                        print(f"AGGREGATE_TRUNCATED  {truncation}", flush=True)
                        for node_id in _red_node_ids(aggregate_suites):
                            print(f"    {node_id}", flush=True)
                        aggregate_coverage_problem = (
                            "aggregate session stopped at its own declared "
                            "failure bound after "
                            f"{aggregate_sink['items_finished']}"
                            f"/{aggregate_sink['items_declared']} items"
                            + (f", so {len(aggregate_missing)} of "
                               f"{len(selection)} selected file(s) were never "
                               f"launched: {aggregate_missing}"
                               if aggregate_missing else
                               " (every selected file was launched)"))
                why = (aggregate_coverage_problem or _norecord_reason(
                    aggregate_rc, out, aggregate_killed,
                    a.aggregate_stall_after,
                    stalled=aggregate_sink.get("stalled") is True,
                    protocol_error=_sink_protocol_error(aggregate_sink)))
                print(f"AGGREGATE_NORECORD  {why} — cross-file/order semantics "
                      "are UNKNOWN, not clean", flush=True)
                aggregate_suites = None
            else:
                print(f"AGGREGATE_COMPLETE  rc={aggregate_rc}  "
                      f"cases={aggregate_cases}  red={aggregate_red}",
                      flush=True)

        if (not a.aggregate_only and a.aggregate_check
                and aggregate_incomplete):
            print(f"=== [fallback] {len(selection)} file(s), "
                  f"{a.fallback_jobs} independent supervisor process(es)",
                  flush=True)

            # The selector emits a sorted path list. A consecutive first batch
            # can therefore contain one directory-local failure cluster. Span the
            # ordered corpus for useful early diagnostics, but never infer an
            # untried file's result from this sample.
            probe_capacity = _fallback_capacity(
                a.fallback_jobs, len(selection))
            _print_fallback_capacity("probe", probe_capacity)
            probe_indices = _stratified_probe_indices(
                len(selection), probe_capacity.jobs)
            print("FALLBACK_STRATIFIED_PROBE  indices="
                  + ",".join(str(i) for i in probe_indices), flush=True)
            recovery: Dict[int, _FallbackOutcome] = {}

            def _run_recovery_wave(indices: Sequence[int]) -> None:
                nonlocal red_total
                indexed = [(i, selection[i - 1]) for i in indices]
                try:
                    outcomes = _run_fallback_batch(
                        pytest_argv, indexed, tmp, a.stall_after, a.cwd,
                        progress_relay_path=(Path(a.progress_relay)
                                             if a.progress_relay else None))
                except Exception as exc:
                    # Batch orchestration is diagnostic plumbing. Its own
                    # failure is a named NORECORD for every file in the wave,
                    # never an uncaught traceback that leaves no merged report.
                    detail = f"fallback batch orchestration failed: {exc!r}"
                    print(f"FALLBACK_BATCH_NORECORD  {detail}", flush=True)
                    outcomes = [_FallbackOutcome(
                        _fallback_no_record(test_file, detail),
                        f"FALLBACK_WORKER_NORECORD: {detail}\n")
                                for _i, test_file in indexed]
                # Workers finish in scheduler order, but neither that race nor
                # the stratified probe order may change stdout/JUnit ordering.
                # Hold every outcome by its original 1-based selection index and
                # emit/merge only after the recovery decision is complete.
                for (index, _test_file), outcome in zip(indexed, outcomes):
                    recovery[index] = outcome
                    red_total += outcome.result.red

            _run_recovery_wave(probe_indices)
            probe_set = set(probe_indices)
            remaining_indices = [
                i for i in range(1, len(selection) + 1)
                if i not in probe_set]
            probe_has_record = any(
                recovery[i].result.has_record for i in probe_indices)
            # Zero complete probe records is evidence about those probe files,
            # not the rest. The old systemic breaker silently skipped a unique
            # recoverable ninth file after eight sampled hangs. In that exact
            # high-loss shape, rescue every remaining file with a broader but
            # explicitly CPU/memory/PID/absolute-capped pool. Because this is the
            # sparse-record rescue, every remaining path must receive its own
            # supervisor.
            exhaustive_rescue = not probe_has_record
            requested_width = (a.fallback_rescue_jobs if exhaustive_rescue
                               else a.fallback_jobs)
            remaining_capacity = _fallback_capacity(
                requested_width, max(1, len(remaining_indices)))
            if remaining_indices:
                _print_fallback_capacity(
                    "zero-record-rescue" if exhaustive_rescue else "recovery",
                    remaining_capacity)
            if exhaustive_rescue:
                print("FALLBACK_ZERO_RECORD_RESCUE  probe="
                      + ",".join(str(i) for i in probe_indices)
                      + f" remaining={len(remaining_indices)} "
                        f"parallel_width={remaining_capacity.jobs} — every "
                        "unprobed file will be attempted",
                      flush=True)

            next_remaining = 0
            while next_remaining < len(remaining_indices):
                # Aggregate NORECORD has already made the whole-selection
                # verdict UNKNOWN.  These sessions are evidence recovery, not
                # a fail-fast ordinary run: a red count in the stratified probe
                # says nothing about an untried path.  In particular, one probe
                # file can exceed --stop-after-failures by itself while the
                # sole recoverable green record sits at the unprobed index.
                # Therefore the legacy threshold is intentionally absent from
                # this loop; it remains enforced by the non-aggregate branch.
                wave_indices = remaining_indices[
                    next_remaining:
                    next_remaining + remaining_capacity.jobs]
                _run_recovery_wave(wave_indices)
                next_remaining += len(wave_indices)

            # Selection order is the durable contract. The initial probe is
            # deliberately non-contiguous, but neither logs nor JUnit reveal its
            # execution order as the semantic result order.
            for i, test_file in enumerate(selection, start=1):
                outcome = recovery[i]
                result = outcome.result
                results.append(result)
                if result.skipped_by_stop:
                    continue
                print(f"=== [{i}/{len(selection)}] {test_file} "
                      "[fallback worker]", flush=True)
                sys.stdout.write(outcome.log)
                if outcome.log and not outcome.log.endswith("\n"):
                    sys.stdout.write("\n")
                state = ("NORECORD" if not result.has_record else
                         ("red" if result.red or result.rc != 0 else "ok"))
                print(f"--- {test_file}  rc={result.rc}  "
                      f"cases={result.cases}  red={result.red}  {state}",
                      flush=True)
        elif not a.aggregate_only and not a.aggregate_check:
            for i, test_file in enumerate(selection, start=1):
                if a.stop_after_failures and red_total >= a.stop_after_failures:
                    results.append(FileResult(
                        test_file, None, False, None, 0, 0,
                        skipped_by_stop=True))
                    continue
                per = tmp / f"{i:05d}.xml"
                print(f"=== [{i}/{len(selection)}] {test_file}", flush=True)
                file_sink: Dict[str, object] = {}
                rc, out, killed = run_one(pytest_argv, test_file, per,
                                          a.stall_after, a.cwd,
                                          progress_relay_path=(
                                              Path(a.progress_relay)
                                              if a.progress_relay else None),
                                          outcome_sink=file_sink)
                sys.stdout.write(out)
                if not out.endswith("\n"):
                    sys.stdout.write("\n")
                suites = _load_suites(per)
                # A process killed/interrupted after starting to write XML can
                # leave a parseable PREFIX. Parseability is not completeness;
                # only normal pytest outcomes 0/1 may contribute a record.
                if killed or rc not in (0, 1):
                    suites = None
                cases = 0
                red = 0
                if suites is not None:
                    for s in suites:
                        c, r = _count(s)
                        cases += c
                        red += r
                red_total += red
                results.append(FileResult(
                    test_file, rc, killed, suites, cases, red,
                    norecord_reason=_norecord_reason(
                        rc, out, killed, a.stall_after,
                        stalled=file_sink.get("stalled") is True,
                        protocol_error=_sink_protocol_error(file_sink))))
                state = ("NORECORD" if suites is None
                         else ("red" if red or rc != 0 else "ok"))
                print(f"--- {test_file}  rc={rc}  cases={cases}  red={red}  "
                      f"{state}", flush=True)
        total = merge(results, Path(a.junit), aggregate_suites, aggregate_rc)
        if (hermetic_progress is not None
                and (aggregate_incomplete or not hermetic_progress.finish())):
            aggregate_incomplete = True
            if hermetic_progress.problem:
                print(f"AGGREGATE_NORECORD  {hermetic_progress.problem}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    norecord = [r for r in results if not r.has_record and not r.skipped_by_stop]
    notrun = [r for r in results if r.skipped_by_stop]
    recorded = [r for r in results if r.has_record]

    # THE NORECORD LINES COME FIRST AND ARE GREPPABLE, because they are the one
    # thing a reader of a 91-file run cannot reconstruct from the tail of it.
    for r in norecord:
        print(f"NORECORD  {r.path}  {r.norecord_reason} — this file's result is UNKNOWN, "
              f"not clean")
    for r in notrun:
        reason = (r.norecord_reason or
                  "not launched: --stop-after-failures="
                  f"{a.stop_after_failures} was already reached")
        print(f"NOTRUN    {r.path}  {reason}")
    # A file that WROTE a report carrying zero test cases is a THIRD state, and
    # it is named rather than folded into either neighbour: the session did run
    # and did answer, and what it answered is "nothing was collected here". The
    # merge gate already refuses on it (`PRODUCED NO TEST CASE`) because the
    # file cannot appear in the ran-file set; the rc is deliberately NOT changed
    # for it, so the push path behaves exactly as the single session did — a
    # file collecting nothing never failed that session either.
    for r in recorded:
        if r.cases == 0:
            print(f"EMPTY     {r.path}  rc={r.rc}: a report was written and it "
                  f"carries no test case")

    print("=== pytest junit summary")
    mode = ("aggregate-only" if a.aggregate_only else
            ("aggregate-first" if a.aggregate_check else "per-file"))
    print(f"  mode       {mode}")
    print(f"  asked      {len(selection)}")
    print(f"  recorded   {len(recorded)}")
    print(f"  NORECORD   {len(norecord)}")
    print(f"  NOTRUN     {len(notrun)}")
    print(f"  red cases  {red_total}")
    if a.aggregate_check:
        print(f"  aggregate  {'INCOMPLETE' if aggregate_incomplete else 'complete'}"
              f" rc={aggregate_rc} cases={aggregate_cases} red={aggregate_red}")
    print(f"  merged     {a.junit}  ({total} test case(s))")

    if norecord or aggregate_incomplete:
        return RC_NORECORD
    # The PROCESS status is an independent verdict from the testcase XML.
    # Session-level guards such as this repo's `suite_write_guard` legitimately
    # set `session.exitstatus = 1` after every testcase has passed, and junit
    # then carries zero red testcase elements.  Accepting rc=1 merely because
    # the XML is green would erase the guard's verdict.  rc=5 is likewise not a
    # successful per-file measurement: the selected file collected nothing.
    # Only rc=0 is a complete green session.
    if (red_total or any(r.rc != 0 for r in recorded)
            or (a.aggregate_check and (aggregate_red or aggregate_rc != 0))):
        return RC_RED
    if notrun:
        return RC_RED
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())

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
pytest-timeout remains a last-resort per-test guard. The outer supervisor does
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
        -- <the full pytest command, e.g. python3 -m pytest -q --timeout=180>

The command after ``--`` is run VERBATIM with ``-o junit_family=xunit1``, a
per-file ``--junitxml`` and the one file appended. It is passed in rather than
built here so the harness bound stays declared at ONE site — the caller's line
in `tools/gatekeeper-land.sh`, which is where `ci_harness_timeout_ceiling_check`
reads it from.

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
import json
import os
import selectors
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import _watchdog as _wd
import pytest_parallel_policy as _policy

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

_PROGRESS_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_PROGRESS_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_PROGRESS_PLUGIN = "_pytest_progress_plugin"
_PROGRAMS_DIR = Path(__file__).resolve().parent
_PROGRESS_SCHEMA = 1
_MAX_PROGRESS_BYTES = 64 * 1024 * 1024
_MAX_PROGRESS_EVENTS = 1_000_000
_MAX_PROGRESS_LINE = 64 * 1024
_MAX_DOMAIN_PROGRESS_TOTAL = 10_000
_MAX_DOMAIN_PROGRESS_SCOPES = 64

_PR_SET_CHILD_SUBREAPER = 36
_ACTIVE_JOB: Optional[Tuple[int, Set[Tuple[int, int]]]] = None
_ACTIVE_FALLBACK_BASELINE: Optional[Set[Tuple[int, int]]] = None
_FALLBACK_WORKER_FLAG = "--_fallback-worker-spec"
_FALLBACK_WORKER_ENV = "VIBEIC_PYTEST_FALLBACK_WORKER"

#: Outcomes that count toward `--stop-after-failures`, matching what
#: `landing_merge_verdict.RED` counts.
_RED_TAGS = ("failure", "error")

#: Written to the merged report even when every arm failed, because the report
#: IS the deliverable: a run that produced no file at all is indistinguishable
#: from a run that never happened.
_ROOT_TAG = "testsuites"


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
        "collect_report": {"nodeid", "outcome"},
        "item_collected": {"nodeid"},
        "collection_finish": {"selected_items"},
        "domain_progress": {"nodeid", "scope", "completed", "total"},
        "test_finish": {"nodeid"},
        "session_finish": {"exitstatus"},
    }
    _COMMON = {"schema", "nonce", "pid", "seq", "event", "monotonic_ns"}

    def __init__(self, path: Path, nonce: str, pid_fn):
        self.path = path
        self.nonce = nonce
        self.pid_fn = pid_fn
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
        self.items: Set[str] = set()
        self.finished: Set[str] = set()
        self.declared_items: Optional[int] = None
        self.domain_progress: Dict[Tuple[str, str], Tuple[int, int]] = {}

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
        if set(record) != self._COMMON | self._FIELDS[event]:
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
            self.stage = "collecting"
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
            if (previous is None
                    and len(self.domain_progress)
                    >= _MAX_DOMAIN_PROGRESS_SCOPES):
                self._fail("domain progress scope resource limit exceeded")
                return
            if ((previous is None and completed != 1)
                    or (previous is not None
                        and (total != previous[1]
                             or completed != previous[0] + 1))):
                self._fail("non-monotonic domain_progress")
                return
            self.domain_progress[key] = (completed, total)
        elif event == "test_finish":
            nodeid = record.get("nodeid")
            if (self.stage != "running" or nodeid not in self.items
                    or nodeid in self.finished):
                self._fail("unknown/duplicate/out-of-order test_finish")
                return
            self.finished.add(nodeid)
        elif event == "session_finish":
            if (self.stage != "running" or not isinstance(
                    record.get("exitstatus"), int)
                    or self.declared_items is None):
                self._fail("out-of-order session_finish")
                return
            if len(self.finished) != self.declared_items:
                self._fail(
                    "session finished before every selected item completed "
                    f"({len(self.finished)}/{self.declared_items})")
                return
            self.stage = "finished"

        self.seq = seq
        self.last_ns = stamp
        self.score += 1

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
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
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


def read_selection(path: Path) -> List[str]:
    return [l.strip() for l in
            path.read_text(errors="replace").splitlines() if l.strip()]


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


def _cleanup_job(root_pid: int, baseline: Set[Tuple[int, int]],
                 *, term_grace_s: float = 2.0) -> CleanupResult:
    """Terminate descendants and return a load-bearing final-zero proof."""
    identities, census_ok = _job_processes_checked(root_pid, baseline)
    if not identities:
        final, final_ok = _job_processes_checked(root_pid, baseline)
        return CleanupResult(set(), set(final), census_ok and final_ok)
    observed = set(identities)
    _signal_identities(identities, signal.SIGTERM)
    deadline = time.monotonic() + term_grace_s
    # watchdog-exempt: bounded by the monotonic SIGTERM grace deadline above.
    while time.monotonic() < deadline:
        time.sleep(0.05)
        _reap_adopted()
        current, scan_ok = _job_processes_checked(root_pid, baseline)
        census_ok = census_ok and scan_ok
        observed.update(current)
        if not current:
            final, final_ok = _job_processes_checked(root_pid, baseline)
            return CleanupResult(
                observed, set(final), census_ok and final_ok)
        identities.update(current)
    _signal_identities(identities, signal.SIGKILL)
    # This short interval verifies teardown; it is not a runtime estimate for
    # the test. SIGKILL has already been delivered.
    deadline = time.monotonic() + term_grace_s
    # watchdog-exempt: bounded by the monotonic post-SIGKILL deadline above.
    while time.monotonic() < deadline:
        time.sleep(0.05)
        _reap_adopted()
        current, scan_ok = _job_processes_checked(root_pid, baseline)
        census_ok = census_ok and scan_ok
        observed.update(current)
        if not current:
            break
        _signal_identities(current, signal.SIGKILL)
    _reap_adopted()
    final, final_ok = _job_processes_checked(root_pid, baseline)
    observed.update(final)
    return CleanupResult(observed, set(final), census_ok and final_ok)


def _shutdown_handler(signum, _frame) -> None:
    """On verifier cancellation, clean the active cross-session process tree."""
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
    raise SystemExit(128 + int(signum))


def _install_shutdown_handlers() -> None:
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)


def _norecord_reason(rc: Optional[int], out: str, incomplete: bool,
                     stall_after: float) -> str:
    """Explain UNKNOWN without calling every instrumentation refusal a stall."""
    if "WATCHDOG_STALLED:" in out:
        return (f"STALLED after {stall_after:g} s with no validated pytest "
                "lifecycle progress")
    marker = "PROGRESS_PROTOCOL_INCOMPLETE:"
    if marker in out:
        detail = out.split(marker, 1)[1].splitlines()[0].strip()
        return f"pytest progress protocol incomplete: {detail}"
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
        ) -> Tuple[Optional[int], str, bool]:
    """Run until natural completion; stop only after semantic events stall."""
    global _ACTIVE_JOB
    if not _enable_subreaper():
        return None, "SUBREAPER_UNAVAILABLE: descendant cleanup is not provable\n", True

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
        proc = subprocess.Popen(
            argv, cwd=cwd, start_new_session=True,
            stderr=subprocess.STDOUT, **kwargs)
        holder["proc"] = proc
        _ACTIVE_JOB = (proc.pid, baseline)
        return proc

    def _kill(proc, _reason: str) -> None:
        nonlocal cleanup_census_ok, cleanup_survivors
        cleanup = _cleanup_job(proc.pid, baseline)
        killed.update(cleanup.observed)
        cleanup_census_ok = cleanup_census_ok and cleanup.census_ok
        cleanup_survivors.update(cleanup.survivors)

    progress_fd, progress_name = tempfile.mkstemp(
        prefix="vibeic-pytest-progress-", suffix=".jsonl")
    os.close(progress_fd)
    progress_path = Path(progress_name)
    nonce = secrets.token_hex(16)
    probe = _SemanticProgressProbe(
        progress_path, nonce,
        lambda: holder["proc"].pid if "proc" in holder else None)
    child_env = os.environ.copy()
    child_env[_PROGRESS_PATH_ENV] = progress_name
    child_env[_PROGRESS_NONCE_ENV] = nonce
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (
        str(_PROGRAMS_DIR) if not old_pythonpath else
        str(_PROGRAMS_DIR) + os.pathsep + old_pythonpath)
    relayed_score = 0

    def _progress_sample() -> int:
        nonlocal relayed_score
        score = probe.sample()
        if progress_relay_path is not None and score > relayed_score:
            try:
                fd = os.open(
                    progress_relay_path,
                    os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.write(fd, f"{score}\n".encode("ascii"))
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
        result = _wd.run_supervised(
            list(cmd), output_progress=False,
            domain_progress_probe=_progress_sample,
            stall_grace_s=stall_after, poll_s=DEFAULT_POLL_S,
            hard_ceiling_s=float("inf"), kill=_kill,
            popen_factory=_popen, env=child_env)
        protocol_complete, protocol_error = probe.complete()
    finally:
        probe.close()
        try:
            progress_path.unlink()
        except OSError:
            pass
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
    return result.rc, out, incomplete


def run_one(pytest_argv: Sequence[str], test_file: str, junit_path: Path,
            stall_after: float, cwd: Optional[str], *,
            progress_relay_path: Optional[Path] = None,
            ) -> Tuple[Optional[int], str, bool]:
    """One pytest session for one file, supervised by forward progress."""
    cmd = list(pytest_argv) + [
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
        cmd, stall_after, cwd, progress_relay_path=progress_relay_path)


def run_aggregate(pytest_argv: Sequence[str], test_files: Sequence[str],
                  junit_path: Path, stall_after: float,
                  cwd: Optional[str], *,
                  progress_relay_path: Optional[Path] = None,
                  ) -> Tuple[Optional[int], str, bool]:
    """Run the original whole-selection pytest shape as a semantics canary."""
    cmd = list(pytest_argv) + [
        "-p", _PROGRESS_PLUGIN,
        "-o", "junit_family=xunit1", f"--junitxml={junit_path}",
        *test_files,
    ]
    return _run_progress_supervised(
        cmd, stall_after, cwd, progress_relay_path=progress_relay_path)


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
    try:
        rc, out, killed = run_one(
            spec["pytest_argv"], test_file, junit_path,
            float(spec["stall_after"]), spec["cwd"],
            progress_relay_path=relay)
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
              _norecord_reason(rc, out, killed, float(spec["stall_after"])))
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


def _isolation_groups(
        indexed_files: Sequence[Tuple[int, str]],
        ) -> List[List[Tuple[int, str]]]:
    """Split one wave so a serial-roster file never shares it with anything.

    THE DEFECT THIS CLOSES (measured 2026-08-17). This function's caller runs
    every file in `indexed_files` CONCURRENTLY against the SAME live tree, and
    ELEVEN files in the shipped corpus PLANT a program into that tree while
    they run (see `pytest_parallel_policy.SERIAL_ONLY`; two were exposed by
    measurement, the other nine by its `--audit`). Anything scanning the whole
    programs directory at that moment counts the plant.

    That is not hypothetical here. The identical shape was reproduced on a
    93-file selection under `pytest-xdist --dist loadfile`: at n=16 and n=24,
    `test_issue833_analog_l5_vacuous_reaches_umbrella::
    test_the_gate_is_out_of_the_unrouted_inventory` FAILED with
    `Finding(gate='_i528_planted_unrouted_check', …)` in its own message, and
    `test_issue1130_wiring_population_parity` FAILED on the denominator it
    states. Both pass serially and at n=8. Every one of those files is in the
    corpus this recovery path schedules, so the recovery path can manufacture
    a red that belongs to the SCHEDULE and not to the branch — and a red
    landing costs a whole 31-minute round and lands nothing.

    ORDER AND TOTALITY ARE PRESERVED: the concatenation of the groups is
    `indexed_files` unchanged, so the caller still merges every file exactly
    once, in selection order. Nothing stops being run and nothing stops being
    measured; a rostered file simply gets the machine to itself.
    """
    groups: List[List[Tuple[int, str]]] = []
    current: List[Tuple[int, str]] = []
    for item in indexed_files:
        if item[1] in _policy.SERIAL_ONLY:
            if current:
                groups.append(current)
                current = []
            groups.append([item])
        else:
            current.append(item)
    if current:
        groups.append(current)
    return groups


def _run_fallback_batch(
        pytest_argv: Sequence[str], indexed_files: Sequence[Tuple[int, str]],
        tmp: Path, stall_after: float, cwd: Optional[str], *,
        progress_relay_path: Optional[Path] = None,
        ) -> List[_FallbackOutcome]:
    """Recover one wave, isolating the files that may not share a machine."""
    groups = _isolation_groups(indexed_files)
    if len(groups) == 1:
        return _run_fallback_wave(
            pytest_argv, indexed_files, tmp, stall_after, cwd,
            progress_relay_path=progress_relay_path)
    out: List[_FallbackOutcome] = []
    for group in groups:
        if len(group) == 1 and group[0][1] in _policy.SERIAL_ONLY:
            print(f"FALLBACK_SERIAL_ISOLATION  {group[0][1]} — "
                  f"{_policy.SERIAL_ONLY[group[0][1]].split('.')[0]}",
                  flush=True)
        out.extend(_run_fallback_wave(
            pytest_argv, group, tmp, stall_after, cwd,
            progress_relay_path=progress_relay_path))
    return out


def _run_fallback_wave(
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
    ap.add_argument("pytest_argv", nargs=argparse.REMAINDER,
                    help="-- followed by the full pytest command")
    a = ap.parse_args(parsed_argv)

    if a.aggregate_only:
        a.aggregate_check = True

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
    tmp = Path(tempfile.mkdtemp(prefix="perfile_junit_"))
    _install_shutdown_handlers()
    results: List[FileResult] = []
    red_total = 0
    aggregate_suites: Optional[List[ET.Element]] = None
    aggregate_rc: Optional[int] = None
    aggregate_red = 0
    aggregate_cases = 0
    aggregate_incomplete = False
    try:
        # Aggregate FIRST. It is the authoritative whole-selection question,
        # and a complete answer avoids N redundant pytest starts. If its record
        # is lost, per-file sessions run only as diagnostic recovery below; they
        # preserve neighbouring records but never clear aggregate_incomplete.
        if a.aggregate_check:
            aggregate_path = tmp / "aggregate.xml"
            print(f"=== [aggregate] {len(selection)} file(s) in one pytest "
                  "process", flush=True)
            aggregate_rc, out, aggregate_killed = run_aggregate(
                pytest_argv, selection, aggregate_path,
                a.aggregate_stall_after, a.cwd,
                progress_relay_path=(Path(a.progress_relay)
                                     if a.progress_relay else None))
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            aggregate_suites = _load_suites(aggregate_path)
            if aggregate_suites is not None:
                for suite in aggregate_suites:
                    cases, red = _count(suite)
                    aggregate_cases += cases
                    aggregate_red += red
            # rc 0/1 are pytest's complete normal outcomes. Everything else is
            # interrupted/internal/usage/no-collection and cannot certify the
            # whole-selection semantics even if a partial XML happened to parse.
            if (aggregate_killed or aggregate_suites is None
                    or aggregate_cases == 0
                    or aggregate_rc not in (0, 1)):
                aggregate_incomplete = True
                why = _norecord_reason(
                    aggregate_rc, out, aggregate_killed,
                    a.aggregate_stall_after)
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
                rc, out, killed = run_one(pytest_argv, test_file, per,
                                          a.stall_after, a.cwd,
                                          progress_relay_path=(
                                              Path(a.progress_relay)
                                              if a.progress_relay else None))
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
                        rc, out, killed, a.stall_after)))
                state = ("NORECORD" if suites is None
                         else ("red" if red or rc != 0 else "ok"))
                print(f"--- {test_file}  rc={rc}  cases={cases}  red={red}  "
                      f"{state}", flush=True)
        total = merge(results, Path(a.junit), aggregate_suites, aggregate_rc)
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

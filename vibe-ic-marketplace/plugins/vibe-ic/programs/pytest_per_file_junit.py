#!/usr/bin/env python3
"""pytest_per_file_junit.py — ONE pytest session per selected file, so a file
that HANGS costs its own record and not the whole run's, plus a whole-selection
semantics canary so process isolation cannot hide cross-file failures
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

chip-AGNOSTIC: pure process and XML plumbing. No design, PDK, vendor or process
literal appears here.

USAGE
-----
    python3 pytest_per_file_junit.py --selection SEL --junit OUT
        [--stall-after SECONDS] [--stop-after-failures N] [--cwd DIR]
        [--aggregate-check] [--aggregate-stall-after SECONDS]
        -- <the full pytest command, e.g. python3 -m pytest -q --timeout=180>

The command after ``--`` is run VERBATIM with ``-o junit_family=xunit1``, a
per-file ``--junitxml`` and the one file appended. It is passed in rather than
built here so the harness bound stays declared at ONE site — the caller's line
in `tools/gatekeeper-land.sh`, which is where `ci_harness_timeout_ceiling_check`
reads it from.

With ``--aggregate-check`` the same command is also run once over the entire
selection. Its testcase ids are namespaced under ``pytest_aggregate`` and its
exact process rc is recorded under a stable process key. That preserves the
single-process order/global-state semantics of the command this driver replaced;
an aggregate stall or missing/partial XML is ``AGGREGATE_NORECORD`` and must be
an absolute landing refusal.

EXIT CODES
----------
    0  every asked file produced a record and nothing was red
    1  every asked file produced a record, some test was red (ordinary failure)
    2  AT LEAST ONE FILE OR THE AGGREGATE CANARY PRODUCED NO COMPLETE RECORD
    3  the question could not be put (no selection, unusable arguments)
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import _watchdog as _wd

RC_OK = 0
RC_RED = 1
RC_NORECORD = 2
RC_CANNOT_ASK = 3

#: No-pytest-progress grace, not a duration estimate. The inner pytest guard is
#: 180 s in both callers, so 300 s permits its diagnostics and teardown while a
#: healthy session that keeps completing pytest stages can run indefinitely.
DEFAULT_STALL_AFTER = 300
DEFAULT_AGGREGATE_STALL_AFTER = 300
DEFAULT_POLL_S = 2

_PROGRESS_PATH_ENV = "VIBEIC_PYTEST_PROGRESS_FILE"
_PROGRESS_NONCE_ENV = "VIBEIC_PYTEST_PROGRESS_NONCE"
_PROGRESS_PLUGIN = "_pytest_progress_plugin"
_PROGRAMS_DIR = Path(__file__).resolve().parent
_PROGRESS_SCHEMA = 1
_MAX_PROGRESS_BYTES = 64 * 1024 * 1024
_MAX_PROGRESS_EVENTS = 1_000_000
_MAX_PROGRESS_LINE = 64 * 1024

_PR_SET_CHILD_SUBREAPER = 36
_ACTIVE_JOB: Optional[Tuple[int, Set[Tuple[int, int]]]] = None

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


class _SemanticProgressProbe:
    """Parse only valid, finite-state pytest lifecycle events as progress."""

    _FIELDS = {
        "session_start": set(),
        "collect_report": {"nodeid", "outcome"},
        "item_collected": {"nodeid"},
        "collection_finish": {"selected_items"},
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
    out: Dict[int, Tuple[int, int, int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(errors="replace")
            fields = raw[raw.rfind(")") + 2:].split()
            # fields starts at proc stat field 3 (state).
            out[int(entry.name)] = (
                int(fields[1]), int(fields[19]),
                int(fields[11]) + int(fields[12]))
        except (OSError, ValueError, IndexError):
            continue
    return out


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
    snap = _proc_snapshot()
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
    return {pid: snap[pid][1] for pid in pids if pid in snap}


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


def _cleanup_job(root_pid: int, baseline: Set[Tuple[int, int]],
                 *, term_grace_s: float = 2.0) -> Set[int]:
    """Terminate and verify every descendant, even if it changed sessions."""
    identities = _job_processes(root_pid, baseline)
    if not identities:
        return set()
    observed = set(identities)
    _signal_identities(identities, signal.SIGTERM)
    deadline = time.monotonic() + term_grace_s
    # watchdog-exempt: bounded by the monotonic SIGTERM grace deadline above.
    while time.monotonic() < deadline:
        time.sleep(0.05)
        _reap_adopted()
        current = _job_processes(root_pid, baseline)
        observed.update(current)
        if not current:
            return observed
        identities.update(current)
    _signal_identities(identities, signal.SIGKILL)
    # This short interval verifies teardown; it is not a runtime estimate for
    # the test. SIGKILL has already been delivered.
    deadline = time.monotonic() + term_grace_s
    # watchdog-exempt: bounded by the monotonic post-SIGKILL deadline above.
    while time.monotonic() < deadline:
        time.sleep(0.05)
        _reap_adopted()
        current = _job_processes(root_pid, baseline)
        observed.update(current)
        if not current:
            break
        _signal_identities(current, signal.SIGKILL)
    return observed


def _shutdown_handler(signum, _frame) -> None:
    """On verifier cancellation, clean the active cross-session process tree."""
    job = _ACTIVE_JOB
    if job is not None:
        _cleanup_job(job[0], job[1])
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
    if "DESCENDANT_LEAK:" in out:
        return "pytest exited with live descendants (cleaned by supervisor)"
    if incomplete:
        return "pytest supervision ended without a complete liveness record"
    return f"the session exited rc={rc} without writing a complete junit"


def _run_progress_supervised(
        cmd: Sequence[str], stall_after: float,
        cwd: Optional[str]) -> Tuple[Optional[int], str, bool]:
    """Run until natural completion; stop only after semantic events stall."""
    global _ACTIVE_JOB
    if not _enable_subreaper():
        return None, "SUBREAPER_UNAVAILABLE: descendant cleanup is not provable\n", True

    snap = _proc_snapshot()
    baseline = {(pid, start) for pid, (_ppid, start, _cpu) in snap.items()
                if pid in _descendants(snap, os.getpid())}
    holder: Dict[str, subprocess.Popen] = {}
    killed: Set[int] = set()

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
        killed.update(_cleanup_job(proc.pid, baseline))

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
    try:
        result = _wd.run_supervised(
            list(cmd), output_progress=False,
            domain_progress_probe=probe.sample,
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
    if proc is not None:
        leaked = set(_job_processes(proc.pid, baseline))
        if leaked:
            killed.update(_cleanup_job(proc.pid, baseline))
    _ACTIVE_JOB = None
    _reap_adopted()
    out = (result.out or "") + (result.err or "")
    if leaked:
        out += ("\nDESCENDANT_LEAK: pytest exited while descendant process(es) "
                f"remained; cleaned pids={sorted(leaked)}\n")
    if not protocol_complete:
        out += f"\nPROGRESS_PROTOCOL_INCOMPLETE: {protocol_error}\n"
    incomplete = (result.outcome != "natural" or bool(leaked)
                  or not protocol_complete)
    return result.rc, out, incomplete


def run_one(pytest_argv: Sequence[str], test_file: str, junit_path: Path,
            stall_after: float, cwd: Optional[str]) -> Tuple[Optional[int], str,
                                                             bool]:
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
    return _run_progress_supervised(cmd, stall_after, cwd)


def run_aggregate(pytest_argv: Sequence[str], test_files: Sequence[str],
                  junit_path: Path, stall_after: float,
                  cwd: Optional[str]) -> Tuple[Optional[int], str, bool]:
    """Run the original whole-selection pytest shape as a semantics canary."""
    cmd = list(pytest_argv) + [
        "-p", _PROGRESS_PLUGIN,
        "-o", "junit_family=xunit1", f"--junitxml={junit_path}",
        *test_files,
    ]
    return _run_progress_supervised(cmd, stall_after, cwd)


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
                         "have been seen; 0 means never stop. The files not "
                         "launched are NAMED and stay out of the report")
    ap.add_argument("--aggregate-check", action="store_true",
                    help="also run the whole selection in one pytest process "
                         "and namespace its junit into the merged report; "
                         "preserves cross-file/order semantics")
    ap.add_argument("--aggregate-stall-after", type=float,
                    default=DEFAULT_AGGREGATE_STALL_AFTER,
                    help="seconds with no validated pytest lifecycle event before "
                         "the whole-selection canary is classified hung "
                         f"(default {DEFAULT_AGGREGATE_STALL_AFTER}); this is "
                         "not a runtime bound")
    ap.add_argument("--cwd", default=None,
                    help="run each pytest session from here")
    ap.add_argument("pytest_argv", nargs=argparse.REMAINDER,
                    help="-- followed by the full pytest command")
    a = ap.parse_args(argv)

    if a.stall_after <= 0 or a.aggregate_stall_after <= 0:
        ap.error("stall windows must be positive")

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
        for i, test_file in enumerate(selection, start=1):
            if a.stop_after_failures and red_total >= a.stop_after_failures:
                results.append(FileResult(test_file, None, False, None, 0, 0,
                                          skipped_by_stop=True))
                continue
            per = tmp / f"{i:05d}.xml"
            print(f"=== [{i}/{len(selection)}] {test_file}", flush=True)
            rc, out, killed = run_one(pytest_argv, test_file, per,
                                      a.stall_after, a.cwd)
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            suites = _load_suites(per)
            # A process killed/interrupted after starting to write XML can leave
            # a parseable PREFIX. Parseability is not completeness; only normal
            # pytest outcomes 0/1 may contribute a per-file record.
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
        if a.aggregate_check:
            aggregate_path = tmp / "aggregate.xml"
            print(f"=== [aggregate] {len(selection)} file(s) in one pytest "
                  "process", flush=True)
            aggregate_rc, out, aggregate_killed = run_aggregate(
                pytest_argv, selection, aggregate_path,
                a.aggregate_stall_after, a.cwd)
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
        print(f"NOTRUN    {r.path}  not launched: --stop-after-failures="
              f"{a.stop_after_failures} was already reached")
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

    print("=== per-file junit summary")
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

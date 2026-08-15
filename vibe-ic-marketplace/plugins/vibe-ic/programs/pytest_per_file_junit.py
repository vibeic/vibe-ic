#!/usr/bin/env python3
"""pytest_per_file_junit.py — ONE pytest session per selected file, so a file
that HANGS costs its own record and not the whole run's (vibe-ic#1654).

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
named on stdout as ``NORECORD``. A synthetic red `<testcase>` was considered and
REJECTED: the merge gate compares two arms, so a red that both arms produce is
scored PRE-EXISTING and would let a hang that fires on both sides land as
"not this PR's" — the exact false-clean this program exists to prevent. Absence
keeps `landing_merge_verdict.decide`'s existing refusal (``SELECTED TEST FILE(S)
PRODUCED NO TEST CASE``) firing, and now it fires naming the ONE file instead of
all 91.

THE OUTER BOUND IS NOT A PER-TEST BOUND
=======================================
pytest-timeout remains the per-test bound and fires first: it took the repro
above down at 180 s by itself. `--kill-after` is the net under the shapes
pytest-timeout cannot see at all — a hang during COLLECTION or module import,
where no test is running for a per-test timer to bound, and a test that starves
the timer thread. Those are unbounded, so the default is deliberately far above
anything this tree measures rather than tight: the worst single file measured
here is `test_ci_harness_timeout_ceiling_check.py` at 178.77 s, and the default
below is 5.0x that. A file killed at the bound is NORECORD, which REFUSES the
landing — so the failure direction of a bound set too low is a refused good
branch, never an accepted bad one. It is overridable for that reason.

chip-AGNOSTIC: pure process and XML plumbing. No design, PDK, vendor or process
literal appears here.

USAGE
-----
    python3 pytest_per_file_junit.py --selection SEL --junit OUT
        [--kill-after SECONDS] [--stop-after-failures N] [--cwd DIR]
        -- <the full pytest command, e.g. python3 -m pytest -q --timeout=180>

The command after ``--`` is run VERBATIM with ``-o junit_family=xunit1``, a
per-file ``--junitxml`` and the one file appended. It is passed in rather than
built here so the harness bound stays declared at ONE site — the caller's line
in `tools/gatekeeper-land.sh`, which is where `ci_harness_timeout_ceiling_check`
reads it from.

EXIT CODES
----------
    0  every asked file produced a record and nothing was red
    1  every asked file produced a record, some test was red (ordinary failure)
    2  AT LEAST ONE FILE PRODUCED NO RECORD — the run could not answer for it
    3  the question could not be put (no selection, unusable arguments)
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_OK = 0
RC_RED = 1
RC_NORECORD = 2
RC_CANNOT_ASK = 3

#: Hard per-file wall bound, seconds. 5.0x the worst file MEASURED in this tree
#: (178.77 s). See "THE OUTER BOUND IS NOT A PER-TEST BOUND" above: this is not
#: the per-test timeout and must never be read as one.
DEFAULT_KILL_AFTER = 900

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
                 skipped_by_stop: bool = False):
        self.path = path
        self.rc = rc
        self.killed = killed
        self.suite = suite
        self.cases = cases
        self.red = red
        self.skipped_by_stop = skipped_by_stop

    @property
    def has_record(self) -> bool:
        return self.suite is not None


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


def run_one(pytest_argv: Sequence[str], test_file: str, junit_path: Path,
            kill_after: int, cwd: Optional[str]) -> Tuple[Optional[int], str,
                                                          bool]:
    """One pytest session for one file, under a hard outer bound.

    `start_new_session=True` puts the child in its own process group and the
    bound is enforced with SIGKILL ON THE GROUP — the same thing
    `timeout -s KILL` does, done here so the escalation is testable and needs no
    coreutils. Signalling the GROUP is the load-bearing part: the tests in this
    corpus launch their own pytest-cell subprocesses, and killing only the
    direct child would leave those holding the pipe open forever, which turns a
    bounded wait into an unbounded one.
    """
    cmd = list(pytest_argv) + [
        # xunit1 CARRIES THE `file` ATTRIBUTE and xunit2 drops it. The merge
        # gate answers "did every file we selected actually run" off that
        # attribute, so it is appended here rather than left to the caller: a
        # caller that forgot it would produce a report in which a file that
        # never ran is indistinguishable from one that did.
        "-o", "junit_family=xunit1",
        f"--junitxml={junit_path}",
        test_file,
    ]
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", start_new_session=True)
    bound = kill_after
    try:
        out, _ = proc.communicate(timeout=bound)
        return proc.returncode, out, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=bound)
        except subprocess.TimeoutExpired:                    # pragma: no cover
            out = ""
        return proc.returncode, out, True


def merge(results: Sequence[FileResult], out_path: Path) -> int:
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
    ap.add_argument("--kill-after", type=int, default=DEFAULT_KILL_AFTER,
                    help=f"hard per-file wall bound in seconds "
                         f"(default {DEFAULT_KILL_AFTER}); a file killed here "
                         f"is NORECORD, never a pass")
    ap.add_argument("--stop-after-failures", type=int, default=0,
                    help="stop launching files once this many red test cases "
                         "have been seen; 0 means never stop. The files not "
                         "launched are NAMED and stay out of the report")
    ap.add_argument("--cwd", default=None,
                    help="run each pytest session from here")
    ap.add_argument("pytest_argv", nargs=argparse.REMAINDER,
                    help="-- followed by the full pytest command")
    a = ap.parse_args(argv)

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
    results: List[FileResult] = []
    red_total = 0
    try:
        for i, test_file in enumerate(selection, start=1):
            if a.stop_after_failures and red_total >= a.stop_after_failures:
                results.append(FileResult(test_file, None, False, None, 0, 0,
                                          skipped_by_stop=True))
                continue
            per = tmp / f"{i:05d}.xml"
            print(f"=== [{i}/{len(selection)}] {test_file}", flush=True)
            rc, out, killed = run_one(pytest_argv, test_file, per,
                                      a.kill_after, a.cwd)
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            suites = _load_suites(per)
            cases = 0
            red = 0
            if suites is not None:
                for s in suites:
                    c, r = _count(s)
                    cases += c
                    red += r
            red_total += red
            results.append(FileResult(test_file, rc, killed, suites, cases,
                                      red))
            state = ("NORECORD" if suites is None
                     else ("red" if red else "ok"))
            print(f"--- {test_file}  rc={rc}  cases={cases}  red={red}  "
                  f"{state}", flush=True)
        total = merge(results, Path(a.junit))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    norecord = [r for r in results if not r.has_record and not r.skipped_by_stop]
    notrun = [r for r in results if r.skipped_by_stop]
    recorded = [r for r in results if r.has_record]

    # THE NORECORD LINES COME FIRST AND ARE GREPPABLE, because they are the one
    # thing a reader of a 91-file run cannot reconstruct from the tail of it.
    for r in norecord:
        why = (f"KILLED at the {a.kill_after} s outer bound"
               if r.killed else
               f"the session exited rc={r.rc} without writing a junit")
        print(f"NORECORD  {r.path}  {why} — this file's result is UNKNOWN, "
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
    print(f"  merged     {a.junit}  ({total} test case(s))")

    if norecord:
        return RC_NORECORD
    # pytest's own exit codes: 0 ok, 1 tests failed, 5 no tests collected. 2/3/4
    # (interrupted / internal error / usage error) would have taken the single
    # session down, so they still fail the run here.
    if red_total or any(r.rc not in (0, 1, 5) for r in recorded):
        return RC_RED
    if notrun:
        return RC_RED
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())

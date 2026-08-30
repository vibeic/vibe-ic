#!/usr/bin/env python3
"""ABSENT / EMPTY / POPULATED are three answers, and the gate must give three.

WHY THIS EXISTS. A DRC report that is ABSENT means the question could not be
put and nothing measured the design. One that is EMPTY means the question WAS
put and the answer is zero -- OpenROAD's `detailed_route -output_drc` writes a
zero-byte file exactly when it found no residual violation. One that is
POPULATED means the answer is whatever it parses to. Only the third can carry
a violation, and collapsing any two of them reports enforcement over a
measurement nobody took.

MEASURED 2026-08-30, spm x gf180mcuD, one tree and one gate, BEFORE this fix:

    routed_router.drc.rpt ABSENT -> passed True,  unreadable 0
    routed_router.drc.rpt EMPTY  -> passed False, unreadable 1

i.e. the verdict was INVERTED: a route WITH violations writes a parseable
report and passes the readability check, while a route with NONE writes an
empty file and fails it. v1.13.3 started requesting the report (PR #1851) and
taught only one of its two consumers what an empty one means.

EXIT CODES ARE ASSERTED EXACTLY, and rc 2 is deliberately never produced:
`flow_compliance_check._check_program_exit_zero` credits rc 2 as a VACUOUS
PASS. Proven by run on this host 2026-08-30 -- a gate exiting 0 grades
passed=True, 1 grades False, and 2 grades **True**. A refusal that spent rc 2
would therefore turn this gate GREEN on absence, which is the failure this
module exists to prevent, arriving by the door marked "skip".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "drc_report_check.py"

RC_PASS, RC_FAIL = 0, 1

def _populated(count: int) -> str:
    """A POPULATED router DRC report carrying `count` violations.

    SYNTHESIZED, never copied from a design: every token here is OpenROAD /
    TritonRoute log grammar plus the audit's own category vocabulary. No
    design, PDK, layer or vendor literal appears.

    It is deliberately realistic rather than minimal. `eda_report_audit`
    refuses a report under 2048 B as `DRC_REPORT_TOO_SMALL` ("suggests a
    hand-typed stub, not a real drc tool output") and requires recognised
    category vocabulary -- guards that exist precisely to stop a fixture like
    this one from certifying anything. A test that dodged them by shrinking
    the guard would be testing a gate nobody runs.
    """
    head = ("# OpenROAD detailed_route DRC summary\n"
            "# Tool: openroad detailed_route (drt)\n"
            "openroad / drt-pass: detailed_route invoked\n"
            f"violation report: {count}\n"
            f"total violations: {count}\n"
            "categories: spacing width density antenna via enclosure\n"
            "Metal Spacing / min width / metal density / antenna ratio /\n"
            "cut via spacing / via enclosure\n")
    # Pad past the anti-stub floor with the tool's own per-iteration lines.
    pad = "".join(f"    Completing {i}% with {count} violations.\n"
                  for i in range(10, 101, 10))
    while len(head) + len(pad) < 2400:
        pad += "[INFO DRT-0267] cpu time = 00:00:01, elapsed time = 00:00:01.\n"
    return head + pad


POPULATED_CLEAN = _populated(0)
POPULATED_DIRTY = _populated(3)


def _project(tmp_path: Path, router_report: str | None) -> Path:
    """A project whose router DRC report is ABSENT / EMPTY / POPULATED.

    `router_report is None` -> the file is not created at all (ABSENT).
    `""`                    -> created with zero bytes (EMPTY).
    anything else           -> created with those bytes (POPULATED).

    A sibling report is always present and populated-clean, so the scope is
    never empty and the state under test is the ONLY thing that varies. Without
    that sibling an absent report and an absent SCOPE would be the same run.
    """
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.drc.rpt").write_text(POPULATED_CLEAN)
    if router_report is not None:
        (pnr / "routed_router.drc.rpt").write_text(router_report)
    return tmp_path


def _run(project: Path, tmp_path: Path, require: bool = True):
    out = tmp_path / "audit.json"
    argv = [sys.executable, str(PROG), str(project), "--mode", "drc",
            "--under", "phase3/stage3/pnr", "--json", str(out)]
    if require:
        argv += ["--require-report", "phase3/stage3/pnr/routed_router.drc.rpt"]
    r = subprocess.run(argv, capture_output=True, text=True)
    payload = json.loads(out.read_text()) if out.is_file() else None
    return r, payload


# --------------------------------------------------------------------------
# The three states, each REACHABLE, each with the fixture that produces it.
# --------------------------------------------------------------------------

def test_empty_report_is_a_measured_zero_and_passes(tmp_path):
    """EMPTY: the tool wrote its report and had nothing to write."""
    r, payload = _run(_project(tmp_path / "p", ""), tmp_path)
    assert r.returncode == RC_PASS, r.stderr
    assert payload["passed"] is True
    assert payload["summary"]["empty_report_files"] == 1
    # It is a zero, NOT an unreadable file. This is the whole defect.
    assert payload["summary"]["unreadable_files"] == 0
    assert any(f["rule"] == "DRC_REPORT_EMPTY" for f in payload["findings"]), \
        "an empty report must be NAMED, never silently folded into clean"


def test_absent_report_refuses(tmp_path):
    """ABSENT: the question could not be put. This must REFUSE."""
    r, payload = _run(_project(tmp_path / "p", None), tmp_path)
    assert r.returncode == RC_FAIL, r.stderr
    assert payload["passed"] is False
    assert payload["summary"]["terminal_verdict"] == "REQUIRED_REPORT_ABSENT"
    assert payload["summary"]["required_reports_absent"] == [
        "phase3/stage3/pnr/routed_router.drc.rpt"]


def test_populated_report_with_violations_refuses(tmp_path):
    """POPULATED: the answer parsed, and it is not zero."""
    r, payload = _run(_project(tmp_path / "p", POPULATED_DIRTY), tmp_path)
    assert r.returncode == RC_FAIL, r.stderr
    assert payload["passed"] is False
    assert payload["summary"]["real_violation_total"] == 3


def test_populated_report_that_is_clean_passes(tmp_path):
    """The control that must stay GREEN in both arms of the falsification."""
    r, payload = _run(_project(tmp_path / "p", POPULATED_CLEAN), tmp_path)
    assert r.returncode == RC_PASS, r.stderr
    assert payload["passed"] is True
    assert payload["summary"]["real_violation_total"] == 0


# --------------------------------------------------------------------------
# The distinctions themselves — asserted as relations, not as three constants
# that a later edit could drift apart.
# --------------------------------------------------------------------------

def test_absent_and_empty_do_not_share_an_exit_code(tmp_path):
    """The load-bearing relation: if these ever converge, one of the two
    answers has been lost and the gate reports enforcement over a measurement
    nobody took. Asserted as rc_absent != rc_empty, so it cannot be satisfied
    by both becoming a pass."""
    r_absent, _ = _run(_project(tmp_path / "a", None), tmp_path / "ja")
    r_empty, _ = _run(_project(tmp_path / "e", ""), tmp_path / "je")
    (tmp_path / "ja").mkdir(exist_ok=True)
    (tmp_path / "je").mkdir(exist_ok=True)
    assert r_absent.returncode != r_empty.returncode
    assert r_absent.returncode == RC_FAIL
    assert r_empty.returncode == RC_PASS


def test_no_state_ever_exits_2(tmp_path):
    """rc 2 is credited as a VACUOUS PASS by flow_compliance_check, so a
    refusal spending it would read as GREEN. No state may produce it."""
    for i, body in enumerate([None, "", POPULATED_CLEAN, POPULATED_DIRTY]):
        r, _ = _run(_project(tmp_path / f"p{i}", body), tmp_path / f"j{i}")
        assert r.returncode in (RC_PASS, RC_FAIL), \
            f"state {body!r} exited {r.returncode}"


def test_without_the_declaration_absence_is_not_invented(tmp_path):
    """No false positives: a caller that did NOT require the report is not
    failed for its absence. The gate refuses an absent report it was TOLD to
    expect, not every report it can imagine."""
    r, payload = _run(_project(tmp_path / "p", None), tmp_path, require=False)
    assert r.returncode == RC_PASS, r.stderr
    assert payload["passed"] is True


def test_empty_is_a_zero_even_with_no_declaration(tmp_path):
    """The EMPTY fix, ISOLATED from the new `--require-report` flag.

    The other empty-state test passes the flag, so against pre-fix code it
    fails on the flag being unknown -- a failure that observed an ABSENCE, not
    a value. This one passes no wrapper flag at all, so its pre-fix failure is
    the real one: the empty report counted as `unreadable` and the gate
    refused a clean route. It is the substantive half of the control.
    """
    r, payload = _run(_project(tmp_path / "p", ""), tmp_path, require=False)
    assert r.returncode == RC_PASS, r.stderr
    assert payload["passed"] is True
    assert payload["summary"]["unreadable_files"] == 0
    assert payload["summary"]["empty_report_files"] == 1

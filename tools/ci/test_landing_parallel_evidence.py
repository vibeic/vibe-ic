#!/usr/bin/env python3
"""The two landing checks that survived the switch to the parallel path.

WHY THIS FILE EXISTS
====================
`tools/gatekeeper-land.sh` used to run its targeted tests as ONE aggregate pytest
session and asked two questions about it:

    FAIL  targeted test instrument produced no junit summary
    FAIL  targeted aggregate session produced no status

Both arms now pass `--parallel-first`, so there is no aggregate session and neither
question could be answered in its old form. The tempting repair is to delete them.
That is precisely the failure the NORECORD doctrine exists to prevent: a stage that
produced NO RECORD must never read as a stage that produced a clean one, and a
deleted check reads clean unconditionally.

So each was re-pointed at the equivalent evidence the parallel path does produce,
and this file is the proof that the re-pointed checks still REFUSE. A check nobody
has made fail is not a check.

HOW IT TESTS THEM
=================
Not by re-describing the logic — by EXECUTING IT. Each check is delimited in the
shell script by `>>> LANDING_EVIDENCE_CHECK_n >>>` sentinels; this file extracts the
text between them and runs it under bash with synthetic `$out` / `$sel` / `$merged`.
A copy retyped here would drift from the shipped script and would keep passing after
the real check was weakened, which is the failure mode being guarded against.

Every case asserts BOTH directions: complete evidence must be ACCEPTED (or the check
is merely broken, refusing everything forever) and each individual piece of evidence
removed must be REFUSED.
"""
from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LAND = REPO / "tools" / "gatekeeper-land.sh"

#: A healthy `--parallel-first` run's evidence, in the shape the driver really emits
#: (verified against a live 4-file run: see `PARALLEL_SPLIT`/`PARALLEL_COMPLETE` and
#: the census block in `programs/pytest_per_file_junit.py`).
GOOD_OUT = textwrap.dedent("""\
    === [fallback] 4 file(s), 8 independent supervisor process(es)
    PARALLEL_SPLIT  parallel_safe=1 tree_exclusive=3 asked=4
    === [tree-exclusive] 3 file(s) will run in an isolated checkout each
    --- programs/tests/test_a.py  rc=0  cases=10  red=0  ok
    suite_write_guard: nothing written
    PARALLEL_COMPLETE  asked=4  recorded=4  norecord=0  notrun=0  tree_exclusive=3/3  red=0
    === pytest junit summary
      mode       parallel-first
      asked      4
      recorded   4
      NORECORD   0
      NOTRUN     0
      red cases  0
      merged     /tmp/m.xml  (46 test case(s))
    """)

SEL_4 = "a.py\nb.py\nc.py\nd.py\n"


def _extract(n: int) -> str:
    text = LAND.read_text()
    m = re.search(rf">>> LANDING_EVIDENCE_CHECK_{n} >>>(.*?)<<< LANDING_EVIDENCE_CHECK_{n} <<<",
                  text, re.S)
    assert m, (
        f"the CHECK_{n} sentinels are gone from {LAND.name}. Either the check was "
        "deleted — which is the thing this file exists to prevent — or it was "
        "renamed without updating its proof.")
    return m.group(1)


def _run(n: int, out: str, tmp_path: Path, *, sel: str = SEL_4,
         merged_bytes: bytes = b"<testsuites/>") -> tuple[int, str]:
    """Execute the shipped check block; return (FAILED, stdout)."""
    selp = tmp_path / "sel"
    selp.write_text(sel)
    mergedp = tmp_path / "merged.xml"
    mergedp.write_bytes(merged_bytes)
    script = tmp_path / "check.sh"
    script.write_text(
        'set -uo pipefail\nFAILED=0\n'
        f'sel={selp}\nmerged={mergedp}\n'
        'out="$(cat "$1")"\n'
        + _extract(n)
        + '\nprintf "RESULT_FAILED=%s\\n" "$FAILED"\n')
    outp = tmp_path / "out.txt"
    outp.write_text(out)
    cp = subprocess.run(["bash", str(script), str(outp)],
                        capture_output=True, text=True, timeout=120)
    m = re.search(r"RESULT_FAILED=(\d+)", cp.stdout)
    assert m, f"the check block did not run to completion:\n{cp.stdout}\n{cp.stderr}"
    return int(m.group(1)), cp.stdout


# ---------------------------------------------------------------------------
# CHECK 1 — the completion census.
# ---------------------------------------------------------------------------
def test_check1_accepts_a_complete_census(tmp_path):
    """The direction that proves the check is not simply broken. Without this, a
    check that refused every round would look identical to a working one."""
    failed, log = _run(1, GOOD_OUT, tmp_path)
    assert failed == 0, log
    assert "REPORT  targeted test census complete" in log


def test_check1_refuses_when_the_instrument_died_before_reporting(tmp_path):
    """THE PLANTED DEFECT THAT MOTIVATED THIS CHECK. The `--parallel-first` driver
    raised NameError after a full parallel wave and before any reporting: real work
    happened, a real wall clock elapsed, and no census was ever printed. The old
    check caught this only incidentally; this one names it."""
    crashed = GOOD_OUT.split("=== pytest junit summary")[0] + (
        "Traceback (most recent call last):\n"
        "NameError: name '_exclusive_indices' is not defined\n")
    failed, log = _run(1, crashed, tmp_path)
    assert failed == 1, log
    assert "produced no completion census" in log


def test_check1_refuses_a_census_that_covers_the_wrong_population(tmp_path):
    """A driver that measured 3 of the 4 files this gate selected and reported
    honestly about its own 3. The census is internally consistent; it is just not a
    census of the selection, and only the gate knows what it asked for."""
    failed, log = _run(1, GOOD_OUT.replace("asked      4", "asked      3"), tmp_path)
    assert failed == 1, log
    assert "census covers 3 file(s), the selection had 4" in log


def test_check1_refuses_a_census_that_does_not_add_up(tmp_path):
    """One file in no bucket at all — neither recorded, nor NORECORD, nor NOTRUN.
    This is the arithmetic that makes 'every file is accounted for' checkable rather
    than merely claimed."""
    failed, log = _run(1, GOOD_OUT.replace("recorded   4", "recorded   3"), tmp_path)
    assert failed == 1, log
    assert "does not add up" in log


def test_check1_refuses_when_the_merged_junit_is_absent(tmp_path):
    """The census is a CLAIM; the merged junit is the artefact backing it. A run that
    says it recorded four files and left no junit has not produced evidence, it has
    produced a sentence."""
    failed, log = _run(1, GOOD_OUT, tmp_path, merged_bytes=b"")
    assert failed == 1, log
    assert "merged junit is absent/empty" in log


@pytest.mark.parametrize("line", ["asked      4", "recorded   4",
                                  "NORECORD   0", "NOTRUN     0"])
def test_check1_refuses_when_any_single_census_field_is_missing(tmp_path, line):
    """Field by field: no one of the four may go missing quietly, because the
    arithmetic that proves completeness needs all four."""
    failed, log = _run(1, GOOD_OUT.replace(line + "\n", ""), tmp_path)
    assert failed == 1, log
    assert "produced no completion census" in log


# ---------------------------------------------------------------------------
# CHECK 2 — the whole-selection status line.
# ---------------------------------------------------------------------------
def test_check2_accepts_a_completed_parallel_session(tmp_path):
    failed, log = _run(2, GOOD_OUT, tmp_path)
    assert failed == 0, log
    assert "REPORT  targeted parallel session completed" in log


def test_check2_refuses_when_no_status_was_declared_at_all(tmp_path):
    """THE BRANCH THE WHOLE CHECK IS FOR, and the one a deletion would have removed:
    the session said NOTHING. Silence must cost more than failure, never less."""
    silent = GOOD_OUT.replace(
        "PARALLEL_COMPLETE  asked=4  recorded=4  norecord=0  notrun=0  "
        "tree_exclusive=3/3  red=0\n", "")
    failed, log = _run(2, silent, tmp_path)
    assert failed == 1, log
    assert "produced no status" in log


def test_check2_refuses_an_explicit_norecord(tmp_path):
    failed, log = _run(2, GOOD_OUT.replace(
        "PARALLEL_COMPLETE  asked=4", "PARALLEL_NORECORD  1 of 4"), tmp_path)
    assert failed == 1, log
    assert "produced no complete record" in log


def test_check2_refuses_when_the_population_was_never_declared(tmp_path):
    """A green status line attests to the population the DRIVER believed it had.
    `PARALLEL_SPLIT` is where that belief is stated as a number the gate can compare
    against its own selection; without it there is nothing to have completed."""
    failed, log = _run(2, GOOD_OUT.replace(
        "PARALLEL_SPLIT  parallel_safe=1 tree_exclusive=3 asked=4\n", ""), tmp_path)
    assert failed == 1, log
    assert "declared no population" in log


def test_check2_refuses_a_split_over_the_wrong_population(tmp_path):
    """The driver measured a different set from the one it was handed. Every file it
    did measure may be green and the round still says nothing about the selection."""
    failed, log = _run(2, GOOD_OUT.replace(
        "tree_exclusive=3 asked=4", "tree_exclusive=3 asked=2"), tmp_path)
    assert failed == 1, log
    assert "split 2 file(s), the selection had 4" in log


def test_check2_does_not_accept_the_aggregate_markers_it_replaced(tmp_path):
    """The old evidence must not still satisfy the new check. A driver reverted to
    the aggregate path would otherwise land silently through a gate that believes it
    is verifying the parallel one."""
    aggregate_era = GOOD_OUT.replace(
        "PARALLEL_COMPLETE  asked=4  recorded=4  norecord=0  notrun=0  "
        "tree_exclusive=3/3  red=0",
        "AGGREGATE_COMPLETE  rc=0  cases=46  red=0").replace(
        "PARALLEL_SPLIT  parallel_safe=1 tree_exclusive=3 asked=4\n", "")
    failed, log = _run(2, aggregate_era, tmp_path)
    assert failed == 1, log


# ---------------------------------------------------------------------------
# The gate really does drive the parallel path — otherwise the two checks above
# are correct and irrelevant.
# ---------------------------------------------------------------------------
def test_both_targeted_arms_ask_for_the_parallel_path():
    text = LAND.read_text()
    # The INVOCATION lines, not every mention: the comments above these checks
    # discuss the flag by name, and counting prose would make this assertion pass
    # for the wrong reason.
    arms = [ln for ln in text.splitlines()
            if ln.strip().rstrip("\\").strip() == "--parallel-first"]
    assert len(arms) == 2, (
        "the candidate arm and the base arm must BOTH take the parallel path; "
        "comparing a parallel candidate against an aggregate base would report the "
        "difference between two instruments as a regression in the change")
    assert not [ln for ln in text.splitlines() if ln.strip().rstrip("\\").strip() == "--aggregate-check"], (
        "an arm still asks for the aggregate session the checks no longer read")

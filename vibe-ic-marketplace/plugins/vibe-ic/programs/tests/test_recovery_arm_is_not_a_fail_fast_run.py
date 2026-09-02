#!/usr/bin/env python3
"""The per-file RECOVERY arm may not inherit the caller's fail-fast bound.

THE DEFECT, as measured on the official 2026-08-31 full landing tier
(tree 08466304b3, 132 selected files, `GATEKEEPER_PYTEST_MAXFAIL=10`). Two of
the stamp's FAIL rows say nothing about any test's content:

    FAIL  targeted per-file session produced no complete record
    FAIL  targeted aggregate session produced no complete record

and the driver output above the first one names its cause exactly::

    FILE_TRUNCATED  programs/tests/test_matrix_mutation_ledger.py  10 failures
      reached at file 1/1, 96/126 items — the recorded failures are a PREFIX of
      the failure set, not the failure set; REFUSED
    NORECORD  programs/tests/test_matrix_mutation_ledger.py  session stopped at
      its own declared failure bound … — this file's result is UNKNOWN

30 of that file's 126 items were never run, and the row a reader sees is the
INSTRUMENT DECLINING TO REPORT. Neither side is behaving badly on its own: the
reader's completeness rule (`_per_file_truncation` — a prefix of a failure set
is not a failure set) is right and must not move, and pytest stopped where it
was told. The CALLER's configuration is what cannot be satisfied: a session run
under `--maxfail=N` can never produce a complete record for a file carrying N or
more reds, so the files most in need of naming are precisely the ones the
recovery arm refuses to name. The driver's own `_per_file_truncation` docstring
already says so in as many words.

The recovery arm is not a fail-fast run. It exists only AFTER
`AGGREGATE_NORECORD` has made the whole-selection verdict UNKNOWN and the
landing has already refused; stopping it early buys nothing and costs the only
evidence anybody can still recover. The driver's OWN cross-file bound
(`--stop-after-failures`) was removed from that loop for this exact reason; the
pytest-level bound inside each recovery session was left behind, so the loop
stopped abandoning whole FILES and went on abandoning the ITEMS inside one.

BLOCKING BEHAVIOUR IS UNCHANGED, and that is what makes this a repair and not a
relaxation: `aggregate_incomplete` is already latched when this arm runs, so the
driver still exits `RC_NORECORD` on both sides of the fix.
`test_the_verdict_does_not_move` pins that in both directions.

BIDIRECTIONAL CONTROL, measured in the pinned image on origin/main
(1ec22dabc) with one fixture, `--maxfail=2` and a file carrying three reds:

    pre-fix   recorded 1  NORECORD 1  red cases 0  merged 2 case(s)   rc=2
    post-fix  recorded 2  NORECORD 0  red cases 3  merged 7 case(s)   rc=2

`test_a_file_with_more_reds_than_the_bound_still_produces_a_record` is RED
against the pre-fix driver and GREEN after. The negatives below hold in BOTH
directions and can only break if the change reached further than the recovery
arm.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as D                              # noqa: E402
import _watchdog                                               # noqa: E402
from _hostpaths import require_repo                            # noqa: E402

_PROG = _PROGRAMS / "pytest_per_file_junit.py"

#: Test-only no-progress window. NOT a cap on healthy runtime — the driver's
#: contract is forward progress, and these fixtures make progress constantly.
_STALL = 1

#: More reds than the bound the caller declares below. Three vs two is the
#: smallest pair that distinguishes "recorded the prefix" from "recorded the
#: set" while still leaving a green item after the reds, so a truncated session
#: is visibly missing work rather than merely missing a verdict.
_BOUND = 2

_MORE_REDS_THAN_THE_BOUND = (
    "def test_red_1():\n    assert False\n\n\n"
    "def test_red_2():\n    assert False\n\n\n"
    "def test_red_3():\n    assert False\n\n\n"
    "def test_green_after_the_reds():\n    assert True\n"
)
_GREEN_NEIGHBOUR = "def test_ok():\n    assert True\n"


def _supervised(cmd, **kw):
    """`subprocess.run` bounded by FORWARD PROGRESS, never by a wall clock."""
    return _watchdog.completed_process(
        cmd, _watchdog.run_host_supervised(cmd, **kw))


def _tree(tmp_path: Path, files: dict) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (corpus / name).write_text(body, encoding="utf-8")
    (corpus / "selection.txt").write_text(
        "".join(f"{n}\n" for n in files), encoding="utf-8")
    return corpus


def _drive(corpus: Path, junit: Path, *extra, pytest_extra=()):
    """The driver, in the shape the landing lane drives it: aggregate first,
    then per-file recovery, under a caller-declared failure bound."""
    return _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(junit),
         "--stall-after", str(_STALL),
         "--aggregate-check", "--aggregate-stall-after", str(_STALL),
         *extra, "--",
         sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--maxfail={_BOUND}", *pytest_extra],
        cwd=str(corpus))


def _report(junit: Path):
    """(per-file process records, red case ids) as the merge gate reads them."""
    root = ET.parse(str(junit)).getroot()
    records = {s.get("name")[: -len("::process_exit")]
               for s in root.iter("testsuite")
               if (s.get("name") or "").endswith("::process_exit")}
    reds = sorted(
        f"{c.get('classname')}::{c.get('name')}"
        for c in root.iter("testcase")
        if c.find("failure") is not None or c.find("error") is not None)
    return records, reds


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    return _tree(tmp_path, {
        "test_more_reds_than_the_bound.py": _MORE_REDS_THAN_THE_BOUND,
        "test_green_neighbour.py": _GREEN_NEIGHBOUR,
    })


# ══════════════════════════════════════════════════════════════════════════
# The control that is RED pre-fix.
# ══════════════════════════════════════════════════════════════════════════

def test_a_file_with_more_reds_than_the_bound_still_produces_a_record(
        corpus, tmp_path):
    """The stamp row, reduced to two files.

    Pre-fix the recovery session stops at the caller's bound, the prefix is
    correctly refused as NOT a failure set, and the merged report carries no
    record for the one file anybody needed one for."""
    junit = tmp_path / "merged.xml"
    proc = _drive(corpus, junit)

    records, reds = _report(junit)
    assert "test_more_reds_than_the_bound.py" in records, proc.stdout
    # The whole failure SET, not a prefix of it — and the item after the reds
    # proves the session was not merely allowed one more failure.
    assert [r.rsplit("::", 1)[-1] for r in reds if "process_exit" not in r] == [
        "test_red_1", "test_red_2", "test_red_3"], proc.stdout
    assert "NORECORD  test_more_reds_than_the_bound.py" not in proc.stdout, (
        proc.stdout)


def test_the_neighbour_record_is_not_traded_away_for_it(corpus, tmp_path):
    """Both files, not one instead of the other."""
    junit = tmp_path / "merged.xml"
    proc = _drive(corpus, junit)
    records, _reds = _report(junit)
    assert records == {"test_more_reds_than_the_bound.py",
                       "test_green_neighbour.py"}, proc.stdout
    assert "  NORECORD   0" in proc.stdout, proc.stdout


# ══════════════════════════════════════════════════════════════════════════
# The load-bearing negatives — TRUE IN BOTH DIRECTIONS.
# ══════════════════════════════════════════════════════════════════════════

def test_the_verdict_does_not_move(corpus, tmp_path):
    """Recovery evidence can never turn UNKNOWN into a landing pass.

    The aggregate record is lost either way, so the driver refuses either way.
    A fix that made this green would be the false-clean the driver exists to
    prevent."""
    proc = _drive(corpus, tmp_path / "merged.xml")
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert "AGGREGATE_NORECORD" in proc.stdout, proc.stdout
    assert "AGGREGATE_COMPLETE" not in proc.stdout, proc.stdout


def test_the_aggregate_arm_keeps_its_own_ratcheted_bound():
    """The aggregate ceiling is untouched: it still rises with the work and
    still refuses to fall below what a small selection asked for."""
    argv = ["python3", "-m", "pytest", "-q", f"--maxfail={_BOUND}"]
    assert D.aggregate_failure_bound(argv, 132) == 132
    assert D.aggregate_failure_bound(argv, 1) == _BOUND
    assert D.aggregate_failure_bound(["python3", "-m", "pytest"], 132) is None


def test_a_caller_that_declared_no_bound_acquires_none():
    plain = ["python3", "-m", "pytest", "-q"]
    assert D.recovery_pytest_argv(plain) == plain


@pytest.mark.parametrize("spelling", [
    ["--maxfail=2"], ["--maxfail", "2"], ["--exitfirst"], ["-x"], ["-qx"],
])
def test_every_spelling_the_reader_understands_is_removed(spelling):
    """The bound and the classifier must read the same argv. A spelling the
    remover missed would leave a session bounded and its own truncation
    classifier blind to why."""
    argv = ["python3", "-m", "pytest", *spelling]
    recovered = D.recovery_pytest_argv(argv)
    assert D._declared_failure_bound(recovered) is None, recovered


def test_the_non_aggregate_per_file_mode_keeps_the_callers_bound(
        corpus, tmp_path):
    """The legacy mode IS the caller's fail-fast run. Removing the bound there
    would change what they asked for, so it is not removed there."""
    junit = tmp_path / "plain.xml"
    proc = _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(junit), "--stall-after", str(_STALL), "--",
         sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--maxfail={_BOUND}"],
        cwd=str(corpus))
    assert "AGGREGATE_NORECORD" not in proc.stdout, proc.stdout
    _records, reds = _report(junit)
    named = [r.rsplit("::", 1)[-1] for r in reds if "process_exit" not in r]
    assert len(named) <= _BOUND, proc.stdout


# ══════════════════════════════════════════════════════════════════════════
# Bound to the REAL production caller, from a checked-in artefact.
# ══════════════════════════════════════════════════════════════════════════

def test_the_shipped_lander_hands_the_driver_a_bound_this_arm_removes():
    """A fixture cannot tell whether the production lane is affected at all.

    Reads the shipped `tools/gatekeeper-land.sh` and asserts BOTH halves of the
    premise this change rests on: that lane runs `--aggregate-check` (so the
    recovery arm is reachable) and hands pytest a failure bound (so, before
    this change, a file with that many reds could not be recorded)."""
    land = require_repo("tools", "gatekeeper-land.sh")
    text = land.read_text(encoding="utf-8", errors="replace")
    assert "--aggregate-check" in text
    assert "--maxfail=" in text and "GATEKEEPER_PYTEST_MAXFAIL" in text
    # The default is a real bound, not a disabled one: `0` removes it.
    assert "GATEKEEPER_PYTEST_MAXFAIL:-10" in text
    assert D._declared_failure_bound(
        ["python3", "-m", "pytest", "--maxfail=10"]) == 10

"""The `.sh` paired guards for `_gate_dispatch.sh` must actually be RUN.

vibe-ic#1764.  `_gate_dispatch.sh` ships three dedicated paired-guard
harnesses -- `test_gate_scope.sh` (#P3), `test_gate_scope_pairing.sh`
(vibe-ic#1729) and `test_gate_concurrency.sh` (#P4) -- 46 assertions across 813
lines, and NOTHING INVOKED ANY OF THEM.  Measured 2026-08-22: the landing gate
that exists for exactly this population,
`gatekeeper-land.sh:run_repo_tools_pytest`, discovers with

    find tools \\( -name 'test_*.py' -o -name '*_test.py' \\) -type f

so a harness named `test_*.sh` is excluded BY THE PATTERN at the one gate meant
to run repo-level tests under `tools/`, and `trusted_test_selection.py` is
`.py`-only and `programs/tests/`-scoped besides.  Every sweep that reported
"the whole `tools/` suite" meant the python files.

So the guard for the dispatcher was 46 assertions that had never been run
against a change to it.  This file is the wire: it is `.py`, it lives under
`tools/`, and it therefore reaches both the landing gate and any `pytest
tools/` sweep, carrying the shell harnesses in with it.

WHY A WRAPPER AND NOT A REWRITE.  The 46 assertions are written in shell
because what they assert is shell: `_gate_dispatch.sh` is sourced, its
functions are called, and its stderr buffering under `GATEKEEPER_HYGIENE_JOBS`
is the subject.  Reimplementing them in python would be a second definition of
the same property, free to drift from the first.  The harnesses stay the
authority; this file only makes them run.

THE LIST IS DERIVED, NOT WRITTEN DOWN.  `test_every_shell_harness_under_tools_
is_collected` fails if any `test_*.sh` exists under `tools/` that this file does
not drive.  A hand-maintained list would reproduce the defect one harness later:
somebody adds the fourth `.sh` guard, nothing collects it, and the sweep still
says green.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "tools" / "ci"

#: Driven by name so a rename is a loud failure here rather than a silent
#: reduction in what runs.  Kept in step with the tree by the test below.
HARNESSES = (
    "test_gate_scope.sh",
    "test_gate_scope_pairing.sh",
    "test_gate_concurrency.sh",
)

#: Each harness ends in `  N passed, M failed`.  Parsed rather than trusted to
#: rc alone: a harness that exits 0 having asserted NOTHING -- an empty corpus,
#: the vacuous pass this repository refuses everywhere else -- must not read as
#: a pass here either.
_TALLY = re.compile(r"^\s*(\d+) passed, (\d+) failed\s*$", re.M)


def _run(name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CI / name)], cwd=str(ROOT),
        capture_output=True, text=True)


def test_every_shell_harness_under_tools_is_collected():
    """A `.sh` guard nothing drives is not a guard -- that is this file's whole
    subject, and the same hole one harness later would be the same defect."""
    found = sorted(p.name for p in ROOT.glob("tools/**/test_*.sh"))
    assert found == sorted(HARNESSES), (
        f"the shell harnesses under tools/ are {found}, but this file drives "
        f"{sorted(HARNESSES)}. `gatekeeper-land.sh:run_repo_tools_pytest` "
        f"discovers only `test_*.py`/`*_test.py`, so a `.sh` harness that is "
        f"not driven from here is run by NOTHING (vibe-ic#1764)")


@pytest.mark.parametrize("name", HARNESSES)
def test_the_shell_paired_guard_passes(name):
    """Run the harness and require a non-empty, all-green tally."""
    proc = _run(name)
    tally = _TALLY.search(proc.stdout)
    assert tally, (
        f"{name} printed no `N passed, M failed` tally, so there is nothing to "
        f"read a verdict off. rc={proc.returncode}\n{proc.stdout[-3000:]}"
        f"\n{proc.stderr[-2000:]}")
    passed, failed = int(tally.group(1)), int(tally.group(2))
    assert passed > 0, (
        f"{name} asserted NOTHING and exited {proc.returncode}. An empty "
        f"corpus is not a pass (vibe-ic#1025)\n{proc.stdout[-3000:]}")
    assert failed == 0 and proc.returncode == 0, (
        f"{name}: {passed} passed, {failed} failed, rc={proc.returncode}\n"
        f"{proc.stdout[-6000:]}")


def test_the_dispatcher_guard_covers_both_zero_population_states():
    """The reason this wiring was worth doing, pinned so it cannot rot.

    `test_gate_concurrency.sh` drove only a producer exiting 0 -- a corpus that
    was READ and holds none -- until vibe-ic#1764 added the absent one. If that
    case is ever dropped the harness goes back to knowing one of the two states
    and this file would still report it green, which is the failure mode
    vibe-ic#1764 is about.
    """
    text = (CI / "test_gate_concurrency.sh").read_text(encoding="utf-8")
    for needed in ("GATE_DISPATCH_ABSENT_RC", "NO_CORPUS", "exit 3"):
        assert needed in text, (
            f"test_gate_concurrency.sh no longer mentions {needed!r}: the "
            f"paired guard for `_gate_dispatch.sh` has stopped driving the "
            f"ABSENT corpus and now covers only the read-empty state "
            f"(vibe-ic#1764)")

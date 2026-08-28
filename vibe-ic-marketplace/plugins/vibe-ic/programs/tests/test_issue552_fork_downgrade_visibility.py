"""test_issue552_fork_downgrade_visibility.py — a warning our fork substitutes
for an abort must still be visible to the gate that needs it.

WHAT WENT WRONG (vibe-ic#552)
=============================
`vibeic/OpenROAD 8d040d56c` downgrades an inaccessible pin from the fatal
`DRT-0073` to a `DRT-627` warning, so a post-route timing repair is not
killed by it. The
downgrade is correct — the fatal form is raised inside an OpenMP region and
`std::terminate` takes the tool down with no diagnostic.

But `phase3_one_shot_runner`'s `_route_fail_markers` were six strings, every one
an `[ERROR ...]`. A downgrade exists precisely to stop the tool erroring, so it
moves the condition OUT of the set the gate can see BY CONSTRUCTION. The flow
printed `routing complete: YES` for a design carrying a pin the router never
reached.

THE PROPERTY UNDER TEST
=======================
Not "DRT-627 is in a list" — that fixes one instance and leaves the shape. The
property is that every REGISTERED downgrade is referenced by a MATCHER in its
consumer, and that the check fails when one is not.

The matcher requirement is the load-bearing part and it was learned the hard
way: the first version of this check searched for the bare id outside whole-line
comments, and a mutation that broke the regex to `DRT-999999` still PASSED,
because the id also occurs in an inline comment and in the human-readable report
line. Neither makes the flow see anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import fork_downgrade_visibility_check as C  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

def test_the_registry_is_not_empty():
    """FALSIFIABILITY ANCHOR. Everything below is vacuous over an empty
    registry, and the program returns rc 2 rather than PASS for that reason —
    but a test suite that never notices the emptying is no better."""
    assert C.DOWNGRADES, "the downgrade registry is empty"
    for d in C.DOWNGRADES:
        assert d.ident and d.replaces and d.fork and d.consumer, (
            f"registry entry {d} is missing a field — a downgrade with no named "
            f"consumer cannot be checked")


def test_every_registered_downgrade_is_visible_today():
    assert C.check(PLUGIN) == [], (
        "a downgrade our fork ships is invisible to its consumer")


def test_the_check_fails_when_the_matcher_is_broken(tmp_path):
    """CONTROL. Without this, PASS on the real tree is indistinguishable from a
    check that cannot fail."""
    fake = tmp_path / "programs"
    fake.mkdir()
    d = C.DOWNGRADES[0]
    (tmp_path / d.consumer).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / d.consumer).write_text(
        "# a comment mentioning " + d.ident + " explains nothing to a gate\n"
        "x = 1\n", encoding="utf-8")
    findings = C.check(tmp_path)
    assert len(findings) == 1, (
        "a consumer that only MENTIONS the id in a comment was accepted — that "
        "is exactly the mutation that survived the first version of this check")
    assert d.ident in findings[0]["problem"]


def test_a_matcher_is_accepted_where_a_mention_is_not(tmp_path):
    """The other half of the control: the check must not be so strict that a
    real matcher fails it, or the fix would be unlandable."""
    d = C.DOWNGRADES[0]
    (tmp_path / d.consumer).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / d.consumer).write_text(
        f'import re\n_pat = re.compile(r"\\[WARNING {d.ident}\\]")\n',
        encoding="utf-8")
    assert C.check(tmp_path) == []


def test_the_program_runs_and_passes_on_the_shipped_tree():
    """Driven through the CLI, because rc is what a gate reads."""
    r = _pr.run([sys.executable, str(PROGRAMS / "fork_downgrade_visibility_check.py"),
                        str(PLUGIN)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "registered fork downgrade" in r.stdout


def test_the_pass_line_discloses_that_the_registry_is_the_scope():
    """It cannot discover an unregistered downgrade, and must not imply it can."""
    r = _pr.run([sys.executable, str(PROGRAMS / "fork_downgrade_visibility_check.py"),
                        str(PLUGIN)], capture_output=True, text=True)
    assert "registry only" in r.stdout, (
        "the PASS line does not say the scope is the registry, so a reader "
        "could take it as 'no unwired downgrade exists'")

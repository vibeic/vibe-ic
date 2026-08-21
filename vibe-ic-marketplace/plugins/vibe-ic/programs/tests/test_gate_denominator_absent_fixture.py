#!/usr/bin/env python3
"""The absent-project fixture, and the two wrong standards it was built with.

`gate_discloses_denominator_check --population project` drives every
`*_check.py` against a structurally EMPTY project — a directory that EXISTS
with `input/docs/` and `reports/` in it. It never asked what a gate says when
the PROJECT ITSELF is not there, and those are different code paths: one walks
a real tree and finds nothing, the other never gets a tree.

Two real defects lived in that gap, both found in v1.8.29/30 by running gates
against a typo'd path rather than by anything failing:

    opcode_field_width_consistency_check  "checked 1 project(s) — ALL_PASS"
    analog_lef_gds_outline_check          "no analog_block_list.json —
                                           digital-only project"

Both are fixed, so the fixture finds nothing today. That is exactly why these
tests exist: a fixture whose population is clean is indistinguishable from a
fixture that cannot fail, and only a pinned predicate tells them apart.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import gate_discloses_denominator_check as G  # noqa: E402

honest = G._honest_about_an_absent_project


def test_a_nonzero_count_over_an_absent_project_is_not_honest():
    """The defect this fixture exists for, in the words it actually printed.

    A count of ONE over a path that does not exist is not a denominator. It
    asserts that one project was opened when none was, and a caller reading
    ALL_PASS cannot tell a typo from a clean chip.
    """
    assert not honest("checked 1 project(s) — ALL_PASS")


def test_the_empty_project_standard_would_have_passed_that():
    """Why the fixture does not reuse `discloses`, pinned so nobody 'unifies'
    the two predicates back together.

    `discloses` accepts a bare count — correct over a real tree, where
    "scanned 0 files" is a denominator a reader can act on. Replayed against
    the pre-fix string it returns True, because of the "1". A fixture built on
    it would have shipped unable to fail on the one program it was built for.
    """
    assert G.discloses("checked 1 project(s) — ALL_PASS") is True


def test_a_zero_count_is_honest_even_with_no_prose():
    """The other wrong standard, in the other direction.

    Requiring a stated REASON flagged 7 gates, and all 7 were correct: zero IS
    a true statement about an absent project. Rejecting them would have made
    the fixture fire on right behaviour, which is how a gate earns being
    switched off rather than fixed.
    """
    for out in ("Files: 0  Errors: 0  Warnings: 0  Result: PASS",
                "PASS — 0 waveform artifact(s)",
                "PASS — 0 bare-% argparse help string(s)"):
        assert honest(out), out


def test_a_stated_reason_is_honest_without_any_count():
    assert honest("[NOT CHECKED] no such project: /x — nothing was examined")


def test_the_two_phrasings_the_shared_regex_does_not_reach():
    """Measured in this population, and widened HERE rather than in the shared
    `_REASON_RE` — loosening that would also loosen the empty-project fixture,
    which is not what was under change."""
    assert honest("PASS — no hw-debug-loop evidence directory; gate not yet "
                  "applicable (Phase 2c either not entered or not reached)")


def test_output_with_no_counts_and_no_reason_is_not_honest():
    """…or the zero-count clause is satisfied by a gate that prints nothing
    quantitative at all."""
    assert not honest("[PASS] everything looks fine")


def test_the_fixture_fails_the_revision_that_carried_the_defect():
    """A fixture that cannot fail is not a fixture.

    Drives the ACTUAL pre-fix program out of git, not a hand-copied string, so
    this cannot drift away from what shipped.
    """
    import subprocess
    import tempfile
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, cwd=str(PROGRAMS))
    if repo.returncode != 0:
        import pytest
        pytest.skip("not a git checkout")
    root = repo.stdout.strip()
    rel = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
           "opcode_field_width_consistency_check.py")
    old = subprocess.run(["git", "log", "--format=%H", "-2", "--", rel],
                         capture_output=True, text=True, cwd=root)
    shas = [s for s in old.stdout.split() if s]
    if len(shas) < 2:
        import pytest
        pytest.skip("no prior revision of the program in this checkout")
    src = subprocess.run(["git", "show", f"{shas[1]}:{rel}"],
                         capture_output=True, text=True, cwd=root)
    if src.returncode != 0:
        import pytest
        pytest.skip("prior revision not retrievable")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "opcode_field_width_consistency_check.py"
        p.write_text(src.stdout)
        res = G._drive_on_absent_project(p, timeout=60)
    assert res["rc"] == 0 and not res["disclosed"], (
        "the fixture no longer fails the revision it was built for: "
        f"rc={res['rc']} honest={res['disclosed']} tail={res.get('output_tail')}")

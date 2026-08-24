#!/usr/bin/env python3
"""The RTL-dispatch symlink guard must block ESCAPES, not every symlink.

WHY (measured 2026-08-25). The isolation guard refused any symlink at all in the
project snapshot, with the stated concern that the isolated tree "must not retain
a portal back to a mutable external namespace". But the runner's OWN `steps/`
mirror links each step to the artifact it declared — links that live inside the
project and point inside the project. A project carried 15 of them, all internal,
zero escaping, and `rtl_gen` was BLOCKED with

    PHASE1_RTL_OUTPUT_PROVENANCE_REFUSED / PROJECT_SYMLINK_NOT_ISOLATABLE
    ... No RTL was written.

on ALL FIVE task natures tried. The runner's bookkeeping blocked the runner's own
RTL generation, and the deterministic program-first dispatch could never run.

TWO CHANGES, and the ORDER matters. First the PRODUCER was fixed —
`step_output_collector` now writes intra-project links RELATIVE, so they stay
inside the tree when it is copied into the isolated stage (an ABSOLUTE link
genuinely IS a portal once the tree moves, so the guard was right to refuse
those). Only then was the guard narrowed to match.

§ 4.05 — this narrows a guard, so the load-bearing half of the proof is the
NEGATIVE: every boundary-outside case must STILL be refused. Those are the
`test_still_refuses_*` cases below; a relaxation that lets one through ships a
real escape as PASS.
"""
import os
import sys

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import design_one_shot_runner as D  # noqa: E402

escapes = D._symlink_escapes_tree


# ── POSITIVE: the real internal links the runner itself writes ───────────────
def test_allows_the_runners_own_relative_step_mirror_link():
    assert not escapes(
        "steps/phase1/stage_phase1/D1_doc/L2_FRS.json",
        "../../../../phase1/generated_docs/L2_FRS.json")


def test_allows_a_sibling_link():
    assert not escapes("a.json", "b.json")


def test_allows_a_descent_that_stays_inside():
    assert not escapes("steps/x/link.json", "../../phase1/out.json")


# ── NEGATIVE no-leak: each must STILL be refused (§ 4.05) ────────────────────
def test_still_refuses_an_absolute_target():
    """The original defect: absolute = a fixed path outside the isolated stage."""
    assert escapes("steps/a/b/L2.json", "/home/someone/phase1/L2.json")


def test_still_refuses_a_climb_past_the_root():
    assert escapes("steps/a/b/L2.json", "../../../../../../etc/passwd")


def test_still_refuses_a_one_level_climb_from_the_top():
    assert escapes("a.json", "../outside")


def test_still_refuses_an_exact_parent_target():
    assert escapes("a.json", "..")


def test_still_refuses_an_unreadable_target():
    """No target string means no containment proof — refuse, never guess."""
    assert escapes("a.json", None)
    assert escapes("a.json", "")


def test_a_traversal_that_returns_is_still_inside():
    """`x/../y` resolves within the tree — allowed, and NOT by accident."""
    assert not escapes("steps/a.json", "../phase1/../phase1/out.json")


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            print("PASS", k)

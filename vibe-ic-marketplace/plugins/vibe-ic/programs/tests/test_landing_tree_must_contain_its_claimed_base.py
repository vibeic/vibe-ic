#!/usr/bin/env python3
"""A commit's TREE must contain the base its PARENT names.

THE DEFECT (2026-08-05), caught by a human read an hour before it would land
=============================================================================
`1766746f6` was authored against v1.9.77 while `origin/main` advanced to
v1.9.78, and was then committed with v1.9.78 as its PARENT and v1.9.77's TREE:

    git diff --stat origin/main...1766746f6  ->  81 files, 1974 +, 9258 -
    git diff --stat 1a6721e15   1766746f6    ->   2 files, 1599 +,   24 -

Landing it would have reverted all 13 intervening commits — 15 files deleted
(13 of them tests), `plugin.json` walked back 1.9.78 -> 1.9.77 — including
`070aea3e8`, which the commit's OWN new docstring cited as "#790's other half".
It shipped the caller and deleted the dependency in one change.

Every landing-shape gate was green on it, and not by accident: the two revert
guards each disclaim this case IN WRITING and hand it to the other.
`landing_collateral_revert_check`'s window is "this push" (0 pairs on a
one-commit branch) and it names `gatekeeper_stale_branch_check` as the guard for
a revert of an earlier push; that gate answered FRESH, because the head really
does descend from the base tip. The graph was fresh, the tree was stale, and
nothing was reading the tree.

WHAT THESE TESTS PIN
====================
* the re-parented stale tree is BLOCKED, and the verdict names the commits whose
  content the tree does not carry;
* a LEGITIMATE LARGE DELETION of files the base added recently is NOT blocked —
  identical deletion footprint, different provenance. If the gate cannot tell
  those apart it will be switched off within a week, so this is the acceptance
  test, not a nicety;
* the exact inverse of ONE commit is DISCLOSED at rc 0, not blocked (measured:
  3 of the last 800 landings on `main` are that shape and all three are
  legitimate);
* the PASS states its own denominator, so it can never be read over a set that
  silently shrank;
* the gate's rc is COUNTED by `gatekeeper_review` — in `blocking`, changing the
  verdict — rather than merely printed;
* `tools/gatekeeper-land.sh`, the script whose success writes the stamp the
  pre-push hook demands, actually invokes it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[5]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_CHECKER = _PROGRAMS / "gatekeeper_stale_branch_check.py"


# ---------------------------------------------------------------------------
# git plumbing for the fixtures.
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# POSITIVE — the defect's shape.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# NEGATIVE — the load-bearing ones.
# ---------------------------------------------------------------------------
























# ---------------------------------------------------------------------------
# CLI + WIRING — the gate must RUN in the landing path and be COUNTED.
# ---------------------------------------------------------------------------








def test_landing_script_wires_the_gate_blocking(tmp_path):
    """`tools/gatekeeper-land.sh` is the script whose success writes the
    `.git/gatekeeper-stamp` the pre-push hook demands, so a push to `main`
    cannot happen without it. The checker was blocking in `gatekeeper_review`
    and had never been wired HERE — which is why nothing in the landing path
    had an opinion on the landing method at all.
    """
    script = (_REPO_ROOT / "tools" / "gatekeeper-land.sh").read_text(
        encoding="utf-8")
    # `run <unit> <label> <cmd…>` since 7c376e348 (v1.10.69): the landing record
    # gave every call site a leading machine unit id, so the LABEL this gate is
    # known by is now the second quoted word. The label itself did not move.
    _LABEL = "tree contains the base it claims as parent"
    assert re.search(rf'^\s*run "[^"]*" "{re.escape(_LABEL)}"', script, re.M), (
        "the base-ancestry gate is no longer wired into gatekeeper-land.sh")
    assert 'gatekeeper_stale_branch_check.py' in script
    # `run`, not `report`: `report` never touches FAILED, so a gate wired
    # through it is printed and not counted.
    assert not re.search(
        rf'^\s*report "[^"]*" "{re.escape(_LABEL)}"', script, re.M), (
        "the base-ancestry gate was demoted from `run` to `report`, which never "
        "touches FAILED — it would be printed and not counted")

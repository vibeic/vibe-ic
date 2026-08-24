#!/usr/bin/env python3
"""The `repo tools tests` stage must not select rescue snapshots — and must
still select everything else.

WHY THIS EXISTS (measured 2026-08-24 on e265f228be)
===================================================
`run_repo_tools_pytest` discovers its corpus with

    find tools \\( -name 'test_*.py' -o -name '*_test.py' \\) -type f

which is the right shape: a hardcoded roster goes stale the moment a file is
added, and it goes stale in the safe-looking direction (fewer files, still
PASS). But the glob also selected `tools/harvest/preserved_untracked_s7/…`,
which is a RESCUE SNAPSHOT — files another workspace left untracked, copied in
verbatim so the work was not lost. Those files import fixtures that live beside
them in the workspace they came from, so every one of them died in setup:

    18  tools/harvest/preserved_untracked_s7/_adv_lgate_unknown/tools/test_adv_unknown_buys_leniency
     8  tools/harvest/preserved_untracked_s7/_adv_lgate_unknown/tools/test_adv_round2
     4  tools/harvest/preserved_untracked_s7/_adv_lgate_unknown/tools/test_adv_round3
    -----
    30  ERRORs, every one of them, and no others in the stage

A rescue snapshot is not a test. It reports red about a workspace that no longer
exists, on every landing, forever.

THIS TEST IS THE HALF THAT MAKES THE PRUNE HONEST
=================================================
An exclusion is a way to make a red disappear, which is exactly what a cheat
looks like. The difference between a prune and a cheat is whether the prune can
be shown to remove ONLY what it claims to remove — so this module asserts BOTH
directions:

  * `test_the_prune_removes_the_snapshots`   — nothing under `tools/harvest/`
                                               survives discovery;
  * `test_the_prune_removes_nothing_else`    — every OTHER test file under
                                               `tools/` still does, compared
                                               against an unpruned walk;
  * `test_the_control_would_have_selected_them` — the UNPRUNED glob really does
                                               select those files, so this
                                               module is not asserting a
                                               vacuous truth about an empty
                                               directory. If `tools/harvest/`
                                               ever stops containing a test
                                               file, this test says so rather
                                               than passing silently.

The third one is the one that matters. Without it, deleting `tools/harvest/`
entirely would leave the first two passing and nobody would learn that the
prune had become a no-op.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAND = REPO / "tools" / "gatekeeper-land.sh"
HARVEST = REPO / "tools" / "harvest"


def _discover(pruned: bool) -> set[str]:
    """Run the stage's own discovery, with and without the prune.

    Shelling out to `find` rather than reimplementing it in Python is
    deliberate: a Python walk would be a SECOND definition of the corpus that
    can drift from the shell one, and the shell one is what actually ships.
    """
    if pruned:
        cmd = (
            "find tools -path 'tools/harvest' -prune -o "
            "\\( -name 'test_*.py' -o -name '*_test.py' \\) -type f -print"
        )
    else:
        cmd = "find tools \\( -name 'test_*.py' -o -name '*_test.py' \\) -type f"
    out = subprocess.run(
        ["bash", "-c", cmd], cwd=REPO, capture_output=True, text=True, check=True
    )
    return {line for line in out.stdout.split("\n") if line}


def test_the_shipped_stage_carries_the_prune() -> None:
    """The prune must be in `gatekeeper-land.sh`, not only in this test.

    A test that describes a prune the shipped script does not perform is a
    test about this file.
    """
    text = LAND.read_text(encoding="utf-8")
    assert "-path 'tools/harvest' -prune -o" in text, (
        "run_repo_tools_pytest no longer prunes tools/harvest; this test would "
        "then be asserting a property of nothing"
    )


def test_the_control_would_have_selected_them() -> None:
    """Guard against this whole module becoming vacuous.

    If `tools/harvest/` holds no test file, the prune removes nothing and the
    two assertions below are true for the wrong reason.
    """
    unpruned = _discover(pruned=False)
    in_harvest = {p for p in unpruned if p.startswith("tools/harvest/")}
    if not in_harvest:
        pytest.fail(
            "tools/harvest/ contains no test file, so the prune in "
            "run_repo_tools_pytest is now a no-op. Either the snapshots were "
            "removed — in which case delete the prune and this module in the "
            "same commit — or discovery changed and this test can no longer "
            "see them."
        )


def test_the_prune_removes_the_snapshots() -> None:
    pruned = _discover(pruned=True)
    leaked = sorted(p for p in pruned if p.startswith("tools/harvest/"))
    assert not leaked, f"rescue snapshots survived the prune: {leaked}"


def test_the_prune_removes_nothing_else() -> None:
    unpruned = _discover(pruned=False)
    pruned = _discover(pruned=True)
    expected = {p for p in unpruned if not p.startswith("tools/harvest/")}
    lost = sorted(expected - pruned)
    assert not lost, (
        "the prune removed files outside tools/harvest/ — it is broader than "
        f"it claims: {lost}"
    )


def test_the_prune_is_the_only_difference() -> None:
    """Stated as an equality so a future widening cannot pass as a shrink."""
    unpruned = _discover(pruned=False)
    pruned = _discover(pruned=True)
    assert unpruned - pruned == {
        p for p in unpruned if p.startswith("tools/harvest/")
    }

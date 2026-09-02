#!/usr/bin/env python3
"""`programs/INDEX.md` was cross-checked by a program that could not fix it.

THE ASYMMETRY, AND IT WAS STRUCTURAL RATHER THAN ANYBODY FORGETTING.
`gen_program_inventory.py` regenerates every document it binds — the artefact
`PROGRAM_INVENTORY.json` plus the two READMEs, rewritten from the SAME
`_CLAIMS` table its own `--check` verifies. `programs/INDEX.md` is bound too:
`check_index_cross` compares the total INDEX.md states for itself against the
`programs_catalogued` population. But nothing regenerated it. Its generator,
`tools/gen_programs_index.py`, is repo-root-only and was invoked by no landing
step, so a landing that adds a program refreshed the inventory and both READMEs
automatically and left the catalogue behind.

MEASURED at `7903c1972305`: INDEX.md stated **1255** while the inventory
measured **1264**, and the gap had been widening on every landing — of the last
20 landings, 8 touched `PROGRAM_INVENTORY.json` and NONE touched INDEX.md. It
reddened three cases across two files, and one of them,
`test_check_mode_exits_zero_on_the_committed_tree`, is red for exactly this and
not for the dirty-tree flake its own docstring records: measured on a fresh
clone with nothing else running, `--check` reports the INDEX.md line and
nothing else.

WHY A ONE-OFF REGENERATION IS NOT THE FIX. Re-running the generator by hand
turns the three cases green for exactly one landing; the next added program
brings the whole cluster back. Editing the stated total by hand is worse — the
count would agree while the missing rows stayed missing, which is what the
`AUTO-GENERATED` marker and `test_index_carries_auto_generated_marker` exist to
prevent. So the round trip is CLOSED instead: a default run of
`gen_program_inventory.py` regenerates the catalogue before it rewrites the
prose, and `--check` after a plain regeneration is a question the program can
answer yes to.

These tests are written so main's version ANSWERS them rather than raising
AttributeError — a control that cannot execute against the tree it
characterises has observed nothing.
"""
import pathlib
import sys

import pytest

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import gen_program_inventory as G  # noqa: E402

_MISSING = (
    "`gen_program_inventory` has no {name!r}. Nothing in a default run "
    "refreshes `programs/INDEX.md`, so the one artefact this program "
    "cross-checks and cannot regenerate drifts by one on every landing that "
    "adds a program — measured 1255 vs 1264 at 7903c1972305."
)


def test_a_default_run_can_refresh_the_catalogue_it_cross_checks(
        tmp_path, monkeypatch):
    """THE CLOSURE. Point INDEX_MD at a deliberately wrong catalogue, ask the
    program to refresh it, and require its own cross-check to come back clean.

    The stale file states a total no tree could produce, so a run that
    regenerated nothing cannot pass by accident.
    """
    regen = getattr(G, "regenerate_index", None)
    assert regen is not None, _MISSING.format(name="regenerate_index")

    stale = tmp_path / "INDEX.md"
    stale.write_text(
        "# Programs index\n\n"
        "**Total programs (excluding helpers / shims):** 1\n",
        encoding="utf-8")
    monkeypatch.setattr(G, "INDEX_MD", stale)

    outcome, account = regen()
    if outcome == getattr(G, "INDEX_NOT_APPLICABLE", "NOT_APPLICABLE"):
        pytest.skip(f"the index generator is not in this tree: {account}")
    assert outcome == getattr(G, "INDEX_REGENERATED", "REGENERATED"), account

    inv = G.discover()
    assert G.check_index_cross(inv) == [], (
        "the catalogue was regenerated and its own cross-check still "
        "disagrees — the two helper predicates have diverged, which is a "
        "different defect from a stale file")
    stated = stale.read_text(encoding="utf-8")
    assert "**Total programs (excluding helpers / shims):** 1\n" not in stated, (
        "the stale total survived the regeneration")


def test_the_regenerator_and_the_cross_check_read_the_same_artefact(
        tmp_path, monkeypatch):
    """They must be the SAME path, or the round trip closes on paper only.

    A regenerator that refreshes one file while the cross-check reads another
    reports success and leaves the shipped catalogue exactly as stale as it
    was. Asserted by REDIRECTING the constant and requiring the write to
    follow it — not by comparing two path expressions, which agree by
    construction and prove nothing.
    """
    regen = getattr(G, "regenerate_index", None)
    assert regen is not None, _MISSING.format(name="regenerate_index")

    target = tmp_path / "elsewhere" / "INDEX.md"
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(G, "INDEX_MD", target)
    outcome, account = regen()
    if outcome == getattr(G, "INDEX_NOT_APPLICABLE", "NOT_APPLICABLE"):
        pytest.skip(f"the index generator is not in this tree: {account}")
    assert target.is_file(), (
        f"regenerate_index did not write the INDEX_MD it was pointed at "
        f"({target}); {account}")
    assert "AUTO-GENERATED" in target.read_text(encoding="utf-8").upper(), (
        "the regenerated catalogue does not carry the auto-generated marker, "
        "so it is not the generator's own output")


def test_a_failed_regeneration_is_reported_and_not_swallowed(monkeypatch):
    """DEGRADE LOUDLY. Three outcomes, and the middle one is not an error.

    A tree that does not ship the repo-root generator (the flattened plugin
    cache) is NOT_APPLICABLE and says so; a generator that ran and failed is
    FAILED and the caller exits non-zero. Folding them together is how the
    second one goes quiet — and a quiet failure here republishes a stale
    catalogue under a successful-looking run.
    """
    regen = getattr(G, "regenerate_index", None)
    assert regen is not None, _MISSING.format(name="regenerate_index")
    for name in ("INDEX_REGENERATED", "INDEX_NOT_APPLICABLE", "INDEX_FAILED"):
        assert hasattr(G, name), _MISSING.format(name=name)
    assert len({G.INDEX_REGENERATED, G.INDEX_NOT_APPLICABLE,
                G.INDEX_FAILED}) == 3, "the three outcomes are not distinct"

    monkeypatch.setattr(G, "INDEX_GENERATOR",
                        pathlib.Path("/nonexistent/no-such-generator.py"))
    outcome, account = regen()
    assert outcome == G.INDEX_NOT_APPLICABLE, (outcome, account)
    assert "NOT regenerated" in account, account

#!/usr/bin/env python3
"""vibe-ic#905 (companion) — a debt ratchet a `git mv` could lower.

`step_internal_fail_bubble_up_check` sweeps the PUBLISHED run trees and ratchets
a recorded count of unacknowledged step-internal FAILs: the number may shrink
freely, any increase is red. It found those trees with

    corpus.glob("*/clean_run_*")        # exactly TWO levels under ic/

`benchmark-data/ic/<IC>/` admits only `input/` and `v<X.Y.Z>_<PDK>/`, and the
standing rule for anything else there is RETIRE BY MOVING, never deleting. So
retiring a stray run folder puts it one level deeper — and MEASURED on the real
corpus, that alone took its run tree out of the population: 13 swept trees
became 12, and the recorded 6 findings became 5.

That is a check that lies. The finding was not paid, it was HIDDEN, and the
gate reported the shrink as progress: "[PASS] 7 -> 5; lower the baseline so the
recorded number stops claiming debt that is paid." A ratchet a directory move
can lower is measuring depth, not debt.

These tests pin BOTH directions: a retired (deeper) run tree is swept, AND the
ordinary two-level layout is swept exactly as before, with no double counting.

chip-AGNOSTIC: invented IC and run-folder names only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import step_internal_fail_bubble_up_check as G  # noqa: E402


def _run_tree(root: Path, rel: str) -> Path:
    """A minimal run tree: the `clean_run_*` folder plus the `reports/` the
    sweep looks inside."""
    d = root / rel
    (d / "reports").mkdir(parents=True)
    (d / "reports" / "some_gate.json").write_text('{"verdict": "FAIL"}')
    return d


def _swept(corpus: Path):
    return sorted(p.relative_to(corpus).as_posix()
                  for p in G._published_run_trees(corpus))


def test_905_a_retired_run_tree_is_still_swept(tmp_path):
    """THE MUTATION TEST. The same folder, the same bytes, one directory
    deeper because it was retired rather than deleted — origin/main stops
    seeing it."""
    _run_tree(tmp_path, "icx/retired/clean_run_v1_20260101")
    assert _swept(tmp_path) == ["icx/retired/clean_run_v1_20260101"]


def test_905_moving_a_run_tree_cannot_change_the_population(tmp_path_factory):
    """The property the ratchet actually needs: the SIZE of the swept
    population is a function of the run trees, not of where they sit."""
    before = tmp_path_factory.mktemp("before")
    _run_tree(before, "icx/clean_run_v1_20260101")
    _run_tree(before, "icy/clean_run_v2_20260101")

    after = tmp_path_factory.mktemp("after")
    _run_tree(after, "icx/retired/clean_run_v1_20260101")   # retired by moving
    _run_tree(after, "icy/clean_run_v2_20260101")

    assert len(_swept(before)) == len(_swept(after)) == 2


def test_905_the_ordinary_two_level_layout_is_unchanged(tmp_path):
    """The opposite verdict, still reachable: the historical arrangement is
    swept exactly as it always was. A reach fix that also re-populated the
    ordinary corpus would move the ratchet for a second, unrelated reason."""
    _run_tree(tmp_path, "icx/clean_run_v1_20260101")
    _run_tree(tmp_path, "icx/clean_run_v2_20260101")
    _run_tree(tmp_path, "icy/clean_run_v3_20260101")
    assert _swept(tmp_path) == ["icx/clean_run_v1_20260101",
                                "icx/clean_run_v2_20260101",
                                "icy/clean_run_v3_20260101"]


def test_905_a_nested_run_tree_is_not_counted_twice(tmp_path):
    """Depth-independence must not become depth-blindness: a folder INSIDE a
    run tree is part of that run, not a second run. Counting it would inflate
    the very number this gate ratchets."""
    _run_tree(tmp_path, "icx/clean_run_v1_20260101")
    _run_tree(tmp_path, "icx/clean_run_v1_20260101/scratch/clean_run_inner")
    assert _swept(tmp_path) == ["icx/clean_run_v1_20260101"]


def test_905_a_non_run_directory_is_never_swept(tmp_path):
    """`retired/` itself, `input/` and a published cell are not run trees."""
    (tmp_path / "icx" / "input" / "docs").mkdir(parents=True)
    (tmp_path / "icx" / "v1.2.3_pdkx" / "reports").mkdir(parents=True)
    (tmp_path / "icx" / "retired").mkdir(parents=True, exist_ok=True)
    assert _swept(tmp_path) == []

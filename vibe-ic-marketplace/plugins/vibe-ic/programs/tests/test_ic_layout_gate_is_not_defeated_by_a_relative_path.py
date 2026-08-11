#!/usr/bin/env python3
"""The IC_LEVEL_LAYOUT verdict must not depend on how the tree was NAMED.

WHAT WENT WRONG. `benchmark_evidence_structure_check --tree <path>` reported

    13/28 conformant, 0 IC_LEVEL_LAYOUT failures

over a tree carrying 93 offending entries across 8 ICs, whenever the path was
RELATIVE. Measured on origin/main, same commit, same tree, one argument style
apart:

    --tree ../../../benchmark-data   ->  9 IC dirs, 0 failing
    --tree /abs/path/benchmark-data  ->  9 IC dirs, 8 failing, 93 entries

MECHANISM. `_git_listed_files` runs `git -C <repo> ls-files -- <folder>`, and
`git -C` interprets a relative pathspec against the REPO ROOT rather than the
caller's cwd. `../../../benchmark-data/ic/<IC>` therefore escapes the repo and
matches nothing; git exits 0 with empty output; the caller reads "no tracked
files under this IC"; and `ic_level_strays` filters every entry away as
untracked developer scratch. The gate passes because it looked at nothing, and
prints the pass as conformance.

The relative form is the SHIPPED one -- the gate is invoked from the plugin
directory, so this was the live behaviour and not a hypothetical.

WHAT IS PINNED HERE
  1. the two argument styles agree, on a tree built to have strays;
  2. an IC directory outside any repo still counts every entry -- the
     documented outside-a-repo behaviour, pinned because it is the property the
     relative-path bug destroyed by a different route;
  3. the paired guard: a conforming IC still passes under BOTH styles, so the
     fix cannot be bought by making the gate say no more often.

Run::

    python3 -m pytest programs/tests/test_ic_layout_gate_is_not_defeated_by_a_relative_path.py \
        -q -p no:pytest_ethereum
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "bes_relpath", _PROGRAMS / "benchmark_evidence_structure_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bes_relpath"] = mod
    spec.loader.exec_module(mod)
    return mod


BES = _load()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _repo_with(tmp_path: Path, ic_name: str, entries) -> Path:
    """A real git repo holding benchmark-data/ic/<ic_name>/ with `entries`."""
    repo = tmp_path / "repo"
    (repo / "benchmark-data" / "ic" / ic_name).mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo)) if False else None
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   capture_output=True, text=True)
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    ic = repo / "benchmark-data" / "ic" / ic_name
    for rel in entries:
        f = ic / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _strays_from(cwd: Path, ic_dir: str) -> int:
    """Count strays for `ic_dir` as spelled, evaluated from `cwd`."""
    old = Path.cwd()
    try:
        os.chdir(cwd)
        return len(BES.ic_level_strays(Path(ic_dir)))
    finally:
        os.chdir(old)


# ---------------------------------------------------------------- the defect

def test_relative_and_absolute_spellings_agree_on_a_tree_with_strays(tmp_path):
    """THE BUG. Same tree, same commit, two spellings of the same directory."""
    repo = _repo_with(tmp_path, "chipA", [
        "input/docs/L1.md",          # permitted
        "v1.0.0_pdkX/RESULT.md",     # permitted (a cell)
        "phase3/routed.def",         # STRAY
        "reports/summary.json",      # STRAY
    ])
    ic_abs = repo / "benchmark-data" / "ic" / "chipA"

    # A cwd deep inside the repo, mirroring the shipped invocation from the
    # plugin directory, so the relative spelling has to climb out.
    deep = repo / "benchmark-data" / "ic" / "chipA" / "v1.0.0_pdkX"
    rel = os.path.relpath(ic_abs, deep)

    n_abs = _strays_from(deep, str(ic_abs))
    n_rel = _strays_from(deep, rel)

    assert n_abs == 2, f"fixture wrong: expected 2 strays, got {n_abs}"
    assert n_rel == n_abs, (
        f"the verdict depends on how the tree was NAMED: absolute spelling "
        f"found {n_abs} stray(s), relative spelling found {n_rel}. A gate whose "
        f"answer changes with its argument style is reporting on the argument.")


def test_a_directory_outside_any_repo_counts_every_entry(tmp_path):
    """The documented outside-a-repo behaviour, pinned.

    PASSES IN BOTH ARMS and is here deliberately. `_git_toplevel` shells out
    with `git -C <folder>`, so it is evaluated AT THE FOLDER: a folder in no
    repo yields None and the tracked-set filter is skipped entirely. That is
    why an explicit "folder is not under the repo" branch was written for this
    fix and then REMOVED -- removing it left all four tests green, so it was a
    branch that could never fire, and a branch that can never fire is a green
    light rather than a check.

    What this pins is the property the relative-path bug destroyed by the OTHER
    route: an entry the gate cannot vouch for must be counted, never cleared.
    """
    repo = _repo_with(tmp_path, "chipB", ["input/docs/L1.md"])
    outside = tmp_path / "elsewhere" / "ic" / "chipB"
    (outside / "phase3").mkdir(parents=True)
    (outside / "phase3" / "routed.def").write_text("x\n", encoding="utf-8")
    (outside / "input").mkdir(parents=True)

    # Evaluated from INSIDE the repo, so `_git_toplevel` resolves to the repo
    # while the folder itself lives somewhere else entirely.
    n = _strays_from(repo, str(outside))
    assert n == 1, (
        f"a directory outside the repo reported {n} stray(s); it holds one "
        f"non-input, non-cell entry and git can say nothing about it, so it "
        f"must be counted rather than cleared")


# ---------------------------------------------------------------- the guard

def test_GUARD_a_conforming_ic_still_passes_under_both_spellings(tmp_path):
    """The fix must not be bought by making the gate say no more often."""
    repo = _repo_with(tmp_path, "chipC", [
        "input/docs/L1.md",
        "v1.0.0_pdkX/RESULT.md",
        "v1.0.1_pdkX/RESULT.md",
    ])
    ic_abs = repo / "benchmark-data" / "ic" / "chipC"
    deep = ic_abs / "v1.0.0_pdkX"
    rel = os.path.relpath(ic_abs, deep)

    assert _strays_from(deep, str(ic_abs)) == 0
    assert _strays_from(deep, rel) == 0, (
        "a conforming IC was reported non-conforming under the relative "
        "spelling — the fix has started inventing findings")


def test_GUARD_untracked_scratch_is_still_not_a_published_finding(tmp_path):
    """The git-awareness the fix repairs must keep doing its original job.

    An entry with no tracked file is a developer's local scratch, not something
    the repository published. That property predates this fix and must survive
    it, or the repair has traded one false verdict for another.
    """
    repo = _repo_with(tmp_path, "chipD", ["input/docs/L1.md"])
    ic = repo / "benchmark-data" / "ic" / "chipD"
    (ic / "_scratch_run").mkdir()
    (ic / "_scratch_run" / "notes.txt").write_text("local\n", encoding="utf-8")

    assert _strays_from(repo, str(ic)) == 0, (
        "an untracked scratch directory was reported as a published layout "
        "violation")

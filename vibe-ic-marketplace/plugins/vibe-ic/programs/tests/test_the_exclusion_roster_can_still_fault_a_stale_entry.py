#!/usr/bin/env python3
"""`_EXCLUDED` is now empty — prove the check that emptied it can still fire.

WHY THIS FILE EXISTS
====================
`landing_unselectable_pytest_corpus._EXCLUDED` held one entry, `benchmark-data/`.
`audit()` faulted it because the prefix matched no tracked test file, the corpus
having moved to `vibeic/benchmark-data`. The entry was withdrawn and the roster is
now `()`.

That is the correct state and it is also the dangerous one: **the assertion that
found the staleness now has nothing to iterate.** A registry emptied on purpose and
a registry emptied by accident look identical from the outside, and `audit()` cannot
distinguish them — it can only fault a declaration that matches nothing, never the
absence of one.

So the guarantee has to be tested against a SYNTHETIC roster rather than against the
shipped one. If it were tested against the shipped roster it would pass by having
nothing to check, which is the shape this repo keeps closing.

BOTH DIRECTIONS, because a check that only proves "clean tree is clean" would pass
against an `audit()` whose body had been deleted.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "landing_unselectable_pytest_corpus.py"


def _load():
    spec = importlib.util.spec_from_file_location("_lupc", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()
REPO = PROGRAMS.parents[3]


def _repo_is_git() -> bool:
    return (REPO / ".git").exists()


# ---------------------------------------------------------------------------
# 1. THE ROSTER IS EMPTY, DELIBERATELY. If someone re-adds an entry, this test
#    is the one that makes them read the comment explaining why it was removed.
# ---------------------------------------------------------------------------
def test_the_roster_is_empty_and_that_is_written_down():
    assert M._EXCLUDED == (), (
        f"an exclusion was added back: {M._EXCLUDED}. That may be right — but the "
        f"comment above _EXCLUDED records why it was emptied, and a new entry must "
        f"state which tree it subtracts and why that tree is in this repository.")
    src = PROG.read_text(encoding="utf-8")
    assert "NOTHING IS EXCLUDED, AND THAT EMPTINESS IS DECLARED" in src, (
        "the empty roster lost the comment that distinguishes 'emptied on purpose' "
        "from 'emptied by accident' — which audit() cannot tell apart")


# ---------------------------------------------------------------------------
# 2. THE FAULT STILL FIRES. A synthetic entry pointing at a tree that is not here
#    must be caught, exactly as benchmark-data/ was.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_a_declared_exclusion_that_subtracts_nothing_is_still_faulted(monkeypatch):
    stale = M.Excluded(
        prefix="a-tree-that-is-not-here/",
        why="a synthetic entry, long enough to satisfy any written-reason rule, "
            "whose only job is to prove the staleness check still has teeth after "
            "the roster it guarded was emptied.")
    monkeypatch.setattr(M, "_EXCLUDED", (stale,))
    plugin = M.plugin_rel(REPO)
    files = M.tracked_test_files(REPO) or []
    assert files, "partitioned an empty file list; this is not a measurement"
    part = M.partition(files, plugin)
    findings = M.audit(REPO, part, plugin)
    assert any("a-tree-that-is-not-here/" in f and "matches NO tracked test file" in f
               for f in findings), (
        f"a declared exclusion that subtracts nothing was NOT faulted — the check "
        f"that emptied this roster has stopped working. findings={findings}")


# ---------------------------------------------------------------------------
# 3. …AND IT STAYS QUIET WHEN THE ENTRY IS REAL. The half that makes case 2 mean
#    something: a check that faults every exclusion would also "pass" case 2.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_a_real_exclusion_is_not_faulted(monkeypatch):
    # `skills/` and NOT `programs/tests/`: `partition()` assigns a file to COVERED
    # before it considers an exclusion, so a prefix already claimed by a covered
    # tree subtracts nothing and would be faulted — making this test pass for the
    # wrong reason. Measured on this tree: skills/ holds 68 of the 110 unselectable
    # files, so it is a prefix an exclusion can genuinely take.
    live = M.Excluded(
        prefix="vibe-ic-marketplace/plugins/vibe-ic/skills/",
        why="a synthetic entry over a tree that DOES hold tracked test files not "
            "already claimed by a covered tree, so a check which faulted every "
            "exclusion regardless of its subtrahend would be caught here rather "
            "than mistaken for correctness.")
    monkeypatch.setattr(M, "_EXCLUDED", (live,))
    plugin = M.plugin_rel(REPO)
    files = M.tracked_test_files(REPO) or []
    assert files, "partitioned an empty file list; this is not a measurement"
    part = M.partition(files, plugin)
    findings = M.audit(REPO, part, plugin)
    assert not any("matches NO tracked test file" in f for f in findings), (
        f"an exclusion over a tree that really holds tests was faulted anyway, so "
        f"case 2 proves nothing. findings={findings}")


# ---------------------------------------------------------------------------
# 4. THE DENOMINATOR STILL ADDS UP with zero exclusions. Removing the last entry
#    must not leave files unaccounted for in any bucket.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_the_partition_is_still_exhaustive_with_no_exclusions():
    files = M.tracked_test_files(REPO) or []
    part = M.partition(files, M.plugin_rel(REPO))
    covered = sum(len(v) for v in part["covered"].values())
    excluded = sum(len(v) for v in part["excluded"].values())
    unselectable = len(part["unselectable"])
    assert excluded == 0, f"the roster is empty but {excluded} file(s) were excluded"
    assert covered + excluded + unselectable == part["total"], (
        f"{covered} + {excluded} + {unselectable} != {part['total']} — emptying the "
        f"roster dropped files out of every bucket, so the census now describes a "
        f"smaller tree than the one on disk")
    assert part["total"] > 0, "partitioned an empty tree; this is not a measurement"


# ---------------------------------------------------------------------------
# 5. THE SHIPPED TREE IS ACTUALLY CLEAN. This is the one that would have caught the
#    stale entry at the time, and it is the one the landing gate runs.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_the_shipped_roster_faults_nothing_on_this_tree():
    # 60 s, not 180 (vibe-ic#1711). 180 was the WHOLE pytest session budget, so
    # under `--timeout-method=thread` it could never fire as a TEST failure —
    # pytest kills the SESSION first and every other file in the subset loses
    # its verdict. MEASURED on this tree: `--repo <root> --audit` partitions
    # 2,734 tracked test files in 0.04 s, so 60 s is ~1500x the observed cost.
    out = subprocess.run(
        [sys.executable, str(PROG), "--repo", str(REPO), "--audit"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, (
        f"the shipped exclusion roster is stale again:\n{out.stdout}\n{out.stderr}")

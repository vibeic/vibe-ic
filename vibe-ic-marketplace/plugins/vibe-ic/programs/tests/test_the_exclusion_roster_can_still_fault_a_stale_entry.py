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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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
    """RENAMED IN SPIRIT, NOT IN NAME: the roster is no longer empty.

    This test was the tripwire that made whoever re-added an entry read the
    comment. It fired, it was read, and the entry stayed — so the assertion now
    holds the roster to what it must be rather than to emptiness. The demand is
    unchanged and is the one the old message stated: an entry must say WHICH
    tree it subtracts and WHY that tree is in this repository.
    """
    assert M._EXCLUDED, (
        "the exclusion roster is empty again. programs/tests/fixtures/ is a tree "
        "no landing stage and no bare run can reach (pytest.ini norecursedirs), "
        "so dropping the entry puts its files back in `covered` — counted as "
        "tests a landing could be blocked by, which nothing runs.")
    for e in M._EXCLUDED:
        assert e.prefix.endswith("/"), f"exclusion prefix {e.prefix!r} is not a tree"
        assert len(e.why.strip()) > 40, (
            f"exclusion {e.prefix!r} states no real reason. The roster's whole "
            f"point is that an exclusion is STATED, not implied by a constant.")
    src = PROG.read_text(encoding="utf-8")
    assert "ONE TREE IS EXCLUDED" in src, (
        "the roster lost the comment recording what it holds and why — which is "
        "what distinguishes a deliberate roster from one somebody edited blind, "
        "and audit() cannot tell those apart")


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
    # `skills/`, a tree no covered prefix claims, so this case is independent of
    # the covered-vs-excluded precedence in either direction.
    #
    # THIS COMMENT USED TO SAY the opposite was forced: "`partition()` assigns a
    # file to COVERED before it considers an exclusion, so a prefix already
    # claimed by a covered tree subtracts nothing and would be faulted". That was
    # true and it was a DEFECT being steered around in a test comment rather than
    # fixed — it is why programs/tests/fixtures/ could not be excluded at all.
    # `partition()` now consults exclusions FIRST; see
    # test_an_exclusion_under_a_covered_tree_actually_subtracts below, which
    # fails against the old order. Measured on this tree: skills/ holds 68 of the
    # 110 unselectable files, so it is a prefix an exclusion can genuinely take.
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
# 3b. AN EXCLUSION UNDER A COVERED TREE ACTUALLY SUBTRACTS.
#     This is the one that fails against the pre-fix order, and it is the whole
#     reason the roster could not hold the entry it now holds.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_an_exclusion_under_a_covered_tree_subtracts_whatever_the_roster_holds(
        monkeypatch):
    """The PRECEDENCE property, on a SYNTHETIC entry, independent of the roster.

    Its sibling below drives the SHIPPED roster, and that one cannot be an
    informative pre-fix control: on a tree whose roster is `()` it fails at its
    own non-vacuity guard, so the failure says only "nothing was declared" —
    which `control_substance_check` correctly grades TAUTOLOGICAL.

    This one declares the entry itself. So on the pre-fix program the module,
    the roster and the corpus are all present and only the ORDER is wrong, and
    the assertion executes over an observed value: the excluded bucket is EMPTY
    for a prefix that really does hold tracked files.
    """
    plugin = M.plugin_rel(REPO)
    files = M.tracked_test_files(REPO) or []
    assert files, "partitioned an empty file list; this is not a measurement"

    under = f"{plugin}/programs/tests/fixtures/"
    covered_prefixes = [c.prefix for c in M._covered(plugin)]
    assert any(under.startswith(c) and under != c for c in covered_prefixes), (
        f"{under!r} is not under any covered tree, so this test would pass "
        f"without exercising the precedence at all. covered={covered_prefixes}")
    here = sorted(f for f in files if f.startswith(under))
    assert here, (
        f"no tracked test file under {under!r}; the stimulus this test needs is "
        f"absent and a green result would prove nothing")

    monkeypatch.setattr(M, "_EXCLUDED", (M.Excluded(
        prefix=under,
        why="synthetic: a tree that IS under a covered prefix and DOES hold "
            "tracked test files, so a partition that consults `covered` first "
            "subtracts nothing here."),))
    part = M.partition(files, plugin)
    got = (part["excluded"] or {}).get(under) or []
    assert got == here, (
        f"an exclusion over {under!r} subtracted {len(got)} of the {len(here)} "
        f"tracked file(s) that really live there. partition() is consulting "
        f"`covered` before `_EXCLUDED`, so a declared exclusion under a covered "
        f"tree can never fire — and it does not announce itself: audit() then "
        f"reports the entry as matching NO tracked file, which reads as a stale "
        f"roster rather than an unreachable one. missing={sorted(set(here)-set(got))[:3]}")
    for c in covered_prefixes:
        leaked = [f for f in ((part["covered"] or {}).get(c) or [])
                  if f.startswith(under)]
        assert not leaked, (
            f"{len(leaked)} file(s) under the excluded tree are still counted "
            f"covered by {c!r}, e.g. {leaked[0]}")


@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_an_exclusion_under_a_covered_tree_actually_subtracts():
    """Every exclusion worth STATING is a subtree of some covered tree.

    That is what makes it worth stating: nobody declares an exclusion over a
    tree no stage claims — the complement already handles those. So if
    `partition()` tests `covered` first, a declared exclusion can never fire,
    and the failure does not announce itself as "the order is wrong": `audit()`
    reports the entry as matching NO tracked file, which reads as a STALE
    ROSTER. MEASURED on 0405c4de96 with the entry declared and the old order:
    covered 2973, excluded 0, `--audit` rc=1 with exactly that finding.

    Driven on the REAL tracked corpus and the REAL shipped roster, not a
    synthetic one — the defect was in how the shipped roster and the shipped
    covered list interact, and a synthetic pair on unrelated prefixes cannot
    exhibit it.
    """
    plugin = M.plugin_rel(REPO)
    files = M.tracked_test_files(REPO) or []
    assert files, "partitioned an empty file list; this is not a measurement"

    assert M._EXCLUDED, "no exclusion is declared, so this test measures nothing"
    covered_prefixes = [c.prefix for c in M._covered(plugin)]
    under = [e for e in M._EXCLUDED
             if any(e.prefix.startswith(c) and e.prefix != c
                    for c in covered_prefixes)]
    assert under, (
        f"no declared exclusion lies UNDER a covered tree, so the precedence "
        f"this test pins is not exercised. exclusions="
        f"{[e.prefix for e in M._EXCLUDED]} covered={covered_prefixes}")

    part = M.partition(files, plugin)
    excluded = part["excluded"]
    covered = part["covered"]
    for e in under:
        got = excluded.get(e.prefix) or []
        assert got, (
            f"exclusion {e.prefix!r} lies under a covered tree and subtracted "
            f"NOTHING. partition() is testing `covered` before `_EXCLUDED`, so "
            f"the declaration cannot fire and its files stay counted as tests a "
            f"landing could be blocked by.")
        for c in covered_prefixes:
            leaked = [f for f in (covered.get(c) or []) if f.startswith(e.prefix)]
            assert not leaked, (
                f"{len(leaked)} file(s) under the excluded tree {e.prefix!r} are "
                f"still counted covered by {c!r}, e.g. {leaked[0]}")

    # and the census still accounts for every tracked file exactly once
    n = (sum(len(v) for v in covered.values())
         + sum(len(v) for v in excluded.values())
         + len(part["unselectable"]))
    assert n == part["total"] == len(files), (
        f"buckets hold {n} of {part['total']} tracked file(s); a file that is in "
        f"no bucket is one nobody can see is unrun")


# ---------------------------------------------------------------------------
# 4. THE DENOMINATOR STILL ADDS UP with zero exclusions. Removing the last entry
#    must not leave files unaccounted for in any bucket.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _repo_is_git(), reason="needs the real git checkout to partition")
def test_the_partition_is_still_exhaustive_with_no_exclusions():
    """Every tracked file lands in exactly one bucket — WHATEVER the roster holds.

    The `excluded == 0` assertion this carried was correct while the roster was
    `()`, and it was pinning the ROSTER'S CONTENTS in a test about the
    DENOMINATOR — so the day an exclusion was legitimately added it failed here
    for a reason that has nothing to do with exhaustiveness. Case 1 is where the
    roster's contents are pinned. What belongs here is that nothing falls out of
    every bucket, and that is now asserted in both directions: the buckets sum to
    the total, and no file is counted twice.
    """
    files = M.tracked_test_files(REPO) or []
    part = M.partition(files, M.plugin_rel(REPO))
    buckets = ([v for v in part["covered"].values()]
               + [v for v in part["excluded"].values()]
               + [part["unselectable"]])
    n = sum(len(v) for v in buckets)
    assert n == part["total"] == len(files), (
        f"buckets hold {n} of {part['total']} tracked file(s) — a file in no "
        f"bucket is one nobody can see is unrun")
    seen = [f for v in buckets for f in v]
    assert len(seen) == len(set(seen)), (
        "a file was counted in more than one bucket, so the census double-counts")
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
    out = _pr.run(
        [sys.executable, str(PROG), "--repo", str(REPO), "--audit"],
        capture_output=True, text=True)
    assert out.returncode == 0, (
        f"the shipped exclusion roster is stale again:\n{out.stdout}\n{out.stderr}")

#!/usr/bin/env python3
"""`_exclusive_worktrees` — the checkout each tree-exclusive file is measured in.

WHY THIS FILE EXISTS
====================
`plugin_full_audit` caught the module shipping untested:

    D1 program-test-coverage: FAIL — untested non-synth programs: ['_exclusive_worktrees']

which is the THIRD shared module to ship with no test in one day (see
`test_corpus_location.py` and `test_tree_exclusive_tests.py`, same finding, same
audit, one hour apart). The rule is right and the omission was mine all three times.

WHAT IS ACTUALLY AT RISK
========================
This module hands 21 test files the only thing that makes their result mean
anything: a tree nobody else is writing into. Every function fails silently in a
way that reads like success:

  * `make` that returns None with no reason turns a REFUSAL into a skip, and the
    driver's whole NORECORD doctrine rests on those two being distinguishable;
  * `remove` that does not remove leaks one worktree per file per round, and the
    NEXT round's clean-tree gate blames that round for a tree this one left;
  * `cwd_for` that points anywhere but the plugin makes every isolated session
    collect nothing, which the driver would report as a file that ran and found
    no tests rather than as a file that never ran;
  * `plan` off by one attributes every record to the wrong file, which reads as a
    coherent set of failures in files that were never touched.

So every case below asserts BOTH directions. A test that only proved "make
returns a path" would pass against a module that never removed anything, and a
test that only proved "remove leaves nothing behind" would pass against a module
that never created anything either.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "_exclusive_worktrees.py"


def _load():
    spec = importlib.util.spec_from_file_location("_xw_under_test", MOD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


X = _load()


def _registered(path: Path) -> bool:
    """Is this path a worktree git itself knows about? `path.exists()` alone would
    accept a bare directory, and a leaked REGISTRATION with no directory is just as
    much of a leak as the reverse."""
    cp = subprocess.run(
        ["git", "-C", str(X.repo_root()), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        return False
    want = str(path.resolve())
    return any(line[len("worktree "):].strip() == want
               for line in cp.stdout.splitlines()
               if line.startswith("worktree "))


@pytest.fixture()
def commit():
    sha = X.head_commit()
    if not sha:
        pytest.skip("no resolvable HEAD; there is no commit to make a worktree at")
    return sha


# ---------------------------------------------------------------------------
# make + remove: BOTH directions, because each one alone is satisfied by a
# module that does nothing at all.
# ---------------------------------------------------------------------------
def test_make_really_creates_a_worktree_and_remove_really_removes_it(commit):
    wt, reason = X.make(commit, "selftest_roundtrip")
    assert reason is None, f"make refused unexpectedly: {reason}"
    assert wt is not None
    try:
        # CREATED, and created as a WORKTREE — not merely as a directory. A linked
        # worktree carries a `.git` FILE pointing at the common dir; a module that
        # only ran mkdir would satisfy `exists()` and nothing else.
        assert wt.is_dir(), f"{wt} is not a directory"
        assert (wt / ".git").exists(), (
            f"{wt} has no .git; it is a bare directory, not a checkout")
        assert _registered(wt), f"git does not list {wt} as a worktree"
    finally:
        X.remove(wt)
    # REMOVED — the paired half. Without it this test passes against a `remove`
    # whose body is `pass`, and the leak lands on the NEXT round's clean-tree gate.
    assert not wt.exists(), f"{wt} survived remove()"
    assert not _registered(wt), (
        f"{wt} is gone from disk but git still lists it — a stale registration is "
        "still a leak, and `git worktree list` is where the next round looks")


def test_two_worktrees_at_once_are_independent(commit):
    """The 21 files are measured concurrently, so `make` is called again before the
    previous one is removed. Two calls must not collide on a path, and removing one
    must not disturb the other."""
    a, ra = X.make(commit, "selftest_a")
    b, rb = X.make(commit, "selftest_b")
    assert ra is None and rb is None, (ra, rb)
    try:
        assert a != b, "two concurrent worktrees were given the same path"
        assert _registered(a) and _registered(b)
        X.remove(a)
        assert not a.exists()
        assert _registered(b) and b.exists(), (
            "removing one isolated checkout destroyed another; the files measured "
            "in it would report as NORECORD through no fault of their own")
    finally:
        X.remove(a)
        X.remove(b)


def test_remove_is_safe_on_an_already_removed_worktree(commit):
    """`remove` is called from a `finally`, including on paths where the tree is
    already gone. Raising there would replace a real failure with this one."""
    wt, reason = X.make(commit, "selftest_twice")
    assert reason is None
    X.remove(wt)
    X.remove(wt)          # must not raise
    assert not wt.exists()


# ---------------------------------------------------------------------------
# make's failure path: a REASON, never a silent None.
# ---------------------------------------------------------------------------
def test_a_failure_to_create_returns_a_reason_and_not_a_silent_none():
    """This is the NORECORD doctrine at its narrowest point. The driver decides
    between 'this file has no record' and 'this file passed' by whether it got a
    reason back; a bare None with no reason is how a file that never ran comes to
    read as a file that ran clean."""
    wt, reason = X.make("0000000000000000000000000000000000000000",
                        "selftest_bogus")
    assert wt is None, "a worktree was somehow created at a commit that cannot exist"
    assert reason, "make() refused without saying why — the refusal is unreportable"
    assert isinstance(reason, str) and reason.strip()
    assert not reason.isspace()


def test_the_two_outcomes_of_make_are_mutually_exclusive(commit):
    """Exactly one of (path, reason) is set, either way. A module that returned both
    or neither would let a caller act on a path it was told to distrust."""
    ok_wt, ok_reason = X.make(commit, "selftest_exclusive")
    try:
        assert (ok_wt is None) != (ok_reason is None), (ok_wt, ok_reason)
    finally:
        if ok_wt is not None:
            X.remove(ok_wt)
    bad_wt, bad_reason = X.make("refs/nope/nothing/here", "selftest_exclusive2")
    assert (bad_wt is None) != (bad_reason is None), (bad_wt, bad_reason)


# ---------------------------------------------------------------------------
# cwd_for: the directory the driver's children actually run in.
# ---------------------------------------------------------------------------
def test_cwd_for_points_at_a_directory_that_really_contains_the_driver(commit):
    """Not 'is a plausible-looking path' — the file the children invoke has to BE
    there. A cwd one level off collects zero tests, and the driver would report that
    as a file which ran and found nothing rather than as a file that never ran."""
    wt, reason = X.make(commit, "selftest_cwd")
    assert reason is None
    try:
        cwd = Path(X.cwd_for(wt))
        assert cwd.is_dir(), f"{cwd} is not a directory"
        assert (cwd / "programs" / "pytest_per_file_junit.py").is_file(), (
            f"{cwd} does not contain programs/pytest_per_file_junit.py; the "
            "isolated sessions would be launched somewhere that cannot run them")
        assert (cwd / "programs" / "_exclusive_worktrees.py").is_file()
        # INSIDE the worktree it was derived from, not next to it: a path that
        # escaped the checkout would silently put every 'isolated' session back in
        # the shared tree, which is the exact thing being bought here.
        assert str(cwd.resolve()).startswith(str(wt.resolve()))
    finally:
        X.remove(wt)


def test_cwd_for_is_not_merely_the_worktree_root(commit):
    """The paired half. If the plugin sat at the repo root, returning the root would
    satisfy the test above while doing no work — and this assertion would be the one
    that noticed the layout had changed."""
    wt, reason = X.make(commit, "selftest_cwd_root")
    assert reason is None
    try:
        assert Path(X.cwd_for(wt)).resolve() != wt.resolve()
        assert not (wt / "programs" / "pytest_per_file_junit.py").is_file(), (
            "the driver is at the worktree root, so cwd_for cannot be shown to "
            "resolve anything")
    finally:
        X.remove(wt)


def test_cwd_for_is_pure_and_does_not_need_the_worktree_to_exist():
    """It is called while building the batch spec, before anything is launched.
    Making it touch the filesystem would couple path derivation to run order."""
    made_up = Path("/nonexistent/selftest/tree")
    assert X.cwd_for(made_up).startswith(str(made_up))


# ---------------------------------------------------------------------------
# plan: the indices are 1-based because every record the driver keeps is keyed
# on the selection index.
# ---------------------------------------------------------------------------
SEL = ["programs/tests/test_api_health.py",                  # 1
       "programs/tests/test_gate_skip_routing_check.py",     # 2
       "programs/tests/test_all_steps_covers_flow.py",       # 3
       "programs/tests/test_programs_index_freshness.py"]    # 4


def test_plan_preserves_one_based_indices():
    """Off by one here means each isolated checkout runs a DIFFERENT file from the
    one its record is filed under — a coherent-looking set of failures in files that
    were never run."""
    out = X.plan([2, 4], SEL)
    assert [i for i, _p, _t in out] == [2, 4]
    assert [p for _i, p, _t in out] == [SEL[1], SEL[3]], (
        "plan resolved the wrong paths — it is indexing from 0, and every record "
        "would be attributed to its neighbour")


def test_plan_returns_the_indices_it_was_given_and_no_others():
    """The paired half of the above: right paths, but also nothing extra and
    nothing dropped. A plan that quietly skipped an index would leave that file with
    no checkout and no reason recorded for why."""
    assert [i for i, _p, _t in X.plan([1, 2, 3, 4], SEL)] == [1, 2, 3, 4]
    assert X.plan([], SEL) == []
    assert [i for i, _p, _t in X.plan([3], SEL)] == [3]


def test_plan_keeps_the_order_it_was_given():
    assert [i for i, _p, _t in X.plan([4, 1, 3], SEL)] == [4, 1, 3]


def test_the_tag_names_the_worktree_after_its_file():
    """A leaked worktree has to be traceable to the test that leaked it. A random
    suffix would make the leak visible and its cause unfindable."""
    (_i, _p, tag), = X.plan([2], SEL)
    assert tag == "test_gate_skip_routing_check", tag
    assert not tag.endswith(".py"), "the .py would make the tag a filename, not a tag"
    assert "/" not in tag, "a tag with a separator would not be a single path component"


def test_a_long_name_is_truncated_but_still_a_usable_tag():
    """`mkdtemp` prefixes are bounded; an untruncated stem is how the isolated run
    fails at directory creation rather than at anything to do with the test."""
    long_sel = ["programs/tests/test_" + ("x" * 120) + ".py"]
    (_i, _p, tag), = X.plan([1], long_sel)
    assert 0 < len(tag) <= 40, len(tag)
    assert tag.startswith("test_")


# ---------------------------------------------------------------------------
# head_commit + prune: the two helpers the caller refuses on.
# ---------------------------------------------------------------------------
def test_head_commit_is_a_real_resolvable_commit():
    """The caller treats a falsy return as 'no tree can be made' and NORECORDs all
    21 files. A truthy-but-wrong value would instead make every `make` fail one by
    one with a less legible reason."""
    sha = X.head_commit()
    if sha is None:
        pytest.skip("detached/unborn HEAD in this checkout")
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), sha
    cp = subprocess.run(["git", "-C", str(X.repo_root()), "cat-file", "-t", sha],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0 and cp.stdout.strip() == "commit", cp.stdout


def test_repo_root_is_the_repo_and_contains_the_plugin():
    root = X.repo_root()
    assert (root / ".git").exists(), f"{root} is not a repo root"
    assert (root / X._PLUGIN_REL / "programs" / "_exclusive_worktrees.py").is_file(), (
        "the plugin is not where _PLUGIN_REL says it is, so cwd_for is deriving a "
        "path into empty space")


def test_prune_is_quiet_and_does_not_raise():
    """It runs unconditionally after every batch, including when there is nothing to
    prune. An exception there would be reported as the batch failing."""
    X.prune()
    X.prune()

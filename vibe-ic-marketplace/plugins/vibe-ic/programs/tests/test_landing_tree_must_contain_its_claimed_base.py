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

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
_PLUGIN_ROOT = _HERE.parents[2]
_REPO_ROOT = _HERE.parents[5]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gatekeeper_stale_branch_check as guard  # noqa: E402

_CHECKER = _PROGRAMS / "gatekeeper_stale_branch_check.py"


# ---------------------------------------------------------------------------
# git plumbing for the fixtures.
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str, index: str = "") -> str:
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    if index:
        env["GIT_INDEX_FILE"] = index
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       text=True, env=env)
    if p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} -> {p.stderr}")
    return p.stdout


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "x.py").write_text("x = 0\n")
    (r / "y.py").write_text("y = 0\n")
    (r / "z.py").write_text("z = 0\n")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "base0")
    return r


def _land(r: Path, path: str, content: str, msg: str) -> str:
    """One landing on `main`."""
    (r / path).parent.mkdir(parents=True, exist_ok=True)
    (r / path).write_text(content)
    _git(r, "add", path)
    _git(r, "commit", "-qm", msg)
    return _git(r, "rev-parse", "HEAD").strip()


def _reparent(r: Path, stale_ref: str, own: dict, msg: str,
              drop: tuple = ()) -> str:
    """The DEFECT's mechanism, reproduced exactly.

    Build a commit whose PARENT is the current `main` tip but whose TREE is
    `stale_ref`'s tree plus `own` — an author's edits applied to an older base
    and then re-parented, which is what a bad rebase produces.
    """
    idx = str(r / ".git" / "fixture-index")
    if os.path.exists(idx):
        os.remove(idx)
    _git(r, "read-tree", stale_ref, index=idx)
    for path, content in own.items():
        blob = subprocess.run(["git", "-C", str(r), "hash-object", "-w",
                               "--stdin"], input=content, capture_output=True,
                              text=True).stdout.strip()
        _git(r, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}",
             index=idx)
    if drop:
        _git(r, "update-index", "--force-remove", "--", *drop, index=idx)
    tree = _git(r, "write-tree", index=idx).strip()
    parent = _git(r, "rev-parse", "main").strip()
    p = subprocess.run(["git", "-C", str(r), "commit-tree", tree, "-p", parent],
                       input=msg, capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t",
                            "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@t"})
    assert p.returncode == 0, p.stderr
    sha = p.stdout.strip()
    _git(r, "update-ref", "refs/heads/pr", sha)
    return sha


def _on_tip(r: Path, own: dict, msg: str, drop: tuple = ()) -> str:
    """A HONEST commit: parent = main tip, tree = main's tree + these edits."""
    return _reparent(r, "main", own, msg, drop)


def _run(args):
    p = subprocess.run([sys.executable, str(_CHECKER), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------------------
# POSITIVE — the defect's shape.
# ---------------------------------------------------------------------------
def test_reparented_stale_tree_is_blocked(tmp_path):
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # landed\n", "land x")
    _land(r, "y.py", "y = 1  # landed\n", "land y")
    _land(r, "z.py", "z = 1  # landed\n", "land z")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "my fix, on a stale tree\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 1
    assert res.verdict == "TREE_REWIND"
    # SET EQUALITY over literals: exactly the three files the base moved on and
    # the head still holds at their pre-landing state — no more, no fewer.
    assert set(res.rewound_files) == {"x.py", "y.py", "z.py"}
    assert len(res.missing_commits) == 3
    assert "does not contain that history" in res.summary


def test_the_blocked_verdict_names_the_collateral_deletions(tmp_path):
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # landed\n", "land x")
    _land(r, "y.py", "y = 1  # landed\n", "land y")
    _land(r, "new_test.py", "def test_new():\n    assert True\n", "land a test")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "my fix, on a stale tree\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 1
    # The stale tree predates `new_test.py`, so the land would delete it. That
    # deletion is COLLATERAL — nothing in the change authored it. It is REPORTED
    # and never the trigger: the trigger is the rewound modification, which is
    # what keeps a real removal green.
    assert set(res.collateral_deletions) == {"new_test.py"}
    assert set(res.rewound_files) == {"x.py", "y.py"}


def test_a_stale_window_carrying_no_version_still_blocks(tmp_path):
    """The version gate is a PROXY; this rule is not.

    `version_bump_monotonic_check` reddened on the real incident only because
    the stale window happened to contain a version bump. 89 of the last 200
    commits of `main` carry no version at all, so a window of data-only or doc
    landings reverts just as much work and moves no version. Nothing here
    touches a manifest of any kind, and the block must be identical.
    """
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # a doc-only day\n", "docs: rewrite x's header")
    _land(r, "y.py", "y = 1  # a doc-only day\n", "docs: rewrite y's header")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "my fix, on a stale tree\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 1
    assert res.verdict == "TREE_REWIND"
    assert set(res.rewound_files) == {"x.py", "y.py"}


# ---------------------------------------------------------------------------
# NEGATIVE — the load-bearing ones.
# ---------------------------------------------------------------------------
def test_ordinary_fresh_change_passes_and_states_its_denominator(tmp_path):
    r = _repo(tmp_path)
    _land(r, "x.py", "x = 1  # landed\n", "land x")
    _on_tip(r, {"y.py": "y = 7  # my edit\n"}, "an ordinary change\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 0
    assert res.verdict == "FRESH"
    assert res.rewound_files == []
    # A pass that does not state its denominator can be read over a set that
    # silently shrank; this one names how many paths it examined.
    assert "rewinds none of the 1 path(s) it modifies" in res.summary


def test_legitimate_large_deletion_of_recently_added_files_passes(tmp_path):
    """THE ACCEPTANCE TEST: same deletion footprint, different provenance.

    A genuine removal of a dead program and its tests deletes exactly the kind
    of paths a stale tree drops — recently added, on the base, in bulk. A gate
    that cannot separate a real removal from a stale-base revert is a gate that
    gets disabled, so this is not an optional extra.

    Measured on the real repository as well as here: a fixture that removes the
    SAME 15 paths the incident removes (16 files, 4206 deletions), authored on
    top of `origin/main`, returns rc 0.
    """
    r = _repo(tmp_path)
    _land(r, "dead/prog.py", "def dead():\n    return 1\n", "add a program")
    _land(r, "dead/test_a.py", "def test_a():\n    assert True\n", "test a")
    _land(r, "dead/test_b.py", "def test_b():\n    assert True\n", "test b")
    _land(r, "dead/test_c.py", "def test_c():\n    assert True\n", "test c")
    _land(r, "catalogue.md", "- prog\n- other\n", "catalogue them")
    _on_tip(r,
            {"catalogue.md": "- other\n"},         # a real edit, new content
            "remove a dead program and its tests\n",
            drop=("dead/prog.py", "dead/test_a.py", "dead/test_b.py",
                  "dead/test_c.py"))

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 0
    assert res.verdict == "FRESH"
    assert res.rewound_files == []


def test_single_commit_inverse_is_disclosed_not_blocked(tmp_path):
    """A revert restores a state the file demonstrably had.

    Measured over the last 800 single-parent landings of `main`, the raw rule
    fires three times and all three are this shape: a declared revert, a repair
    that removes a probe marker one commit landed by accident, and a deletion
    whose catalogue entry returns to its exact prior state. Blocking any of them
    is how a gate gets switched off.
    """
    r = _repo(tmp_path)
    before = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # the change being undone\n", "land x")
    _on_tip(r, {"x.py": "x = 0\n"}, "revert the change to x\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 0
    assert res.verdict == "SINGLE_COMMIT_INVERSE"
    assert res.rewound_files == ["x.py"]
    assert res.inverse_of == _git(r, "rev-parse", "main").strip()
    assert before == _git(r, "rev-parse", "main~1").strip()
    assert "EXACT INVERSE of one commit" in res.summary


def test_single_commit_inverse_verifies_the_state_it_claims(tmp_path):
    """The exemption PROVES its claim against a commit that exists.

    Found by mutation: widening `len(missing) != 1` to `not missing` killed
    nothing, because with one missing commit the rewind is almost always that
    commit's exact inverse anyway — so the count was carrying the whole test and
    the VERIFICATION was unpinned. An exemption nobody checks is a bypass. This
    drives the predicate directly with a head whose blob is NOT the named
    commit's parent state, and requires it to refuse.
    """
    r = _repo(tmp_path)
    m = _land(r, "x.py", "x = 1\n", "land x")
    _on_tip(r, {"x.py": "x = 2\n"}, "a forward edit, not an inverse\n")
    head = _git(r, "rev-parse", "pr").strip()

    assert guard._single_commit_inverse(
        r, head, [guard.Rewind("x.py", m)], [m]) is None
    # …and it DOES fire when the state really is the one before that commit.
    _on_tip(r, {"x.py": "x = 0\n"}, "the actual inverse\n")
    inverse_head = _git(r, "rev-parse", "pr").strip()
    assert guard._single_commit_inverse(
        r, inverse_head, [guard.Rewind("x.py", m)], [m]) == m


def test_pure_add_commits_cannot_hide_behind_the_exemption(tmp_path):
    """`missing` counts commits that touched a REWOUND path — nothing else.

    A commit in the stale window that only ADDS files touches no rewound path,
    so it never enters that union; and a stale tree deletes exactly those
    additions, so the whole commit vanishes from the arithmetic. The exemption
    then declared a tree missing many commits to be "the EXACT INVERSE of one
    commit" — an assertion that was false about the tree it was made over.

    The bound is the deletions: a real inverse of M can only delete what M
    ADDED, so a deleted path ABSENT at M was added by a commit the counter never
    saw.
    """
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # the one modification\n", "land x")
    _land(r, "added_a.py", "a = 1\n", "land a")          # pure add
    _land(r, "added_b.py", "b = 1\n", "land b")          # pure add
    _land(r, "added_c.py", "c = 1\n", "land c")          # pure add
    _reparent(r, fork, {"own.py": "own = 1\n"}, "my fix, on a stale tree\n")

    res = guard.analyze(r, "main", "pr")
    # ONE rewound path — so the rewound-path union alone names ONE commit, which
    # is the shape the exemption used to wave through while the tree was three
    # further landings behind.
    assert res.rewound_files == ["x.py"]
    # The three pure-add commits are now counted, because the paths they created
    # are paths this tree does not have. 1 + 3 = 4.
    assert len(res.missing_commits) == 4
    assert res.inverse_of is None
    assert res.rc == 1
    assert res.verdict == "TREE_REWIND"
    # …and the evidence names them, because the deletion probe now runs before
    # any early return.
    assert set(res.collateral_deletions) == {"added_a.py", "added_b.py",
                                             "added_c.py"}


def test_a_real_inverse_may_delete_what_that_commit_added(tmp_path):
    """The bound must not break the reverts it exists to permit.

    Two of the three legitimate firings measured on `main` delete files: the
    probe-marker repair removes the `.probe-orig` backups the inverted commit
    created, and the register deletion removes the program that commit added.
    Both are accounted for AT M. Anchoring the test at `M~1` instead would have
    blocked them — that was the first candidate condition and it is why this
    test names the anchor.
    """
    r = _repo(tmp_path)
    # ONE landing that both modifies a file and adds its helper — the shape both
    # real firings have.
    (r / "x.py").write_text("x = 1  # the change\n")
    (r / "helper.py").write_text("helper = 1\n")
    _git(r, "add", "x.py", "helper.py")
    _git(r, "commit", "-qm", "land the feature: x plus its helper")
    m = _git(r, "rev-parse", "HEAD").strip()
    # Undo BOTH: x.py back to its earlier state, helper.py removed.
    _on_tip(r, {"x.py": "x = 0\n"}, "revert the feature\n",
            drop=("helper.py",))

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 0
    assert res.verdict == "SINGLE_COMMIT_INVERSE"
    assert res.inverse_of == m
    assert res.deletions == 1
    assert res.collateral_deletions == []
    # helper.py EXISTS at M (M added it) and is absent at M~1 — the anchor is
    # what decides this, and only `M` gives the right answer.
    assert guard.unaccounted_deletions(r, m, ["helper.py"]) == []
    assert guard.unaccounted_deletions(r, f"{m}~1", ["helper.py"]) == ["helper.py"]
    # The bound is WIRED, not merely available: hand the predicate a deletion M
    # cannot account for and the exemption must refuse. This is the second,
    # independent guard — the missing-commit counter above catches the same
    # shape whenever the walk can see the creating commit, and this one still
    # holds when it cannot (a bounded `--window`).
    rewinds = [guard.Rewind("x.py", m)]
    head = _git(r, "rev-parse", "pr").strip()
    assert guard._single_commit_inverse(r, head, rewinds, [m], []) == m
    assert guard._single_commit_inverse(r, head, rewinds, [m],
                                        ["helper.py"]) == m   # M added it
    assert guard._single_commit_inverse(
        r, head, rewinds, [m], ["from_a_later_add.py"]) is None


def test_a_deletion_older_than_the_known_missing_work_is_not_counted(tmp_path):
    """The inequality is sound in ONE direction, and this pins which.

    A change may delete a file that has been there for months. Counting every
    deleted path's creator blocked two real landings of the last 800 —
    `3c5530564`, which deletes a gate added long before the commit it inverts,
    and `afce80526`. What a stale tree cannot do is lack a file created AFTER
    the state it was built on, and the only sound witness for "after" is a
    commit the rewinds already prove missing.
    """
    r = _repo(tmp_path)
    _land(r, "ancient.py", "ancient = 1\n", "add a file, long ago")
    (r / "x.py").write_text("x = 1  # the change\n")
    _git(r, "add", "x.py")
    _git(r, "commit", "-qm", "the commit being inverted")
    m = _git(r, "rev-parse", "HEAD").strip()
    # Undo that ONE commit, and also drop a file far older than it.
    _on_tip(r, {"x.py": "x = 0\n"}, "revert it, and retire a stale file\n",
            drop=("ancient.py",))

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 0
    assert res.verdict == "SINGLE_COMMIT_INVERSE"
    assert res.inverse_of == m
    assert res.missing_commits == [m]      # ancient.py's creator is NOT counted


def test_two_commit_rewind_is_not_a_single_commit_inverse(tmp_path):
    """The suppression is structural, not a magnitude with slack in it.

    Two commits' worth of missing content cannot be the exact inverse of one
    commit that exists, so it blocks — which is what stops the exemption from
    becoming a doorway.
    """
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1\n", "land x")
    _land(r, "y.py", "y = 1\n", "land y")
    _on_tip(r, {"x.py": "x = 0\n", "y.py": "y = 0\n"}, "undo both\n")

    res = guard.analyze(r, "main", "pr")
    assert res.rc == 1
    assert res.verdict == "TREE_REWIND"
    assert res.inverse_of is None
    assert set(res.rewound_files) == {"x.py", "y.py"}


def test_stale_branch_overlap_still_blocks(tmp_path):
    """Regression guard: the STALE half of this gate is untouched.

    The new predicate lives in the FRESH branch only — the case where the land
    publishes the head's tree verbatim. A branch that has NOT been rebased is a
    different question, already answered by the overlap check, and it must keep
    the same verdict and the same remedy text.
    """
    r = _repo(tmp_path)
    _git(r, "branch", "pr")
    _land(r, "x.py", "x = 99  # landed fix\n", "land fix on x")
    _git(r, "checkout", "-q", "pr")
    (r / "x.py").write_text("x = 1  # pr edit\n")
    _git(r, "add", "x.py")
    _git(r, "commit", "-qm", "pr also edits x")
    _git(r, "checkout", "-q", "main")

    res = guard.analyze(r, "main", "pr")
    assert res.verdict == "STALE_OVERLAP"
    assert res.rc == 1
    assert res.rewound_files == []


def test_window_bounds_the_search_and_the_pass_discloses_it(tmp_path):
    """The window is a REAL boundary and the verdict must say which side it is on.

    A rewind older than `--window` commits of the base is out of reach — the
    result changes SIGN as the window moves, which an earlier comment on
    `DEFAULT_WINDOW` denied in the same file this test lives in. A PASS that
    exhausted its window and one that read the base's whole history are
    different facts and must not read alike.
    """
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1\n", "land x")
    _land(r, "y.py", "y = 1\n", "land y")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "stale tree\n")

    unbounded = guard.analyze(r, "main", "pr")
    assert unbounded.rc == 1
    assert unbounded.window_exhausted is False
    assert "its complete history, nothing bounded away" in unbounded.summary

    narrow = guard.analyze(r, "main", "pr", window=1)
    assert narrow.rc == 0
    assert narrow.window_exhausted is True
    assert "WINDOW WAS EXHAUSTED" in narrow.summary
    assert "Searched the last 1 commit(s)" in narrow.summary


def test_the_default_walks_the_whole_history(tmp_path):
    """The bound is OFF by default, and that is a measured choice.

    It was 300, which on this repo hid a 2-commit-stale re-parent at eight of
    300 sampled points — not because the tree was 300 landings stale but because
    the files it rewound had not been touched for 300 landings. Walking all 1644
    first-parent commits costs 0.60 s against 0.39 s, so the bound bought
    nothing it did not also cost.
    """
    assert guard.DEFAULT_WINDOW == 0
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1\n", "land x")
    _land(r, "y.py", "y = 1\n", "land y")
    # A long tail of landings that touch NEITHER rewound file, so a windowed
    # walk would stop before the commits that wrote the states the head holds.
    for i in range(8):
        _land(r, f"unrelated_{i}.py", f"u = {i}\n", f"unrelated {i}")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "stale tree\n")

    assert guard.analyze(r, "main", "pr").rc == 1          # default: unbounded
    assert guard.analyze(r, "main", "pr", window=3).rc == 0  # the old blind spot


def test_a_path_it_could_not_read_is_not_a_path_it_found_clean(tmp_path):
    """"I could not look" must never read as "I looked and it was clean".

    Found by mutation: dropping `rep.unexaminable_paths += 1` left all tests
    green, so the doctrine was prose only. A gitlink is the real instance — git
    calls it MODIFIED and `cat-file` yields a commit, not a blob — and it must be
    counted and NAMED rather than skipped into silence.
    """
    r = _repo(tmp_path)
    a = _git(r, "rev-parse", "HEAD").strip()
    _git(r, "update-index", "--add", "--cacheinfo", f"160000,{a},sub")
    _git(r, "commit", "-qm", "a submodule pointer")
    b = _git(r, "rev-parse", "HEAD").strip()
    # base moves the gitlink; the head leaves it where it was.
    _git(r, "update-index", "--cacheinfo", f"160000,{b},sub")
    _git(r, "commit", "-qm", "move the submodule pointer")
    _on_tip(r, {"y.py": "y = 9\n"}, "an ordinary change\n")
    _git(r, "update-index", "--cacheinfo", f"160000,{a},sub")

    mod, _add, _dele = guard._name_status(r, "main", "pr")
    assert "sub" not in mod          # the head's tree matches base here…
    rep = guard.tree_rewind(r, "main", "pr")
    assert rep.unexaminable_paths == 0

    # …now make the head hold the OLD pointer, which git reports as MODIFIED.
    stale = _reparent(r, b, {"y.py": "y = 9\n"}, "holds the old pointer\n")
    mod2, _a2, _d2 = guard._name_status(r, "main", "pr")
    assert "sub" in mod2
    rep2 = guard.tree_rewind(r, "main", "pr")
    assert rep2.unexaminable_paths == 1
    res = guard.analyze(r, "main", "pr")
    assert "1 modified path(s) NOT EXAMINED" in res.summary
    assert res.unexaminable_paths == 1
    assert stale == _git(r, "rev-parse", "pr").strip()


# ---------------------------------------------------------------------------
# CLI + WIRING — the gate must RUN in the landing path and be COUNTED.
# ---------------------------------------------------------------------------
def test_cli_fails_and_prints_the_verdict_first(tmp_path):
    r = _repo(tmp_path)
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1\n", "land x")
    _land(r, "y.py", "y = 1\n", "land y")
    _reparent(r, fork, {"own.py": "own = 1\n"}, "stale tree\n")

    rc, out, err = _run(["--repo", str(r), "--base", "main", "--head", "pr"])
    assert rc == 1
    body = (err or out).splitlines()
    # `gatekeeper_review` summarises this program by its FIRST line; a detail
    # line printed above the verdict becomes the summary a reader acts on.
    assert body[0].startswith("FAIL: TREE REWIND")
    assert "[MISSING FROM THIS TREE]" in "\n".join(body)


def _synthetic_plugin(repo: Path, version: str = "9.9.9") -> Path:
    """The minimal plugin tree the file-walking gates need to report PASS.

    Same shape the sibling `test_gatekeeper_review` builds, and for the same
    reason: the assertion below is that ONE gate turns MERGE_OK into
    REQUEST_CHANGES, and coupling it to the live monorepo's audit state would
    make that claim depend on whatever else happens to be red today.
    """
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "vibe-ic", "version": "%s"}\n' % version)
    mkt = repo / "vibe-ic-marketplace" / ".claude-plugin"
    mkt.mkdir(parents=True)
    (mkt / "marketplace.json").write_text(
        '{"name": "vibe-ic-marketplace", "plugins": [{"name": "vibe-ic", '
        '"source": "./plugins/vibe-ic", "version": "%s"}]}\n' % version)
    progs = plugin / "programs"
    (progs / "tests").mkdir(parents=True)
    (progs / "widget.py").write_text("def go():\n    return 1\n")
    (progs / "tests" / "test_widget.py").write_text(
        "import widget\n\ndef test_go():\n    assert widget.go() == 1\n")
    (progs / "tests" / "chip_deny_list.txt").write_text("# empty deny list\n")
    flow = plugin / "flow"
    flow.mkdir()
    (flow / "phase1_phase2_phase3.yaml").write_text(
        "steps:\n  - id: s1\n    gate:\n"
        '      program_exit_zero: "widget"\n')
    for guard_name in ("gate_self_assertion_check", "single_testpath_guard",
                       "flow_condition_reachability_check"):
        (progs / f"{guard_name}.py").write_text(
            "import sys\n"
            "def main(argv=None):\n"
            "    return 0\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n")
        (progs / "tests" / f"test_{guard_name}.py").write_text(
            f"import {guard_name}\n\n"
            f"def test_ok():\n    assert {guard_name}.main([]) == 0\n")
    return plugin


def test_gatekeeper_review_counts_the_gate_as_blocking(tmp_path):
    """Driven through the REAL aggregation, not a stand-in for it.

    A gate that is registered and never executes is a defect this repo has
    already had (v1.7.65: `landing_is_one_commit_check` was measuring the
    REVIEWER'S own checkout and certified an unsquashed branch). So this calls
    `gatekeeper_review.review()` over a real git range and asserts the rc lands
    in `blocking` and MOVES THE VERDICT — with the plugin manifests identical on
    both sides, so no other gate can be doing the work.
    """
    spec = importlib.util.spec_from_file_location(
        "gatekeeper_review", _PROGRAMS / "gatekeeper_review.py")
    gk = importlib.util.module_from_spec(spec)
    sys.modules["gatekeeper_review"] = gk
    spec.loader.exec_module(gk)

    r = _repo(tmp_path)
    plugin = _synthetic_plugin(r)
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "the plugin tree")
    fork = _git(r, "rev-parse", "HEAD").strip()
    _land(r, "x.py", "x = 1  # landed\n", "land x")
    _land(r, "y.py", "y = 1  # landed\n", "land y")

    # CONTROL: the same change authored ON the tip is green end to end.
    honest = _on_tip(r, {"own.py": "own = 1\n"}, "my fix, on the tip\n")
    clean = gk.review("main", "pr", repo=r, plugin_root=plugin,
                      pytest_cmd="python3 -m pytest -q programs/tests",
                      override_files=["own.py"],
                      override_cur="9.9.9", override_prev="9.9.8")
    assert clean.verdict == "MERGE_OK", clean.blocking

    # The SAME edits, re-parented onto the tip from a stale tree.
    _reparent(r, fork, {"own.py": "own = 1\n"}, "my fix, on a stale tree\n")
    v = gk.review("main", "pr", repo=r, plugin_root=plugin,
                  pytest_cmd="python3 -m pytest -q programs/tests",
                  override_files=["own.py"],
                  override_cur="9.9.9", override_prev="9.9.8")
    by_name = {g.name: g for g in v.gates}
    assert by_name["gatekeeper_stale_branch_check"].rc == 1
    assert "TREE REWIND" in by_name["gatekeeper_stale_branch_check"].summary
    assert {b.split(":", 1)[0] for b in v.blocking} == {
        "gatekeeper_stale_branch_check"}
    assert v.verdict == "REQUEST_CHANGES"
    assert honest != _git(r, "rev-parse", "pr").strip()


def test_landing_script_wires_the_gate_blocking(tmp_path):
    """`tools/gatekeeper-land.sh` is the script whose success writes the
    `.git/gatekeeper-stamp` the pre-push hook demands, so a push to `main`
    cannot happen without it. The checker was blocking in `gatekeeper_review`
    and had never been wired HERE — which is why nothing in the landing path
    had an opinion on the landing method at all.
    """
    script = (_REPO_ROOT / "tools" / "gatekeeper-land.sh").read_text(
        encoding="utf-8")
    assert 'run "tree contains the base it claims as parent"' in script
    assert 'gatekeeper_stale_branch_check.py' in script
    # `run`, not `report`: `report` never touches FAILED, so a gate wired
    # through it is printed and not counted.
    assert 'report "tree contains the base it claims as parent"' not in script

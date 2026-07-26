#!/usr/bin/env python3
"""The shared answer to "is this artefact PUBLISHED?", after three programs got
it wrong the same way in one session.

Each asked the LOCAL DISK whether an artefact is there, when the question was
whether the published tree carries it. A working checkout also holds whatever
the last local run left behind; a fresh clone and a `git worktree` hold only
tracked files. The result was three gates giving DIFFERENT VERDICTS ON
DIFFERENT HOSTS for byte-identical code — and always in the same direction:
whoever runs the flow locally fails, whoever does not, passes.

The two states this module must never merge are `None` ("not a published tree,
use the disk") and an empty published set ("published, ships nothing"). Merging
them turns "I could not look" into "I looked and there is nothing", which is
the false-certificate shape that produced all three defects.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import _published_tree as P  # noqa: E402


def _repo(tmp_path: Path, *, commit: tuple[str, ...] = ()) -> Path:
    r = tmp_path / "r"
    (r / "sub").mkdir(parents=True)
    (r / "tracked.txt").write_text("a\n")
    (r / "sub" / "nested.txt").write_text("b\n")
    (r / "leftover.txt").write_text("c\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    if commit:
        subprocess.run(["git", "-C", str(r), "add", *commit], check=True)
        subprocess.run(["git", "-C", str(r), "commit", "-qm", "publish"],
                       check=True)
    return r


def test_tracked_paths_are_returned_relative_to_root(tmp_path):
    r = _repo(tmp_path, commit=("tracked.txt", "sub/nested.txt"))
    assert P.published_paths(r) == frozenset({"tracked.txt", "sub/nested.txt"})


def test_an_untracked_leftover_is_not_published(tmp_path):
    r = _repo(tmp_path, commit=("tracked.txt",))
    pub = P.published_paths(r)
    assert "leftover.txt" not in pub
    assert P.is_published(r, "leftover.txt") is False
    assert P.is_published(r, "tracked.txt") is True


def test_outside_a_repository_the_disk_is_the_answer(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "x.txt").write_text("x\n")
    assert P.published_paths(d) is None
    assert P.is_published(d, "x.txt") is True
    assert P.is_published(d, "absent.txt") is False


def test_a_repo_with_nothing_committed_is_not_a_published_tree(tmp_path):
    """The discriminator that keeps a raw run directory working when it happens
    to sit inside a repository. Returning an empty SET here would declare that
    it ships nothing and flip every present file to absent."""
    r = _repo(tmp_path)
    assert P.published_paths(r) is None
    assert P.is_published(r, "tracked.txt") is True


def test_require_keys_publishedness_to_the_artefact_that_defines_it(tmp_path):
    """A deliverable is published when ITS OWN ledger is — not when some file
    under it happens to be committed."""
    r = _repo(tmp_path, commit=("tracked.txt",))
    assert P.published_paths(r, require="tracked.txt") is not None
    assert P.published_paths(r, require="provenance.jsonl") is None
    # ...and with require unmet, the caller falls back to the disk
    assert P.is_published(r, "leftover.txt", require="provenance.jsonl") is True


def test_filter_keeps_only_published_paths_in_order(tmp_path):
    r = _repo(tmp_path, commit=("tracked.txt", "sub/nested.txt"))
    got = P.filter_to_published(
        r, [r / "sub" / "nested.txt", r / "leftover.txt", r / "tracked.txt"])
    assert [p.name for p in got] == ["nested.txt", "tracked.txt"]


def test_filter_keeps_everything_when_nothing_is_published(tmp_path):
    """Paired half: a run tree handed over on its own must not be filtered to
    zero — a gate that walks nothing reports a clean corpus it never read."""
    d = tmp_path / "run"
    d.mkdir()
    (d / "a.txt").write_text("a\n")
    assert [p.name for p in P.filter_to_published(d, [d / "a.txt"])] == ["a.txt"]


def test_a_path_outside_root_is_dropped_not_kept(tmp_path):
    """Traversal guard: `relative_to` raising must not fall through to keep."""
    r = _repo(tmp_path, commit=("tracked.txt",))
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x\n")
    assert P.filter_to_published(r, [outside]) == []


def test_all_three_callers_use_this_module_rather_than_their_own_copy():
    """The point of the module. A fourth private copy is how this defect class
    came back three times; if someone adds one, this fails."""
    import re
    suspects = ["provenance_output_hash_completeness_check.py",
                "cross_layer_reference_check.py",
                "l4_systemrdl_export.py"]
    for name in suspects:
        src = (_PROGRAMS / name).read_text()
        assert "_published_tree" in src, f"{name} no longer uses the shared helper"
        # its own `git ls-files` call would be a private re-implementation
        assert not re.search(r'"ls-files"', src), \
            f"{name} calls git ls-files directly again"

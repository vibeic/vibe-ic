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
# The real-data arm at the bottom walks the PUBLISHED tree's git index, which
# now lives in vibeic/benchmark-data. `_published_corpus` owns the single "is a
# published cell readable here?" answer and the single skip reason.
from _published_corpus import corpus_root, needs_corpus  # noqa: E402


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


# ---------------------------------------------------------------------------
# vibe-ic#404 — the hole the PATH filter left open: a tracked SYMLINK.
#
# Callers decide by path (`rel in published`) and then read by dereference
# (`(root / rel).read_text()`). For a tracked link whose target the index does
# not carry those are different questions: the link ships, its content does
# not. MEASURED on this repo at the landing commit — 20324 tracked paths, 172
# tracked symlinks, 43 pointing outside the index; 15 of those 43 readable on a
# working checkout and 0 in a clean worktree, which made one reader answer
# differently for 3 of 15 published cells from the SAME commit.
# ---------------------------------------------------------------------------

def _linked(tmp_path: Path, links: dict, *, extra_tracked=("real.txt",)) -> Path:
    """A published tree carrying `links` (name -> target text).

    Every target is also written to DISK, so a test that still reads the disk
    passes for the wrong reason unless the answer is taken from the index.
    """
    r = tmp_path / "r"
    (r / "sub").mkdir(parents=True)
    (r / "real.txt").write_text("published\n")
    (r / "sub" / "nested.txt").write_text("published\n")
    (r / "leftover.txt").write_text("local run output\n")
    (r / "sub" / "leftover.txt").write_text("local run output\n")
    for name, target in links.items():
        p = r / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(target)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", *extra_tracked, *links],
                   check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "publish"], check=True)
    return r


def test_a_tracked_link_to_an_untracked_target_is_not_published(tmp_path):
    """The #404 hole. The link is tracked and the target is RIGHT THERE on this
    disk — and a reader who clones receives a dangling link. Absent is the only
    answer that is the same on both hosts."""
    r = _linked(tmp_path, {"link.txt": "leftover.txt"})
    assert (r / "link.txt").read_text() == "local run output\n"   # on THIS disk
    assert "link.txt" not in P.published_paths(r)
    assert P.is_published(r, "link.txt") is False


def test_a_tracked_link_to_a_tracked_target_stays_published(tmp_path):
    """The paired half. Over-refusing would delete real published content — 128
    of this repo's 172 tracked links point at tracked files."""
    r = _linked(tmp_path, {"link.txt": "real.txt"})
    assert "link.txt" in P.published_paths(r)
    assert P.is_published(r, "link.txt") is True


def test_a_tracked_link_to_a_tracked_directory_stays_published(tmp_path):
    """git tracks files, never directories, so directory-ness is a prefix
    question. One corpus link is of this shape; treating it as hollow would
    drop content a clean clone does receive."""
    r = _linked(tmp_path, {"link": "sub"}, extra_tracked=("sub/nested.txt",))
    assert "link" in P.published_paths(r)


def test_a_link_reaching_out_of_the_published_tree_is_not_published(tmp_path):
    r = _linked(tmp_path, {"up.txt": "../outside.txt",
                           "sub/up.txt": "../../outside.txt"})
    pub = P.published_paths(r)
    assert "up.txt" not in pub and "sub/up.txt" not in pub


def test_an_absolute_link_is_not_published(tmp_path):
    """An absolute target names a location on THIS machine by construction."""
    (tmp_path / "abs.txt").write_text("x\n")
    r = _linked(tmp_path, {"abs.txt": str(tmp_path / "abs.txt")})
    assert "abs.txt" not in P.published_paths(r)


def test_a_chain_is_followed_to_where_it_actually_lands(tmp_path):
    """Stopping at one hop would call the first link published because its
    target is tracked — while the chain ends outside the tree. 0 of this
    repo's 172 links chain today, so this fixture is the only thing holding
    the loop honest."""
    r = _linked(tmp_path, {"a.txt": "b.txt", "b.txt": "leftover.txt",
                           "c.txt": "d.txt", "d.txt": "real.txt"})
    pub = P.published_paths(r)
    assert "a.txt" not in pub and "b.txt" not in pub
    assert "c.txt" in pub and "d.txt" in pub


def test_a_link_cycle_terminates_and_is_not_published(tmp_path):
    r = _linked(tmp_path, {"x.txt": "y.txt", "y.txt": "x.txt"})
    pub = P.published_paths(r)
    assert "x.txt" not in pub and "y.txt" not in pub


def test_the_link_target_is_read_from_the_index_not_from_the_disk(tmp_path):
    """Answering "where does this point?" with `os.readlink` would rebuild the
    host-dependence inside the fix. Here the COMMITTED link is hollow and the
    on-disk link has been repointed at published content; the index wins."""
    r = _linked(tmp_path, {"link.txt": "leftover.txt"})
    (r / "link.txt").unlink()
    (r / "link.txt").symlink_to("real.txt")
    assert (r / "link.txt").read_text() == "published\n"
    assert "link.txt" not in P.published_paths(r)


def test_a_tree_of_nothing_but_hollow_links_publishes_an_EMPTY_SET(tmp_path):
    """The fail-open that would re-open the hole at its worst. If the drop were
    allowed to empty the set, `published_paths` would return None, every caller
    would fall back to the disk, and it would read exactly the leftovers this
    refuses to read. Emptiness is decided on the RAW index."""
    r = _linked(tmp_path, {"link.txt": "leftover.txt"}, extra_tracked=())
    pub = P.published_paths(r)
    assert pub is not None, "a hollow-only tree fell back to the disk"
    assert pub == frozenset()
    assert P.is_published(r, "leftover.txt") is False


def test_require_is_not_satisfied_by_a_hollow_link(tmp_path):
    """A deliverable whose own ledger is a link to something unpublished has
    not published its ledger."""
    r = _linked(tmp_path, {"provenance.jsonl": "leftover.txt"})
    assert P.published_paths(r, require="provenance.jsonl") is None
    assert P.published_paths(r, require="real.txt") is not None


@needs_corpus
def test_on_the_real_repo_no_published_path_is_a_hollow_link():
    """REAL DATA, with the target set computed a second, independent way.

    The fixtures above are built to be hollow, so they cannot show the defect
    still exists in the shipped corpus. This walks the actual index, resolves
    every mode-120000 entry with its own `readlink`, and requires that none of
    the ones landing outside the index survives into `published_paths`.

    It refuses an empty tracked tree.  A non-empty tree with zero symlinks is
    now a real clean population, not a vacuous one: the publisher normalized
    the former links into tracked files/directories.  The hollow-link branch
    remains exercised in both directions by the fixtures above.

    THE TREE IT WALKS IS THE PUBLISHED ONE. Every one of the 126 tracked
    symlinks this guard was written against lived under `benchmark-data/`, and
    all of them moved to vibeic/benchmark-data.  The current corpus normalized
    those links away, so zero links is legitimate only after the corpus's own
    index proves a non-empty tracked population.  The test skips (naming the
    corpus) when that published tree is unavailable."""
    import os
    root = corpus_root()
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        import pytest
        pytest.skip("not a git work tree — the question does not apply")
    tracked, links = set(), []
    for ent in r.stdout.split("\0"):
        if not ent or "\t" not in ent:
            continue
        meta, path = ent.split("\t", 1)
        tracked.add(path)
        if meta.split()[0] == "120000":
            links.append(path)
    dirs = set()
    for p in tracked:
        parts = p.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    hollow = []
    for p in links:
        fp = root / p
        if not fp.is_symlink():
            continue
        t = os.readlink(fp)
        resolved = t if t.startswith("/") else os.path.normpath(
            os.path.join(os.path.dirname(p), t)).replace(os.sep, "/")
        if resolved not in tracked and resolved not in dirs:
            hollow.append(p)

    assert tracked, f"the published tree at {root} has no tracked population"
    pub = P.published_paths(root)
    assert pub is not None
    leaked = sorted(p for p in hollow if p in pub)
    assert not leaked, (
        f"{len(leaked)} of {len(hollow)} hollow link(s) (out of {len(links)} "
        f"tracked links, {len(tracked)} tracked paths) are still reported as "
        f"published; a reader dereferences them and gets this host's leftovers."
        f" First: {leaked[:3]}")


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

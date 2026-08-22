"""A citation this repo really ships is OUT OF SCOPE, not dangling.

`_resolves_outside_the_scan_root` walked up from the scan root and its comment
read "benchmark-data/ic -> benchmark-data -> repo root". That was true while the
published cells lived inside this repository. `c5d7f2d00` moved them to
`vibeic/benchmark-data`, making the scan root a SIBLING of the repo rather than
a child, so the walk arrived at $HOME and / instead — and a citation naming a
file this repo really ships was reported as `dangling`. The gate was reporting
its own scope as the document's defect, which is the failure #1044 is about and
the exact thing the `outside` class exists to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import evidence_citation_resolves_check as E  # noqa: E402

REPO = PROGRAMS.parents[3]


def test_a_file_this_repo_ships_is_outside_the_scan_root_not_dangling(tmp_path):
    """The regression, staged the way the move actually left things: a corpus
    that is a SIBLING of the repo, with no ancestor in common below $HOME."""
    corpus = tmp_path / "benchmark-data" / "ic"
    corpus.mkdir(parents=True)
    assert E._resolves_outside_the_scan_root(
        "tools/gatekeeper-land.sh", corpus), (
        "a path this repository ships was not recognised as living above the "
        "scan root, so it would be reported as a document's dangling citation")


def test_the_ancestor_walk_still_works_when_the_corpus_is_inside_the_repo(
        tmp_path):
    """The behaviour that existed before the move is not traded away for the
    behaviour after it — a corpus nested under any directory still resolves
    against that directory."""
    root = tmp_path / "corpus" / "ic"
    root.mkdir(parents=True)
    (tmp_path / "corpus" / "shipped.md").write_text("x", encoding="utf-8")
    assert E._resolves_outside_the_scan_root("shipped.md", root)


def test_a_citation_that_names_nothing_anywhere_is_still_dangling(tmp_path):
    """The direction that makes the other two mean something. Widening the
    search must not turn the gate into one that can never fail."""
    corpus = tmp_path / "benchmark-data" / "ic"
    corpus.mkdir(parents=True)
    assert not E._resolves_outside_the_scan_root(
        "tools/no-such-file-anywhere-9f3a.md", corpus)


def test_an_absolute_citation_is_never_rescued_by_the_widening(tmp_path):
    """Absolute paths are non-portable and were already never resolvable; the
    new search must not become a way for one to pass."""
    corpus = tmp_path / "benchmark-data" / "ic"
    corpus.mkdir(parents=True)
    assert not E._resolves_outside_the_scan_root(
        str(REPO / "tools" / "gatekeeper-land.sh"), corpus)


def test_the_repo_is_found_by_its_own_location_not_by_the_corpus(tmp_path):
    """The structural claim, asserted: the program locates the repository from
    where IT ships, so the answer does not depend on where the corpus sits."""
    a = tmp_path / "one" / "ic"
    b = tmp_path / "two" / "deep" / "ic"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert E._resolves_outside_the_scan_root("tools/gatekeeper-land.sh", a)
    assert E._resolves_outside_the_scan_root("tools/gatekeeper-land.sh", b)

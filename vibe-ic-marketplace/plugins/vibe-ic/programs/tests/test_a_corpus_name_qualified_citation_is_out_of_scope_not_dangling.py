#!/usr/bin/env python3
"""A corpus document naming the corpus BY ITS OWN REPOSITORY NAME is not
citing a missing proof.

MEASURED on the stamp full-tier run of 2026-08-31. One of the fourteen NEW
dangling citations is

    spm/v1.5.65_sky130A/RESULT.md :: benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md

and the citing sentence is

    One cell (IC x PDK) of the open-PDK matrix. See
    `benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` for the full matrix's
    current per-cell status.

THE FILE EXISTS. It is `BENCHMARK_IC_CAMPAIGN_STATUS.md` at the ROOT of the
published corpus clone -- tracked, 9,168 bytes, present on that repository's
`main`. The document is correct and this gate is simply not the one that
judges it.

WHY IT DID NOT RESOLVE. The citation carries the corpus's own repository name
as its first segment, which is how the path was spelled while the published
tree lived INSIDE this repository at `benchmark-data/ic` -- there,
`<repo>/benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` resolved against the
repository-root base and the notation was simply true. `chore: move published
benchmark results to vibeic/benchmark-data` (c5d7f2d00) made the corpus a
separate clone whose ROOT is that tree, so the same spelling now names one
directory level that no longer exists, and the file moved out from under the
one base that used to reach it. This is the SECOND half of the loss that
commit's own comment already records ("the disclosed OUT OF SCOPE count fell
from 7 to 2").

WHY THE RECONCILIATION IS NOT A GUESS. `_corpus_location.CANONICAL_CORPUS_NAME`
already exists and already means exactly this -- "what the published corpus
tree was CALLED while it lived in this repository" -- and its docstring already
rules that the two spellings "must be reconciled DELIBERATELY and in one place
rather than by each gate guessing." This gate was guessing (by omission). It
now consults the seam.

BOUNDED, in the same shape as the plugin-root base beside it: stripping the
prefix retires a finding ONLY when the named file is really in the corpus
clone. Every control below is a case that must STILL be reported.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "evidence_citation_resolves_check.py"

spec = importlib.util.spec_from_file_location("_evidence_citation_corpusname", GATE)
assert spec and spec.loader
G = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = G
spec.loader.exec_module(G)

sys.path.insert(0, str(PROGRAMS))
import _corpus_location as _corpus  # noqa: E402

pytestmark = pytest.mark.timeout(0)

NAME = _corpus.CANONICAL_CORPUS_NAME


def _clone(tmp_path, *, ship: bool = True):
    """A corpus clone in the shape c5d7f2d00 left behind: the published tree
    IS the clone root, and the gate's scan root is `ic` inside it."""
    clone = tmp_path / "some-checkout-name"
    (clone / "ic" / "spm" / "v1.5.65_sky130A").mkdir(parents=True)
    if ship:
        (clone / "BENCHMARK_IC_CAMPAIGN_STATUS.md").write_text("# matrix\n")
    return clone / "ic"


def test_the_stamp_red_a_corpus_name_qualified_citation_resolves(tmp_path):
    """THE STAMP RED. The cited file ships at the corpus root; the gate could
    not see it because the citation names the corpus by its repository name."""
    root = _clone(tmp_path)
    assert G._resolves_outside_the_scan_root(
        f"{NAME}/BENCHMARK_IC_CAMPAIGN_STATUS.md", root) is True


def test_the_checkout_directory_name_is_irrelevant(tmp_path):
    """The clone above is deliberately NOT called `benchmark-data`. Resolving
    by the checkout's own directory name would be the 'inference from where the
    corpus happens to sit' that c5d7f2d00 removed, and would give two machines
    opposite verdicts on identical trees."""
    root = _clone(tmp_path)
    assert root.parent.name != NAME
    assert G._resolves_outside_the_scan_root(
        f"{NAME}/BENCHMARK_IC_CAMPAIGN_STATUS.md", root) is True


def test_a_corpus_name_qualified_path_that_does_not_exist_is_still_dangling(
        tmp_path):
    """THE NEGATIVE CONTROL. Stripping a prefix is the RETIRING direction, so
    it must retire only citations naming a file that is really there."""
    root = _clone(tmp_path, ship=False)
    assert G._resolves_outside_the_scan_root(
        f"{NAME}/BENCHMARK_IC_CAMPAIGN_STATUS.md", root) is False


def test_only_the_canonical_corpus_name_is_stripped(tmp_path):
    """NEGATIVE CONTROL. A citation whose first segment is some OTHER directory
    must not have it stripped -- otherwise `phase3/stage3/pnr/openroad.log`
    could resolve against an unrelated `stage3/pnr/openroad.log` and the gate
    would launder real holes."""
    root = _clone(tmp_path)
    (root.parent / "elsewhere.md").write_text("x\n")
    assert G._resolves_outside_the_scan_root(
        "not-the-corpus/elsewhere.md", root) is False


def test_the_bare_name_alone_is_not_a_resolution(tmp_path):
    """NEGATIVE CONTROL. The prefix must be a PATH SEGMENT followed by a
    remainder; the corpus name on its own names a directory, not a proof."""
    root = _clone(tmp_path)
    assert G._resolves_outside_the_scan_root(NAME, root) is False
    assert G._resolves_outside_the_scan_root(f"{NAME}/", root) is False


def test_the_strip_cannot_escape_the_corpus_clone(tmp_path):
    """NEGATIVE CONTROL. The remainder is resolved INSIDE the clone; a
    traversal that climbs back out must not resolve, or the prefix becomes a
    way to reach anything on the machine."""
    root = _clone(tmp_path)
    (tmp_path / "outside.md").write_text("x\n")
    assert G._resolves_outside_the_scan_root(
        f"{NAME}/../outside.md", root) is False


def test_an_absolute_path_is_unaffected(tmp_path):
    """Absolute paths are non-portable and were never resolvable here."""
    root = _clone(tmp_path)
    target = root.parent / "BENCHMARK_IC_CAMPAIGN_STATUS.md"
    assert G._resolves_outside_the_scan_root(str(target), root) is False

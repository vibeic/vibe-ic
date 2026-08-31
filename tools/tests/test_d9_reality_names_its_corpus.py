#!/usr/bin/env python3
"""A committed statistic ABOUT a corpus must name the corpus, and the name must check.

WHAT WENT WRONG, MEASURED
=========================
`tools/d9_reality/d9_reality.json` published `corpus: {"runs": 107, "how": "git ls-files
benchmark-data | dirs containing phase1/generated_docs/"}` and named no corpus at all.
Its generator, `tools/d9_flow_gate_reality.py`, reads the corpus from the hard-coded path
`REPO / "benchmark-data"` and says in its own refusal that it "has no option to point it
elsewhere", so once the corpus moved the artefact became unregenerable — and unnamed
evidence that cannot be regenerated cannot be checked by anything.

It is worse than unnamed. The artefact's own commit is `c45c502ce` [v1.10.70], 2026-08-18.
The corpus left this repository at `c5d7f2d00`, 2026-08-16. Re-deriving the figure by the
artefact's OWN method at its OWN commit gives **0**, not 107: it was landed two days after
its subject was gone, and nothing recorded that.

WHY THIS GATE CAN RUN WHEN THE GENERATOR CANNOT
===============================================
`corpus.how` is INDEX-based, so the figure is a function of a git tree and not of a
checkout. `git ls-tree -r <commit> -- benchmark-data` re-derives it offline, from history
this repository still carries, with no corpus mounted and no network. That is the whole
reason an identity is demanded in this particular form: it is the one identity that is
verifiable here, today, by anyone.

THE CONTRACT
============
`corpus.identity.reproduces_at` names a commit. Re-deriving `corpus.runs` at that commit
must give exactly `corpus.runs`. An artefact that names a commit where its own figure is
false is worse than one that names nothing, because it looks checked.

MEASURED over all 46 commits that ever touched `benchmark-data`: 107 holds exactly across
`cdc54d32f..ae800cb70` (2026-08-02..2026-08-12), 106 before it, 105 from `e73601fec`, and 0
from `c5d7f2d00` onward. The window is why `reproduces_at` is a commit and not a date.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTEFACT = REPO / "tools" / "d9_reality" / "d9_reality.json"

#: The commit that PUBLISHED the artefact. It is the negative control: the figure does not
#: re-derive here, so a gate that passes at this commit is not measuring anything.
PUBLISHED_AT = "c45c502ce"


def _run_dirs_at(commit: str) -> int:
    """`corpus.how`, re-derived from a git TREE. No corpus checkout is needed."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", "benchmark-data"],
        cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip(f"commit {commit} is not in this checkout's history: "
                    f"{out.stderr.strip()[:120]}")
    runs = {line.split("/phase1/generated_docs/", 1)[0]
            for line in out.stdout.splitlines()
            if "/phase1/generated_docs/" in line}
    return len(runs)


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(ARTEFACT.read_text(encoding="utf-8"))


def test_the_artefact_names_the_corpus_it_measured(report):
    """An unnamed corpus figure is unfalsifiable, which is the whole defect."""
    identity = (report.get("corpus") or {}).get("identity")
    assert identity, (
        f"{ARTEFACT.relative_to(REPO)} states corpus figures and carries no "
        f"`corpus.identity`. A statistic ABOUT a corpus that does not say WHICH "
        f"corpus cannot be checked by anyone, on any host.")
    for field in ("reproduces_at", "method", "published_at"):
        assert identity.get(field), f"`corpus.identity.{field}` is missing or empty"


def test_the_named_commit_actually_reproduces_the_figure(report):
    """The identity must be TRUE, not merely present.

    A commit that does not reproduce the figure is worse than no commit at all: it
    reads as verified. This is the assertion that makes the identity load-bearing.
    """
    corpus = report["corpus"]
    identity = corpus.get("identity") or {}
    named = identity.get("reproduces_at")
    assert named, (
        "no `corpus.identity.reproduces_at` to check — "
        "test_the_artefact_names_the_corpus_it_measured says why")
    live = _run_dirs_at(named)
    assert live == corpus["runs"], (
        f"`corpus.identity.reproduces_at` names {named}, where the artefact's own "
        f"method yields {live} run dir(s) — but the artefact publishes "
        f"corpus.runs={corpus['runs']}. Either the figure or the commit is wrong; "
        f"re-derive the window with `git ls-tree -r <commit> -- benchmark-data` "
        f"over the commits that touched benchmark-data, and name a commit where "
        f"the figure is TRUE.")


def test_the_publishing_commit_is_the_negative_control(report):
    """PAIRED CONTROL: the gate must be able to fail, and here is where it does.

    The artefact was committed at `c45c502ce`, two days after the corpus left the
    repository. Re-deriving there gives 0. If this ever equalled `corpus.runs`, the
    check above would be satisfied by the artefact's own commit and would stop
    distinguishing a named corpus from an absent one — so the distance between the
    two commits IS the measurement, and it is asserted rather than assumed.
    """
    corpus = report["corpus"]
    identity = corpus.get("identity")
    assert identity, (
        "no `corpus.identity` to control against — "
        "test_the_artefact_names_the_corpus_it_measured says why")
    at_publish = _run_dirs_at(PUBLISHED_AT)
    assert at_publish != corpus["runs"], (
        f"the figure now ALSO re-derives at the publishing commit {PUBLISHED_AT} "
        f"({at_publish}); this control no longer separates a named corpus from an "
        f"unnamed one and must be re-derived rather than deleted")
    assert at_publish == identity.get("reproduces_at_published_commit"), (
        f"the artefact records that its method yields "
        f"{identity.get('reproduces_at_published_commit')} at {PUBLISHED_AT}; "
        f"live it yields {at_publish}")


def test_the_generator_still_cannot_reach_the_corpus(report):
    """The identity is a WORKAROUND, and it must stop being needed, not linger.

    `d9_flow_gate_reality.py` reads the corpus from a hard-coded in-repo path. While
    that is true the artefact cannot be regenerated and the recorded identity is the
    only thing standing behind its figures. If the generator ever gains the corpus
    pointer every other corpus reader uses, this test reddens — which is the signal
    to regenerate against a named corpus and record THAT, instead of a commit window
    reconstructed from history.
    """
    src = (REPO / "tools" / "d9_flow_gate_reality.py").read_text(encoding="utf-8")
    assert 'BENCH = REPO / "benchmark-data"' in src, (
        "d9_flow_gate_reality.py no longer resolves the corpus from the hard-coded "
        "in-repo path. Regenerate d9_reality.json against the corpus the pointer "
        "now names and record ITS identity; then re-derive this test.")
    assert "CANNOT CHECK" in src, (
        "the refusal that makes the artefact unregenerable is gone; re-derive the "
        "identity contract against whatever replaced it")

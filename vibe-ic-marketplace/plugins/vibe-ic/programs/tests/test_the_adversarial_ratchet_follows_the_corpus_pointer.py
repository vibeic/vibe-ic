#!/usr/bin/env python3
"""The 63x8 adversarial ratchet must be REACHABLE, or it measures nothing.

THE DEFECT THIS PINS, MEASURED
==============================
`c5d7f2d00` moved the published results out of this repository. The ratchet that
re-runs the recorded attacks resolved its cells as `REPO / "benchmark-data" /
"ic" / ...`, a literal rather than a question, so from that commit it could not
reach a cell on ANY host. Measured on `053eecd27`, with a readable clone at
`$VIBE_IC_BENCHMARK_DATA`::

    $ VIBE_IC_BENCHMARK_DATA=<clone> pytest tests/test_adversarial_agent.py -q
    9 passed, 12 skipped

Twelve of the twenty-one tests, including
`test_the_findings_ratchet_holds_in_BOTH_directions`, were unreachable with the
corpus present and correctly named. For that whole span the thirteen recorded
findings were adjudicated by nothing: a gate that started forging a green would
not have been noticed, and a gate that stopped would not have been credited.

WHY A SKIP IS THE WRONG SHAPE HERE, AND WHY THIS TEST IS NOT ONE
================================================================
The program the ratchet drives already distinguishes the three cases in its own
verdicts — SUCCEEDED, DEFENDED, and UNAVAILABLE-with-the-reason — and its
docstring names the exact scenario: "a corpus prune would silently close all
thirteen and the ratchet would be measuring the publication schedule instead of
the gates". That reasoning was sound and it was defeated one layer below, by a
`pytest.mark.skipif` over a path that could no longer resolve. UNAVAILABLE never
got the chance to be reported, because no attack was ever attempted.

So this file asks a question that needs NO corpus: given a corpus, does the
ratchet look where it was told? It builds a synthetic one, points the pointer at
it, and re-imports. That runs identically on a host with a clone and on a host
without one, which is the property the thing it guards lost.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _published_corpus as PC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The three run trees the recorded finding set names. Spelled here so a rename
#: on either side is a failure rather than a silent skip.
_RECORDED = (
    ("spm", "v1.9.96_gf180mcuD"),
    ("sha256", "clean_run_v1427_20260715"),
    ("sha256", "clean_run_v1422_20260715"),
)


def _synthetic_corpus(root: Path) -> Path:
    """A corpus shaped like the published one, carrying the three named trees.

    It holds no reports: this file asks WHERE the ratchet looks, never what it
    finds there. Attacking a synthetic cell would measure the fixture.
    """
    for parts in _RECORDED:
        (root / "ic" / parts[0] / parts[1]).mkdir(parents=True, exist_ok=True)
    return root


def _reload_ratchet():
    for name in ("_published_corpus", "test_adversarial_agent"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    return importlib.import_module("test_adversarial_agent")


@pytest.fixture
def pointed_at_a_corpus(tmp_path, monkeypatch):
    root = _synthetic_corpus(tmp_path / "benchmark-data")
    monkeypatch.setenv(PC.CORPUS_ENV, str(root))
    yield root
    for name in ("_published_corpus", "test_adversarial_agent"):
        if name in sys.modules:
            del sys.modules[name]


def test_the_recorded_cells_resolve_under_the_pointer(pointed_at_a_corpus):
    """CELL / DONOR / OLDER come from the pointer, not from a repo-local literal.

    THE FAILURE THIS CATCHES is the one that actually happened: the names still
    resolve to *something*, so nothing raises — they resolve to a path under a
    repository that stopped carrying the corpus, and every test gated on them
    goes quiet.
    """
    root = pointed_at_a_corpus
    mod = _reload_ratchet()
    for attr, parts in zip(("CELL", "DONOR", "OLDER"), _RECORDED):
        got = getattr(mod, attr)
        assert got is not None, (
            f"{attr} did not resolve although the pointer names a corpus "
            f"carrying ic/{parts[0]}/{parts[1]}. An unreachable ratchet reports "
            f"nothing and reads as nothing wrong.")
        assert root in got.parents, (
            f"{attr} resolved to {got}, which is NOT under the corpus named by "
            f"${PC.CORPUS_ENV} ({root}). The ratchet is reading a path it "
            f"spelled itself instead of the corpus it was given — that is how "
            f"12 of its 21 tests went to a silent skip at c5d7f2d00.")


def test_the_corpus_gate_opens_when_the_corpus_is_there(pointed_at_a_corpus):
    """The skip mark must actually lift. Resolving is not the same as running."""
    mod = _reload_ratchet()
    mark = mod._corpus
    assert not mark.args[0], (
        "the corpus skip is still in force with a readable corpus at "
        f"${PC.CORPUS_ENV}. Every attack below it is unattempted, and an "
        "attack nobody ran is not an attack that failed.")


def test_the_skip_reason_is_the_suites_one_reason(pointed_at_a_corpus):
    """One reason, so a reader who greps for one quiet corpus check finds all.

    The private spelling this replaces — "published cells absent from this
    checkout" — was true and useless: it named no pointer, so nobody reading it
    learned that setting one would have run the tests.
    """
    mod = _reload_ratchet()
    assert mod._corpus.kwargs["reason"] == PC.SKIP_REASON, (
        "the ratchet skips with a reason of its own instead of the shared one; "
        f"got {mod._corpus.kwargs['reason']!r}")


def test_the_generator_refuses_rather_than_publishing_an_empty_finding_set(
        monkeypatch):
    """No corpus must not render as "every finding closed".

    `tools/gen_adversarial_findings.py` writes the ratchet's own subject, and it
    is the only supported way to write it — the file says so, because a
    hand-edited finding list is an allowlist. Run with no corpus it attempts
    nothing, finds nothing forging, and writes an EMPTY `forging` list. The
    ratchet then reads thirteen findings closed on the day the corpus moved,
    with no fix anywhere near them.

    Asserted by RUNNING it, not by reading it: the refusal has to happen before
    the write, and only the exit code proves the order.
    """
    monkeypatch.delenv(PC.CORPUS_ENV, raising=False)
    gen = PC._REPO / "tools" / "gen_adversarial_findings.py"
    assert gen.is_file(), f"{gen} is missing"
    if PC.corpus_root() is not None:
        pytest.skip("this checkout carries a corpus; the no-corpus path is "
                    "not reachable here")
    r = _pr.run([sys.executable, str(gen), str(PC._PLUGIN)],
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert r.returncode != 0, (
        "the generator exited 0 with no corpus to measure. Whatever it wrote, "
        f"it measured nothing:\n{out[:2000]}")
    assert "REFUSED" in out, (
        f"the generator failed without refusing by name; a reader cannot tell "
        f"'no corpus' from 'the campaign found nothing':\n{out[:2000]}")


def test_the_repo_local_corpus_branch_looks_at_the_repository():
    """`corpus_root()`'s no-pointer branch must look where a corpus would BE.

    It resolved `vibe-ic-marketplace/benchmark-data` — one level short of the
    repository root, a path that has never existed here. The bug could not be
    seen from its behaviour, because the only tree it fails to find is one this
    repository stopped carrying in the same period. It is asserted rather than
    reasoned about because that is the whole difficulty: an inert wrong answer
    and a correct answer are the same observation until the corpus comes back.
    """
    repo = _HERE.parents[4]
    assert (repo / ".git").exists(), (
        f"the test's own idea of the repository root ({repo}) is not one; "
        f"fix this test before trusting what it says about the helper")
    assert PC._REPO == repo, (
        f"_published_corpus._REPO is {PC._REPO}, not the repository root "
        f"{repo}. Its repo-local corpus branch reads <that>/benchmark-data, so "
        f"a checkout that DOES carry published cells is reported as carrying "
        f"none — the opposite of this module's stated guarantee.")
    assert PC._PLUGIN == repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic", (
        f"_published_corpus._PLUGIN is {PC._PLUGIN}, which is not the plugin")

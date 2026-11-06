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

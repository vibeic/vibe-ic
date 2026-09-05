"""A landing's production-corpus binding may not retarget synthetic tests.

The landing process intentionally exports both variables below so production
gates read the byte-attested benchmark-data checkout.  Pytest fixtures own
their own populations, however.  Letting the outer environment replace those
fixtures made the v1.17.21 exact-tree stamp report 54 failures about a corpus
none of the failing tests had asked to inspect.

Run this file with both variables exported for the behavioural negative
control: it fails before the conftest repair and passes after it.  The second
test proves that a test which actually exercises the binding can still opt in
explicitly after the isolation fixture has run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("landing_corpus_binding_is_test_local")

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _corpus_location as corpus_location  # noqa: E402


def test_outer_landing_corpus_binding_does_not_retarget_synthetic_tests():
    assert corpus_location.BOUND_SHA_ENV not in os.environ
    assert corpus_location.CORPUS_ENV not in os.environ


def test_a_test_can_explicitly_opt_in_to_the_bound_corpus(monkeypatch, tmp_path):
    bound = tmp_path / "bound-corpus"
    bound.mkdir()
    monkeypatch.setenv(corpus_location.BOUND_SHA_ENV, "0" * 40)
    monkeypatch.setenv(corpus_location.CORPUS_ENV, str(bound))

    resolved, origin = corpus_location.resolve(
        tmp_path / "candidate-local-corpus", gate="fixture")

    assert resolved == bound
    assert origin == corpus_location.ENV

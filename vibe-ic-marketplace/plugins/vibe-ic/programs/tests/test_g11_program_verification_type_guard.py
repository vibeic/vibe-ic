"""Fixture-independent control for the Shape-C acceptance predicate's type guard.

``_validate_ai_review`` read ``task["program_verification"]`` as
``... or {}``.  That launders a FALSY non-dict (``[]``, ``None``) but not a
truthy one: ``"not-an-object"`` and ``7`` reached ``.get()`` and raised
``AttributeError`` out of the acceptance predicate.  A fail-closed guard may
refuse; it may not crash, because a ``BLOCKED`` exit is legible to the
operator and a traceback out of the predicate is not -- and the crash defeats
the very test that exists to prove malformed input blocks *cleanly*.

These assertions are on the predicate itself, not on any Shape-C export
fixture, so they stay red against the pre-fix program on their own.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import benchmark_dispatch as dispatch


def _minimal_task(tmp_path: Path, program_verification) -> dict:
    """A hash-bound task carrying a real review file, nothing else asserted."""
    review = tmp_path / "review.json"
    prompt = tmp_path / "prompt.md"
    prompt_text = "Implement a module named TopModule.\n"
    prompt.write_text(prompt_text)
    prompt_sha = hashlib.sha256(prompt_text.encode()).hexdigest()
    review.write_text(json.dumps({
        "schema": dispatch._AI_REVIEW_SCHEMA,
        "id": "Prob900_neutral",
        "prompt_sha256": prompt_sha,
        "rtl_sha256": "0" * 64,
        "reviewer": {"kind": "AI", "model": "control-reviewer"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {"verdict": "PASS", "findings": [],
                            "rationale": "control review, basis stated here."},
    }) + "\n")
    return {
        "schema": dispatch._REVIEW_TASK_SCHEMA,
        "id": "Prob900_neutral",
        "prompt_path": str(prompt.resolve()),
        "prompt_sha256": prompt_sha,
        "rtl_sha256": "0" * 64,
        "review_path": str(review.resolve()),
        "program_routing": {"nature": "spec_generation"},
        "program_verification": program_verification,
    }


@pytest.mark.parametrize("malformed", ["not-an-object", 7, 1.5, True])
def test_truthy_non_dict_program_verification_is_named_not_a_traceback(
        tmp_path, malformed):
    """The predicate must NAME the malformed record, never raise."""
    verdict = dispatch._validate_ai_review(
        _minimal_task(tmp_path, malformed))
    reasons = [str(r) for r in verdict.get("reasons") or []]
    assert verdict.get("status") != "ACCEPTED"
    assert any("verification record is malformed" in r for r in reasons), reasons


@pytest.mark.parametrize("malformed", [[], {}])
def test_falsy_non_dict_program_verification_still_refuses(tmp_path, malformed):
    """Negative arm: the guard must not become 'accept everything'."""
    verdict = dispatch._validate_ai_review(
        _minimal_task(tmp_path, malformed))
    assert verdict.get("status") != "ACCEPTED"


def test_a_well_formed_but_unaccepted_record_is_still_refused(tmp_path):
    """Negative arm: a dict-shaped record does not buy acceptance."""
    verdict = dispatch._validate_ai_review(_minimal_task(tmp_path, {
        "actor": "vibe_ic_one_shot_runner",
        "rtl_gen": "PASS",
        "runner_rc": 0,
        "functional_evidence": "PASS",
        "functional_confirmation_required": False,
    }))
    assert verdict.get("status") != "ACCEPTED"
    reasons = [str(r) for r in verdict.get("reasons") or []]
    assert not any("verification record is malformed" in r for r in reasons)

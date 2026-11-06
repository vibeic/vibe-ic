"""Public source declarations, normal L8 producer and unchanged strict consumer.

The document is the issue's public snippet, not the unavailable field corpus.
The review receipt below is a validator fixture, not an actual expert review.
"""
import json
from pathlib import Path

import pytest

import ai_signed_judgement as judgement
import phase1_doc_one_shot_runner as runner


PUBLIC = (Path(__file__).parent / "fixtures/phase1_local/"
          "source_literal_widths/design.md").read_text().rstrip("\n")


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path














def test_a_previous_d1_review_cannot_authorize_changed_l8_output(tmp_path):
    old_digest = judgement.evidence_sha256(tmp_path, "D1")
    _write(tmp_path, "reports/audit/ai_judgements/D1.json", json.dumps({
        "schema": judgement.SCHEMA, "step_id": "D1",
        "evidence_sha256": old_digest, "verdict": "PASS",
        "signed_by": "test-only-validator-fixture",
        "judgement": "Synthetic receipt for freshness rejection, not a real review.",
    }))
    assert judgement.check(tmp_path, "D1")[0] is True
    assert judgement.evidence_sha256(tmp_path, "D1") != old_digest
    valid, reason = judgement.check(tmp_path, "D1")
    assert valid is False
    assert "awaiting_signed_judgement" in reason

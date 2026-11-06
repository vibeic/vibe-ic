#!/usr/bin/env python3
"""Smoke tests for l25_reliability_envelope_actionable_check.py — batch-8.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every rule is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart must PASS.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied;
no real design, PDK or vendor token appears anywhere in this file. The
"qualification standard" strings below are invented placeholders on purpose —
the gate never matches a standards name, it only requires traceability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l25_reliability_envelope_actionable_check.py")
if str(PROG.parent) not in sys.path:
    sys.path.insert(0, str(PROG.parent))

import phase1_post_process as post_process  # noqa: E402


_SYNTH_CLASS = "synthetic_block_class_alpha"

# Synthesized source text — the only place any figure legitimately comes from.








def _emit_l25(project: Path) -> dict:
    return post_process.emit_l_doc_skeleton(
        "L25", _SYNTH_CLASS, project_dir=project)


def _producer_project(tmp_path, text, name="producer"):
    project = tmp_path / name
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "reliability.md").write_text(text, encoding="utf-8")
    return project


def test_source_silence_stays_applicable_and_unknown(tmp_path):
    proj = _producer_project(tmp_path, "A synchronous counter.\n")
    doc = _emit_l25(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "NOT_YET_EXTRACTED"
    assert "applicability_evidence" not in doc


def test_explicit_negative_reliability_fact_is_preserved(tmp_path):
    proj = _producer_project(
        tmp_path, "Reliability is not qualified for production use.\n")
    doc = _emit_l25(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    status = doc["fields"]["qualification_status"]
    assert status["status"] == "NOT_ESTABLISHED"
    assert status["citation"]["document"] == "input/docs/reliability.md"


def test_incidental_or_malformed_prose_does_not_authorize_absence(tmp_path):
    for text in ("The counter output is reliable.\n", "Qualification maybe.\n"):
        proj = _producer_project(tmp_path, text, name=str(abs(hash(text))))
        doc = _emit_l25(proj)
        assert doc["applicability"] == "APPLICABLE"
        assert doc["extraction_status"] == "NOT_YET_EXTRACTED"




# ===========================================================================
# POSITIVE DIRECTION
# ===========================================================================


# ===========================================================================
# NEGATIVE CONTROL
# ===========================================================================


# ===========================================================================
# No-false-positive direction
# ===========================================================================


# ===========================================================================
# Both directions on the SAME layer.
# ===========================================================================

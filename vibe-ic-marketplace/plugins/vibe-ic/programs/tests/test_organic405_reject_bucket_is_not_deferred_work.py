#!/usr/bin/env python3
"""ORGANIC #405 — a REJECTED bare-keyword row is provenance, not deferred work.

`L9.memory_candidates[]` is the reject bucket (#317 P3): every row in it is
one `_v1_6_441_is_useful_memory_entry` turned away. Those rows carried
`"low_confidence": true`, and `flow_compliance_check._STUB_TAG_RE` greps the
raw bytes of every evidence file for that token and reads a hit as DEFERRED
work — so a clean ingestion lost its PASS because the walker had correctly
rejected a phrase.

Two facts shared one token:
    "we have evidence and are not confident in it"  -> deferred work
    "we saw a bare keyword and REJECTED it"         -> provenance

Both directions are tested. Clearing the flag everywhere would be trivially
"green" and would also hide real deferred work, so the paired case asserts a
genuine low-confidence row still trips the scan.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import phase1_doc_one_shot_runner as P  # noqa: E402

# The exact expression flow_compliance_check runs over evidence-file bytes.
_STUB_TAG_RE = re.compile(
    r'deterministic_stub|"low_confidence"\s*:\s*true|low_confidence=true',
    re.IGNORECASE)


def test_a_rejected_row_no_longer_reads_as_deferred_work():
    marked = P._organic_405_mark_rejected(
        {"name": None, "kind": "fifo", "type": "FIFO", "port_count": None,
         "depth": None, "width": None, "low_confidence": True})
    assert marked["rejected_low_information"] is True
    assert "low_confidence" not in marked
    assert marked["rejection_reason"]
    assert not _STUB_TAG_RE.search(json.dumps({"memory_candidates": [marked]}))


def test_a_real_low_confidence_row_still_trips_the_scan():
    """The paired half. Clearing the token everywhere would pass the test
    above and quietly hide the deferred work the scan exists to surface."""
    real = {"name": "u_fifo", "kind": "fifo", "depth": 16, "width": 32,
            "low_confidence": True}
    assert _STUB_TAG_RE.search(json.dumps({"memories": [real]}))


def test_the_row_is_kept_not_deleted():
    """Deleting the row would throw away provenance #317 added on purpose.
    "found nothing" and "found a phrase and rejected it" are different facts."""
    src = {"name": None, "kind": "fifo", "type": "FIFO",
           "evidence_file": "x.md", "low_confidence": True}
    marked = P._organic_405_mark_rejected(src)
    assert marked["evidence_file"] == "x.md"
    assert marked["kind"] == "fifo" and marked["type"] == "FIFO"
    assert src.get("low_confidence") is True, "must not mutate the input"


def test_end_to_end_on_the_real_input_that_filed_the_issue():
    """The opentitan_aes candidate is mined from a paragraph explaining why
    the block does NOT use a FIFO. It must survive as provenance and must not
    downgrade the step."""
    docs = (_PROGRAMS.parents[3] / "benchmark-data" / "ic" / "opentitan_aes"
            / "input" / "docs")
    if not docs.is_dir():
        pytest.skip("benchmark input not present")
    extracted = {f.name: f.read_text(errors="replace")
                 for f in sorted(docs.glob("*.md"))}
    l9: dict = {}
    P._v1_6_426_emit_memories(l9, extracted)
    cands = l9.get("memory_candidates") or []
    assert cands, "the reject row must still be recorded as provenance"
    assert all("low_confidence" not in c for c in cands)
    assert all(c.get("rejected_low_information") is True for c in cands)
    assert not _STUB_TAG_RE.search(json.dumps(l9))


def test_the_emitter_never_puts_a_stub_token_in_the_reject_bucket():
    """Corpus sweep over real INPUTS, not committed outputs. An assertion on
    the committed artefacts would have to tolerate the 57 pre-fix rows and
    would say nothing about the emitter; this drives the emitter over every
    IC's own input docs and requires the reject bucket to be token-free."""
    root = _PROGRAMS.parents[3] / "benchmark-data" / "ic"
    if not root.is_dir():
        pytest.skip("no corpus")
    checked = 0
    for docs in sorted(root.glob("*/input/docs")):
        extracted = {f.name: f.read_text(errors="replace")
                     for f in sorted(docs.glob("*.md"))}
        if not extracted:
            continue
        l9: dict = {}
        P._v1_6_426_emit_memories(l9, extracted)
        checked += 1
        for c in (l9.get("memory_candidates") or []):
            assert "low_confidence" not in c, (docs, c)
    assert checked >= 3, f"swept only {checked} corpora — too few to mean anything"

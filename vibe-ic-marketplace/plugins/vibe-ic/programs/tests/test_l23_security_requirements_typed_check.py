#!/usr/bin/env python3
"""Smoke tests for l23_security_requirements_typed_check.py (layergate-7).

NEGATIVE CONTROL IS THE POINT
=============================
Both directions are asserted for every behaviour: gutted layer FAILs,
well-formed layer PASSes.

The asymmetry under test is deliberate. L23 has NO consumer anywhere in
the plugin, so:
  * the SELF-CONTRADICTION half (asserting security posture the layer
    cannot back) BLOCKS — it needs no consumer to be wrong;
  * the CROSS-LAYER half (requirement stated in the design's own inputs,
    absent from L23) ADVISES — there is no downstream contract to
    protect by stopping.

All fixtures are SYNTHESISED neutral data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(PROG.parent) not in sys.path:
    sys.path.insert(0, str(PROG.parent))

import phase1_post_process as post_process  # noqa: E402
import spi_protocol_synth  # noqa: E402






def _produce_l23(tmp_path, source_text):
    proj = tmp_path / "producer"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design.md").write_text(source_text, encoding="utf-8")
    doc = post_process.emit_l_doc_skeleton(
        "L23", "synthetic_block", project_dir=proj)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    path = gd / "L23_SECURITY_REQUIREMENTS.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    spi_protocol_synth.apply_spi_synth(gd, False, None)
    return proj, json.loads(path.read_text())


def test_security_silence_stays_unknown_through_normal_overlay(tmp_path):
    proj, doc = _produce_l23(tmp_path, "A small synchronous counter.\n")
    assert doc["fields"]["secure_boot"] is None
    assert doc["fields"]["security_requirements_present"] is None


def test_explicit_security_positive_is_preserved_as_typed_state(tmp_path):
    proj, doc = _produce_l23(
        tmp_path,
        "## Key handling\nThe session key must be cleared on reset.\n")
    assert doc["fields"]["security_requirements_present"] is True
    assert doc["fields"]["key_handling"]


def test_explicit_security_negative_is_preserved_verbatim(tmp_path):
    proj, doc = _produce_l23(
        tmp_path,
        "## Key handling\nNo key storage is implemented in this block.\n")
    assert doc["fields"]["security_requirements_present"] is True
    record = doc["fields"]["key_handling"][0]
    assert "No key storage" in record["description"]
    assert record["evidence"].startswith("input/docs/design.md:")
    assert doc["fields"]["secure_boot"] is None


def test_incidental_security_word_does_not_become_negative_fact(tmp_path):
    proj, doc = _produce_l23(
        tmp_path, "The fixture is secured to the bench with a clamp.\n")
    assert doc["fields"]["secure_boot"] is None
    assert doc["fields"]["security_requirements_present"] is None


# The shape observed in 24/24 sampled real runs: honest, asserts nothing.


# Synthetic requirement text: technology vocabulary + requirement framing.
# A passing mention with no requirement framing — must NOT trigger.


# ── skips ────────────────────────────────────────────────────────────









# ── F1 VACUOUS_SECURITY_ASSERTION — BLOCKS, negative control pair ────









# ── F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER — ADVISES ─────────────────







# ── waiver ───────────────────────────────────────────────────────────





# ── report emission ──────────────────────────────────────────────────

#!/usr/bin/env python3
"""Tests for crypto_arch_extractor.py — README crypto-architecture extractor.

Pins the real extraction logic: prose facts (digest/block/state/key/nonce
width, rounds, latency) are pulled into a structured dict with per-field
evidence; the bespoke scanners reject the documented false-positives
(chacha "64-bit block counter" must NOT become message_block_bits, and
"settable up to 32 rounds" must NOT win over the stated default).
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import crypto_arch_extractor as mod  # noqa: E402


# ----------------------------------------------------------------------
# PASS — a well-formed crypto README populates every field.
# ----------------------------------------------------------------------
def test_pass_extracts_all_fields():
    txt = (
        "The core produces a 256-bit digest.\n"
        "It uses 10 rounds per block.\n"
        "Processes a 512-bit message block.\n"
        "Internal 256-bit state.\n"
        "Completes in 64 cycles per block.\n"
        "Accepts a 256-bit key and a 96-bit nonce.\n"
    )
    out = mod.extract_crypto_arch(txt)
    assert out["digest_width_bits"] == 256
    assert out["message_block_bits"] == 512
    assert out["state_bits"] == 256
    assert out["rounds"] == 10
    assert out["latency_cycles_per_block"] == 64
    assert out["key_bits"] == 256
    assert out["nonce_bits"] == 96
    # every extracted field carries provenance evidence
    for f in ("digest_width_bits", "rounds", "key_bits"):
        ev = out[f"{f}_evidence"]
        assert ev["extraction_strategy"] == "crypto_arch_pattern_match"
        assert ev["line"] >= 1
        assert str(out[f].__class__.__name__) == "int"


# ----------------------------------------------------------------------
# The exact defects this extractor guards (documented in #40 4A / #42).
# ----------------------------------------------------------------------
def test_rejects_block_counter_as_message_block():
    # chacha README literally says "64-bit block counter" — this must NOT
    # be harvested as message_block_bits (the counter-context veto).
    txt = "ChaCha uses a 64-bit block counter for the keystream.\n"
    out = mod.extract_crypto_arch(txt)
    assert "message_block_bits" not in out


def test_default_rounds_beats_upper_bound_range():
    # "default 8, settable up to 32" must extract 8, never 32.
    txt = (
        "The default number of rounds is eight.\n"
        "It supports any number of rounds from two to 32 in steps of two.\n"
    )
    out = mod.extract_crypto_arch(txt)
    assert out["rounds"] == 8


def test_word_or_digit_to_int_helper():
    # English number-word path (chacha "eight") + digit path + unknown.
    assert mod._word_or_digit_to_int("eight") == 8
    assert mod._word_or_digit_to_int("thirty-two") == 32
    assert mod._word_or_digit_to_int("10") == 10
    assert mod._word_or_digit_to_int("banana") is None
    assert mod._word_or_digit_to_int(None) is None


# ----------------------------------------------------------------------
# Empty / garbage input -> empty dict (never fabricates a value).
# ----------------------------------------------------------------------
def test_empty_input_returns_empty_dict():
    assert mod.extract_crypto_arch("") == {}


def test_garbage_input_returns_empty_dict():
    out = mod.extract_crypto_arch(
        "lorem ipsum dolor sit amet, nothing technical here at all"
    )
    assert out == {}


def test_first_match_wins_does_not_aggregate():
    # Two digest mentions -> only the first is recorded (stable output).
    txt = "A 256-bit digest is produced.\nLater a 224-bit digest variant.\n"
    out = mod.extract_crypto_arch(txt)
    assert out["digest_width_bits"] == 256
    assert out["digest_width_bits_evidence"]["line"] == 1


def test_issue3288_round_rate_does_not_beat_block_latency(tmp_path):
    """The intake document must reach the ordinary L1 post-emitter."""
    from programs.tests._hostpaths import require_repo
    from programs import phase1_doc_one_shot_runner as producer

    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "neutral_round_vs_block_latency",
        "timing_contract.md",
    )
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "README.md").write_text(fixture.read_text())
    generated = tmp_path / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    l1 = generated / "L1_DATASHEET.json"
    l1.write_text(json.dumps({"class_path": "crypto_block_cipher"}))

    producer._post_emit_crypto_arch_into_L1(tmp_path)
    result = json.loads(l1.read_text())["architecture"]
    assert result["latency_cycles_per_block"] == 66
    evidence = result["latency_cycles_per_block_evidence"]
    assert evidence["line"] == 4
    assert evidence["matched_token"].lower() == "66 cycles per block"


def test_issue3288_round_only_has_no_block_latency():
    out = mod.extract_crypto_arch(
        "The cipher operates at approximately 1 cycle per round.\n")
    assert "latency_cycles_per_block" not in out
    assert "latency_cycles_per_block_evidence" not in out


@pytest.mark.parametrize("text,expected", [
    ("Latency is 66 cycles per block.\nThe core uses 1 cycle per round.", 66),
    ("The core uses 1 cycle per round.\nBlock latency is 66 cycles.", 66),
    ("Latency per block: 66 cycles.", 66),
    ("The core uses 1 cycle per round.\nA 66-cycle block latency applies.", 66),
    ("The core has a 66-cycle latency per block.", 66),
    ("Latency is 1 cycle per byte and 2 cycles per beat.", None),
    ("Latency is 1 cycle per iteration.", None),
    ("Variant A is 66 cycles per block.\nVariant B is 82 cycles per block.", None),
    ("Block latency is 66 cycles.\nAlso 66 cycles per block.", 66),
])
def test_issue3288_full_block_scope_and_conflicts(text, expected):
    out = mod.extract_crypto_arch(text)
    assert out.get("latency_cycles_per_block") == expected
    assert ("latency_cycles_per_block_evidence" in out) == (expected is not None)

#!/usr/bin/env python3
"""Tests for readme_usage_sequence_extractor.py — README numbered-step
host-usage-sequence picker (feeds L12.behavioral_sequences).

Pins the real heuristics and their false-positive defenses:
  * >=3 consecutive monotone-increasing numbered items,
  * >=half begin with a generic imperative verb (Load/Set/Write/...),
  * >=6 chars of action text after the "N." prefix,
  * a counter reset (or intervening prose line) starts a NEW sequence.
"""
from __future__ import annotations

# programs/ is on sys.path via programs/tests/conftest.py.
import readme_usage_sequence_extractor as mod  # noqa: E402

_extract = mod.extract_usage_sequence_from_readme


# ----------------------------------------------------------------------
# PASS — canonical crypto-IP usage sequence.
# ----------------------------------------------------------------------
def test_canonical_sequence():
    readme = (
        "## Usage\n"
        "1. Load key into key registers\n"
        "2. Set length bit in ctrl\n"
        "3. Write init bit\n"
        "4. Wait for ready\n"
        "5. Read digest\n"
    )
    seqs = _extract(readme)
    assert len(seqs) == 1
    seq = seqs[0]
    assert seq["name"] == "usage_sequence_1"
    assert seq["trigger"] == "host_initiates"
    assert seq["source"] == "readme_usage_sequence"
    assert len(seq["steps"]) == 5
    assert seq["steps"][0]["action"] == "Load key into key registers"
    assert seq["steps"][0]["step"] == 1
    assert all("evidence_line" in s for s in seq["steps"])


def test_counter_reset_splits_into_two_sequences():
    readme = (
        "1. Load aaaaaa\n"
        "2. Set bbbbbb\n"
        "3. Write cccccc\n"
        "1. Read dddddd\n"
        "2. Send eeeeee\n"
        "3. Poll ffffff\n"
    )
    seqs = _extract(readme)
    assert len(seqs) == 2
    assert seqs[0]["name"] == "usage_sequence_1"
    assert seqs[1]["name"] == "usage_sequence_2"


# ----------------------------------------------------------------------
# FAIL / floors — the defenses that suppress false positives.
# ----------------------------------------------------------------------
def test_too_few_steps_rejected():
    # Only 2 items -> below the >=3 floor.
    readme = "1. Load the key now\n2. Set the ctrl bit\n"
    assert _extract(readme) == []


def test_non_imperative_prose_list_rejected():
    # Descriptive prose (mostly "The ...") fails the imperative fraction.
    readme = (
        "1. The IP is reset internally on power up\n"
        "2. The block then waits idle until selected\n"
        "3. The output appears on the data bus eventually\n"
    )
    assert _extract(readme) == []


def test_short_action_text_breaks_sequence():
    # An item with <6 chars of action text flushes the run, dropping it
    # below the 3-step floor.
    readme = (
        "1. Load the key value\n"
        "2. Go\n"            # too short -> flush
        "3. Write the data\n"
        "4. Read the result\n"
    )
    # Remaining contiguous run after the flush is only 2 imperative
    # items (Write/Read) -> below floor -> no sequence.
    assert _extract(readme) == []


# ----------------------------------------------------------------------
# Edge — empty / None / no list.
# ----------------------------------------------------------------------
def test_empty_string():
    assert _extract("") == []


def test_none_input():
    assert _extract(None) == []


def test_no_numbered_list():
    assert _extract("Just prose describing the chip, no numbered steps.") == []


# ----------------------------------------------------------------------
# helper-level behavior.
# ----------------------------------------------------------------------
def test_first_word_lower_helper():
    assert mod._first_word_lower("Load the thing") == "load"
    assert mod._first_word_lower("  Set bit") == "set"
    assert mod._first_word_lower("123 not a word") == ""

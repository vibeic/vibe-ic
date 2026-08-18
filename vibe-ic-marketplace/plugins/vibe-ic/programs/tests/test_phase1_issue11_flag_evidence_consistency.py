"""tests/test_phase1_issue11_flag_evidence_consistency.py — v1.6.78

Closes GitHub issue #11.

Per-field `no_X_in_input` flag must consult the layer's
`extraction_evidence` map — when the evidence carries any source
whose filename matches the layer's topic pattern, the flag must be
False even if the structured field is empty. The L7 anti-pattern
reported in #11 (rich-input project's L7 emits `test_modes: []` +
`no_test_modes_in_input: true` while EngineerMode.txt remains in
extraction_evidence) is the canonical case.

Same shape exists across L1..L13. This file covers the helper
invariants plus per-topic positive / negative controls — 31
reject-test pairs total (5 helper invariants + 13 positive controls
+ 13 negative controls).
"""
from __future__ import annotations

import pytest

from programs.phase1_one_shot_runner import (
    _flag_no_X_in_input,
    _TOPIC_FILENAME_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helper invariants (5 tests)
# ---------------------------------------------------------------------------
def test_flag_helper_returns_false_when_structured_present():
    """Non-empty structured field → flag False regardless of evidence."""
    assert _flag_no_X_in_input([{"a": 1}], {}, "test_modes") is False


def test_flag_helper_returns_false_when_evidence_matches_topic():
    """Empty structured + evidence has topic-matched source → flag False."""
    evidence = {
        "input/docs/EngineerMode.txt": [{"matched": "engineer mode"}],
    }
    assert _flag_no_X_in_input([], evidence, "test_modes") is False


def test_flag_helper_returns_true_when_no_evidence_match():
    """Empty structured + no topic-matched source → flag True."""
    evidence = {"input/docs/PinList.txt": []}
    assert _flag_no_X_in_input([], evidence, "test_modes") is True


def test_flag_helper_unknown_topic_returns_true_on_empty():
    """Unknown topic key + empty structured → True (fallback)."""
    assert _flag_no_X_in_input([], {"x.txt": []}, "nonexistent_topic") is True


def test_flag_helper_handles_missing_evidence_map():
    """No evidence map → flag based on structured presence only."""
    assert _flag_no_X_in_input([], None, "test_modes") is True
    assert _flag_no_X_in_input([], {}, "test_modes") is True
    assert _flag_no_X_in_input([{"a": 1}], None, "test_modes") is False


# ---------------------------------------------------------------------------
# Per-topic positive controls (13 tests)
#
# Each layer's topic regex must match a representative filename so the
# flag flips False even when the structured extractor produced []. If
# any of these fail, the layer's flag becomes False-negative against
# real-world filename conventions.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("topic,positive_filename", [
    ("pin_table",            "input/docs/PinList.txt"),
    ("protocol_overview",    "input/docs/CommandProtocol.md"),
    ("crc_parameters",       "input/docs/CRC_Spec.txt"),
    ("registers",            "input/docs/RegisterMap.xlsx"),
    ("analog",               "input/docs/AnalogBlocks.md"),
    ("fsm",                  "input/docs/StateMachine.md"),
    ("test_modes",           "input/docs/EngineerMode.txt"),
    ("timing_constants",     "input/docs/TimingSpec.md"),
    ("integration",          "input/docs/Integration.md"),
    ("test_cases",           "input/docs/TestPlan.md"),
    ("otp_layout",           "input/docs/OTP_Layout.md"),
    ("behavioral_sequences", "input/docs/UseCases.md"),
    ("lab_calibration",      "input/docs/CalibrationProcedure.md"),
])
def test_flag_helper_per_topic_positive_match(topic, positive_filename):
    evidence = {positive_filename: [{"matched": "x"}]}
    assert _flag_no_X_in_input([], evidence, topic) is False, (
        f"Topic '{topic}' regex failed to match positive filename "
        f"'{positive_filename}' — flag should be False"
    )


# ---------------------------------------------------------------------------
# Per-topic negative controls (13 tests)
#
# A neutral filename (no topic-related keyword) must NOT match any of
# the layer regexes; otherwise the flag would never be set to True
# even on truly thin inputs.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("topic", list(_TOPIC_FILENAME_PATTERNS.keys()))
def test_flag_helper_per_topic_negative_match(topic):
    """A neutral filename should not flip the flag to False."""
    # "Misc.txt" / "Generic.txt" intentionally carries no topic keywords.
    # Pick the more-neutral name when the layer's regex is broad.
    evidence = {"input/docs/Misc.txt": []}
    assert _flag_no_X_in_input([], evidence, topic) is True, (
        f"Topic '{topic}' regex spuriously matched neutral filename "
        f"'input/docs/Misc.txt' — flag should be True"
    )

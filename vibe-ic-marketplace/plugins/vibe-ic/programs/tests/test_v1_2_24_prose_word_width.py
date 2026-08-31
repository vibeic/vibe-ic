"""CVDP §3.9 triage round-2: a spelled-out bit count is a STATED width.

`_prose_width` resolved `8-bit` (digits) but not `one-bit` (word), so a port whose
width is NARRATED — `- `hour`: Represents a one-bit signal …` — was mislabeled
SPEC_ABSENT. Spelled-out small numbers (one/single/two/…) are now recognised, a
GENERAL design-doc form that also serves RTLLM/VerilogEval/Phase-1 prose.

COMPLETE 230 -> 231 (digital_stopwatch_0001). §4.05 NO-LEAK: the word must be
immediately bound to `bit(s)` and tied to the named port; "one hour has passed"
or a bare "single" never yields a width.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import record_prompt_context_bridge as B  # noqa: E402
import cvdp_complete_extract as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/cvdp_open_v110/"
                  "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def test_word_bit_after_name():
    assert B._prose_width("- `hour`: Represents a one-bit signal.", "hour") == 1
    assert B._prose_width("`flag` is a single-bit status output.", "flag") == 1
    assert B._prose_width("`sel`: a two-bit selector.", "sel") == 2


def test_word_bit_before_name_not_supported():
    # bit->name word order is deliberately NOT credited (would risk forward-leak);
    # such a port stays a gap rather than risk a wrong width.
    assert B._prose_width("the eight-bit `data` bus", "data") is None


def test_digit_form_still_resolves():
    assert B._prose_width("the 16-bit `addr` bus", "addr") == 16
    assert B._prose_width("`q` is a 4-bit register", "q") == 4


def test_no_leak_word_not_bound_to_bit():
    # "one hour" / "single cycle" carry no width — must stay None
    assert B._prose_width("`hour`: high when one hour has passed.", "hour") is None
    assert B._prose_width("`done`: pulses for a single cycle.", "done") is None
    # a number-word with no port tie nearby on the line
    assert B._prose_width("Unrelated: a four-bit code.\n`other` is described.",
                          "other") is None


def test_dataset_digital_stopwatch_complete():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DS.read_text().splitlines()}
    r = recs.get("cvdp_copilot_digital_stopwatch_0001")
    if r is None:
        pytest.skip("record absent")
    spec = C.extract(r)
    assert spec["completeness"] == "COMPLETE"
    w = {p["name"]: p["width"] for p in spec["interface"]}
    assert w["hour"] == 1 and w["seconds"] == 6 and w["minutes"] == 6


def test_dataset_floor_231():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = [json.loads(l) for l in _DS.read_text().splitlines()]
    comp = sum(1 for r in recs if C.extract(r)["completeness"] == "COMPLETE")
    assert comp >= 226, f"COMPLETE regressed below 231->226: {comp}"

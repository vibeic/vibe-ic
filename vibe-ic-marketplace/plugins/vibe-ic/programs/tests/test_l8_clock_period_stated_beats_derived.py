#!/usr/bin/env python3
"""A row that states the period must not be recorded at the frequency's precision.

Spec rows routinely write one clock fact twice, at two precisions::

    | Target clock period | 25.9 ns (~38.6 MHz) |

The doc-prose harvester matched only the FREQUENCY literal, so the period L8
recorded was ``1000 / 38.6 = 25.906736 ns`` — a number the design never wrote,
derived from the rounded, explicitly-approximate half of the row while the
exact half sat two words to its left. `clock_mhz` mirrors the primary domain,
`sdc_gen` reads `clock_mhz` first, and `l8_sta_clock_period_design_owned_check`
then reports the derived number as "design-owned".

These tests are about the PRODUCER and assert only observable document fields,
so any correct fix satisfies them.

The reverse controls matter as much as the forward one: a row that states only
a frequency, a row whose time literal is a DIFFERENT fact (a setup time), and a
frequency RANGE row must all come out byte-identical to what they were before.
Every literal here (7.4 ns / 135 MHz, 12.8 ns / 78.1 MHz, 40 ns / 25 MHz) is
synthetic and unlike any design in the corpus, so a fix that hardcodes a number
cannot pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P1     # noqa: E402


def _project(tmp_path: Path, clock_port: str = "clk") -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"pin_table": [{"name": clock_port, "mode": "input"}]}),
        encoding="utf-8")
    return proj


def _emit(tmp_path: Path, doc_text: str) -> dict:
    """Run the producer AND the two post-emit hooks that finish the record.

    `gen_l8_timing_waveform` writes the domain; `_post_emit_typed_clock_domains`
    is what fills `period_ns`, and `_v1_6_295_post_emit_l8_clock_mhz_back_fill`
    is what fills the `clock_mhz` scalar `sdc_gen` reads. All three are the
    producer's own pipeline stages, in the order the runner calls them — a test
    that stopped after the first would be measuring a half-written document.
    """
    proj = _project(tmp_path)
    P1.gen_l8_timing_waveform(proj, {"product_overview.md": doc_text})
    P1._post_emit_typed_clock_domains(proj)
    P1._v1_6_295_post_emit_l8_clock_mhz_back_fill(proj)
    return json.loads((proj / "phase1" / "generated_docs"
                       / "L8_RTL_CONSTANTS.json").read_text())


def _primary(doc: dict) -> dict:
    domains = doc.get("clock_domains") or []
    assert domains, "the emitter produced no clock_domains[] at all"
    for d in domains:
        if isinstance(d, dict) and d.get("role") in ("primary", "master"):
            return d
    return domains[0]


# --- the row states BOTH: the period is stated, the frequency is rounded ----
_ROUNDED_RESTATEMENT_DOC = """\
# Product metadata

## Tapeout targets

| Field | Value |
|---|---|
| Target clock period | 7.4 ns (~135 MHz) |

The core runs from a single external clock input.
"""


def test_stated_period_is_recorded_not_the_one_derived_from_the_frequency(
        tmp_path):
    """7.4 ns is written on the row; 1000/135 = 7.407407 ns is not."""
    doc = _emit(tmp_path, _ROUNDED_RESTATEMENT_DOC)
    primary = _primary(doc)
    assert primary.get("period_ns") == pytest.approx(7.4, abs=1e-9), (
        f"the row states 7.4 ns and L8 recorded "
        f"period_ns={primary.get('period_ns')!r} — the period was taken from "
        f"the rounded frequency beside it instead of from the row's own "
        f"stated value")


def test_the_frequency_the_document_stated_is_kept_not_deleted(tmp_path):
    """Reconciliation must not be silent deletion — 135 MHz is still IN the doc."""
    doc = _emit(tmp_path, _ROUNDED_RESTATEMENT_DOC)
    blob = json.dumps(doc)
    assert "135" in blob, (
        "the document's own 135 MHz literal disappeared; a value the input "
        "stated must be kept as a mention even when it does not decide")


def test_the_clock_record_is_internally_consistent(tmp_path):
    """freq_mhz and period_ns must describe the SAME clock, whichever wins."""
    doc = _emit(tmp_path, _ROUNDED_RESTATEMENT_DOC)
    primary = _primary(doc)
    period = primary.get("period_ns")
    freq = primary.get("freq_mhz")
    assert period and freq, f"incomplete clock record: {primary!r}"
    assert 1000.0 / float(freq) == pytest.approx(float(period), rel=1e-6), (
        f"freq_mhz={freq} and period_ns={period} disagree — every consumer "
        f"picks one of the two keys, so a record that carries both must not "
        f"carry two different clocks")


def test_the_scalar_the_sdc_generator_reads_follows_the_stated_period(
        tmp_path):
    """`sdc_gen` takes L8.clock_mhz first; it must be the stated clock."""
    doc = _emit(tmp_path, _ROUNDED_RESTATEMENT_DOC)
    clock_mhz = doc.get("clock_mhz")
    assert clock_mhz is not None, "L8 recorded no clock_mhz scalar"
    assert 1000.0 / float(clock_mhz) == pytest.approx(7.4, rel=1e-9), (
        f"clock_mhz={clock_mhz} implies a period of "
        f"{1000.0 / float(clock_mhz):.6f} ns; the row states 7.4 ns, so the "
        f"SDC this run writes would not be the design's own constraint")


# --- reverse controls: these must hold BEFORE and AFTER the fix ------------
_FREQUENCY_ONLY_DOC = """\
# Product metadata

| Field | Value |
|---|---|
| Operating frequency | 78.1 MHz |

The core runs from a single external clock input.
"""


def test_a_row_with_no_stated_period_still_derives_one(tmp_path):
    """Nothing to adopt — the derived period is the only fact there is."""
    doc = _emit(tmp_path, _FREQUENCY_ONLY_DOC)
    primary = _primary(doc)
    assert primary.get("freq_mhz") == pytest.approx(78.1, rel=1e-9)
    assert primary.get("period_ns") == pytest.approx(
        1000.0 / 78.1, rel=1e-6), (
        "a row that states only a frequency must keep deriving its period "
        "from that frequency")


_UNRELATED_TIME_LITERAL_DOC = """\
# Product metadata

| Field | Value |
|---|---|
| Operating frequency | 78.1 MHz, with 4 ns of input setup required |

The core runs from a single external clock input.
"""


def test_a_time_literal_that_is_a_different_fact_is_not_taken_as_the_period(
        tmp_path):
    """4 ns is a setup time, not 1/78.1 MHz. It must not become the period."""
    doc = _emit(tmp_path, _UNRELATED_TIME_LITERAL_DOC)
    primary = _primary(doc)
    assert primary.get("period_ns") == pytest.approx(
        1000.0 / 78.1, rel=1e-6), (
        f"period_ns={primary.get('period_ns')!r} — a time literal on the row "
        f"that is nowhere near 1/f is a different quantity and must never be "
        f"adopted as the clock period")


_RANGE_DOC = """\
# Product metadata

| Field | Value |
|---|---|
| Clock frequency range | 20 - 25 MHz, 40 ns worst-case period |

The core runs from a single external clock input.
"""


def test_a_frequency_range_row_is_left_alone(tmp_path):
    """A range is not one clock written twice; the envelope must survive."""
    doc = _emit(tmp_path, _RANGE_DOC)
    primary = _primary(doc)
    assert primary.get("freq_low_mhz") == pytest.approx(20.0, rel=1e-9), (
        f"the low end of the stated range moved to "
        f"{primary.get('freq_low_mhz')!r}")
    assert primary.get("freq_high_mhz") == pytest.approx(25.0, rel=1e-9), (
        f"the high end of the stated range moved to "
        f"{primary.get('freq_high_mhz')!r}")


_EXACT_RESTATEMENT_DOC = """\
# Product metadata

| Field | Value |
|---|---|
| Target clock period | 40 ns (25 MHz) |

The core runs from a single external clock input.
"""


def test_an_exact_restatement_changes_nothing(tmp_path):
    """When the two halves agree exactly there is nothing to correct."""
    doc = _emit(tmp_path, _EXACT_RESTATEMENT_DOC)
    primary = _primary(doc)
    assert primary.get("freq_mhz") == pytest.approx(25.0, rel=1e-9)
    assert primary.get("period_ns") == pytest.approx(40.0, rel=1e-9)

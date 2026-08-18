#!/usr/bin/env python3
"""Tests for sata_timing_extractor.py — SATA-spec timing-literal picker.

Pins the real extraction logic for L8.timing_constants:
  * SATA line rates (1.5 / 3.0 / 6.0 Gbps) and litex-litesata system
    clocks (37.5 / 75 / 150 MHz) — both single-value and the real
    LiteSATA slash-tuple form "1.5/3.0/6.0GBps ... 37.5/75/150MHz".
  * Confidence floor: fewer than 2 distinct SATA literals -> [] (a lone
    "6.0 Gbps" anywhere is not enough to claim SATA evidence).
  * Garbage / empty / None input -> [].
"""
from __future__ import annotations

# programs/ is on sys.path via programs/tests/conftest.py.
import sata_timing_extractor as mod  # noqa: E402

_extract = mod.extract_sata_timing_constants_from_readme


# ----------------------------------------------------------------------
# PASS — the real LiteSATA slash-tuple form yields all six constants.
# ----------------------------------------------------------------------
def test_slash_tuple_form_all_six():
    txt = ("LiteSATA supports 1.5/3.0/6.0GBps speeds "
           "(respectively 37.5/75/150MHz system clk)")
    hits = _extract(txt)
    names = {h["name"] for h in hits}
    assert names == {
        "sata_gen1_line_rate", "sata_gen2_line_rate", "sata_gen3_line_rate",
        "sata_sys_clk_37p5_mhz", "sata_sys_clk_75_mhz", "sata_sys_clk_150_mhz",
    }
    # values + units land in the L8 schema shape.
    by_name = {h["name"]: h for h in hits}
    assert by_name["sata_gen3_line_rate"]["value"] == 6.0
    assert by_name["sata_gen3_line_rate"]["unit"] == "Gbps"
    assert by_name["sata_sys_clk_150_mhz"]["value"] == 150.0
    assert by_name["sata_sys_clk_150_mhz"]["unit"] == "MHz"
    assert all("evidence_line" in h for h in hits)


def test_single_value_form_two_hits():
    # Two distinct single-value literals clear the >=2 confidence floor.
    txt = "Gen3 link runs at 6.0 Gbps with a 150 MHz system clock."
    hits = _extract(txt)
    names = {h["name"] for h in hits}
    assert names == {"sata_gen3_line_rate", "sata_sys_clk_150_mhz"}


def test_no_dedup_across_passes():
    # The slash-tuple and single-value passes must not double-count.
    txt = ("Speeds 1.5/3.0/6.0GBps. Also note Gen3 is 6.0 Gbps. "
           "Clocks 37.5/75/150MHz.")
    hits = _extract(txt)
    names = [h["name"] for h in hits]
    assert len(names) == len(set(names))  # no duplicate names


# ----------------------------------------------------------------------
# FAIL / floor — fewer than 2 distinct literals is not SATA evidence.
# ----------------------------------------------------------------------
def test_single_literal_below_floor():
    assert _extract("The bus runs at 6.0 Gbps only.") == []


def test_non_sata_speed_ignored():
    # 5.0 Gbps / 100 MHz are not SATA-canonical literals.
    assert _extract("Runs at 5.0 Gbps and a 100 MHz clock.") == []


# ----------------------------------------------------------------------
# Edge — empty / None / no-signal input.
# ----------------------------------------------------------------------
def test_empty_string():
    assert _extract("") == []


def test_none_input():
    assert _extract(None) == []


def test_unrelated_prose():
    assert _extract("This README describes a generic SoC with a UART.") == []

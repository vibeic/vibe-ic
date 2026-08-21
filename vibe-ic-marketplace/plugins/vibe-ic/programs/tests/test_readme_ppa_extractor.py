#!/usr/bin/env python3
"""Tests for readme_ppa_extractor.py — PPA implementation-results picker
(#36 Bug 10).

Pins the REAL behavior of extract_implementation_results_from_readme and
its parse helpers across the three presentation forms the picker handles:
  * markdown PPA table (header metric tokens + data rows),
  * inline key-value lines under a platform heading,
  * number-first bullets (`- 2624 ALMs`), ASIC area lines, sub-blocks.

Also pins the value-normalisation (GHz→MHz, SI prefix scaling, int vs
float) and the deny-list / floor guards that prevent garbage prose from
being mis-classified as PPA.

Chip-AGNOSTIC: industry-standard FPGA/ASIC metric vocabulary only.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "readme_ppa_extractor.py"

_spec = importlib.util.spec_from_file_location("readme_ppa_extractor", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# PASS — markdown table form
# ----------------------------------------------------------------------
def test_pass_markdown_table():
    readme = (
        "| Platform   | LUTs | Regs | Fmax    |\n"
        "|------------|------|------|---------|\n"
        "| Cyclone V  | 1234 | 567  | 250 MHz |\n"
        "| Stratix V  | 2345 | 678  | 300 MHz |\n"
    )
    out = mod.extract_implementation_results_from_readme(readme)
    assert len(out) == 2
    by_plat = {d["platform"]: d for d in out}
    cyc = by_plat["Cyclone V"]
    assert cyc["source_form"] == "markdown_table"
    assert cyc["metrics"]["luts"] == 1234
    assert cyc["metrics"]["regs"] == 567
    assert cyc["metrics"]["fmax_mhz"] == 250.0
    assert by_plat["Stratix V"]["metrics"]["fmax_mhz"] == 300.0


# ----------------------------------------------------------------------
# PASS — inline key-value under a heading
# ----------------------------------------------------------------------
def test_pass_inline_kv_under_heading():
    readme = (
        "## Cyclone V\n"
        "LUTs: 1538\n"
        "Regs: 432\n"
        "Fmax: 51 MHz\n"
    )
    out = mod.extract_implementation_results_from_readme(readme)
    assert len(out) == 1
    e = out[0]
    assert e["platform"] == "Cyclone V"
    assert e["source_form"] == "inline_kv"
    assert e["metrics"]["luts"] == 1538
    assert e["metrics"]["regs"] == 432
    assert e["metrics"]["fmax_mhz"] == 51.0


# ----------------------------------------------------------------------
# PASS — number-first bullet form (the dominant aes/sha README form)
# ----------------------------------------------------------------------
def test_pass_number_first_bullets():
    readme = (
        "## TSMC 180nm\n"
        "- 2624 ALMs\n"
        "- 8 kCells\n"
        "- 96 MHz\n"
    )
    out = mod.extract_implementation_results_from_readme(readme)
    assert len(out) == 1
    m = out[0]["metrics"]
    assert m["alms"] == 2624
    assert m["fmax_mhz"] == 96.0
    # 8 kCells stays in kCells units (value preserved).
    assert m["kcells"] == 8


# ----------------------------------------------------------------------
# helper-level pins — value normalisation
# ----------------------------------------------------------------------
def test_ghz_normalised_to_mhz():
    nf = mod._parse_number_first_line("- 1 GHz")
    assert nf["metric"] == "fmax_mhz"
    assert nf["value"] == 1000.0  # 1 GHz → 1000 MHz


def test_inline_int_vs_float():
    hits = mod._parse_inline_line("LUTs: 1500")
    assert hits[0]["metric"] == "luts"
    assert hits[0]["value"] == 1500
    assert isinstance(hits[0]["value"], int)


def test_area_pair_form():
    """`- Aera: 520 x 520 um` (sic typo) → die_size_um + derived area."""
    ar = mod._parse_area_line("- Aera: 520 x 520 um")
    assert ar is not None
    assert ar["die_size_um"] == "520x520"
    assert ar["area_um2"] == 520 * 520


def test_area_scalar_mm2_to_um2():
    ar = mod._parse_area_line("- Die size: 0.142 mm2")
    assert ar is not None
    # 0.142 mm2 = 0.142 * 1e6 um2 = 142000 um2.
    assert ar["area_um2"] == 142000


def test_sub_block_vendor_deny():
    """A vendor word on the left of a colon is NOT a submodule (deny)."""
    assert mod._parse_sub_block_line("- cyclone: 1234 LUTs") is None
    # but a real submodule name is accepted.
    sb = mod._parse_sub_block_line("- aes_sbox: 160 ALUTs")
    assert sb is not None
    assert sb["name"] == "aes_sbox"
    assert sb["canonical"] == "alut_count"
    assert sb["value"] == 160


# ----------------------------------------------------------------------
# FAIL/guard — no PPA evidence
# ----------------------------------------------------------------------
def test_none_and_empty_return_empty():
    assert mod.extract_implementation_results_from_readme(None) == []
    assert mod.extract_implementation_results_from_readme("") == []


def test_plain_prose_yields_nothing():
    readme = (
        "# My Project\n"
        "This is an open-source IP core. It does useful things.\n"
        "See the docs for usage. No numbers here.\n"
    )
    assert mod.extract_implementation_results_from_readme(readme) == []


def test_table_without_metric_header_skipped():
    """A markdown table whose header has no PPA metric token is not a
    PPA table — it must be skipped, not mis-parsed."""
    readme = (
        "| Name | Description |\n"
        "|------|-------------|\n"
        "| foo  | does a thing |\n"
    )
    assert mod.extract_implementation_results_from_readme(readme) == []

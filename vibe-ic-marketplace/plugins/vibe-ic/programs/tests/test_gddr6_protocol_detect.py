"""Regression tests for the GDDR6 (JEDEC JESD250) graphics-DRAM detector.

GDDR6 joins the JEDEC memory family (DDR3/DDR4/DDR5, LPDDR5, HBM3). It shares
the broad DRAM vocabulary (SDRAM, bank group, mode register, ACTIVATE/PRECHARGE,
refresh) with all of them and shares the WCK write clock with LPDDR5, so a NAME
or WCK token alone is never sufficient. ``is_gddr6`` keys on the GDDR6-ONLY
structural signature (JESD250 / GDDR6 name / graphics-SGRAM identity PLUS the
EDC read+write CRC pins / CABI / two-independent-16-bit-channel / WCK2CK) and
carries a sibling-primary MUTEX that defers to DDR3/4/5, LPDDR5, and HBM3.

These tests pin:
  * the WCK-vs-LPDDR5 disambiguation (WCK alone must NOT fire GDDR6);
  * the DDR4/DDR5 no-misfire (those docs carry "write CRC" / "two independent"
    and mention "graphics" in passing, but lack the GDDR6 identity);
  * the HBM3 / DDR3 sibling MUTEX;
  * fixture-level: is_gddr6 fires ONLY on the gddr6 benchmark.

The v0.1.89 KEY LESSON applies: GDDR6's synth force-overwrites the LPDDR5/HBM3
synths that legitimately fire on a GDDR6 spec's positioning section, so a
detector that over-fires on a foreign doc would be MASKED by parity. These unit
tests guard the detector directly.
"""
import os
from pathlib import Path

import pytest

from gddr6_protocol_synth import is_gddr6
from _plugin_tree import repo_path_or_missing

# flow #486: benchmark_phase1/ is a repo-root-only private corpus absent on
# the flattened cache; resolve defensively so the existing skipif guards fire.
BP = repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")


# --------------------------------------------------------------------------- unit
def test_fires_on_canonical_gddr6():
    blob = (
        "GDDR6 SGRAM, JEDEC JESD250. Graphics Double Data Rate type 6. Two "
        "independent 16-bit channels. Quarter-rate CK plus a higher-rate Write "
        "Clock WCK with WCK2CK alignment training. 16n prefetch, BL16, NRZ "
        "16-18 Gb/s. Data Bus Inversion (DBI) and Command/Address Bus Inversion "
        "(CABI). 8-bit read CRC and write CRC per byte lane on the EDC pins with "
        "a programmable EDC hold pattern. Bank groups, MR0..MR15."
    )
    assert is_gddr6(blob) is True


def test_fires_on_graphics_sgram_without_explicit_name():
    # Identity via the tight graphics-SGRAM phrase (no literal "GDDR6"/"JESD250").
    blob = (
        "Graphics SGRAM device with two independent 16-bit channels. A separate "
        "Write Clock (WCK) at twice the CK data rate, aligned by WCK2CK "
        "training. Read CRC and write CRC carried per byte lane on the EDC pins. "
        "Command/Address Bus Inversion (CABI). 16n prefetch, BL16."
    )
    assert is_gddr6(blob) is True


def test_wck_alone_does_not_fire():
    # WCK is shared with LPDDR5 — WCK without the GDDR6 identity must NOT fire.
    blob = (
        "Memory device with a Write Clock WCK at twice the CK data rate, bank "
        "groups, mode registers, ACTIVATE/PRECHARGE, 16n prefetch, burst length "
        "16. No graphics context, no EDC CRC pins."
    )
    assert is_gddr6(blob) is False


def test_lpddr5_primary_defers():
    blob = (
        "LPDDR5 SDRAM, JEDEC JESD209-5. Low-power mobile DRAM. WCK write clock, "
        "bank groups, mode registers, 16n prefetch, ACTIVATE/PRECHARGE, "
        "low-power states. Mobile memory with no error-detection CRC pins."
    )
    assert is_gddr6(blob) is False


def test_hbm3_primary_defers():
    blob = (
        "HBM3, JEDEC JESD238. High Bandwidth Memory, 1024-bit wide interface, "
        "TSV-stacked DRAM on a silicon interposer. Pseudo channel mode. Bank "
        "groups, mode registers, ACTIVATE/PRECHARGE."
    )
    assert is_gddr6(blob) is False


def test_ddr3_primary_defers():
    blob = (
        "DDR3 SDRAM, JEDEC JESD79-3. DIMM module memory, multi-rank shared bus, "
        "CK_t/CK_c command clock (no WCK), bank groups, mode registers, 8n "
        "prefetch, burst length 8, ACTIVATE/PRECHARGE, tRCD, tRP."
    )
    assert is_gddr6(blob) is False


def test_ddr4_primary_defers():
    # DDR4 carries "write CRC" (write-CRC / CA-parity feature) but is a DIMM
    # JESD79-4 device with no GDDR6 identity.
    blob = (
        "DDR4 SDRAM, JEDEC JESD79-4. RDIMM/LRDIMM module memory. Bank groups, "
        "mode registers MR0..MR7, ACTIVATE/PRECHARGE, tRCD, tRP, 8n prefetch, "
        "burst length 8, CK_t/CK_c. Write CRC and CA parity. DIMM."
    )
    assert is_gddr6(blob) is False


def test_ddr5_primary_defers():
    # DDR5 has "two independent sub-channels" + "write CRC" + 16n/BL16 — the
    # trickiest sibling — but is a JESD79-5 DIMM with no GDDR6 identity.
    blob = (
        "DDR5 SDRAM, JEDEC JESD79-5. DIMM module with two independent 32-bit "
        "sub-channels. Bank groups, mode registers, decision feedback "
        "equalization, on-die ECC, 16n prefetch, burst length 16, write CRC, "
        "ACTIVATE/PRECHARGE. RDIMM/UDIMM."
    )
    assert is_gddr6(blob) is False


def test_empty_blob():
    assert is_gddr6("") is False
    assert is_gddr6(None) is False


# ------------------------------------------------------------------------ fixture
def _blob_for(name: str) -> str:
    d = BP / name
    blob = ""
    idd = d / "input" / "docs"
    if idd.is_dir():
        for f in idd.iterdir():
            if f.suffix.lower() in (".txt", ".md", ".json"):
                try:
                    blob += "\n" + f.read_text(errors="ignore")
                except Exception:
                    pass
    for n in ("L1_DATASHEET.json", "L2_FRS.json"):
        p = d / "phase1" / "generated_docs" / n
        if p.is_file():
            blob += p.read_text()
    return blob


@pytest.mark.skipif(not (BP / "gddr6").is_dir(), reason="gddr6 benchmark absent")
def test_fixture_fires_on_gddr6_benchmark():
    assert is_gddr6(_blob_for("gddr6")) is True


@pytest.mark.parametrize("sibling", ["ddr", "ddr4", "ddr5", "lpddr5", "hbm3"])
def test_fixture_no_misfire_on_memory_siblings(sibling):
    d = BP / sibling
    if not d.is_dir():
        pytest.skip(f"{sibling} benchmark absent")
    assert is_gddr6(_blob_for(sibling)) is False


def test_fixture_no_misfire_across_all_benchmarks():
    if not BP.is_dir():
        pytest.skip("benchmark_phase1 absent")
    for d in sorted(BP.iterdir()):
        if not d.is_dir() or d.name == "gddr6":
            continue
        assert is_gddr6(_blob_for(d.name)) is False, (
            f"is_gddr6 mis-fired on benchmark '{d.name}'")

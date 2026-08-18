"""Regression tests for the DDR4 SDRAM (JEDEC JESD79-4) detector.

DDR4 joins the JEDEC memory family (DDR3, DDR5, LPDDR5, HBM3). It shares the
broad DRAM vocabulary (SDRAM, bank group, mode register, ACTIVATE/PRECHARGE,
refresh) with all of them, so a NAME token alone is never sufficient.
``is_ddr4`` keys on the DDR4-ONLY structural signature (JESD79-4 + 1.2 V +
bank groups + the DDR4-new features: gear-down / DBI / write CRC / CA parity /
on-die VrefDQ / ACT_n command flag) and carries a sibling-primary MUTEX that
defers to DDR3, DDR5, LPDDR5, and HBM3.

The trickiest sibling is DDR5: a DDR4 spec's positioning section references
DDR5 (sub-channels, equalization) and a DDR5 spec references DDR4 / 1.2 V, so
the MUTEX requires a STRONG, multi-token DDR5 structural cluster to defer, and
the DDR4-primary path requires DDR4's own spec id + the DDR4 cluster.

The v0.1.89 KEY LESSON applies: the DDR4 synth force-overwrites the DDR3 synth
that legitimately fires first on a DDR4 spec (DDR4 extends DDR3's command
model), so a detector that over-fired on a foreign memory doc would be MASKED
by parity. These unit tests guard the detector directly.
"""
from pathlib import Path

import pytest

from ddr4_protocol_synth import is_ddr4
from _plugin_tree import repo_path_or_missing

# flow #486: benchmark_phase1/ is a repo-root-only private corpus; on the
# flattened install cache it is absent, so this resolves to a non-existent
# path and the existing `skipif(not (BP/...).is_dir())` guards fire (named
# skip), instead of an IndexError from a hard-coded parents[5].
BP = repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")


# --------------------------------------------------------------------------- unit
def test_fires_on_canonical_ddr4():
    blob = (
        "DDR4 SDRAM Standard, JEDEC Standard No. 79-4 (JESD79-4). Single 64-bit "
        "(72-bit ECC) channel at VDD = VDDQ = 1.2 V, VPP 2.5 V. Bank Groups "
        "(BG0/BG1; 4 bank groups x 4 banks = 16 banks). Gear-down (1/2-rate) "
        "command/address mode. Data Bus Inversion on DM_n/DBI_n. Internal "
        "VrefDQ generation with VrefDQ training. Write CRC on the data bus with "
        "ALERT_n. Command/Address parity (PAR). ACT_n command flag; RAS_n/A16, "
        "CAS_n/A15, WE_n/A14 multiplexed. BL8/BC4. Mode registers MR0..MR6."
    )
    assert is_ddr4(blob) is True


def test_fires_without_explicit_jesd_id_via_strong_cluster():
    # No literal JESD79-4 / DDR4 string: identity via the DDR4 STRUCTURAL
    # cluster (bank groups + 1.2 V + >=2 DDR4-only features).
    blob = (
        "Fourth-generation synchronous DRAM at 1.2 V. Bank groups with short "
        "and long bank-group timings (tCCD_S/tCCD_L). Gear-down 1/2-rate "
        "command/address. Data Bus Inversion on DM_n/DBI_n. Write CRC on the "
        "data bus. Command/address parity with ALERT_n. ACT_n activate command "
        "flag. ACTIVATE/PRECHARGE, tRCD, tRP."
    )
    assert is_ddr4(blob) is True


def test_name_token_alone_does_not_fire():
    # A foreign doc with an injected "DDR4" name token but no DDR4 structural
    # feature must NOT fire (general-not-keyword).
    blob = (
        "This bus controller interfaces to a DDR4 memory subsystem via an "
        "external PHY. The controller itself is a simple AXI bridge with no "
        "memory-protocol features."
    )
    assert is_ddr4(blob) is False


def test_ddr3_primary_defers():
    # DDR3 (1.5 V, no bank groups, external VREFDQ, no write CRC / CA parity /
    # gear-down / DBI).
    blob = (
        "DDR3 SDRAM, JEDEC JESD79-3. DIMM module memory at 1.5 V. 8 banks via "
        "BA0..BA2 (no bank groups). External VREFDQ. CK_t/CK_c command clock, "
        "8n prefetch, burst length 8, ACTIVATE/PRECHARGE, tRCD, tRP. No write "
        "CRC, no CA parity, no gear-down."
    )
    assert is_ddr4(blob) is False


def test_ddr5_primary_defers():
    # DDR5 references DDR4/1.2 V and shares bank-groups/gear-down/DBI, but its
    # OWN device has the strong DDR5 cluster (two 32-bit sub-channels + DFE +
    # on-die ECC + DIMM PMIC + same-bank refresh).
    blob = (
        "DDR5 SDRAM, JEDEC JESD79-5. The DIMM is split into two independent "
        "32-bit (40-bit ECC) sub-channels. The DQ receiver uses Decision "
        "Feedback Equalization (DFE). On-die ECC. Each DIMM carries a PMIC "
        "(Power Management IC) and SPD hub at 1.1 V. Same-bank refresh. Bank "
        "groups, gear-down, Data Bus Inversion. DDR5 succeeds DDR4 (JESD79-4) "
        "at 1.2 V. ACTIVATE/PRECHARGE."
    )
    assert is_ddr4(blob) is False


def test_lpddr5_primary_defers():
    blob = (
        "LPDDR5 SDRAM, JEDEC JESD209-5. Low-power mobile DRAM. WCK write clock "
        "separate from CK. Bank groups, mode registers, 16n prefetch, "
        "ACTIVATE/PRECHARGE, low-power states. 1.05 V."
    )
    assert is_ddr4(blob) is False


def test_hbm3_primary_defers():
    blob = (
        "HBM3, JEDEC JESD238. High Bandwidth Memory, 1024-bit wide interface, "
        "TSV-stacked DRAM on a silicon interposer. Pseudo channel mode. Bank "
        "groups, mode registers, ACTIVATE/PRECHARGE."
    )
    assert is_ddr4(blob) is False


def test_ddr4_referencing_siblings_still_fires():
    # A real DDR4 spec names DDR3 / DDR5 / LPDDR5 / HBM3 in comparison prose;
    # it must still fire (the strong sibling clusters are NOT met by a one-line
    # mention).
    blob = (
        "DDR4 SDRAM Standard JESD79-4. Single 64-bit channel at 1.2 V. Bank "
        "groups, gear-down, Data Bus Inversion, write CRC, CA parity, on-die "
        "VrefDQ training. DDR4 succeeds DDR3 (1.5 V) and precedes DDR5 "
        "(JESD79-5), which splits into sub-channels. Unlike LPDDR5 there is no "
        "WCK; unlike HBM3 there are no through-silicon vias."
    )
    assert is_ddr4(blob) is True


def test_empty_blob():
    assert is_ddr4("") is False
    assert is_ddr4(None) is False


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


@pytest.mark.skipif(not (BP / "ddr4").is_dir(), reason="ddr4 benchmark absent")
def test_fixture_fires_on_ddr4_benchmark():
    assert is_ddr4(_blob_for("ddr4")) is True


@pytest.mark.parametrize("sibling", ["ddr", "ddr5", "lpddr5", "hbm3"])
def test_fixture_no_misfire_on_memory_siblings(sibling):
    d = BP / sibling
    if not d.is_dir():
        pytest.skip(f"{sibling} benchmark absent")
    assert is_ddr4(_blob_for(sibling)) is False


def test_fixture_no_misfire_across_all_benchmarks():
    if not BP.is_dir():
        pytest.skip("benchmark_phase1 absent")
    for d in sorted(BP.iterdir()):
        if not d.is_dir() or d.name == "ddr4":
            continue
        assert is_ddr4(_blob_for(d.name)) is False, (
            f"is_ddr4 mis-fired on benchmark '{d.name}'")

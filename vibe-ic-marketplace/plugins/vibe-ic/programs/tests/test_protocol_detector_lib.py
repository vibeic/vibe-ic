"""Pins the canonical protocol-detector helpers (v0.1.95).

These lock the codified Bucket-A detector-authoring patterns so a future edit can't
silently reintroduce the bugs the Tier-D/E/F/G sweeps hit by hand (substring
false-matches, name-token-only fires, family-member confusion, allowlist drift).
"""
from protocol_detector_lib import (
    word_boundary,
    any_word_boundary,
    foreign_exclusive_defer,
    subject_dominates,
    DERIVED_SIBLING_CROSS_FIRES,
)


# ------------------------------------------------------------- word_boundary
def test_word_boundary_rejects_substring_false_matches():
    # the exact bugs HyperBus/others hit
    assert word_boundary("ddr", "command-address bus") is False
    assert word_boundary("8-bit", "a 48-bit command-address") is False
    assert word_boundary("VC", "the device") is False
    # and matches the standalone word
    assert word_boundary("ddr", "this is a DDR-like note") is False  # case-sensitive
    assert word_boundary("DDR", "a DDR3 SDRAM") is False             # DDR3 != DDR boundary
    assert word_boundary("DDR3", "a DDR3 SDRAM") is True
    assert word_boundary("VC", "Virtual Channel VC is set") is True


def test_word_boundary_empty_safe():
    assert word_boundary("", "x") is False
    assert word_boundary("x", "") is False
    assert any_word_boundary(["FS", "FE"], "FE marks frame end") is True
    assert any_word_boundary(["FS", "FE"], "nothing here") is False


# --------------------------------------------------- foreign_exclusive_defer
def test_foreign_exclusive_defer_conjunction_or_groups():
    # SAS-detector deferring to a Fibre-Channel-primary doc
    fc = "Fibre Channel fabric: N_Port, FLOGI, FC-2 frame header R_CTL/D_ID/S_ID"
    assert foreign_exclusive_defer(fc, [("n_port", "flogi", "r_ctl")]) is True
    # a real SAS doc has none of those → no defer
    sas = "Serial Attached SCSI: SSP, STP, SMP, expander, SAS address, wide port"
    assert foreign_exclusive_defer(sas, [("n_port", "flogi", "r_ctl")]) is False
    # OR of groups: any fully-matching group triggers
    assert foreign_exclusive_defer(
        "uses SDCI with IODD", [("n_port", "flogi"), ("sdci", "iodd")]) is True
    # partial group (not all tokens) → no defer
    assert foreign_exclusive_defer("only n_port here", [("n_port", "flogi")]) is False


# -------------------------------------------------------- subject_dominates
def test_subject_dominates_basic():
    # DDR4 dominant, DDR5 only mentioned once in a comparison
    blob = ("DDR4 SDRAM. DDR4 bank groups. DDR4 gear-down. "
            "Unlike DDR5, DDR4 has a single channel.")
    assert subject_dominates(blob, ["ddr4"], [["ddr5"], ["lpddr5"]]) is True
    # the reverse must NOT dominate
    assert subject_dominates(blob, ["ddr5"], [["ddr4"]]) is False


def test_subject_dominates_substring_subtract():
    # "lpddr5" contains "ddr5": a DDR5-primary doc must still beat an LPDDR5 comparison.
    blob = ("DDR5 SDRAM JESD79-5. DDR5 DFE. DDR5 two sub-channels. DDR5 on-die ECC. "
            "Not to be confused with LPDDR5 / LPDDR5 mobile.")
    # without subtract, raw count("ddr5") includes the 2 lpddr5 hits — still dominant here,
    # but the subtract gives the TRUE ddr5-only net count vs the lpddr5 subject.
    assert subject_dominates(
        blob, ["ddr5"], [["lpddr5"]], subtract=[("lpddr5", "ddr5")]) is True


# ------------------------------------------------- derived-sibling allowlist
def test_derived_sibling_allowlist_is_canonical_and_contains_edp():
    assert ("displayport", "edp") in DERIVED_SIBLING_CROSS_FIRES
    # it is a set of (base, derived) string pairs
    for pair in DERIVED_SIBLING_CROSS_FIRES:
        assert isinstance(pair, tuple) and len(pair) == 2
        assert all(isinstance(s, str) for s in pair)

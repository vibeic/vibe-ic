#!/usr/bin/env python3
"""The declared-vs-used PDK audit must not contradict a PDK with its own library.

A PDK is distributed under a directory named for its NODE (`nangate45`) while
its library is named for its FAMILY (`NangateOpenCellLibrary`). `tokens()` does
not split CamelCase, so the library collapses to one 22-character token and
`shares_identity` fails both of its rules: the BOUNDARY test (the library does
not start with `nangate45` — the digits are not in the library name) and the
SUBSTANCE ratio (9/22 = 0.41 < MIN_IDENTITY_RATIO).

Measured across the five PDKs shipped in the EDA image, each against its OWN
real library filenames: 4 corroborate, `nangate45` alone is reported contradicted
by the libraries shipped at `/foss/pdks/nangate45/`.

BIDIRECTIONAL NEGATIVE CONTROL: the nangate tests FAIL pre-fix. Everything under
"the guards" passes BOTH ways and pins the blast radius — this gate's dangerous
direction is a FALSE PASS (declaring a process ran that did not), so the
adversarial cases below matter more than the positive one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import declared_pdk_is_the_pdk_used_check as g  # noqa: E402


NANGATE_LIBS = [
    "NangateOpenCellLibrary_typical.lib",
    "NangateOpenCellLibrary.lef",
    "NangateOpenCellLibrary.tech.lef",
]

# Every PDK shipped in vibeic-eda:0.2.58, with real filenames from the image.
SHIPPED = {
    "asap7": ["asap7sc7p5t_OA_RVT_TT_nldm_211120.lib",
              "asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib"],
    "gf180mcuD": ["gf180mcu_fd_ip_sram__sram256x8m8wm1__ff_n40C_1v98.lib",
                  "gf180mcu_fd_sc_mcu7t5v0.lef"],
    "ihp-sg13g2": ["sg13g2_io_dummy.lib", "sg13g2_io_fast_1p32V_3p6V_m40C.lib"],
    "sky130A": ["sky130_sram_1kbyte_1rw1r_32x256_8_TT_1p8V_25C.lib",
                "sky130_fd_sc_hd__tt_025C_1v80.lib"],
    "nangate45": NANGATE_LIBS,
}


# ------------------------------------------------------------- the defect

def test_nangate_is_corroborated_by_its_own_library():
    """FAILS PRE-FIX. The node-named PDK must match its family-named library."""
    assert g.shares_stem_identity({"nangate45"},
                                  "NangateOpenCellLibrary_typical.lib")


def test_no_shipped_pdk_is_contradicted_by_its_own_libraries():
    """FAILS PRE-FIX (nangate45). Every shipped PDK corroborates itself."""
    contradicted = {p: g.contradicting_named_pdks(p, libs)
                    for p, libs in SHIPPED.items()}
    assert all(not v for v in contradicted.values()), (
        f"a PDK was reported contradicted by its OWN libraries: "
        f"{ {k: v for k, v in contradicted.items() if v} }")


# ------------------------------------ the guards (must pass BOTH ways)

@pytest.mark.parametrize("declared,libs", [
    # a DIFFERENT process must still be caught — this gate's whole purpose
    ("nangate45", ["sky130_fd_sc_hd__tt_025C_1v80.lib"]),
    ("sky130A", NANGATE_LIBS),
    ("asap7", NANGATE_LIBS),
    ("gf180mcu", NANGATE_LIBS),
])
def test_a_different_process_is_still_contradicted(declared, libs):
    assert g.contradicting_named_pdks(declared, libs), (
        f"{declared!r} was NOT flagged against {libs} — a wrong-PDK run would "
        "pass, which is the failure this gate exists to prevent")


@pytest.mark.parametrize("declared,name", [
    # interior / generic CamelCase segments must never match (#709 hole)
    ("cell1", "NangateOpenCellLibrary.lef"),
    ("library1", "NangateOpenCellLibrary.lef"),
    ("open1", "NangateOpenCellLibrary.lef"),
    # a short stem must not carry identity on 3 characters
    ("sky130", "SkyfooBarBaz.lib"),
    ("scl180", "SclfooBarBaz.lib"),
    # stem must EQUAL a leading segment, not merely prefix it
    ("nangate45", "NangateenOpenCell.lib"),
    # no digits => not a <stem><node> token at all, rule does not fire
    ("nangate", "NangateOpenCellLibrary.lef"),
])
def test_stem_rule_does_not_over_match(declared, name):
    assert not g.shares_stem_identity({declared}, name)


def test_leading_segments_are_leading_only():
    """Only the LEADING segment of each identifier is admitted."""
    lead = g.leading_segments("NangateOpenCellLibrary.lef")
    assert "nangate" in lead
    for interior in ("open", "cell", "library"):
        assert interior not in lead, (
            f"{interior!r} is an INTERIOR segment — admitting it re-opens the "
            "#709 interior-fragment hole")


def test_underscore_separated_names_keep_every_leading_segment():
    lead = g.leading_segments("sky130_fd_sc_hd__tt_025C_1v80.lib")
    assert {"sky130", "fd", "sc", "hd"} <= lead

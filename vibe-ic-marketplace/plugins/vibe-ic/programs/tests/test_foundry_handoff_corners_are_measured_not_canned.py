"""BIDIRECTIONAL test: the ATE corner kit must state the corners the design was
SIGNED OFF AT, not a canned list wearing a PENDING_FOUNDRY_ prefix.

THE DEFECT
==========
`foundry_handoff_pack_gen` shipped these two lines in every
`corner_test_vectors.json` it ever wrote:

    "PENDING_FOUNDRY_voltage_corners": ["VDD_min", "VDD_nom", "VDD_max"],
    "PENDING_FOUNDRY_temperature_corners_celsius": [-40, 25, 85, 125],

Neither is pending on the foundry. Operating corners are a DESIGN decision,
Phase 1 captures them and this flow already runs multi-corner STA — so the
prefix was not marking an open item, it was hiding an answer the flow already
had. And the value behind the prefix was not empty, it was FABRICATED: a
plausible-looking list a foundry could test silicon against.

MEASURED, published corpus, 8 roots carrying a hand-off kit, reading the
liberty files the sign-off flow itself consumed:

    resolved                8 / 8       unparsed liberty names   0
    ic/sha256 (both runs)   1.40 / 1.80 / 1.95 V   -40 / 25 / 100 C
    ic/caravel_user_project 1.60 / 1.80 / 1.95 V   -40 / 25 / 100 C
    the other five          1.80 V                 25 C

Not one of them is `[-40, 25, 85, 125]`. Every kit in the corpus told a foundry
the design was characterised at 85 C and 125 C — points it was never
characterised at — and omitted the 100 C point it was.

THE FIX
=======
Read the corners off the liberty BASENAMES the flow's own artefacts name, the
same ground truth `_pdk_from_signoff_flow` already uses to name the PDK. When
the PDK's liberty names carry no operating point the answer is NOT_DETERMINED
and the size of the search is reported — never a default.

THE GRAMMAR IS MEASURED. Every liberty basename shipped in the pinned image
(sha256:66c33ff2…, 2026-08-20) was enumerated; the two delimiters in the regex
were each put there by a false positive found in that set, and both are pinned
below as tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import foundry_handoff_pack_gen as FH  # noqa: E402

# field (foundry-handoff hollow chip GDS) — the chip GDS in this fixture must
# carry GEOMETRY. A four-byte GDSII BOUNDARY record header (length 4, record
# type 0x08) is the smallest thing that makes
# `analog_a5_layout_check._gds_geometry_count` read 1 rather than 0. Without it
# this fixture models a HOLLOW die, which `foundry_handoff_pack_gen` now refuses
# to package and `foundry_handoff_package_check` now FAILs — so the fixture
# would stop standing for the real run it was written from.
_GDS_BOUNDARY_RECORD = b"\x00\x04\x08\x00"


# ── the grammar, against real shipped filenames ─────────────────────────────

def test_form_a_sky130_gf180_temperature_and_voltage():
    """`<proc>_<T>C_<V>` — the sky130 / gf180mcu spelling."""
    assert FH._corner_from_liberty_name(
        "sky130_fd_sc_hd__tt_025C_1v80.lib") == ([1.80], [25])
    assert FH._corner_from_liberty_name(
        "gf180mcu_fd_io__ff_n40C_5v50.lib") == ([5.50], [-40])
    assert FH._corner_from_liberty_name(
        "gf180mcu_fd_io__ss_125C_2v25.lib") == ([2.25], [125])


def test_form_b_ihp_swaps_the_order_and_spells_minus_with_m():
    """IHP puts the voltage first, writes the decimal point as `p`, appends a
    `V` unit, and spells the minus sign `m` rather than `n`. A grammar tuned to
    one vendor's spelling would silently return nothing here."""
    v, t = FH._corner_from_liberty_name("sg13g2_stdcell_typ_1p20V_25C.lib")
    assert (v, t) == ([1.20], [25])
    v, t = FH._corner_from_liberty_name(
        "sg13cmos5l_io_fast_1p32V_3p6V_m40C.lib")
    assert t == [-40]
    # A one-digit fraction is a real spelling (3p6 == 3.6 V), not a typo.
    assert v == [1.32, 3.6]


def test_a_file_naming_two_rails_yields_both():
    """`…_1v95_1v65.lib` is a core rail and an IO rail. Returning one of them
    would be a guess about which the reader meant."""
    v, t = FH._corner_from_liberty_name(
        "sky130_ef_io__gpiov2_pad_ff_ss_100C_1v95_1v65.lib")
    assert v == [1.65, 1.95] or v == [1.95, 1.65]
    assert t == [100]


# ── the three false positives that shaped the delimiters ────────────────────

def test_cell_height_is_not_a_voltage():
    """`asap7sc7p5t` — `7p5` is a 7.5-TRACK cell height. Read as a voltage it
    would put a 7.5 V rail in a hand-off for a 7 nm library. It is excluded by
    requiring `_` before the token."""
    v, t = FH._corner_from_liberty_name(
        "asap7sc7p5t_AO_RVT_TT_nldm_211120.lib")
    assert v == [], f"cell height leaked in as a voltage: {v}"
    assert t == []


def test_library_name_voltage_is_not_the_corner_voltage():
    """`gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00` names 5 V TWICE: once in the
    LIBRARY name (`mcu7t5v0`) and once in the corner (`_5v00`). Only the corner
    field is a corner. Here they agree, which is exactly why the case is
    dangerous — on a library whose name and corner disagree, taking the library
    name would be silently wrong."""
    v, t = FH._corner_from_liberty_name(
        "gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")
    assert v == [5.00], f"expected only the corner voltage, got {v}"
    assert t == [25]


def test_a_letter_before_v_is_not_a_voltage():
    """`gpiov2` — a `v` needs a digit in front of it to be a decimal point."""
    v, _ = FH._corner_from_liberty_name("sky130_ef_io__gpiov2_pad.lib")
    assert v == []


# ── NOT_DETERMINED is an answer, and a default is not ───────────────────────







# ── fixture ────────────────────────────────────────────────────────────────

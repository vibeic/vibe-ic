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

def test_pdk_without_operating_points_resolves_to_not_determined(tmp_path):
    """asap7 and nangate45 name no operating point at all. The kit must say so
    and report the size of the search, rather than fall back to a list."""
    proj = _project(tmp_path, libs=[
        "/foss/pdks/asap7/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib",
        "/foss/pdks/nangate45/NangateOpenCellLibrary_typical.lib",
    ])
    FH.main([str(proj)])
    kit = json.loads((proj / "phase3/stage4/foundry_handoff"
                      / "corner_test_vectors.json").read_text())
    assert kit["corner_source"] == "NOT_DETERMINED"
    assert kit["voltage_corners_v"] is None
    assert kit["temperature_corners_celsius"] is None
    # The non-answer states how big the search was — a null beside
    # `liberty_paths_seen: 0` and one beside `2 seen, 2 unparsed` are
    # different facts and must not read the same.
    assert kit["corner_search"]["liberty_paths_seen"] == 2
    assert len(kit["corner_search"]
               ["liberty_names_without_operating_point"]) == 2


def test_signoff_corners_replace_the_canned_literals(tmp_path):
    """The positive half: real liberty paths in, real corners out — and the
    two fabricated PENDING_FOUNDRY_ corner keys gone from the member."""
    proj = _project(tmp_path, libs=[
        "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
        "sky130_fd_sc_hd__tt_025C_1v80.lib",
        "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
        "sky130_fd_sc_hd__ss_100C_1v40.lib",
        "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
        "sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib",
    ])
    FH.main([str(proj)])
    kit = json.loads((proj / "phase3/stage4/foundry_handoff"
                      / "corner_test_vectors.json").read_text())
    assert kit["corner_source"] == "signoff_liberty"
    assert kit["voltage_corners_v"] == [1.4, 1.8, 1.95]
    assert kit["temperature_corners_celsius"] == [-40, 25, 100]
    # NEGATIVE CONTROL — this is the assertion that could not have passed
    # against the pre-fix generator, whose output carried both keys with the
    # canned values regardless of what the flow had consumed.
    assert "PENDING_FOUNDRY_voltage_corners" not in kit
    assert "PENDING_FOUNDRY_temperature_corners_celsius" not in kit
    assert 85 not in (kit["temperature_corners_celsius"] or [])
    assert 125 not in (kit["temperature_corners_celsius"] or [])


def test_corner_fields_no_longer_inflate_the_pending_count(tmp_path):
    """`pending_foundry_count` was the literal `9` and did not move when the
    field set changed. It is counted now, and the two corner fields leaving the
    PENDING namespace is visible in it."""
    proj = _project(tmp_path, libs=[
        "/foss/pdks/sky130A/sky130_fd_sc_hd__tt_025C_1v80.lib"])
    FH.main([str(proj)])
    audit = json.loads((proj / "reports/phase3"
                        / "foundry_handoff_audit.json").read_text())
    # 9 -> 7: exactly the two corner fields, and nothing else, left the
    # PENDING namespace.
    assert audit["pending_foundry_count"] == 7, audit["pending_foundry_count"]
    # The second population — the same items as the GATE counts them, i.e.
    # the JSON keys plus the scribe-line note. Stated separately because
    # quoting one where the other is meant is a different measurement.
    assert audit["pending_open_items_total"] == 8


# ── fixture ────────────────────────────────────────────────────────────────

def _project(tmp_path, libs):
    """A minimal project whose PnR script names `libs`. chip-AGNOSTIC: the
    design is a one-cell stub and every PDK path is a parameter."""
    p = tmp_path / "alpha"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/chip_top.sv").write_text(
        "module chip_top(input clk);\nendmodule\n")
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase2/stage2/synth/netlist.v").write_text(
        "module top(input clk);\n  buf_cell _0_ (.A(clk), .X());\nendmodule\n")
    (p / "phase3/stage3/pnr").mkdir(parents=True)
    (p / "phase3/stage3/pnr/pnr.tcl").write_text(
        "".join(f"read_liberty {lib}\n" for lib in libs)
        + "link_design chip_top\n")
    (p / "phase3/stage4/gds").mkdir(parents=True)
    (p / "phase3/stage4/gds/chip_top.gds").write_bytes(b"\x00\x06\x00\x02alph")
    (p / "phase1/generated_docs").mkdir(parents=True)
    (p / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "alpha"}))
    return p

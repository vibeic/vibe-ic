"""BIDIRECTIONAL test for the `ihp-sg13cmos5l` registry entry.

WHY THE ENTRY EXISTS
====================
`/foss/pdks/ihp-sg13cmos5l` is a real, complete digital PDK inside
vibeic-eda:0.2.30 (sg13cmos5l_stdcell / _io / _sram), but it was absent from
pdk_registry.json. Because it was absent, `--pdk ihp-sg13cmos5l` resolved to
sky130A — see the companion capture
`test_pdk_undeclared_name_refuses_sky130_substitution.py`.

It is the CMOS-only, M1-M4-TM1 sibling of the already-declared `ihp-sg13g2`, so
the tempting shortcut is to copy the sg13g2 entry. That would be wrong in at
least four places, and the tests below pin each one so a future copy-paste
cannot silently reintroduce them:

  * PDN mesh   — sg13g2 straps TopMetal1 x TopMetal2; CMOS5L HAS NO TopMetal2
                 (drc/ihp-sg13cmos5l.drc:24 "# Excludes: Metal5, Via4, TopVia2,
                 TopMetal2, MIM, HBT, Schottky"), so the mesh is Metal4 x TopMetal1.
  * clk buffers— this PDK's OWN librelane config names buf_8 as CTS_ROOT_BUFFER
                 (not sg13g2's buf_16), and deliberately keeps buf_16 out of
                 CTS_CLK_BUFFERS.
  * devices    — CMOS5L has no HBT and no MIM: npn / cap_mim / cap_rfmim are
                 null, and the only capacitor primitive is cap_mfringe.
  * cell names — every master is sg13cmos5l_*, never sg13g2_*.

WHY tap_geom_layers IS LOAD-BEARING
===================================
The PDK ships NO tapcell master (measured: 84 MACROs in the cell LEF = 77 CLASS
CORE + 6 CLASS CORE SPACER + 1 CLASS CORE ANTENNACELL; no CLASS CORE WELLTAP, no
ENDCAP), and says so itself twice:
    libs.tech/librelane/sg13cmos5l_stdcell/config.tcl:49-53
        "There are no endcap and welltie cells in ihp-sg13cmos5l
         thus set to undefined to skip insertion"
    libs.tech/librelane/config.tcl:79-80   "# No tap cells" / FP_TAPCELL_DIST 0
The ties are INSIDE every std cell, so the routed DEF carries 0 tap COMPONENTS
BY DESIGN. Without `tap_geom_layers` the PERC tapless rescue cannot measure the
ties and the latch-up verdict stays INDETERMINATE forever.

The layer numbers come from this PDK's OWN decks
(drc/rule_decks/sg13cmos5l_maximal.drc:1455/1460/1465/1478/1490) and
`implicit_implant: nplus` is a MEASURED fact, not a guess: on the shipped
std-cell GDS, pSD (14/0) has 172 polygons and nSD (7/0) has ZERO, exactly as the
PDK's own deck derives N+ at drc/ihp-sg13cmos5l.drc:260
    nactiv = activ_drw.not(psd_drw.join(nsd_block))

END-TO-END MUTATION CONTROL ALREADY RUN (spm x ihp-sg13cmos5l, plugin 1.6.4,
image vibeic-eda:0.2.30 id sha256:4182c63b10d1), three FRESH full runs:
    tapless + tap_geom_layers        -> PASS       WELLTAP_PRESENT_BY_GEOMETRY
                                                   (ntap=20/936.762um2, ptap=21/1092.116um2)
    tapcell_master DECLARED, 0 placed-> FAIL       WELLTAP_GAP  (conclusive)
    tapless, tap_geom_layers REMOVED -> INCOMPLETE WELLTAP_TAPLESS_INDETERMINATE
i.e. the entry does NOT defeat the gate: a PDK that declares a real tapcell
master with zero placed taps still fails conclusively, and an unmeasurable case
stays INDETERMINATE rather than becoming a fabricated pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
NAME = "ihp-sg13cmos5l"
SIBLING = "ihp-sg13g2"


def _pdks() -> dict:
    data = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    return {e["name"]: e for e in data["pdks"] if e.get("name")}


@pytest.fixture(scope="module")
def entry() -> dict:
    p = _pdks()
    assert NAME in p, f"{NAME} missing from pdk_registry.json"
    return p[NAME]


# --------------------------------------------------------------------------
# POSITIVE CONTROLS — the entry states what it must
# --------------------------------------------------------------------------

def test_entry_is_present_and_points_at_its_own_container_path(entry):
    assert entry["container_path"] == f"/foss/pdks/{NAME}"
    assert entry["process_node_nm"] == 130
    assert entry["open_source"] is True


@pytest.mark.parametrize("key", [
    "liberty_glob", "tech_lef_glob", "cell_lef_glob", "cell_gds_glob",
    "drc_deck", "lvs_deck", "klayout_lvs_deck", "lefdef_layermap",
])
def test_every_asset_path_is_relative_and_belongs_to_this_pdk(entry, key):
    """Assets must be THIS PDK's own files: relative paths, and never a
    sg13g2 path smuggled in by copy-paste."""
    v = entry[key]
    assert isinstance(v, str) and v, f"{key} empty"
    assert not v.startswith("/"), f"{key} must be relative to container_path"
    assert "sg13g2" not in v, f"{key} points at the SIBLING PDK: {v}"


def test_tapless_pdk_declares_null_tapcell_master(entry):
    """The PDK ships no tapcell master; declaring one would send the flow down
    the tapcell-methodology branch and produce a false WELLTAP_GAP."""
    assert entry["tapcell_master"] is None


def test_tap_geom_layers_carry_the_pdk_own_feol_numbers(entry):
    """Without these the PERC tapless rescue cannot measure the ties and the
    latch-up verdict is stuck at WELLTAP_TAPLESS_INDETERMINATE."""
    tg = entry["tap_geom_layers"]
    assert tg == {
        "nwell": "31/0",
        "nplus": "7/0",
        "pplus": "14/0",
        "poly": "5/0",
        "activ": "1/0",
        "implicit_implant": "nplus",
    }


# --------------------------------------------------------------------------
# NEGATIVE CONTROLS — the four ways a copy of the sg13g2 entry would be WRONG
# --------------------------------------------------------------------------

def test_NEGATIVE_CONTROL_pdn_does_not_use_the_nonexistent_TopMetal2(entry):
    """CMOS5L has no TopMetal2. Straps copied from sg13g2 would target a layer
    this PDK's tech LEF does not define."""
    layers = [s["layer"] for s in entry["pdn_straps"]["stripes"]]
    assert "TopMetal2" not in layers, layers
    assert layers == ["Metal4", "TopMetal1"], layers
    flat = [l for pair in entry["pdn_straps"]["connects"] for l in pair]
    assert "TopMetal2" not in flat, flat


def test_NEGATIVE_CONTROL_no_sg13g2_cell_name_leaks_into_the_entry(entry):
    """Any sg13g2_* master name anywhere in this entry is a copy-paste escape."""
    blob = json.dumps(entry, ensure_ascii=False)
    assert "sg13g2_" not in blob, "a sg13g2_* cell name leaked into the entry"


def test_NEGATIVE_CONTROL_clk_buffers_are_this_pdk_declared_cts_set(entry):
    """The PDK's own config.tcl names buf_8 as CTS_ROOT_BUFFER and keeps buf_16
    OUT of the CTS set — copying sg13g2's buf_16 root would use a cell this PDK
    deliberately excludes from CTS."""
    assert entry["clk_buf_cell"] == "sg13cmos5l_buf_4"
    assert entry["clk_buf_root_cell"] == "sg13cmos5l_buf_8"
    assert "16" not in entry["clk_buf_root_cell"]


def test_NEGATIVE_CONTROL_absent_device_modules_are_null_not_inherited(entry):
    """CMOS5L excludes MIM and HBT. Inheriting sg13g2's npn13G2 / cap_cmim would
    map a generic role onto a primitive this process does not have."""
    dm = entry["device_map"]
    assert dm["npn"] is None
    assert dm["cap_mim"] is None
    assert dm["cap_rfmim"] is None
    assert dm["cap_fringe"] == "cap_mfringe"
    for absent in ("npn13G2", "cap_cmim", "cap_rfcmim"):
        assert absent not in entry["device_models"], absent


# --------------------------------------------------------------------------
# The sibling must be untouched — this capture ADDS, it does not edit sg13g2
# --------------------------------------------------------------------------

def test_sibling_sg13g2_entry_is_not_disturbed():
    sib = _pdks()[SIBLING]
    assert sib["tapcell_master"] is None
    assert sib["container_path"] == f"/foss/pdks/{SIBLING}"
    assert [s["layer"] for s in sib["pdn_straps"]["stripes"]] == [
        "TopMetal1", "TopMetal2"], "the sg13g2 PDN was modified"


def test_two_ihp_entries_are_distinct_not_duplicates():
    p = _pdks()
    a, b = p[NAME], p[SIBLING]
    assert a["liberty_glob"] != b["liberty_glob"]
    assert a["drc_deck"] != b["drc_deck"]
    assert a["lefdef_layermap"] != b["lefdef_layermap"]
    assert a["clk_buf_root_cell"] != b["clk_buf_root_cell"]

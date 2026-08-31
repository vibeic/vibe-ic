"""A4 `build_design_deck` on a SECTIONED-corner-lib PDK (vibe-ic u_hawaii_adc).

WHAT WENT WRONG (measured, u_hawaii_adc ldo, plugin v1.14.71): A3's own emitter
writes the PDK-correct per-device-class binding for a sectioned corner library
family — three `.lib` cards (`cornerMOShv.lib mos_tt` + `cornerCAP.lib cap_typ`
+ `cornerRES.lib res_typ`) — and A4's `build_design_deck` refused ANY deck whose
total `.lib` card count was not exactly 1. A3 and A4 disagreed inside the same
plugin, so every block on such a PDK dead-ended at A4 with
"the delivered deck carries 3 `.lib` corner card(s)".

THE RULE. The card A4 owns is the one bound to the model set A4 RESOLVED
(matched by file name — the same identity the model-set refusal has always
used). Exactly one such card is required. Companion device-class cards are
A3's electrical decisions: kept VERBATIM (never blanket-restamped with the
process corner, whose section vocabulary belongs to a different library) and
recorded in the info dict, never silently.

Bidirectional controls:
  * the sectioned 3-card deck BUILDS after the fix (pre-fix: refused) — the
    positive arm;
  * two cards bound to the SAME resolved model set still REFUSE (ambiguity);
  * zero `.lib` cards still REFUSE;
  * a deck bound only to a DIFFERENT model set still REFUSES and names both
    sides (the pre-existing pin, held);
  * the single-card known-family deck is BYTE-IDENTICAL to the pre-fix
    rendering — the negative control that proves the relaxation reaches only
    the tree it was written for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import analog_real_corner_sweep as S  # noqa: E402

MOS_LIB = "/foss/pdks/fam_x/libs.tech/ngspice/models/cornerMOShv.lib"
CAP_LIB = "/foss/pdks/fam_x/libs.tech/ngspice/models/cornerCAP.lib"
RES_LIB = "/foss/pdks/fam_x/libs.tech/ngspice/models/cornerRES.lib"
SKY_LIB = "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice"


def _proj(tmp_path: Path, block: str, lib_cards: str) -> Path:
    root = tmp_path / "proj"
    bdir = root / "phase3" / "analog" / block
    bdir.mkdir(parents=True)
    (bdir / f"{block}.sp").write_text(
        f"* {block} delivered netlist\n"
        f"{lib_cards}"
        f".subckt {block} vdd vss vout\n"
        f"xm1 vout vss vss vss fam_x_hv_nmos w=10u l=1u\n"
        f".ends {block}\n")
    (bdir / f"tb_{block}.sp").write_text(
        f"* tb\n.include {block}.sp\n"
        f"v1 vdd 0 1.8\nxdut vdd 0 vout {block}\n"
        f".control\nop\n.endc\n.end\n")
    return root


def test_sectioned_three_card_deck_builds_and_restamps_only_the_own_card(
        tmp_path: Path) -> None:
    cards = (f".lib {MOS_LIB} mos_tt\n"
             f".lib {CAP_LIB} cap_typ\n"
             f".lib {RES_LIB} res_typ\n")
    project = _proj(tmp_path, "blk", cards)
    deck, info = S.build_design_deck(project, "blk", MOS_LIB, "mos_ss")
    assert deck is not None, info.get("reason")
    lines = [ln.strip() for ln in deck.splitlines()
             if ln.strip().startswith(".lib")]
    assert f".lib {MOS_LIB} mos_ss" in lines, "own card must take THIS corner"
    assert f".lib {CAP_LIB} cap_typ" in lines, "companion card kept verbatim"
    assert f".lib {RES_LIB} res_typ" in lines, "companion card kept verbatim"
    assert all("mos_ss" not in ln for ln in lines
               if not ln.startswith(f".lib {MOS_LIB}")), (
        "a companion device-class card must never receive the process corner")
    assert info["declared_model_lib"] == MOS_LIB
    assert info["declared_model_section"] == "mos_tt"
    assert info["lib_cards_restamped"] == 1
    assert info["lib_cards_kept"] == 2
    assert {c["lib"] for c in info["companion_lib_cards"]} == {CAP_LIB, RES_LIB}


def test_two_cards_bound_to_the_resolved_model_set_still_refuse(
        tmp_path: Path) -> None:
    cards = (f".lib {MOS_LIB} mos_tt\n"
             f".lib {MOS_LIB} mos_ff\n")
    project = _proj(tmp_path, "blk", cards)
    deck, info = S.build_design_deck(project, "blk", MOS_LIB, "mos_ss")
    assert deck is None
    assert "2" in info["reason"] and "exactly one" in info["reason"]


def test_zero_lib_cards_still_refuse(tmp_path: Path) -> None:
    project = _proj(tmp_path, "blk", "")
    deck, info = S.build_design_deck(project, "blk", MOS_LIB, "mos_ss")
    assert deck is None
    assert "0" in info["reason"]


def test_deck_bound_only_to_a_different_model_set_names_both_sides(
        tmp_path: Path) -> None:
    cards = f".lib {SKY_LIB} tt\n"
    project = _proj(tmp_path, "blk", cards)
    deck, info = S.build_design_deck(project, "blk", MOS_LIB, "mos_ss")
    assert deck is None
    assert "sky130.lib.spice" in info["reason"]
    assert "cornerMOShv.lib" in info["reason"], (
        "the refusal must name BOTH bindings, or nobody can tell which is wrong")


def test_single_card_known_family_deck_is_byte_identical(
        tmp_path: Path) -> None:
    """Negative control: on the path every prior run took (one `.lib` card,
    matching model set) the emitted deck is EXACTLY the pre-fix rendering —
    the same single card restamped, nothing else touched."""
    cards = f".lib {SKY_LIB} tt\n"
    project = _proj(tmp_path, "blk", cards)
    deck, info = S.build_design_deck(project, "blk", SKY_LIB, "ss")
    assert deck is not None, info.get("reason")
    lines = [ln.strip() for ln in deck.splitlines()
             if ln.strip().startswith(".lib")]
    assert lines == [f".lib {SKY_LIB} ss"]
    assert info["lib_cards_restamped"] == 1
    assert info["lib_cards_kept"] == 0
    assert info["companion_lib_cards"] == []


def test_required_roles_read_the_naming_convention_not_one_pdk(
        tmp_path: Path) -> None:
    """`design_deck_required_roles` used to match sky130 literals only, so any
    other family's netlist reported None and the flavour election downstream
    ran unconstrained. It now reads the industry naming convention
    (nmos/nfet vs pmos/pfet identifiers), comments excluded."""
    project = _proj(
        tmp_path, "blk",
        f".lib {MOS_LIB} mos_tt\n")
    sp = project / "phase3" / "analog" / "blk" / "blk.sp"
    sp.write_text(sp.read_text() +
                  "xm2 a b c d fam_x_lv_pmos w=2u l=1u\n"
                  "* comment mentioning nothing_relevant\n")
    assert S.design_deck_required_roles(project, "blk") == ("nmos", "pmos")

    # comments alone must not manufacture a role
    only_comment = _proj(tmp_path / "c2", "blkc", f".lib {MOS_LIB} mos_tt\n")
    spc = only_comment / "phase3" / "analog" / "blkc" / "blkc.sp"
    spc.write_text("* a PMOS is mentioned in prose only\n"
                   f".lib {MOS_LIB} mos_tt\n"
                   ".subckt blkc a b\nr1 a b 1k\n.ends blkc\n")
    assert S.design_deck_required_roles(only_comment, "blkc") is None

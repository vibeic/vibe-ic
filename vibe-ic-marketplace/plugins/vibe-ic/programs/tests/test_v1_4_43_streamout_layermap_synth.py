"""v1.4.43 — deck-derived streamout layermap synthesis (sha256 commercial-PDK
clean-room). When a commercial PDK ships a sign-off DRC deck but no standalone
Encounter/SoC streamout map, the KLayout LEF/DEF reader falls back to legacy
numbering and scatters the via/cut layers onto GDS numbers that collide with the
deck's reserved FEOL device layers (proven on the real routed sha256 design:
36 DRC fails -> 11 after the fix; the entire LMFfc.* fuse chain, 18 rules gated
on the mis-numbered FUSEOPEN layer, clears).

`_synthesize_streamout_layermap` reads the LEF->GDS numbering the deck itself
embeds (`LAYER <name> <internal>` + `LAYER MAP <gds> DATATYPE <dt> <internal>`)
and emits a KLayout LEF/DEF map pinning every LEF routing/cut layer to its
deck-true number. These tests use a SYNTHETIC deck + LEF with DIFFERENT layer
names and numbers than the real PDK, to prove the mechanism reads the deck and
hardcodes nothing.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# A synthetic deck: routing FOO1/FOO2 on 20/22, cut CUT1 on 21, and a FEOL
# device layer DEV on 40 — DELIBERATELY different names/numbers from the real
# PDK (MET/VIA/9/10/11...) so a hardcoded map would fail these.
_DECK = """\
LAYER FOO1 1000
LAYER MAP 20 DATATYPE 0 1000
LAYER CUT1 1001
LAYER MAP 21 DATATYPE 0 1001
LAYER FOO2 1002
LAYER MAP 22 DATATYPE 0 1002
LAYER DEV 1003
LAYER MAP 40 DATATYPE 0 1003
LAYER BADR 1004
LAYER MAP 40 DATATYPE 0 1004
"""

_LEF = """\
LAYER FOO1
  TYPE ROUTING ;
END FOO1
LAYER CUT1
  TYPE CUT ;
END CUT1
LAYER FOO2
  TYPE ROUTING ;
END FOO2
"""


def _write(tmp, name, text):
    p = tmp / name
    p.write_text(text)
    return p


def test_synthesizes_deck_true_numbers_generic(tmp_path):
    deck = _write(tmp_path, "SYNTH_DRC.rule", _DECK)
    lef = _write(tmp_path, "tech.lef", _LEF)
    mp, notes = R._synthesize_streamout_layermap(str(deck), str(lef),
                                                 tmp_path / "stage")
    assert mp is not None and Path(mp).is_file()
    body = Path(mp).read_text()
    # routing FOO1->20, FOO2->22 ; cut CUT1->21 — the deck's own numbers.
    assert "FOO1" in body and " 20 0" in body
    assert "FOO2" in body and " 22 0" in body
    assert "CUT1" in body and " 21 0" in body
    # the CUT purpose line for the via layer
    assert any(l.startswith("CUT1") and "VIA" in l for l in body.splitlines())
    # nothing is emitted onto the FEOL device number 40.
    assert " 40 " not in body and " 40\n" not in body


def test_map_has_the_klayout_lefdef_four_token_format(tmp_path):
    # every emitted data line must be `<name> <purpose_csv> <int> <int>` — the
    # KLayout LEF/DEF map shape (same as the proven sky130A.map). The file is
    # DELIBERATELY named `*_streamout_synth.map` so it does NOT match
    # _discover_lefdef_layermap's globs and can never be re-discovered as a
    # stale "shipped" map on a second run.
    deck = _write(tmp_path, "SYNTH_DRC.rule", _DECK)
    lef = _write(tmp_path, "tech.lef", _LEF)
    mp, _ = R._synthesize_streamout_layermap(str(deck), str(lef), tmp_path / "stage")
    assert not Path(mp).name.lower().endswith(".layermap")
    assert "layermap" not in Path(mp).name.lower()
    for line in Path(mp).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        toks = s.split()
        assert len(toks) >= 4, line
        assert toks[-1].isdigit() and toks[-2].isdigit(), line


def test_via_collision_case_pins_cut_to_deck_number(tmp_path):
    # The real bug: without a map the CUT layer lands on a FEOL number. Here we
    # assert the cut IS pinned to its own deck number (21), never left to default.
    deck = _write(tmp_path, "SYNTH_DRC.rule", _DECK)
    lef = _write(tmp_path, "tech.lef", _LEF)
    mp, notes = R._synthesize_streamout_layermap(str(deck), str(lef), tmp_path / "stage")
    cut_lines = [l for l in Path(mp).read_text().splitlines()
                 if l.startswith("CUT1")]
    assert cut_lines and cut_lines[0].split()[-2:] == ["21", "0"]
    assert any("cut/via pinned" in n for n in notes)


def test_unmatched_cut_layer_warns_critical_and_is_omitted(tmp_path):
    # A LEF cut layer the deck has NO entry for -> CRITICAL warn, omitted.
    deck = _write(tmp_path, "SYNTH_DRC.rule", _DECK)
    lef2 = _LEF + "LAYER VIAX\n  TYPE CUT ;\nEND VIAX\n"
    lef = _write(tmp_path, "tech.lef", lef2)
    mp, notes = R._synthesize_streamout_layermap(str(deck), str(lef), tmp_path / "stage")
    assert "VIAX" not in Path(mp).read_text()      # omitted, never mis-mapped
    assert any("CRITICAL" in n and "VIAX" in n for n in notes)


def test_routing_layer_on_reserved_feol_number_is_dropped(tmp_path):
    # If a ROUTING layer's deck number is one used ONLY by a non-routing (FEOL)
    # layer, it must be DROPPED + WARN (never shipped onto a FEOL number).
    deck = _DECK + "LAYER FOO3 1005\nLAYER MAP 40 DATATYPE 0 1005\n"
    lef2 = _LEF + "LAYER FOO3\n  TYPE ROUTING ;\nEND FOO3\n"
    deck_p = _write(tmp_path, "SYNTH_DRC.rule", deck)
    lef_p = _write(tmp_path, "tech.lef", lef2)
    mp, notes = R._synthesize_streamout_layermap(str(deck_p), str(lef_p),
                                                 tmp_path / "stage")
    # FOO3 -> 40 collides with FEOL-only DEV/BADR(40) -> dropped + WARN.
    assert "FOO3" not in Path(mp).read_text()
    assert any("FOO3" in n and "FEOL" in n for n in notes)


def test_noop_without_deck_or_lef(tmp_path):
    lef = _write(tmp_path, "tech.lef", _LEF)
    assert R._synthesize_streamout_layermap(None, str(lef), tmp_path)[0] is None
    deck = _write(tmp_path, "SYNTH_DRC.rule", _DECK)
    assert R._synthesize_streamout_layermap(str(deck), None, tmp_path)[0] is None
    # a deck with no LAYER MAP table -> None
    empty = _write(tmp_path, "empty.rule", "// no layer map here\n")
    assert R._synthesize_streamout_layermap(str(empty), str(lef), tmp_path)[0] is None


def test_wired_into_detect_pdk(tmp_path):
    # end-to-end: a custom PDK with a deck but no shipped map -> _detect_pdk
    # sets pdk.lefdef_layermap to the SYNTHESIZED map (both streamout &
    # LVS --pdk-map then consume it).
    pdk = tmp_path / "input" / "pdk"
    (pdk / "liberty").mkdir(parents=True)
    (pdk / "liberty" / "std_tt.lib").write_text("library(std){}\n")
    (pdk / "lef").mkdir()
    (pdk / "lef" / "tech.tlef").write_text(_LEF)
    (pdk / "lef" / "macro.lef").write_text("MACRO INV\nEND INV\n")
    (pdk / "gds").mkdir()
    (pdk / "gds" / "cells.gds").write_bytes(b"\x00\x06\x00\x02\x00\x00")  # tiny stub
    (pdk / "calibre").mkdir()
    (pdk / "calibre" / "SYNTH_DRC.rule").write_text(_DECK)
    p = R._detect_pdk(tmp_path, override="auto")
    assert p is not None
    assert p.lefdef_layermap is not None
    assert "streamout_synth.map" in p.lefdef_layermap

"""v1.3.93 — unit tests for the commercial-PDK phase3 sign-off gate fixes that
drove spm to a genuine tapeout-clean state on a TAPLESS-CELL PDK (commercial
commercial PDK). All pure-Python / deterministic (no `pya`, no container, no oracle):

  * _parse_gds_layer_spec          — "N/D" | "N" GDS layer spec parsing.
  * _measure_tap_geometry          — FAIL-SAFE: never a fabricated pass when the
                                     tap_geom_layers config is absent.
  * _discover_spare_cells_from_liberty — the mux2 pattern now resolves the
                                     Artisan `MX2*/MXI2*` naming (else the spare
                                     density target is unreachable on commercial
                                     PDKs).
  * _build_pdn_tcl                 — emits upper-metal straps + add_pdn_connect
                                     when pdk.pdn_straps is set; met1-only else.
  * def_gds_port_power_restore     — parse_power_rails captures the metal layer;
                                     metal_index; the marker is painted on the
                                     FOLLOW-PIN layer only (straps NOT marked).

Chip-AGNOSTIC synthetic fixtures (generic `widget` top, generic cells).
"""
import importlib
import types

mod = importlib.import_module("phase3_one_shot_runner")
pwr = importlib.import_module("def_gds_port_power_restore")


# --- _parse_gds_layer_spec -------------------------------------------------
def test_parse_gds_layer_spec():
    assert mod._parse_gds_layer_spec("2/0") == (2, 0)
    assert mod._parse_gds_layer_spec("15/1") == (15, 1)
    assert mod._parse_gds_layer_spec("9") == (9, 0)      # datatype defaults to 0
    assert mod._parse_gds_layer_spec(None) is None
    assert mod._parse_gds_layer_spec("met1") is None     # non-numeric -> None
    assert mod._parse_gds_layer_spec("") is None


# --- _measure_tap_geometry FAIL-SAFE (never a fabricated pass) --------------
def _fake_pdk(**kw):
    d = {"tap_geom_layers": None}
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_measure_tap_geometry_no_config_is_not_ok(tmp_path):
    # No tap_geom_layers -> ok=False (INDETERMINATE), never a fabricated pass.
    res = mod._measure_tap_geometry(tmp_path, "widget", _fake_pdk(), "no-container")
    assert res["ok"] is False
    assert "nwell" in res["reason"] or "tap_geom_layers" in res["reason"]


def test_measure_tap_geometry_partial_config_is_not_ok(tmp_path):
    # nwell only (missing nplus/pplus) -> still not ok (needs all three).
    pdk = _fake_pdk(tap_geom_layers={"nwell": "2/0"})
    res = mod._measure_tap_geometry(tmp_path, "widget", pdk, "no-container")
    assert res["ok"] is False


# --- spare mux2 pattern (Artisan MX2*/MXI2* naming) ------------------------
_LIB = """\
library (commercial_pdk) {
  cell (INVD1) { }
  cell (NAND2D1) { }
  cell (NOR2D1) { }
  cell (MX2D1) { }
  cell (MXI2D1) { }
  cell (AOI21D1) { }
  cell (OAI21D1) { }
  cell (DFFD1) { }
}
"""


def test_spare_mux2_resolves_artisan_mx2_name(tmp_path):
    lib = tmp_path / "commercial_pdk.lib"
    lib.write_text(_LIB)
    out = mod._discover_spare_cells_from_liberty(str(lib))
    # the mux2 class must resolve to a concrete cell (MX2* / MXI2*), not None —
    # a None here drops the class and sinks the spare-density target.
    assert out["mux2"] in ("MX2D1", "MXI2D1")
    # the other classes still resolve (no regression).
    assert out["inverter"] == "INVD1"
    assert out["nand2"] == "NAND2D1"
    assert out["dff"] == "DFFD1"


def test_spare_mux2_none_when_no_mux(tmp_path):
    lib = tmp_path / "nomux.lib"
    lib.write_text("library (x) { cell (INVD1) { } cell (NAND2D1) { } }\n")
    out = mod._discover_spare_cells_from_liberty(str(lib))
    assert out["mux2"] is None            # honestly None when the library has no mux


# --- _build_pdn_tcl strap emission ----------------------------------------
def _pdn_pdk(straps=None):
    # A non-sky130 (commercial) PDK: tapcell_master None -> adaptive branch.
    # _discover_pg_from_lef reads cell_lef; supply a minimal LEF with PG pins.
    return straps


def test_build_pdn_tcl_emits_straps_when_configured(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text(
        "MACRO NAND2D1\n  CLASS CORE ;\n  SIZE 2.64 BY 5.04 ;\n"
        "  PIN VDD\n    USE POWER ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 4.8 2.64 5.04 ;\n    END\n  END VDD\n"
        "  PIN VSS\n    USE GROUND ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 0 2.64 0.24 ;\n    END\n  END VSS\nEND NAND2D1\n")
    pdk = types.SimpleNamespace(
        tapcell_master=None, cell_lef=str(lef),
        pdn_straps={"stripes": [{"layer": "MET4", "width": 1.6, "pitch": 22.4,
                                 "offset": 2.24}],
                    "connects": [["MET1", "MET4"]]})
    tcl = mod._build_pdn_tcl(pdk)
    assert "add_pdn_stripe -grid grid -layer MET4 -width 1.6 -pitch 22.4" in tcl
    assert "add_pdn_connect -grid grid -layers {MET1 MET4}" in tcl
    assert "-followpins" in tcl              # the met1 follow-pins rail is still there
    assert "straps(MET4)" in tcl


def test_build_pdn_tcl_met1_only_when_no_straps(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text(
        "MACRO NAND2D1\n  CLASS CORE ;\n  SIZE 2.64 BY 5.04 ;\n"
        "  PIN VDD\n    USE POWER ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 4.8 2.64 5.04 ;\n    END\n  END VDD\n"
        "  PIN VSS\n    USE GROUND ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 0 2.64 0.24 ;\n    END\n  END VSS\nEND NAND2D1\n")
    pdk = types.SimpleNamespace(tapcell_master=None, cell_lef=str(lef),
                                pdn_straps=None)
    tcl = mod._build_pdn_tcl(pdk)
    assert "-followpins" in tcl
    assert "add_pdn_stripe -grid grid -layer MET4" not in tcl   # no straps
    assert "add_pdn_connect" not in tcl


# --- def_gds_port_power_restore: layer-aware rail markers ------------------
def test_metal_num():
    """#613 folded `_metal_num`'s sentinel into the ONE resolver: an
    unresolvable name is 0, and `parse_power_rails` drops those segments before
    the minimum is taken, so no sentinel has to survive into the arithmetic."""
    assert pwr.metal_index("MET1") == 1
    assert pwr.metal_index("MET4") == 4
    assert pwr.metal_index("met3") == 3          # case-insensitive
    assert pwr.metal_index("VIA1") == 0          # non-metal -> unresolved
    assert pwr.metal_index(None) == 0


_DEF_WITH_STRAP = """\
DESIGN spm ;
UNITS DISTANCE MICRONS 1000 ;
SPECIALNETS 2 ;
- VDD ( * VDD )
  + ROUTED MET1 800 + SHAPE FOLLOWPIN ( 0 5000 ) ( 145000 * )
  NEW MET4 1600 ( 2240 0 ) ( 2240 145000 )
  + USE POWER ;
- VSS ( * VSS )
  + ROUTED MET1 800 + SHAPE FOLLOWPIN ( 0 0 ) ( 145000 * )
  NEW MET4 1600 ( 24640 0 ) ( 24640 145000 )
  + USE GROUND ;
END SPECIALNETS
END DESIGN
"""


def test_parse_power_rails_captures_metal_layer():
    rails = pwr.parse_power_rails(_DEF_WITH_STRAP)
    assert set(rails) == {"VDD", "VSS"}
    # each net has a MET1 follow-pin seg + a MET4 strap seg; the tuple now
    # carries the metal token as the 6th element.
    metals = {seg[5] for segs in rails.values() for seg in segs}
    assert metals == {"MET1", "MET4"}
    for segs in rails.values():
        for seg in segs:
            assert len(seg) == 6            # (x1,y1,x2,y2,w,metal)


def test_followpin_min_layer_is_met1():
    # the marker-painting layer selection in restore() picks the LOWEST metal
    # among all rail segs — MET1 here — so MET4 straps are NOT painted.
    rails = pwr.parse_power_rails(_DEF_WITH_STRAP)
    all_metals = [pwr.metal_index(s[5]) for segs in rails.values() for s in segs]
    assert min(all_metals) == 1             # follow-pin layer
    # exactly the MET4 strap segs would be skipped (2 straps: 1 VDD + 1 VSS).
    skipped = [s for segs in rails.values() for s in segs
               if pwr.metal_index(s[5]) != 1]
    assert len(skipped) == 2
    assert all(s[5] == "MET4" for s in skipped)


# --- _discover_via_resistances (PSM static-IR resistance map) ---------------
_TECH_LEF_VIAS = """\
LAYER MET1
  TYPE ROUTING ;
  RESISTANCE RPERSQ 0.082 ;
END MET1
LAYER VIA1
  TYPE CUT ;
END VIA1
VIA VIA12 DEFAULT
  LAYER MET1 ;
    RECT -0.14 -0.14 0.14 0.14 ;
  LAYER VIA1 ;
    RECT -0.11 -0.11 0.11 0.11 ;
  LAYER MET2 ;
    RECT -0.14 -0.14 0.14 0.14 ;
  RESISTANCE 5.5 ;
END VIA12
VIA VIA23 DEFAULT
  LAYER MET2 ;
  LAYER VIA2 ;
  LAYER MET3 ;
  RESISTANCE 5.5 ;
END VIA23
VIA VIA56_CENTER DEFAULT
  LAYER MET5 ;
  LAYER VIA5 ;
  LAYER MET6 ;
  RESISTANCE 0.75 ;
END VIA56_CENTER
"""


def test_discover_via_resistances(tmp_path):
    lef = tmp_path / "tech.lef"
    lef.write_text(_TECH_LEF_VIAS)
    vr = mod._discover_via_resistances(str(lef))
    # each fixed-VIA master maps to its CUT layer (VIAn), not the METn metals.
    assert vr == {"VIA1": 5.5, "VIA2": 5.5, "VIA5": 0.75}
    # no MET* keys leaked in (only cut layers).
    assert all(k.startswith("VIA") for k in vr)


def test_discover_via_resistances_missing_lef():
    # FAIL-SAFE: no tech LEF -> empty dict (PSM would then skip via RC honestly),
    # never a fabricated resistance.
    assert mod._discover_via_resistances(None) == {}
    assert mod._discover_via_resistances("/no/such/tech.lef") == {}

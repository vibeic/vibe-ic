"""Regression: chip-AGNOSTIC per-layer density metal-fill config derivation.

`metal_fill_config_gen.build_metal_fill_config` synthesizes the density metal-fill
config from a PDK's OWN declared files — the streamout LEF->GDS layermap (layer numbers),
the tech LEF (routing width + manufacturing grid) and the sign-off DRC deck (the dummy
datatype, the dummy-metal spacings, and the metal density floor). This closes the gap
where an open PDK ships no bridge `metal_fill_density` config, so the flow skipped metal
fill and a sparse die FAILed the min-metal-density sign-off DRC.

All fixtures below are SYNTHETIC / NDA-clean with arbitrary layer numbers — the point is
that the derivation is purely a function of the PDK-declared TEXT, with no vendor / chip /
PDK literal in the logic. The engine's DRC-clean behaviour on a real streamed GDS is
proven separately by the flow's own sign-off DRC (this unit test guards the derivation).
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import metal_fill_config_gen as G  # noqa: E402


# A synthetic streamout layermap (KLayout .map shape): `<name> <purposes> <num> <dt>`.
# Arbitrary numbers; the DRAWN (datatype-0 / NET) line is the one that must be picked.
_LAYERMAP = """\
# synthetic streamout map
Metal1  NET,SPNET,PIN,VIA 61 0
NAME    Metal1/LABEL      61 10
Metal1  PIN               61 10
Metal2  NET,SPNET,PIN,VIA 62 0
Metal2  PIN               62 10
Contact CUT               50 0
"""

# A synthetic tech LEF with two routing metals + a manufacturing grid, and (crucially) a
# recurring `LAYER Metal1 ;` geometry reference that must NOT overwrite the real block.
_TECHLEF = """\
MANUFACTURINGGRID 0.010 ;
LAYER Metal1
    TYPE ROUTING ;
    MINWIDTH 0.20 ;
    WIDTH 0.20 ;
    SPACING 0.20 ;
    SPACING 0.30 RANGE 10.0 999.0 ;
END Metal1
LAYER Via1
    TYPE CUT ;
    WIDTH 0.20 ;
    SPACING 0.20 ;
END Via1
LAYER Metal2
    TYPE ROUTING ;
    WIDTH 0.24 ;
    SPACING 0.24 ;
    SPACING 0.30 RANGE 10.0 999.0 ;
END Metal2
MACRO SOMECELL
  PIN A
    LAYER Metal1 ;
      RECT 0 0 0.4 0.4 ;
    LAYER Metal2 ;
      RECT 0 0 0.4 0.4 ;
  END A
END SOMECELL
"""

# A synthetic DRC deck: the layer table (drawn + dummy datatypes), the dummy-metal
# spacing rules, and the metal density floor rule.
_DECK = """\
extract_single_layer_from_design.call(:metal1_drawn, 61, 0)
extract_single_layer_from_design.call(:metal1_dummy, 61, 7)
extract_single_layer_from_design.call(:metal2_drawn, 62, 0)
extract_single_layer_from_design.call(:metal2_dummy, 62, 7)

def dummy_metal_rules(idx:)
  metal_dummy = ctx[...]
  dm_2b = metal_dummy.space(1.00.um, euclidian)
  dm_3  = metal_dummy.separation(metal_drawn, 2.50.um, euclidian)
end

if (metal1.area / chip_area) * 100 < 33
  extent.output('M1.4', 'Metal1 coverage ... : 33%')
end
if (metal2.area / chip_area) * 100 < 33
  extent.output('M2.4', 'Metal2 coverage ... : 33%')
end
"""


def _cfg(**kw):
    return G.build_metal_fill_config(_LAYERMAP, _TECHLEF, _DECK,
                                     metal_prefix="Metal", **kw)


def test_layer_numbers_from_layermap():
    cfg = _cfg()
    by = {l["name"]: l for l in cfg["layers"]}
    # DRAWN datatype-0 lines picked, in metal order
    assert [l["name"] for l in cfg["layers"]] == ["metal1", "metal2"]
    assert by["metal1"]["layer"] == [61, 0]
    assert by["metal2"]["layer"] == [62, 0]


def test_dummy_datatype_and_two_spacings():
    cfg = _cfg()
    m1 = cfg["layers"][0]
    # dummy datatype from the deck's `metalN_dummy, num, dt` entry
    assert m1["fill_datatype"] == 7
    # DM.2b dummy-to-dummy and DM.3 dummy-to-circuit, from the deck's own rules
    assert m1["space"] == 1.00
    assert m1["space_to_metal"] == 2.50
    assert cfg["_derivation"]["dummy_space_um"] == 1.00
    assert cfg["_derivation"]["dummy_to_circuit_space_um"] == 2.50


def test_density_floor_and_target():
    cfg = _cfg(margin=0.05)
    # floor read from the deck (33%), target = floor + margin
    assert cfg["_derivation"]["density_floor_pct"] == 33.0
    assert abs(cfg["layers"][0]["target"] - 0.38) < 1e-9


def test_manufacturing_grid_and_on_grid_width():
    cfg = _cfg()
    assert cfg["mfg_grid_um"] == 0.010
    for l in cfg["layers"]:
        # width is snapped to the manufacturing grid (multiple of 0.010)
        steps = round(l["width"] / 0.010)
        assert abs(l["width"] - steps * 0.010) < 1e-9
        assert l["width"] > 0


def test_whole_die_window_and_full_extent_bbox():
    cfg = _cfg()
    # None window -> single whole-die window == the deck's whole-die coverage rule;
    # None boundary layer -> engine uses the full-layout extent.
    assert cfg["window_um"] is None
    assert cfg["boundary_layer"] is None


def test_techlef_block_dedup_not_clobbered_by_geometry_ref():
    # The recurring `LAYER Metal1 ;` inside the MACRO must not blank the routing block.
    ws = G.parse_techlef_routing(_TECHLEF, "Metal")
    assert "metal1" in ws and "metal2" in ws
    min_w, max_s = ws["metal1"]
    assert min_w == 0.20
    assert max_s == 0.30            # the wide-metal SPACING (keep-out), not 0.20


def test_no_dummy_datatype_falls_back_to_drawn_disclosed():
    deck_no_dummy = "\n".join(
        l for l in _DECK.splitlines() if "dummy" not in l)
    cfg = G.build_metal_fill_config(_LAYERMAP, _TECHLEF, deck_no_dummy,
                                    metal_prefix="Metal")
    m1 = cfg["layers"][0]
    assert "fill_datatype" not in m1
    assert m1.get("fill_on_drawn") is True


def test_no_routing_metal_returns_none():
    assert G.build_metal_fill_config("", "", "", metal_prefix="Metal") is None

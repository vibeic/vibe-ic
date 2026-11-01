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
import json
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo

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


_PRL = """SPACINGTABLE
  PARALLELRUNLENGTH 0 1 900
  WIDTH 0 0.21 0.23 0.25
  WIDTH 800 0.31
    0.51 0.71 ;"""

_INFLUENCE = """SPACINGTABLE INFLUENCE
  WIDTH 0 WITHIN 700 SPACING 0.41
  WIDTH 800 WITHIN 900 SPACING 0.81 ;"""


def _routing_layer(name, rules, width="WIDTH 0.22 ;"):
    return f"LAYER {name}\n TYPE ROUTING ;\n {width}\n {rules}\nEND {name}\n"


@pytest.mark.parametrize("rules, expected", [
    (_PRL, 0.71),
    (_INFLUENCE, 0.81),
    ("SPACING 0.32 ;\n" + _PRL, 0.71),
    (_PRL + "\nSPACING 0.92 ;", 0.92),
    (_PRL + "\n" + _INFLUENCE, 0.81),
    ("SPACINGTABLE PARALLELRUNLENGTH 0 1e3 WIDTH 0 +2.1e-1 .72 ;", 0.72),
])
def test_table_spacing_uses_all_cells_but_no_axes(rules, expected):
    lef = _routing_layer("Metal1", rules)
    assert G.parse_techlef_routing(lef, "Metal") == {"metal1": (0.22, expected)}
    cfg = G.build_metal_fill_config("Metal1 NET 71 0", lef, "")
    assert cfg["layers"][0]["space"] == expected
    assert cfg["layers"][0]["space_to_metal"] == expected


def test_only_standalone_width_and_uncommented_rules_are_used():
    rules = """MINIMUMCUT 2 WIDTH 0.001 ;
      # WIDTH 0.0001 ; SPACING 999 ;
      SPACING 0.27 ;
    """ + _PRL
    assert G.parse_techlef_routing(_routing_layer("Metal1", rules), "Metal") == {
        "metal1": (0.22, 0.71)}


@pytest.mark.parametrize("prefix", [None, "Metal"])
def test_builder_selects_routing_type_then_joins_exact_streamout_names(prefix):
    lef = "".join(_routing_layer(n, "SPACING 0.37 ;") for n in (
        "Metal1", "TopMetal1", "TopMetal2", "Crown"))
    lef += "LAYER Metal9\n TYPE CUT ;\n WIDTH 0.01 ;\n SPACING 0.01 ;\nEND Metal9\n"
    lm = """metal1 NET 71 0
TOPMETAL1 PIN 72 10
TopMetal1 NET 72 0
topmetal2 NET 73 0
cRoWn NET 74 0
Metal9 CUT 79 0
Other NET 80 0
"""
    cfg = G.build_metal_fill_config(lm, lef, "", metal_prefix=prefix)
    assert {s["name"]: s["layer"] for s in cfg["layers"]} == {
        "metal1": [71, 0], "topmetal1": [72, 0],
        "topmetal2": [73, 0], "crown": [74, 0]}


def test_routing_names_need_no_derived_stem():
    lef = _routing_layer("Crown", _PRL)
    cfg = G.build_metal_fill_config("CROWN NET 74 0", lef, "")
    assert cfg["layers"][0]["name"] == "crown"
    assert cfg["layers"][0]["space"] == 0.71


@pytest.mark.parametrize("layout", ["header", "compact", "single"])
def test_routing_inventory_does_not_depend_on_line_breaks(layout):
    lower = _routing_layer("Metal1", "SPACING 0.3 ;")
    upper = _routing_layer("Crown", "SPACING 0.6 ;", "WIDTH 0.4 ;")
    lef = lower + upper.replace("Crown\n TYPE", "Crown TYPE")
    expected = {"metal1": [71, 0], "crown": [74, 0]}
    if layout == "compact":
        lef = " ".join(lef.split())
    elif layout == "single":
        lef = " ".join(upper.split())
        expected = {"crown": [74, 0]}
    cfg = G.build_metal_fill_config("Metal1 NET 71 0\nCROWN NET 74 0", lef, "")
    assert {rule["name"]: rule["layer"] for rule in (cfg or {}).get("layers", [])} == expected


@pytest.mark.parametrize("missing", ["WIDTH", "SPACING", "mapping"])
def test_inline_routing_layer_with_missing_input_is_named(missing):
    width = "" if missing == "WIDTH" else "WIDTH 0.4 ;"
    spacing = "" if missing == "SPACING" else "SPACING 0.6 ;"
    upper = _routing_layer("Crown", spacing, width).replace("Crown\n TYPE", "Crown TYPE")
    lef = _routing_layer("Metal1", "SPACING 0.3 ;") + upper
    mapping = "Metal1 NET 71 0" + ("" if missing == "mapping" else "\nCROWN NET 74 0")
    with pytest.raises(ValueError, match=rf"Crown.*{missing}"):
        G.build_metal_fill_config(mapping, lef, "")


def test_routing_inventory_ignores_geometry_references_and_quoted_layer_words():
    lef = _routing_layer("Metal1", 'SPACING 0.3 ;\n PROPERTY note "LAYER Ghost TYPE ROUTING ;" ;')
    lef += "MACRO Cell PIN A PORT LAYER Metal1 ; RECT 0 0 1 1 ; END END A END Cell"
    assert G.parse_techlef_routing(lef, "Metal") == {"metal1": (0.22, 0.3)}


def test_arbitrary_routing_name_keeps_deck_declared_regions():
    deck = """crown_drawn = input(74, 0)
blocked = input(95, 0)
crown_drawn.separation(blocked, 4.7.um)
"""
    cfg = G.build_metal_fill_config("CROWN NET 74 0", _routing_layer("Crown", _PRL), deck)
    assert cfg["keepout_layers"] == [[95, 0, 4.7]]


@pytest.mark.parametrize("selected", [True, False])
def test_arbitrary_routing_keepout_follows_selected_dummy_datatype(selected):
    lef = _routing_layer("Crown", "SPACING 0.3 ;")
    left = "crown_dummy" if selected else "crown_fill"
    deck = ("crown_dummy = input(74, 7)\ncrown_fill = input(74, 9)\n"
            "blocked = input(95, 0)\n"
            f"{left}.separation(blocked, 4.7.um).output('gap', 'gap')\n")
    cfg = G.build_metal_fill_config("CROWN NET 74 0", lef, deck)
    assert cfg["layers"][0]["fill_datatype"] == 7
    assert cfg["keepout_layers"] == ([[95, 0, 4.7]] if selected else [])


@pytest.mark.parametrize("preceding", ["SPACING 0.2", "AREA 0.1"])
def test_missing_semicolon_cannot_hide_scalar_spacing(preceding):
    lef = _routing_layer("Metal1", preceding + "\n SPACING 0.9 ;\n SPACING 0.2 ;")
    with pytest.raises(ValueError, match="Metal1.*SPACING"):
        G.build_metal_fill_config("Metal1 NET 71 0", lef, "")


def test_explicit_prefix_keeps_all_declared_routing_layers():
    lef = _routing_layer("Metal1", _PRL) + _routing_layer("TopMetal1", _INFLUENCE)
    assert G.parse_techlef_routing(lef, "Metal") == {
        "metal1": (0.22, 0.71), "topmetal1": (0.22, 0.81)}


@pytest.mark.parametrize("rules, width, missing", [
    ("", "WIDTH 0.22 ;", "SPACING"),
    (_PRL, "MINIMUMCUT 2 WIDTH 0.01 ;", "WIDTH"),
])
def test_nonderivable_routing_layer_is_named_for_parser_and_builder(rules, width, missing):
    lef = _routing_layer("Metal1", "SPACING 0.25 ;")
    lef += _routing_layer("Metal2", rules, width)
    with pytest.raises(ValueError, match=rf"Metal2.*{missing}"):
        G.parse_techlef_routing(lef, "Metal")
    with pytest.raises(ValueError, match=rf"Metal2.*{missing}"):
        G.build_metal_fill_config("Metal1 NET 71 0\nMetal2 NET 72 0", lef, "")


@pytest.mark.parametrize("table", [
    "SPACINGTABLE PARALLELRUNLENGTH 0 1 WIDTH 0 0.2 ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 1 WIDTH 0 0.2 0.3 0.4 ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 1 ;",
    "SPACINGTABLE INFLUENCE WIDTH 0 WITHIN 0.3 ;",
    "SPACINGTABLE INFLUENCE WIDTH 0 WITHIN 1 SPACING 0.2 0.3 ;",
    "SPACINGTABLE TWOWIDTHS WIDTH 0 PRL 0 0.2 ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 NaN ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 -0.2 ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 1e999 ;",
    "SPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 0.2",
    "SPACING 0.27\nSPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 0.9 ;",
    "AREA 0.1\nSPACINGTABLE PARALLELRUNLENGTH 0 WIDTH 0 0.9 ;",
])
def test_malformed_or_unsupported_table_refuses_by_layer_even_with_numeric_spacing(table):
    lef = _routing_layer("Metal1", "SPACING 0.27 ;\n" + table)
    with pytest.raises(ValueError, match="Metal1.*SPACINGTABLE"):
        G.build_metal_fill_config("Metal1 NET 71 0", lef, "")


def test_missing_routing_drawn_mapping_refuses_by_layer():
    lef = _routing_layer("Metal1", "SPACING 0.25 ;")
    lef += _routing_layer("Crown", _PRL)
    with pytest.raises(ValueError, match="Crown.*(?:map|GDS|drawn)"):
        G.build_metal_fill_config("Metal1 NET 71 0\nCrown PIN 74 10", lef, "")


def _cli_args(tmp_path, lef):
    lm, tl, deck = (tmp_path / name for name in ("layers.map", "tech.lef", "deck.drc"))
    lm.write_text("Metal1 NET 71 0\nMetal2 NET 72 0")
    tl.write_text(lef)
    deck.write_text("")
    out = tmp_path / "fill.json"
    return ["--layermap", str(lm), "--techlef", str(tl),
            "--deck", str(deck), "--out", str(out)], out


@pytest.mark.parametrize("existing", [False, True])
def test_cli_names_missing_spacing_without_publishing_partial_config(tmp_path, capsys, existing):
    lef = _routing_layer("Metal1", _PRL) + _routing_layer("Metal2", "")
    args, out = _cli_args(tmp_path, lef)
    if existing:
        out.write_text("previous config")
    assert G.main(args) == 2
    captured = capsys.readouterr()
    assert "Metal2" in captured.err and "SPACING" in captured.err
    assert captured.out == ""
    assert out.read_text() == "previous config" if existing else not out.exists()


def test_cli_publishes_table_only_config(tmp_path, capsys):
    args, out = _cli_args(tmp_path, _routing_layer("Metal1", _PRL))
    assert G.main(args) == 0
    cfg = json.loads(out.read_text())
    assert cfg["layers"][0]["space"] == 0.71
    assert json.loads(capsys.readouterr().out) == cfg


@pytest.mark.parametrize("table", [False, True])
def test_checked_in_density_fill_techlef_remains_supported(table):
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "flow109_density_fill", "tech.lef")
    lef = path.read_text()
    if table:
        lef = lef.replace("SPACING 0.2 ;", _PRL)
    cfg = G.build_metal_fill_config("M1 NET 77 0", lef, "")
    assert cfg["layers"][0]["layer"] == [77, 0]
    assert cfg["layers"][0]["space"] == (0.71 if table else 0.2)


_NUMERIC_CFG_JSON = {
    "met": """{
  "boundary_layer": null,
  "window_um": null,
  "keepout_layers": [],
  "max_passes": 8,
  "mfg_grid_um": 0.01,
  "fill_datatype": null,
  "layers": [
    {
      "name": "met1",
      "layer": [
        61,
        0
      ],
      "target": 0.35,
      "max": 0.95,
      "space": 1.0,
      "space_to_metal": 2.5,
      "width": 3.44,
      "fill_datatype": 7
    },
    {
      "name": "met2",
      "layer": [
        62,
        0
      ],
      "target": 0.35,
      "max": 0.95,
      "space": 1.0,
      "space_to_metal": 2.5,
      "width": 3.44,
      "fill_datatype": 7
    }
  ],
  "_derivation": {
    "source": "metal_fill_config_gen (chip-AGNOSTIC; PDK-declared files)",
    "metal_prefix": "met",
    "metal_prefix_derived_from_techlef": true,
    "density_floor_pct": null,
    "target_density": 0.35,
    "mfg_grid_um": 0.01,
    "dummy_space_um": 1.0,
    "dummy_to_circuit_space_um": 2.5,
    "layers_derived": 2,
    "dummy_datatype_found": 2,
    "keepout_layers_derived": 0,
    "density_rules_covered": {},
    "density_rules_without_fill_entry": {},
    "keepout_layer_names": []
  }
}""",
    "Metal": """{
  "boundary_layer": null,
  "window_um": null,
  "keepout_layers": [],
  "max_passes": 8,
  "mfg_grid_um": 0.01,
  "fill_datatype": null,
  "layers": [
    {
      "name": "metal1",
      "layer": [
        61,
        0
      ],
      "target": 0.38,
      "max": 0.95,
      "space": 1.0,
      "space_to_metal": 2.5,
      "width": 3.7,
      "fill_datatype": 7
    },
    {
      "name": "metal2",
      "layer": [
        62,
        0
      ],
      "target": 0.38,
      "max": 0.95,
      "space": 1.0,
      "space_to_metal": 2.5,
      "width": 3.7,
      "fill_datatype": 7
    }
  ],
  "_derivation": {
    "source": "metal_fill_config_gen (chip-AGNOSTIC; PDK-declared files)",
    "metal_prefix": "Metal",
    "metal_prefix_derived_from_techlef": true,
    "density_floor_pct": 33.0,
    "target_density": 0.38,
    "mfg_grid_um": 0.01,
    "dummy_space_um": 1.0,
    "dummy_to_circuit_space_um": 2.5,
    "layers_derived": 2,
    "dummy_datatype_found": 2,
    "keepout_layers_derived": 0,
    "density_rules_covered": {},
    "density_rules_without_fill_entry": {},
    "keepout_layer_names": []
  }
}""",
}


@pytest.mark.parametrize("stem", ["met", "Metal"])
def test_numeric_spacing_config_json_is_byte_identical_to_base(stem):
    deck = _DECK
    for n in ("1", "2"):
        deck = deck.replace("metal" + n, stem.lower() + n).replace("Metal" + n, stem + n)
    cfg = G.build_metal_fill_config(_LAYERMAP.replace("Metal", stem),
                                    _TECHLEF.replace("Metal", stem), deck)
    assert json.dumps(cfg, indent=2) == _NUMERIC_CFG_JSON[stem]

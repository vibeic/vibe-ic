"""#170 (A10) — for a custom PDK without a foundry streamout map, KLayout
streamout landed pure-annotation geometry (per-instance cell OUTLINE boxes, DEF
REGIONS, placement BLOCKAGES) on auto-assigned low GDS numbers that collide with
the deck's reserved FEOL device layers (spm/ASAP7: ~323 stray items on 8/0, 9/0,
10/0 near the west pins). The fix (a) carries BLOCKAGE+FILL on the routing
layer's own deck number in the synthesized map, and (b) disables the three
annotation producers in the KLayout DEF reader — but ONLY for the deck-
synthesized `*_streamout_synth.map`, so sky130/nangate/declared-map streamout is
byte-identical.
"""
import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


_DECK = """\
LAYER FOO1 1000
LAYER MAP 20 DATATYPE 0 1000
LAYER CUT1 1001
LAYER MAP 21 DATATYPE 0 1001
"""
_LEF = """\
LAYER FOO1
  TYPE ROUTING ;
END FOO1
LAYER CUT1
  TYPE CUT ;
END CUT1
"""


def test_routing_line_carries_blockage_and_fill(tmp_path):
    (tmp_path / "D.rule").write_text(_DECK)
    (tmp_path / "t.lef").write_text(_LEF)
    mp, _ = R._synthesize_streamout_layermap(
        str(tmp_path / "D.rule"), str(tmp_path / "t.lef"), tmp_path / "s")
    body = Path(mp).read_text()
    routing_line = next(l for l in body.splitlines()
                        if l.startswith("FOO1") and "NET" in l)
    # blockage + fill share the routing layer's deck number (20), not an
    # auto-assigned FEOL-colliding number.
    assert "BLOCKAGE" in routing_line and "FILL" in routing_line
    toks = routing_line.split()
    assert toks[-2:] == ["20", "0"]
    # still the KLayout 4-token map shape.
    assert len(toks) >= 4 and toks[-1].isdigit() and toks[-2].isdigit()


def test_streamout_disables_annotation_producers_for_synth_map_only():
    src = R._GDS_STREAMOUT_PY
    # the embedded klayout script is valid python.
    ast.parse(src)
    # the three annotation producers are disabled …
    for flag in ("produce_cell_outlines", "produce_regions",
                 "produce_placement_blockages"):
        assert flag in src
    # … and the disabling is GATED on the deck-synthesized map basename, so
    # sky130/nangate/declared foundry maps are untouched.
    assert "_streamout_synth.map" in src
    # routing/via/pin producers are NOT disabled (no real geometry dropped).
    for kept in ("produce_via_geometry", "produce_pins", "produce_routing"):
        assert f"{kept}, False" not in src and f"{kept}=False" not in src

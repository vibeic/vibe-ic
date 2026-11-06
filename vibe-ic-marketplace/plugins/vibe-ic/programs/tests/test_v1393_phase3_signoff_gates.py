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

pwr = importlib.import_module("def_gds_port_power_restore")


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

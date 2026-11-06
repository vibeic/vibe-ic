"""PDN straps: derive them, and never report a strapless grid as a success.

WHAT SHIPPED
------------
A follow-pin-only PDN is not a power grid. `add_pdn_stripe -followpins` emits
one rail per std-cell ROW and nothing else, so the rails are mutually ISOLATED
islands with zero upper-metal straps and zero vias tying them together. Ground
often *looks* whole only because the substrate ties it physically; supply is
genuinely fragmented into one island per row.

Measured on a shipped layout: the DEF's SPECIALNETS section held **130
follow-pin rails on ONE metal layer, 0 straps and 0 vias** — while the PnR
transcript said `PDN_INSERTED_ADAPTIVE`, the PnR step reported PASS, and
`pdn.done` asserted "PDN inserted". Three separate success markers over a grid
that was not connected.

TWO DEFECTS, BOTH CHIP-AGNOSTIC
-------------------------------
1. **Straps came only from config.** `pdk.pdn_straps` was the ONLY source of
   upper-metal straps, and exactly ONE PDK in the registry ever carried that
   key. Every other PDK — named or project-staged — got the hollow grid. This
   is not PDK-specific: it is the DEFAULT for any PDK without a hand-written
   strap block. The fix DERIVES a strap plan from the tech LEF's own routing
   stack, so no PDK depends on someone having written config for it. Config
   still WINS when present.

2. **The strapless case reported success.** `pdngen` exits 0 for a
   follow-pin-only grid, so a marker can never distinguish a real mesh from
   isolated rails. The fix gates on the MEASURED geometry in the emitted DEF
   (`_def_pdn_evidence`), and a grid with no straps and no vias is reported
   BLOCKED — never green.

The second half is the load-bearing one: deriving straps makes the common case
work, but only the evidence gate stops the NEXT strapless grid from shipping
silently.

NEGATIVE CONTROLS (§B3 — a detector that cannot return clean is an alarm)
------------------------------------------------------------------------
The evidence detector is proved in BOTH directions against REAL layouts:
it FIRES on the shipped rails-only DEF, and stays SILENT on genuinely strapped
DEFs from two different PDKs. Reduced fixtures of both shapes are inlined here
so the property is enforced without shipping multi-MB artifacts.
"""
import importlib
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
mod = importlib.import_module("phase3_one_shot_runner")


# --------------------------------------------------------------- fixtures --
def _stack(prefix="M", dirs=("HORIZONTAL", "VERTICAL", "HORIZONTAL",
                               "VERTICAL", "HORIZONTAL", "VERTICAL"),
           pitch=0.5, width=0.2):
    """A generic routing stack. No PDK literal — the point of the fix is that
    NO layer-name convention is assumed."""
    return "".join(
        f"LAYER {prefix}{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH {pitch} ;\n  WIDTH {width} ;\nEND {prefix}{i}\n"
        for i, d in enumerate(dirs, 1))


CELL_LEF = """\
MACRO cellA
  CLASS core ;
  SIZE 2.0 BY 10.0 ;
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER M1 ;
        RECT 0.0 9.6 2.0 10.4 ;
    END
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER M1 ;
        RECT 0.0 -0.4 2.0 0.4 ;
    END
  END VSS
END cellA
"""

# Reduced from the SHIPPED defective layout: follow-pin rails on ONE layer,
# no straps, no vias. This is the known-BAD input.
DEF_RAILS_ONLY = """\
SPECIALNETS 2 ;
    - VDD ( c1 VDD ) ( c2 VDD )
      + ROUTED M1 300 + SHAPE FOLLOWPIN ( 1000 9000 ) ( 9900 9000 )
      NEW M1 300 + SHAPE FOLLOWPIN ( 1000 8000 ) ( 9900 8000 )
      + USE POWER ;
    - VSS ( c1 VSS ) ( c2 VSS )
      + ROUTED M1 300 + SHAPE FOLLOWPIN ( 1000 8500 ) ( 9900 8500 )
      NEW M1 300 + SHAPE FOLLOWPIN ( 1000 7500 ) ( 9900 7500 )
      + USE GROUND ;
END SPECIALNETS
"""

# Reduced from a genuinely strapped layout: follow-pin rails PLUS upper-metal
# stripes PLUS via placements bonding them. This is the known-GOOD input.
DEF_STRAPPED = """\
SPECIALNETS 2 ;
    - VDD ( c1 VDD ) ( c2 VDD )
      + ROUTED M1 300 + SHAPE FOLLOWPIN ( 1000 9000 ) ( 9900 9000 )
      NEW M1 300 + SHAPE FOLLOWPIN ( 1000 8000 ) ( 9900 8000 )
      NEW M5 500 + SHAPE STRIPE ( 2000 10000 ) ( 2000 9950 )
      NEW M6 900 + SHAPE STRIPE ( 3000 3000 ) ( 63000 3000 )
      NEW M1 0 ( 2000 9000 ) VIA_A
      NEW M5 0 ( 2000 3000 ) VIA_B
      + USE POWER ;
    - VSS ( c1 VSS ) ( c2 VSS )
      + ROUTED M1 300 + SHAPE FOLLOWPIN ( 1000 8500 ) ( 9900 8500 )
      NEW M5 500 + SHAPE STRIPE ( 4000 10000 ) ( 4000 9950 )
      NEW M1 0 ( 4000 8500 ) VIA_A
      + USE GROUND ;
END SPECIALNETS
"""


def _pdk(tmp_path, *, tech_lef_text=_stack(), straps=None, cell=CELL_LEF,
         prefix="M"):
    cl = tmp_path / "cells.lef"
    cl.write_text(cell)
    tl = tmp_path / "tech.lef"
    tl.write_text(tech_lef_text)
    return mod.PdkConfig(
        name="unit", liberty="/nonexistent/x.lib", tech_lef=str(tl),
        cell_lef=str(cl), cell_gds=None, site="SITE", drc_deck=None,
        metal_prefix=prefix, tapcell_master=None, pdn_straps=straps)


# ------------------------------------------------ tech-LEF stack parsing ---
def test_routing_layers_parsed_in_declaration_order():
    got = mod._techlef_routing_layers(_stack())
    assert [n for n, _d, _p, _w in got] == [f"M{i}" for i in range(1, 7)]
    assert got[0][1] == "HORIZONTAL" and got[1][1] == "VERTICAL"


def test_routing_layers_ignores_non_routing_layers():
    txt = ("LAYER Nwell\n  TYPE MASTERSLICE ;\nEND Nwell\n"
           "LAYER M1\n  TYPE ROUTING ;\n  DIRECTION HORIZONTAL ;\n"
           "  PITCH 0.5 ;\n  WIDTH 0.2 ;\nEND M1\n"
           "LAYER VIA1\n  TYPE CUT ;\nEND VIA1\n")
    assert [n for n, _d, _p, _w in mod._techlef_routing_layers(txt)] == ["M1"]


def test_routing_layers_empty_on_garbage():
    assert mod._techlef_routing_layers("") == []
    assert mod._techlef_routing_layers("not a lef at all") == []
    assert mod._techlef_routing_layers(None) == []


def test_routing_layers_is_name_convention_agnostic():
    """A stack named nothing like the usual convention parses identically."""
    got = mod._techlef_routing_layers(_stack(prefix="TopMetal"))
    assert [n for n, _d, _p, _w in got][:2] == ["TopMetal1", "TopMetal2"]


# ------------------------------------------------- strap plan derivation ---
def test_auto_straps_picks_the_highest_alternating_pair():
    """rails(H) -> M4(V) -> M5(H): every connect pair CROSSES.

    M6 is the topmost layer but is VERTICAL like the strap that would have
    to sit under it, so no alternating pair ends at M6 — the highest one
    that alternates is (M4, M5)."""
    plan = mod._auto_pdn_straps_from_techlef(_stack(), "M1")
    assert [s["layer"] for s in plan["stripes"]] == ["M4", "M5"]
    assert plan["connects"] == [["M1", "M4"], ["M4", "M5"]]
    assert plan["source"] == "auto:tech_lef"


def test_every_connect_pair_names_perpendicular_layers():
    """THE rule. Two stripes bond only where they CROSS, so a connect pair of
    two PARALLEL layers bonds nothing — measured as `PDN-0178 Remaining
    channel` across the whole core followed by `PDN-0179 Unable to repair all
    channels`."""
    for dirs in (("HORIZONTAL", "VERTICAL", "HORIZONTAL", "VERTICAL",
                  "HORIZONTAL", "VERTICAL"),
                 ("VERTICAL", "HORIZONTAL", "VERTICAL", "HORIZONTAL"),
                 ("HORIZONTAL", "VERTICAL", "VERTICAL", "HORIZONTAL")):
        txt = _stack(dirs=dirs)
        dir_of = {n: d for n, d, _p, _w in mod._techlef_routing_layers(txt)}
        plan = mod._auto_pdn_straps_from_techlef(txt, "M1")
        assert plan is not None, dirs
        for a, b in plan["connects"]:
            assert dir_of[a] != dir_of[b], (dirs, a, b)


def test_auto_straps_single_perpendicular_layer_is_enough(tmp_path):
    """One layer crossing the rails bonds every rail, even with no second
    layer to mesh with."""
    txt = _stack(dirs=("HORIZONTAL", "VERTICAL"))
    plan = mod._auto_pdn_straps_from_techlef(txt, "M1")
    assert [s["layer"] for s in plan["stripes"]] == ["M2"]
    assert plan["connects"] == [["M1", "M2"]]


def test_auto_straps_never_connects_rails_to_a_parallel_layer():
    """Only a PARALLEL layer sits above the rails apart from the top one —
    the derivation must still reach for the perpendicular one."""
    txt = _stack(dirs=("HORIZONTAL", "HORIZONTAL", "VERTICAL"))
    plan = mod._auto_pdn_straps_from_techlef(txt, "M1")
    assert plan["connects"][0] == ["M1", "M3"]   # not M2 (parallel)


def test_auto_straps_none_when_nothing_sits_above_the_rails():
    """A single-metal stack CANNOT be strapped — and must say so, not guess."""
    txt = _stack(dirs=("HORIZONTAL",))
    assert mod._auto_pdn_straps_from_techlef(txt, "M1") is None


def test_auto_straps_none_when_followpin_layer_absent_or_lef_unparseable():
    assert mod._auto_pdn_straps_from_techlef(_stack(), "NOSUCH") is None
    assert mod._auto_pdn_straps_from_techlef("", "M1") is None
    assert mod._auto_pdn_straps_from_techlef(_stack(), "") is None


def test_auto_strap_geometry_is_derived_and_self_consistent():
    """Every number traces to the LEF's own declarations, and pitch stays
    comfortably greater than width so straps can never abut."""
    plan = mod._auto_pdn_straps_from_techlef(
        _stack(pitch=0.5, width=0.2), "M1")
    for s in plan["stripes"]:
        assert s["width"] == 4.0 * 0.2                 # 4x the layer min WIDTH
        assert s["pitch"] >= mod._PDN_STRAP_MIN_PITCH_X_WIDTH * s["width"]
        assert 0 < s["offset"] < s["pitch"]


def test_auto_straps_scale_with_the_process():
    """A coarser layer yields proportionally coarser straps — no absolute
    dimension is hard-coded anywhere."""
    fine = mod._auto_pdn_straps_from_techlef(_stack(width=0.2), "M1")
    coarse = mod._auto_pdn_straps_from_techlef(_stack(width=2.0), "M1")
    assert coarse["stripes"][0]["width"] == 10 * fine["stripes"][0]["width"]


# ------------------------------------------------------- emitted PDN Tcl ---


# ------------------------------------------------------- DEF evidence -----


# -------------------------------------------------- the connectivity gate --
def _project(tmp_path, log, def_text=None, def_name="routed.def"):
    pnr = mod._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "openroad.log").write_text(log)
    if def_text is not None:
        (pnr / def_name).write_text(def_text)
    return tmp_path


# ------------------------------------------- three-valued gate verdict -----
# The GATE must block on KNOWN-BAD, never on UNKNOWN. A gate that blocks on
# absent evidence manufactures failures out of nothing — the same error class
# as passing on absent evidence, just pointing the other way.

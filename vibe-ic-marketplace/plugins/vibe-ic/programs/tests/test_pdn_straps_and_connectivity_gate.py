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
def test_pdn_emits_straps_and_connects_without_any_config(tmp_path):
    """THE DEFECT: this used to emit follow-pins ONLY and claim success."""
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    # Round 15: every core strap layer ALSO carries a strap group for the
    # design's SECONDARY supplies (`-nets $_sec_pwr`), emitted behind a
    # runtime fit check and inert on a design with none. The primary count
    # is unchanged: follow-pins + two strap layers.
    primary = [ln for ln in tcl.splitlines()
               if "add_pdn_stripe" in ln and "$_sec_pwr" not in ln]
    secondary = [ln for ln in tcl.splitlines()
                 if "add_pdn_stripe" in ln and "$_sec_pwr" in ln]
    assert len(primary) == 3                     # follow-pins + two strap layers
    assert len(secondary) == 2                   # one per strap layer
    assert all("-extend_to_boundary" in ln for ln in secondary)
    assert tcl.count("add_pdn_connect") == 2     # rails->lower->upper via stacks
    assert "-followpins" in tcl
    assert "PDN_INSERTED_ADAPTIVE" in tcl
    assert "straps(auto:M4,M5)" in tcl
    assert "PDN_NO_STRAPS" not in tcl


def test_declared_config_wins_over_derivation(tmp_path):
    """A PDK shipping tuned IR-drop geometry keeps it — derivation is only a
    fallback for PDKs that declare none."""
    straps = {"stripes": [{"layer": "TopMetal1", "width": 2.2, "pitch": 75.6,
                           "offset": 13.6}],
              "connects": [["M1", "TopMetal1"]]}
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, straps=straps))
    assert ("add_pdn_stripe -grid grid -layer TopMetal1 -width 2.2 "
            "-pitch 75.6 -offset 13.6") in tcl
    assert "add_pdn_connect -grid grid -layers {M1 TopMetal1}" in tcl
    assert "M5" not in tcl and "M6" not in tcl   # derivation did not fire
    assert "auto:" not in tcl


def test_unstrappable_pdk_refuses_to_claim_success(tmp_path):
    """THE SECOND DEFECT: silence is what let the hollow grid ship."""
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, tech_lef_text=_stack(
        dirs=("HORIZONTAL",))))
    assert "PDN_NO_STRAPS" in tcl
    assert "PDN_INSERTED_ADAPTIVE" not in tcl
    assert "ISOLATED" in tcl and "NOT a usable power grid" in tcl


def test_no_straps_marker_names_the_reason(tmp_path):
    """Three different problems with three different fixes must not collapse
    into one message: an UNREADABLE tech LEF, a readable one declaring no
    routing layers, and a genuinely single-metal stack."""
    empty = mod._build_pdn_tcl(_pdk(tmp_path, tech_lef_text=""))
    assert "PDN_NO_STRAPS" in empty
    assert "no parseable TYPE ROUTING" in empty

    flat = mod._build_pdn_tcl(
        _pdk(tmp_path, tech_lef_text=_stack(dirs=("HORIZONTAL",))))
    assert "no routing layer above M1" in flat

    cl = tmp_path / "cells.lef"
    cl.write_text(CELL_LEF)
    missing = mod._build_pdn_tcl(mod.PdkConfig(
        name="unit", liberty="/x.lib", tech_lef="/nonexistent/x.tlef",
        cell_lef=str(cl), cell_gds=None, site="SITE", drc_deck=None,
        metal_prefix="M", tapcell_master=None))
    assert "tech LEF unreadable" in missing


def test_sky130_style_branch_is_untouched():
    """The hard-coded branch already emitted straps and must not change."""
    pdk = mod.PdkConfig(
        name="sky130A", liberty="/x.lib", tech_lef="/x.tlef",
        cell_lef="/x.lef", cell_gds=None, site="unit", drc_deck=None,
        metal_prefix="met", tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1")
    tcl = mod._build_pdn_tcl(pdk)
    assert "PDN_INSERTED:" in tcl
    assert "add_pdn_connect -grid grid -layers {met1 met4}" in tcl
    assert "PDN_NO_STRAPS" not in tcl


def test_pdn_skipped_when_no_pg_pins_discoverable(tmp_path):
    cl = tmp_path / "nopg.lef"
    cl.write_text("MACRO X\n  SIZE 1 BY 1 ;\nEND X\n")
    pdk = mod.PdkConfig(
        name="unit", liberty="/x.lib", tech_lef="/x.tlef", cell_lef=str(cl),
        cell_gds=None, site="unit", drc_deck=None, metal_prefix="M",
        tapcell_master=None)
    assert "PDN_SKIPPED" in mod._build_pdn_tcl(pdk)


# ------------------------------------------------------- DEF evidence -----
def test_evidence_FIRES_on_the_shipped_rails_only_def():
    """KNOWN-BAD. Mirrors the shipped layout: rails on one layer, nothing else."""
    ev = mod._def_pdn_evidence(DEF_RAILS_ONLY)
    assert ev["parsed"] is True
    assert ev["followpin"] == 4
    assert ev["stripe"] == 0 and ev["ring"] == 0
    assert ev["vias"] == 0
    assert ev["layers"] == ["M1"]


def test_evidence_is_SILENT_on_a_strapped_def():
    """KNOWN-GOOD. A detector that cannot return clean is an alarm, not a
    detector — this is the half that is easy to skip and dangerous to."""
    ev = mod._def_pdn_evidence(DEF_STRAPPED)
    assert ev["parsed"] is True
    assert ev["stripe"] == 3
    assert ev["vias"] == 3
    assert ev["layers"] == ["M1", "M5", "M6"]


def test_evidence_does_not_mistake_keywords_for_via_names():
    """`NEW`/`SHAPE`/`USE` follow coordinates constantly; counting them as vias
    would make every rails-only DEF look strapped."""
    ev = mod._def_pdn_evidence(DEF_RAILS_ONLY)
    assert ev["vias"] == 0


def test_evidence_reports_not_parsed_without_a_specialnets_section():
    """Absent evidence is NOT evidence of absence — the caller must be able to
    tell 'no section' from 'empty section'."""
    ev = mod._def_pdn_evidence("DESIGN top ;\nEND DESIGN\n")
    assert ev["parsed"] is False
    assert mod._def_pdn_evidence("")["parsed"] is False
    assert mod._def_pdn_evidence(None)["parsed"] is False


# -------------------------------------------------- the connectivity gate --
def _project(tmp_path, log, def_text=None, def_name="routed.def"):
    pnr = mod._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "openroad.log").write_text(log)
    if def_text is not None:
        (pnr / def_name).write_text(def_text)
    return tmp_path


def test_gate_overturns_a_success_marker_the_def_contradicts(tmp_path):
    """THE WHOLE POINT. The log said the grid went in; the geometry says it
    did not. The geometry wins."""
    p = _project(tmp_path, "PDN_INSERTED_ADAPTIVE: M1 follow-pins\n",
                 DEF_RAILS_ONLY)
    ok, why = mod._pnr_pdn_status(p)
    assert ok is False
    assert "DEF DISAGREES" in why
    assert "0 straps and 0 vias" in why
    assert "ISOLATED" in why


def test_gate_passes_when_the_def_confirms_the_marker(tmp_path):
    p = _project(tmp_path, "PDN_INSERTED_ADAPTIVE: M1 follow-pins\n",
                 DEF_STRAPPED)
    assert mod._pnr_pdn_status(p) == (True, "PDN_INSERTED_ADAPTIVE")


def test_gate_fail_safe_leaves_the_marker_standing_without_evidence(tmp_path):
    """A missing DEF must not manufacture a failure out of absent evidence —
    the geometry may only OVERTURN a marker, never invent a verdict."""
    p = _project(tmp_path, "PDN_INSERTED_ADAPTIVE: M1 follow-pins\n")
    assert mod._pnr_pdn_status(p) == (True, "PDN_INSERTED_ADAPTIVE")
    p2 = _project(tmp_path / "b", "PDN_INSERTED: met1 + met4/met5 stripes\n",
                  "DESIGN top ;\nEND DESIGN\n")
    assert mod._pnr_pdn_status(p2) == (True, "PDN_INSERTED")


def test_gate_reports_the_new_no_straps_marker(tmp_path):
    p = _project(tmp_path, "PDN_NO_STRAPS: M1 follow-pins ... ISOLATED\n")
    assert mod._pnr_pdn_status(p) == (False, "PDN_NO_STRAPS")


def test_gate_preserves_the_pre_existing_negative_markers(tmp_path):
    for marker, expect in (("PDN_NONFATAL: boom", "PDN_NONFATAL"),
                           ("PDN_SKIPPED: no PDK config", "PDN_SKIPPED")):
        p = _project(tmp_path / marker[:6], marker + "\n", DEF_STRAPPED)
        ok, why = mod._pnr_pdn_status(p)
        assert ok is False and why == expect


def test_gate_reports_no_marker_when_the_log_has_none(tmp_path):
    p = _project(tmp_path, "nothing about power here\n", DEF_STRAPPED)
    assert mod._pnr_pdn_status(p) == (False, "no PDN insertion marker")


# ------------------------------------------- three-valued gate verdict -----
# The GATE must block on KNOWN-BAD, never on UNKNOWN. A gate that blocks on
# absent evidence manufactures failures out of nothing — the same error class
# as passing on absent evidence, just pointing the other way.
def test_verdict_BAD_when_the_def_contradicts_a_success_marker(tmp_path):
    p = _project(tmp_path, "PDN_INSERTED_ADAPTIVE: M1 follow-pins\n",
                 DEF_RAILS_ONLY)
    verdict, why = mod._pnr_pdn_grid_verdict(p)
    assert verdict == "BAD"
    assert "DEF DISAGREES" in why


def test_verdict_BAD_on_each_positive_failure_marker(tmp_path):
    for i, log in enumerate(("PDN_NO_STRAPS: ... ISOLATED\n",
                             "PDN_NONFATAL: pdngen threw\n",
                             "PDN_SKIPPED: no PDK config\n")):
        p = _project(tmp_path / f"m{i}", log)
        assert mod._pnr_pdn_grid_verdict(p)[0] == "BAD", log


def test_verdict_OK_when_the_def_confirms_the_marker(tmp_path):
    p = _project(tmp_path, "PDN_INSERTED_ADAPTIVE: M1\n", DEF_STRAPPED)
    assert mod._pnr_pdn_grid_verdict(p) == ("OK", "PDN_INSERTED_ADAPTIVE")


def test_verdict_UNKNOWN_when_the_transcript_says_nothing_about_pdn(tmp_path):
    """A truncated or mocked transcript must NOT be read as a broken grid."""
    p = _project(tmp_path, "routing done, 0 violations\n", DEF_STRAPPED)
    assert mod._pnr_pdn_grid_verdict(p)[0] == "UNKNOWN"


def test_verdict_UNKNOWN_when_the_log_is_missing(tmp_path):
    pnr = mod._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    assert mod._pnr_pdn_grid_verdict(tmp_path)[0] == "UNKNOWN"


def test_unknown_and_bad_are_distinguishable_from_ok(tmp_path):
    """All three states are reachable and distinct — a verdict function that
    can only ever return one of them is not a verdict function."""
    seen = {
        mod._pnr_pdn_grid_verdict(
            _project(tmp_path / "a", "PDN_INSERTED_ADAPTIVE: x\n",
                     DEF_STRAPPED))[0],
        mod._pnr_pdn_grid_verdict(
            _project(tmp_path / "b", "PDN_INSERTED_ADAPTIVE: x\n",
                     DEF_RAILS_ONLY))[0],
        mod._pnr_pdn_grid_verdict(_project(tmp_path / "c", "quiet\n"))[0],
    }
    assert seen == {"OK", "BAD", "UNKNOWN"}

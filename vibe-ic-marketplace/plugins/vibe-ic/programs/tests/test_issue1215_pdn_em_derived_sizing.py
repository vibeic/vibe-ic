#!/usr/bin/env python3
"""#1215-PDN — DERIVED (never tuned) EM strap sizing + real-width screening.

Two halves, one discipline: the strap width is COMPUTED from the PDK's own
Jmax and the design's measured supply current, and the gate then confirms
independently against the width the router actually drew. No width is ever
tried-until-green, the Jmax rule/margin/gate are untouched, and a first pass
with no measurement keeps the PDN byte-identical.

(A) `em_current_density_check.discover_def_pg_min_widths` — the PSM CSV has
    no width column, so the screen divided strap currents by the LEF minimum
    width (measured spm x gf180mcuD: assumed 0.28 um vs the 1.6 um the DEF
    states — J overstated ~5.7x). The routed DEF's SPECIALNETS state every
    PG wire width; the per-layer MIN positive width is a true LOWER bound on
    any PG wire there (the analysed net's wires are a subset), so dividing
    by it still OVERSTATES J — it can only add offenders vs the truth, never
    hide one, while being strictly less pessimistic than the LEF default.

(B) `phase3_one_shot_runner._pdn_em_width_floor` — the conservation bound:
    no PDN segment can carry more than the injected I_total = P/V, so

        w_em(layer) = I_total / (jmax_per_width(layer) * (1 - margin))

    guarantees no strap can exceed the margined Jmax under ANY current
    distribution. One-shot derivation, nothing to iterate. Applied as a
    FLOOR (max) on strap layers only; follow-pin rails are the cell
    architecture's and are judged (not sized) at their DEF-stated width.

chip-AGNOSTIC: LEF/DEF grammar and arithmetic only; layer names below are
arbitrary tokens.
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import em_current_density_check as EMC  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

# mkdtemp, not tmp_path (containerised-suite tmp_path newline hazard).

_TLEF = """LAYER MetalA
  TYPE ROUTING ;
  WIDTH 0.28 ;
  THICKNESS 0.54 ;
  DCCURRENTDENSITY AVERAGE 0.67 ;
END MetalA
LAYER MetalB
  TYPE ROUTING ;
  WIDTH 0.44 ;
  THICKNESS 1.19 ;
  DCCURRENTDENSITY AVERAGE 1.5 ;
END MetalB
"""

_DEF = """VERSION 5.8 ;
DESIGN unit ;
UNITS DISTANCE MICRONS 2000 ;
SPECIALNETS 2 ;
    - VDD ( * VDD ) + USE POWER
      + ROUTED MetalA 3200 + SHAPE STRIPE ( 0 0 ) ( 100000 0 )
        NEW MetalA 0 ( 0 0 ) viaX
        NEW MetalB 1200 + SHAPE STRIPE ( 0 0 ) ( 0 100000 ) ;
    - VSS ( * VSS ) + USE GROUND
      + ROUTED MetalA 3200 + SHAPE STRIPE ( 0 4000 ) ( 100000 4000 ) ;
END SPECIALNETS
END DESIGN
"""


# ---------------------------------------------------------------- (A) ----
def test_def_pg_min_widths_parses_specialnets_and_skips_via_points():
    d = Path(tempfile.mkdtemp(prefix="i1215d_"))
    f = d / "unit.def"
    f.write_text(_DEF)
    w = EMC.discover_def_pg_min_widths(f)
    # 3200 dbu / 2000 = 1.6 um; 1200/2000 = 0.6; the `NEW MetalA 0` via
    # point must NOT drag MetalA's bound to zero.
    assert w == {"metala": 1.6, "metalb": 0.6}
    # project-dir form resolves the canonical PnR DEF path.
    proj = Path(tempfile.mkdtemp(prefix="i1215p_"))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "unit.def").write_text(_DEF)
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 1.6,
                                                    "metalb": 0.6}
    # absence degrades to {} (the LEF fallback), never an error.
    assert EMC.discover_def_pg_min_widths(Path(tempfile.mkdtemp())) == {}


def _screen(cur_a, def_widths):
    table = EMC.parse_lef_jmax(_TLEF)
    seg = {"layer0": "MetalA", "layer1": "MetalA", "net": "VDD",
           "current_A": cur_a, "width_um": None}
    return EMC._screen_segment(seg, table, 0.10, 2.0, def_widths)


def test_def_width_bound_judges_the_wire_the_router_drew():
    """2.0 mA on MetalA: at the LEF default 0.28 um J=1.32e-2 >> Jmax
    1.24e-3 (a false offender ~10.7x); at the DEF-stated 1.6 um
    J=2.31e-3 — still an offender (~1.87x, the spm shape) but judged on
    real geometry. At 0.5 mA the LEF basis still cries offender (2.7x)
    while the DEF basis rightly clears it (0.47x)."""
    r_lef = _screen(2.0e-3, None)
    assert r_lef["status"] == "offender"
    assert r_lef["width_source"] == "lef_default_width"
    r_def = _screen(2.0e-3, {"metala": 1.6})
    assert r_def["status"] == "offender"      # genuinely over even when real
    assert r_def["width_source"] == "def_specialnets_min"
    assert r_def["width_um"] == 1.6
    ok = _screen(0.5e-3, {"metala": 1.6})
    assert ok["status"] == "ok"
    assert _screen(0.5e-3, None)["status"] == "offender", \
        "control: the pre-fix LEF basis mislabels this segment"


def test_csv_width_still_wins_over_def_bound():
    table = EMC.parse_lef_jmax(_TLEF)
    seg = {"layer0": "MetalA", "layer1": "MetalA", "net": "VDD",
           "current_A": 2.0e-3, "width_um": 0.30}
    r = EMC._screen_segment(seg, table, 0.10, 2.0, {"metala": 1.6})
    assert r["width_source"] == "csv" and r["width_um"] == 0.30


# ---------------------------------------------------------------- (B) ----
def _mk_measured_project(i_total_a: float) -> Path:
    proj = Path(tempfile.mkdtemp(prefix="i1215b_"))
    rpt3 = proj / "reports" / "phase3"
    rpt3.mkdir(parents=True)
    (rpt3 / "em_current_authority.json").write_text(json.dumps({
        "supply_authority": [{"net": "VDD",
                              "supply_current_A": i_total_a}]}))
    return proj


def _mk_pdk(tlef_path) -> SimpleNamespace:
    return SimpleNamespace(tech_lef=str(tlef_path), tapcell_master=None)


def test_floor_is_derived_from_measurement_and_pdk_jmax_only():
    proj = _mk_measured_project(4.36e-3)
    tlef = proj / "unit_tech.tlef"
    tlef.write_text(_TLEF)
    fl = R._pdn_em_width_floor(proj, _mk_pdk(tlef), container=None)
    assert fl is not None
    # THE ARITHMETIC, verbatim: w = I / (jmax * (1 - margin)), then rounded
    # UP to 2x the manufacturing grid (0.001 fallback — this LEF states no
    # MANUFACTURINGGRID). 2x because pdngen centres a stripe on its axis so
    # the HALF-width must be on-grid (measured: PDN-0117 refused 7.235 on a
    # 0.005 grid and the whole PDN degraded to PDN_NONFATAL). Strictly
    # above the bound: the gate counts util >= 1 - margin as an offender,
    # and a round-to-nearest could even land below the bound.
    import math

    def _w(bound, quantum=0.002):
        w = math.ceil(bound / quantum - 1e-9) * quantum
        return round(w + quantum, 4) if w <= bound + 1e-12 else round(w, 4)

    assert fl["margin"] == 0.10
    b_a = 4.36e-3 / (0.67e-3 * 0.9)
    b_b = 4.36e-3 / (1.5e-3 * 0.9)
    assert fl["per_layer"]["metala"]["w_em_um"] == _w(b_a)
    assert fl["per_layer"]["metalb"]["w_em_um"] == _w(b_b)
    assert fl["per_layer"]["metala"]["w_em_um"] > b_a, "bound must be strict"
    assert fl["per_layer"]["metalb"]["w_em_um"] > b_b, "bound must be strict"
    # pdngen's PDN-0117 constraint: width is a multiple of 2x the grid.
    for lyr in ("metala", "metalb"):
        w = fl["per_layer"][lyr]["w_em_um"]
        assert abs(w / 0.002 - round(w / 0.002)) < 1e-6, \
            f"{lyr}: {w} is not a 2x-grid multiple (PDN-0117)"
    # the arithmetic is published for independent recomputation.
    art = json.loads((proj / "reports" / "phase3"
                      / "pdn_em_sizing.json").read_text())
    assert "I_total / (jmax_per_width" in art["arithmetic"]
    assert "STRICT" in art["arithmetic"]
    assert art["i_total_A"] == 4.36e-3
    assert art["manufacturing_grid_um"] == 0.001
    assert art["width_quantum_um"] == 0.002


def test_first_pass_without_measurement_derives_nothing():
    proj = Path(tempfile.mkdtemp(prefix="i1215n_"))
    tlef = proj / "unit_tech.tlef"
    tlef.write_text(_TLEF)
    assert R._pdn_em_width_floor(proj, _mk_pdk(tlef), None) is None


def test_sky130_grid_untouched_without_floor_and_widened_with_it():
    pdk = SimpleNamespace(tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
                          tech_lef=None, cell_lef=None, pdn_straps=None)
    base = R._build_pdn_tcl(pdk, None, em_floor=None)
    # no-floor render is byte-identical to the tuned grid.
    assert "-layer met4 -width 1.6 -pitch 40.0 -offset 8.0" in base
    assert "-layer met5 -width 1.6 -pitch 40.0 -offset 8.0" in base
    assert "EM-derived" not in base
    floor = {"per_layer": {"met4": {"w_em_um": 3.23},
                           "met5": {"w_em_um": 3.23}}}
    widened = R._build_pdn_tcl(pdk, None, em_floor=floor)
    assert "-layer met4 -width 3.23" in widened
    assert "-layer met5 -width 3.23" in widened
    assert "EM-derived strap floor applied" in widened


def test_sky130_pitch_grows_only_when_the_ratio_demands_it():
    pdk = SimpleNamespace(tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
                          tech_lef=None, cell_lef=None, pdn_straps=None)
    # 3.23 um: 8*w = 25.84 < 40 -> tuned pitch/offset kept.
    small = R._build_pdn_tcl(pdk, None, em_floor={
        "per_layer": {"met4": {"w_em_um": 3.23}}})
    assert "-width 3.23 -pitch 40.0 -offset 8.0" in small
    # 7.23 um: 8*w = 57.84 > 40 -> pitch re-derived, offset = pitch/4.
    big = R._build_pdn_tcl(pdk, None, em_floor={
        "per_layer": {"met4": {"w_em_um": 7.23},
                      "met5": {"w_em_um": 7.23}}})
    assert "-width 7.23 -pitch 57.84 -offset 14.46" in big
    assert "EM-derived strap floor applied" in big


def test_floor_never_narrows_a_strap():
    pdk = SimpleNamespace(tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
                          tech_lef=None, cell_lef=None, pdn_straps=None)
    out = R._build_pdn_tcl(pdk, None, em_floor={
        "per_layer": {"met4": {"w_em_um": 0.5}}})
    assert "-layer met4 -width 1.6 -pitch 40.0 -offset 8.0" in out
    assert "EM-derived" not in out


def test_followpin_rails_are_never_resized_SOURCE():
    import inspect
    src = inspect.getsource(R._build_pdn_tcl)
    # the follow-pins lines carry no _em_floor_w application: the sky130
    # met1 followpins literal is untouched and the generic followpins line
    # (rendered elsewhere with the discovered rail width) is not in the
    # stripe loop the floor rewrites.
    assert "-layer met1 -width 0.48 -pitch 5.44 -offset 0 -followpins" in src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_def_discovery_is_newest_first_and_skips_specialnets_free_defs():
    """The wrong-subject incident: alphabetical [0] picked a stale
    PDN-failed filled.def with zero SPECIALNETS and the gate judged LEF
    widths while the fresh routed DEF carried the sized straps. Newest
    non-empty wins; a newer SPECIALNETS-free DEF (floorplan-shaped) must
    not blank the whole project."""
    import os
    proj = Path(tempfile.mkdtemp(prefix="i1215o_"))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    old = pnr / "a_routed.def"
    old.write_text(_DEF)                       # has SPECIALNETS (1.6 / 0.6)
    os.utime(old, (1000, 1000))
    new_empty = pnr / "b_floorplan.def"        # newer, no SPECIALNETS
    new_empty.write_text("VERSION 5.8 ;\nUNITS DISTANCE MICRONS 2000 ;\n"
                         "END DESIGN\n")
    os.utime(new_empty, (2000, 2000))
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 1.6,
                                                    "metalb": 0.6}
    newest = pnr / "c_final.def"               # newest, different widths
    newest.write_text(_DEF.replace("3200", "14480"))
    os.utime(newest, (3000, 3000))
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 7.24,
                                                    "metalb": 0.6}


def test_em_authority_emit_reports_a_stale_artifact_instead_of_claiming_it_SOURCE():
    import inspect
    src = inspect.getsource(R._emit_em_current_authority)
    assert "did not refresh" in src and "after <= before" in src, \
        "#1215-PDN: a crashed gate must not be reported as an emit because " \
        "the previous run's file still exists"

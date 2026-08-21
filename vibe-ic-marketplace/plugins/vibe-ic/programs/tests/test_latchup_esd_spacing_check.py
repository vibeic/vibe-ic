"""Tests for latchup_esd_spacing_check — the OPEN-SOURCE GEOMETRY-LAYER half of
PERC latch-up / ESD sign-off (v0.2.30).

Pins the anti-over-claim contract proven by the 6-agent adversarial panel:
spacing is CONCLUSIVE-FAIL-ONLY — it may emit WELLTAP_SPACING_GAP (conclusive),
INCOMPLETE (degenerate/missing DIEAREA, unrecognised taps, too-few cells, looser
pitch), or SPACING_OK_NECESSARY_NOT_SUFFICIENT, but NEVER an automated PASS that
implies latch-up safety. Also pins guard-ring topology, optional clamp netlist
connectivity, the geometry parsers, the foundry-data residual, and validation on
the REAL routed DEFs in the repo.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import latchup_esd_spacing_check as L
from _hostpaths import corpus_path, repo_path_opt, require_corpus  # noqa: E402


# --------------------------------------------------------------------------- #
# synthetic DEF builders                                                       #
# --------------------------------------------------------------------------- #
def _def(rows, die="( 0 0 ) ( 250000 250000 )", units=1000, nets=""):
    return (f"VERSION 5.8 ;\nDESIGN t ;\nUNITS DISTANCE MICRONS {units} ;\n"
            f"DIEAREA {die} ;\nCOMPONENTS {len(rows)} ;\n"
            + "\n".join(rows) + "\nEND COMPONENTS\n" + nets + "END DESIGN\n")


def _std_rows(n, step=4000, master="sky130_fd_sc_hd__nand2_1"):
    """n std cells laid out on a grid (step in DBU)."""
    return [f"- _{i}_ {master} + PLACED ( {(i % 20) * step} {(i // 20) * step} ) N ;"
            for i in range(n)]


def _tap_rows(n, step=4000, x0=0, y0=0, master="sky130_fd_sc_hd__tapvpwrvgnd_1"):
    return [f"- tap{j} {master} + SOURCE DIST + FIXED ( {x0 + (j % 20) * step} "
            f"{y0 + (j // 20) * step} ) N ;" for j in range(n)]


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


# --------------------------------------------------------------------------- #
# geometry parsers                                                             #
# --------------------------------------------------------------------------- #
def test_parse_diearea_two_paren_form():
    box = L._parse_diearea_um("DIEAREA ( 0 0 ) ( 250000 250000 ) ;", 1000)
    assert box == (0.0, 0.0, 250.0, 250.0)


def test_parse_diearea_flat_form():
    box = L._parse_diearea_um("DIEAREA ( 0 0 100000 200000 ) ;", 1000)
    assert box == (0.0, 0.0, 100.0, 200.0)


def test_parse_diearea_rectilinear_polygon_bbox():
    # >2 points → bounding box of all points
    box = L._parse_diearea_um(
        "DIEAREA ( 0 0 ) ( 0 100000 ) ( 50000 100000 ) ( 50000 0 ) ;", 1000)
    assert box == (0.0, 0.0, 50.0, 100.0)


def test_parse_diearea_missing_returns_none():
    assert L._parse_diearea_um("DESIGN t ;", 1000) is None


def test_parse_units_default_and_explicit():
    assert L._parse_units("DESIGN t ;") == 1000
    assert L._parse_units("UNITS DISTANCE MICRONS 2000 ;") == 2000


def test_parse_placed_geometry_extracts_xy_and_skips_artifacts():
    text = _def(["- _1_ sky130_fd_sc_hd__nand2_1 + PLACED ( 1000 2000 ) N ;",
                 "- tap0 sky130_fd_sc_hd__tapvpwrvgnd_1 + SOURCE DIST + FIXED ( 3000 4000 ) N ;"])
    geom = L._parse_placed_geometry(text)
    assert ("_1_", "sky130_fd_sc_hd__nand2_1", 1000, 2000) in geom
    assert ("tap0", "sky130_fd_sc_hd__tapvpwrvgnd_1", 3000, 4000) in geom


def test_cell_classifiers():
    assert L._is_rated_tap("sky130_fd_sc_hd__tapvpwrvgnd_1")
    assert not L._is_rated_tap("sky130_fd_sc_hd__nand2_1")
    assert L._is_std_cell("sky130_fd_sc_hd__nand2_1")
    assert not L._is_std_cell("sky130_fd_sc_hd__tapvpwrvgnd_1")
    assert not L._is_std_cell("sky130_fd_sc_hd__decap_3")
    assert not L._is_std_cell("sky130_fd_sc_hd__fill_1")


# --------------------------------------------------------------------------- #
# spacing — CONCLUSIVE-FAIL-ONLY contract                                      #
# --------------------------------------------------------------------------- #
def test_zero_taps_is_conclusive_gap(tmp_path):
    d = _write(tmp_path, "z.def", _def(_std_rows(100)))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["reason"] == "ZERO_TAPS"
    assert r["n_tap"] == 0 and r["n_std"] == 100


def test_unknown_tap_master_not_counted_and_noted(tmp_path):
    # a 'tap'-token master not on the rated allowlist must NOT count as a tap
    rows = _std_rows(80) + [
        "- t0 some_other_lib__tap_filler_1 + PLACED ( 100 100 ) N ;"]
    d = _write(tmp_path, "u.def", _def(rows))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["n_tap"] == 0
    assert any("tap" in t for t in r["unknown_taps"])


def test_dense_taps_is_necessary_not_sufficient_never_pass(tmp_path):
    # every std cell within the generous screen radius of a tap → OK_NNS, NOT a PASS
    rows = _std_rows(100, step=4000) + _tap_rows(100, step=4000)
    d = _write(tmp_path, "ok.def", _def(rows))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "SPACING_OK_NECESSARY_NOT_SUFFICIENT"
    # the contract: the word PASS never appears as a verdict, only NNS
    assert "PASS" not in r["status"]
    assert "NOT an automated latch-up PASS" in r["note"]


def test_untapped_region_is_conclusive_gap(tmp_path):
    # 60 std cells spread across a 400um die, taps only in the origin corner
    rows = [f"- _{i}_ sky130_fd_sc_hd__nand2_1 + PLACED ( {(i % 10) * 40000} "
            f"{(i // 10) * 40000} ) N ;" for i in range(60)]
    rows += _tap_rows(5, step=100, x0=0, y0=0)
    d = _write(tmp_path, "ut.def", _def(rows, die="( 0 0 ) ( 400000 400000 )"))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["reason"] == "UNTAPPED_REGION"


def test_degenerate_diearea_is_incomplete_never_gap(tmp_path):
    # 0-taps would be a GAP normally, but with NO logic-vs-die it stays conclusive
    # only on ZERO_TAPS; here we give taps but a degenerate die so UNTAPPED can't fire
    rows = _std_rows(80) + _tap_rows(80)
    d = _write(tmp_path, "deg.def", _def(rows, die="( 0 0 ) ( 0 0 )"))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "INCOMPLETE"
    assert r["reason"] == "DEGENERATE_DIEAREA"


def test_zero_taps_conclusive_even_for_tiny_block(tmp_path):
    # 0 taps is conclusive regardless of cell count (matches the shipped presence
    # doctrine: any placed logic with no substrate tie latches up) — ZERO_TAPS wins
    # over the too-few-cells INCOMPLETE coverage guard.
    rows = _std_rows(10)
    d = _write(tmp_path, "tiny0.def", _def(rows))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["reason"] == "ZERO_TAPS"


def test_too_few_std_cells_with_taps_is_incomplete_never_coverage_gap(tmp_path):
    # taps PRESENT but below the meaningful-block threshold → the sparse-coverage
    # screen is withheld as INCOMPLETE (no UNTAPPED over-claim on a tiny block)
    rows = _std_rows(10) + _tap_rows(2, step=100, x0=0, y0=0)
    d = _write(tmp_path, "tiny.def", _def(rows, die="( 0 0 ) ( 400000 400000 )"))
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "INCOMPLETE"
    assert r["reason"] == "TOO_FEW_STD_CELLS"


def test_no_geometry_is_incomplete(tmp_path):
    d = _write(tmp_path, "empty.def", "VERSION 5.8 ;\nDESIGN t ;\nEND DESIGN\n")
    r = L._latchup_tap_spacing_check(d)
    assert r["status"] == "INCOMPLETE"
    assert r["reason"] == "NO_PLACED_GEOMETRY"


def test_spacing_never_emits_a_bare_pass_status(tmp_path):
    """Hard anti-over-claim invariant: across every input class the spacing status
    is ALWAYS one of the three honest verdicts — never a bare 'PASS' / 'OK'."""
    allowed = {"WELLTAP_SPACING_GAP", "INCOMPLETE",
               "SPACING_OK_NECESSARY_NOT_SUFFICIENT"}
    cases = [
        _def(_std_rows(100)),                                   # zero taps
        _def(_std_rows(100) + _tap_rows(100)),                  # dense
        _def(_std_rows(10)),                                    # tiny
        _def(_std_rows(80) + _tap_rows(80), die="( 0 0 ) ( 0 0 )"),  # degenerate
        "VERSION 5.8 ;\nDESIGN t ;\nEND DESIGN\n",              # no geometry
    ]
    for i, txt in enumerate(cases):
        d = _write(tmp_path, f"c{i}.def", txt)
        assert L._latchup_tap_spacing_check(d)["status"] in allowed


def test_generous_screen_means_ok_is_looser_than_real_rule(tmp_path):
    # the default screen is intentionally loose (30um); a clean OK must SAY it cannot
    # certify the real foundry pitch
    rows = _std_rows(100) + _tap_rows(100)
    d = _write(tmp_path, "g.def", _def(rows))
    r = L._latchup_tap_spacing_check(d)
    assert r["screen_um"] == L._DEFAULT_SCREEN_UM
    assert "LOOSER" in r["note"] and "foundry" in r["note"].lower()


# --------------------------------------------------------------------------- #
# guard-ring topology                                                          #
# --------------------------------------------------------------------------- #
def test_guardring_na_pure_digital_core(tmp_path):
    d = _write(tmp_path, "core.def", _def(_std_rows(100) + _tap_rows(100)))
    r = L._guardring_topology_check(d)
    assert r["status"] == "NA"


def test_guardring_absent_when_io_present_but_no_ring(tmp_path):
    rows = _std_rows(60) + ["- pad0 sky130_fd_io__top_gpiov2 + PLACED ( 1000 1000 ) N ;",
                            "- pad1 sky130_fd_io__top_gpiov2 + PLACED ( 2000 2000 ) N ;"]
    d = _write(tmp_path, "io.def", _def(rows))
    r = L._guardring_topology_check(d)
    assert r["status"] == "GUARDRING_ABSENT"
    assert r["n_io_or_hicurrent"] == 2 and r["n_guardring"] == 0
    # MANUAL, never auto-fail
    assert "auto-fail" in r["note"] or "MANUAL" in r["note"]


def test_guardring_present_reports_proximity(tmp_path):
    rows = _std_rows(40) + [
        "- pad0 sky130_fd_io__top_gpiov2 + PLACED ( 1000 1000 ) N ;",
        "- gr0 sky130_fd_io__top_power_hvc_wpadv2_guard + PLACED ( 1100 1100 ) N ;"]
    d = _write(tmp_path, "gr.def", _def(rows))
    r = L._guardring_topology_check(d)
    assert r["status"] == "GUARDRING_PRESENT"
    assert r["n_guardring"] == 1
    assert "EFFICACY" in r["note"]


def test_guardring_proximity_count_is_accurate(tmp_path):
    # 3 IO pads; one guard ring near pad0 only (others > proximity away) → near==1
    rows = _std_rows(40) + [
        "- pad0 sky130_fd_io__top_gpiov2 + PLACED ( 1000 1000 ) N ;",
        "- pad1 sky130_fd_io__top_gpiov2 + PLACED ( 200000 200000 ) N ;",
        "- pad2 sky130_fd_io__top_gpiov2 + PLACED ( 240000 240000 ) N ;",
        "- gr0 my_substrate_ring + PLACED ( 1100 1100 ) N ;"]
    d = _write(tmp_path, "px.def", _def(rows, die="( 0 0 ) ( 250000 250000 )"))
    r = L._guardring_topology_check(d, proximity_um=50.0)
    assert r["status"] == "GUARDRING_PRESENT"
    assert r["io_hicurrent_within_proximity"] == 1


def test_count_within_helper():
    anchors = [(0.0, 0.0)]
    q = [(1.0, 1.0), (100.0, 100.0)]   # one within 10um, one not
    assert L._count_within(q, anchors, 10.0) == 1
    assert L._count_within(q, [], 10.0) == 0


def test_is_guardring_tokens():
    assert L._is_guardring("my_guard_ring_cell")
    assert L._is_guardring("foundry_substrate_ring")
    assert not L._is_guardring("sky130_fd_sc_hd__nand2_1")


# --------------------------------------------------------------------------- #
# ESD clamp netlist connectivity (optional)                                    #
# --------------------------------------------------------------------------- #
def test_clamp_netlist_na_when_no_clamps(tmp_path):
    n = _write(tmp_path, "n.spice",
               "x1 SIGNAL_A SIGNAL_B sky130_fd_sc_hd__nand2_1\n")
    r = L._esd_clamp_netlist_connectivity(n)
    assert r["status"] == "NA"
    assert r["n_clamps"] == 0


def test_clamp_netlist_ok_both_rails(tmp_path):
    n = _write(tmp_path, "ok.spice",
               "x1 VDDIO VSSIO sky130_fd_io__top_gpiov2\n"
               "x2 VCCD VSSD sky130_fd_io__top_xres4v2\n")
    r = L._esd_clamp_netlist_connectivity(n)
    assert r["status"] == "CLAMP_CONNECTIVITY_OK"
    assert r["n_clamps"] == 2
    assert "NOT prove clamp HBM/CDM" in r["note"]


def test_clamp_netlist_gap_dangling_clamp(tmp_path):
    # x2 tied to a power net + a signal net only (no ground) → conclusive GAP
    n = _write(tmp_path, "gap.spice",
               "x1 VDDIO VSSIO sky130_fd_io__top_gpiov2 w=10\n"
               "x2 VDDIO FLOATSIG sky130_fd_io__top_xres4v2\n")
    r = L._esd_clamp_netlist_connectivity(n)
    assert r["status"] == "CLAMP_CONNECTIVITY_GAP"
    assert len(r["gaps"]) == 1


def test_clamp_netlist_handles_line_continuation(tmp_path):
    n = _write(tmp_path, "cont.spice",
               "x1 VDDIO\n+ VSSIO sky130_fd_io__top_gpiov2\n")
    r = L._esd_clamp_netlist_connectivity(n)
    assert r["status"] == "CLAMP_CONNECTIVITY_OK"
    assert r["n_clamps"] == 1


def test_split_spice_inst_drops_params():
    parsed = L._split_spice_inst("x1 VDDIO VSSIO sky130_fd_io__top_gpiov2 w=10 l=0.15")
    assert parsed == ("x1", "sky130_fd_io__top_gpiov2", ["VDDIO", "VSSIO"])


# --------------------------------------------------------------------------- #
# aggregator + public API                                                      #
# --------------------------------------------------------------------------- #
def test_run_geometry_layer_flags_conclusive_gap(tmp_path):
    d = _write(tmp_path, "z.def", _def(_std_rows(100)))
    rep = L.run_geometry_layer(str(d))
    assert rep["any_conclusive_gap"] is True
    assert rep["spacing"]["status"] == "WELLTAP_SPACING_GAP"
    assert rep["layer"] == "perc_geometry_open_source"
    assert "foundry" in rep["foundry_data_residual"].lower()


def test_run_geometry_layer_clean_has_no_gap(tmp_path):
    d = _write(tmp_path, "ok.def", _def(_std_rows(100) + _tap_rows(100)))
    rep = L.run_geometry_layer(str(d))
    assert rep["any_conclusive_gap"] is False


def test_run_geometry_layer_with_netlist(tmp_path):
    d = _write(tmp_path, "ok.def", _def(_std_rows(100) + _tap_rows(100)))
    n = _write(tmp_path, "n.spice", "x1 VDDIO FLOATSIG sky130_fd_io__top_gpiov2\n")
    rep = L.run_geometry_layer(str(d), netlist_file=str(n))
    assert "clamp_netlist" in rep
    assert rep["clamp_netlist"]["status"] == "CLAMP_CONNECTIVITY_GAP"
    assert rep["any_conclusive_gap"] is True


def test_foundry_residual_names_the_three_uncloseable_items():
    res = L.FOUNDRY_DATA_RESIDUAL
    for tok in ("HBM/CDM", "Vhold", "beta", "guard-ring efficacy",
                "TLP", "substrate RC", "NOT commercial-tool lock-in"):
        assert tok in res, tok


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _cli(args):
    prog = Path(L.__file__)
    return subprocess.run([sys.executable, str(prog), *args],
                          capture_output=True, text=True)


def test_cli_exit1_on_conclusive_gap(tmp_path):
    d = _write(tmp_path, "z.def", _def(_std_rows(100)))
    res = _cli([str(d)])
    assert res.returncode == 1
    out = json.loads(res.stdout)
    assert out["spacing"]["status"] == "WELLTAP_SPACING_GAP"


def test_cli_exit0_when_no_gap(tmp_path):
    d = _write(tmp_path, "ok.def", _def(_std_rows(100) + _tap_rows(100)))
    res = _cli([str(d)])
    assert res.returncode == 0


def test_cli_def_not_found():
    res = _cli(["/no/such/file.def"])
    assert res.returncode == 2
    assert json.loads(res.stdout)["reason"] == "DEF_NOT_FOUND"


# --------------------------------------------------------------------------- #
# REAL routed-DEF validation (repo fixtures) — skipped if absent              #
# --------------------------------------------------------------------------- #
_REAL_GAP_DEFS = [
    str(corpus_path("spm_pilot_v0144/rerun_d030/routed.def")),          # 0 taps
    str(repo_path_opt("benchmark-data/ic/subservient/phase3/stage3/pnr/routed.def")),  # 0 taps
]
_REAL_OK_DEFS = [
    str(corpus_path("spm_pilot_v0144/rerun_d030_tapcell/routed.def")),  # 384 taps
    str(corpus_path("spm_pilot_v0144/pdn_ir_v0146/routed.def")),        # 384 taps
]


@pytest.mark.parametrize("path", _REAL_GAP_DEFS)
def test_real_zero_tap_def_is_conclusive_gap(path):
    if not Path(path).is_file():
        pytest.skip(f"real DEF not present: {path}")
    r = L._latchup_tap_spacing_check(Path(path))
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["reason"] == "ZERO_TAPS"
    assert r["n_tap"] == 0 and r["n_std"] > 0


@pytest.mark.parametrize("path", _REAL_OK_DEFS)
def test_real_tapped_def_is_necessary_not_sufficient(path):
    if not Path(path).is_file():
        pytest.skip(f"real DEF not present: {path}")
    r = L._latchup_tap_spacing_check(Path(path))
    # tapped → NNS (never a bare PASS); could also be INCOMPLETE if tiny, but these
    # are full routed blocks so we expect the necessary-not-sufficient verdict
    assert r["status"] == "SPACING_OK_NECESSARY_NOT_SUFFICIENT"
    assert r["n_tap"] > 0


def test_real_caravel_chip_io_guardring_absent_not_autofail():
    """Real Caravel chip_io.def: sky130 IO pads carry their guard ring INSIDE the
    pad GDS, not as separate placed instances — so the screen sees IO cells but no
    guard-ring master and returns GUARDRING_ABSENT (MANUAL), never auto-fail."""
    path = str(require_corpus("spm_pilot_v0144/caravel_work/caravel_user_project/"
                              "caravel/def/chip_io.def"))
    if not Path(path).is_file():
        pytest.skip("real chip_io.def not present")
    r = L._guardring_topology_check(Path(path))
    assert r["status"] == "GUARDRING_ABSENT"
    assert r["n_io_or_hicurrent"] > 0


# --------------------------------------------------------------------------- #
# TAPLESS-CELL PDK guard — BIDIRECTIONAL                                       #
#                                                                              #
# Measured twice on the IHP SG13 family: a PDK that ships NO tapcell master     #
# (ties internal to every std cell) produced a CONCLUSIVE false FAIL from the   #
# DEF-component count — sg13g2 "452 placed std cell(s) but no well taps" and    #
# sg13cmos5l "364 placed std cell(s) but 0 rated well/substrate-tap cell(s)".   #
# Both designs' ties are present and measurable in the sign-off GDS.            #
#                                                                              #
# The pair below is load-bearing in BOTH directions:                            #
#   * the DEFECT (tapless PDK) must STOP being a conclusive GAP, and            #
#   * a GENUINE 0-tap break on a tapcell-methodology PDK must STILL FAIL.       #
# Either assertion alone is a rubber stamp.                                     #
# --------------------------------------------------------------------------- #
def test_tapless_pdk_zero_taps_is_incomplete_not_a_gap(tmp_path):
    """FIXED DIRECTION: tapless-cell PDK + 0 tap COMPONENTS is EXPECTED."""
    d = _write(tmp_path, "tapless.def", _def(_std_rows(364)))
    r = L._latchup_tap_spacing_check(d, tapless_pdk=True)
    assert r["status"] == "INCOMPLETE"
    assert r["reason"] == "ZERO_TAPS_TAPLESS_PDK"
    assert r["status"] not in L.GAP_STATUSES
    assert r["n_tap"] == 0 and r["n_std"] == 364
    # honesty contract: INCOMPLETE is NOT a latch-up pass
    assert "NOT a conclusive structural GAP" in r["note"]
    assert "tap_geom_layers" in r["note"]


def test_tapcell_pdk_zero_taps_still_conclusive_gap(tmp_path):
    """DEFECT DIRECTION: the guard must NOT mask a real skipped-tapcell break."""
    d = _write(tmp_path, "tapped.def", _def(_std_rows(364)))
    r = L._latchup_tap_spacing_check(d, tapless_pdk=False)
    assert r["status"] == "WELLTAP_SPACING_GAP"
    assert r["reason"] == "ZERO_TAPS"
    assert r["status"] in L.GAP_STATUSES


def test_tapless_guard_defaults_off_and_is_narrow(tmp_path):
    """Default is unchanged (guard opt-in), and it only touches ZERO_TAPS."""
    d = _write(tmp_path, "dflt.def", _def(_std_rows(100)))
    assert L._latchup_tap_spacing_check(d)["reason"] == "ZERO_TAPS"
    # a tapless PDK that DOES carry taps is screened normally, not short-circuited
    rows = _std_rows(100, step=4000) + _tap_rows(100, step=4000)
    d2 = _write(tmp_path, "dense.def", _def(rows))
    r = L._latchup_tap_spacing_check(d2, tapless_pdk=True)
    assert r["status"] == "SPACING_OK_NECESSARY_NOT_SUFFICIENT"


def test_run_geometry_layer_threads_tapless_flag(tmp_path):
    """The public API must carry the flag through to any_conclusive_gap."""
    d = _write(tmp_path, "api.def", _def(_std_rows(364)))
    assert L.run_geometry_layer(str(d), tapless_pdk=False)["any_conclusive_gap"] is True
    assert L.run_geometry_layer(str(d), tapless_pdk=True)["any_conclusive_gap"] is False

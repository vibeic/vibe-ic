"""Tests for si_signoff_timing_aware.py — OPEN-SOURCE timing-window-aware SI screen.

Covers:
  * SPEF parsing: NAME_MAP, ground/coupling caps, node->net attribution
    (the correctness heart — a pin-node like `*3069:A` must land on the real
    D_NET it belongs to, NOT on the instance id `*3069`), and the *P vs *I
    direction semantics (an input port `*P x I` is an external DRIVER).
  * compute_net_windows: driver-pin arrival window -> net switching window.
  * window overlap gating: no overlap => decoupled => safe.
  * the full scorer: deterministic ADVISORY screen on synthetic cases (overlap
    + high coupling on a floating victim => HIGH watch-list; same coupling
    decoupled by non-overlapping windows => decoupled-safe, empty watch-list;
    driven victim damping). The verdict is ALWAYS the single advisory
    SI_TIMING_AWARE_SCREEN -- there is no PASS/FAIL split that implies sign-off.
  * NO fabricated flags: a low-coupling net never lands on any watch-list.
  * build_opensta_si_tcl: emits the required read_* + report_arrival/slews
    capture commands and the documented JSON shape.
  * run_si_signoff_timing_aware public API + CLI exit codes (advisory => exit 0
    by default; --strict opt-in exits 1 only when the HIGH watch-list is set).
  * REAL-SPEF validation against PUBLISHED extraction output — a routed SPEF
    under `benchmark-data/`, selected by `_real_data` on a checked publication
    rule rather than by a filesystem walk, and DISCLOSED by path in the run's
    `real-data provenance` summary. If nothing published qualifies, these skip
    with a reason naming which absence occurred; they never fall back to a
    fixture (vibe-ic#1037).

The synthetic SPEF fixtures use the exact OpenROAD SPEF dialect (C_UNIT PF,
':' delimiter, *NAME_MAP, *D_NET/*CONN/*CAP/*RES/*END) so the parser is
exercised on the real grammar.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import si_signoff_timing_aware as m
import _real_data as rd  # noqa: E402

PROG = Path(m.__file__).resolve()

# --- locate a real routed SPEF: PUBLISHED run output only --------------------
# vibe-ic#1037. This used to be three named `benchmark-data/...` paths followed
# by an unbounded `root.rglob("*.spef")` fallback. The named candidates sit
# under run roots being withdrawn from publication (#1015/#1010); the moment
# they go, the fallback is the only live branch — and the only `*.spef` under
# that walk root are THIS SUITE'S OWN FIXTURES. Two tests named
# `test_real_spef_*` would then assert properties of "production extraction
# output" about a file this suite wrote for itself.
#
# The red that caught it was luck, and the luck is measurable: of the six
# fixture SPEFs that walk yields, `si_mcf_zero_coupling/coupled/design.spef`
# (`pair_cc == 1`) satisfies EVERY assertion in BOTH tests below. Only
# `Path.rglob`'s directory-walk order kept this suite from reporting a green
# real-data anchor over its own fixture.
#
# So "real" is now a CHECKED property, not a hope, and the check lives in
# `_real_data` where any other real-data selector can adopt it:
#   * the candidate set comes from the GIT INDEX, not from a walk — the walk
#     was the bug, so there is no walk;
#   * eligibility is an ALLOW-LIST of published-run SHAPES (under
#     `benchmark-data/`, downstream of a flow phase, no held/dot tree,
#     git-tracked), not a deny-list of fixture directory names;
#   * selection applies THE PROPERTY THESE TESTS ASSERT (coupling pairs
#     present), so a substituted premise fails loudly at selection instead of
#     quietly at assertion, where it can accidentally agree;
#   * nothing falls back. If no published SPEF carries coupling pairs, that is
#     the answer and the skip says which absence occurred.
_SPEF_REQUIREMENT = ("coupling pairs present (`*CAP` entries between two "
                     "distinct nets) — the parasitic these tests read")


def _has_coupling_pairs(p: Path) -> bool:
    """The property the two `test_real_spef_*` tests assert, applied at
    SELECTION. Extraction output with no coupling pair cannot answer the
    question these tests ask, so it is not a candidate for them — this is a
    requirement, not a filter for convenience."""
    return len(m.parse_spef(p.read_text(errors="replace"))["pair_cc"]) > 0


def _real_spef() -> rd.Selection:
    """The published, git-tracked, coupling-carrying SPEF — or a refusal that
    names what is missing. NEVER a fixture, and never "whatever the walk
    yields"."""
    return rd.select(".spef", _has_coupling_pairs, _SPEF_REQUIREMENT,
                     label="test_si_signoff_timing_aware::real_spef")


# ===========================================================================
# Synthetic SPEF / timing fixtures
# ===========================================================================
# Net A (=*1) driven by instance _u0_/Q, with a load _u1_/A. Net B (=*2)
# driven by _u2_/Q, load _u3_/A. A and B couple strongly (Cc >> Cg on A) at
# the pin-node level: the coupling cap is between node *10:A (a pin on
# instance *10, which is a LOAD of net *1) and node *11:A (a pin on instance
# *11, a LOAD of net *2). A naive ':' split would mis-attribute to *10/*11.
SYNTH_SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "synth"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 neta
*2 netb
*10 _u1_
*11 _u3_
*20 _u0_
*21 _u2_

*D_NET *1 0.01
*CONN
*I *20:Q O *D sky130_fd_sc_hd__dfxtp_1
*I *10:A I *D sky130_fd_sc_hd__nor2_1
*CAP
1 neta 0.0001
2 *10:A 0.0001
3 *10:A *11:A 0.0098
*RES
1 *20:Q neta 10
*END

*D_NET *2 0.01
*CONN
*I *21:Q O *D sky130_fd_sc_hd__dfxtp_1
*I *11:A I *D sky130_fd_sc_hd__nor2_1
*CAP
1 netb 0.005
2 *11:A 0.001
3 *11:A *10:A 0.0098
*RES
1 *21:Q netb 10
*END
"""

# A low-coupling pair: net C (=*3) and net D (=*4) share a tiny coupling cap
# but C has a large ground cap => low ratio => must NEVER be a violation.
LOWCOUP_SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "lowcoup"
*DIVIDER /
*DELIMITER :
*C_UNIT 1 PF

*NAME_MAP
*3 netc
*4 netd
*30 _u4_
*31 _u5_

*D_NET *3 0.5
*CONN
*I *30:Q O *D sky130_fd_sc_hd__dfxtp_1
*CAP
1 netc 0.5
2 netc netd 0.001
*RES
*END

*D_NET *4 0.5
*CONN
*I *31:Q O *D sky130_fd_sc_hd__dfxtp_1
*CAP
1 netd 0.5
2 netd netc 0.001
*RES
*END
"""


def _timing(pins: dict, vdd: float = 1.8) -> dict:
    return {"tool": "OpenSTA", "design": "synth", "time_unit": "ns",
            "vdd_v": vdd, "pins": pins}


# overlapping windows: both drivers switch in the same interval
TIMING_OVERLAP = _timing({
    "_u0_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2, "arr_fall_min": 1.0,
               "arr_fall_max": 1.2, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
    "_u2_/Q": {"arr_rise_min": 1.05, "arr_rise_max": 1.25, "arr_fall_min": 1.05,
               "arr_fall_max": 1.25, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
})

# non-overlapping windows: aggressor switches far away in time
TIMING_DECOUPLED = _timing({
    "_u0_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2, "arr_fall_min": 1.0,
               "arr_fall_max": 1.2, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
    "_u2_/Q": {"arr_rise_min": 8.0, "arr_rise_max": 8.2, "arr_fall_min": 8.0,
               "arr_fall_max": 8.2, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
})


# ===========================================================================
# SPEF parsing
# ===========================================================================
def test_parse_spef_name_map_and_units():
    sp = m.parse_spef(SYNTH_SPEF)
    assert sp["name_map"]["*1"] == "neta"
    assert sp["name_map"]["*2"] == "netb"
    assert sp["c_unit_pf"] == pytest.approx(1.0)  # PF
    assert sp["delimiter"] == ":"


def test_parse_spef_node_attribution_to_real_net():
    """The coupling cap is on nodes *10:A and *11:A. *10:A is a LOAD of net
    *1, *11:A is a LOAD of net *2. The pair MUST be attributed to {*1, *2},
    NOT to the instance ids {*10, *11}."""
    sp = m.parse_spef(SYNTH_SPEF)
    keys = list(sp["pair_cc"].keys())
    assert len(keys) == 1
    assert keys[0] == frozenset({"*1", "*2"})
    # the coupling magnitude is summed from both D_NETs that listed it
    assert sp["pair_cc"][frozenset({"*1", "*2"})] == pytest.approx(0.0098 * 2)
    # the bogus instance-id nets must NOT appear
    assert "*10" not in sp["cg"] and "*10" not in sp["cc"]
    assert "*11" not in sp["cg"] and "*11" not in sp["cc"]


def test_parse_spef_ground_caps_on_real_net():
    sp = m.parse_spef(SYNTH_SPEF)
    # net *1 ground = 0.0001 (neta) + 0.0001 (*10:A) = 0.0002
    assert sp["cg"]["*1"] == pytest.approx(0.0002)
    # net *2 ground = 0.005 (netb) + 0.001 (*11:A) = 0.006
    assert sp["cg"]["*2"] == pytest.approx(0.006)


def test_parse_spef_driver_pins():
    sp = m.parse_spef(SYNTH_SPEF)
    assert sp["net_driver_pins"]["*1"] == ["_u0_/Q"]
    assert sp["net_driver_pins"]["*2"] == ["_u2_/Q"]
    assert sp["net_load_pins"]["*1"] == ["_u1_/A"]


def test_parse_spef_input_port_is_driver():
    """An input port (*P x I) is an EXTERNAL driver of its net; an output port
    (*P y O) is a load. This must not be conflated with *I direction."""
    spef = (
        "*C_UNIT 1 PF\n*DELIMITER :\n*NAME_MAP\n*1 din\n*2 dout\n"
        "*D_NET *1 0.01\n*CONN\n*P din I\n*I *5:A I *D INV\n*CAP\n1 din 0.01\n*RES\n*END\n"
        "*D_NET *2 0.01\n*CONN\n*P dout O\n*I *5:Y O *D INV\n*CAP\n1 dout 0.01\n*RES\n*END\n"
    )
    sp = m.parse_spef(spef)
    # input port din drives net *1
    assert "din" in sp["net_driver_pins"]["*1"]
    # output port dout is a load of net *2 (driven internally by *5:Y).
    # *5 is not in NAME_MAP here, so the pin token stays raw '*5:Y'.
    assert "dout" in sp["net_load_pins"]["*2"]
    assert "*5:Y" in sp["net_driver_pins"]["*2"]


# ===========================================================================
# window computation + overlap
# ===========================================================================
def test_compute_net_windows_from_driver():
    sp = m.parse_spef(SYNTH_SPEF)
    nw = m.compute_net_windows(sp["net_driver_pins"], TIMING_OVERLAP["pins"])
    # net *1 window comes from _u0_/Q (1.0 .. 1.2 + slew 0.05)
    assert nw["*1"]["driven"] is True
    lo, hi = nw["*1"]["win"]
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.25)  # 1.2 + 0.05 slew pad


def test_windows_overlap_logic():
    assert m._windows_overlap((1.0, 2.0), (1.5, 3.0)) is True
    assert m._windows_overlap((1.0, 2.0), (5.0, 6.0)) is False
    # unknown window => conservatively assume overlap
    assert m._windows_overlap(None, (5.0, 6.0)) is True
    assert m._windows_overlap((1.0, 2.0), None) is True


# ===========================================================================
# the full scorer
# ===========================================================================
def test_scorer_always_advisory_verdict():
    """The verdict is ALWAYS the single advisory value, regardless of the
    coupling/overlap outcome — no PASS/FAIL split that implies sign-off."""
    v_overlap = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP)
    v_decoup = m.score_si_timing_aware(SYNTH_SPEF, TIMING_DECOUPLED)
    assert v_overlap["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v_decoup["verdict"] == "SI_TIMING_AWARE_SCREEN"
    # no FAIL/PASS sign-off verdict must ever be emitted
    assert "FAIL" not in v_overlap["verdict"]
    assert "PASS" not in v_overlap["verdict"]


def test_scorer_overlap_high_coupling_is_high_watchlist():
    """Strongly coupled pair (ratio >> margin) whose driver windows OVERLAP is
    flagged onto the HIGH advisory watch-list — NOT a build-failing violation.
    The advisory verdict is still emitted."""
    v = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP,
                                vdd_v=1.8, noise_margin_mv=100.0)
    assert v["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v["watchlist_high_count"] >= 1
    assert v["pairs_decoupled_by_window"] == 0
    # the HIGH entries are the overlap+over-margin pairs
    high = [e for e in v["watchlist"] if e["priority"] == "high"]
    assert high, "expected a HIGH watch-list entry"
    worst = high[0]
    assert worst["victim"] in ("neta", "netb")
    assert worst["base_noise_mv"] > 100.0
    # the entry is honestly labelled as advisory, not a proven failure
    assert "flagged" in worst["note"].lower()
    assert "not a proven failure" in worst["note"].lower()


def test_scorer_nonoverlap_decouples_to_safe():
    """SAME coupling, but the aggressor switches in a non-overlapping window
    => decoupled => conclusively safe, empty watch-list. This is the
    conclusive-in-one-direction upgrade over the floating-victim advisory."""
    v = m.score_si_timing_aware(SYNTH_SPEF, TIMING_DECOUPLED,
                                vdd_v=1.8, noise_margin_mv=100.0)
    assert v["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v["watchlist_high_count"] == 0
    assert v["watchlist_count"] == 0
    assert v["pairs_decoupled_by_window"] >= 1


def test_scorer_low_coupling_never_flagged():
    """A low-coupling pair (large Cg) must NEVER land on any watch-list even
    with overlapping windows — no fabricated flags."""
    timing = _timing({
        "_u4_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2, "arr_fall_min": 1.0,
                   "arr_fall_max": 1.2, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
        "_u5_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2, "arr_fall_min": 1.0,
                   "arr_fall_max": 1.2, "slew_rise_max": 0.05, "slew_fall_max": 0.05},
    })
    v = m.score_si_timing_aware(LOWCOUP_SPEF, timing,
                                vdd_v=1.8, noise_margin_mv=100.0)
    assert v["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v["watchlist_high_count"] == 0
    assert v["watchlist_low_count"] == 0
    assert v["watchlist_count"] == 0
    # ratio 0.001/(0.001+0.5) ~ 0.002 -> ~3.6 mV, far below margin
    assert v["max_base_noise_mv"] < 100.0


def test_scorer_driven_damping_applied():
    """A driven victim's gated noise is the base noise * damping derate."""
    v = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP)
    high = [e for e in v["watchlist"] if e["priority"] == "high"]
    e = high[0]
    assert e["victim_driven"] is True
    assert e["gated_noise_mv"] == pytest.approx(
        e["base_noise_mv"] * v["driven_damping_derate"], rel=1e-6)


def test_scorer_deterministic():
    """Same inputs -> byte-identical verdict (determinism)."""
    a = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP)
    b = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_scorer_margin_tunable():
    """Raising the margin above the gated noise clears the HIGH watch-list
    (the verdict stays the single advisory value either way)."""
    v_hi = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP,
                                   noise_margin_mv=2000.0)
    assert v_hi["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v_hi["watchlist_high_count"] == 0
    assert v_hi["watchlist_count"] == 0


def test_scorer_honesty_scope_strings():
    """The report must DISCLAIM commercial equivalence, name the model, and be
    explicit that it is CONCLUSIVE ONLY in the decoupled-safe direction while
    the flagged direction is an ADVISORY watch needing foundry-calibrated
    models (CCS-Noise / RLC(K)) — a physical need, not tool lock-in."""
    v = m.score_si_timing_aware(SYNTH_SPEF, TIMING_OVERLAP)
    blob = (v["scope"] + " " + v["method"]).lower()
    assert "screen" in blob
    assert "advisory" in blob
    assert "not" in blob and "commercial" in blob
    assert "lumped" in blob
    assert "rlc" in blob or "transmission-line" in blob
    # conclusive-only-in-one-direction honesty
    assert "conclusive" in blob and "decoupled" in blob
    # the flagged direction needs foundry-calibrated noise models
    assert "ccs-noise" in blob
    # it is a physical need, not commercial-tool lock-in
    assert "lock-in" in blob


def test_scorer_chip_agnostic_no_hardcoded_names():
    """No chip-specific net/signal name appears in the program source.

    `chip_top` is intentionally NOT forbidden: it is the plugin-wide generic
    top-module placeholder (a `top` PARAMETER default in examples), not a
    chip-specific net name. The scorer never matches on net names — it derives
    everything from the SPEF/timing-JSON data."""
    src = PROG.read_text().lower()
    for forbidden in ("mdio", "espi", "sgmii", "wdata", "phyad", "rdata",
                      "clause45", "regad"):
        assert forbidden not in src, f"hardcoded chip token: {forbidden}"


# ===========================================================================
# OpenSTA TCL recipe
# ===========================================================================
def test_build_tcl_has_required_commands():
    tcl = m.build_opensta_si_tcl(
        liberty="/p/sky130.lib", netlist="/p/net.v", top="chip_top",
        sdc="/p/c.sdc", spef="/p/x.spef", out_json="/p/out.json")
    for cmd in ("read_liberty /p/sky130.lib", "read_verilog /p/net.v",
                "link_design chip_top", "read_sdc /p/c.sdc",
                "read_spef /p/x.spef", "report_arrival", "report_slews",
                "sta::redirect_string_begin", "get_pins -hierarchical *",
                "get_ports *"):
        assert cmd in tcl, f"TCL missing: {cmd}"
    # emits the documented JSON keys
    for k in ("arr_rise_min", "arr_rise_max", "slew_rise_max"):
        assert k in tcl


def test_build_tcl_extra_lefs_liberties():
    # v0.2.55: standalone OpenSTA (`sta`) has NO `read_lef` command (that is an
    # OpenROAD command) — emitting it aborted the whole TCL at line 1 with
    # "invalid command name read_lef", leaving a sub-1KB stub log the STA gate
    # then rejected. OpenSTA derives all timing from Liberty + Verilog + SDC +
    # SPEF; LEF is physical-only and neither read nor needed. The TCL must NOT
    # contain read_lef, and the macro liberties must still be read.
    tcl = m.build_opensta_si_tcl(
        liberty="/p/a.lib", netlist="/p/n.v", top="t", sdc="/p/c.sdc",
        spef="/p/x.spef", out_json="/p/o.json",
        extra_lefs=["/p/tech.lef", "/p/cell.lef"],
        extra_liberties=["/p/macro.lib"])
    assert "read_lef" not in tcl
    assert "read_liberty /p/a.lib" in tcl
    assert "read_liberty /p/macro.lib" in tcl


def test_timing_json_shape_documented():
    assert "pins" in m.TIMING_JSON_SHAPE
    rec = m.TIMING_JSON_SHAPE["pins"]["<pin_full_name>"]
    for k in ("arr_rise_min", "arr_rise_max", "arr_fall_min", "arr_fall_max",
              "slew_rise_max", "slew_fall_max"):
        assert k in rec


# ===========================================================================
# public API + CLI
# ===========================================================================
def test_run_public_api_writes_artifacts(tmp_path):
    spef = tmp_path / "x.spef"
    spef.write_text(SYNTH_SPEF)
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(TIMING_OVERLAP))
    out_json = tmp_path / "si.json"
    out_rpt = tmp_path / "si.rpt"
    v = m.run_si_signoff_timing_aware(
        spef, tj, out_json=out_json, out_rpt=out_rpt)
    assert out_json.is_file() and out_rpt.is_file()
    assert v["spef"] == str(spef)
    body = json.loads(out_json.read_text())
    assert body["verdict"] == "SI_TIMING_AWARE_SCREEN"
    rpt = out_rpt.read_text()
    assert "NOT a full RLC(K)" in rpt
    assert "watchlist_high_count" in rpt


def test_cli_score_exit_code_advisory_default_zero(tmp_path):
    """DEFAULT is advisory: even with an overlap+over-margin HIGH watch-list,
    the screen exits 0 (it never fails a build)."""
    spef = tmp_path / "x.spef"
    spef.write_text(SYNTH_SPEF)
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(TIMING_OVERLAP))
    r = subprocess.run(
        [sys.executable, str(PROG), "score", str(spef), str(tj)],
        capture_output=True, text=True)
    assert r.returncode == 0  # advisory => never fails a build
    out = json.loads(r.stdout)
    assert out["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert out["watchlist_high_count"] >= 1


def test_cli_score_strict_exits_one_on_high_watchlist(tmp_path):
    """The opt-in --strict gate exits 1 iff the HIGH advisory watch-list is
    non-empty (the verdict is still the advisory value)."""
    spef = tmp_path / "x.spef"
    spef.write_text(SYNTH_SPEF)
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(TIMING_OVERLAP))
    r = subprocess.run(
        [sys.executable, str(PROG), "score", str(spef), str(tj), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert json.loads(r.stdout)["verdict"] == "SI_TIMING_AWARE_SCREEN"


def test_cli_score_exit_code_advisory_no_flags(tmp_path):
    """A low-coupling design has an empty watch-list -> exit 0 in both default
    and --strict modes."""
    spef = tmp_path / "x.spef"
    spef.write_text(LOWCOUP_SPEF)
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(_timing({
        "_u4_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2,
                   "arr_fall_min": 1.0, "arr_fall_max": 1.2,
                   "slew_rise_max": 0.05, "slew_fall_max": 0.05},
        "_u5_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2,
                   "arr_fall_min": 1.0, "arr_fall_max": 1.2,
                   "slew_rise_max": 0.05, "slew_fall_max": 0.05},
    })))
    r = subprocess.run(
        [sys.executable, str(PROG), "score", str(spef), str(tj)],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert json.loads(r.stdout)["verdict"] == "SI_TIMING_AWARE_SCREEN"
    r2 = subprocess.run(
        [sys.executable, str(PROG), "score", str(spef), str(tj), "--strict"],
        capture_output=True, text=True)
    assert r2.returncode == 0  # no HIGH watch-list -> strict still passes


def test_cli_emit_tcl(tmp_path):
    out_tcl = tmp_path / "emit.tcl"
    r = subprocess.run(
        [sys.executable, str(PROG), "emit-tcl", str(out_tcl),
         "--liberty", "/p/a.lib", "--netlist", "/p/n.v", "--top", "t",
         "--sdc", "/p/c.sdc", "--spef", "/p/x.spef",
         "--out-json", "/p/o.json"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert out_tcl.is_file()
    assert "read_spef /p/x.spef" in out_tcl.read_text()


# ===========================================================================
# REAL-SPEF validation. The premise is PUBLISHED extraction output, and the
# premise is CHECKED (vibe-ic#1037), not assumed from a walk. A skip here names
# which absence occurred — "the real-data anchor was withdrawn" and "nothing of
# this kind was ever published here" are different facts and do not share a
# message.
# ===========================================================================
def test_real_spef_parses_and_attributes(record_property):
    sel = _real_spef()
    if sel.path is None:
        pytest.skip(sel.reason)
    sp_path = sel.path
    # SAY WHICH FILE — the premise is disclosed, not trusted (vibe-ic#1037).
    record_property("real_spef_source", rd.provenance(sp_path))
    record_property("real_spef_eligible_of_tracked",
                    f"{sel.eligible}/{sel.considered}")
    sp = m.parse_spef(sp_path.read_text(errors="replace"))
    # a real OpenRCX SPEF must carry coupling pairs + named nets + drivers
    assert len(sp["pair_cc"]) > 0
    assert len(sp["name_map"]) > 0
    assert len(sp["net_driver_pins"]) > 0
    # node->net attribution must NOT leak instance ids as nets: every net in a
    # coupling pair should be a real D_NET id that has a ground cap OR a driver
    real_nets = set(sp["cg"]) | set(sp["net_driver_pins"]) | set(sp["net_load_pins"])
    leaked = [n for pr in sp["pair_cc"] for n in pr if n not in real_nets]
    assert leaked == [], (f"coupling attributed to non-net ids: {leaked[:5]} "
                          f"(in {rd.provenance(sp_path)})")


def test_real_spef_scores_with_synthetic_windows(record_property):
    """Score the real SPEF against a permissive all-overlap timing JSON
    (every net's driver in one big window). Validates the scorer runs on real
    extracted parasitics end-to-end and is deterministic; with no decoupling
    it must reproduce the floating bound on the truly coupling-dominated nets
    (i.e. it does NOT crash and the verdict is well-formed)."""
    sel = _real_spef()
    if sel.path is None:
        pytest.skip(sel.reason)
    sp_path = sel.path
    record_property("real_spef_source", rd.provenance(sp_path))
    record_property("real_spef_eligible_of_tracked",
                    f"{sel.eligible}/{sel.considered}")
    sp = m.parse_spef(sp_path.read_text(errors="replace"))
    # build a timing JSON: every driver pin switches in [0,1] ns (all overlap)
    pins = {}
    for drivers in sp["net_driver_pins"].values():
        for d in drivers:
            pins[d] = {"arr_rise_min": 0.0, "arr_rise_max": 1.0,
                       "arr_fall_min": 0.0, "arr_fall_max": 1.0,
                       "slew_rise_max": 0.05, "slew_fall_max": 0.05}
    tj = _timing(pins)
    spef_text = sp_path.read_text(errors="replace")
    v = m.score_si_timing_aware(spef_text, tj, vdd_v=1.8, noise_margin_mv=100.0)
    # the verdict is ALWAYS the single advisory value — never a sign-off PASS/FAIL
    assert v["verdict"] == "SI_TIMING_AWARE_SCREEN"
    assert v["nets_analyzed"] > 0
    assert v["coupling_pairs"] > 0
    assert 0.0 <= v["max_gated_noise_mv"] <= v["max_base_noise_mv"] + 1e-6
    # high+low watch-list partition is internally consistent
    assert v["watchlist_count"] == v["watchlist_high_count"] + v["watchlist_low_count"]
    # determinism on real data
    v2 = m.score_si_timing_aware(sp_path.read_text(errors="replace"), tj,
                                 vdd_v=1.8, noise_margin_mv=100.0)
    assert v["watchlist_high_count"] == v2["watchlist_high_count"]
    assert v["watchlist_low_count"] == v2["watchlist_low_count"]

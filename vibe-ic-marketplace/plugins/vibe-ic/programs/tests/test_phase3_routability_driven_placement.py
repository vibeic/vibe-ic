"""Phase-3 CONGESTION-DRIVEN (routability-driven) global placement.

A full-OpenTitan-class AES peripheral (~39k cells) has high-fanout crypto
datapath nets (SBox / MixColumns wide-XOR trees, key-schedule fanout) that
create detailed-route congestion, so the design only routes at a very sparse
die. OpenROAD's `global_placement -routability_driven` (RePlAce routability
mode) estimates routing congestion during placement and spreads / inflates
cells in congested regions so such a design can route at a denser die. It is
a placement-QUALITY knob: it changes NOTHING about connectivity or logic and
OpenROAD reverts the routability loop if it diverges — so `_build_pnr_tcl_text`
emits it by DEFAULT (chip-AGNOSTIC, applies to every design).

`placement_padding_sites` is an OPTIONAL, version-correct extra congestion
knob (`set_placement_padding -global`), left OFF by default (padding changes
every design unconditionally).

HONESTY: this is the STANDARD OSS mechanism for a congested design; it does
NOT by itself GUARANTEE a denser route. The empirical benefit (does AES now
route at a denser die?) needs a live PnR run to confirm — these tests pin the
EMITTER (correct flag + well-formed TCL + no structural regression), not the
routing outcome.

Flag names verified against the container's OpenROAD 26Q1-990-g15af3a5c0:
    global_placement [...] [-routability_driven] [...] [-density target_density]
    set_placement_padding -global|-masters|-instances [-right N] [-left N]
Both parse cleanly (a bare `global_placement -routability_driven -density 0.5`
errors only with `GPL-0130 No rows defined` — a runtime "no design" error, not
"unknown option").
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")
_STUB = 'proc unknown {args} { return "" }\n'


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _build(**overrides) -> str:
    """Build the COMPLETE pnr.tcl from the REAL sub-block builders (exactly
    as step_pnr wires them), so the well-formedness / regression pins see
    the true emission — a hand-rolled stand-in could be balanced while the
    real template is not."""
    pdk = _pdk()
    out_dir_c = "/out"
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290),
        liberty_path="", container="")
    kw = dict(
        tech_lef_c="/pdk/tech.lef", cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/w/netlist.v", top="chip_top",
        sdc_c="/w/chip_top.sdc",
        dont_use_block=R._dont_use_tcl(pdk),
        metal_prefix=pdk.metal_prefix, die_w=300, die_h=300,
        core_pad=10, core_w=280, core_h=280, site=pdk.site,
        out_dir_c=out_dir_c,
        tapcell_block=R._build_tapcell_tcl(pdk),
        pdn_block=R._build_pdn_tcl(pdk),
        util=0.45,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, out_dir_c),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO"),
        clk_buf="sky130_fd_sc_hd__clkbuf_4",
        clk_buf_root="sky130_fd_sc_hd__clkbuf_16",
        routing_constraint_tcl="",
        pg_cleanup_block=R._pg_net_cleanup_tcl(),
        spef_repair_block=R._post_route_spef_repair_tcl(out_dir_c, "/nope"),
        antenna_repair_block=R._antenna_repair_tcl(pdk),
        filler_block="",
    )
    kw.update(overrides)
    return R._build_pnr_tcl_text(**kw)


def _command_lines(tcl: str):
    """Non-comment, non-blank lines (the doctrine comment names the flags
    while explaining them, so content assertions must scan COMMANDS only)."""
    return [ln for ln in tcl.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def _gp_cmd_lines(tcl: str):
    return [ln for ln in _command_lines(tcl)
            if ln.lstrip().startswith("global_placement")]


# ── default: routability-driven is ON, density kept, exactly once ──────────

def test_default_emits_routability_driven_global_placement():
    tcl = _build()
    gp = _gp_cmd_lines(tcl)
    assert len(gp) == 1, f"expected exactly one global_placement: {gp}"
    assert "-routability_driven" in gp[0]
    # -density must still be present with the util value.
    assert "-density 0.45" in gp[0]
    assert gp[0].strip() == "global_placement -routability_driven -timing_driven -density 0.45"


def test_density_flag_tracks_util_value():
    for u in (0.30, 0.55, 0.7):
        gp = _gp_cmd_lines(_build(util=u))[0]
        assert f"-density {u}" in gp
        assert "-routability_driven" in gp


def test_routability_driven_is_the_default_when_arg_omitted():
    # The enhancement must be DEFAULT-ON without step_pnr passing anything.
    assert "-routability_driven" in _gp_cmd_lines(_build())[0]


# ── gate branch: routability can be turned OFF (chip-AGNOSTIC signal) ───────

def test_routability_off_emits_plain_density_placement():
    tcl = _build(routability_driven=False)
    gp = _gp_cmd_lines(tcl)
    assert len(gp) == 1
    assert "-routability_driven" not in gp[0]
    # timing_driven remains DEFAULT-ON independently of routability.
    assert gp[0].strip() == "global_placement -timing_driven -density 0.45"


# ── optional padding knob: OFF by default, correct syntax when enabled ─────

def test_placement_padding_off_by_default():
    assert "set_placement_padding" not in _command_lines_join(_build())


def test_placement_padding_zero_is_off():
    assert "set_placement_padding" not in _command_lines_join(
        _build(placement_padding_sites=0))


def test_placement_padding_emitted_before_global_placement_when_enabled():
    tcl = _build(placement_padding_sites=2)
    cmds = _command_lines(tcl)
    pad = [ln for ln in cmds if ln.lstrip().startswith("set_placement_padding")]
    assert len(pad) == 1
    assert pad[0].strip() == "set_placement_padding -global -left 2 -right 2"
    # padding must appear BEFORE global_placement in command order.
    pad_idx = next(i for i, ln in enumerate(cmds)
                   if ln.lstrip().startswith("set_placement_padding"))
    gp_idx = next(i for i, ln in enumerate(cmds)
                  if ln.lstrip().startswith("global_placement"))
    assert pad_idx < gp_idx
    # global_placement itself is unchanged (still routability-driven).
    assert "-routability_driven" in cmds[gp_idx]


def _command_lines_join(tcl: str) -> str:
    return "\n".join(_command_lines(tcl))


# ── well-formedness: balanced braces + real tclsh parse ────────────────────

def test_full_tcl_braces_balanced():
    for kw in ({}, {"routability_driven": False},
               {"placement_padding_sites": 1},
               {"routability_driven": False, "placement_padding_sites": 3}):
        tcl = _build(**kw)
        assert tcl.count("{") == tcl.count("}"), (kw, tcl.count("{"),
                                                  tcl.count("}"))


@needs_tclsh
@pytest.mark.parametrize("kw", [
    {}, {"routability_driven": False},
    {"placement_padding_sites": 1},
    {"routability_driven": False, "placement_padding_sites": 4},
])
def test_full_tcl_parses_in_tclsh(tmp_path, kw):
    """The emitted TCL must survive a real Tcl parser in EVERY branch — an
    invalid flag line would otherwise break EVERY phase3 run (the template
    is emitted unconditionally)."""
    tcl = _build(**kw).replace("\nexit\n", "\nputs PNR_TCL_END\n")
    script = tmp_path / "pnr.tcl"
    script.write_text(_STUB + tcl)
    res = _pr.run([tclsh, str(script)], capture_output=True,
                         text=True)
    assert res.returncode == 0, res.stderr
    assert "missing close-bracket" not in res.stderr
    assert "PNR_TCL_END" in res.stdout


# ── regression: the rest of the template is UNCHANGED in structure ─────────

def test_surrounding_flow_structure_unchanged():
    """Only the global_placement line (and the optional padding line) may
    change; every other stage anchor — floorplan, tracks, pin placement,
    detailed placement, CTS, global/detailed route, DEF checkpoints — must
    remain exactly present and in order."""
    tcl = _build()
    anchors = [
        "initialize_floorplan",
        "make_tracks",
        "write_def /out/floorplan.def",
        "global_placement",
        "detailed_placement",
        "write_def /out/placed.def",
        "clock_tree_synthesis",
        "write_def /out/post_cts.def",
        "write_def /out/post_hold.def",
        "global_route",
        "detailed_route",
        "write_def /out/routed.def",
        "write_verilog /out/chip_top_pnr.v",
        "report_design_area",
        "exit",
    ]
    last = -1
    for a in anchors:
        idx = tcl.find(a)
        assert idx != -1, f"missing flow anchor: {a}"
        assert idx > last, f"flow anchor out of order: {a}"
        last = idx


def test_padding_does_not_perturb_surrounding_structure():
    """Turning padding on must ONLY insert the padding line — the whole
    template must be identical apart from that one added line."""
    base = _build()
    padded = _build(placement_padding_sites=1)
    added = [ln for ln in padded.splitlines() if ln not in base.splitlines()]
    assert added == ["set_placement_padding -global -left 1 -right 1"]


def test_default_only_adds_routability_flag_vs_plain():
    """A clean-design regression proof: routability-off vs routability-on
    differ ONLY by the ` -routability_driven` token on the global_placement
    line — nothing else in the template moves."""
    plain = _build(routability_driven=False)
    routab = _build()
    assert plain.replace(
        "global_placement -timing_driven -density 0.45",
        "global_placement -routability_driven -timing_driven -density 0.45") == routab


# ── container OpenROAD flag verification (runs where openroad is on PATH) ───

@pytest.mark.skipif(shutil.which("openroad") is None,
                    reason="openroad not on PATH (container-only tool)")
def test_openroad_accepts_routability_driven_flag():
    """When openroad is reachable (inside the iic-osic-tools container CI),
    assert `help global_placement` advertises the exact flags we emit."""
    res = _pr.run(
        ["openroad", "-no_init", "-exit"],
        input="help global_placement\n",
        capture_output=True, text=True)
    out = res.stdout + res.stderr
    assert "-routability_driven" in out
    assert "-timing_driven" in out
    assert re.search(r"-density\s+target_density", out)


# -- timing-driven placement: DEFAULT-ON slack-weighted global placement ----
# ORGANIC (sha256 x sky130A): routability_driven placement left the SS
# post-route setup WNS deeply negative because global placement was BLIND to
# the 25.907 ns clock. `-timing_driven` net-weights placement by setup slack so
# critical-path cells cluster. Negative control: git-checkout the pre-fix runner
# -> these assertions fail (no global_placement line carries -timing_driven).


def test_timing_driven_on_by_default():
    gp = _gp_cmd_lines(_build())
    assert len(gp) == 1
    assert "-timing_driven" in gp[0]


def test_timing_driven_default_line_is_exact():
    assert _gp_cmd_lines(_build())[0].strip() == (
        "global_placement -routability_driven -timing_driven -density 0.45")


def test_timing_driven_off_when_disabled():
    gp = _gp_cmd_lines(_build(timing_driven=False))
    assert len(gp) == 1
    assert "-timing_driven" not in gp[0]
    assert gp[0].strip() == "global_placement -routability_driven -density 0.45"


def test_timing_and_routability_both_off_is_plain_density():
    gp = _gp_cmd_lines(_build(routability_driven=False, timing_driven=False))
    assert len(gp) == 1
    assert gp[0].strip() == "global_placement -density 0.45"


# ── approach (a): multi-corner liberty for the PnR session (ss setup/ff hold) ──
# Repair the SLOW (ss) setup corner BEFORE detailed route by loading the PDK's
# OWN ss/tt/ff corner libs into the PnR session (define_corners + read_liberty
# -corner), so repair_timing -setup optimizes ss instead of only tt. RED on the
# pre-fix runner: `_build_pnr_tcl_text` has no `corner_liberty_block` kwarg
# (TypeError) and `_v1_5_37a_multicorner_pnr_block` does not exist
# (AttributeError) — every assertion below fails until the fix is wired in.

def _liberty_cmd_lines(tcl: str):
    return [ln for ln in _command_lines(tcl)
            if ln.lstrip().startswith("read_liberty")]


def test_corner_liberty_none_is_byte_identical_single_read_liberty():
    # Pure additive knob: OFF (None) keeps the exact single-corner read_liberty.
    assert _liberty_cmd_lines(_build()) == ["read_liberty /pdk/lib.lib"]
    assert _liberty_cmd_lines(_build(corner_liberty_block=None)) == [
        "read_liberty /pdk/lib.lib"]


def test_corner_liberty_block_replaces_single_read_liberty():
    block = ("define_corners ss tt ff\n"
             "read_liberty -corner ss /pdk/ss.lib\n"
             "read_liberty -corner tt /pdk/tt.lib\n"
             "read_liberty -corner ff /pdk/ff.lib")
    tcl = _build(corner_liberty_block=block)
    libs = _liberty_cmd_lines(tcl)
    # the bare single-corner read_liberty is GONE, replaced by per-corner reads.
    assert "read_liberty /pdk/lib.lib" not in libs, libs
    assert libs == [
        "read_liberty -corner ss /pdk/ss.lib",
        "read_liberty -corner tt /pdk/tt.lib",
        "read_liberty -corner ff /pdk/ff.lib",
    ]
    cmds = _command_lines(tcl)
    assert "define_corners ss tt ff" in cmds
    # corners+libs are loaded BEFORE read_verilog so repair sees ss on the
    # placed cells that route in the normal detailed-route pass.
    dc_idx = next(i for i, ln in enumerate(cmds)
                  if ln.startswith("define_corners"))
    rv_idx = next(i for i, ln in enumerate(cmds)
                  if ln.startswith("read_verilog"))
    assert dc_idx < rv_idx


def test_multicorner_block_none_when_pdk_lacks_distinct_corners(monkeypatch):
    # <2 distinct process libs -> None -> caller keeps single-corner PnR
    # (chip/PDK-AGNOSTIC: a PDK that ships one lib is never forced multi-corner).
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs",
                        lambda *a, **k: {"TT": "/pdk/tt.lib"})
    assert R._v1_5_37a_multicorner_pnr_block(
        Path("/proj"), _pdk(), "", "/pdk/tt.lib") is None
    # all corners collapsing to the SAME lib is also <2 distinct -> None.
    monkeypatch.setattr(
        R, "_resolve_signoff_corner_libs",
        lambda *a, **k: {"SS": "/x.lib", "TT": "/x.lib", "FF": "/x.lib"})
    assert R._v1_5_37a_multicorner_pnr_block(
        Path("/proj"), _pdk(), "", "/x.lib") is None


def test_multicorner_block_built_from_pdk_own_corner_libs(monkeypatch):
    monkeypatch.setattr(
        R, "_resolve_signoff_corner_libs",
        lambda *a, **k: {"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib",
                         "FF": "/pdk/ff.lib"})
    out = R._v1_5_37a_multicorner_pnr_block(
        Path("/proj"), _pdk(), "", "/pdk/tt.lib")
    lines = out.splitlines()
    assert lines[0] == "define_corners ss tt ff"
    assert "read_liberty -corner ss /pdk/ss.lib" in lines
    assert "read_liberty -corner tt /pdk/tt.lib" in lines
    assert "read_liberty -corner ff /pdk/ff.lib" in lines


def test_multicorner_block_is_best_effort_none_on_resolver_failure(monkeypatch):
    # A resolver crash must NEVER take down the PnR flow — best-effort -> None.
    def _boom(*a, **k):
        raise RuntimeError("no corner libs available")
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs", _boom)
    assert R._v1_5_37a_multicorner_pnr_block(
        Path("/proj"), _pdk(), "", "/pdk/tt.lib") is None

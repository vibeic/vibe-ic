"""Unit tests for the ORGANIC-20260531 Phase-3 sign-off-chain emitters in
phase3_one_shot_runner.py.

All tests are docker-free: container-touching emitters are exercised by
monkeypatching `_docker_exec` with synthetic OpenROAD PSM / antenna /
filler_placement stdout, then asserting that (a) the emitted reports carry
the exact keyword / tool-signature anchors the downstream gate checks
(eda_report_audit:ir_drop / :em, metal_fill_density_check, si_crosstalk_check)
require, and (b) the SPEF extract.tcl discovers the OpenRCX captable and runs
extract_parasitics -ext_model_file → write_spef (v0.2.5; estimate is fallback-only),
and (c) spare_cells.json now carries a rows[] field
derived deterministically from the existing placement.

Covers the 7 backlog items:
  1 SPEF      — OpenRCX captable discovery + extract_parasitics -ext_model_file (v0.2.5)
  2 IR/EM/SI  — PSM analyze_power_grid report content + gate keywords
  3 Antenna   — check_antennas report re-emitted to audit path
  4 DRC/ERC   — ERC report emitter content (DRC env probe is integration-only)
  5 Metal fill— filler_placement → filled.def + metal_fill.done + density rpt
  6 Spare     — spare_cells.json rows[] field (placement unchanged)
  7 Formal    — confirmed informational-only (no code; asserted via flow yaml)
"""
import importlib
import sys
from pathlib import Path






PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

runner = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Test scaffold — a minimal project with a routed DEF carrying a PDN.
# ---------------------------------------------------------------------------
_DEF_WITH_PDN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
SPECIALNETS 2 ;
    - VGND ( _1_ VNB ) ( _2_ VNB ) + USE GROUND ;
    - VPWR ( _1_ VPB ) ( _2_ VPB ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

_DEF_NO_PDN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
END DESIGN
"""










# ---------------------------------------------------------------------------
# 6. Spare-cell rows[] field (placement unchanged)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Power-net discovery (chip-AGNOSTIC structural parse)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. SPEF extract.tcl uses the OpenRCX captable (v0.2.5 — corrected from the
#    estimate-only recipe; sky130A DOES ship rules.openrcx.sky130A.nom.magic and
#    `extract_parasitics -ext_model_file` writes a real SPEF — validated: spm
#    routed DEF → 1370 rc segments, 268 KB SPEF).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. IR-drop + EM report content (PSM) satisfies the gate keyword checks.
# ---------------------------------------------------------------------------
_PSM_STDOUT = """[INFO PSM-0040] All shapes on net VPWR are connected.
Supply voltage   : 1.80e+00 V
Worstcase voltage: 1.80e+00 V
Average voltage  : 1.80e+00 V
Average IR drop  : 4.96e-05 V
Worstcase IR drop: 1.19e-04 V
########## EM analysis ###############
Maximum current    : 6.85e-05 A
Average current    : 3.28e-06 A
"""




# ---------------------------------------------------------------------------
# 3. Antenna report re-emitted to audit path.
# ---------------------------------------------------------------------------
_ANT_STDOUT = """[INFO ANT-0002] Found 0 net violations.
[INFO ANT-0001] Found 0 pin violations.
"""




# ---------------------------------------------------------------------------
# 3b. v0.2.14 — antenna REPAIR Tcl shape + in-session authoritative result.
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 2b. SI crosstalk screen (deterministic, no container).
# ---------------------------------------------------------------------------
# A tiny IEEE-1481 SPEF with known caps. Net *1 = mostly coupling (dominated),
# net *2 = mostly ground (low coupling). *CAP entries: `idx node val` = ground;
# `idx n1 n2 val` = coupling (credited to both nets).
_SPEF_SAMPLE = """\
*SPEF "ieee 1481-1999"
*DESIGN "toy"
*C_UNIT 1 PF
*D_NET *1 1.0
*CAP
1 *1:1 0.01
2 *1:2 *2:3 0.99
*RES
1 *1:1 *1:2 5.0
*END
*D_NET *2 1.0
*CAP
1 *2:1 0.90
2 *2:3 *1:2 0.10
*END
"""




# ---------------------------------------------------------------------------
# 5. Metal fill via filler_placement.
# ---------------------------------------------------------------------------
_FILL_STDOUT = """=== DESIGN AREA (pre-fill) ===
Design area 2034 um^2 7% utilization.
[INFO DPL-0001] Placed 3298 filler instances.
=== DESIGN AREA (post-fill) ===
Design area 2034 um^2 7% utilization.
"""




# ---------------------------------------------------------------------------
# 4. ERC report emitter content.
# ---------------------------------------------------------------------------
_ERC_STDOUT = """=== ERC: floating nets ===
[INFO] 0 floating nets.
=== ERC metrics ===
"""




# ---------------------------------------------------------------------------
# 8. PERC-equivalent coverage aggregate (ORGANIC-20260601) — Step 32 residual.
# ---------------------------------------------------------------------------
# A core-only DEF (no pads, no diodes) → ESD = N/A; single VPWR/VGND → xdomain
# = N/A. A pad-ring DEF → ESD = MANUAL_REVIEW with a pending checklist.
_DEF_PADRING = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 4 ;
    - _1_ sky130_fd_sc_hd__nor3_1 + PLACED ( 100 100 ) N ;
    - pad_io_0 sky130_fd_io__gpiov2 + PLACED ( 0 0 ) N ;
    - esd_0 sky130_fd_io__top_xres4v2 + PLACED ( 0 200 ) N ;
    - diode_0 sky130_fd_sc_hd__diode_2 + PLACED ( 200 0 ) N ;
END COMPONENTS
SPECIALNETS 2 ;
    - VGND ( _1_ VNB ) + USE GROUND ;
    - VPWR ( _1_ VPB ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

_DEF_MULTI_DOMAIN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 2 ;
- _1_ sky130_fd_sc_hd__nor3_1 + PLACED ( 0 0 ) N ;
- ls0 sky130_fd_sc_hdll__lpflow_lsbuf_lh_isowell_1 + PLACED ( 100 0 ) N ;
END COMPONENTS
SPECIALNETS 4 ;
    - VGND ( _1_ VNB ) + USE GROUND ;
    - VPWR ( _1_ VPB ) + USE POWER ;
    - VPWR_AON ( _2_ VPB ) + USE POWER ;
    - VGND_AON ( _2_ VNB ) + USE GROUND ;
END SPECIALNETS
END DESIGN
"""


class TestParseDefComponents:
    def test_parses_components(self, tmp_path):
        d = tmp_path / "x.def"
        d.write_text(_DEF_PADRING)
        comps = runner._parse_def_components(d)
        masters = {m for _i, m in comps}
        assert "sky130_fd_io__gpiov2" in masters
        assert "sky130_fd_sc_hd__diode_2" in masters
        assert len(comps) == 4

    def test_no_components_block_returns_empty(self, tmp_path):
        d = tmp_path / "x.def"
        d.write_text(_DEF_WITH_PDN)
        assert runner._parse_def_components(d) == []








# ---------------------------------------------------------------------------
# 7. Formal stays informational (no code change) — confirm via flow yaml.
# ---------------------------------------------------------------------------
class TestFormalInformational:
    def test_formal_step_unchanged(self):
        flow = (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml")
        assert flow.is_file()
        text = flow.read_text()
        # Step 5 formal still references the SymbiYosys results contract;
        # there is no new mandatory formal gate added by this change.
        assert "formal" in text.lower()
        assert "results.json" in text


# ---------------------------------------------------------------------------
# v0.2.9 — ESD discharge-path TOPOLOGY check (connectivity half automated).
# Validated against the real Caravel chip_io.def (TOPOLOGY_OK; sizing MANUAL).
# ---------------------------------------------------------------------------




_RING_DEF_HEAD = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
"""
_RING_COMPONENTS = """COMPONENTS 7 ;
- clk_pad sky130_ef_io__gpiov2_pad + PLACED ( 0 0 ) N ;
- vddio0 sky130_ef_io__vddio_hvc_clamped_pad + PLACED ( 0 0 ) N ;
- vssio0 sky130_ef_io__vssio_hvc_clamped_pad + PLACED ( 0 0 ) N ;
- vccd0 sky130_ef_io__vccd_lvc_clamped_pad + PLACED ( 0 0 ) N ;
- vssd0 sky130_ef_io__vssd_lvc_clamped_pad + PLACED ( 0 0 ) N ;
- vdda0 sky130_ef_io__vdda_hvc_clamped_pad + PLACED ( 0 0 ) N ;
{vssa}END COMPONENTS
"""
_RING_NETS = """NETS 2 ;
- vddio_net ( clk_pad VDDIO ) ( vddio0 VDDIO ) ( vssio0 VDDIO ) ( vccd0 VCCD ) ( vssd0 VCCD ) ( vdda0 VDDA ){vssa_p} + USE POWER ;
- vssio_net ( clk_pad VSSIO ) ( vddio0 VSSIO ) ( vssio0 VSSIO ) ( vccd0 VSSD ) ( vssd0 VSSD ) ( vdda0 VSSA ){vssa_g} + USE GROUND ;
END NETS
SPECIALNETS 2 ;
    - VGND ( clk_pad VSSIO ) + USE GROUND ;
    - VPWR ( clk_pad VDDIO ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""






# ---------------------------------------------------------------------------
# v0.2.10 — latch-up well-tap PRESENCE (automates the conclusive 0-tap FAIL).
# Real routed DEFs (spm/subservient/neorv32) ship 0 tap cells → WELLTAP_GAP.
# Only tap-presence is shipped; spacing + device-physics stay MANUAL (an
# adversarial panel showed spatial density/max-distance over-claim from DEF).
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# v0.2.10 — END-TO-END integration on a faithful multi-domain padded chip.
# Composes ALL the v0.2.7-2.10 PERC categories at once (the unit tests each
# exercise one in isolation). Structure mirrors the real Caravel chip_io:
# 3 supply domains (SPECIALNETS) → xdomain MANUAL (not N/A); a gpiov2 + clamped
# pad ring tied to both rails → ESD PRESENT + topology OK; well taps present.
# ---------------------------------------------------------------------------
_PADDED_CHIP_DEF = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 200000 200000 ) ;
COMPONENTS 10 ;
- io_clk sky130_ef_io__gpiov2_pad + PLACED ( 1000 1000 ) N ;
- p_vddio sky130_ef_io__vddio_hvc_clamped_pad + PLACED ( 2000 1000 ) N ;
- p_vssio sky130_ef_io__vssio_hvc_clamped_pad + PLACED ( 3000 1000 ) N ;
- p_vccd sky130_ef_io__vccd_lvc_clamped_pad + PLACED ( 4000 1000 ) N ;
- p_vssd sky130_ef_io__vssd_lvc_clamped_pad + PLACED ( 5000 1000 ) N ;
- p_vdda sky130_ef_io__vdda_hvc_clamped_pad + PLACED ( 6000 1000 ) N ;
- p_vssa sky130_ef_io__vssa_hvc_clamped_pad + PLACED ( 7000 1000 ) N ;
- core0 sky130_fd_sc_hd__nor3_1 + PLACED ( 50000 50000 ) N ;
- tap0 sky130_fd_sc_hd__tapvpwrvgnd_1 + PLACED ( 50500 50000 ) N ;
- ls0 sky130_fd_sc_hdll__lpflow_lsbuf_lh_isowell_1 + PLACED ( 51000 50000 ) N ;
END COMPONENTS
NETS 2 ;
- vpwr_net ( io_clk VDDIO ) ( p_vddio VDDIO ) ( p_vssio VDDIO ) ( p_vccd VCCD ) ( p_vssd VCCD ) ( p_vdda VDDA ) ( p_vssa VDDA ) + USE POWER ;
- vgnd_net ( io_clk VSSIO ) ( p_vddio VSSIO ) ( p_vssio VSSIO ) ( p_vccd VSSD ) ( p_vssd VSSD ) ( p_vdda VSSA ) ( p_vssa VSSA ) + USE GROUND ;
END NETS
SPECIALNETS 6 ;
    - vddio ( io_clk VDDIO ) + USE POWER ;
    - vssio ( io_clk VSSIO ) + USE GROUND ;
    - vccd ( core0 VPB ) + USE POWER ;
    - vssd ( core0 VNB ) + USE GROUND ;
    - vdda ( p_vdda VDDA ) + USE POWER ;
    - vssa ( p_vssa VSSA ) + USE GROUND ;
END SPECIALNETS
END DESIGN
"""




# ---------------------------------------------------------------------------
# v0.2.11 — cross-voltage-domain: robust multi-domain count (NETS+SPECIALNETS)
# + conclusive zero-crossing-cell FAIL. Fixes the real Caravel single-supply
# mis-count (power via NETS, not SPECIALNETS). Presence stays MANUAL (an
# adversarial panel ruled a structural OK over-claims).
# ---------------------------------------------------------------------------


_CARAVEL_LIKE_DEF = """VERSION 5.8 ;
DESIGN chip_io ;
NETS 10 ;
- vccd1 ( a x ) + ROUTED met1 ;
- vccd2 ( b x ) ;
- vdda ( c x ) ;
- vddio ( d x ) ;
- vcchib ( e x ) ;
- vswitch ( f x ) ;
- vssio ( g x ) ;
- vssd1 ( h x ) ;
- vssa ( i x ) ;
- clk ( j x ) ;
END NETS
END DESIGN
"""






# ---------------------------------------------------------------------------
# v0.2.12 — tie/logic-constant net (zero_/one_) declared USE GROUND/POWER must
# NOT count as a power domain. Surfaced by the external-IC sweep: secworks/prince
# has a `zero_` tie-low SPECIALNET (from setundef -zero; hilomap) → was counted as
# a 2nd ground domain → false multi_domain → false XDOMAIN_GAP on a single-supply
# core macro. The fix: _is_constant_net excludes tie nets from the domain count.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# v0.2.30 — SI TIMING-WINDOW-AWARE ADVISORY upgrade wired into
# _emit_si_crosstalk_report. The advisory watch-list is MERGED into the SI
# report WITHOUT touching violations_count / max_crosstalk_noise (the gate-read
# schema). It NEVER blocks the build (advisory). Container-free: we pre-stage
# the OpenSTA timing JSON (the exact shape build_opensta_si_tcl emits) so the
# merge skips the container producer and runs the pure scorer.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# v0.2.30 — PERC GEOMETRY-LAYER (CONCLUSIVE-FAIL-ONLY) wired into
# _emit_perc_equivalent via latchup_esd_spacing_check.run_geometry_layer.
#   * a status in GAP_STATUSES is a CONCLUSIVE geometry FAIL (real gap);
#   * a SPACING_OK / GUARDRING_PRESENT / CLAMP_OK is SEMI_AUTOMATED
#     "necessary-but-not-sufficient" — NEVER an automated device-physics PASS;
#   * INCOMPLETE never over-claims;
#   * device-physics (ESD/latch-up/x-domain) stays MANUAL; the memo states the
#     foundry-data residual VERBATIM.
# ---------------------------------------------------------------------------

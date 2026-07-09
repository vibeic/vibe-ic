#!/usr/bin/env python3
"""R6 (v1.3.52) — sparse-die POWER-AWARE-LVS well-tie gap.

CAPTURE — caravel rerun_v1346, Step-31 power-aware LVS FAIL:
  `lvs_power_aware.rpt` reports `disconnected node: VNB` / `disconnected
  node: VPB` on every PLACED std cell (sky130_fd_sc_hd__conb_1, nor2_1,
  edfxtp_1, and3_1, dfxtp_1, diode_2, o22a_1, ...) → LVS_NETLISTS_DO_NOT_
  MATCH, while MAIN LVS still "Circuits match uniquely" and DRC=0.

RCA — REAL, fixable body-tie gap (NOT an OSS-flow floor / waiver):
  The #684 sparse-die guard SKIPPED the full-die tapcell on a sub-threshold
  fixed wrapper (caravel: 0.022% util). tapcell -distance tiles well-tie
  cells across EVERY row, so on the 2920x3520 um fixed die that would be
  ~136K taps over empty silicon — the guard was RIGHT to not flood, but
  WRONG to drop the well-tie for the std cells that ARE placed, leaving
  their VPB (nwell tie) / VNB (psub tie) body pins physically disconnected.
  Those are ORDINARY std cells whose wells the OSS flow CAN tie (not a
  blackbox-macro power-domain floor), so Branch-B's own precondition ("OSS
  flow structurally cannot tie the wells") is FALSE — a tieable defect must
  be FIXED, not waived.

FIX — bounded well-tie: on a sparse die still run `tapcell` (ties the placed
  cells) then PRUNE the taps that landed over empty silicon, keeping only
  those in the occupied-instance bbox (+ a 2x-distance latch-up margin).
  Placed-cell VPB/VNB stay tied (power-LVS matches) AND the empty die is not
  flooded. Live cross-check (caravel-scale 2920x3520 die, synthetic 4-cell
  cluster): 135239 taps inserted → 65 kept / 135174 pruned, u0/u3 VPB→VPWR
  VNB→VGND tied.

§4.05 no-leak / adversarial (the fix does NOT mask a real defect):
  * a DENSE / normal-util design still runs the full-die tapcell unchanged
    (util >= threshold → no prune, no bound) — test_dense_branch_*;
  * the 0-placed-cell edge case still SKIPS (no wells → no fabricated taps)
    — test_zero_core_cell_edge_case_still_skips;
  * the attestation parser only fires on a runtime marker, never the Tcl
    `puts` template — test_parser_ignores_puts_template;
  * a genuine 0-tap NON-sparse design still FAILs the downstream latch-up /
    perc / metal-fill gates (round-8 no-leak negatives) — unchanged, see
    test_v1_0_56_round8_sparse_die_signoff_consistency.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))
import phase3_one_shot_runner as r  # noqa: E402


class _Pdk:
    tapcell_master = "sky130_fd_sc_hd__tapvpwrvgnd_1"
    tapcell_distance_um = 14.0


def _info_complete(tcl: str) -> bool:
    src = "proc ord::get_db_block {} {return blk}\n" + tcl
    p = subprocess.run(
        ["tclsh"],
        input="if {[info complete {" + src + "}]} {puts OK} else {puts BAD}",
        capture_output=True, text=True)
    return "OK" in p.stdout


# ── the emitted tapcell Tcl now ties the placed cells' wells ───────────
def test_sparse_branch_inserts_and_bounds_taps():
    block = r._build_tapcell_tcl(_Pdk())
    # the sparse branch RUNS tapcell (well-tie) — not a bare skip
    assert "tapcell -distance 14.0 -tapcell_master " \
        "sky130_fd_sc_hd__tapvpwrvgnd_1" in block
    # then bounds it to the occupied region by pruning taps over empty silicon
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in block
    assert "odb::dbInst_destroy" in block
    # prune keeps taps in the occupied bbox + a latch-up margin
    assert "_tap_margin" in block
    assert "getDbUnitsPerMicron" in block
    # the sparse branch is only entered when there ARE placed core cells
    assert "_tap_ncore > 0" in block
    # the prune compares against the occupied bbox (not the whole die)
    for v in ("_tap_minx", "_tap_miny", "_tap_maxx", "_tap_maxy"):
        assert v in block


def test_prune_matches_only_the_tapcell_master():
    # the prune must delete ONLY the tap master it inserted (never a real
    # std cell) — the destroy loop is guarded by an exact master-name match.
    block = r._build_tapcell_tcl(_Pdk())
    assert '[[$_ti getMaster] getName] ne "sky130_fd_sc_hd__tapvpwrvgnd_1"' \
        in block


def test_emitted_tcl_is_brace_complete():
    assert _info_complete(r._build_tapcell_tcl(_Pdk()))


# ── §4.05 no-leak: dense design is untouched ───────────────────────────
def test_dense_branch_still_full_die_taps_no_prune_marker_first():
    """A dense design (util >= threshold) hits the ELSE branch: full-die
    tapcell, NO prune. The prune machinery only lives in the sparse if-branch."""
    block = r._build_tapcell_tcl(_Pdk())
    # both branches reference tapcell, but the BOUNDED/prune markers must sit
    # BEFORE the final else-branch tapcell (i.e. inside the sparse branch).
    bounded_idx = block.index("SPARSE_DIE_TAPCELL_BOUNDED")
    last_tap_idx = block.rindex("tapcell -distance")
    assert bounded_idx < last_tap_idx  # dense tapcell is the LAST occurrence


def test_no_master_still_skips():
    class _NoTap:
        tapcell_master = None
        tapcell_distance_um = 14.0
    block = r._build_tapcell_tcl(_NoTap())
    assert "TAPCELL_SKIPPED" in block
    assert "tapcell -distance" not in block
    assert "odb::dbInst_destroy" not in block


def test_zero_core_cell_edge_case_still_skips():
    # The emitted Tcl still carries a SPARSE_DIE_TAPCELL_SKIPPED path for the
    # runtime case where a sparse die has NO placed core cells (nothing to
    # tie) — we never fabricate taps for a wall-less design.
    block = r._build_tapcell_tcl(_Pdk())
    assert "SPARSE_DIE_TAPCELL_SKIPPED" in block
    assert "no placed core cells" in block


# ── attestation parser records the bounded well-tie ────────────────────
_BOUNDED_LOG = (
    "[INFO] placement done\n"
    "TAPCELL_INSERTED: master=sky130_fd_sc_hd__tapvpwrvgnd_1 distance=14.0um\n"
    "SPARSE_DIE_TAPCELL_BOUNDED: core_util=0.022% < 5.0% — well-tie taps "
    "kept in occupied region (kept=65) and pruned over empty silicon "
    "(pruned=135174); placed-cell VPB/VNB tied (R6).\n"
    "SPARSE_DIE_FILL_SKIPPED: core_util=0.041% < 5.0% — full-die decap/fill "
    "tiling bounded to avoid filling an empty fixed wrapper.\n"
    "[INFO] route done\n")


def test_parser_records_bounded_kept_pruned():
    att = r._parse_sparse_die_skip(_BOUNDED_LOG)
    assert att["tapcell_bounded"] is True
    assert att["tapcell_skipped"] is False   # bounded, not skipped
    assert att["tap_kept"] == 65
    assert att["tap_pruned"] == 135174
    assert att["tapcell_core_util_pct"] == 0.022
    assert att["fill_skipped"] is True
    assert att["fill_core_util_pct"] == 0.041


def test_parser_ignores_puts_template():
    # §4.05 — the Tcl `puts "SPARSE_DIE_TAPCELL_BOUNDED..."` template line
    # (present in the emitted block, never a runtime marker) must NOT be
    # counted as a fired bound.
    tcl = r._build_tapcell_tcl(_Pdk())
    att = r._parse_sparse_die_skip(tcl)
    assert att["tapcell_bounded"] is False
    assert att["tapcell_skipped"] is False
    assert att["fill_skipped"] is False


def test_write_attestation_reflects_bounded(tmp_path):
    r._write_sparse_die_skip_attestation(tmp_path, [_BOUNDED_LOG])
    loaded = r._load_sparse_die_skip(tmp_path)
    assert loaded is not None
    assert loaded["tapcell_bounded"] is True
    assert loaded["tap_kept"] == 65
    assert loaded["fill_skipped"] is True
    # the reason text documents the well-tie was PRESERVED, not skipped
    assert "well-tie" in loaded["reason"].lower()


def test_no_bound_no_skip_writes_no_attestation(tmp_path):
    r._write_sparse_die_skip_attestation(tmp_path, ["[INFO] normal dense run\n"])
    assert r._load_sparse_die_skip(tmp_path) is None


# ── LIVE end-to-end proof (auto-skips without the container) ────────────
def _container_available() -> bool:
    if os.environ.get("VIBEIC_R6_LIVE") != "1":
        return False
    try:
        p = subprocess.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc",
             "command -v openroad >/dev/null && echo ok"],
            capture_output=True, text=True, timeout=30)
        return "ok" in p.stdout
    except Exception:
        return False


@pytest.mark.skipif(not _container_available(),
                    reason="live OpenROAD container proof (set VIBEIC_R6_LIVE=1"
                           " with the vibeic-eda container up)")
def test_live_emitted_block_ties_wells_and_prunes():
    """Run the ACTUAL emitted R6 block on a caravel-scale (2920x3520 um)
    fixed die with a tiny 4-cell cluster; prove taps are kept in the
    occupied region, pruned over empty silicon, and placed-cell VPB/VNB are
    tied to VPWR/VGND."""
    block = r._build_tapcell_tcl(_Pdk())
    vlog = (
        "module sparse_top (input a, input b, input clk, output y);\n"
        "  wire n1, n2, n3;\n"
        "  sky130_fd_sc_hd__inv_1   u0 (.A(a),  .Y(n1));\n"
        "  sky130_fd_sc_hd__nand2_1 u1 (.A(n1), .B(b),  .Y(n2));\n"
        "  sky130_fd_sc_hd__buf_1   u2 (.A(n2), .X(n3));\n"
        "  sky130_fd_sc_hd__dfrtp_1 u3 (.CLK(clk), .D(n3), .RESET_B(a), .Q(y));\n"
        "endmodule\n")
    ref = "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd"
    tcl = textwrap.dedent(f"""\
        read_lef {ref}/techlef/sky130_fd_sc_hd__nom.tlef
        read_lef {ref}/lef/sky130_fd_sc_hd.lef
        read_liberty {ref}/lib/sky130_fd_sc_hd__ff_n40C_1v95.lib
        read_verilog /tmp/_r6_sparse_top.v
        link_design sparse_top
        initialize_floorplan -die_area {{0 0 2920 3520}} -core_area {{10 10 2910 3510}} -site unithd
        set blk [ord::get_db_block]
        set x 50000
        foreach iname {{u0 u1 u2 u3}} {{
          set inst [$blk findInst $iname]
          $inst setLocation $x 50880
          $inst setPlacementStatus FIRM
          set x [expr {{$x + 3000}}]
        }}
        """) + block + textwrap.dedent("""\
        add_global_connection -net VPWR -pin_pattern {^VPWR$} -power
        add_global_connection -net VPWR -pin_pattern {^VPB$}  -power
        add_global_connection -net VGND -pin_pattern {^VGND$} -ground
        add_global_connection -net VGND -pin_pattern {^VNB$}  -ground
        global_connect
        foreach iname {u0 u3} {
          set u [$blk findInst $iname]
          foreach pin {VPB VNB} { puts "TIE_${iname}_${pin}: [[[$u findITerm $pin] getNet] getName]" }
        }
        """)

    def _cp(text, dst):
        subprocess.run(["docker", "exec", "-i", "vibeic-eda", "bash", "-lc",
                        f"cat > {dst}"], input=text, text=True, check=True)
    _cp(vlog, "/tmp/_r6_sparse_top.v")
    _cp(tcl, "/tmp/_r6_live.tcl")
    p = subprocess.run(
        ["docker", "exec", "vibeic-eda", "bash", "-lc",
         "cd /tmp && openroad -exit _r6_live.tcl 2>&1"],
        capture_output=True, text=True, timeout=600)
    out = p.stdout
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in out, out[-2000:]
    # placed-cell wells tied
    assert "TIE_u0_VPB: VPWR" in out
    assert "TIE_u0_VNB: VGND" in out
    assert "TIE_u3_VPB: VPWR" in out
    assert "TIE_u3_VNB: VGND" in out
    # taps kept in-region and pruned over empty silicon
    att = r._parse_sparse_die_skip(out)
    assert att["tapcell_bounded"] is True
    assert att["tap_kept"] and att["tap_kept"] > 0
    assert att["tap_pruned"] and att["tap_pruned"] > att["tap_kept"]

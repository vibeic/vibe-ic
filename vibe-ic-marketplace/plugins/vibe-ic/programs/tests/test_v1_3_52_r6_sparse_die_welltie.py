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
from not_verified_tier import (PROBE_PRESENT, probe,  # noqa: E402
                               probe_skip_reason)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


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


# ── insertion always ties every placed cell's wells; prune is post-place ──
def test_sparse_branch_inserts_and_bounds_taps():
    # v1.5.x SPLIT: insertion is UNCONDITIONAL + full-die (pre-placement, so
    # the placer flows logic around the FIXED taps and every cell gets a tie);
    # the #684 anti-flood prune runs POST-placement on REAL geometry.
    insert = r._build_tapcell_tcl(_Pdk())
    prune = r._build_tapcell_prune_tcl(_Pdk())
    # insertion RUNS the full-die well-tie tapcell — not a bare skip
    assert "tapcell -distance 14.0 -tapcell_master " \
        "sky130_fd_sc_hd__tapvpwrvgnd_1" in insert
    assert "odb::dbInst_destroy" not in insert     # no prune in insertion
    # the prune bounds the taps to the occupied region (empty silicon pruned)
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in prune
    assert "odb::dbInst_destroy" in prune
    assert "getDbUnitsPerMicron" in prune
    # locality (not bounding-box): a tap survives iff a placed cell is within
    # the latch-up neighbourhood (2x distance) — kept via the _cbin hash.
    assert "_cbin" in prune
    # the prune only fires on a sparse die (util below the fill threshold)
    assert "getCoreArea" in prune
    assert "_tap_util < " in prune


def test_prune_matches_only_the_tapcell_master():
    # the prune must delete ONLY the tap master it inserted (never a real
    # std cell) — the destroy loop is guarded by an exact master-name match.
    prune = r._build_tapcell_prune_tcl(_Pdk())
    assert '[[$_ti getMaster] getName] ne "sky130_fd_sc_hd__tapvpwrvgnd_1"' \
        in prune


def test_emitted_tcl_is_brace_complete():
    assert _info_complete(r._build_tapcell_tcl(_Pdk()))
    assert _info_complete(r._build_tapcell_prune_tcl(_Pdk()))
    assert _info_complete(
        r._build_tapcell_prune_tcl(_Pdk(), [(155, 185), (1025, 1235)]))


# ── §4.05 no-leak: dense design keeps ALL taps (no prune) ──────────────
def test_dense_branch_still_full_die_taps_no_prune_marker_first():
    """A dense design (util >= threshold) hits the prune's ELSE branch:
    full-die taps RETAINED, no destroy. The BOUNDED prune only lives in the
    sparse if-branch, guarded by the util test; the dense path emits the
    DENSE_OR_UNKNOWN retain marker."""
    insert = r._build_tapcell_tcl(_Pdk())
    prune = r._build_tapcell_prune_tcl(_Pdk())
    # insertion is unconditional full-die — dense and sparse both get taps
    assert "tapcell -distance" in insert
    # the destroy is INSIDE the sparse `if {$_tap_util ... < thr}` branch and
    # BEFORE the dense else-branch retain marker.
    if_idx = prune.index("_tap_util < ")
    bounded_idx = prune.index("SPARSE_DIE_TAPCELL_BOUNDED")
    dense_idx = prune.index("TAPCELL_PRUNE_DENSE_OR_UNKNOWN")
    assert if_idx < bounded_idx < dense_idx


def test_no_master_still_skips():
    class _NoTap:
        tapcell_master = None
        tapcell_distance_um = 14.0
    insert = r._build_tapcell_tcl(_NoTap())
    assert "TAPCELL_SKIPPED" in insert
    assert "tapcell -distance" not in insert
    assert "odb::dbInst_destroy" not in insert
    # no tapcell master → nothing to prune → empty prune block
    assert r._build_tapcell_prune_tcl(_NoTap()) == ""


def test_zero_core_cell_edge_case_keeps_no_taps():
    # v1.5.x — insertion is unconditional, so on a sparse die with NO placed
    # core cells (nothing to tie) the post-place prune finds no anchor and
    # prunes EVERY tap (kept=0). We never leave fabricated taps over a
    # wall-less design; coverage is still exact (there are no cells to cover).
    prune = r._build_tapcell_prune_tcl(_Pdk())
    # the kill list is built from taps with no cell in their 3x3 bin
    # neighbourhood; with zero anchor bins every tap is killed.
    assert "_tap_kill" in prune
    assert "array unset _cbin" in prune


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
    # (present in the emitted PRUNE block, never a runtime marker) must NOT be
    # counted as a fired bound.
    prune = r._build_tapcell_prune_tcl(_Pdk())
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in prune  # the template IS in the block
    att = r._parse_sparse_die_skip(prune)
    assert att["tapcell_bounded"] is False        # but the parser ignores it
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
# vibe-ic#1283 — TWO questions, and the old single bool answered them with one
# word. "the live proof was not asked for" is an ordinary N/A (the first mark);
# "the probe for openroad did not answer" is NOT a finding that openroad is
# missing (the second). The `except Exception: return False` this replaces
# collapsed the timeout into the opt-in reason, so a host that lost the race
# was reported as a host that had not opted in.
_R6_LIVE_REQUESTED = os.environ.get("VIBEIC_R6_LIVE") == "1"
# Not requested -> the probe is NOT RUN AT ALL: the mark above already skips,
# and spending the budget on a container nobody asked about would only make a
# loaded host slower. PRESENT here means "nothing to report", not "measured".
_R6_STATE, _R6_DETAIL = (
    probe(["docker", "exec", "vibeic-eda", "bash", "-lc",
           "command -v openroad >/dev/null && echo ok"])
    if _R6_LIVE_REQUESTED else (PROBE_PRESENT, ""))


@pytest.mark.skipif(not _R6_LIVE_REQUESTED,
                    reason="live OpenROAD container proof not requested (set"
                           " VIBEIC_R6_LIVE=1 with the vibeic-eda container up)")
@pytest.mark.skipif(
    _R6_STATE != PROBE_PRESENT,
    reason=probe_skip_reason(_R6_STATE, _R6_DETAIL,
                             "openroad not reachable in the vibeic-eda"
                             " container",
                             "bash tools/vibeic-eda/restart-eda.sh"))
def test_live_emitted_block_ties_wells_and_prunes():
    """Run the ACTUAL emitted R6 block on a caravel-scale (2920x3520 um)
    fixed die with a tiny 4-cell cluster; prove taps are kept in the
    occupied region, pruned over empty silicon, and placed-cell VPB/VNB are
    tied to VPWR/VGND."""
    # Cells are pre-placed FIRM below, so run insertion (full-die) THEN the
    # post-place locality prune in sequence — the same order the flow emits.
    block = r._build_tapcell_tcl(_Pdk()) + r._build_tapcell_prune_tcl(_Pdk())
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
    p = _pr.run(
        ["docker", "exec", "vibeic-eda", "bash", "-lc",
         "cd /tmp && openroad -exit _r6_live.tcl 2>&1"],
        capture_output=True, text=True)
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

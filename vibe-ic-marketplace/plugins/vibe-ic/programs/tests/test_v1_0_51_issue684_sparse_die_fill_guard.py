#!/usr/bin/env python3
"""Regression tests for issue #684 — Phase-3 PnR must NOT flood a large
fixed wrapper holding a tiny design with full-die decap/fill (+ tapcell).

Root cause (caravel round-6, public tree v1.0.47): the runner emitted a
BARE, uncapped `filler_placement {<masters>}` and `tapcell -distance 14.0`
that tile EVERY empty placement row of the FIXED caravel die (2920×3520 µm
= 10.28 mm²). For a 189-cell design (core util 0.033%) that produced
940,262 filler cells (99.93%) / a 2.0 GB GDS (known-good dense build =
2.8 MB, ~740×). chip-AGNOSTIC: any small/sparse design in a large fixed
wrapper (pad-frame / SoC harness) hit the same explosion.

Fix: a RUNTIME sparse-die guard measures post-place CORE utilization from
odb and SKIPs the full-die decap/fill tiling when util < threshold
(default 5%). OpenROAD 26Q1 `filler_placement` has no -area/region/density
arg, so the runtime util gate is the portable bound.

R6 (v1.3.52) refinement — the well-tie `tapcell` is a CORRECTNESS op (it
ties placed std-cell VPB/VNB body pins), NOT an optional density filler, so
on a sparse die it is no longer skipped: the runner inserts taps then PRUNES
the ones that fell over empty silicon (keeps the occupied bbox + a
2x-distance latch-up margin). Placed-cell wells stay tied (power-aware LVS
matches) with no empty-silicon flood. Only decap/fill remains skip-bounded.

§4.05 negative (no-leak): a DENSE / normal-util design must STILL get the
full fill + tapcell (util ≥ threshold → the unconditional call runs). The
`filler_placement {<masters>}` and `tapcell ...` calls must remain present
in the ELSE branch — covered by test_dense_branch_still_fills /
test_dense_branch_still_taps. (Live OpenROAD cross-check, recorded in the
issue close comment: sparse placed.def → SKIPPED at 1.69%; a 75%-util
synthetic design → FILLER_INSERTED. R6 live cross-check: caravel-scale
2920x3520 die → 135239 taps inserted, 65 kept / 135174 pruned, u0/u3
VPB→VPWR VNB→VGND tied.)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as r  # noqa: E402


_MASTERS = list(r._SKY130_FILLER_MASTERS)


def _info_complete(tcl: str) -> bool:
    """tclsh `info complete` — proves balanced braces / quotes."""
    src = ("proc ord::get_db_block {} {return blk}\n" + tcl)
    p = subprocess.run(
        ["tclsh"], input=f"if {{[info complete {{{src}}}]}} "
        "{puts OK} else {puts BAD}",
        capture_output=True, text=True)
    return "OK" in p.stdout


# ── the fill guard ─────────────────────────────────────────────────────
def test_fill_guard_gates_full_die_filler_on_sparse_util():
    block = r._build_sparse_die_aware_filler_tcl(_MASTERS)
    # The sparse guard machinery must be present.
    assert "SPARSE_DIE_FILL_SKIPPED" in block
    assert "getCoreArea" in block
    assert "getInsts" in block
    # The full-die filler must NOT be emitted unconditionally — it must be
    # inside the (else) branch, guarded by the utilization comparison.
    assert "filler_placement" in block
    # the bare top-level emission (no guard) is gone: the call is preceded
    # by the SPARSE_DIE_FILL_SKIPPED conditional in the same block.
    skip_idx = block.index("SPARSE_DIE_FILL_SKIPPED")
    fill_idx = block.index("filler_placement")
    assert skip_idx < fill_idx, "filler_placement must be guarded by the " \
        "sparse-die check, not emitted before it"


def test_dense_branch_still_fills():
    """§4.05 NEGATIVE no-leak — the unconditional full filler_placement of
    every PDK master must survive in the else (dense) branch so a normal
    design still meets density-fill rules."""
    block = r._build_sparse_die_aware_filler_tcl(_MASTERS)
    for m in _MASTERS:
        assert m in block, f"master {m} dropped from the dense-branch fill"
    # the else branch literally runs `filler_placement {<all masters>}`.
    assert "filler_placement {" + " ".join(_MASTERS) + "}" in block


def test_fill_guard_threshold_default_and_env(monkeypatch):
    monkeypatch.delenv("VIBEIC_SPARSE_DIE_FILL_PCT", raising=False)
    assert r._sparse_die_fill_threshold_pct() == \
        r._SPARSE_DIE_FILL_UTIL_PCT_DEFAULT
    monkeypatch.setenv("VIBEIC_SPARSE_DIE_FILL_PCT", "12.5")
    assert r._sparse_die_fill_threshold_pct() == 12.5
    # garbage / out-of-range falls back to the default
    monkeypatch.setenv("VIBEIC_SPARSE_DIE_FILL_PCT", "nan-ish")
    assert r._sparse_die_fill_threshold_pct() == \
        r._SPARSE_DIE_FILL_UTIL_PCT_DEFAULT
    monkeypatch.setenv("VIBEIC_SPARSE_DIE_FILL_PCT", "0")
    assert r._sparse_die_fill_threshold_pct() == \
        r._SPARSE_DIE_FILL_UTIL_PCT_DEFAULT


def test_fill_guard_empty_masters_skips():
    block = r._build_sparse_die_aware_filler_tcl([])
    assert "FILLER_SKIPPED" in block
    assert "filler_placement" not in block


def test_fill_guard_tcl_is_brace_complete():
    assert _info_complete(r._build_sparse_die_aware_filler_tcl(_MASTERS))


# ── the tapcell guard ──────────────────────────────────────────────────
class _Pdk:
    tapcell_master = "sky130_fd_sc_hd__tapvpwrvgnd_1"
    tapcell_distance_um = 14.0


def test_tapcell_guard_gates_full_die_tapcell_on_sparse():
    # v1.5.x — the tap flow is SPLIT: `_build_tapcell_tcl` ALWAYS inserts the
    # full-die well-tie taps (pre-placement, so global_placement flows logic
    # around the FIXED taps → every cell gets a tie), and the #684 anti-flood
    # prune moved to `_build_tapcell_prune_tcl`, which runs POST-placement on
    # the REAL geometry. The earlier in-place prune measured the occupied
    # region BEFORE global_placement (every cell still stacked at the origin),
    # so it kept only the origin-corner taps and stripped every tap over what
    # later became the placed logic → a conclusive PERC latch-up tap-spacing
    # GAP ("std cell ... infinitely (no tap in neighbourhood)").
    insert = r._build_tapcell_tcl(_Pdk())
    prune = r._build_tapcell_prune_tcl(_Pdk())
    # insertion is unconditional + full-die; NO prune machinery lives in it
    assert ("tapcell -distance 14.0 -tapcell_master "
            "sky130_fd_sc_hd__tapvpwrvgnd_1") in insert
    assert "odb::dbInst_destroy" not in insert
    # the prune is util-gated (getCoreArea) and only fires on a sparse die
    assert "getCoreArea" in prune
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in prune
    assert "odb::dbInst_destroy" in prune
    # empty silicon is still not flooded — taps are kept by cell LOCALITY
    # (a placed cell within 2x the tapcell distance), not by bounding box.
    assert "_cbin" in prune
    assert "getDbUnitsPerMicron" in prune


def test_dense_branch_still_taps():
    """§4.05 NEGATIVE no-leak — a dense design still inserts tap cells."""
    block = r._build_tapcell_tcl(_Pdk())
    assert ("tapcell -distance 14.0 -tapcell_master "
            "sky130_fd_sc_hd__tapvpwrvgnd_1") in block


def test_tapcell_guard_no_master_skips():
    class _NoTap:
        tapcell_master = None
        tapcell_distance_um = 14.0
    block = r._build_tapcell_tcl(_NoTap())
    assert "TAPCELL_SKIPPED" in block
    assert "tapcell -distance" not in block


def test_tapcell_guard_tcl_is_brace_complete():
    assert _info_complete(r._build_tapcell_tcl(_Pdk()))
    assert _info_complete(r._build_tapcell_prune_tcl(_Pdk()))
    # with spare anchor points injected the block stays brace-complete too
    assert _info_complete(
        r._build_tapcell_prune_tcl(_Pdk(), [(155, 185), (1025, 1235)]))

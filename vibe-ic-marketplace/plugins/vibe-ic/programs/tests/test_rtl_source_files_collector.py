#!/usr/bin/env python3
"""Tests for _specrtl_common.rtl_source_files — the shared AUTHORED-RTL
source collector (Kimi-scale fix).

Root cause covered: on the first Kimi-scale run (3.1M-cell edge-LLM accel)
the RTL-source structural gates rglobbed the whole project and ingested the
342 MB emitted netlist_yosys.v / netlist.v under phase2/stage2/synth/; their
char-level comment strippers then ran >30 min and all 7 gates were killed at
the #525 900 s budget. The collector must:
  1. prefer the canonical authored-RTL home phase2/stage1/rtl/ when it holds
     RTL, scanning ONLY it;
  2. otherwise rglob the project EXCLUDING generated-output dirs and any
     file above the 8 MB sanity cap;
  3. change nothing a gate legitimately scans on a small canonical-layout
     project (§4.05 no-leak).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import _specrtl_common as sc

PROGRAMS = Path(__file__).resolve().parent.parent


def _mk(p: Path, content: str = "module m; endmodule\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# 1. canonical-dir preference
# ---------------------------------------------------------------------------
def test_canonical_rtl_dir_preferred(tmp_path):
    a = _mk(tmp_path / "phase2/stage1/rtl/top.v")
    b = _mk(tmp_path / "phase2/stage1/rtl/sub/core.sv")
    _mk(tmp_path / "phase2/stage2/synth/netlist_yosys.v")   # emitted netlist
    _mk(tmp_path / "extra/loose.v")                          # outside canonical
    _mk(tmp_path / "verify/tb_top.v")                        # sim build
    got = sc.rtl_source_files(tmp_path)
    assert got == sorted([a, b])


def test_canonical_dir_without_rtl_falls_back(tmp_path):
    # canonical dir EXISTS but holds no *.v/*.sv → fallback scan must still
    # find RTL elsewhere (an empty rtl/ must never blank the gate's input).
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    keep = _mk(tmp_path / "src/design.v")
    _mk(tmp_path / "phase2/stage2/synth/netlist.v")
    got = sc.rtl_source_files(tmp_path)
    assert got == [keep]


# ---------------------------------------------------------------------------
# 2. fallback: generated-output dir exclusion + size cap
# ---------------------------------------------------------------------------
def test_fallback_excludes_generated_output_dirs(tmp_path):
    keep_root = _mk(tmp_path / "design.v")
    keep_sub = _mk(tmp_path / "rtl_src/alu.sv")
    for d in ("phase2/stage2/synth", "phase3/stage3/pnr", "stage4/gds",
              "sim", "sim_full_stack", "sim_professional", "verify",
              "reports", "_logs"):
        _mk(tmp_path / d / "gen.v")
    got = sc.rtl_source_files(tmp_path)
    assert got == sorted([keep_root, keep_sub])


def test_fallback_size_cap_drops_netlist_scale_files(tmp_path):
    keep = _mk(tmp_path / "small.v")
    big = tmp_path / "flat_netlist.v"
    # sparse file just over the cap — no need to write 342 MB in a test
    with big.open("wb") as fh:
        fh.seek(sc.RTL_SOURCE_MAX_BYTES)          # cap + 1 bytes total
        fh.write(b"\n")
    assert big.stat().st_size > sc.RTL_SOURCE_MAX_BYTES
    got = sc.rtl_source_files(tmp_path)
    assert got == [keep]


def test_fallback_filename_is_not_matched_as_dir_part(tmp_path):
    # a DESIGN FILE merely named like a generated dir must be kept — only
    # directory components are matched against the exclusion set.
    keep = _mk(tmp_path / "synth.v")
    got = sc.rtl_source_files(tmp_path)
    assert got == [keep]


def test_non_directory_returns_empty(tmp_path):
    f = _mk(tmp_path / "x.v")
    assert sc.rtl_source_files(f) == []                      # file, not dir
    assert sc.rtl_source_files(tmp_path / "missing") == []


def test_bare_rtl_dir_argument_unchanged(tmp_path):
    # gates are also invoked directly on an rtl/ dir (no phase2 layout
    # inside); every file in it must be collected exactly as before.
    a = _mk(tmp_path / "rtl/top.v")
    b = _mk(tmp_path / "rtl/core.sv")
    assert sc.rtl_source_files(tmp_path / "rtl") == sorted([a, b])


# ---------------------------------------------------------------------------
# 2b. exts widening (Kimi-scale round 2): gates that have always also scanned
#     *.vh/*.svh headers keep that coverage through the shared collector
# ---------------------------------------------------------------------------
def test_exts_widening_keeps_headers_in_canonical_dir(tmp_path):
    a = _mk(tmp_path / "phase2/stage1/rtl/top.v")
    h = _mk(tmp_path / "phase2/stage1/rtl/timing.vh", "`define T_A_CYC 4\n")
    s = _mk(tmp_path / "phase2/stage1/rtl/pkg.svh", "package p; endpackage\n")
    _mk(tmp_path / "phase2/stage2/synth/netlist.v")          # emitted netlist
    wide = sc.rtl_source_files(
        tmp_path, exts=("*.v", "*.sv", "*.vh", "*.svh"))
    assert wide == sorted([a, h, s])
    # the default suffix set is unchanged (headers NOT collected)
    assert sc.rtl_source_files(tmp_path) == [a]


def test_exts_widening_fallback_applies_same_contract(tmp_path):
    # fallback scan: excluded generated dirs + the size cap gate headers too.
    keep_v = _mk(tmp_path / "src/design.v")
    keep_h = _mk(tmp_path / "src/timing.vh", "`define T_A_CYC 4\n")
    _mk(tmp_path / "sim/gen.vh")                             # generated dir
    big = tmp_path / "src/huge.vh"
    with big.open("wb") as fh:
        fh.seek(sc.RTL_SOURCE_MAX_BYTES)                     # cap + 1 bytes
        fh.write(b"\n")
    got = sc.rtl_source_files(tmp_path, exts=("*.v", "*.sv", "*.vh", "*.svh"))
    assert got == sorted([keep_v, keep_h])


# ---------------------------------------------------------------------------
# 3. end-to-end: a gate no longer ingests an emitted netlist (cwd=<project>,
#    arg "." — exactly the flow_compliance strict-structural invocation)
# ---------------------------------------------------------------------------
def test_gate_ignores_generated_netlist_end_to_end(tmp_path):
    _mk(tmp_path / "phase2/stage1/rtl/top.v",
        "module top(input clk);\n  reg [7:0] d;\n  wire x = d[3];\nendmodule\n")
    # the netlist carries an out-of-range bitselect that WOULD fail the gate
    # if it were (wrongly) scanned
    _mk(tmp_path / "phase2/stage2/synth/netlist_yosys.v",
        "module top(input clk);\n  reg [4:0] idx;\n"
        "  wire [7:0] a = {1'b0, idx[6:0]};\nendmodule\n")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "bitwidth_consistency_check.py"),
         ".", "--json"],
        cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"files_scanned": 1' in r.stdout

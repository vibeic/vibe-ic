"""test_mbist_wrapper_gen.py — the deterministic MBIST March C- wrapper
generator + coverage gate (TAPEOUT-SIGNOFF P0, MBIST half).

mbist_wrapper_gen has two responsibilities and a gate:
  (a) DETECT RAMs in a design (behavioral `reg [W-1:0] mem [0:D-1]` inference,
      SRAM/DPRAM macro instances, memory-macro LEF), deriving each RAM's
      DATA_WIDTH x DEPTH (+ ADDR_WIDTH) FROM THE DESIGN (chip-AGNOSTIC);
  (b) EMIT a synthesizable March C- MBIST wrapper parameterized to that
      geometry, with a bist_start/bist_done/bist_fail interface, plus a
      good/broken RAM + testbench self-check bundle.
  GATE: PASS when every detected RAM has an MBIST wrapper; FAIL naming any RAM
      with no wrapper; N/A (not PASS, not FAIL) when the design has NO RAM.

§4.05 BOUNDARY proved BOTH directions:
  * a RAM-less design -> N/A (never a spurious FAIL, never a spurious PASS);
  * a design WITH a RAM and NO wrapper -> FAIL (an untestable memory must not
    slip through as PASS).

The iverilog functional checks (a correct RAM -> bist_fail=0, a stuck-at RAM ->
bist_fail=1) are GATED on the iverilog binary; all detect/emit/gate assertions
run anywhere.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import mbist_wrapper_gen as M  # noqa: E402

_HAS_IVERILOG = (shutil.which("iverilog") is not None
                 and shutil.which("vvp") is not None)


# --------------------------------------------------------------------------- #
# fixtures — a RAM-bearing design and a RAM-less design (chip-AGNOSTIC)
# --------------------------------------------------------------------------- #
RAM_8x256 = """\
module simple_ram (
    input              clk,
    input              we,
    input      [7:0]   addr,
    input      [7:0]   din,
    output reg [7:0]   dout
);
    reg [7:0] mem [0:255];      // on-chip RAM: 8-bit x 256 words
    always @(posedge clk) begin
        if (we) mem[addr] <= din;
        dout <= mem[addr];
    end
endmodule
"""

# same array, expressed through the design's OWN parameters (geometry must be
# derived from the parameter defaults, not from a chip literal).
RAM_PARAM = """\
module param_ram #(
    parameter DATA_WIDTH = 16,
    parameter DEPTH      = 64
) (
    input                    clk,
    input                    wr_en,
    input  [5:0]             addr,
    input  [DATA_WIDTH-1:0]  wdata,
    output reg [DATA_WIDTH-1:0] rdata
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    always @(posedge clk) begin
        if (wr_en) mem[addr] <= wdata;
        rdata <= mem[addr];
    end
endmodule
"""

RAMLESS = """\
module up_counter (
    input              clk,
    input              rst_n,
    output reg [7:0]   count
);
    // a plain counter — no memory array, legitimately needs no MBIST
    always @(posedge clk) begin
        if (!rst_n) count <= 8'd0;
        else        count <= count + 8'd1;
    end
endmodule
"""

# a read-only initialized LUT (never written) must NOT be flagged as a RAM.
ROM_LUT = """\
module sbox (
    input      [3:0] idx,
    output reg [7:0] q
);
    reg [7:0] lut [0:15];
    integer i;
    initial for (i = 0; i < 16; i = i + 1) lut[i] = i * 3;
    always @(*) q = lut[idx];
endmodule
"""


# --------------------------------------------------------------------------- #
# (a) DETECT + EMIT  — reg [7:0] mem [0:255] -> 8x256 March C- wrapper
# --------------------------------------------------------------------------- #
def test_detect_behavioral_ram_geometry():
    specs = M.detect([("ram.v", RAM_8x256)])
    assert len(specs) == 1
    s = specs[0]
    assert s.module == "simple_ram"
    assert s.data_width == 8
    assert s.depth == 256
    assert s.addr_width == 8
    assert s.kind == "behavioral"
    assert s.complete
    assert (s.clk, s.we, s.addr, s.din, s.dout) == \
        ("clk", "we", "addr", "din", "dout")


def test_detect_parameterized_geometry():
    # geometry derived through the design's own parameter defaults.
    s = M.detect([("p.v", RAM_PARAM)])[0]
    assert s.module == "param_ram"
    assert s.data_width == 16
    assert s.depth == 64
    assert s.addr_width == 6
    assert s.we == "wr_en" and s.din == "wdata" and s.dout == "rdata"


def test_rom_lut_is_not_a_ram():
    # a read-only initialized LUT is not a March-testable RAM -> not detected.
    assert M.detect([("rom.v", ROM_LUT)]) == []


def test_emit_wrapper_is_march_c_minus_and_parameterized():
    s = M.detect([("ram.v", RAM_8x256)])[0]
    w = M.emit_wrapper(s)
    # the wrapper wraps the RAM and carries the standard bist interface
    assert "module simple_ram_mbist" in w
    assert "simple_ram dut" in w
    for port in ("bist_start", "bist_done", "bist_fail"):
        assert port in w
    # parameterized to the detected geometry
    assert "parameter DATA_WIDTH = 8" in w
    assert "parameter DEPTH      = 256" in w
    assert "parameter ADDR_WIDTH = 8" in w
    # a REAL March C- controller (6 elements), not a stub: the sequencer,
    # both background writes, and the read-compare must all be present.
    assert "March C-" in w
    assert "{DATA_WIDTH{1'b0}}" in w and "{DATA_WIDTH{1'b1}}" in w
    assert "3'd5" in w                       # six march elements (0..5)
    assert "bist_fail <= 1'b1" in w          # a read mismatch fails the test
    assert "endmodule" in w


# --------------------------------------------------------------------------- #
# (a)+(b)  gate PASS once the wrapper is present
# --------------------------------------------------------------------------- #
def test_gate_pass_when_ram_has_wrapper():
    s = M.detect([("ram.v", RAM_8x256)])[0]
    wrapper = M.emit_wrapper(s)
    report, rc = M.gate([("ram.v", RAM_8x256), ("mbist.v", wrapper)])
    assert report["verdict"] == "PASS"
    assert rc == 0
    assert report["uncovered"] == []
    assert report["rams"][0]["covered_by"] == "simple_ram_mbist"


# --------------------------------------------------------------------------- #
# (b)  gate FAIL when the RAM has NO wrapper — the §4.05 FAIL half
# --------------------------------------------------------------------------- #
def test_gate_fail_when_ram_has_no_wrapper():
    report, rc = M.gate([("ram.v", RAM_8x256)])
    assert report["verdict"] == "FAIL"
    assert rc == 1
    assert "simple_ram" in report["uncovered"]
    assert "simple_ram" in report["message"]


# --------------------------------------------------------------------------- #
# (c)  gate N/A for a RAM-less design — the §4.05 N/A half (BOTH ways)
# --------------------------------------------------------------------------- #
def test_gate_na_for_ramless_design_never_fail_never_pass():
    report, rc = M.gate([("c.v", RAMLESS)])
    assert report["verdict"] == "N/A"      # not PASS, not FAIL
    assert report["verdict"] not in ("PASS", "FAIL")
    assert rc == 0                          # N/A is not a failure
    assert report["ram_count"] == 0


def test_section_405_boundary_both_directions():
    # ONE assertion capturing both directions of the §4.05 boundary:
    # RAM present + no wrapper => FAIL ; no RAM => N/A (and never the reverse).
    fail_rep, fail_rc = M.gate([("ram.v", RAM_8x256)])
    na_rep, na_rc = M.gate([("c.v", RAMLESS)])
    assert (fail_rep["verdict"], fail_rc) == ("FAIL", 1)
    assert (na_rep["verdict"], na_rc) == ("N/A", 0)
    # a RAM-less design is never a spurious FAIL, a RAM is never a silent PASS.
    assert na_rep["verdict"] != "FAIL"
    assert fail_rep["verdict"] != "PASS"


# --------------------------------------------------------------------------- #
# secondary detection paths (macro instance / LEF) — flagged, not silently lost
# --------------------------------------------------------------------------- #
def test_sram_macro_instance_detected_and_gated():
    design = """\
module core (input clk, input we, input [9:0] a, input [31:0] d,
             output [31:0] q);
    sram_32x1024 u_sram (.clk(clk), .we(we), .addr(a), .din(d), .dout(q));
endmodule
"""
    specs = M.detect([("core.v", design)])
    mods = {s.module: s for s in specs}
    assert "sram_32x1024" in mods
    assert mods["sram_32x1024"].kind == "macro"
    # a macro RAM with no wrapper still FAILs the gate (untestable memory).
    report, rc = M.gate([("core.v", design)])
    assert report["verdict"] == "FAIL" and rc == 1
    assert "sram_32x1024" in report["uncovered"]


def test_lef_memory_macro_detected():
    lef = """\
VERSION 5.8 ;
MACRO sram_16x512
  CLASS BLOCK ;
  SIZE 100.0 BY 200.0 ;
END sram_16x512
"""
    specs = M.detect([("mem.lef", lef)])
    assert any(s.module == "sram_16x512" and s.kind == "lef" for s in specs)


# --------------------------------------------------------------------------- #
# (d)  iverilog functional proof — correct RAM passes, stuck-at RAM fails
# --------------------------------------------------------------------------- #
def _iverilog_run(*sources: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        paths = []
        for i, src in enumerate(sources):
            p = dp / f"src{i}.v"
            p.write_text(src)
            paths.append(str(p))
        c = subprocess.run(
            ["iverilog", "-g2012", "-o", str(dp / "a.out"), *paths],
            capture_output=True, text=True)
        assert c.returncode == 0, "compile failed:\n" + c.stderr
        r = subprocess.run(["vvp", str(dp / "a.out")],
                           capture_output=True, text=True)
        return r.stdout


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_selfcheck_good_ram_passes():
    sc = M.build_selfcheck(8, 256)
    out = _iverilog_run(sc["wrapper"], sc["ram_good"], sc["tb"])
    assert "MBIST_RESULT PASS" in out


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_selfcheck_broken_ram_fails():
    sc = M.build_selfcheck(8, 256)
    out = _iverilog_run(sc["wrapper"], sc["ram_broken"], sc["tb"])
    assert "MBIST_RESULT FAIL" in out


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_selfcheck_second_geometry_passes_and_fails():
    # parameterization proven at a SECOND geometry (4-bit x 16 words).
    sc = M.build_selfcheck(4, 16, module="tiny_ram")
    assert "MBIST_RESULT PASS" in _iverilog_run(
        sc["wrapper"], sc["ram_good"], sc["tb"])
    assert "MBIST_RESULT FAIL" in _iverilog_run(
        sc["wrapper"], sc["ram_broken"], sc["tb"])


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_detected_spec_wrapper_end_to_end():
    # the wrapper emitted from the ACTUALLY-DETECTED fixture RAM compiles with
    # that RAM and passes; a stuck-at variant of the same interface fails.
    spec = M.detect([("ram.v", RAM_8x256)])[0]
    wrapper = M.emit_wrapper(spec)
    tb = M.emit_selfcheck_tb(spec, "simple_ram_mbist")
    broken = M.emit_reference_ram(spec, broken=True)
    assert "MBIST_RESULT PASS" in _iverilog_run(wrapper, RAM_8x256, tb)
    assert "MBIST_RESULT FAIL" in _iverilog_run(wrapper, broken, tb)

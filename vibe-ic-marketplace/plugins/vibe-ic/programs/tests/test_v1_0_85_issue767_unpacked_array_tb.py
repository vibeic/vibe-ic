#!/usr/bin/env python3
"""ORGANIC #767 — `latency_conformance_check` could not model a SystemVerilog
UNPACKED-ARRAY port (`input wire [7:0] char_in [7:0]`) in its auto-generated
measurement TB. The shared 3-tuple parser drops the trailing post-name unpacked
dimension, so `build_measurement_tb` emitted a SCALAR `reg [7:0] char_in;` wired
to the DUT's array port — iverilog rejected it at elaboration ("Can not assign
non-array identifier char_in to array") → a HARD rc=2 BLOCK on correct,
spec-faithful RTL whose real start->valid latency is exactly 1 cycle.

Fix (program-first, chip-AGNOSTIC, LOCAL — the shared 3-tuple contract is
untouched): recover the post-name unpacked dimension via `parse_unpacked_dims`,
carry it on `PortInfo.unpacked_dims`, render `[..]` on each TB reg/wire decl,
drive single-dim concrete array inputs ELEMENT-WISE, and screen an array
event/output or a multi-dimension/non-constant array to a DISTINCT rc=3
NOT_APPLICABLE instead of a misleading hard rc=2.

Tests
=====
NEW-PATH        : `parse_unpacked_dims` recovers the post-name dim; the TB now
                  declares + drives the array element-wise; the real program
                  PASSES (rc 0, measured=1==spec 1) on the affected shape.
REGRESSION-GUARD: a SCALAR/packed-only design has unpacked_dims=="" — its TB
                  declaration + drive are byte-for-byte unchanged (§4.05).
§4.05 NO-LEAK   : a GENUINE 2-cycle latency on the unpacked-array port still
                  BLOCKs (rc=1); a multi-dimension / non-constant held array
                  routes to rc=3 NOT_APPLICABLE (not a silent PASS); an array
                  event/output routes to rc=3.
#478 END-STATE  : write the unpacked-array RTL to tmp_path, invoke the REAL
                  latency_conformance_check.py via subprocess; assert rc=0 with
                  measured==1 — NOT the rc=2 non-array-assign elaboration error.

chip-AGNOSTIC: pure SV unpacked-array port grammar; no chip/SKU literal.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "latency_conformance_check.py"

_spec = importlib.util.spec_from_file_location("latency_conformance_check",
                                               str(_PROG))
lcc = importlib.util.module_from_spec(_spec)
sys.modules["latency_conformance_check"] = lcc
_spec.loader.exec_module(lcc)

_HAVE_IV = bool(shutil.which("iverilog") and shutil.which("vvp"))


# ── RTL fixtures ────────────────────────────────────────────────────────────

UNPACKED_1CYCLE = """
module String_to_ASCII_Converter(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  input  wire [7:0] char_in [7:0],
  output reg  valid
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) valid <= 1'b0;
    else if (start) valid <= 1'b1;
    else valid <= 1'b0;
  end
endmodule
"""

UNPACKED_2CYCLE = """
module String_to_ASCII_Converter(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  input  wire [7:0] char_in [7:0],
  output reg  valid
);
  reg stage1;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin valid <= 1'b0; stage1 <= 1'b0; end
    else begin stage1 <= start; valid <= stage1; end
  end
endmodule
"""

MULTIDIM = """
module md(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  input  wire [7:0] mem [0:3][7:0],
  output reg  valid
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) valid <= 1'b0;
    else valid <= start;
  end
endmodule
"""

ARRAY_OUTPUT = """
module ao(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  output reg [7:0] dout [7:0]
);
  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) for(i=0;i<8;i=i+1) dout[i] <= 0;
    else for(i=0;i<8;i=i+1) dout[i] <= start;
  end
endmodule
"""

SCALAR_DESIGN = """
module sc(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  input  wire [7:0] data_in,
  output reg  valid
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) valid <= 1'b0;
    else if (start) valid <= 1'b1;
    else valid <= 1'b0;
  end
endmodule
"""


# ── NEW-PATH: dimension recovery + element-wise modelling ───────────────────

def test_parse_unpacked_dims_recovers_postname_dim():
    m = lcc.parse_unpacked_dims(UNPACKED_1CYCLE, "String_to_ASCII_Converter")
    assert m == {"char_in": "[7:0]"}, m
    # scalar design has no post-name dim → empty map (no leak)
    assert lcc.parse_unpacked_dims(SCALAR_DESIGN, "sc") == {}


def test_unpacked_indices_single_dim_descending_and_ascending():
    pi = lcc.PortInfo("lane", "input", "[7:0]", "[7:0]")
    assert lcc._unpacked_indices(pi, {}) == [7, 6, 5, 4, 3, 2, 1, 0]
    pi2 = lcc.PortInfo("lane", "input", "[7:0]", "[0:3]")
    assert lcc._unpacked_indices(pi2, {}) == [0, 1, 2, 3]
    pi3 = lcc.PortInfo("lane", "input", "[7:0]", "[4]")  # short-form
    assert lcc._unpacked_indices(pi3, {}) == [0, 1, 2, 3]
    # multi-dim → None (left to the rc=3 fallback)
    pi4 = lcc.PortInfo("mem", "input", "[7:0]", "[0:3][7:0]")
    assert lcc._unpacked_indices(pi4, {}) is None


def test_tb_declares_and_drives_array_elementwise():
    pi = lcc.PortInfo("char_in", "input", "[7:0]", "[7:0]")
    ev = lcc.PortInfo("start", "input", "", "")
    out = lcc.PortInfo("valid", "output", "", "")
    rst = lcc.PortInfo("rst_n", "input", "", "")
    tb = lcc.build_measurement_tb(
        "String_to_ASCII_Converter", lcc.PortInfo("clk", "input", "", ""),
        [rst], ev, out, [pi], {"rst_n": True}, -1, 64, {})
    # the held array net is declared WITH its trailing unpacked dim ...
    assert "reg [7:0] char_in [7:0];" in tb, tb
    # ... and driven ELEMENT-WISE (one assignment per index), never as a single
    # illegal flat `char_in = {8{1'b1}};`.
    assert "char_in[7] = {8{1'b1}};" in tb, tb
    assert "char_in[0] = {8{1'b1}};" in tb, tb
    assert "char_in = {8{1'b1}};" not in tb, tb


# ── REGRESSION-GUARD (§4.05 — scalar TB byte-identical) ─────────────────────

def test_scalar_design_tb_unchanged_no_unpacked_artifacts():
    pi = lcc.PortInfo("data_in", "input", "[7:0]", "")   # unpacked_dims==""
    ev = lcc.PortInfo("start", "input", "", "")
    out = lcc.PortInfo("valid", "output", "", "")
    rst = lcc.PortInfo("rst_n", "input", "", "")
    tb = lcc.build_measurement_tb(
        "sc", lcc.PortInfo("clk", "input", "", ""),
        [rst], ev, out, [pi], {"rst_n": True}, -1, 64, {})
    # scalar held input declared + flat-driven exactly as before — no per-element
    # decl, no `[k] =` element drive.
    assert "reg [7:0] data_in;" in tb, tb
    assert "data_in = {8{1'b1}};" in tb, tb
    assert "data_in[" not in tb, tb
    assert "data_in [" not in tb, tb


def test_scalar_port_is_array_false():
    assert lcc.PortInfo("x", "input", "[7:0]", "").is_array is False
    assert lcc.PortInfo("x", "input", "[7:0]", "[7:0]").is_array is True


# ── #478 END-STATE: real program ────────────────────────────────────────────

def _run_lcc(args):
    cp = _pr.run([sys.executable, str(_PROG), *args],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


@pytest.mark.skipif(not _HAVE_IV,
                    reason="iverilog/vvp required to MEASURE latency")
def test_endstate_unpacked_array_now_passes(tmp_path):
    rtl = tmp_path / "test_unpacked_array.sv"
    rtl.write_text(UNPACKED_1CYCLE)
    rc, out = _run_lcc(["--rtl", str(rtl), "--top",
                        "String_to_ASCII_Converter", "--event", "start",
                        "--output", "valid", "--expect", "1"])
    # the defect was rc=2 with "Can not assign non-array identifier ... to array"
    assert "non-array identifier" not in out, out
    assert rc == 0, out
    assert "measured=1 == spec 1" in out, out


@pytest.mark.skipif(not _HAVE_IV,
                    reason="iverilog/vvp required to MEASURE latency")
def test_endstate_unpacked_array_genuine_2cycle_still_blocks(tmp_path):
    # §4.05 NO-LEAK: a REAL 2-cycle latency on the SAME unpacked-array shape vs
    # expect=1 must STILL BLOCK rc=1.
    rtl = tmp_path / "lat2.sv"
    rtl.write_text(UNPACKED_2CYCLE)
    rc, out = _run_lcc(["--rtl", str(rtl), "--top",
                        "String_to_ASCII_Converter", "--event", "start",
                        "--output", "valid", "--expect", "1"])
    assert rc == 1, out
    assert "LATENCY-MISMATCH" in out and "measured=2" in out, out


@pytest.mark.skipif(not _HAVE_IV,
                    reason="iverilog/vvp required to build/elaborate the TB")
def test_endstate_multidim_array_routes_to_not_applicable(tmp_path):
    # §4.05 NO-LEAK: a MULTI-DIMENSION held array is rc=3 NOT_APPLICABLE — NOT a
    # silent PASS and NOT the misleading hard rc=2 BLOCK.
    rtl = tmp_path / "md.sv"
    rtl.write_text(MULTIDIM)
    json_path = tmp_path / "md.json"
    rc, out = _run_lcc(["--rtl", str(rtl), "--top", "md", "--event", "start",
                        "--output", "valid", "--expect", "1",
                        "--json", str(json_path)])
    assert rc == 3, out
    import json
    rep = json.loads(json_path.read_text())
    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert "MULTI-DIMENSION" in rep["reason"], rep["reason"]


@pytest.mark.skipif(not _HAVE_IV,
                    reason="iverilog/vvp required to build/elaborate the TB")
def test_endstate_array_output_routes_to_not_applicable(tmp_path):
    # §4.05 NO-LEAK: an ARRAY measured-OUTPUT has no single-bit assertion
    # semantics → rc=3 NOT_APPLICABLE.
    rtl = tmp_path / "ao.sv"
    rtl.write_text(ARRAY_OUTPUT)
    json_path = tmp_path / "ao.json"
    rc, out = _run_lcc(["--rtl", str(rtl), "--top", "ao", "--event", "start",
                        "--output", "dout", "--expect", "1",
                        "--json", str(json_path)])
    assert rc == 3, out
    import json
    rep = json.loads(json_path.read_text())
    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert "UNPACKED-ARRAY" in rep["reason"], rep["reason"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

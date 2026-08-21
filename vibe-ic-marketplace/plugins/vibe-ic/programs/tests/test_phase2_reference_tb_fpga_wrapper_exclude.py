#!/usr/bin/env python3
"""Regression tests for ORGANIC-20260531-reference-tb-source-glob-includes-fpga-board-wrapper.

The ASIC functional reference-TB / synth source glob must exclude FPGA /
board-integration wrappers, because such a wrapper (a) `include`s a sibling
ASIC source (double-defining it) and/or (b) instantiates an FPGA-vendor hard
primitive (e.g. altsyncram) that an open-source simulator cannot elaborate —
which would tank the ASIC sim even though the ASIC RTL is perfectly fine.

The exclusion is chip-AGNOSTIC: two structural signals (sibling-include /
vendor primitive) with a `// asic-sim-include:` escape hatch.

Covers:
  - unit: _is_fpga_board_wrapper True for sibling-include wrapper, True for a
    vendor-primitive instantiation, False for a plain ASIC top / pkg, False for
    a file that includes a NON-sibling header, False when the escape marker is
    present.
  - integration: _select_asic_rtl_sources excludes the wrapper but keeps the
    clean ASIC top + pkg.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as p2  # noqa: E402


_ASIC_TOP = """
module chip_top (input wire clk, input wire reset_n, inout wire id_bus);
endmodule
"""

_PKG = """
package chip_pkg;
  localparam int W = 8;
endpackage
"""

# Board wrapper: includes a SIBLING rtl source AND instantiates a vendor PLL.
_BOARD_WRAPPER_INCLUDE_AND_PRIM = '''
`include "chip_top.sv"
module de10_board_top (input CLK50, output [9:0] LEDR);
  wire clk;
  altpll u_pll ( .inclk0(CLK50), .c0(clk) );
  chip_top u_dut ( .clk(clk), .reset_n(1'b1), .id_bus() );
endmodule
'''

# Board wrapper: vendor memory primitive only (no sibling include).
_VENDOR_MEM_WRAPPER = '''
module ram_wrap (input clk, input we, input [7:0] addr, output [7:0] q);
  altsyncram #(.WIDTH(8)) u_ram (
    .clock0(clk), .wren_a(we), .address_a(addr), .q_a(q)
  );
endmodule
'''

# Plain leaf that includes a NON-sibling external header — NOT a wrapper.
_NON_SIBLING_INCLUDE = '''
`include "external_defines.vh"
module leaf (input a, output b);
  assign b = a;
endmodule
'''

# A wrapper that includes a sibling but carries the explicit allow-marker.
_ALLOW_MARKED_INCLUDE = '''
// asic-sim-include: legitimate ASIC composition for this design
`include "chip_top.sv"
module composed_top (input wire clk, input wire reset_n, inout wire id_bus);
endmodule
'''


def _write(tmp: Path, files: dict) -> dict:
    out = {}
    for name, text in files.items():
        p = tmp / name
        p.write_text(text)
        out[name] = p
    return out


def test_unit_sibling_include_wrapper_is_excluded():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {
            "chip_top.sv": _ASIC_TOP,
            "de10_board_top.sv": _BOARD_WRAPPER_INCLUDE_AND_PRIM,
        })
        sib = set(files.keys())
        assert p2._is_fpga_board_wrapper(files["de10_board_top.sv"], sib) is True


def test_unit_vendor_primitive_only_wrapper_is_excluded():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {"ram_wrap.v": _VENDOR_MEM_WRAPPER})
        sib = set(files.keys())
        # No sibling include, but altsyncram alone is enough.
        assert p2._is_fpga_board_wrapper(files["ram_wrap.v"], sib) is True


def test_unit_plain_asic_top_is_not_wrapper():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {"chip_top.sv": _ASIC_TOP})
        sib = set(files.keys())
        assert p2._is_fpga_board_wrapper(files["chip_top.sv"], sib) is False


def test_unit_pkg_is_not_wrapper():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {"chip_pkg.sv": _PKG})
        sib = set(files.keys())
        assert p2._is_fpga_board_wrapper(files["chip_pkg.sv"], sib) is False


def test_unit_non_sibling_include_is_not_wrapper():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {"leaf.v": _NON_SIBLING_INCLUDE})
        sib = set(files.keys())  # external_defines.vh is NOT in rtl/
        assert p2._is_fpga_board_wrapper(files["leaf.v"], sib) is False


def test_unit_allow_marker_overrides_sibling_include():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _write(tmp, {
            "chip_top.sv": _ASIC_TOP,
            "composed_top.sv": _ALLOW_MARKED_INCLUDE,
        })
        sib = set(files.keys())
        # The allow-marker disables the sibling-include signal; no vendor
        # primitive present -> not a wrapper.
        assert p2._is_fpga_board_wrapper(files["composed_top.sv"], sib) is False


def test_integration_selector_excludes_wrapper_keeps_asic_and_pkg():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, {
            "chip_pkg.sv": _PKG,
            "chip_top.sv": _ASIC_TOP,
            "de10_board_top.sv": _BOARD_WRAPPER_INCLUDE_AND_PRIM,
            "ram_wrap.v": _VENDOR_MEM_WRAPPER,
        })
        selected = {p.name for p in p2._select_asic_rtl_sources(tmp)}
        assert "chip_top.sv" in selected
        assert "chip_pkg.sv" in selected
        assert "de10_board_top.sv" not in selected, "sibling+prim wrapper kept"
        assert "ram_wrap.v" not in selected, "vendor-primitive wrapper kept"


def test_integration_selector_still_excludes_testbenches():
    """Regression: the unified selector still drops TB files (prior behavior)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, {
            "chip_top.sv": _ASIC_TOP,
            "tb_chip_top.v": "module tb_chip_top; endmodule\n",
            "chip_top_tb.sv": "module chip_top_tb; endmodule\n",
        })
        selected = {p.name for p in p2._select_asic_rtl_sources(tmp)}
        assert selected == {"chip_top.sv"}, selected

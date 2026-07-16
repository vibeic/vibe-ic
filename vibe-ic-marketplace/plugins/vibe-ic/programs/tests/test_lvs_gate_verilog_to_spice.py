"""Unit tests for `gate_verilog_to_spice.py`.

Pin the deterministic structural-Verilog -> netgen-LVS-source-SPICE
conversion: cell-pin-order learning (`parse_cell_pins`), net normalisation
(`norm`: 1'b0->VSS, 1'b1->VDD, bus `x[3]`->`x.3`), full structural parse
(`parse_verilog`: bus expansion + `assign` alias resolution + instance
pinmaps), and the end-to-end `convert` emitter (global power tie-off,
`.SUBCKT`, one `X` line per known instance, unknown cells skipped + noted).

Pure Python, no `pya`, no EDA tools. Chip-AGNOSTIC synthetic fixtures.
"""
import importlib

import pytest

mod = importlib.import_module("gate_verilog_to_spice")


# Tiny cell library — only the .subckt header (pin ORDER) matters to the parser.
SYNTH_CELLS = """\
* tiny synthetic cell library
.SUBCKT NOR2D1 A B Y VDD VSS
M0 Y A VSS VSS nmos L=0.18U W=1U
M1 Y B VSS VSS nmos L=0.18U W=1U
.ENDS
.subckt BUFD1 A Y VDD VSS
.ends
"""

# Structural netlist: a 4-bit bus input, an aliased output (y <- y_r), one
# known instance (NOR2D1) and one unknown cell (FILLCAP, not in the library).
SYNTH_V = """\
// structural gate-level netlist
module top (a, y);
  input [3:0] a;
  output y;
  wire y_r;
  assign y = y_r;
  NOR2D1 u0 (.A(a[0]), .B(a[1]), .Y(y_r));
  FILLCAP uf (.VDD(a[2]));
endmodule
"""

# Same, minus the unknown fill cell — used to pin the parse_verilog contract.
PARSE_V = """\
module top (a, y);
  input [3:0] a;
  output y;
  wire y_r;
  assign y = y_r;
  NOR2D1 u0 (.A(a[0]), .B(a[1]), .Y(y_r));
endmodule
"""


class TestParseCellPins:
    def test_two_cells(self):
        cp = mod.parse_cell_pins(SYNTH_CELLS)
        assert set(cp.keys()) == {"NOR2D1", "BUFD1"}

    def test_pin_order_preserved(self):
        cp = mod.parse_cell_pins(SYNTH_CELLS)
        assert cp["NOR2D1"] == ["A", "B", "Y", "VDD", "VSS"]

    def test_case_insensitive_subckt_keyword(self):
        # `.SUBCKT` and `.subckt` are both recognised.
        cp = mod.parse_cell_pins(SYNTH_CELLS)
        assert cp["BUFD1"] == ["A", "Y", "VDD", "VSS"]

    def test_no_subckt_returns_empty(self):
        assert mod.parse_cell_pins("* just a comment\nM0 a b c d nmos\n") == {}


class TestNorm:
    def test_const_zero(self):
        assert mod.norm("1'b0") == "VSS"
        assert mod.norm("1'B0") == "VSS"

    def test_const_one(self):
        assert mod.norm("1'b1") == "VDD"
        assert mod.norm("1'B1") == "VDD"

    def test_bus_bit_to_dot(self):
        assert mod.norm("x[3]") == "x.3"
        assert mod.norm("data[10]") == "data.10"

    def test_plain_net_unchanged(self):
        assert mod.norm("y_r") == "y_r"

    def test_strips_whitespace(self):
        assert mod.norm("  clk  ") == "clk"


class TestParseVerilog:
    def test_top_name(self):
        top, _ports, _insts = mod.parse_verilog(PARSE_V)
        assert top == "top"

    def test_bus_expanded_ports_msb_first(self):
        _top, ports, _insts = mod.parse_verilog(PARSE_V)
        assert ports == ["a.3", "a.2", "a.1", "a.0", "y"]

    def test_alias_resolves_output_port(self):
        # `assign y = y_r;` means the y_r net is the port net y.
        _top, ports, _insts = mod.parse_verilog(PARSE_V)
        assert "y" in ports
        assert "y_r" not in ports

    def test_single_instance(self):
        _top, _ports, insts = mod.parse_verilog(PARSE_V)
        assert len(insts) == 1
        cell, inst, _pinmap = insts[0]
        assert (cell, inst) == ("NOR2D1", "u0")

    def test_instance_pinmap_with_bus_and_alias(self):
        _top, _ports, insts = mod.parse_verilog(PARSE_V)
        _cell, _inst, pinmap = insts[0]
        # A/B are bus bits (dotted); Y is the y_r net resolved through the alias.
        assert pinmap == {"A": "a.0", "B": "a.1", "Y": "y"}


class TestConvert:
    def _write(self, tmp_path, vtext=SYNTH_V, ctext=SYNTH_CELLS):
        v = tmp_path / "top.v"
        v.write_text(vtext)
        c = tmp_path / "cells.spice"
        c.write_text(ctext)
        out = tmp_path / "source.spice"
        return str(v), str(c), str(out)

    def test_end_to_end(self, tmp_path, capsys):
        v, c, out = self._write(tmp_path)
        rc = mod.convert(v, c, out)
        assert rc == 0
        text = (tmp_path / "source.spice").read_text()

        # global power tie-off + subckt header with the bus-expanded ports
        assert ".GLOBAL VDD VSS" in text
        assert ".SUBCKT top a.3 a.2 a.1 a.0 y" in text

        # exactly one X line (the unknown FILLCAP is skipped, not emitted)
        x_lines = [ln for ln in text.splitlines() if ln.startswith("X")]
        assert len(x_lines) == 1
        # nets follow the cell's pin ORDER; VDD/VSS tie to the globals
        assert x_lines[0] == "Xu0 a.0 a.1 y VDD VSS NOR2D1"

    def test_unknown_cell_reported_in_note(self, tmp_path, capsys):
        v, c, out = self._write(tmp_path)
        mod.convert(v, c, out)
        captured = capsys.readouterr()
        assert "NOTE" in captured.out
        assert "FILLCAP" in captured.out

    def test_include_cells_default_on(self, tmp_path):
        v, c, out = self._write(tmp_path)
        mod.convert(v, c, out)
        text = (tmp_path / "source.spice").read_text()
        assert ".include" in text

    def test_include_cells_can_be_disabled(self, tmp_path):
        v, c, out = self._write(tmp_path)
        mod.convert(v, c, out, include_cells=False)
        text = (tmp_path / "source.spice").read_text()
        assert ".include" not in text

    def test_unconnected_signal_pin_becomes_dangle(self, tmp_path):
        # A known cell whose signal pin C is left unconnected (and is not
        # VDD/VSS) must get a unique DANGLE net, not be silently dropped.
        cells = ".subckt AOI21 A B C Y VDD VSS\n.ends\n"
        vtext = ("module top (a, y);\n"
                 "  input a;\n  output y;\n"
                 "  AOI21 u0 (.A(a), .B(a), .Y(y));\n"
                 "endmodule\n")
        v, c, out = self._write(tmp_path, vtext=vtext, ctext=cells)
        rc = mod.convert(v, c, out)
        assert rc == 0
        text = (tmp_path / "source.spice").read_text()
        assert "DANGLE_1" in text


# ---------------------------------------------------------------------------
# Escaped Verilog identifier + bit-select tokenisation.
#
# A yosys post-PnR netlist declares a hierarchical bus as an ESCAPED identifier
# `wire [7:0] \blk.sub.reg.q ;` and a bit-select on it as `\blk.sub.reg.q [2]`:
# the space TERMINATES the escaped id (Verilog LRM) and the trailing `[2]` is the
# bit-select that BELONGS to the net. If `norm()` keeps that terminator space in
# the middle of the name, `[->.` yields `\blk.sub.reg.q .2` and `' '.join(nets)`
# splits ONE net into TWO SPICE tokens, overflowing the cell's pin arity ->
# netgen "Too many parameters in call in <cell>". These tests pin the collapse to
# a single node AND that ordinary (non-escaped) `bus[N]` stays byte-unchanged.
# Fictional hierarchies only — nothing hardcoded from any real design.
# ---------------------------------------------------------------------------
class TestEscapedBusBitSelect:
    def test_escaped_id_bitselect_is_single_token(self):
        # the space between the escaped id and its bit-select is collapsed
        assert mod.norm(r"\blk.sub.reg.q [2]") == r"\blk.sub.reg.q.2"

    def test_escaped_id_bitselect_no_internal_space(self):
        out = mod.norm(r"\a.b.c [0]")
        assert " " not in out
        assert out == r"\a.b.c.0"

    def test_escaped_id_multidigit_bit(self):
        assert mod.norm(r"\dut.pipe.stage.acc [31]") == r"\dut.pipe.stage.acc.31"

    def test_escaped_bare_id_unchanged(self):
        # an escaped scalar (no bit-select) is left as-is
        assert mod.norm(r"\blk.sub.reg.i_en") == r"\blk.sub.reg.i_en"

    def test_ordinary_bus_byte_unchanged(self):
        # REGRESSION: a plain (non-escaped) bus bit is untouched by the escaped
        # path — no `\`, so the whitespace-collapse never runs.
        assert mod.norm("data[7]") == "data.7"
        assert mod.norm("q[10]") == "q.10"
        assert mod.norm("n_1234") == "n_1234"

    def test_escaped_bus_full_convert_correct_arity(self, tmp_path):
        # End-to-end: two cells share the SAME escaped bus bits. Every emitted
        # X-line must have exactly (1 + n_pins + 1) whitespace fields — the
        # escaped net must NOT add a phantom token.
        cells = (".SUBCKT INVD1 I ZN VDD VSS\n.ENDS\n"
                 ".SUBCKT NOR2D1 A1 A2 ZN VDD VSS\n.ENDS\n")
        vtext = (
            "module widget (o_out, i_in);\n"
            "  input i_in;\n  output o_out;\n"
            "  wire [7:0] \\blk.sub.reg.q ;\n"
            "  INVD1 _00_ (.I(\\blk.sub.reg.q [2]), .ZN(o_out),"
            " .VDD(VDD), .VSS(VSS));\n"
            "  NOR2D1 _01_ (.A1(\\blk.sub.reg.q [7]),\n"
            "    .A2(\\blk.sub.reg.q [6]),\n"
            "    .ZN(\\blk.sub.reg.q [2]), .VDD(VDD), .VSS(VSS));\n"
            "  INVD1 _02_ (.I(i_in), .ZN(\\blk.sub.reg.q [7]),"
            " .VDD(VDD), .VSS(VSS));\n"
            "endmodule\n"
        )
        v = tmp_path / "widget.v"; v.write_text(vtext)
        c = tmp_path / "cells.spice"; c.write_text(cells)
        out = tmp_path / "src.spice"
        rc = mod.convert(str(v), str(c), str(out), include_cells=False)
        assert rc == 0
        x_lines = [ln for ln in out.read_text().splitlines()
                   if ln.startswith("X")]
        assert len(x_lines) == 3
        by_inst = {ln.split()[0]: ln for ln in x_lines}
        # INVD1 = X + 4 nets + cell = 6 fields; NOR2D1 = X + 5 nets + cell = 7.
        assert len(by_inst["X_00_"].split()) == 6
        assert len(by_inst["X_02_"].split()) == 6
        assert len(by_inst["X_01_"].split()) == 7
        # the escaped bus bit is ONE token, and the SAME string wherever it
        # appears (so netgen sees one shared node -> topology preserved).
        assert r"\blk.sub.reg.q.2" in by_inst["X_00_"].split()
        assert r"\blk.sub.reg.q.2" in by_inst["X_01_"].split()
        assert r"\blk.sub.reg.q.7" in by_inst["X_01_"].split()
        assert r"\blk.sub.reg.q.7" in by_inst["X_02_"].split()
        # no emitted line carries a bare ` .N` phantom token
        for ln in x_lines:
            assert " ." not in ln

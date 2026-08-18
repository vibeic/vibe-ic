"""Regression tests for _specrtl_common port parsing:

  * defect #3 — the JSON spec loader must accept the `dir` port key (the shape
    the canonical phase1_port_extract / L9-L17 L-docs emit), not only
    `direction`, else every port is silently read as `input`.
  * defect #4 — a parameterized RTL port bound (`[WB_AW-1:0]`) must resolve to
    the in-module parameter where possible and otherwise be WIDTH_UNKNOWN,
    NEVER a literal 1 (which fabricates a false width-mismatch).
"""
import importlib

C = importlib.import_module("_specrtl_common")


# ---------------------------------------------------------------------------
# defect #3 — JSON spec `dir` / `direction` alias
# ---------------------------------------------------------------------------
class TestJsonDirAlias:
    def test_dir_key_read(self):
        assert C._json_port_direction({"dir": "output"}) == "output"

    def test_direction_key_still_read(self):
        assert C._json_port_direction({"direction": "output"}) == "output"

    def test_abbreviations_normalized(self):
        assert C._json_port_direction({"dir": "out"}) == "output"
        assert C._json_port_direction({"dir": "in"}) == "input"
        assert C._json_port_direction({"dir": "io"}) == "inout"

    def test_missing_defaults_input(self):
        assert C._json_port_direction({"name": "x"}) == "input"

    def test_extract_spec_contract_json_reads_dir(self):
        js = ('{"module":"m","ports":['
              '{"name":"a","dir":"input","width":8},'
              '{"name":"y","dir":"output","width":8}]}')
        c = C.extract_spec_contract(js, is_json=True, confirm=False)
        by = {p.name: p.direction for p in c.ports}
        assert by == {"a": "input", "y": "output"}


# ---------------------------------------------------------------------------
# defect #4 — parameterized / symbolic port width resolution
# ---------------------------------------------------------------------------
class TestParamWidth:
    def test_literal_range_unchanged(self):
        ports = C.parse_verilog_ports("input [7:0] d;")
        assert ports[0].width == 8

    def test_scalar_no_bracket_is_one(self):
        ports = C.parse_verilog_ports("input clk;")
        assert ports[0].width == 1

    def test_param_bound_resolved_from_module(self):
        src = ("module m #(parameter WB_AW = 32, parameter WB_DW = 16)("
               "input [WB_AW-1:0] adr, input [WB_DW-1:0] dat); endmodule")
        by = {p.name: p.width for p in C.parse_verilog_ports(src)}
        assert by["adr"] == 32
        assert by["dat"] == 16

    def test_clog2_and_arithmetic_bound(self):
        src = ("module m #(parameter DEPTH = 256, parameter N = 4)("
               "input [$clog2(DEPTH)-1:0] a, input [N*8-1:0] b); endmodule")
        by = {p.name: p.width for p in C.parse_verilog_ports(src)}
        assert by["a"] == 8    # clog2(256) = 8 -> [7:0]
        assert by["b"] == 32   # 4*8 = 32 -> [31:0]

    def test_unresolvable_bound_is_unknown_not_one(self):
        # WB_AW is not declared in-module -> UNKNOWN, must NOT be 1.
        ports = C.parse_verilog_ports("input [WB_AW-1:0] adr;")
        assert ports[0].width == C.WIDTH_UNKNOWN
        assert ports[0].width != 1

    def test_local_param_chain_resolves(self):
        src = ("module m #(parameter W = 8)("
               "input [W2-1:0] d); localparam W2 = W*2; endmodule")
        by = {p.name: p.width for p in C.parse_verilog_ports(src)}
        assert by["d"] == 16

    def test_parse_rtl_ports_threads_params(self):
        src = ("module top #(parameter AW = 12)("
               "input clk, input [AW-1:0] addr, output [7:0] q); endmodule")
        _, ports = C.parse_rtl_ports(src, "top")
        by = {p.name: p.width for p in ports}
        assert by == {"clk": 1, "addr": 12, "q": 8}

    def test_json_symbolic_width_is_unknown(self):
        c = C.extract_spec_contract(
            '{"ports":[{"name":"a","dir":"input","width":"WB_AW"}]}',
            is_json=True, confirm=False)
        assert c.ports[0].width == C.WIDTH_UNKNOWN

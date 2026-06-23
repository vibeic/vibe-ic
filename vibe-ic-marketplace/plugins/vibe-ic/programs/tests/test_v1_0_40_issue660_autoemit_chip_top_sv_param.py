"""ORGANIC #660 — auto-emitted chip_top wrapper copies SV-only param syntax
into a .v file that the reference_tb sv2v fallback (.sv-only filter) never
converts.

_autoemit_chip_top_if_needed copied the wrapped DUT's `#(parameter …)` block
VERBATIM into the wrapper header and ALWAYS wrote `<top>.v`. When that param
block carries package-scoped enum/type param syntax
(`parameter ibex_pkg::rv32m_e RV32M = …`), the runner-generated `.v` carries
SV-2017-only syntax. The reference_tb sv2v pre-pass filters strictly on the
`.sv` extension and passes every `.v` UNCONVERTED to `iverilog -g2012`, which
then syntax-errors on the SV param types → the runner's OWN output fails the
sim frontend, while yosys-slang synth passes (masking the divergence).

Fix: detect SV-only param syntax in the captured param block
(_chip_top_param_block_needs_sv) and emit the wrapper as `<top>.sv` instead
of `<top>.v`, so it joins the .sv sv2v-conversion set in BOTH the synth and
reference_tb frontends. NO-LEAK: a plain Verilog-2005 param block keeps the
`.v` extension (byte-identical historical behaviour).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402


# ── SV-param detection predicate ────────────────────────────────────────────

def test_detects_package_scoped_enum_param_type():
    # the field agent's exact case (round-3 chip_top.v lines 18-20):
    pb = ("#(parameter ibex_pkg::rv32m_e RV32M = ibex_pkg::RV32MFast,\n"
          "  parameter ibex_pkg::rv32b_e RV32B = ibex_pkg::RV32BNone)")
    assert R._chip_top_param_block_needs_sv(pb) is True


def test_detects_logic_typed_param():
    pb = "#(parameter logic [31:0] BootAddr = 32'h8000_0000)"
    assert R._chip_top_param_block_needs_sv(pb) is True


def test_detects_bit_and_enum_keyword_typed_param():
    assert R._chip_top_param_block_needs_sv(
        "#(parameter bit SecureIbex = 1'b0)") is True
    assert R._chip_top_param_block_needs_sv(
        "#(parameter enum logic [1:0] {A, B} MODE = A)") is True


# ── NO-LEAK negatives: plain Verilog-2005 stays .v ──────────────────────────

def test_plain_verilog_param_does_not_need_sv():
    assert R._chip_top_param_block_needs_sv(
        "#(parameter WIDTH = 8, parameter DEPTH = 16)") is False


def test_sized_plain_param_does_not_need_sv():
    # `[N:0]`-width params are plain Verilog-2005, not SV-only.
    assert R._chip_top_param_block_needs_sv(
        "#(parameter [7:0] INIT = 8'hFF)") is False


def test_empty_param_block_does_not_need_sv():
    assert R._chip_top_param_block_needs_sv("") is False
    assert R._chip_top_param_block_needs_sv("   ") is False


def test_param_name_containing_double_colon_text_not_falsefired():
    # a localparam computed from a plain expression must NOT false-fire (no
    # `::` scope-resolution as a TYPE between `parameter` and the name).
    assert R._chip_top_param_block_needs_sv(
        "#(parameter N = 4, parameter M = N*2)") is False


# ── end-to-end: param capture → extension routing, via the SAME regex +
#    helpers the autoemit closure uses (mod_re then _extract_param_and_ports)─

# the EXACT module-decl regex _autoemit_chip_top_if_needed uses (L4341):
import re as _re  # noqa: E402
_MOD_RE = _re.compile(r"^\s*module\s+([A-Za-z_]\w*)\s*[(#]", _re.M)


def _capture_param_block(dut_src: str, mod_name: str) -> str:
    """Mirror the autoemit's param/port capture for `mod_name`."""
    masked = R._chip_top_mask_comments(dut_src)
    for m in _MOD_RE.finditer(masked):
        if m.group(1) != mod_name:
            continue
        param_block, port_block = R._chip_top_extract_param_and_ports(
            masked, m.end() - 1)
        assert port_block is not None, "autoemit would have captured a port block"
        return param_block
    raise AssertionError(f"module {mod_name} not matched by autoemit regex")


def test_autoemit_writes_dot_sv_for_pkg_enum_dut():
    # A DUT whose ANSI header carries a pkg::enum param type → the captured
    # param block trips _chip_top_param_block_needs_sv → the autoemit writes
    # chip_top.sv (joining the sv2v set), NOT chip_top.v.
    dut = (
        "module core\n"
        "  #(parameter ibex_pkg::rv32m_e RV32M = ibex_pkg::RV32MFast)\n"
        "  (input wire clk, input wire rst_n, output wire done);\n"
        "  assign done = 1'b0;\n"
        "endmodule\n")
    pb = _capture_param_block(dut, "core")
    assert R._chip_top_param_block_needs_sv(pb) is True   # → .sv selected


def test_autoemit_writes_dot_v_for_plain_verilog_dut():
    # NO-LEAK: a plain Verilog-2005 param block keeps the .v extension.
    dut = (
        "module adder #(parameter WIDTH = 8)\n"
        "  (input wire [WIDTH-1:0] a, input wire [WIDTH-1:0] b,\n"
        "   output wire [WIDTH-1:0] y);\n"
        "  assign y = a + b;\n"
        "endmodule\n")
    pb = _capture_param_block(dut, "adder")
    assert R._chip_top_param_block_needs_sv(pb) is False  # → .v stays

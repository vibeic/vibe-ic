"""ORGANIC #582 — the auto-emitted chip_top wrapper copied a NON-ANSI DUT
port list verbatim (sv2v output is always non-ANSI: header lists bare
names, directions/widths live in body declarations) and emitted no I/O
declarations: `module chip_top ( name1, name2, ... );` + instance only.
yosys rejected it with "port 'X' has no I/O member declaration" for every
port, failing yosys_synth on the whole staged-vendor-RTL path.

Fix: _chip_top_nonansi_port_decls() detects the direction-keyword-free
port list, harvests the DUT body's input/output/inout declarations for
the listed names (storage keywords dropped per #463; `wire` made explicit
for `default_nettype none`), and the wrapper emits them in its body.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as P2  # noqa: E402

iverilog = shutil.which("iverilog")
needs_iverilog = pytest.mark.skipif(iverilog is None,
                                    reason="iverilog not installed")

# sv2v-shaped non-ANSI DUT (the issue's exact shape: bare-name header,
# body declarations incl. multi-name lists, reg storage, signed, widths).
_SV2V_DUT = """\
module crypto_core (
\tclk_i,
\trst_ni,
\tdata_i,
\tdata_o,
\tbusy_o,
\tirq_o
);
\tinput wire clk_i;
\tinput wire rst_ni;
\tinput wire [31:0] data_i;
\toutput reg [31:0] data_o;
\toutput wire busy_o, irq_o;
\talways @(posedge clk_i or negedge rst_ni)
\t\tif (!rst_ni) data_o <= 32'b0;
\t\telse data_o <= data_i;
\tassign busy_o = 1'b0;
\tassign irq_o = 1'b0;
endmodule
"""

_PORTS = ["clk_i", "rst_ni", "data_i", "data_o", "busy_o", "irq_o"]


def _harvest(dut_text: str, mod: str, ports):
    return P2._chip_top_nonansi_port_decls(
        P2._chip_top_mask_comments(dut_text), mod, ports)


# ── helper semantics ─────────────────────────────────────────────────────────

def test_harvest_finds_all_declarations():
    decls = _harvest(_SV2V_DUT, "crypto_core", _PORTS)
    assert decls is not None
    assert "input wire clk_i;" in decls
    assert "input wire [31:0] data_i;" in decls
    # reg storage dropped (#463: wrapper nets are instance-driven)
    assert "output wire [31:0] data_o;" in decls
    assert "reg" not in decls
    # multi-name declaration split per port
    assert "output wire busy_o;" in decls
    assert "output wire irq_o;" in decls


def test_harvest_returns_none_on_missing_port():
    assert _harvest(_SV2V_DUT, "crypto_core", _PORTS + ["ghost"]) is None


def test_harvest_handles_signed_and_multibracket():
    dut = (
        "module m ( a, q );\n"
        "  input signed [7:0] a;\n"
        "  output [1:0] [3:0] q;\n"
        "endmodule\n"
    )
    decls = _harvest(dut, "m", ["a", "q"])
    assert decls is not None
    assert "input wire signed [7:0] a;" in decls
    assert "output wire [1:0] [3:0] q;" in decls


# ── the issue's exact 現象 end-state: wrapper + DUT must parse ──────────────

def _emit_wrapper(decls: str) -> str:
    """Assemble the wrapper exactly as the auto-emit path does (header,
    `default_nettype none`, bare-name port list, harvested decls,
    pass-through instance)."""
    connects = ",\n    ".join(f".{n}({n})" for n in _PORTS)
    return (
        "`default_nettype none\n"
        "module chip_top (" + ", ".join(_PORTS) + ");\n"
        + decls + "\n"
        "  crypto_core u_dut (\n    " + connects + "\n  );\n"
        "endmodule\n"
        "`default_nettype wire\n"
    )


@needs_iverilog
def test_wrapper_with_harvested_decls_parses(tmp_path):
    """驗收 1: the emitted wrapper parses under `iverilog -t null`
    (pre-fix shape aborts with 'port X has no I/O member declaration')."""
    decls = _harvest(_SV2V_DUT, "crypto_core", _PORTS)
    assert decls is not None
    (tmp_path / "crypto_core.v").write_text(_SV2V_DUT)
    (tmp_path / "chip_top.v").write_text(_emit_wrapper(decls))
    result = subprocess.run(
        [iverilog, "-g2012", "-t", "null",
         str(tmp_path / "crypto_core.v"), str(tmp_path / "chip_top.v")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "has no I/O member declaration" not in result.stderr


@needs_iverilog
def test_preflix_shape_fails_proving_harness(tmp_path):
    """NEGATIVE pin: the v0.3.38 broken wrapper (verbatim bare-name list,
    no decls) must FAIL the same harness — proving the test catches the
    defect class."""
    (tmp_path / "crypto_core.v").write_text(_SV2V_DUT)
    (tmp_path / "chip_top.v").write_text(_emit_wrapper(""))
    result = subprocess.run(
        [iverilog, "-g2012", "-t", "null",
         str(tmp_path / "crypto_core.v"), str(tmp_path / "chip_top.v")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


# ── regression: ANSI DUT path unchanged ─────────────────────────────────────

def test_ansi_port_block_not_treated_as_nonansi():
    """An ANSI port block carries direction keywords — the non-ANSI
    detection regex must not fire (decl harvest reserved for sv2v shape)."""
    import re
    ansi_block = "(input wire clk, input wire [3:0] d, output reg [3:0] q)"
    assert re.search(r"\b(?:input|output|inout)\b", ansi_block)

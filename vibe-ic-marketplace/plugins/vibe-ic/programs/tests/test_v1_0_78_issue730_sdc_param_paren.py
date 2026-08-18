"""ORGANIC #730 [HIGH] — sdc_gen._parse_module_ports split on the FIRST '(',
which on a parameterized ANSI top `module foo #(parameter integer A=10)(input
wire i_clk, ...)` is the `#(parameter...)` block. It therefore captured the
PARAMETER names as ports and DROPPED every real port. The emitted SDC then
named `get_ports {clk}` (matching nothing) instead of the real clock i_clk, so
STA/PnR had no valid clock constraint and zero I/O delay / false_path.

Fix: in _parse_module_ports, after locating `module <name>`, skip an optional
leading `#(...)` parameter block via a BALANCED-paren scan BEFORE taking the
port-list '('. Applies equally to _collect_all_module_ports (it calls
_parse_module_ports per module header). Parameter names must NEVER leak.

POSITIVE (#730): a parameterized ANSI top returns its real ports
(i_clk/i_rst/...), parameter names (AW/DW/MEMSIZE/RESET_PC) never appear, and
i_clk is detected as the clock.

NEGATIVE no-leak / no-regression (§4.05): a NON-parameterized header (no `#()`)
still parses correctly and its genuine clock/ports are still detected.

chip-AGNOSTIC: pure Verilog/SV module-header parsing; no chip names.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import sdc_gen as G  # noqa: E402
import _path_layout as _pl  # noqa: E402


# A bit-serial RISC-V SoC top, faithful to the round-11 #730 reproduction:
# a `#(...)` parameter block (AW/DW/MEMSIZE/RESET_PC) ahead of the real ANSI
# port list (i_clk/i_rst/i_gpio/o_gpio/SRAM bus).
PARAM_TOP = """\
module riscv_soc_top #(
    parameter integer AW       = 16,
    parameter integer DW       = 32,
    parameter         MEMSIZE  = 4096,
    parameter [31:0]  RESET_PC = 32'h0000_0000
) (
    input  wire             i_clk,
    input  wire             i_rst,
    input  wire [7:0]       i_gpio,
    output wire [7:0]       o_gpio,
    input  wire [DW-1:0]    i_sram_data,
    output wire [AW-1:0]    o_sram_addr,
    output wire             o_sram_cyc,
    output wire [DW-1:0]    o_sram_data,
    output wire             o_sram_we
);
endmodule
"""

PARAM_NAMES = {"AW", "DW", "MEMSIZE", "RESET_PC"}
REAL_PORTS = {"i_clk", "i_rst", "i_gpio", "o_gpio",
              "i_sram_data", "o_sram_addr", "o_sram_cyc",
              "o_sram_data", "o_sram_we"}


# ── POSITIVE #730 — parameterized ANSI top ─────────────────────────────────

def test_param_names_never_in_port_set():
    """(a) parameter names never leak into the returned port set."""
    parsed = {name for name, _d, _w in G._parse_module_ports(PARAM_TOP)}
    for p in PARAM_NAMES:
        assert p not in parsed, f"parameter {p} leaked into port set (#730)"


def test_real_ports_returned_not_dropped():
    """(c) the real ports (i_clk/i_rst/...) are returned, not dropped."""
    parsed = {name for name, _d, _w in G._parse_module_ports(PARAM_TOP)}
    assert REAL_PORTS <= parsed, (
        f"real ports dropped (#730): missing {REAL_PORTS - parsed}")


def test_i_clk_detected_as_clock():
    """(b) i_clk is detected as the clock."""
    parsed = [name for name, _d, _w in G._parse_module_ports(PARAM_TOP)]
    clocks = [n for n in parsed if G._is_clock(n)]
    assert clocks == ["i_clk"], f"expected i_clk as the sole clock, got {clocks}"
    # And nothing fabricated like a bare 'clk'.
    assert "clk" not in parsed


def test_width_uses_first_port_not_param():
    """Param-block widths/bit-ranges must not bleed into port widths; the
    first real port (i_clk) is a scalar."""
    parsed = G._parse_module_ports(PARAM_TOP)
    by_name = {n: (d, w) for n, d, w in parsed}
    assert by_name["i_clk"] == ("input", 1)
    assert by_name["i_gpio"][1] == 8
    assert by_name["i_gpio"][0] == "input"
    assert by_name["o_gpio"][0] == "output"


def test_collect_union_param_top():
    """_collect_all_module_ports (calls _parse_module_ports per header) must
    likewise return only real ports, never parameter names."""
    d = Path(tempfile.mkdtemp())
    rd = _pl.rtl_dir(d)
    rd.mkdir(parents=True)
    (rd / "riscv_soc_top.v").write_text(PARAM_TOP)
    names = G._collect_all_module_ports(G._list_rtl(d))
    assert REAL_PORTS <= names, f"missing {REAL_PORTS - names}"
    assert not (PARAM_NAMES & names), f"param names leaked: {PARAM_NAMES & names}"


def test_param_top_emits_real_clock_in_sdc():
    """End-to-end: SDC for a parameterized top names the real clock i_clk,
    NOT a phantom 'clk' that matches nothing."""
    d = Path(tempfile.mkdtemp())
    gd = _pl.generated_docs_dir(d)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": 100.0}))
    pins = [{"name": n, "mode": "input" if n.startswith("i_") else "output"}
            for n in sorted(REAL_PORTS)]
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": "riscv_soc_top", "top_module_pins": pins}))
    rd = _pl.rtl_dir(d)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "riscv_soc_top.v").write_text(PARAM_TOP)

    G.main([str(d), "--top-name", "riscv_soc_top", "--force"])
    sdc = (_pl.fpga_early_dir(d) / "riscv_soc_top.sdc").read_text()
    emitted = set(re.findall(r"get_ports\s+\{?\s*([A-Za-z_]\w*)", sdc))
    # The real clock survives the #619 RTL-surface intersection.
    assert "i_clk" in emitted, "real clock i_clk dropped (#730/#619 interplay)"
    # No parameter name appears as a constrained port.
    assert not (PARAM_NAMES & emitted), f"param leaked into SDC: {PARAM_NAMES & emitted}"
    # The clock create_clock targets i_clk (not a phantom bare clk).
    cc = re.findall(r"create_clock[^\n]*get_ports\s+\{?\s*([A-Za-z_]\w*)", sdc)
    assert cc and all(c == "i_clk" for c in cc), f"create_clock targets {cc}, not i_clk"


# ── NEGATIVE no-leak / no-regression (§4.05) — non-parameterized header ─────

NONPARAM_TOP = """\
module ctrl_top (
    input  wire        i_clk,
    input  wire        i_rst,
    input  wire [7:0]  i_gpio,
    output wire [7:0]  o_gpio
);
endmodule
"""


def test_nonparam_header_still_parses():
    """A header with NO `#()` must still parse correctly (no regression)."""
    parsed = {name for name, _d, _w in G._parse_module_ports(NONPARAM_TOP)}
    assert parsed == {"i_clk", "i_rst", "i_gpio", "o_gpio"}


def test_nonparam_clock_still_detected():
    """A genuine clock is still detected on a non-parameterized header."""
    parsed = [name for name, _d, _w in G._parse_module_ports(NONPARAM_TOP)]
    clocks = [n for n in parsed if G._is_clock(n)]
    assert clocks == ["i_clk"], f"expected i_clk, got {clocks}"


def test_nonparam_widths_correct():
    parsed = G._parse_module_ports(NONPARAM_TOP)
    by_name = {n: (d, w) for n, d, w in parsed}
    assert by_name["i_clk"] == ("input", 1)
    assert by_name["i_gpio"] == ("input", 8)
    assert by_name["o_gpio"] == ("output", 8)

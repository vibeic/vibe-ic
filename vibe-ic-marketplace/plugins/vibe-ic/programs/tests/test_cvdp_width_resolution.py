"""test_cvdp_width_resolution.py — parameterized-width resolution for the CVDP
complete-extraction layer.

The dominant CVDP EXTRACTION_GAP types were ports whose WIDTH is a PARAMETER
EXPRESSION the literal `[\\d+:\\d+]` reader could not resolve:

  param_expression_width  — `[N-1:0]`, `[DATA_WIDTH-1:0]`, `[$clog2(DEPTH)-1:0]`
  param_override_width    — `[N*IN_WIDTH-1:0]` / a `NUM_INPUTS * WIDTH` cell
  range_before_name       — `[1:0] resp_o` (literal range PRECEDES the name)

verilog_width_resolve reads those forms from the PROMPT (+ input.context) WITHOUT
touching any golden RTL body or the hidden cocotb harness: it harvests the
parameter-DEFAULT table from the prompt's partial module header / prose /
parameter table, then resolves each port's symbolic width to its integer default.

§4.05 (the load-bearing rule): a width is resolved ONLY when every identifier in
the span has a derivable default. A parameter expression whose parameter has NO
derivable default stays a GAP — never a fabricated width.

§4.05 CVDP COMPLIANCE: the interface is recovered from the PROMPT's declared
Input/Output ports (+ input.context header), NEVER the cocotb `dut.<sig>` test /
`.env` / golden output. The completeness split is a pure PROMPT-COMPLETENESS check.

CHIP-AGNOSTIC: renaming the module + every identifier yields the SAME widths and
the SAME completeness verdict.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import cvdp_atomic_bridge as B  # noqa: E402
import cvdp_complete_extract as CE  # noqa: E402
import verilog_width_resolve as W  # noqa: E402


# --------------------------------------------------------------------------- #
# iverilog helpers (defined first — used by a collection-time skipif decorator)
# --------------------------------------------------------------------------- #
def _have_iverilog() -> bool:
    try:
        subprocess.run(["iverilog", "-V"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _iverilog_run(rtl: str, tb: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        tbf = Path(d) / "tb.sv"
        vvp = Path(d) / "a.vvp"
        dut.write_text(rtl)
        tbf.write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(dut), str(tbf)],
                           capture_output=True, text=True, timeout=60)
        if c.returncode != 0:
            return "COMPILE_ERROR:\n" + c.stderr
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr


# --------------------------------------------------------------------------- #
# CVDP-faithful record builder (input.prompt + input.context + a DECOY harness
# with a .env TOPLEVEL + a cocotb test). The harness + golden output are OFF-
# LIMITS oracle and are NEVER read by extract().
# --------------------------------------------------------------------------- #
def _make_record(top, prompt, cocotb_test, rid=None):
    rtl_path = f"rtl/{top}.sv"
    return {
        "id": rid or f"test_{top}",
        "input": {"prompt": prompt, "context": {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"VERILOG_SOURCES = /code/{rtl_path}\n"
                f"TOPLEVEL        = {top}\n"
                f"MODULE          = test_{top}\n"
            ),
            f"src/test_{top}.py": cocotb_test,
        }},
    }


# =========================================================================== #
# (1) param-default table — harvest from prose / code / parameter-table sources
# =========================================================================== #
def test_param_defaults_from_code_prose_and_table():
    prompt = """Design `m`.
    parameter DATA_WIDTH = 8 // code-declared default
- `WIDTH`: bus width with a default value of `16` bits.
- `NUM` (Default: 4): the count.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `DEPTH`   | fifo depth  | 32      |
"""
    pd = W.param_defaults(prompt)
    assert pd["DATA_WIDTH"] == 8       # code `parameter NAME = N`
    assert pd["WIDTH"] == 16           # prose "default value of 16 bits"
    assert pd["NUM"] == 4              # "(Default: 4)"
    assert pd["DEPTH"] == 32           # parameter table default column


def test_param_defaults_derived_ternary_and_arithmetic():
    # OUT_ROW = (IN_ROW > IN_COL) ? IN_ROW : IN_COL — a derived param over knowns.
    prompt = """
    parameter IN_ROW     = 4 ,
    parameter IN_COL     = 6 ,
    parameter OUT_ROW    = (IN_ROW > IN_COL) ? IN_ROW : IN_COL ,
    parameter DATA_WIDTH = 8
"""
    pd = W.param_defaults(prompt)
    assert pd["IN_ROW"] == 4 and pd["IN_COL"] == 6 and pd["DATA_WIDTH"] == 8
    assert pd["OUT_ROW"] == 6, "ternary-derived param not resolved"


# =========================================================================== #
# (2) width-expression evaluator — the parameter-expression forms
# =========================================================================== #
def test_eval_width_expr_forms():
    p = {"N": 8, "IN_WIDTH": 4, "DEPTH": 16, "M": 5}
    assert W.eval_width_expr("N-1", p) == 7
    assert W.eval_width_expr("N*IN_WIDTH-1", p) == 31
    assert W.eval_width_expr("$clog2(DEPTH)-1", p) == 3   # clog2(16)=4 -> 3
    assert W.eval_width_expr("M-2", p) == 3
    # §4.05: an unbound identifier yields None (never a guess).
    assert W.eval_width_expr("UNKNOWN-1", p) is None


# =========================================================================== #
# (3) POSITIVE — param_expression_width RESOLVES to a placed port + COMPLETE
# =========================================================================== #
PARAM_EXPR_PROMPT = """Complete the parameterized module named `rotate8`.

### Parameterization
- The module supports a parameterized data width, `DATA_WIDTH`, with a default
  value of 8 bits.

### Inputs:
- **`i_data`** (logic [`DATA_WIDTH`-1:0]): Input data to be rotated.
- **`i_dir`** (logic): Controls the rotation direction.

### Outputs:
- **`o_data`** (logic [`DATA_WIDTH`-1:0]): The rotated result.

```
    parameter DATA_WIDTH = 8
    input  logic [DATA_WIDTH-1:0] i_data,
    input  logic                  i_dir,
    output logic [DATA_WIDTH-1:0] o_data
```
"""

PARAM_EXPR_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_rotate8(dut):
    dut.i_data.value = 5
    dut.i_dir.value = 0
    await Timer(1, unit='ns')
    o = int(dut.o_data.value)
"""


def test_param_expression_width_resolves_to_complete():
    rec = _make_record("rotate8", PARAM_EXPR_PROMPT, PARAM_EXPR_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    # the `[DATA_WIDTH-1:0]` ports resolve to width 8 with a param-expr source.
    assert iface["i_data"]["width"] == 8
    assert iface["i_data"]["source"] == "param_expression_width"
    assert iface["o_data"]["width"] == 8
    # the `(logic)` scalar control is an explicit 1-bit (not absent, not a guess).
    assert iface["i_dir"]["width"] == 1
    assert iface["i_dir"]["source"] == "scalar_declared"
    # every prompt-declared port placed -> COMPLETE (no longer an EXTRACTION_GAP).
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# =========================================================================== #
# (4) POSITIVE — range_before_name LITERAL `[1:0] name` resolves + is placed
# =========================================================================== #
RANGE_BEFORE_PROMPT = """Design the module named `respmod`. The status port is declared
`[1:0] resp_o` (a two-bit field), and the strobe `valid_o` is 1 when ready.

### Inputs:
- req_i: request input.

### Outputs:
- resp_o: the status field, declared `[1:0] resp_o`.
- valid_o: 1 when the response is ready.
"""

RANGE_BEFORE_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_respmod(dut):
    dut.req_i.value = 1
    await Timer(1, unit='ns')
    r = int(dut.resp_o.value)
    v = int(dut.valid_o.value)
"""


def test_range_before_name_literal_resolves():
    rec = _make_record("respmod", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface["resp_o"]["width"] == 2
    assert iface["resp_o"]["source"] == "range_before_name"
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# =========================================================================== #
# (5) POSITIVE — param_override_width `[N*IN_WIDTH-1:0]` resolves to the product
# =========================================================================== #
PARAM_OVERRIDE_PROMPT = """Complete the module named `concat`.

## Parameters
- `NUM_INPUTS` (Default: 4): number of input lanes.
- `IN_WIDTH` (Default: 8): width of one lane.

### Inputs:
- data_in [NUM_INPUTS*IN_WIDTH-1:0]: packed input lanes.

### Outputs:
- data_out [IN_WIDTH-1:0]: one lane out.
"""

PARAM_OVERRIDE_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_concat(dut):
    dut.data_in.value = 1
    await Timer(1, unit='ns')
    o = int(dut.data_out.value)
"""


def test_param_override_width_resolves_product():
    rec = _make_record("concat", PARAM_OVERRIDE_PROMPT, PARAM_OVERRIDE_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface["data_in"]["width"] == 32   # 4 * 8
    assert iface["data_in"]["source"] == "param_override_width"
    assert iface["data_out"]["width"] == 8
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# =========================================================================== #
# (6) §4.05 NEGATIVE — a parameter expression with NO derivable default STAYS a
# gap width-wise (never a fabricated width); the port is still PLACED (width=None)
# and, since N/M are recognised config parameters, PARAMETERISED-COMPLETE.
# =========================================================================== #
UNSTATED_PARAM_PROMPT = """Design a parameterized priority encoder named `penc`.

    parameter N,
    parameter M,

### Inputs:
- in_vec [N-1:0]: the N-bit input vector (N is configurable).

### Outputs:
- idx [M-1:0]: the index of the highest set bit.
"""

UNSTATED_PARAM_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_penc(dut):
    N = int(dut.N.value)
    M = int(dut.M.value)
    dut.in_vec.value = 1
    await Timer(1, unit='ns')
    i = int(dut.idx.value)
"""


def test_param_expression_without_default_places_port_width_unknown():
    # N and M are declared parameters but the prompt states NO default for them,
    # so `[N-1:0]` / `[M-1:0]` cannot be RESOLVED to an int.
    pd = W.param_defaults(UNSTATED_PARAM_PROMPT)
    assert "N" not in pd and "M" not in pd, "no default should be invented for N/M"
    assert W.symbolic_width(UNSTATED_PARAM_PROMPT, "in_vec", pd) is None, \
        "§4.05: an unresolvable param expression must NOT yield a (fabricated) width"
    # ...but the param-expression DECLARATION is structurally present, so the width
    # is UNKNOWN, not a coincidental prose literal:
    assert W.has_param_expr_width(UNSTATED_PARAM_PROMPT, "in_vec") is True
    rec = _make_record("penc", UNSTATED_PARAM_PROMPT, UNSTATED_PARAM_TB)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    # the PORT is prompt-declared -> PLACED, but with width=None, never a
    # fabricated literal. (Step-2.7 §4.05: placing it width=None keeps the record
    # gate-able on presence+dir; dropping it emptied the interface.)
    assert "in_vec" in by, "a real prompt-declared port must be placed even when its width is symbolic"
    assert by["in_vec"]["width"] is None, "an unresolvable param width must NOT be fabricated"
    assert "N" not in by and "M" not in by, "config params are not ports"
    # N and M ARE recognised config parameters (declared `parameter N` in the
    # prompt), so the `[N-1:0]` / `[M-1:0]` widths are FULLY specified as
    # PARAMETERISED -> COMPLETE (the AI writes the param expression; the width is
    # not unknown, it is the parameter). A genuinely-unknown symbol would stay a gap.
    assert spec["completeness"] == "COMPLETE"


def test_genuinely_silent_width_stays_spec_absent():
    # a data port the prompt declares, no width form anywhere -> SPEC_ABSENT.
    prompt = ("Design the module named `passthru` that registers an opaque payload "
              "from input to output on each clock; reset clears the output.\n\n"
              "### Inputs:\n- clk: the clock.\n- rst: reset clears the output.\n"
              "- data_in: an opaque payload of unstated width.\n\n"
              "### Outputs:\n- data_out: the opaque payload output.\n")
    tb = ("import cocotb\nfrom cocotb.triggers import RisingEdge\n\n"
          "@cocotb.test()\nasync def test_passthru(dut):\n"
          "    dut.data_in.value = 7\n"
          "    dut.rst.value = 0\n"
          "    await RisingEdge(dut.clk)\n"
          "    o = int(dut.data_out.value)\n")
    rec = _make_record("passthru", prompt, tb)
    spec = CE.extract(rec)
    placed = {p["name"] for p in spec["interface"]}
    assert "data_in" not in placed and "data_out" not in placed
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT"
    assert any(g["type"] == "width_not_stated" for g in spec["gaps"])


# =========================================================================== #
# (7) 1-bit-CONVENTION width — a prompt-declared control/serial line with no
# stated bus range is 1-bit by the universal naming convention (prompt-only, no
# harness). The {0,1}-drive heuristic (_harness_one_bit) is a general engine
# helper: it correctly REFUSES to pin a width from a wide-bus randint upper bound.
# =========================================================================== #
def test_serial_line_is_one_bit_by_convention():
    prompt = ("Design the module named `serconv` that converts a serial line.\n\n"
              "### Inputs:\n- serial_in: carries the line bit.\n\n"
              "### Outputs:\n- serial_out: the converted bit.\n")
    tb = ("import cocotb, random\nfrom cocotb.triggers import Timer\n\n"
          "@cocotb.test()\nasync def test_serconv(dut):\n"
          "    dut.serial_in.value = random.randint(0, 1)\n"
          "    await Timer(1, unit='ns')\n"
          "    o = int(dut.serial_out.value)\n")
    rec = _make_record("serconv", prompt, tb)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface["serial_in"]["width"] == 1
    assert iface["serial_in"]["source"] == "one_bit_convention"


def test_harness_one_bit_helper_rejects_randint_upper_bound():
    # the general {0,1}-pin helper: randint(0, 40) for a data port does NOT prove a
    # 6-bit width (a wider bus driven with small values is legal). §4.05: it must
    # NOT credit a width. (extract() never feeds a real tb — this pins the helper.)
    tb = ("import cocotb, random\nfrom cocotb.triggers import Timer\n\n"
          "@cocotb.test()\nasync def test_acc(dut):\n"
          "    v = random.randint(0, 40)\n"
          "    dut.data_in.value = v\n"
          "    await Timer(1, unit='ns')\n"
          "    o = int(dut.data_out.value)\n")
    assert CE._harness_one_bit(tb, "data_in") is False
    # and a prompt that declares data ports with no width -> SPEC_ABSENT.
    prompt = ("Design the module named `acc` that accumulates data.\n\n"
              "### Inputs:\n- data_in: an opaque payload of unstated width.\n\n"
              "### Outputs:\n- data_out: the accumulated opaque payload.\n")
    rec = _make_record("acc", prompt, tb)
    spec = CE.extract(rec)
    placed = {p["name"] for p in spec["interface"]}
    assert "data_in" not in placed, "an unstated data-port width must not be fabricated"
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT"


# =========================================================================== #
# (8) PARAMETERIZED EMIT — the registry-emitted RTL is re-parameterized with a
# `#(parameter ...)` block and symbolic widths; verified FUNCTIONALLY by iverilog
# at the default width AND under a `#(.N(...))` harness override.
# =========================================================================== #
def test_parameterize_rtl_inserts_block_and_symbolic_widths():
    rtl = ("module foo (\n  input [7:0] data,\n  output [7:0] q\n);\n"
           "assign q = data;\nendmodule")
    out = B._parameterize_rtl(rtl, "foo", {"DATA_WIDTH": 8},
                              {"data": (8, "DATA_WIDTH-1:0"),
                               "q": (8, "DATA_WIDTH-1:0")})
    assert "#(" in out and "parameter DATA_WIDTH = 8" in out
    assert "[DATA_WIDTH-1:0] data" in out
    assert "[DATA_WIDTH-1:0] q" in out
    # §4.05: a same-width literal NOT adjacent to a symbolic port is untouched.
    assert "[7:0]" not in out


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog not installed")
def test_parameterized_emit_functionally_correct():
    """The re-parameterized module is functionally correct at the DEFAULT width
    and under a harness `#(.DATA_WIDTH(16))` override — a passthru identity."""
    rtl = ("module foo (\n  input [7:0] data,\n  output [7:0] q\n);\n"
           "assign q = data;\nendmodule")
    out = B._parameterize_rtl(rtl, "foo", {"DATA_WIDTH": 8},
                              {"data": (8, "DATA_WIDTH-1:0"),
                               "q": (8, "DATA_WIDTH-1:0")})
    tb = """`timescale 1ns/1ps
module tb;
  reg [7:0] d0; wire [7:0] q0;
  foo dut0(.data(d0), .q(q0));
  reg [15:0] d1; wire [15:0] q1;
  foo #(.DATA_WIDTH(16)) dut1(.data(d1), .q(q1));
  integer errs=0;
  initial begin
    d0=8'hA5; #1; if (q0!==8'hA5) errs=errs+1;
    d1=16'hBEEF; #1; if (q1!==16'hBEEF) errs=errs+1;
    if (errs==0) $display("FUNC_PASS");
    $finish;
  end
endmodule
"""
    out_text = _iverilog_run(out, tb)
    assert "FUNC_PASS" in out_text, out_text


# =========================================================================== #
# (9) CHIP-AGNOSTIC — rename module + every identifier; same widths + verdict.
# =========================================================================== #
def test_chip_agnostic_rename_invariant():
    rec_a = _make_record("rotate8", PARAM_EXPR_PROMPT, PARAM_EXPR_TB)
    spec_a = CE.extract(rec_a)

    ren = {"rotate8": "zzz", "DATA_WIDTH": "WW", "i_data": "p_in",
           "i_dir": "p_dir", "o_data": "p_out"}
    prompt_b, tb_b = PARAM_EXPR_PROMPT, PARAM_EXPR_TB
    for src in sorted(ren, key=len, reverse=True):
        prompt_b = re.sub(rf"\b{re.escape(src)}\b", ren[src], prompt_b)
        tb_b = re.sub(rf"\b{re.escape(src)}\b", ren[src], tb_b)
    spec_b = CE.extract(_make_record("zzz", prompt_b, tb_b))

    assert spec_a["completeness"] == spec_b["completeness"] == "COMPLETE"
    wa = sorted(p["width"] for p in spec_a["interface"])
    wb = sorted(p["width"] for p in spec_b["interface"])
    assert wa == wb, "rename changed the resolved widths — not chip-agnostic"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""test_cvdp_complete_extract.py — the UNIFIED CVDP complete-extraction layer.

cvdp_complete_extract.extract(record) composes the shipped cvdp_atomic_bridge
interface helpers + the v1.1.82 structural extractors into ONE complete spec
dict, and assigns a per-record COMPLETENESS verdict:
  COMPLETE                  — every harness-checked port placed + stated
                              structures captured;
  INCOMPLETE_EXTRACTION_GAP — a fact IS in the prompt/harness but we missed it
                              (ACTIONABLE; carries a recurring gap TYPE);
  INCOMPLETE_SPEC_ABSENT    — the fact is genuinely NOT in the prompt (the AI's
                              irreducible §3.9 domain).

POSITIVE: a real-shaped record extracts a complete spec JSON with the expected
fields (module_name, interface with resolved widths, structures, reset, ...) and
is classified COMPLETE.

CLASSIFIER: the EXTRACTION_GAP vs SPEC_ABSENT split is correct on hand-checked
records — a port whose width is stated as a PARAMETER EXPRESSION (`[N-1:0]`) is an
EXTRACTION_GAP; a port the cocotb drives but whose width the prompt never states
is SPEC_ABSENT.

§4.05: a field is emitted ONLY when structurally present — the interface comes
from the cocotb dut.<sig> set + prose widths, never invented; a data port with no
stated width is recorded as a GAP, never forced to a guessed width.

CHIP-AGNOSTIC: renaming every identifier in a prompt yields the SAME verdict and
the SAME number of interface ports / gaps.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import cvdp_complete_extract as CE  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped record builder (faithful to CVDP v1.1.0: input.prompt +
# input.context{} + output.context{<rtl>:""} (EMPTY skeleton) + harness.files
# with a .env carrying TOPLEVEL + a cocotb test_*.py). output.context is never
# read for logic.
# --------------------------------------------------------------------------- #
def _make_record(top, prompt, cocotb_test, rid=None, rtl_path=None):
    rtl_path = rtl_path or f"rtl/{top}.sv"
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


# --------------------------------------------------------------------------- #
# (1) POSITIVE — a fully-specified combinational adder: prose states each port's
# width with an explicit `[hi:lo]` range; the cocotb test drives a/b/carry_in and
# reads sum/carry_out. Every harness-checked port is placed -> COMPLETE.
# --------------------------------------------------------------------------- #
ADDER_PROMPT = """Design a combinational module `adder8` that adds two operands.

## Inputs and Outputs

| Name       | Width   | Description                       |
|------------|---------|-----------------------------------|
| `a [7:0]`  | 8 bits  | First operand.                    |
| `b [7:0]`  | 8 bits  | Second operand.                   |
| `carry_in` | 1 bit   | Carry input.                      |
| `sum [7:0]`| 8 bits  | The 8-bit sum.                    |
| `carry_out`| 1 bit   | Carry output.                     |

The module performs `sum = a + b + carry_in` with `carry_out` the overflow bit.
"""

ADDER_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_adder8(dut):
    dut.a.value = 5
    dut.b.value = 3
    dut.carry_in.value = 0
    await Timer(10, unit='ns')
    s = int(dut.sum.value)
    c = int(dut.carry_out.value)
    assert s == 8
"""


def test_positive_complete_spec_has_expected_fields():
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    spec = CE.extract(rec)
    # the spec dict carries every promised structural key
    for key in ("id", "module_name", "interface", "operation_family", "params",
                "structures", "reset", "timing", "byte_order", "completeness",
                "gaps", "harness"):
        assert key in spec, f"missing top-level key {key}"
    assert spec["module_name"] == "adder8"
    # interface placed every cocotb-driven port with a RESOLVED width
    names = {p["name"]: p for p in spec["interface"]}
    assert {"a", "b", "carry_in", "sum", "carry_out"} <= set(names)
    assert names["a"]["width"] == 8 and names["a"]["dir"] == "input"
    assert names["sum"]["width"] == 8 and names["sum"]["dir"] == "output"
    assert names["carry_in"]["width"] == 1
    assert names["carry_out"]["width"] == 1
    # arithmetic family recognised from the operation vocabulary
    assert spec["operation_family"]["guess"] == "arithmetic"
    # nothing missed, nothing absent -> COMPLETE
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]
    assert spec["gaps"] == []


# --------------------------------------------------------------------------- #
# (2) CLASSIFIER — EXTRACTION_GAP: the width IS in the prompt but as a PARAMETER
# EXPRESSION (`[N-1:0]`) our literal reader does not resolve. The cocotb test
# reads N via int(dut.N.value) (so N is a parameter, NOT a port). The driven data
# port `in_vec` has a parameter-expression width -> EXTRACTION_GAP, type
# param_expression_width. This is the dominant actionable bucket.
# --------------------------------------------------------------------------- #
PARAM_WIDTH_PROMPT = """Design a parameterized priority encoder `penc`.

## Inputs and Outputs
- **Inputs**: `in_vec [N-1:0]` - the `N`-bit input vector to encode.
- **Outputs**: `idx [M-1:0]` - the index of the highest set bit.
- `valid` - 1 when any input bit is set.
"""

PARAM_WIDTH_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_penc(dut):
    N = int(dut.N.value)
    M = int(dut.M.value)
    dut.in_vec.value = 1
    await Timer(1, unit='ns')
    i = int(dut.idx.value)
    v = int(dut.valid.value)
"""


def test_classifier_param_expression_width_is_extraction_gap():
    rec = _make_record("penc", PARAM_WIDTH_PROMPT, PARAM_WIDTH_TB)
    spec = CE.extract(rec)
    # N and M are config parameters (read via int(dut.X.value)), NOT ports
    assert "N" in spec["harness"]["params"]
    assert "M" in spec["harness"]["params"]
    iface_names = {p["name"] for p in spec["interface"]}
    assert "N" not in iface_names and "M" not in iface_names, \
        "single-letter int(dut.X.value) parameter must not become a port"
    # valid is a 1-bit control by convention
    assert any(p["name"] == "valid" and p["width"] == 1 for p in spec["interface"])
    # the data ports in_vec / idx have a param-expression width -> EXTRACTION_GAP
    assert spec["completeness"] == "INCOMPLETE_EXTRACTION_GAP"
    gap_types = {g["type"] for g in spec["gaps"]
                 if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"}
    assert "param_expression_width" in gap_types
    # the evidence is a REAL prompt line that carries the param range
    for g in spec["gaps"]:
        if g["type"] == "param_expression_width":
            assert "[" in g["evidence"] and "]" in g["evidence"]


# --------------------------------------------------------------------------- #
# (3) CLASSIFIER — SPEC_ABSENT: the cocotb test drives a DATA port the prompt
# never states a width for (no `[hi:lo]`, no `N-bit`, no table column, no param
# expression). That width is the AI's irreducible domain -> SPEC_ABSENT.
# --------------------------------------------------------------------------- #
ABSENT_PROMPT = """Design a module `passthru` that registers its data input to its
data output on each clock. The reset clears the output. The data signals carry an
opaque payload between two endpoints.
"""

ABSENT_TB = """import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def test_passthru(dut):
    dut.data_in.value = 7
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    o = int(dut.data_out.value)
"""


def test_classifier_width_not_stated_is_spec_absent():
    rec = _make_record("passthru", ABSENT_PROMPT, ABSENT_TB)
    spec = CE.extract(rec)
    # rst is driven (dut.rst.value=...) so it IS a cocotb signal; it is placed
    # 1-bit by the reset convention. The DATA ports are width-unresolved -> gaps.
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface.get("rst", {}).get("width") == 1
    assert iface["rst"]["source"] == "clk_rst_convention"
    assert "data_in" not in iface and "data_out" not in iface, \
        "a data port with no stated width must NOT be forced to a guessed width"
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT", spec["completeness_reason"]
    assert all(g["kind"] == "INCOMPLETE_SPEC_ABSENT" for g in spec["gaps"])
    assert any(g["type"] == "width_not_stated" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (4) §4.05 — a field is emitted ONLY when structurally present. The interface is
# never fabricated: a port the cocotb does not reference is never invented, and a
# data port with no stated width is a GAP, not a phantom width.
# --------------------------------------------------------------------------- #
def test_no_fabrication_only_cocotb_signals_become_ports():
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    spec = CE.extract(rec)
    cocotb_sigs = set(spec["harness"]["cocotb_inputs"]) | set(spec["harness"]["cocotb_outputs"])
    for p in spec["interface"]:
        assert p["name"] in cocotb_sigs, \
            f"port {p['name']} is not referenced by the cocotb harness — fabricated"
        # every placed port carries a structural SOURCE tag (no source == guess)
        assert p["source"] in (
            "skeleton_header", "explicit_range", "prose_width", "test_case_table",
            "clk_rst_convention", "one_bit_convention"), p["source"]


def test_no_structures_fabricated_from_bare_prose():
    # a prompt with NO register map / enum / fsm / worked example yields EMPTY
    # structure lists — never invented.
    rec = _make_record("passthru", ABSENT_PROMPT, ABSENT_TB)
    spec = CE.extract(rec)
    s = spec["structures"]
    assert s["register_map"] == []
    assert s["enum_modes"] == []
    assert s["fsm"] == {"states": [], "transitions": []}
    assert s["worked_examples"] == []


# --------------------------------------------------------------------------- #
# (5) CHIP-AGNOSTIC — renaming the design (module + every port) yields the SAME
# verdict and the SAME interface size / gap count. The layer keys on STRUCTURE,
# never on a design name.
# --------------------------------------------------------------------------- #
def test_chip_agnostic_rename_invariant():
    rec_a = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    spec_a = CE.extract(rec_a)

    # rename module + ports consistently across prompt + cocotb + .env
    ren = {
        "adder8": "zzz_top", "a": "p", "b": "q", "carry_in": "ck_in",
        "sum": "res", "carry_out": "ck_out",
    }
    prompt_b = ADDER_PROMPT
    tb_b = ADDER_TB
    # whole-word replace, longest-first to avoid partial clobber
    import re
    for src in sorted(ren, key=len, reverse=True):
        dst = ren[src]
        prompt_b = re.sub(rf"\b{re.escape(src)}\b", dst, prompt_b)
        tb_b = re.sub(rf"\b{re.escape(src)}\b", dst, tb_b)
    rec_b = _make_record("zzz_top", prompt_b, tb_b)
    spec_b = CE.extract(rec_b)

    assert spec_a["completeness"] == spec_b["completeness"] == "COMPLETE"
    assert len(spec_a["interface"]) == len(spec_b["interface"])
    assert len(spec_a["gaps"]) == len(spec_b["gaps"]) == 0
    # the widths transfer with the rename
    wa = {p["name"]: p["width"] for p in spec_a["interface"]}
    wb = {p["name"]: p["width"] for p in spec_b["interface"]}
    assert wa["a"] == wb["p"] == 8
    assert wa["sum"] == wb["res"] == 8


# --------------------------------------------------------------------------- #
# (6) range-before-name RESOLUTION: a `[1:0] name` declaration (range PRECEDES the
# identifier) is now RESOLVED to its literal width and PLACED (source
# range_before_name) — it is no longer a gap. The record stays SPEC_ABSENT here
# ONLY because a DIFFERENT port (`data_o`) is explicitly width-unspecified.
# --------------------------------------------------------------------------- #
RANGE_BEFORE_PROMPT = """Design `respmod`. The response port is declared as
**`[1:0] resp_o`**: a two-bit field indicating success or error, and `data_o`
carries the response payload (width unspecified). The `valid_o` strobe is 1 when
the response is ready.
"""

RANGE_BEFORE_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_respmod(dut):
    await Timer(1, unit='ns')
    r = int(dut.resp_o.value)
    d = int(dut.data_o.value)
    v = int(dut.valid_o.value)
    dut.req_i.value = 1
"""


def test_range_before_name_now_resolves_and_is_placed():
    rec = _make_record("respmod", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB)
    spec = CE.extract(rec)
    # resp_o's `[1:0]` range (declared before the name) is now resolved to width 2
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface["resp_o"]["width"] == 2
    assert iface["resp_o"]["source"] == "range_before_name"
    # the ONLY residual gap is the genuinely-width-unspecified data_o (SPEC_ABSENT),
    # NOT a range_before_name gap (we no longer miss that form).
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT", spec["completeness_reason"]
    gap_ports = {g["detail"] for g in spec["gaps"]}
    assert any("data_o" in d for d in gap_ports)
    assert all(g["type"] != "range_before_name" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (7) STRUCTURE COMPOSITION — an enum-mode prompt surfaces enum_modes in the spec
# (the layer really does compose the v1.1.82 extractors, not just the interface).
# --------------------------------------------------------------------------- #
ENUM_PROMPT = """Design `opsel`, a 3-bit operation selector `op [2:0]` driving a
`result [7:0]` output from operand `a [7:0]`.

| op     | Operation  |
|--------|------------|
| 3'b000 | pass a     |
| 3'b001 | invert a   |
| 3'b010 | shift left |
| 3'b011 | shift right|
| 3'b100 | zero       |

For any other value of op, the result is held at zero.
"""

ENUM_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_opsel(dut):
    dut.op.value = 0
    dut.a.value = 5
    await Timer(1, unit='ns')
    r = int(dut.result.value)
"""


def test_structures_compose_enum_extractor():
    rec = _make_record("opsel", ENUM_PROMPT, ENUM_TB)
    spec = CE.extract(rec)
    enum = spec["structures"]["enum_modes"]
    # the 5-entry op table is recovered (the enumset extractor requires >=3)
    assert len(enum) >= 3, "enum table not composed into the spec"
    codes = {tok for it in enum for tok in it.get("coverage_tokens", [])}
    assert "3'b000" in codes and "3'b100" in codes
    # interface fully resolved (op/a/result all have widths) -> COMPLETE
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# =========================================================================== #
# EXTRACTION_GAP CLOSURE (v1.1.92) — the remaining in-prompt facts the layer
# missed BEYOND widths. Each test closes one recurring gap-TYPE against a real
# structural source, and the §4.05 pair proves a GENUINELY-absent fact STAYS a gap.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# (8) COCOTB-IO RECOVERY — an output the harness reads ONLY through an
# assert-comparison (`dut.X.value == k`), an f-string (`{dut.X.value}`), a
# bracket access (`dut['in'].value`), or an indexed read leaves the bridge's
# `_cocotb_io` empty. The recovery reader binds these so the interface is no
# longer empty. The bracket form is REQUIRED for a Python-keyword port (`in`).
# --------------------------------------------------------------------------- #
IO_RECOVER_PROMPT = """Design `encoder8` — an 8-to-3 priority encoder.
The 8-bit input `in [7:0]` carries the request bits; the 3-bit output `out [2:0]`
is the index of the highest set bit.
"""

IO_RECOVER_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_encoder8(dut):
    dut['in'].value = 0b00010000          # bracket-driven (in is a py keyword)
    await Timer(1, unit='ns')
    dut._log.info(f"out = {dut.out.value}")   # f-string READ (+ a non-port attr)
    assert dut.out.value == 4              # assert-comparison READ
"""


def test_cocotb_io_recovery_assert_fstring_bracket_forms():
    rec = _make_record("encoder8", IO_RECOVER_PROMPT, IO_RECOVER_TB)
    spec = CE.extract(rec)
    names = {p["name"]: p for p in spec["interface"]}
    # the bracket-driven `in` is an INPUT; the assert/f-string-read `out` an OUTPUT
    assert "in" in names and names["in"]["dir"] == "input"
    assert "out" in names and names["out"]["dir"] == "output"
    assert names["in"]["width"] == 8 and names["out"]["width"] == 3
    # the cocotb framework attribute `_log` is NEVER promoted to a port
    assert "_log" not in names
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (9) §4.05 — a recovered `dut.reg.value == k` READ that the prompt NEVER cites as
# an interface signal is an INTERNAL white-box register, NOT a port. It must NOT be
# promoted to the interface (no fabricated port).
# --------------------------------------------------------------------------- #
WHITEBOX_PROMPT = """Design `divider` that produces a divided clock `clk_out` from
the input clock. Reset `rst_n` clears the output.
"""

WHITEBOX_TB = """import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def test_divider(dut):
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    # white-box probe of an INTERNAL counter the prompt never names as a signal:
    assert dut.internal_div_counter.value == 0
    assert dut.clk_out.value == 0
"""


def test_internal_register_probe_is_not_promoted_to_a_port():
    rec = _make_record("divider", WHITEBOX_PROMPT, WHITEBOX_TB)
    spec = CE.extract(rec)
    names = {p["name"] for p in spec["interface"]}
    # the internal counter (no prompt mention, no width, no convention) is dropped
    assert "internal_div_counter" not in names, \
        "a white-box internal register must NOT become an interface port (§4.05)"
    # clk_out IS a corroborated port — a clock output is 1-bit by convention
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface.get("clk_out", {}).get("width") == 1
    assert iface["clk_out"]["source"] == "clk_rst_convention"


# --------------------------------------------------------------------------- #
# (10) GROUPED-BULLET WIDTH — a width stated ONCE in a `(N-bit each)` group header
# applies to the bulleted port names beneath it. The members inherit the width.
# --------------------------------------------------------------------------- #
GROUP_WIDTH_PROMPT = """Design `ctrl` from a 6-bit feedback `i_fb [5:0]`.

**Heating Control (1-bit each)**
- `o_heat_hi`
- `o_heat_lo`

**FSM Output State (3-bit)**
- `o_state [2:0]`
"""

GROUP_WIDTH_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_ctrl(dut):
    dut.i_fb.value = 1
    await Timer(1, unit='ns')
    assert dut.o_heat_hi.value == 0
    assert dut.o_heat_lo.value == 0
    assert dut.o_state.value == 0
"""


def test_grouped_bullet_width_binds_header_to_members():
    rec = _make_record("ctrl", GROUP_WIDTH_PROMPT, GROUP_WIDTH_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface["o_heat_hi"]["width"] == 1
    assert iface["o_heat_hi"]["source"] == "grouped_bullet_width"
    assert iface["o_heat_lo"]["width"] == 1
    assert iface["o_state"]["width"] == 3       # 3-bit from the explicit [2:0]
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (11) PROSE / PAREN PARAMETER DEFAULTS — a width param stated as
# "(Default 4, must be > 0)" / "Default value 4" / "`P = 8` (default ...)" /
# "default is **8 bits**" was missed (the old readers required `)` right after the
# int, "is/of" connectors, the `parameter` keyword, or no markdown decoration). The
# port's `[P-1:0]` width now resolves to the stated default.
# --------------------------------------------------------------------------- #
PROSE_DEFAULT_PROMPT = """Design `widthed`.

## Parameters
- `WID` (Default 4, must be greater than 0): bit-width of the data.
- `GPIO_WIDTH = 8` (default, configurable): number of pins.
- `DEPTHP`: depth of the buffer. Default value 16.
- `p_data_width`: configurable data width, default is **8 bits**.

## Ports
- `data [WID-1:0]`: the data word.
- `gpio [GPIO_WIDTH-1:0]`: the gpio pins.
- `bus` (`p_data_width` bit): the bus payload.
"""

PROSE_DEFAULT_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_widthed(dut):
    dut.data.value = 3
    dut.gpio.value = 1
    await Timer(1, unit='ns')
    assert dut.bus.value == 0
"""


def test_prose_and_paren_parameter_defaults_resolve_widths():
    rec = _make_record("widthed", PROSE_DEFAULT_PROMPT, PROSE_DEFAULT_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    # "(Default 4, must be > 0)" -> WID=4 -> data is 4-bit
    assert iface["data"]["width"] == 4
    # "`GPIO_WIDTH = 8` (default ...)" -> GPIO_WIDTH=8 -> gpio is 8-bit
    assert iface["gpio"]["width"] == 8
    # "(`p_data_width` bit)" + "default is **8 bits**" -> bus is 8-bit
    assert iface["bus"]["width"] == 8
    # every resolved width is anchored to a parameter expression, not invented
    for n in ("data", "gpio", "bus"):
        assert iface[n]["source"] == "param_expression_width"
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (12) DERIVED-localparam + spec-notation-`x` multiply + backtick-in-bracket — a
# port sized by a derived `localparam` (the `localparam` keyword was silently
# dropped), by a spec `A x B x C` multiply, or by a backtick-decorated bracket
# expression now resolves to the computed default.
# --------------------------------------------------------------------------- #
DERIVED_PROMPT = """Design `crossbar`.

```
parameter DATA_W = 8,
localparam NPORTS = 4,
localparam DATA_W_IN = (DATA_W + $clog2(NPORTS))
```

## Parameters
- `RW` (default = 16): row width.
- `NS` (default = 4): element count.

## Ports
- `in0 [DATA_W_IN-1:0]`: input data (sized by the DERIVED localparam).
- `flat [ (RW x NS) - 1 : 0]`: a flattened vector using a spec `x` multiply.
- `o_sum [(`RW` + $clog2(`NS`)) - 1 : 0]`: backtick-decorated bracket expression.
"""

DERIVED_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_crossbar(dut):
    dut.in0.value = 0
    dut.flat.value = 0
    await Timer(1, unit='ns')
    assert dut.o_sum.value == 0
"""


def test_derived_localparam_x_multiply_and_backtick_bracket_resolve():
    rec = _make_record("crossbar", DERIVED_PROMPT, DERIVED_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    # DERIVED localparam: DATA_W_IN = 8 + clog2(4) = 10 -> in0 is 10-bit
    assert iface["in0"]["width"] == 10
    # spec `x` multiply: RW x NS = 16 x 4 = 64 -> flat is 64-bit
    assert iface["flat"]["width"] == 64
    # backtick-in-bracket: (RW + clog2(NS)) = 16 + 2 = 18 -> o_sum is 18-bit
    assert iface["o_sum"]["width"] == 18
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (13) §4.05 ADVERSARIAL — a parameter-expression width whose parameter has NO
# stated default STAYS a gap (the width form is present but unresolvable; never a
# fabricated default). The record is EXTRACTION_GAP, not silently COMPLETE.
# --------------------------------------------------------------------------- #
ABSENT_DEFAULT_PROMPT = """Design `gpio2` (a modification of an earlier gpio).
- `gpio [GPIO_WIDTH-1:0]`: bidirectional GPIO pins.

The GPIO_WIDTH parameter is unchanged from the base design (no default restated).
"""

ABSENT_DEFAULT_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_gpio2(dut):
    dut.gpio.value = 1
    await Timer(1, unit='ns')
    assert dut.gpio.value == 1
"""


def test_param_expression_with_no_stated_default_stays_a_gap():
    rec = _make_record("gpio2", ABSENT_DEFAULT_PROMPT, ABSENT_DEFAULT_TB)
    spec = CE.extract(rec)
    # GPIO_WIDTH has no derivable default here -> gpio is NOT placed with a width
    iface = {p["name"] for p in spec["interface"]}
    assert "gpio" not in iface, \
        "a param-expression width with no stated default must NOT be fabricated"
    assert spec["completeness"] == "INCOMPLETE_EXTRACTION_GAP"
    gtypes = {g["type"] for g in spec["gaps"]
              if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"}
    assert "param_expression_width" in gtypes


# --------------------------------------------------------------------------- #
# (14) §4.05 ADVERSARIAL — a recovered output port whose width the prompt genuinely
# never states (only example VALUES, no `[hi:lo]` / `N-bit` / param) STAYS a
# SPEC_ABSENT gap. The port is surfaced (real harness signal) but its width is the
# AI's irreducible domain — never a guessed width.
# --------------------------------------------------------------------------- #
ABSENT_WIDTH_PROMPT = """Design `ascii_gen` that converts a character to its ASCII
code. The output `ascii_out` carries the code. Example outputs: 65, 49, 98.
"""

ABSENT_WIDTH_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_ascii_gen(dut):
    dut.char_in.value = ord('A')
    await Timer(1, unit='ns')
    assert dut.ascii_out.value == 65
"""


def test_recovered_output_with_unstated_width_stays_spec_absent():
    rec = _make_record("ascii_gen", ABSENT_WIDTH_PROMPT, ABSENT_WIDTH_TB)
    spec = CE.extract(rec)
    # ascii_out is a real harness-read output, surfaced by the recovery, BUT its
    # width is never stated (only example values) -> a SPEC_ABSENT gap, not a guess.
    assert "ascii_out" in (set(spec["harness"]["cocotb_outputs"]))
    iface = {p["name"] for p in spec["interface"]}
    assert "ascii_out" not in iface, "an unstated width must not be fabricated"
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT", spec["completeness_reason"]
    assert any(g["type"] == "width_not_stated" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (15) CHIP-AGNOSTIC — the new gap-closures key on STRUCTURE, never a design name.
# Renaming the module + every identifier in the grouped-bullet-width record yields
# the SAME widths and the SAME COMPLETE verdict.
# --------------------------------------------------------------------------- #
def test_new_closures_are_chip_agnostic():
    rec_a = _make_record("ctrl", GROUP_WIDTH_PROMPT, GROUP_WIDTH_TB)
    spec_a = CE.extract(rec_a)
    import re as _re
    ren = {"ctrl": "qqq", "i_fb": "fb_x", "o_heat_hi": "z_hi",
           "o_heat_lo": "z_lo", "o_state": "z_st"}
    prompt_b, tb_b = GROUP_WIDTH_PROMPT, GROUP_WIDTH_TB
    for src in sorted(ren, key=len, reverse=True):
        prompt_b = _re.sub(rf"\b{_re.escape(src)}\b", ren[src], prompt_b)
        tb_b = _re.sub(rf"\b{_re.escape(src)}\b", ren[src], tb_b)
    spec_b = CE.extract(_make_record("qqq", prompt_b, tb_b))
    assert spec_a["completeness"] == spec_b["completeness"] == "COMPLETE"
    wa = {p["name"]: p["width"] for p in spec_a["interface"]}
    wb = {p["name"]: p["width"] for p in spec_b["interface"]}
    assert wa["o_heat_hi"] == wb["z_hi"] == 1
    assert wa["o_state"] == wb["z_st"] == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

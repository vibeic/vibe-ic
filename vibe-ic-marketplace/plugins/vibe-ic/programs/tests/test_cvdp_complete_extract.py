"""test_cvdp_complete_extract.py — the UNIFIED CVDP complete-extraction layer.

cvdp_complete_extract.extract(record) composes the shipped cvdp_atomic_bridge
interface helpers + the v1.1.82 structural extractors into ONE complete spec
dict, and assigns a per-record COMPLETENESS verdict:
  COMPLETE                  — every PROMPT/CONTEXT-declared port placed + stated
                              structures captured;
  INCOMPLETE_EXTRACTION_GAP — a fact IS in the prompt/context but we missed it
                              (ACTIONABLE; carries a recurring gap TYPE);
  INCOMPLETE_SPEC_ABSENT    — the fact is genuinely NOT in the prompt (the AI's
                              irreducible §3.9 domain).

§4.05 CVDP COMPLIANCE (the load-bearing rule): the model sees ONLY
`input.prompt` + `input.context`. The interface is recovered from the PROMPT's
declared Input/Output ports (+ the input.context module header), NEVER from the
hidden cocotb `dut.<sig>` test / `.env` TOPLEVEL / golden `output`. The
EXTRACTION_GAP-vs-SPEC_ABSENT split is a pure PROMPT-COMPLETENESS assessment: is
every port the PROMPT itself declares fully width-resolved from prompt+context?

POSITIVE: a real-shaped record extracts a complete spec JSON with the expected
fields (module_name, interface with resolved widths, structures, reset, ...) and
is classified COMPLETE.

CLASSIFIER: the EXTRACTION_GAP vs SPEC_ABSENT split is correct on hand-checked
records — a port whose width is stated as a PARAMETER EXPRESSION (`[N-1:0]`) with
no derivable default is an EXTRACTION_GAP; a port the prompt declares but whose
width the prompt never states is SPEC_ABSENT.

§4.05: a field is emitted ONLY when structurally present — the interface comes
from the prompt/context, never invented; a data port with no stated width is
recorded as a GAP, never forced to a guessed width.

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
# input.context{} + output.context{<rtl>:""} + a DECOY harness with a .env
# TOPLEVEL + a cocotb test_*.py). The harness + output are OFF-LIMITS oracle and
# are NEVER read by extract() — they are present only to prove that presence.
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
# (1) POSITIVE — a fully-specified combinational adder: the PROMPT declares each
# port (### Inputs/Outputs) with an explicit `[hi:lo]` range on the data ports.
# Every prompt-declared port is placed with a resolved width -> COMPLETE.
# --------------------------------------------------------------------------- #
ADDER_PROMPT = """Design a combinational module named `adder8` that adds two operands.

### Inputs:
- a [7:0]: First operand.
- b [7:0]: Second operand.
- carry_in: a 1-bit carry input.

### Outputs:
- sum [7:0]: The 8-bit sum.
- carry_out: a 1-bit carry output.

The module performs `sum = a + b + carry_in` with `carry_out` the overflow bit.
"""

# A DECOY cocotb test — extract() must IGNORE it (it is the OFF-LIMITS harness).
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
    # the spec dict carries every promised structural key (harness block is GONE —
    # the cocotb signal sets are OFF-LIMITS oracle and are never re-attached).
    for key in ("id", "module_name", "interface", "operation_family", "params",
                "structures", "reset", "timing", "byte_order", "completeness",
                "gaps"):
        assert key in spec, f"missing top-level key {key}"
    assert "harness" not in spec, "the cocotb harness block must NOT be re-attached"
    assert spec["module_name"] == "adder8"
    # interface placed every PROMPT-declared port with a RESOLVED width
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
# (2) CLASSIFIER — a width IS in the prompt as a PARAMETER EXPRESSION (`[N-1:0]`)
# over PROMPT-declared config parameters (`parameter N`, `parameter M`). Those
# ports are placed with width=None and the width is FULLY specified as
# PARAMETERISED (the AI writes `[N-1:0]`, correct under every override) -> the
# record is COMPLETE, NOT a gap. A single-token config parameter is never a port.
# --------------------------------------------------------------------------- #
PARAM_WIDTH_PROMPT = """Design a parameterized priority encoder named `penc`.

    parameter N,
    parameter M,

### Inputs:
- in_vec [N-1:0]: the N-bit input vector to encode.

### Outputs:
- idx [M-1:0]: the index of the highest set bit.
- valid: 1 when any input bit is set.
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


def test_param_expression_over_config_params_is_parameterized_complete():
    rec = _make_record("penc", PARAM_WIDTH_PROMPT, PARAM_WIDTH_TB)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    # N and M are PROMPT-declared config parameters, NOT ports
    assert "N" not in by and "M" not in by, \
        "a declared `parameter N` must not become a port"
    # valid is a 1-bit control by convention
    assert by.get("valid", {}).get("width") == 1
    # in_vec / idx have a param-expression width over ONLY config params (N, M) ->
    # the width is FULLY specified as PARAMETERISED (the AI writes `[N-1:0]`,
    # correct under every override): the ports are PLACED with width=None and the
    # spec is COMPLETE — NOT an extraction gap (the width is not unknown, it is
    # parameterised). No fabricated literal.
    assert by["in_vec"]["width"] is None
    assert by["in_vec"]["source"] == "param_expression_width"
    assert by["idx"]["width"] is None
    assert spec["completeness"] == "COMPLETE"


def test_param_expression_over_unknown_symbol_stays_a_gap():
    # the SAME shape but the width parameter is NOT a recognised config param
    # (never declared) -> we genuinely do not know the width, so it stays an honest
    # EXTRACTION_GAP (NOT falsely COMPLETE, NOT fabricated).
    prompt = "Design the module named `m`.\n\n### Outputs:\n- dout [MYSTERY-1:0]: the output bus.\n"
    tb = ("import cocotb\n@cocotb.test()\nasync def test_m(dut):\n"
          "    _ = dut.dout.value\n")
    spec = CE.extract(_make_record("m", prompt, tb))
    by = {p["name"]: p for p in spec["interface"]}
    assert by["dout"]["width"] is None, "unknown-symbol width is never fabricated"
    assert spec["completeness"] == "INCOMPLETE_EXTRACTION_GAP"
    assert any(g["type"] == "param_expression_width" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (3) CLASSIFIER — SPEC_ABSENT: the prompt DECLARES a DATA port but states no
# width for it (no `[hi:lo]`, no `N-bit`, no table column, no param expression).
# That width is the AI's irreducible domain -> SPEC_ABSENT.
# --------------------------------------------------------------------------- #
ABSENT_PROMPT = """Design a module named `passthru` that registers its data input to its
data output on each clock. The reset clears the output.

### Inputs:
- clk: the clock.
- rst: reset clears the output.
- data_in: an opaque payload input of unstated width.

### Outputs:
- data_out: the opaque payload output.
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
    # rst is a declared control -> placed 1-bit by the reset convention. The DATA
    # ports are width-unresolved -> gaps (never forced to a guessed width).
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface.get("rst", {}).get("width") == 1
    assert iface["rst"]["source"] == "clk_rst_convention"
    assert "data_in" not in iface and "data_out" not in iface, \
        "a data port with no stated width must NOT be forced to a guessed width"
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT", spec["completeness_reason"]
    assert all(g["kind"] == "INCOMPLETE_SPEC_ABSENT" for g in spec["gaps"])
    assert any(g["type"] == "width_not_stated" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (4) §4.05 — a field is emitted ONLY when structurally present. Every placed
# port is a PROMPT/CONTEXT-declared signal (echoed in interface_source), never a
# harness peek; a data port with no stated width is a GAP, not a phantom width.
# --------------------------------------------------------------------------- #
def test_no_fabrication_only_prompt_signals_become_ports():
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    spec = CE.extract(rec)
    # the enforced interface comes ONLY from prompt+context (interface_source echoes
    # exactly the names the adapter supplied to the general engine).
    src = spec["interface_source"]
    declared = set(src["inputs"]) | set(src["outputs"])
    for p in spec["interface"]:
        assert p["name"] in declared, \
            f"port {p['name']} is not a prompt/context-declared signal — fabricated"
        # every placed port carries a structural SOURCE tag (no source == guess)
        assert p["source"] in (
            "skeleton_header", "context_header", "explicit_range", "prose_width",
            "test_case_table", "range_before_name", "param_expression_width",
            "param_override_width", "grouped_bullet_width", "scalar_declared",
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
# identifier) is RESOLVED to its literal width and PLACED (source
# range_before_name) — it is no longer a gap. The record stays SPEC_ABSENT here
# ONLY because a DIFFERENT port (`data_o`) is explicitly width-unspecified.
# --------------------------------------------------------------------------- #
RANGE_BEFORE_PROMPT = """Design the module named `respmod`. The response port is declared
`[1:0] resp_o`: a two-bit field indicating success or error.

### Inputs:
- req_i: request input.

### Outputs:
- resp_o: the status field, declared `[1:0] resp_o`.
- data_o: carries the response payload (width unspecified).
- valid_o: 1 when the response is ready.
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
ENUM_PROMPT = """Design the module named `opsel`, a 3-bit operation selector.

### Inputs:
- op [2:0]: operation select.
- a [7:0]: operand.

### Outputs:
- result [7:0]: the result.

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
# EXTRACTION_GAP CLOSURE (v1.1.92) — the in-prompt facts the layer must recover
# BEYOND a plain literal width. Each test closes one recurring gap-TYPE against a
# real PROMPT structural source, and the §4.05 pair proves a GENUINELY-absent
# fact STAYS a gap.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# (8) PROMPT-DECLARED INTERFACE — a prompt with an explicit ### Inputs/Outputs
# port block yields the full interface with resolved widths. (The `in`/`out`
# names are Python keywords in a cocotb TB — irrelevant now that the interface
# comes from the PROMPT, not the harness.)
# --------------------------------------------------------------------------- #
IO_RECOVER_PROMPT = """Design the module named `encoder8` — an 8-to-3 priority encoder.

### Inputs:
- in [7:0]: the request bits.

### Outputs:
- out [2:0]: the index of the highest set bit.
"""

IO_RECOVER_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_encoder8(dut):
    dut['in'].value = 0b00010000
    await Timer(1, unit='ns')
    dut._log.info(f"out = {dut.out.value}")
    assert dut.out.value == 4
"""


def test_prompt_declared_interface_resolves():
    rec = _make_record("encoder8", IO_RECOVER_PROMPT, IO_RECOVER_TB)
    spec = CE.extract(rec)
    names = {p["name"]: p for p in spec["interface"]}
    assert "in" in names and names["in"]["dir"] == "input"
    assert "out" in names and names["out"]["dir"] == "output"
    assert names["in"]["width"] == 8 and names["out"]["width"] == 3
    # the cocotb framework attribute `_log` (harness-only) is never a port
    assert "_log" not in names
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (9) §4.05 — an INTERNAL register the prompt NEVER declares as a port is never
# promoted to the interface (it only ever appeared as a white-box cocotb probe,
# which is OFF-LIMITS). Only the PROMPT-declared ports are placed.
# --------------------------------------------------------------------------- #
WHITEBOX_PROMPT = """Design the module named `divider` that produces a divided clock
`clk_out` from the input clock. Reset `rst_n` clears the output.

### Inputs:
- clk: the input clock.
- rst_n: active-low reset.

### Outputs:
- clk_out: the divided clock.
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
    # the internal counter appears ONLY in the (off-limits) cocotb probe, never the
    # prompt -> it is not a port (§4.05: the harness is never read at all).
    assert "internal_div_counter" not in names, \
        "a white-box internal register must NOT become an interface port (§4.05)"
    iface = {p["name"]: p for p in spec["interface"]}
    assert iface.get("clk_out", {}).get("width") == 1
    assert iface["clk_out"]["source"] == "clk_rst_convention"


# --------------------------------------------------------------------------- #
# (10) GROUPED-BULLET WIDTH — a width stated ONCE in a `(N-bit each)` group header
# applies to the bulleted port names beneath it. The members inherit the width.
# --------------------------------------------------------------------------- #
GROUP_WIDTH_PROMPT = """Design the module named `ctrl` from a 6-bit feedback.

### Inputs:
- i_fb [5:0]: 6-bit feedback.

### Outputs:

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
# "(Default 4, must be > 0)" / "`P = 8` (default ...)" / "default is **8 bits**"
# resolves the port's `[P-1:0]` width to the stated default.
# --------------------------------------------------------------------------- #
PROSE_DEFAULT_PROMPT = """Design the module named `widthed`.

## Parameters
- `WID` (Default 4, must be greater than 0): bit-width of the data.
- `GPIO_WIDTH = 8` (default, configurable): number of pins.
- `p_data_width`: configurable data width, default is **8 bits**.

### Inputs:
- data [WID-1:0]: the data word.
- gpio [GPIO_WIDTH-1:0]: the gpio pins.

### Outputs:
- bus [p_data_width-1:0]: the bus payload.
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
    # "default is **8 bits**" -> p_data_width=8 -> bus is 8-bit
    assert iface["bus"]["width"] == 8
    # every resolved width is anchored to a parameter expression, not invented
    for n in ("data", "gpio", "bus"):
        assert iface[n]["source"] == "param_expression_width"
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (12) DERIVED-localparam + spec-notation-`x` multiply + bracket expression — a
# port sized by a derived `localparam`, by a spec `A x B x C` multiply, or by a
# bracket expression now resolves to the computed default.
# --------------------------------------------------------------------------- #
DERIVED_PROMPT = """Design the module named `crossbar`.

```
parameter DATA_W = 8,
localparam NPORTS = 4,
localparam DATA_W_IN = (DATA_W + $clog2(NPORTS))
```

## Parameters
- `RW` (default = 16): row width.
- `NS` (default = 4): element count.

### Inputs:
- in0 [DATA_W_IN-1:0]: input data (sized by the DERIVED localparam).
- flat [ (RW x NS) - 1 : 0]: a flattened vector using a spec `x` multiply.

### Outputs:
- o_sum [(RW + $clog2(NS)) - 1 : 0]: a summed bracket expression.
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


def test_derived_localparam_x_multiply_and_bracket_resolve():
    rec = _make_record("crossbar", DERIVED_PROMPT, DERIVED_TB)
    spec = CE.extract(rec)
    iface = {p["name"]: p for p in spec["interface"]}
    # DERIVED localparam: DATA_W_IN = 8 + clog2(4) = 10 -> in0 is 10-bit
    assert iface["in0"]["width"] == 10
    # spec `x` multiply: RW x NS = 16 x 4 = 64 -> flat is 64-bit
    assert iface["flat"]["width"] == 64
    # bracket expr: (RW + clog2(NS)) = 16 + 2 = 18 -> o_sum is 18-bit
    assert iface["o_sum"]["width"] == 18
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]


# --------------------------------------------------------------------------- #
# (13) §4.05 ADVERSARIAL — a parameter-expression width whose parameter has NO
# stated default STAYS a gap (the width form is present but unresolvable; never a
# fabricated default). The record is EXTRACTION_GAP, not silently COMPLETE.
# --------------------------------------------------------------------------- #
ABSENT_DEFAULT_PROMPT = """Design the module named `gpio2` (a modification of an earlier gpio).

### Inputs:
- gpio [GPIO_WIDTH-1:0]: bidirectional GPIO pins.

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


def test_param_expression_with_no_stated_default_is_placed_width_unknown():
    rec = _make_record("gpio2", ABSENT_DEFAULT_PROMPT, ABSENT_DEFAULT_TB)
    spec = CE.extract(rec)
    # GPIO_WIDTH has no derivable default. The PORT is prompt-declared, so it is
    # PLACED — but with width=None (UNKNOWN), never a fabricated/guessed literal
    # and never a coincidental same-line prose number. The width stays an honest
    # gap. (Step-2.7 §4.05 fix: dropping the port emptied the interface and dropped
    # the record to an un-gateable tier; grabbing a prose literal over-claimed a
    # wrong width. Placing it width=None lets the gate enforce presence+dir only.)
    by = {p["name"]: p for p in spec["interface"]}
    assert "gpio" in by, "a real prompt-declared port must be placed even when its width is unknown"
    assert by["gpio"]["width"] is None, \
        "a param-expression width with no stated default must NOT be fabricated"
    assert spec["completeness"] == "INCOMPLETE_EXTRACTION_GAP"
    gtypes = {g["type"] for g in spec["gaps"]
              if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"}
    assert "param_expression_width" in gtypes


# --------------------------------------------------------------------------- #
# (14) §4.05 ADVERSARIAL — a prompt-declared output whose width the prompt
# genuinely never states (only example VALUES, no `[hi:lo]` / `N-bit` / param)
# STAYS a SPEC_ABSENT gap. The width is the AI's irreducible domain — never a
# guessed width.
# --------------------------------------------------------------------------- #
ABSENT_WIDTH_PROMPT = """Design the module named `ascii_gen` that converts a character to
its ASCII code.

### Inputs:
- char_in [7:0]: the input character.

### Outputs:
- ascii_out: carries the code. Example outputs: 65, 49, 98.
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
    # ascii_out is a prompt-DECLARED output, BUT its width is never stated (only
    # example values) -> a SPEC_ABSENT gap, not a guess. It is surfaced in the
    # supplied interface (interface_source) but NOT placed with a fabricated width.
    assert "ascii_out" in set(spec["interface_source"]["outputs"])
    iface = {p["name"] for p in spec["interface"]}
    assert "ascii_out" not in iface, "an unstated width must not be fabricated"
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT", spec["completeness_reason"]
    assert any(g["type"] == "width_not_stated" for g in spec["gaps"])


# --------------------------------------------------------------------------- #
# (15) CHIP-AGNOSTIC — the gap-closures key on STRUCTURE, never a design name.
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

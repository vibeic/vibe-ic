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
# (6) range-before-name EXTRACTION_GAP: a `[1:0] name` declaration (range PRECEDES
# the identifier) is a width form our name-first reader misses -> EXTRACTION_GAP.
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


def test_classifier_range_before_name_is_extraction_gap():
    rec = _make_record("respmod", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB)
    spec = CE.extract(rec)
    # at least one EXTRACTION_GAP of the range_before_name type (resp_o has a
    # `[1:0] resp_o` range our name-first reader cannot tie to the name)
    assert spec["completeness"] == "INCOMPLETE_EXTRACTION_GAP"
    types = {g["type"] for g in spec["gaps"] if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"}
    assert "range_before_name" in types


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

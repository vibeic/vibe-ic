"""test_cvdp_solve_pipeline.py — the CVDP TIER-1→3 AUTHORING-GATE PIPELINE.

cvdp_solve_pipeline composes three shipped programs into ONE classify+gate layer
that makes the AI's CVDP solve STABLE by enforcing the program-extracted spec:

  solve(record)                  -> {tier, rtl, spec, gate}
  gate_check(record, candidate)  -> {pass, violations}

Tier model (owner's 5-tier):
  Tier1  the atomic bridge program-SOLVES it (deterministic, rtl returned).
  Tier3  the spec is COMPLETE-or-near -> the AI authors and the conformance GATE
         constrains it; gate_check REJECTS a drifting output (the stabilizer).
  Tier4  too-incomplete to gate (no module name / no ports / no convention).
  Tier5  genuine FLOOR (self-contradictory spec / broken harness), cited.

This suite proves:
  (1) TIER CLASSIFICATION — a bridge-solvable record is Tier1; a complete-spec
      record the bridge skips is Tier3; an interface-less record is Tier4; a
      conflicting-width record is Tier5 (floor).
  (2) GATE REJECTS — gate_check rejects an interface violation (wrong port width /
      missing port / wrong dir), a missing stated parameter, and a missing stated
      structure (enum mode), and ACCEPTS a conformant RTL.
  (3) §4.05 NO FALSE-REJECT — gate_check does NOT reject a correct RTL for an
      UNSTATED fact: an extra port the spec never carried, a width the spec left
      as a parameter expression, and a structure the extractor never recovered are
      all allowed. The gate only enforces facts that ARE in the extracted spec.
  (4) CHIP-AGNOSTIC — renaming every identifier yields the SAME tier and the SAME
      gate verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import cvdp_solve_pipeline as SP  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped record builder (faithful to CVDP v1.1.0): input.prompt +
# input.context{} + output.context{<rtl>:""} (EMPTY skeleton, never read) +
# harness.files with a src/.env carrying TOPLEVEL + a cocotb test_*.py.
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


# A fully-specified combinational adder — every port width stated with an explicit
# `[hi:lo]` range; the cocotb test drives a/b/carry_in and reads sum/carry_out.
ADDER_PROMPT = """Design a combinational module `adder8` that adds two operands.

## Inputs and Outputs

| Name        | Width  | Description       |
|-------------|--------|-------------------|
| `a [7:0]`   | 8 bits | First operand.    |
| `b [7:0]`   | 8 bits | Second operand.   |
| `carry_in`  | 1 bit  | Carry input.      |
| `sum [7:0]` | 8 bits | The 8-bit sum.    |
| `carry_out` | 1 bit  | Carry output.     |

The module performs `sum = a + b + carry_in`, with `carry_out` the overflow bit.
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


# --------------------------------------------------------------------------- #
# (1) TIER CLASSIFICATION
# --------------------------------------------------------------------------- #
def test_tier1_bridge_solvable_returns_rtl():
    """A fully-specified atomic adder is program-SOLVED by the bridge -> Tier1
    with the deterministic RTL returned (module named per TOPLEVEL)."""
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.solve(rec)
    assert res["tier"] == SP.TIER_PROGRAM
    assert res["rtl"] and "module adder8" in res["rtl"]
    # the gate is still built (carried for the record), and the spec is present.
    assert res["gate"]["module_name"] == "adder8"
    assert res["spec"]["module_name"] == "adder8"


# A complete-spec record the bridge SKIPS (a stated FSM controller — not a single
# registry-emittable atomic function), so the AI must author it. Interface is
# fully placed -> the gate is meaningful -> Tier3.
FSM_PROMPT = """Design a finite state machine `traffic_ctl`.

## Inputs and Outputs
- `clk` - clock.
- `rst_n` - active-low asynchronous reset.
- `sensor` - 1-bit vehicle sensor input.
- `light [1:0]` - 2-bit light output.

The FSM has states `S_RED`, `S_GREEN`, `S_YELLOW`. On reset it enters `S_RED`.
From `S_RED` it transitions to `S_GREEN` when `sensor` is high.
"""

FSM_TB = """import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def test_traffic_ctl(dut):
    dut.rst_n.value = 0
    dut.sensor.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    dut.sensor.value = 1
    await RisingEdge(dut.clk)
    l = int(dut.light.value)
"""


def test_complete_spec_fsm_is_tier2():
    """A COMPLETE-spec FSM the bridge skips -> Tier2: a PROGRAM
    (cvdp_complete_extract) pinned every testable fact, so the AI authors from the
    complete structured spec + gate (the most stable AI tier). No RTL is emitted;
    the gate carries the module name + placed interface."""
    rec = _make_record("traffic_ctl", FSM_PROMPT, FSM_TB)
    res = SP.solve(rec)
    assert res["tier"] == SP.TIER_AI_EMIT
    assert res["spec"].get("completeness") == "COMPLETE"
    assert res["rtl"] is None
    g = res["gate"]
    assert g["module_name"] == "traffic_ctl"
    names = {p["name"] for p in g["ports"]}
    assert {"sensor", "light"} <= names


# A record whose harness binds NO cocotb interface and whose prompt has no port
# table -> nothing to place -> the gate has no ports -> Tier4 (un-gateable).
NO_IFACE_PROMPT = """Implement a module `mystery_block` that does something useful.

It should process the incoming stream and produce a result. The exact widths
depend on the configuration.
"""

NO_IFACE_TB = """import cocotb

@cocotb.test()
async def test_mystery_block(dut):
    # no dut.<sig> interface references at all
    await cocotb.triggers.Timer(1, unit='ns')
"""


def test_tier4_no_interface_is_ungateable():
    rec = _make_record("mystery_block", NO_IFACE_PROMPT, NO_IFACE_TB)
    res = SP.solve(rec)
    assert res["tier"] == SP.TIER_UNGATED
    assert res["rtl"] is None
    # no ports -> the gate cannot stabilize the AI output (honest Tier4).
    assert res["gate"]["ports"] == []


# A GENUINE floor: the same port is DECLARED twice in real HDL declaration
# syntax (`input ... [hi:lo] name`) with two different widths -> the AI cannot
# satisfy both. This is the ONLY shape that may be called a floor; prose
# mentions / bit-selects / worked examples may NOT manufacture one.
CONTRADICT_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_widget(dut):
    dut.data_in.value = 1
    await Timer(1, unit='ns')
    r = int(dut.result.value)
"""

GENUINE_FLOOR_PROMPT = """Design a module `widget` with a data path.

In the first variant the interface is:
    input  logic [7:0]  data_in,
    output logic [7:0]  result

In the second variant the interface is:
    input  logic [15:0] data_in,
    output logic [7:0]  result
"""


def test_tier5_genuine_two_decl_contradiction_is_floor():
    rec = _make_record("widget", GENUINE_FLOOR_PROMPT, CONTRADICT_TB)
    res = SP.solve(rec)
    assert res["tier"] == SP.TIER_FLOOR
    assert "floor_reason" in res["gate"]
    assert "data_in" in res["gate"]["floor_reason"]
    # the cited evidence names the conflicting DECLARED widths.
    assert "8" in res["gate"]["floor_reason"] and "16" in res["gate"]["floor_reason"]


# --------------------------------------------------------------------------- #
# §4.05 NO-FALSE-FLOOR — the dominant lens for a suppressor gate: a floor means
# "unsolvable, give up", so a FALSE floor is far worse than a missed one. These
# pin the EXACT real-dataset shapes the old slice-blind detector wrongly called
# floors (64b66b_decoder / sync_serial_communication / vga_controller). Each
# port has ONE consistent declared width; the multiple bracketed numbers are
# BIT-SELECTS / multi-mode prose / worked examples — NOT conflicting decls.
# --------------------------------------------------------------------------- #
def test_no_false_floor_on_bit_slices_of_one_port():
    # decoder_data_in is one 66-bit port; `[65:64]` (sync header) and `[63:0]`
    # (payload) are SLICES — must NOT read as conflicting widths [2, 64].
    prompt = """Implement `dec`. The decoder processes a 66-bit word.
    input  logic [65:0] decoder_data_in,
    output logic [63:0] decoder_data_out

The sync header is `decoder_data_in[65:64]` and the payload is
`decoder_data_in[63:0]`. Example: decoder_data_in = {2'b01, 64'hA5A5A5A5A5A5A5A5}.
"""
    tb = CONTRADICT_TB.replace("data_in", "decoder_data_in").replace("test_widget", "test_dec")
    rec = _make_record("dec", prompt, tb)
    res = SP.solve(rec)
    assert res["tier"] != SP.TIER_FLOOR, res["gate"].get("floor_reason")


def test_no_false_floor_on_multimode_valid_bits():
    # data_in is a 64-bit port; the 8/16/32/64 are MODE-selected valid-bit counts
    # in prose, not conflicting declarations.
    prompt = """Implement `ser`. Transmitter with selectable width.
    input  logic [63:0] data_in,
    output logic        tx

- `3'h1`: 8 bits. `data_in [7:0]` is the valid data.
- `3'h2`: 16 bits. `data_in [15:0]` is the valid data.
- `3'h3`: 32 bits. `data_in [31:0]` is the valid data.
- `3'h4`: 64 bits. `data_in [63:0]` is the valid data.
"""
    rec = _make_record("ser", prompt, CONTRADICT_TB.replace("test_widget", "test_ser"))
    res = SP.solve(rec)
    assert res["tier"] != SP.TIER_FLOOR, res["gate"].get("floor_reason")


def test_no_false_floor_on_rgb_subfield_slices():
    # color_in is one 8-bit RRRGGGBB port; `[7:5]`/`[4:2]`/`[1:0]` are subfields.
    prompt = """Implement `vga`. Pixel color in RRRGGGBB format.
    input  logic [7:0] color_in,
    output logic [7:0] red

- `red`   = {color_in[7:5], 5'd0};
- `green` = {color_in[4:2], 5'd0};
- `blue`  = {color_in[1:0], 6'd0};
"""
    tb = CONTRADICT_TB.replace("data_in", "color_in").replace("test_widget", "test_vga")
    rec = _make_record("vga", prompt, tb)
    res = SP.solve(rec)
    assert res["tier"] != SP.TIER_FLOOR, res["gate"].get("floor_reason")


def test_prose_double_width_is_ambiguous_not_floor():
    # Two PROSE mentions of different widths (no real HDL declaration) are
    # AMBIGUOUS, not provably contradictory -> NOT a floor (let the AI attempt).
    # This is the exact fixture the old false-floor test used.
    prompt = """Design a module `widget` with a data path.

In one section the spec says `data_in [7:0]` is an 8-bit input.
In another section the spec says `data_in [15:0]` is a 16-bit input.
The output `result [7:0]` is 8 bits.
"""
    rec = _make_record("widget", prompt, CONTRADICT_TB)
    res = SP.solve(rec)
    assert res["tier"] != SP.TIER_FLOOR, res["gate"].get("floor_reason")


# --------------------------------------------------------------------------- #
# (2) GATE REJECTS interface / param / structure violations + ACCEPTS conformant
# --------------------------------------------------------------------------- #
ADDER_GOOD = """module adder8 (
    input  [7:0] a,
    input  [7:0] b,
    input        carry_in,
    output [7:0] sum,
    output       carry_out
);
    assign {carry_out, sum} = a + b + carry_in;
endmodule
"""


def test_gate_accepts_conformant_rtl():
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, ADDER_GOOD)
    assert res["pass"] is True, res["violations"]
    assert res["violations"] == []


def test_gate_no_false_reject_on_keyword_prefixed_port_names():
    """§4.05 false-reject regression (Step-2.7, corpus-caught on hmac_register):
    a port whose NAME begins with a type keyword (`registers` / `logic_out` /
    `wire_sel`) must be parsed as that full name — the candidate parser's
    `(?:wire|reg|logic)` match needs a trailing word boundary, else `reg` ate the
    prefix of `registers` (leaving `isters`) and a CORRECT answer was rejected."""
    rtl = (
        "module m (\n"
        "    input  [7:0] addr,\n"
        "    output       registers,\n"
        "    output [1:0] logic_out,\n"
        "    input        wire_sel\n"
        ");\nendmodule\n")
    parsed = SP._parse_candidate_header(rtl)
    assert parsed is not None
    names = {p["name"] for p in parsed[1]}
    assert {"addr", "registers", "logic_out", "wire_sel"} <= names, names
    # and the keyword-typed port still parses correctly (reg/logic as a TYPE)
    rtl2 = "module n (output reg [3:0] cnt, output logic done);\nendmodule\n"
    names2 = {p["name"] for p in SP._parse_candidate_header(rtl2)[1]}
    assert {"cnt", "done"} <= names2, names2


def test_gate_rejects_wrong_port_width():
    """A drifting AI output (sum declared 7-bit instead of 8) is REJECTED with a
    concrete, fixable width violation — the Tier-3 stabilizer."""
    bad = ADDER_GOOD.replace("output [7:0] sum", "output [6:0] sum")
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, bad)
    assert res["pass"] is False
    kinds = {v["kind"] for v in res["violations"]}
    assert "port_width" in kinds
    assert any("sum" in v["detail"] for v in res["violations"])


def test_gate_rejects_missing_port():
    bad = ADDER_GOOD.replace("    input        carry_in,\n", "")
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, bad)
    assert res["pass"] is False
    assert any(v["kind"] == "missing_port" and "carry_in" in v["detail"]
               for v in res["violations"])


def test_gate_rejects_wrong_module_name():
    bad = ADDER_GOOD.replace("module adder8", "module adder_8bit")
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, bad)
    assert res["pass"] is False
    assert any(v["kind"] == "module_name" for v in res["violations"])


def test_gate_rejects_wrong_port_direction():
    bad = ADDER_GOOD.replace("output [7:0] sum", "input  [7:0] sum")
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, bad)
    assert res["pass"] is False
    assert any(v["kind"] == "port_dir" and "sum" in v["detail"]
               for v in res["violations"])


# A stated PARAMETER the AI must declare. The cocotb test reads WIDTH via
# int(dut.WIDTH.value) (a config parameter), and the prompt's parameter table
# states it -> the gate requires it be declared.
PARAM_PROMPT = """Design a parameterized register `preg`.

## Parameters
| Parameter | Default | Description        |
|-----------|---------|--------------------|
| `WIDTH`   | 8       | data path width    |

## Inputs and Outputs
- `clk` - clock.
- `d [7:0]` - 8-bit data input.
- `q [7:0]` - 8-bit registered output.
"""

PARAM_TB = """import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def test_preg(dut):
    WIDTH = int(dut.WIDTH.value)
    dut.d.value = 5
    await RisingEdge(dut.clk)
    q = int(dut.q.value)
"""

PARAM_GOOD = """module preg #(parameter WIDTH = 8) (
    input               clk,
    input  [7:0]        d,
    output reg [7:0]    q
);
    always @(posedge clk) q <= d;
endmodule
"""


def test_gate_rejects_missing_param():
    """The stated parameter WIDTH must be declared; an output that drops it is
    REJECTED."""
    rec = _make_record("preg", PARAM_PROMPT, PARAM_TB)
    assert "WIDTH" in SP.solve(rec)["gate"]["params"]
    bad = PARAM_GOOD.replace("#(parameter WIDTH = 8) ", "")
    res = SP.gate_check(rec, bad)
    assert res["pass"] is False
    assert any(v["kind"] == "missing_param" and "WIDTH" in v["detail"]
               for v in res["violations"])
    # ... and the conformant RTL that declares it is ACCEPTED.
    assert SP.gate_check(rec, PARAM_GOOD)["pass"] is True


def test_gate_rejects_missing_enum_mode():
    """A stated enum mode / FSM state the extractor recovered must be REPRESENTED
    in the candidate; an output that omits one is REJECTED. We drive gate_check_spec
    with a gate the extractor's structure shape produces (built via build_gate from
    a faithful spec), so the test pins the GATE's structure-enforcement directly,
    independent of any one extractor's prose grammar."""
    # a faithful spec carrying recovered enum modes (the shape extract() emits).
    spec = {
        "module_name": "modeic",
        "interface": [
            {"name": "mode_sel", "dir": "input", "width": 2, "source": "prose"},
            {"name": "y", "dir": "output", "width": 8, "source": "prose"},
        ],
        "params": {},
        "harness": {"params": []},
        "structures": {
            "register_map": [], "enum_modes": [{"name": "MODE_ADD"},
                                               {"name": "MODE_SUB"},
                                               {"name": "MODE_XOR"}],
            "fsm": {"states": [], "transitions": []},
            "worked_examples": [],
        },
        "completeness": "COMPLETE",
    }
    gate = SP.build_gate(spec)
    assert set(gate["structures"]["enum_modes"]) == {"MODE_ADD", "MODE_SUB", "MODE_XOR"}
    good = (
        "module modeic (\n"
        "  input [1:0] mode_sel, output [7:0] y\n);\n"
        "  localparam MODE_ADD = 0, MODE_SUB = 1, MODE_XOR = 2;\n"
        "endmodule\n"
    )
    assert SP.gate_check_spec(gate, good)["pass"] is True, \
        SP.gate_check_spec(gate, good)["violations"]
    # drop one stated mode -> rejected with a concrete missing-structure reason.
    bad = good.replace("MODE_SUB = 1, ", "")
    res = SP.gate_check_spec(gate, bad)
    assert res["pass"] is False
    assert any(v["kind"] == "missing_enum_mode" and "MODE_SUB" in v["detail"]
               for v in res["violations"])


# --------------------------------------------------------------------------- #
# (3) §4.05 — gate_check does NOT reject a correct RTL for an UNSTATED fact
# --------------------------------------------------------------------------- #
def test_405_extra_unstated_port_is_not_rejected():
    """The spec never carried a `debug_o` port; an AI output that legitimately adds
    one must NOT be rejected — the gate only enforces facts that ARE in the spec."""
    extra = ADDER_GOOD.replace(
        "    output       carry_out\n",
        "    output       carry_out,\n    output       debug_o\n")
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    res = SP.gate_check(rec, extra)
    assert res["pass"] is True, res["violations"]


def test_405_parameter_expression_width_is_not_width_rejected():
    """The spec width is a literal 8, but if a candidate declares the SAME port with
    a PARAMETER-EXPRESSION width (`[WIDTH-1:0]`, an over-ridable width), the gate
    must NOT reject it for a literal-width mismatch — a parameterized width is not a
    stated-literal violation (§4.05)."""
    rec = _make_record("preg", PARAM_PROMPT, PARAM_TB)
    # candidate uses the parameterized width form for d/q rather than literal [7:0]
    cand = """module preg #(parameter WIDTH = 8) (
    input                   clk,
    input  [WIDTH-1:0]      d,
    output reg [WIDTH-1:0]  q
);
    always @(posedge clk) q <= d;
endmodule
"""
    res = SP.gate_check(rec, cand)
    # d/q widths are param-expressions on the candidate side -> width NOT enforced;
    # WIDTH is declared -> no param violation. The output is ACCEPTED.
    assert res["pass"] is True, res["violations"]


def test_405_unrecovered_structure_is_not_demanded():
    """The adder spec has NO enum/FSM/register structures; the gate must demand
    none, so a plain conformant adder (no localparams) passes — the gate never
    invents a structure the extractor did not recover."""
    rec = _make_record("adder8", ADDER_PROMPT, ADDER_TB)
    gate = SP.solve(rec)["gate"]
    s = gate["structures"]
    assert s["enum_modes"] == [] and s["fsm_states"] == [] and s["register_names"] == []
    assert SP.gate_check(rec, ADDER_GOOD)["pass"] is True


# --------------------------------------------------------------------------- #
# (4) CHIP-AGNOSTIC — renaming every identifier yields the SAME tier + verdict
# --------------------------------------------------------------------------- #
def _rename(text, mapping):
    import re
    for a, b in mapping.items():
        text = re.sub(rf"\b{re.escape(a)}\b", b, text)
    return text


def test_chip_agnostic_tier_and_gate_invariant_under_rename():
    """The pipeline keys on STRUCTURE, never a design-name literal: renaming the
    module + ports yields the SAME tier and an isomorphic gate (same port count /
    widths / dirs). Tested on a Tier-3 record (the gate is the deliverable there)."""
    mapping = {
        "traffic_ctl": "zylo3", "sensor": "trig", "light": "lamp",
        "S_RED": "P0", "S_GREEN": "P1", "S_YELLOW": "P2",
    }
    rec0 = _make_record("traffic_ctl", FSM_PROMPT, FSM_TB)
    rec1 = _make_record(
        "zylo3", _rename(FSM_PROMPT, mapping), _rename(FSM_TB, mapping), rid="renamed")
    r0, r1 = SP.solve(rec0), SP.solve(rec1)
    # SAME tier — invariant under rename (chip-AGNOSTIC); both land in the gated
    # AI band (Tier2/Tier3), never shifting because an identifier changed.
    assert r0["tier"] == r1["tier"]
    assert r0["tier"] in (SP.TIER_AI_EMIT, SP.TIER_AI_GATED)
    # SAME interface shape (count + widths + dirs), names renamed in lock-step
    p0 = sorted((p["dir"], p["width"]) for p in r0["gate"]["ports"])
    p1 = sorted((p["dir"], p["width"]) for p in r1["gate"]["ports"])
    assert p0 == p1
    assert len(r0["gate"]["params"]) == len(r1["gate"]["params"])


def test_chip_agnostic_gate_reject_invariant_under_rename():
    """The SAME wrong-width violation is caught regardless of identifier names —
    on a Tier-1-solvable adder (rename only the module + output, not the operands,
    so the bridge still recognizes the operation; the GATE is what we assert is
    name-agnostic)."""
    mapping = {"adder8": "zylo3", "sum": "tot"}
    rec1 = _make_record(
        "zylo3", _rename(ADDER_PROMPT, mapping), _rename(ADDER_TB, mapping), rid="r2")
    good1 = _rename(ADDER_GOOD, mapping)
    # conformant renamed RTL passes its renamed gate
    assert SP.gate_check(rec1, good1)["pass"] is True, SP.gate_check(rec1, good1)["violations"]
    # the SAME wrong-width drift is caught under the renamed identifiers
    bad1 = good1.replace("output [7:0] tot", "output [6:0] tot")
    res = SP.gate_check(rec1, bad1)
    assert res["pass"] is False
    assert any(v["kind"] == "port_width" for v in res["violations"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

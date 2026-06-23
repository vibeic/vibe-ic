"""Tests for rtllm_tier_pipeline.py + rtllm_iface_recover.py + rtllm_arith_ext_synth.py
— the RTLLM 5-tier converge pipeline (mirror of cvdp_solve_pipeline / the
VerilogEval tier pipelines).

Two layers:
  * PURE-LOGIC (always run): the conformance gate (build_gate / gate_check), the
    header-dialect interface recoverer, and the iverilog-proven arithmetic
    extension — each with a POSITIVE case and §4.05 NEGATIVE cases (a wrong RTL is
    REJECTED; an under-specified prose SKIPs; an unstated fact is never demanded;
    the arith extension never fires on a non-adder / out-of-scope op).
  * DATASET+IVERILOG (auto-skipped when the RTLLM dataset or iverilog/vvp are
    absent): the end-to-end Tier-1 verification + the Tier-5 golden-floor proof
    on the real benchmark.

chip-AGNOSTIC: every assertion keys on structure (interface shape, arithmetic
grammar, golden-vs-testbench result), never on a design name.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtllm_tier_pipeline as P            # noqa: E402
import rtllm_iface_recover as R            # noqa: E402
import rtllm_arith_ext_synth as AX         # noqa: E402
import port_parser as PP                   # noqa: E402
import rtllm_port_bridge as BR             # noqa: E402

_RTLLM_ROOT = Path("/home/reyerchu/AI_IC_design/_extbench/RTLLM")
_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_HAVE_DS = _RTLLM_ROOT.is_dir()
_needs_iv = pytest.mark.skipif(not _HAVE_IV, reason="iverilog/vvp not installed")
_needs_ds = pytest.mark.skipif(not _HAVE_DS, reason="RTLLM dataset absent")


# --------------------------------------------------------------------------- #
# gate_check — POSITIVE + §4.05 NEGATIVES
# --------------------------------------------------------------------------- #
def _gate(module, ports):
    return {"module_name": module, "ports": ports, "completeness": "COMPLETE"}


def test_gate_accepts_conformant_header():
    gate = _gate("adder_8bit", [
        {"name": "a", "dir": "input", "width": 8},
        {"name": "b", "dir": "input", "width": 8},
        {"name": "cin", "dir": "input", "width": 1},
        {"name": "sum", "dir": "output", "width": 8},
        {"name": "cout", "dir": "output", "width": 1}])
    rtl = ("module adder_8bit(input [7:0] a, input [7:0] b, input cin,"
           " output [7:0] sum, output cout); assign {cout,sum}=a+b+cin; endmodule")
    res = P.gate_check_spec(gate, rtl)
    assert res["pass"], res["violations"]


def test_gate_rejects_wrong_module_name():
    gate = _gate("adder_8bit", [{"name": "a", "dir": "input", "width": 8}])
    rtl = "module WRONG(input [7:0] a); endmodule"
    res = P.gate_check_spec(gate, rtl)
    assert not res["pass"]
    assert any(v["kind"] == "module_name" for v in res["violations"])


def test_gate_rejects_missing_port():
    gate = _gate("m", [{"name": "a", "dir": "input", "width": 8},
                       {"name": "b", "dir": "input", "width": 8}])
    rtl = "module m(input [7:0] a); endmodule"
    res = P.gate_check_spec(gate, rtl)
    assert not res["pass"]
    assert any(v["kind"] == "missing_port" and "`b`" in v["detail"]
               for v in res["violations"])


def test_gate_rejects_wrong_width():
    gate = _gate("m", [{"name": "s", "dir": "output", "width": 8}])
    rtl = "module m(output [6:0] s); endmodule"   # 7 bits, spec says 8
    res = P.gate_check_spec(gate, rtl)
    assert not res["pass"]
    assert any(v["kind"] == "port_width" for v in res["violations"])


def test_gate_405_does_not_demand_unstated_width():
    # spec width unknown (parameter-expression) -> a literal-width candidate is NOT
    # rejected (the load-bearing §4.05 no-false-reject rule).
    gate = _gate("m", [{"name": "c", "dir": "output", "width": None}])
    rtl = "module m(output [31:0] c); endmodule"
    res = P.gate_check_spec(gate, rtl)
    assert res["pass"], res["violations"]


def test_gate_405_allows_extra_candidate_ports():
    # an extra port the AI legitimately adds (a clk the harness drives) is NOT a
    # violation — the gate only enforces the ports the spec carries.
    gate = _gate("m", [{"name": "a", "dir": "input", "width": 8}])
    rtl = "module m(input clk, input [7:0] a, output o); endmodule"
    res = P.gate_check_spec(gate, rtl)
    assert res["pass"], res["violations"]


def test_gate_no_module_header_is_reject():
    res = P.gate_check_spec(_gate("m", []), "// just a comment, no module")
    assert not res["pass"]
    assert res["violations"][0]["kind"] == "no_module"


# --------------------------------------------------------------------------- #
# rtllm_iface_recover — the header-dialect recoverer (T4->T3->T2 lever)
# --------------------------------------------------------------------------- #
def test_recover_paren_direction_form():
    # float_multi-style: direction (+width) inside parens, not a section header.
    text = ("Input ports:\n"
            "    clk (input): Clock.\n"
            "    a (input [31:0]): First operand.\n"
            "    b (input [31:0]): Second operand.\n"
            "Output ports:\n"
            "    z (output reg [31:0]): Result.\n"
            "Internal signals:\n"
            "    tmp (reg [23:0]): not a port.\n")
    ins, outs = R.recover_ports(text)
    assert ("a", 32) in ins and ("b", 32) in ins and ("clk", 1) in ins
    assert outs == [("z", 32)]
    assert ("tmp", 24) not in ins and ("tmp", 24) not in outs  # internal -> excluded


def test_recover_param_expression_width_present_unknown():
    # fixed_point-style: [N-1:0] -> present, width None (never a guessed int).
    text = ("Input ports:\n"
            "    a [N-1:0]: First operand.\n"
            "    b [N-1:0]: Second operand.\n"
            "Output ports:\n"
            "    c [N-1:0]: Result.\n")
    ins, outs = R.recover_ports(text)
    assert ins == [("a", None), ("b", None)]
    assert outs == [("c", None)]


def test_recover_bare_inputs_outputs_headers():
    # traffic_light-style: 'Inputs:' / 'Outputs:' synonyms.
    text = ("Inputs:\n"
            "    rst_n: Reset.\n"
            "    clk: Clock.\n"
            "Outputs:\n"
            "    clock[7:0]: 8-bit counter value.\n")
    ins, outs = R.recover_ports(text)
    assert ("rst_n", 1) in ins and ("clk", 1) in ins
    assert ("clock", 8) in outs


def test_recover_range_is_authoritative_over_prose_token():
    # multi_8bit-style: explicit [15:0] wins over a stray "8-bit" prose token that
    # refers to the OPERANDS (the strict base bridge drops this as "ambiguous").
    text = ("Input ports:\n"
            "    A [7:0]: First 8-bit operand.\n"
            "Output ports:\n"
            "    product [15:0]: 16-bit output, product of the two 8-bit inputs.\n")
    ins, outs = R.recover_ports(text)
    assert ("product", 16) in outs


# --------------------------------------------------------------------------- #
# rtllm_arith_ext_synth — POSITIVE + §4.05 NEGATIVES
# --------------------------------------------------------------------------- #
def _adder_prompt():
    return ("Implement an 8-bit adder with multiple bit-level adders.\n"
            "Module name:\n    adder_8bit\n"
            "Input ports:\n    a[7:0]\n    b[7:0]\n    cin\n"
            "Output ports:\n    sum[7:0]\n    cout\n")


def test_arith_ext_emits_nbit_adder_with_cout():
    p = _adder_prompt()
    ins = [("a", 8), ("b", 8), ("cin", 1)]
    outs = [("sum", 8), ("cout", 1)]
    rtl = AX.synth(p, ins, outs, "adder_8bit")
    assert rtl is not None
    assert "module adder_8bit" in rtl
    assert "{cout, sum}" in rtl and "a + b + cin" in rtl


def test_arith_ext_emits_without_carry_in():
    p = "Implement an N-bit adder.\nInput ports:\n a\n b\nOutput ports:\n y\n co\n"
    rtl = AX.synth(p, [("a", 16), ("b", 16)], [("y", 16), ("co", 1)], "m")
    assert rtl is not None
    assert "a + b;" in rtl   # no cin term
    assert "{co, y}" in rtl


def test_arith_ext_405_skips_multiplier():
    p = "Implement an 8-bit multiplier.\nInput ports:\n a\n b\nOutput ports:\n product\n"
    assert AX.synth(p, [("a", 8), ("b", 8)], [("product", 16)], "m") is None


def test_arith_ext_405_skips_subtractor_and_bcd():
    ps = ["Implement a 64-bit subtractor.\n a\n b\n diff\n",
          "Implement a BCD adder.\n a\n b\n sum\n carry\n"]
    for p in ps:
        assert AX.synth(p, [("a", 8), ("b", 8)], [("s", 8), ("c", 1)], "m") is None


def test_arith_ext_405_skips_pipelined_or_clocked():
    p = "Implement a pipelined 64-bit adder.\n clk\n a\n b\n sum\n cout\n"
    assert AX.synth(p, [("clk", 1), ("a", 64), ("b", 64)],
                    [("sum", 64), ("cout", 1)], "m") is None


def test_arith_ext_405_does_not_false_match_module_or_multiple():
    # the scope guard must NOT trip on the boilerplate "Module name:" header nor on
    # the word "multiple" (these were two real false-positive bugs that suppressed
    # every fire — regression-pinned here).
    p = ("Implement an 8-bit adder built from multiple full adders.\n"
         "Module name:\n    adder_8bit\n")
    rtl = AX.synth(p, [("a", 8), ("b", 8), ("cin", 1)],
                   [("sum", 8), ("cout", 1)], "adder_8bit")
    assert rtl is not None


def test_arith_ext_405_skips_when_no_adder_cue():
    p = "Implement a register file.\nInput ports:\n a\n b\nOutput ports:\n y\n co\n"
    assert AX.synth(p, [("a", 8), ("b", 8)], [("y", 8), ("co", 1)], "m") is None


def test_arith_ext_405_skips_packed_carry_form():
    # a single (N+1)-bit output (carry packed in the MSB) is arithmetic_synth's
    # FORM C, NOT this separate-carry-out FORM -> this solver must SKIP (no cout).
    p = "Implement an N-bit adder; the sum output includes the overflow bit.\n a\n b\n"
    assert AX.synth(p, [("a", 8), ("b", 8)], [("sum", 9)], "m") is None


# --------------------------------------------------------------------------- #
# build_gate — interface recovered for a known dialect (no iverilog needed for
# the gate itself, but module_name resolution needs the testbench -> dataset gate)
# --------------------------------------------------------------------------- #
def _design_dir(name):
    for d in P.find_designs(str(_RTLLM_ROOT)):
        if Path(d).name == name:
            return d
    return None


@_needs_ds
def test_build_gate_recovers_paren_direction_interface():
    dd = _design_dir("float_multi")
    assert dd is not None
    gate = P.build_gate(dd)
    names = {p["name"] for p in gate["ports"]}
    assert {"a", "b", "z"} <= names
    assert gate["completeness"] == "COMPLETE"


@_needs_ds
def test_build_gate_recovers_param_width_interface():
    dd = _design_dir("fixed_point_adder")
    assert dd is not None
    gate = P.build_gate(dd)
    names = {p["name"] for p in gate["ports"]}
    assert {"a", "b", "c"} <= names
    # parameter-expression widths -> width None (present, unknown), never guessed.
    assert all(p["width"] is None for p in gate["ports"])


# --------------------------------------------------------------------------- #
# DATASET + IVERILOG end-to-end: Tier-1 verification + Tier-5 floor proof
# --------------------------------------------------------------------------- #
@_needs_ds
@_needs_iv
def test_tier1_adder_8bit_is_program_solved_and_verified():
    dd = _design_dir("adder_8bit")
    res = P.solve(dd)
    assert res["tier"] == P.TIER_PROGRAM
    assert res["rtl"] is not None
    assert res["evidence"]["verify"] == "iverilog PASS"


@_needs_ds
@_needs_iv
def test_tier5_clkgenerator_is_proven_floor():
    # the golden FAILS its own testbench (sampling race / integer-vs-1bit compare):
    # a genuine floor, cited with the run evidence.
    dd = _design_dir("clkgenerator")
    why = P.golden_floor_evidence(dd)
    assert why is not None
    assert "golden fails its own testbench" in why


@_needs_ds
@_needs_iv
def test_tier5_ring_counter_is_tool_incompatible_floor():
    # the testbench uses an iverilog-unsupported construct (array-slice assign):
    # the golden cannot even build -> a tool-incompatible floor.
    dd = _design_dir("ring_counter")
    why = P.golden_floor_evidence(dd)
    assert why is not None
    assert "golden fails its own testbench" in why


@_needs_ds
@_needs_iv
def test_a_passing_golden_is_NOT_flagged_as_floor():
    # conservative floor proof: a design whose golden PASSES must return None.
    dd = _design_dir("adder_8bit")
    assert P.golden_floor_evidence(dd) is None


@_needs_ds
@_needs_iv
def test_full_distribution_converges_to_expected_shape():
    info = P.distribution(str(_RTLLM_ROOT))
    c = info["counts"]
    assert info["total"] == 50
    # INVARIANTS (robust to canonical-solver growth): the exact Tier1 count rises
    # as the shared canonical solvers cover more forms (this pipeline reuses them
    # + the arith extension, all iverilog-VERIFIED), so we pin the floor + the
    # stable ceiling, not a frozen Tier1 number. At minimum the 3 iverilog-proven
    # adders are Tier1; on the full canonical base it is more (RAM/ROM/accu/...).
    assert c[1] >= 3              # >= the 3 proven adders; grows with canonicals
    assert c[4] == 0              # no too-incomplete residual (interface recovered)
    assert c[5] == 4              # the 4 proven golden-fails-own-test floors
    assert c[1] + c[2] + c[3] == 46   # stable = solvable ceiling (total - floors)
    assert c[3] == 0              # every gate-able design is COMPLETE (Tier2) here

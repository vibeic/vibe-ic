"""test_compose_synth.py — the CVDP DECOMPOSE -> SOLVE-EACH -> COMPOSE engine.

compose_synth.solve(record) parses a composite TOP's structure from the prompt
prose / skeleton HEADER / harness interface (NEVER the golden body), solves each
sub-block with the atomic solvers, and emits the wired structural top. Today it emits
the THIN-WRAPPER pattern: a fixed-latency registered wrapper around an N-element
'+'-reduction of a flattened input vector (the sub-block being composed is the adder
core; the glue is the input/output registers + the valid pipeline).

POSITIVE: a real-shaped `cascaded_adder` composite (flattened N-element vector summed,
registered, fixed 2-cycle latency, async-low reset, i_valid->o_valid handshake)
DECOMPOSES and the emit is FUNCTIONALLY correct against the harness convention
(host-verified via iverilog when available: o_data == sum, cocotb-measured latency
== 2, reset zeroes the outputs).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * UNPARSEABLE structure — the latency / reset / vector-width are not unambiguously
    stated, so the wrapper plumbing cannot be reconstructed without guessing;
  * a sub-block that is NOT atomic-solvable — a non-plain-sum reduction (e.g. a
    Galois-field / weighted / convolution core) the '+' template would emit WRONG;
  * NOVEL-LOGIC — a bus / protocol / memory / cache top no atomic block covers.

CHIP-AGNOSTIC: the engine keys only on operation/interface vocabulary, never on a
design name. A renamed copy of the positive decomposes identically; the SKIP guards
fire on the SEMANTICS, not the module name.

iverilog functional check is GATED on the iverilog binary; the structural / SKIP
assertions run anywhere.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import compose_synth as C  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped record fixtures (faithful to CVDP v1.1.0 structure: input.prompt
# [+ optional input.context skeleton header] + EMPTY output.context[<rtl path>]
# + harness.files with a .env carrying TOPLEVEL + a cocotb test_*.py).
# --------------------------------------------------------------------------- #
def _make_record(top, rtl_path, prompt, cocotb_test, input_context=None):
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": input_context or {}},
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


# A faithful THIN-WRAPPER composite: a cascaded adder that sums IN_DATA_NS elements of a
# flattened input vector, registered, with an explicit 2-cycle latency, async-low reset,
# and an i_valid -> o_valid handshake. The prose states the port list (no fenced header),
# the parameters' defaults, the sum semantics, the fixed latency, and the reset — every
# fact the engine needs is grounded in the prose.
_CASCADE_PROMPT = """Develop a SystemVerilog module named `cascaded_adder` that performs the summation of
multiple input data elements, synchronized to the clock, with asynchronous reset.

## Parameters:
 - **`IN_DATA_WIDTH` (default = 16):** the bit-width of each individual input data element.
 - **`IN_DATA_NS` (default = 4):** the number of input data elements to be summed.

## Input Ports:
- `clk`: Clock signal. The design registers are triggered on its positive edge.
- `rst_n`: An active-low asynchronous reset signal. When low, both `o_valid` and `o_data` are driven low.
- `i_valid`: An active-high input signal indicating the availability of valid data.
- `i_data` [`IN_DATA_WIDTH` * `IN_DATA_NS` - 1 : 0]: Input data provided as a flattened 1D vector.
  This vector contains `IN_DATA_NS` elements, each `IN_DATA_WIDTH` bits wide.

## Output Ports:
- `o_valid`: Active-high signal indicating that the output sum has been computed.
- `o_data` [(`IN_DATA_WIDTH` + $clog2(`IN_DATA_NS`)) - 1 : 0]: the cumulative sum of all input elements.

## Functional Description:
The output provides the cumulative sum of all the input elements. The output width accommodates
the full sum without overflow. The module introduces a total latency of two clock cycles: one
cycle for registering the input data, and another for registering the output sum.
"""

_CASCADE_COCOTB = """import cocotb
@cocotb.test()
async def test_cascaded_adder(dut):
    pass
"""


def _cascade_record(top="cascaded_adder"):
    prompt = _CASCADE_PROMPT.replace("cascaded_adder", top)
    return _make_record(top, f"rtl/{top}.sv", prompt, _CASCADE_COCOTB)


# NEGATIVE 1 — UNPARSEABLE: same sum composite but the latency is NOT stated, so the
# wrapper plumbing cannot be reconstructed without guessing -> SKIP.
def _unparseable_record():
    prompt = _CASCADE_PROMPT.replace(
        "The module introduces a total latency of two clock cycles: one\n"
        "cycle for registering the input data, and another for registering the output sum.",
        "The module registers its data path.")  # latency removed
    return _make_record("cascaded_adder", "rtl/cascaded_adder.sv", prompt, _CASCADE_COCOTB)


# NEGATIVE 2 — NON-ATOMIC sub-block: a Galois-field weighted reduction is NOT a plain
# '+' sum; the '+' template would emit a functionally WRONG core -> SKIP.
def _nonatomic_core_record():
    prompt = _CASCADE_PROMPT.replace(
        "The output provides the cumulative sum of all the input elements.",
        "The output provides the Galois field GF(2^8) modular sum (carry-less, with "
        "irreducible polynomial reduction) of all the input elements.")
    return _make_record("gf_reducer", "rtl/gf_reducer.sv",
                        prompt.replace("cascaded_adder", "gf_reducer"), _CASCADE_COCOTB)


# NEGATIVE 3 — NOVEL-LOGIC: a bus/protocol top no atomic block covers -> SKIP.
_AXI_PROMPT = """Design an `axi_lite_regfile` module: an AXI4-Lite slave that exposes a bank of
memory-mapped registers. It implements the AWVALID/AWREADY/WVALID/WREADY write handshake
and the ARVALID/ARREADY/RVALID/RREADY read handshake over the AXI-Lite interface.

## Input Ports:
- `clk`: clock.
- `rst_n`: active-low asynchronous reset.
- `awvalid` [0:0]: write-address valid.
- `wdata` [31:0]: write data.

## Output Ports:
- `awready`: write-address ready.
- `rdata` [31:0]: read data.
"""


def _novel_record():
    return _make_record("axi_lite_regfile", "rtl/axi_lite_regfile.sv",
                        _AXI_PROMPT, _CASCADE_COCOTB)


# NEGATIVE 4 — NO RESOLVABLE TOPLEVEL: the SAME clean sum composite, but the prose
# never NAMES a module (the `module named \`cascaded_adder\`` designation is stripped)
# and input.context is empty — so the target module name is absent from the ONLY two
# compliant sources (input.prompt + input.context). The harness `.env` TOPLEVEL is the
# OFF-LIMITS oracle and is NOT consulted, so with no name to emit under, solve SKIPs.
# This is the compliant expression of the original "no emit without a toplevel" intent
# under the prompt+context-only name-resolution rule (previously the fixture blanked
# the harness `.env`, which the refactored bridge no longer reads).
def _no_named_toplevel_record():
    prompt = _CASCADE_PROMPT.replace(
        "module named `cascaded_adder` that performs", "design that performs")
    # input.context stays empty; harness `.env` keeps its (ignored) TOPLEVEL.
    return _make_record("cascaded_adder", "rtl/cascaded_adder.sv", prompt, _CASCADE_COCOTB)


# =========================================================================== #
# STRUCTURAL — decomposition + SKIP behavior (run anywhere)
# =========================================================================== #
def test_positive_decomposes_and_emits_top():
    rtl = C.solve(_cascade_record())
    assert rtl is not None, "the clean THIN-WRAPPER composite must decompose + emit"
    # the emitted top is named per TOPLEVEL and is a structural wrapper around a sum core.
    assert "module cascaded_adder" in rtl
    assert "sum_comb" in rtl and "+" in rtl          # the atomic '+'-reduction core
    assert "v1 <= i_valid" in rtl and "o_valid <= v1" in rtl  # the 2-cycle valid pipeline
    assert "endmodule" in rtl


def test_positive_pattern_is_thin_wrapper_sum():
    assert C.pattern_of(_cascade_record()) == "thin_wrapper_sum"


def test_skip_unparseable_structure():
    # latency unstated -> wrapper plumbing not reconstructable -> SKIP (never guess).
    assert C.solve(_unparseable_record()) is None


def test_skip_nonatomic_sub_block():
    # a GF / carry-less weighted reduction is NOT a plain sum -> SKIP (NO-CHEAT).
    assert C.solve(_nonatomic_core_record()) is None


def test_skip_novel_logic():
    # a bus/protocol top is not an atomic-sub-block composite -> SKIP.
    assert C.solve(_novel_record()) is None


def test_no_emit_without_toplevel():
    # No module name in input.prompt OR input.context -> name unresolvable from the
    # only two compliant sources -> nothing to emit under -> SKIP. The harness .env
    # TOPLEVEL (OFF-LIMITS oracle) is deliberately NOT the source of the skip.
    rec = _no_named_toplevel_record()
    assert C._toplevel(rec) is None, "sanity: module name absent from prompt+context"
    assert C.solve(rec) is None


def test_no_emit_on_empty_prompt():
    rec = _cascade_record()
    rec["input"]["prompt"] = ""
    assert C.solve(rec) is None


# =========================================================================== #
# CHIP-AGNOSTIC — keys on semantics, never on a design name
# =========================================================================== #
def test_chip_agnostic_rename_decomposes_identically():
    base = C.solve(_cascade_record("cascaded_adder"))
    renamed = C.solve(_cascade_record("totally_unrelated_name_zzz"))
    assert base is not None and renamed is not None
    assert "module totally_unrelated_name_zzz" in renamed
    # the two emits are identical up to the module name (same structure / same core).
    assert base.replace("cascaded_adder", "X") == renamed.replace(
        "totally_unrelated_name_zzz", "X")


def test_no_design_name_keys_in_source():
    """The engine source must not key on any specific design name (chip-agnostic)."""
    src = (PROG / "compose_synth.py").read_text()
    # the recognizers must be operation/interface vocabulary only.
    for forbidden in ("cascaded_adder", "axi_lite_regfile", "brent_kung", "16qam",
                      "mshr", "cvdp_copilot"):
        assert forbidden not in src, f"design-name key leaked into engine: {forbidden}"


# =========================================================================== #
# FUNCTIONAL — host-verify the emit against the harness convention (iverilog-gated)
# o_data == sum(elements), cocotb-measured latency == 2, async-low reset zeroes outputs.
# =========================================================================== #
@pytest.mark.skipif(shutil.which("iverilog") is None or shutil.which("vvp") is None,
                    reason="iverilog/vvp not installed")
def test_emit_functionally_matches_harness():
    rtl = C.solve(_cascade_record())
    assert rtl is not None
    # W=16, N=4, OW=18. The TB mirrors the CVDP cascaded_adder harness:
    #   harness_library packs input_1d = (input_1d<<W)|val (sum is order-independent),
    #   drives i_data/i_valid one cycle, then counts edges to o_valid (expects 2),
    #   and checks o_data == sum. Vectors: DIRECT_MAX (overflow), RANDOM, MIN + reset.
    # Latency reference (matches the cocotb harness): count edges starting from the edge
    # that SAMPLES i_valid (the cocotb harness's `RisingEdge` reference), so a 2-cycle
    # registered wrapper (input reg -> comb -> output reg) measures latency 2. (A loop that
    # only counts edges AFTER deassert reports a value 1 lower than cocotb — a phasing
    # mismatch with the authoritative harness, not a different design.)
    tb = r"""`timescale 1ns/1ps
module tb;
  localparam W=16,N=4,OW=18; reg clk=0,rst_n=0,i_valid=0; reg[W*N-1:0]i_data;
  wire o_valid; wire[OW-1:0]o_data; integer i,latency,errors=0; reg[OW-1:0]golden;
  cascaded_adder #(.IN_DATA_WIDTH(W),.IN_DATA_NS(N)) dut(.clk(clk),.rst_n(rst_n),
    .i_valid(i_valid),.i_data(i_data),.o_valid(o_valid),.o_data(o_data));
  always #5 clk=~clk;
  task gen(input integer m); integer j; reg[W-1:0]v; begin i_data=0;golden=0;
    for(j=0;j<N;j=j+1) begin
      if(m==1) v={W{1'b1}}; else if(m==2) v=0; else v=$random;
      i_data=(i_data<<W)|v; golden=golden+v; end end endtask
  task chk(input integer m); begin
    @(posedge clk);#1;gen(m);i_valid=1;
    @(posedge clk);#1;i_valid=0;   // i_valid sampled at this edge (latency reference)
    latency=1; while(o_valid!==1'b1) begin @(posedge clk);#1;latency=latency+1; end
    if(latency!==2) begin $display("FAIL lat=%0d",latency);errors=errors+1; end
    if(o_data!==golden) begin $display("FAIL data=%h exp=%h",o_data,golden);errors=errors+1; end
  end endtask
  initial begin
    rst_n=1;#3;rst_n=0;#1;
    if(o_valid!==1'b0||o_data!==0)begin $display("FAIL reset0");errors=errors+1;end
    #30;@(negedge clk);rst_n=1;
    for(i=0;i<5;i=i+1) chk(1);     // DIRECT_MAX (overflow)
    for(i=0;i<50;i=i+1) chk(0);    // RANDOM
    for(i=0;i<3;i=i+1) chk(2);     // MIN
    @(negedge clk);rst_n=0;#1;
    if(o_valid!==1'b0||o_data!==0)begin $display("FAIL reset1");errors=errors+1;end
    if(errors==0) $display("ALL_PASS"); else $display("HAD_%0d_FAILS",errors);
    $finish; end
endmodule
"""
    d = tempfile.mkdtemp()
    rf, tf, vf = Path(d) / "dut.sv", Path(d) / "tb.sv", Path(d) / "a.out"
    rf.write_text(rtl)
    tf.write_text(tb)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(vf), str(rf), str(tf)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"iverilog compile failed: {cp.stderr}"
    rp = subprocess.run(["vvp", str(vf)], capture_output=True, text=True)
    assert "ALL_PASS" in rp.stdout, f"functional FAIL: {rp.stdout}"

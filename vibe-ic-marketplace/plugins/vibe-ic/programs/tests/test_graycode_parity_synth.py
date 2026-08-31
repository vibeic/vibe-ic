"""test_graycode_parity_synth.py — the DETERMINISTIC gray-code / parity solver.

graycode_parity_synth.solve(record) reuses record_prompt_context_bridge for the module NAME
(from the prompt) and the port NAMES via extract_interface (prompt+context ONLY —
`### Inputs:`/`### Outputs:` block / skeleton header / test table; NEVER the hidden
harness or golden), then recognizes the gray-conversion / parity OPERATION from the
PROMPT PROSE and emits correct deterministic combinational RTL with parameter-width
buses.

POSITIVES (functionally host-verified via iverilog when available):
  * binary -> gray : gray_out = binary_in ^ (binary_in >> 1), exhaustive for the
    runner's WIDTH parametrize set {4,5}.
  * gray -> binary : binary_out[i] = ^(gray_in >> i), plus the spec's stated
    side-outputs (even parity = ^binary_out, DEBUG_MODE-gated debug_mask =
    ~binary_out), exhaustive for {4,5} with DEBUG_MODE=1.

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * UNSTATED gray direction (only "gray code" mentioned, no b->g vs g->b) -> SKIP.
  * AMBIGUOUS gray direction (BOTH binary->gray and gray->binary claimed) -> SKIP.
  * UNSTATED parity convention (a parity generator with no even/odd word and no
    explicit ^/~^ reduction) -> SKIP — NEVER guess even-vs-odd.
  * AMBIGUOUS parity convention ("even parity" AND "odd parity" both as the
    convention) -> SKIP.
  * UNSTATED width (no WIDTH/N parameter and no literal) -> SKIP (never guess a
    data-path width); this is why the LINT-review variant SKIPs.
  * a composite/protocol design (FIFO/UART/...) -> SKIP.
  * an unexplained side-output on a converter -> SKIP.

CHIP-AGNOSTIC: keyed on operation/interface vocabulary, never a design name. A
renamed copy of a positive solves identically; the guards fire on the SEMANTICS.

The iverilog functional check is GATED on the iverilog binary; the structural /
SKIP assertions run anywhere.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import graycode_parity_synth as G  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# --------------------------------------------------------------------------- #
# faithful CVDP-v1.1.0-shaped record builder (input.prompt + harness .env with
# TOPLEVEL + a cocotb test whose dut.<sig> usage fixes port names+direction).
# output.context is EMPTY in CVDP v1.1.0 — the solver never reads it for logic.
# --------------------------------------------------------------------------- #
def _make_record(top, prompt, cocotb_test, rtl_path=None):
    rtl_path = rtl_path or f"rtl/{top}.sv"
    return {
        "id": f"test_{top}",
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


# ---- positive 1: binary -> gray ------------------------------------------- #
B2G_PROMPT = """Complete the partial SystemVerilog module `binary_to_gray` to implement the
Binary to Gray Code Converter. It translates an N-bit binary input into its
equivalent N-bit Gray code output using combinational logic. The MSB of the Gray
code is the same as the MSB of the binary input; each subsequent Gray code bit is
the XOR of the current and the previous binary bits.

parameter WIDTH = 6

### Inputs:
- `binary_in` [WIDTH-1:0]

### Outputs:
- `gray_out` [WIDTH-1:0]
"""
B2G_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_binary_to_gray(dut):
    WIDTH = int(dut.WIDTH.value)
    for binary in range(2 ** WIDTH):
        dut.binary_in.value = binary
        await Timer(10, unit="ns")
        gray = binary ^ (binary >> 1)
        assert int(dut.gray_out.value) == gray
"""

# ---- positive 2: gray -> binary with stated parity + debug_mask side outs --- #
G2B_PROMPT = """Complete the partial parameterized module `gray_to_binary` to implement the
Gray to Binary Converter that translates a binary-reflected Gray code input into
its equivalent binary output. Parameters: `WIDTH` default = 4, `DEBUG_MODE`
(0 or 1).

Outputs: Binary Output (`binary_out`), Debug Mask (`debug_mask`), Parity (`parity`).
Start with the MSB of binary_out directly from the MSB of gray_in; for each
subsequent bit, cascade XOR the previous binary bit with the current gray bit.
When DEBUG_MODE = 1, generate a debug mask by inverting the `binary_out`; when
DEBUG_MODE = 0 set the debug mask to zero. Compute the even parity of binary_out:
parity = `^binary_out`.

### Inputs:
- `gray_in` [WIDTH-1:0]

### Outputs:
- `binary_out` [WIDTH-1:0]
- `debug_mask` [WIDTH-1:0]
- `parity`
"""
G2B_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_gray_to_binary(dut):
    WIDTH = int(dut.WIDTH.value)
    DEBUG_MODE = int(dut.DEBUG_MODE.value)
    for gray_in in range(2 ** WIDTH):
        dut.gray_in.value = gray_in
        await Timer(1, unit="ns")
        b = 0; prev = 0
        for i in range(WIDTH - 1, -1, -1):
            bit = ((gray_in >> i) & 1) ^ prev; b |= bit << i; prev = bit
        assert int(dut.binary_out.value) == b
        assert int(dut.parity.value) == bin(b).count('1') % 2
        exp_dm = (~b) & ((1 << WIDTH) - 1) if DEBUG_MODE else 0
        assert int(dut.debug_mask.value) == exp_dm
"""

# ---- positive 3: parity GENERATOR, even (chip-agnostic name) --------------- #
PGEN_EVEN_PROMPT = """The module `widget_parity` is an even parity generator. It computes the EVEN
parity of an N-bit data input. parameter WIDTH = 8.
Output `par` is the even parity bit = XOR of all data bits.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `par`
"""
PGEN_EVEN_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_widget_parity(dut):
    WIDTH = int(dut.WIDTH.value)
    for data in range(2 ** WIDTH):
        dut.data_in.value = data
        await Timer(1, unit="ns")
        assert int(dut.par.value) == bin(data).count('1') % 2
"""


# --------------------------------------------------------------------------- #
# iverilog helpers
# --------------------------------------------------------------------------- #
def _iverilog_ok(rtl: str, top: str, tb: str) -> str:
    d = tempfile.mkdtemp()
    try:
        rp = os.path.join(d, f"{top}.sv"); Path(rp).write_text(rtl)
        tp = os.path.join(d, "tb.sv"); Path(tp).write_text(tb)
        out = os.path.join(d, "a.out")
        c = subprocess.run(["iverilog", "-g2012", "-o", out, tp, rp],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}"
        r = subprocess.run(["vvp", out], capture_output=True, text=True)
        return r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# POSITIVES — structural
# --------------------------------------------------------------------------- #
def test_b2g_emits_correct_structure():
    rtl = G.solve(_make_record("binary_to_gray", B2G_PROMPT, B2G_COCOTB))
    assert rtl is not None
    assert "module binary_to_gray" in rtl
    assert "binary_in ^ (binary_in >> 1)" in rtl
    assert "[WIDTH-1:0] binary_in" in rtl and "[WIDTH-1:0] gray_out" in rtl
    assert G.family_of(_make_record("binary_to_gray", B2G_PROMPT, B2G_COCOTB)) == "gray_b2g"


def test_g2b_emits_correct_structure_with_side_outputs():
    rtl = G.solve(_make_record("gray_to_binary", G2B_PROMPT, G2B_COCOTB))
    assert rtl is not None
    assert "module gray_to_binary" in rtl
    assert "^(gray_in >> gp_i)" in rtl                 # cascade XOR, vectorized
    assert "assign parity = ^binary_out" in rtl        # even parity == ^
    assert "DEBUG_MODE ? (~binary_out)" in rtl         # gated debug mask
    assert G.family_of(_make_record("gray_to_binary", G2B_PROMPT, G2B_COCOTB)) == "gray_g2b"


def test_parity_generator_even_emits_xor_reduction():
    rtl = G.solve(_make_record("widget_parity", PGEN_EVEN_PROMPT, PGEN_EVEN_COCOTB))
    assert rtl is not None
    assert "module widget_parity" in rtl
    assert "assign par = ^data_in" in rtl
    assert G.family_of(_make_record("widget_parity", PGEN_EVEN_PROMPT, PGEN_EVEN_COCOTB)) == "parity_gen"


# ---- positive 4: parity GENERATOR, odd ------------------------------------ #
PGEN_ODD_PROMPT = """The module `op` is an ODD parity generator over the N-bit input.
parameter WIDTH = 8. Output `par` is the odd parity bit.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `par`
"""
PGEN_ODD_COCOTB = PGEN_EVEN_COCOTB.replace("widget_parity", "op").replace(
    "count('1') % 2", "(count('1') + 1) % 2")


def test_parity_generator_odd_emits_xnor_reduction():
    rtl = G.solve(_make_record("op", PGEN_ODD_PROMPT, PGEN_ODD_COCOTB))
    assert rtl is not None
    assert "assign par = ~^data_in" in rtl          # odd parity == XNOR of all


# ---- positive 5: parity CHECKER, even ------------------------------------- #
PCHK_EVEN_PROMPT = """The module `pc` is an even parity checker. It takes an N-bit data input and a
received parity_bit and asserts `error` when the EVEN parity is violated.
parameter WIDTH = 8.

### Inputs:
- `data_in` [WIDTH-1:0]
- `parity_bit`

### Outputs:
- `error`
"""
PCHK_EVEN_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_pc(dut):
    WIDTH = int(dut.WIDTH.value)
    dut.data_in.value = 0
    dut.parity_bit.value = 0
    await Timer(1, unit="ns")
    _ = int(dut.error.value)
"""


def test_parity_checker_even_xors_data_and_received_bit():
    rtl = G.solve(_make_record("pc", PCHK_EVEN_PROMPT, PCHK_EVEN_COCOTB))
    assert rtl is not None
    assert "assign error = ^{data_in, parity_bit}" in rtl
    assert G.family_of(_make_record("pc", PCHK_EVEN_PROMPT, PCHK_EVEN_COCOTB)) == "parity_check"


# --------------------------------------------------------------------------- #
# POSITIVES — functional (iverilog), exhaustive for the runner WIDTH set {4,5}
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("W", [4, 5])
def test_b2g_functional(W):
    rtl = G.solve(_make_record("binary_to_gray", B2G_PROMPT, B2G_COCOTB))
    tb = f"""module tb; localparam W={W}; reg [W-1:0] bi; wire [W-1:0] go;
binary_to_gray #(.WIDTH(W)) dut(.binary_in(bi),.gray_out(go));
integer i,err; initial begin err=0;
for(i=0;i<(1<<W);i=i+1) begin bi=i; #1;
 if(go!==(i ^ (i>>1))) err=err+1; end
$display("RESULT %0d",err); $finish; end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "binary_to_gray", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("W", [4, 5])
def test_g2b_functional(W):
    rtl = G.solve(_make_record("gray_to_binary", G2B_PROMPT, G2B_COCOTB))
    tb = f"""module tb; localparam W={W};
reg [W-1:0] gi; wire [W-1:0] bo,dm; wire par;
gray_to_binary #(.WIDTH(W),.DEBUG_MODE(1)) dut(.gray_in(gi),.binary_out(bo),.debug_mask(dm),.parity(par));
integer i,err,k; reg [W-1:0] exp; reg p;
initial begin err=0;
 for(i=0;i<(1<<W);i=i+1) begin gi=i; #1;
  exp=0; exp[W-1]=gi[W-1];
  for(k=W-2;k>=0;k=k-1) exp[k]=exp[k+1]^gi[k];
  p=^exp;
  if(bo!==exp) err=err+1;
  if(par!==p) err=err+1;
  if(dm!==(~exp)) err=err+1;
 end
 $display("RESULT %0d",err); $finish; end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "gray_to_binary", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("W", [4, 8])
def test_parity_gen_even_functional(W):
    rtl = G.solve(_make_record("widget_parity", PGEN_EVEN_PROMPT, PGEN_EVEN_COCOTB))
    tb = f"""module tb; localparam W={W}; reg [W-1:0] d; wire par;
widget_parity #(.WIDTH(W)) dut(.data_in(d),.par(par));
integer i,err; initial begin err=0;
for(i=0;i<(1<<W);i=i+1) begin d=i; #1;
 if(par!==(^d[W-1:0])) err=err+1; end
$display("RESULT %0d",err); $finish; end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "widget_parity", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("W", [4, 6])
def test_parity_checker_even_functional(W):
    rtl = G.solve(_make_record("pc", PCHK_EVEN_PROMPT, PCHK_EVEN_COCOTB))
    tb = f"""module tb; localparam W={W}; reg [W-1:0] d; reg pb; wire er;
pc #(.WIDTH(W)) dut(.data_in(d),.parity_bit(pb),.error(er));
integer i,err; initial begin err=0;
for(i=0;i<(1<<W);i=i+1) begin
 d=i; pb=0; #1; if(er!==(^d)) err=err+1;
 pb=1; #1; if(er!==(^{{d,1'b1}})) err=err+1; end
$display("RESULT %0d",err); $finish; end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "pc", tb)


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVES — each MUST SKIP (return None)
# --------------------------------------------------------------------------- #
UNSTATED_DIR_PROMPT = """The module `code_thing` deals with Gray code values. It processes an N-bit
input and produces an N-bit output. parameter WIDTH = 8.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `data_out` [WIDTH-1:0]
"""  # mentions gray, NEVER states binary->gray vs gray->binary
DIR_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_code_thing(dut):
    WIDTH = int(dut.WIDTH.value)
    dut.data_in.value = 0
    await Timer(1, unit="ns")
    _ = int(dut.data_out.value)
"""


def test_skip_unstated_gray_direction():
    assert G.solve(_make_record("code_thing", UNSTATED_DIR_PROMPT, DIR_COCOTB)) is None


AMBIG_DIR_PROMPT = """The bidirectional codec `gray_codec` performs binary to gray conversion AND
gray to binary conversion depending on a mode. parameter WIDTH = 8. It converts
binary into gray and also converts gray code into binary.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `data_out` [WIDTH-1:0]
"""


def test_skip_ambiguous_gray_direction():
    assert G.solve(_make_record("gray_codec", AMBIG_DIR_PROMPT, DIR_COCOTB)) is None


PGEN_NOSENSE_PROMPT = """The module `p_gen` is a parity generator. It computes a parity bit over the
N-bit data input. parameter WIDTH = 8.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `par`
"""  # parity generator but NO even/odd word and NO explicit ^/~^ expression
PGEN_NOSENSE_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_p_gen(dut):
    WIDTH = int(dut.WIDTH.value)
    dut.data_in.value = 0
    await Timer(1, unit="ns")
    _ = int(dut.par.value)
"""


def test_skip_unstated_parity_convention():
    assert G.solve(_make_record("p_gen", PGEN_NOSENSE_PROMPT, PGEN_NOSENSE_COCOTB)) is None


PGEN_AMBIG_PROMPT = """The module `p_sel` is a parity generator that can produce either even parity
or odd parity. It supports both even parity and odd parity conventions over the
N-bit input. parameter WIDTH = 8.

### Inputs:
- `data_in` [WIDTH-1:0]

### Outputs:
- `par`
"""


def test_skip_ambiguous_parity_convention():
    assert G.solve(_make_record("p_sel", PGEN_AMBIG_PROMPT, PGEN_NOSENSE_COCOTB)) is None


B2G_NOWIDTH_PROMPT = """The module `bg_lint` converts a binary input into its gray code output. Perform
a LINT code review addressing multi-driven signals and unused signals.

### Inputs:
- `binary_in`

### Outputs:
- `gray_out`
"""  # gray b->g, port NAMES stated but NO width parameter / literal anywhere


def test_skip_unstated_width():
    # the direction (b->g) and port names ARE prompt-derivable, but NO WIDTH/N
    # parameter (and no literal) is stated, so the parameter-width guard SKIPs —
    # the solver never guesses a data-path width. (The cocotb harness is OFF-LIMITS
    # oracle the solver never reads, so its content is irrelevant here.)
    rec = _make_record("bg_lint", B2G_NOWIDTH_PROMPT, B2G_COCOTB.replace(
        "test_binary_to_gray", "test_bg_lint"))
    assert G.solve(rec) is None


COMPOSITE_PROMPT = """The module `pkt_fifo` is an asynchronous FIFO with gray-code read/write pointer
synchronization across two clock domains, with even parity protection.
parameter WIDTH = 8.
"""
FIFO_COCOTB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def test_pkt_fifo(dut):
    WIDTH = int(dut.WIDTH.value)
    dut.data_in.value = 0
    await Timer(1, unit="ns")
    _ = int(dut.data_out.value)
"""


def test_skip_composite_design():
    assert G.solve(_make_record("pkt_fifo", COMPOSITE_PROMPT, FIFO_COCOTB)) is None


# --------------------------------------------------------------------------- #
# CHIP-AGNOSTIC — a renamed copy of a positive solves identically
# --------------------------------------------------------------------------- #
def test_chip_agnostic_rename_b2g():
    base = G.solve(_make_record("binary_to_gray", B2G_PROMPT, B2G_COCOTB))
    renamed_prompt = B2G_PROMPT.replace("binary_to_gray", "my_custom_b2g_block")
    renamed_tb = B2G_COCOTB.replace("test_binary_to_gray", "test_my_custom_b2g_block")
    other = G.solve(_make_record("my_custom_b2g_block", renamed_prompt, renamed_tb))
    assert other is not None
    # identical logic, just the module name differs
    assert "binary_in ^ (binary_in >> 1)" in other
    assert other.replace("my_custom_b2g_block", "X") == base.replace("binary_to_gray", "X")


def test_chip_agnostic_parity_even_arbitrary_name():
    prompt = PGEN_EVEN_PROMPT.replace("widget_parity", "zzz_even_par_unit")
    tb = PGEN_EVEN_COCOTB.replace("test_widget_parity", "test_zzz_even_par_unit")
    rtl = G.solve(_make_record("zzz_even_par_unit", prompt, tb))
    assert rtl is not None and "assign par = ^data_in" in rtl


# --------------------------------------------------------------------------- #
# REAL dataset records (gated) — COMPLIANCE invariant (prompt+context ONLY).
#
# The solver now sources the interface EXCLUSIVELY from the model-visible surface
# (`input.prompt` + `input.context`) via the frozen `record_prompt_context_bridge.extract_interface`;
# it NEVER reads the hidden harness (cocotb `dut.<sig>`, `.env`) or golden — those
# are OFF-LIMITS oracle.
#
# In this dataset the two clean converters (`binary_to_gray_0001` /
# `gray_to_binary_0001`) declare their port interface ONLY as an in-prompt
# `module ...(...)` CODE SKELETON inside `input.prompt`, with an EMPTY
# `input.context`. The frozen `extract_interface` parses `input.context` skeletons,
# prose `### Inputs:`/`### Outputs:` blocks, and test-case tables — but NOT an
# in-prompt code skeleton — so those two now HONESTLY SKIP rather than fall back to
# the harness. (This is NOT a runtime regression: `record_prompt_context_bridge.solve` strips
# the harness BEFORE dispatch, so the old cocotb read already returned nothing and
# these records already skipped at runtime; only the non-production direct-call with
# a full record ever "emitted" — via the now-removed OFF-LIMITS harness read.)
#
# The load-bearing NO-CHEAT invariant this pins: sourcing prompt+context ONLY, the
# solver emits for ZERO records across the whole dataset whose interface it can only
# have learned from the harness — i.e. no emit depends on the hidden oracle.
# --------------------------------------------------------------------------- #
DATASET = corpus_path("_extbench/cvdp_open_v110/"
                      "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


@pytest.mark.skipif(not DATASET.exists(), reason="CVDP dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_dataset_compliant_no_harness_sourced_emit():
    import json
    import re
    recs = [json.loads(l) for l in DATASET.open()]
    # prompt+context ONLY: no gray/parity record whose interface lives solely in the
    # hidden harness may emit — the two clean converters (interface only in an
    # in-prompt code skeleton the frozen extractor doesn't parse) HONESTLY SKIP.
    emitted = {r["id"] for r in recs if G.solve(r)}
    assert emitted == set(), f"compliant sourcing must emit for no harness-only record: {emitted}"
    # the two clean converters specifically SKIP (their interface is prompt-visible
    # but only as an in-prompt code skeleton `extract_interface` does not parse).
    by_id = {r["id"]: r for r in recs}
    for tid in ("cvdp_copilot_binary_to_gray_0001", "cvdp_copilot_gray_to_binary_0001"):
        if tid in by_id:
            assert G.solve(by_id[tid]) is None
    # and NO false emit anywhere in the gray/parity-mention set.
    for r in recs:
        p = (r.get("input") or {}).get("prompt") or ""
        if re.search(r"(?i)\bgray\b|\bparity\b", p):
            assert G.solve(r) is None

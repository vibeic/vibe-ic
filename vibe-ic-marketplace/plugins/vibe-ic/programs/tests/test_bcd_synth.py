"""test_bcd_synth.py — the DETERMINISTIC CVDP binary-coded-decimal (BCD) solver.

bcd_synth.solve(record) recognizes a single BCD primitive (BCD adder /
binary->BCD double-dabble / BCD->binary) from the prompt prose, pins the
digit-count/bit-width from the prose or the embedded test-case table (reusing the
shipped record_prompt_context_bridge for the harness TOPLEVEL + interface), and emits the
CORRECT decimal-arithmetic RTL named per TOPLEVEL — NEVER a plain binary add.

POSITIVE (host-verified via iverilog when available):
  * a real-shaped 4-bit BCD adder record solves and is FUNCTIONALLY correct
    (sum=(a+b)%10, cout=(a+b)>=10) across the whole BCD operand domain;
  * a real-shaped 8-bit binary->BCD (double-dabble) record solves and matches the
    double-dabble reference across the whole 8-bit input domain.

§4.05 PARSE-OR-SKIP / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a BCD<->Excess-3 code converter (NOT one of the four BCD primitives);
  * a parity/error-code extra-feature BCD converter (the bare primitive lacks them);
  * a dual-mode bidirectional binary<->BCD converter (ambiguous primitive);
  * a BCD 24-hour counter (sequential, design-specific rollover — not pinned);
  * a binary->BCD record whose bit-width is NOT stated anywhere (width unresolved);
  * a non-BCD record (the solver only fires on BCD designs).

CHIP-AGNOSTIC: the solver keys only on operation/interface vocabulary, never on a
design name. A renamed copy of the positive solves identically and is named per the
(renamed) harness TOPLEVEL.

The iverilog functional check is GATED on the iverilog binary; the structural /
SKIP assertions run anywhere.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import bcd_synth as S  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped CVDP v1.1.0 record fixture builder.
# --------------------------------------------------------------------------- #
def _make_record(top, rtl_path, prompt, cocotb_test):
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


# --------------------------------------------------------------------------- #
# POSITIVE 1 — a faithful 4-bit BCD adder (the real cvdp_copilot_bcd_adder_0001
# shape: a skeleton header pins the 4-bit a/b/sum + 1-bit cout interface, and the
# prose + example table state the +6 decimal-correction operation).
# --------------------------------------------------------------------------- #
BCD_ADDER_PROMPT = """Complete the given partial SystemVerilog code for a Binary coded decimal (BCD)
adder. This BCD adder uses combinational logic to take two 4-bit BCD inputs (a and
b) and produce a 4-bit BCD result (sum). The adder must keep the result within the
valid BCD range (0-9) by adding 6 when the binary sum exceeds 9, and assert cout.

| a       | b       | sum      | cout |
|---------|---------|----------|------|
| 4'b0000 | 4'b0000 | 4'b0000  | 1'b0 |
| 4'b0101 | 4'b1000 | 4'b0011  | 1'b1 |
| 4'b1001 | 4'b1001 | 4'b1000  | 1'b1 |

```verilog
module bcd_adder(
                 input  [3:0] a,
                 input  [3:0] b,
                 output [3:0] sum,
                 output       cout
                );
endmodule
```
"""

BCD_ADDER_COCOTB = """import cocotb
from cocotb.triggers import Timer
import random

@cocotb.test()
async def test_bcd_adder(dut):
    for _ in range(10):
        a_value = random.randint(0, 9)
        b_value = random.randint(0, 9)
        dut.a.value = a_value
        dut.b.value = b_value
        await Timer(10, unit='ns')
        expected_sum = (a_value + b_value) % 10
        expected_cout = 1 if (a_value + b_value) >= 10 else 0
        assert int(dut.sum.value) == expected_sum
        assert int(dut.cout.value) == expected_cout
"""


def _bcd_adder_record(top="bcd_adder"):
    prompt = BCD_ADDER_PROMPT.replace("bcd_adder", top)
    cocotb = BCD_ADDER_COCOTB.replace("bcd_adder", top)
    return _make_record(top, f"rtl/{top}.sv", prompt, cocotb)


# --------------------------------------------------------------------------- #
# POSITIVE 2 — a faithful 8-bit binary->BCD double-dabble (the real
# cvdp_copilot_binary_to_BCD_0001 shape). The skeleton header pins the 8-bit
# binary_in / 12-bit bcd_out interface; the prose names the double-dabble op.
# --------------------------------------------------------------------------- #
BIN2BCD_PROMPT = """Complete the given partial SystemVerilog module `binary_to_bcd` to implement the
Binary to BCD (Binary-Coded Decimal) Converter using the Double Dabble algorithm.
It translates an 8-bit binary input into a 12-bit BCD output using combinational
logic. Before every left shift, add 3 to any BCD digit that is 5 or greater.

```verilog
module binary_to_bcd (
    input  logic [7:0]  binary_in,
    output logic [11:0] bcd_out
    );
endmodule
```
"""

BIN2BCD_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_binary_to_bcd(dut):
    for binary_value in [0, 20, 99, 128, 255]:
        dut.binary_in.value = binary_value
        await Timer(10, unit="ns")
        _ = int(dut.bcd_out.value)
"""


def _bin2bcd_record(top="binary_to_bcd"):
    prompt = BIN2BCD_PROMPT.replace("binary_to_bcd", top)
    cocotb = BIN2BCD_COCOTB.replace("binary_to_bcd", top)
    return _make_record(top, f"rtl/{top}.sv", prompt, cocotb)


# Lint-review variant (real cvdp_copilot_binary_to_BCD_0036): NO skeleton header
# and NO table — the interface is declared in a prompt-side `### Inputs:`/`### Outputs:`
# block (the ONLY model-visible surface), with explicit bit ranges. extract_interface
# resolves the names+widths from the prompt; the cocotb harness is OFF-LIMITS oracle
# the solver never reads.
BIN2BCD_LINT_PROMPT = """The `binary_to_bcd` module converts an 8-bit binary input into a 12-bit BCD
(Binary-Coded Decimal) output using the Double Dabble algorithm. Perform a LINT
code review and provide clean RTL without Lint errors.

### Inputs:
- `binary_in` [7:0]

### Outputs:
- `bcd_out` [11:0]
"""

BIN2BCD_LINT_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_binary_to_bcd(dut):
    for binary_value in [0, 99, 255]:
        dut.binary_in.value = binary_value
        await Timer(10, unit="ns")
        _ = int(dut.bcd_out.value)
"""


def _bin2bcd_lint_record(top="binary_to_bcd"):
    return _make_record(top, f"rtl/{top}.sv", BIN2BCD_LINT_PROMPT, BIN2BCD_LINT_COCOTB)


# --------------------------------------------------------------------------- #
# Structural positives
# --------------------------------------------------------------------------- #
def test_bcd_adder_solves_and_names_per_toplevel():
    rtl = S.solve(_bcd_adder_record())
    assert rtl is not None
    assert re.search(r"\bmodule\s+bcd_adder\b", rtl)
    assert S.variant_of(_bcd_adder_record()) == "bcd_adder"
    # NO-CHEAT: must NOT be a plain binary add; the +6 decimal correction is present.
    assert "4'd6" in rtl and ">" in rtl


def test_bin2bcd_solves_double_dabble_widths():
    rtl = S.solve(_bin2bcd_record())
    assert rtl is not None
    assert re.search(r"\bmodule\s+binary_to_bcd\b", rtl)
    assert S.variant_of(_bin2bcd_record()) == "bin2bcd"
    assert re.search(r"input\s+\[7:0\]\s+binary_in", rtl)
    assert re.search(r"output reg \[11:0\]\s+bcd_out", rtl)
    # double-dabble: the +3 adjust and a 20-bit shift register (12 BCD + 8 binary).
    assert "4'd3" in rtl and re.search(r"reg \[19:0\]\s+shift_reg", rtl)


def test_bin2bcd_lint_variant_pins_widths_from_prose():
    """No skeleton header / no table — width must be pinned from prose, BCD=12."""
    rec = _bin2bcd_lint_record()
    rtl = S.solve(rec)
    assert rtl is not None
    assert re.search(r"input\s+\[7:0\]\s+binary_in", rtl)
    assert re.search(r"output reg \[11:0\]\s+bcd_out", rtl)


# --------------------------------------------------------------------------- #
# §4.05 PARSE-OR-SKIP / NO-CHEAT negatives — each MUST return None.
# --------------------------------------------------------------------------- #
EXCESS3 = """Design a BCD to Excess-3 Code Converter that translates a 4-bit Binary-Coded
Decimal (BCD) input `bcd` into a corresponding 4-bit Excess-3 output `excess3`,
asserting an `error` flag on invalid BCD. Combinational.
"""
EXCESS3_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.bcd.value = 0
    _ = int(dut.excess3.value)
    _ = int(dut.error.value)
"""

PARITY = """Improve the `bcd_to_binary` module to incorporate parity calculation and an
error_code [1:0] reporting invalid BCD input alongside the converted value.
"""
PARITY_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.bcd.value = 0
"""

TWOWAY = """Enhance the binary-to-BCD converter by adding support for both binary-to-BCD and
BCD-to-binary conversions. A 1-bit input `switch` selects the conversion mode.
Inputs binary_in and bcd_in, outputs binary_out and bcd_out.
"""
TWOWAY_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.switch.value = 1
"""

COUNTER = """Design a module `bcd_counter` that implements a 24-hour clock using BCD counters
displaying hours, minutes and seconds (00:00:00 to 23:59:59), with clk and rst.
"""
COUNTER_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.clk.value = 0
    dut.rst.value = 1
"""

# binary->BCD but with NO stated bit-width anywhere -> width unresolved -> SKIP.
NOWIDTH = """Implement a binary to BCD converter `binary_to_bcd` using the Double Dabble
algorithm. It converts the binary input into a BCD output.
"""
NOWIDTH_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.binary_in.value = 5
    _ = int(dut.bcd_out.value)
"""

# Not a BCD design at all -> the solver must not fire.
NON_BCD = """Design a 4-bit binary up counter `counter` with clk and rst that increments each
clock cycle and wraps at 15.
"""
NON_BCD_TB = """import cocotb
@cocotb.test()
async def test_x(dut):
    dut.clk.value = 0
"""


@pytest.mark.parametrize("top,prompt,tb", [
    ("bcd_to_excess_3", EXCESS3, EXCESS3_TB),
    ("bcd_to_binary", PARITY, PARITY_TB),
    ("binary_bcd_converter_twoway", TWOWAY, TWOWAY_TB),
    ("bcd_counter", COUNTER, COUNTER_TB),
    ("binary_to_bcd", NOWIDTH, NOWIDTH_TB),
    ("counter", NON_BCD, NON_BCD_TB),
])
def test_section_4_05_skips(top, prompt, tb):
    rec = _make_record(top, f"rtl/{top}.sv", prompt, tb)
    assert S.solve(rec) is None, f"{top} must SKIP (§4.05 parse-or-skip)"
    assert S.variant_of(rec) is None


def test_no_record_no_emit():
    assert S.solve(None) is None
    assert S.solve({}) is None
    # a record with no harness TOPLEVEL cannot be named -> SKIP.
    assert S.solve({"input": {"prompt": "a BCD adder, 4-bit"}}) is None


# --------------------------------------------------------------------------- #
# CHIP-AGNOSTIC — a renamed positive solves identically (keyed on semantics, not
# the design name) and is named per the renamed harness TOPLEVEL.
# --------------------------------------------------------------------------- #
def test_chip_agnostic_rename_solves_identically():
    base = S.solve(_bcd_adder_record("bcd_adder"))
    renamed = S.solve(_bcd_adder_record("decimal_digit_adder_xyz"))
    assert base is not None and renamed is not None
    assert re.search(r"\bmodule\s+decimal_digit_adder_xyz\b", renamed)
    # structurally identical apart from the module name.
    assert base.replace("bcd_adder", "X") == renamed.replace("decimal_digit_adder_xyz", "X")


def test_chip_agnostic_no_design_name_keys_in_source():
    """The solver source must not hard-code any specific CVDP design name."""
    src = (PROG / "bcd_synth.py").read_text()
    for banned in ("bcd_adder_0001", "binary_to_BCD", "cvdp_copilot", "brent_kung"):
        assert banned not in src, f"design-name key {banned!r} leaked into the solver"


# --------------------------------------------------------------------------- #
# iverilog functional oracle (GATED on the iverilog binary).
# --------------------------------------------------------------------------- #
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")
_HAVE_SIM = bool(_IVERILOG and _VVP)


def _run_sim(rtl, tb):
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.v"
        tbf = Path(d) / "tb.v"
        sim = Path(d) / "sim"
        dut.write_text(rtl)
        tbf.write_text(tb)
        c = subprocess.run([_IVERILOG, "-g2012", "-o", str(sim), str(dut), str(tbf)],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"iverilog compile failed:\n{c.stderr}"
        r = subprocess.run([_VVP, str(sim)], capture_output=True, text=True)
        return r.stdout


@pytest.mark.skipif(not _HAVE_SIM, reason="iverilog/vvp not installed")
def test_bcd_adder_functional_oracle():
    rtl = S.solve(_bcd_adder_record())
    tb = """module tb;
  reg [3:0] a,b; wire [3:0] sum; wire cout; integer i,j,errs;
  bcd_adder u(.a(a),.b(b),.sum(sum),.cout(cout));
  initial begin errs=0;
    for(i=0;i<=9;i=i+1) for(j=0;j<=9;j=j+1) begin
      a=i;b=j;#1;
      if(sum!==((i+j)%10) || cout!==((i+j)>=10?1:0)) errs=errs+1; end
    $display("ERRS %0d", errs); end endmodule"""
    out = _run_sim(rtl, tb)
    m = re.search(r"ERRS (\d+)", out)
    assert m and m.group(1) == "0", f"BCD adder functional mismatch: {out}"


@pytest.mark.skipif(not _HAVE_SIM, reason="iverilog/vvp not installed")
def test_bin2bcd_functional_oracle():
    rtl = S.solve(_bin2bcd_record())
    # double-dabble reference inside the TB; sweep the whole 8-bit input domain.
    tb = """module tb;
  reg [7:0] bin; wire [11:0] bcd; integer v,errs; reg [11:0] exp;
  binary_to_bcd u(.binary_in(bin),.bcd_out(bcd));
  function [11:0] ref_dd; input [7:0] b; integer i,nib; reg [19:0] sr; begin
    sr={12'd0,b};
    for(i=0;i<8;i=i+1) begin
      for(nib=0;nib<3;nib=nib+1) if(sr[8+nib*4 +:4]>=5) sr[8+nib*4 +:4]=sr[8+nib*4 +:4]+3;
      sr=sr<<1; end
    ref_dd=sr[19:8]; end endfunction
  initial begin errs=0;
    for(v=0;v<=255;v=v+1) begin bin=v[7:0]; #1; exp=ref_dd(v[7:0]);
      if(bcd!==exp) errs=errs+1; end
    $display("ERRS %0d", errs); end endmodule"""
    out = _run_sim(rtl, tb)
    m = re.search(r"ERRS (\d+)", out)
    assert m and m.group(1) == "0", f"binary->BCD functional mismatch: {out}"

"""test_gf_synth.py — the DETERMINISTIC CVDP Galois-field / carry-less
multiply family solver.

gf_synth.solve(record) recognizes a GF(2^n) / carry-less polynomial multiply
(or GF multiply-accumulate), PARSES the field width n and the irreducible polynomial
from the PROMPT PROSE, and emits a combinational carry-less-multiply-then-reduce
datapath (module named per the harness TOPLEVEL, ports from the bridge's interface
extraction). It NEVER reads the golden RTL and NEVER emits integer `A*B`.

POSITIVE: a real-shaped GF(2^4) multiplier (x^4+x+1) program-SOLVES, and the emit is
FUNCTIONALLY correct — a HAND-COMPUTED GF product (3 ⊗ 7 = 9 in GF(2^4) mod x^4+x+1)
is asserted both in Python (cross-check of the reference math) and against the
emitted RTL via iverilog (when the binary is available).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a GF multiplier whose polynomial / field is NOT stated (never guess a poly);
  * a GF *inverse* (a different extended-Euclid / table datapath — not a plain mult);
  * a GF s-box / a clocked crypto FSM / an LFSR (polynomial present but not a
    plain combinational multiply).

CHIP-AGNOSTIC: the solver keys only on GF semantics + the parsed poly/field, never on
a design name. A renamed copy of the positive solves identically.

The iverilog functional check is GATED on the iverilog binary; the Python hand-computed
GF assertion + structural / SKIP assertions run anywhere.
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

import gf_synth as G  # noqa: E402

_IVERILOG = shutil.which("iverilog") and shutil.which("vvp")


# --------------------------------------------------------------------------- #
# Record fixture (faithful to CVDP v1.1.0: input.prompt + output.context[rtl]
# EMPTY + harness.files .env carrying TOPLEVEL + a cocotb test_*.py).
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


# A pure-Python GF reference: carry-less multiply then reduce mod the full poly.
def _gf_ref(a, b, poly_full, n):
    p = 0
    bb = b
    while bb:
        if bb & 1:
            p ^= a
        a <<= 1
        bb >>= 1
    for i in range(2 * n - 1, n - 1, -1):
        if p & (1 << i):
            p ^= poly_full << (i - n)
    return p & ((1 << n) - 1)


# --------------------------------------------------------------------------- #
# POSITIVE: a GF(2^4) multiplier (x^4 + x + 1 = 5'b10011).
# --------------------------------------------------------------------------- #
GF4_PROMPT = """Design the SystemVerilog module `gf_multiplier` for a 4-bit Galois Field
Multiplier (GF(2^4)) by utilizing the irreducible polynomial x^4 + x + 1. The
multiplication is between two 4-bit values to result in a 4-bit product output.

#### Inputs:
- A ([3:0], 4-bit): The multiplicand.
- B ([3:0], 4-bit): The multiplier.
#### Output:
- result ([3:0], 4-bit): The product using the GF multiplication algorithm.

Polynomial Reduction: the irreducible polynomial x^4 + x + 1 (represented as
`5'b10011`) is used for reduction on overflow during multiplication.
"""

GF4_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_gf_multiplier(dut):
    dut.A.value = 0
    dut.B.value = 0
    await Timer(10, unit="ns")
    _ = int(dut.result.value)
"""


def _gf4_record(top="gf_multiplier"):
    prompt = GF4_PROMPT.replace("gf_multiplier", top)
    cocotb = GF4_COCOTB.replace("gf_multiplier", top)
    return _make_record(top, f"rtl/{top}.sv", prompt, cocotb)


def test_python_gf_reference_hand_computed():
    """The reference GF math: in GF(2^4) mod x^4+x+1, the textbook product
    3 ⊗ 7 = 9, and 15 ⊗ 15 = 10. Pin the reference (the emit is checked against it)."""
    poly = 0b10011  # x^4 + x + 1
    assert _gf_ref(3, 7, poly, 4) == 9
    assert _gf_ref(15, 15, poly, 4) == 10
    # AES field GF(2^8) mod 0x11B: the canonical 0x57 ⊗ 0x83 = 0xC1, 0x57 ⊗ 0x13 = 0xFE.
    assert _gf_ref(0x57, 0x83, 0x11B, 8) == 0xC1
    assert _gf_ref(0x57, 0x13, 0x11B, 8) == 0xFE


def test_gf4_solves_and_parses_field_and_poly():
    rec = _gf4_record()
    rtl = G.solve(rec)
    assert rtl is not None, "GF(2^4) multiplier with stated poly must SOLVE"
    assert "module gf_multiplier" in rtl
    # the parsed irreducible polynomial appears as the full 5-bit literal
    assert "5'b10011" in rtl
    # NO-CHEAT: never a plain-integer multiply
    assert "A * B" not in rtl and "a * b" not in rtl and "A*B" not in rtl
    # parse helper returns (n=4, poly=0b10011)
    n, poly = G.parse_field_and_poly(rec["input"]["prompt"], 4)
    assert n == 4 and poly == 0b10011


def test_gf4_chip_agnostic_rename_solves_identically():
    """Keyed on GF semantics + parsed poly, not on a design name."""
    base = G.solve(_gf4_record("gf_multiplier"))
    renamed = G.solve(_gf4_record("poly_mult_unit"))
    assert base is not None and renamed is not None
    assert "module poly_mult_unit" in renamed
    # bodies identical modulo the module name
    assert base.replace("gf_multiplier", "X") == renamed.replace("poly_mult_unit", "X")


@pytest.mark.skipif(not _IVERILOG, reason="iverilog/vvp not installed")
def test_gf4_emitted_rtl_functionally_correct_via_iverilog():
    """The emitted RTL matches the hand-computed GF product 3 ⊗ 7 = 9 (and the
    full GF(2^4) truth table) under iverilog."""
    rtl = G.solve(_gf4_record())
    assert rtl is not None
    poly = 0b10011
    d = Path(tempfile.mkdtemp())
    (d / "gf_multiplier.sv").write_text(rtl)
    # exhaustive GF(2^4) table check + the hand-computed 3⊗7=9 vector
    lines = ["module tb; reg [3:0] A,B; wire [3:0] R;",
             "gf_multiplier dut(.A(A),.B(B),.result(R));",
             "integer fails=0;", "initial begin"]
    for x in range(16):
        for y in range(16):
            e = _gf_ref(x, y, poly, 4)
            lines.append(f"  A=4'd{x}; B=4'd{y}; #1; "
                         f"if(R!==4'd{e}) fails=fails+1;")
    lines.append('  if(fails==0) $display("ALLPASS"); else $display("FAILS=%0d",fails);')
    lines.append("end endmodule")
    (d / "tb.sv").write_text("\n".join(lines))
    sim = d / "sim"
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(sim),
                         str(d / "gf_multiplier.sv"), str(d / "tb.sv")],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"compile failed: {cp.stderr}"
    rp = subprocess.run(["vvp", str(sim)], capture_output=True, text=True)
    assert "ALLPASS" in rp.stdout, f"GF(2^4) table mismatch: {rp.stdout}"


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE 1: polynomial / field NOT stated -> SKIP (never guess a poly).
# --------------------------------------------------------------------------- #
NO_POLY_PROMPT = """Design the SystemVerilog module `gf_multiplier`, a Galois Field
carry-less multiplier. The multiplication is between two 4-bit values A and B to
produce a 4-bit product `result`. Reduce any overflow with the field's irreducible
polynomial.

#### Inputs:
- A ([3:0], 4-bit): The multiplicand.
- B ([3:0], 4-bit): The multiplier.
#### Output:
- result ([3:0], 4-bit): The GF product.
"""


def test_no_polynomial_stated_skips():
    """GF family but the irreducible polynomial is never given — SKIP, never guess."""
    rec = _make_record("gf_multiplier", "rtl/gf_multiplier.sv",
                       NO_POLY_PROMPT, GF4_COCOTB)
    assert G.solve(rec) is None
    # and the parse helper itself refuses (no degree-4 poly literal/algebra present)
    assert G.parse_field_and_poly(NO_POLY_PROMPT, 4) is None


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE 2: a GF *inverse* -> SKIP (different datapath, not a plain mult).
# --------------------------------------------------------------------------- #
GF_INVERSE_PROMPT = """Design the SystemVerilog module `gf_inverter` that computes the
multiplicative INVERSE of an element in GF(2^8) using the irreducible polynomial
x^8 + x^4 + x^3 + x + 1 (0x11B). For input `a`, output `inv` is the field element
such that a ⊗ inv = 1.

#### Inputs:
- a ([7:0], 8-bit): The field element.
#### Output:
- inv ([7:0], 8-bit): The multiplicative inverse of `a`.
"""

GF_INVERSE_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_gf_inverter(dut):
    dut.a.value = 1
    await Timer(10, unit="ns")
    _ = int(dut.inv.value)
"""


def test_gf_inverse_skips():
    """A GF multiplicative INVERSE is not a plain GF multiply — SKIP."""
    rec = _make_record("gf_inverter", "rtl/gf_inverter.sv",
                       GF_INVERSE_PROMPT, GF_INVERSE_COCOTB)
    assert G.solve(rec) is None


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE 3: an LFSR with a polynomial -> SKIP (sequential PRNG, not mult).
# --------------------------------------------------------------------------- #
LFSR_PROMPT = """Design an 8-bit Galois-configuration LFSR with the primitive polynomial
x^8 + x^6 + x^5 + x + 1. With a clock `clk`, asynchronous reset `rst`, and an 8-bit
seed, generate an 8-bit pseudo-random `lfsr_out` on every positive clock edge.
"""

LFSR_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_lfsr_8bit(dut):
    dut.clk.value = 0
    dut.rst.value = 0
    dut.seed.value = 1
    await Timer(10, unit="ns")
    _ = int(dut.lfsr_out.value)
"""


def test_lfsr_skips():
    """A clocked LFSR is a sequential PRNG keyed by a polynomial — not a GF multiply."""
    rec = _make_record("lfsr_8bit", "rtl/lfsr_8bit.sv", LFSR_PROMPT, LFSR_COCOTB)
    assert G.solve(rec) is None


# --------------------------------------------------------------------------- #
# Non-GF design -> not the family at all -> SKIP (the synth fires only on GF).
# --------------------------------------------------------------------------- #
def test_plain_adder_not_gf_family_skips():
    ADDER = """Design the module `adder` computing sum = a + b. Inputs a ([7:0]),
b ([7:0]); output sum ([7:0])."""
    ADDER_TB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_adder(dut):
    dut.a.value = 0
    dut.b.value = 0
    await Timer(10, unit="ns")
    _ = int(dut.sum.value)
"""
    rec = _make_record("adder", "rtl/adder.sv", ADDER, ADDER_TB)
    assert G.solve(rec) is None

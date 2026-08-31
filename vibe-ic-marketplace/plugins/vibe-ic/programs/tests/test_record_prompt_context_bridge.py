"""Generic visible prompt/context record bridge tests.

record_prompt_context_bridge.solve(record) reads the module name from the harness TOPLEVEL,
extracts the interface from the BEST available CVDP source (skeleton header /
cocotb dut.<sig> / test-case table / prose), builds a clean port block, prepends
it to the ORIGINAL prompt prose, and routes through spec_artifact_registry —
emitting RTL named per TOPLEVEL when a deterministic canonical fires, else SKIP.

POSITIVE: a real-shaped 32-bit adder record (the Brent-Kung problem, functionally
sum=a+b+carry_in) program-SOLVES, and the emit is FUNCTIONALLY correct against the
prompt's own test-case-table vectors (host-verified via iverilog when available).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a Galois-field multiplier (NOT result=A*B — a plain-integer emit would be
    functionally WRONG; the special-algebra guard catches it);
  * an AXI bus controller (composite, not a single atomic function);
  * a sequential accumulator (clk/reset, registry has no plain combinational emit);
  * a record with no extractable interface.

CHIP-AGNOSTIC: the bridge keys only on operation/interface vocabulary, never on a
design name. A renamed copy of the positive solves identically; the guards fire on
the SEMANTICS, not the module name.

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

import record_prompt_context_bridge as B  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped record fixtures (faithful to CVDP v1.1.0 record structure:
# input.prompt + input.context + output.context[<rtl path>] + harness.files
# with a .env carrying TOPLEVEL + a cocotb test_*.py). output.context is EMPTY
# in CVDP v1.1.0 — the bridge never reads it for logic regardless.
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


# A faithful 32-bit adder (Brent-Kung style): a markdown test-case table fixes the
# interface + widths (8 hex digits => 32-bit a/b/sum; carry_in/carry_out 1-bit) and
# the cocotb test drives a/b/carry_in and reads sum/carry_out.
ADDER_PROMPT = """The 32-bit Brent-Kung Adder module `brent_kung_adder` performs parallel binary
addition. Below is a table showing the expected values for key outputs:

| Test case | a        | b        | carry_in | Expected Sum | Expected carry_out |
|-----------|----------|----------|----------|--------------|--------------------|
| 1         | 00000000 | 00000000 | 0        | 00000000     | 0                  |
| 2         | FFFFFFFF | 00000001 | 0        | 00000000     | 1                  |
| 3         | 12345678 | 87654321 | 1        | 9999999A     | 0                  |

Identify and Fix the RTL Bug(s) to ensure the correct behaviour of the adder.
"""

ADDER_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_brent_kung_adder(dut):
    vectors = [
        (0x00000000, 0x00000000, 0, 0x00000000, 0),
        (0xFFFFFFFF, 0x00000001, 0, 0x00000000, 1),
        (0x12345678, 0x87654321, 1, 0x9999999A, 0),
    ]
    for a, b, carry_in, exp_sum, exp_co in vectors:
        dut.a.value = a
        dut.b.value = b
        dut.carry_in.value = carry_in
        await Timer(10, unit="ns")
        actual_sum = int(dut.sum.value)
        actual_co = int(dut.carry_out.value)
        assert actual_sum == exp_sum
        assert actual_co == exp_co
"""


def _adder_record(top="brent_kung_adder"):
    prompt = ADDER_PROMPT.replace("brent_kung_adder", top)
    cocotb = ADDER_COCOTB.replace("brent_kung_adder", top)
    return _make_record(top, f"rtl/{top}.sv", prompt, cocotb)


# A Galois-field multiplier — result is GF(2^4) carry-less multiply mod an
# irreducible polynomial, NOT result = A * B. A plain-integer emit would be WRONG.
GF_PROMPT = """Design the SystemVerilog module `gf_multiplier` for a 4-bit Galois Field
Multiplier (GF(2^4)) using the irreducible polynomial x^4 + x + 1. The
multiplication is between two 4-bit values to result in a 4-bit product.

#### Inputs:
- A ([3:0], 4-bit): The multiplicand.
- B ([3:0], 4-bit): The multiplier.
#### Output:
- result ([3:0], 4-bit): The product using the GF multiplication algorithm.

Polynomial Reduction: the irreducible polynomial is used for reduction on overflow.
"""

GF_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_gf_mult(dut):
    dut.A.value = 0
    dut.B.value = 0
    await Timer(10, unit="ns")
    _ = int(dut.result.value)
"""


def _gf_record():
    return _make_record("gf_multiplier", "rtl/gf_multiplier.sv", GF_PROMPT, GF_COCOTB)


# An AXI register controller — composite, not a single atomic function.
AXI_PROMPT = """Implement the `axi_register` module: an AXI-Lite slave with write-address,
write-data, write-response, read-address and read-data channels. It exposes a
register file over the AXI handshake (awvalid/awready, wvalid/wready, ...).
"""

AXI_COCOTB = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_axi_register(dut):
    dut.awaddr_i.value = 0
    dut.awvalid_i.value = 0
    dut.wdata_i.value = 0
    await Timer(10, unit="ns")
    _ = int(dut.rdata_o.value)
"""


def _axi_record():
    return _make_record("axi_register", "rtl/axi_register.sv", AXI_PROMPT, AXI_COCOTB)


# A sequential accumulator — clk/reset registered cumulative sum; the registry has
# no plain combinational emit for a stateful accumulator.
ACC_PROMPT = """The `cascaded_adder` module performs the cumulative sum of multiple input
data elements, synchronized to the clock, with asynchronous reset. The input is a
flattened 1D vector; the output provides the accumulated sum over clocked cycles.
"""

ACC_COCOTB = """import cocotb
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def test_cascaded_adder(dut):
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_data.value = 0
    await Timer(10, unit="ns")
    _ = int(dut.o_data.value)
"""


def _acc_record():
    return _make_record("cascaded_adder", "rtl/cascaded_adder.sv", ACC_PROMPT, ACC_COCOTB)


# =========================================================================== #
# POSITIVE — the adder program-SOLVES and binds to the TOPLEVEL
# =========================================================================== #
def test_adder_solves_and_names_per_toplevel():
    rec = _adder_record()
    rtl = B.solve(rec)
    assert rtl is not None, "the 32-bit adder must program-SOLVE"
    assert "module brent_kung_adder" in rtl, "module must be named per harness TOPLEVEL"
    # functional structure: sum = a + b + carry_in (the registry's canonical adder)
    assert "a + b + carry_in" in rtl.replace("  ", " ")
    assert B.family_of(rec) == "arithmetic"


def test_adder_interface_extracted_from_table_and_cocotb():
    ins, outs = B.extract_interface(_adder_record(), "brent_kung_adder")
    iw = dict(ins)
    ow = dict(outs)
    assert iw.get("a") == 32 and iw.get("b") == 32 and iw.get("carry_in") == 1
    assert ow.get("sum") == 32 and ow.get("carry_out") == 1


def test_toplevel_name_from_env():
    assert B.toplevel_name(_adder_record()) == "brent_kung_adder"
    assert B.toplevel_name({"harness": {"files": {}}}) is None


# =========================================================================== #
# §4.05 / NO-CHEAT NEGATIVES — each MUST SKIP
# =========================================================================== #
def test_galois_field_multiplier_solved_correctly_not_plain_mult():
    # GF multiply is NOT result=A*B. The registry's plain `*` would be a functional
    # LIE — so the bridge's special-algebra guard SKIPs the registry path, and the
    # gf_synth FAMILY solver now emits the CORRECT carry-less-multiply-then-
    # reduce datapath (parsed irreducible polynomial), NEVER a plain integer multiply.
    rtl = B.solve(_gf_record())
    assert rtl is not None
    assert "A * B" not in rtl and "A*B" not in rtl and "a * b" not in rtl
    assert "10011" in rtl   # the parsed poly drives the GF reduction (no fabrication)


def test_axi_composite_skips():
    assert B.solve(_axi_record()) is None


def test_sequential_accumulator_skips():
    assert B.solve(_acc_record()) is None


def test_no_interface_skips():
    # a record with no extractable interface (no skeleton header, no parseable
    # cocotb IO, no prose ports) MUST skip.
    rec = _make_record("mystery", "rtl/mystery.sv",
                       "Design a mystery block that does something complex.",
                       "import cocotb\n")
    assert B.solve(rec) is None


def test_never_reads_golden_rtl_body():
    # Even if output.context were (wrongly) populated with a reference body, the
    # bridge must NOT copy its logic — it parses ONLY a module HEADER. Put a
    # populated body whose header DOES match: only the declared ports may be used,
    # never the `assign secret` body line.
    rec = _adder_record()
    rec["output"]["context"]["rtl/brent_kung_adder.sv"] = (
        "module brent_kung_adder(input [31:0] a, input [31:0] b, "
        "input carry_in, output [31:0] sum, output carry_out);\n"
        "  assign sum = 32'hDEADBEEF; // golden secret — must NOT be copied\n"
        "  assign carry_out = 1'b1;\nendmodule\n"
    )
    rtl = B.solve(rec)
    assert rtl is not None
    assert "DEADBEEF" not in rtl, "must never copy the reference body logic"
    assert "a + b + carry_in" in rtl.replace("  ", " ")


# =========================================================================== #
# CHIP-AGNOSTIC — behavior keys on semantics, never on a design name
# =========================================================================== #
def test_chip_agnostic_rename_solves_identically():
    base = B.solve(_adder_record("brent_kung_adder"))
    renamed = B.solve(_adder_record("totally_different_name_xyz"))
    assert base is not None and renamed is not None
    assert "module totally_different_name_xyz" in renamed
    # body logic identical modulo the module name
    assert base.replace("brent_kung_adder", "X") == \
        renamed.replace("totally_different_name_xyz", "X")


def test_chip_agnostic_guard_fires_on_semantics_not_name():
    # rename the GF multiplier to an innocuous name: it must STILL be GF-solved
    # (keyed on the "Galois field / irreducible polynomial" semantics, never the
    # name), emitting the correct GF datapath under the TOPLEVEL name — not a plain
    # integer multiply.
    rec = _make_record("plain_mult", "rtl/plain_mult.sv",
                       GF_PROMPT.replace("gf_multiplier", "plain_mult"),
                       GF_COCOTB.replace("gf_mult", "plain_mult"))
    rtl = B.solve(rec)
    assert rtl is not None and "module plain_mult" in rtl
    assert "A * B" not in rtl and "A*B" not in rtl   # GF, never plain multiply


# =========================================================================== #
# FUNCTIONAL — host-verify the emit against the table vectors (iverilog-gated)
# =========================================================================== #
@pytest.mark.skipif(shutil.which("iverilog") is None or shutil.which("vvp") is None,
                    reason="iverilog/vvp not installed")
def test_adder_emit_functionally_passes_table_vectors():
    rec = _adder_record()
    rtl = B.solve(rec)
    assert rtl is not None
    # drive the prompt's test-case-table vectors and check expected outputs.
    vectors = [
        (0x00000000, 0x00000000, 0, 0x00000000, 0),
        (0xFFFFFFFF, 0x00000001, 0, 0x00000000, 1),
        (0x12345678, 0x87654321, 1, 0x9999999A, 0),
    ]
    body = []
    for ri, (a, b, ci, es, eco) in enumerate(vectors):
        body += [f"    a = 32'd{a}; b = 32'd{b}; carry_in = 1'd{ci}; #10;",
                 f"    if (sum !== 32'd{es}) errors = errors + 1;",
                 f"    if (carry_out !== 1'd{eco}) errors = errors + 1;"]
    tb = (
        "`timescale 1ns/1ps\nmodule tb;\n"
        "  reg [31:0] a, b; reg carry_in;\n"
        "  wire [31:0] sum; wire carry_out;\n"
        "  integer errors = 0;\n"
        "  brent_kung_adder dut(.a(a), .b(b), .carry_in(carry_in), "
        ".sum(sum), .carry_out(carry_out));\n"
        "  initial begin\n" + "\n".join(body) + "\n"
        "    if (errors == 0) $display(\"ALL_PASS\"); else "
        "$display(\"HAD_%0d_FAILS\", errors);\n    $finish;\n  end\nendmodule\n"
    )
    d = tempfile.mkdtemp()
    rf, tf, vf = Path(d) / "dut.sv", Path(d) / "tb.sv", Path(d) / "a.out"
    rf.write_text(rtl)
    tf.write_text(tb)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(vf), str(rf), str(tf)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"iverilog compile failed: {cp.stderr}"
    rp = subprocess.run(["vvp", str(vf)], capture_output=True, text=True)
    assert "ALL_PASS" in rp.stdout, f"functional FAIL: {rp.stdout}"

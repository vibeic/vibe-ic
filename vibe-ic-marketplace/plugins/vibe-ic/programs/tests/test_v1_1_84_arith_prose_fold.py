"""v1.1.84 — RTLLM-prose dialect FOLDED into arithmetic_synth (combinational shapes).

arithmetic_synth.synth now tries the VE-phrasing forms first, then falls back to the
RTLLM-prose dialect (comparator / ALU / accumulator / fixed-point / combinational
multiplier / divider / separate-sum-cout adder), reading ports through the prose
bridge. Every emitted fact is PARSED from the prose; an unstated fact SKIPs (§4.05).

DEFERRED (audit H1/H2/M3 — guessed latency / pipeline stages): the sequential-
multiplier (mult_seq_*) and pipelined (mult_pipe_*, adder_pipe) shapes SKIP here until
the parse-the-stated-cycle-count remediation lands — an honest SKIP, never a guess.

Host-verify is GATED on iverilog + the RTLLM dataset; the structural assertions + the
deferred-SKIP guard run anywhere.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import arithmetic_synth as A  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_RT = corpus_path("_extbench/RTLLM")

# a real RTLLM-prose comparator (structured form the VE solver doesn't phrase)
CMP = """
Implement a 3-bit comparator.
Module name:
    comparator_3bit
Input ports:
    A: 3-bit input operand.
    B: 3-bit input operand.
Output ports:
    A_greater: high when A > B.
    A_equal: high when A == B.
    A_less: high when A < B.
"""


def test_prose_comparator_fires_general():
    rtl = A.synth(CMP, "comparator_3bit")
    assert rtl is not None
    assert ">" in rtl and "==" in rtl and "<" in rtl


def test_deferred_seq_multiplier_skips():
    # a sequential multiplier with a clk + done handshake whose completion cycle is
    # not parsed must SKIP (DEFERRED), never emit a guessed-latency machine.
    seq = """
Implement a sequential multiplier.
Module name:
    seqmul
Input ports:
    clk: clock.
    rst: reset.
    start: start the multiply.
    a: 8-bit operand.
    b: 8-bit operand.
Output ports:
    p: 16-bit product.
    done: high when complete.
"""
    assert A.synth(seq, "seqmul") is None


def test_ve_combinational_adder_still_native():
    # the VE bullet half-adder is still solved by the native path, byte-identical
    ve = (" - input a\n - input b\n - output sum\n - output cout\n\n"
          "The module should implement a half adder.\n")
    rtl = A.synth(ve, "TopModule")
    assert rtl is not None and "assign {cout, sum} = a + b;" in rtl


@pytest.mark.skipif(not _HAVE_IV, reason="iverilog not installed")
@pytest.mark.parametrize("design,top", [
    ("Arithmetic/Comparator/comparator_3bit", "comparator_3bit"),
    ("Arithmetic/Substractor/sub_64bit", "sub_64bit"),
    ("Arithmetic/Multiplier/multi_8bit", "multi_8bit"),
    ("Miscellaneous/RISC-V/alu", "alu"),
])
def test_host_pass(design, top):
    d = _RT / design
    if not (d / "design_description.txt").is_file():
        pytest.skip("RTLLM dataset not present")
    rtl = A.synth((d / "design_description.txt").read_text(), top)
    assert rtl is not None
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / f"{top}.v"
        dut.write_text(rtl)
        vvp = Path(td) / "a.vvp"
        ce = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), "testbench.v", str(dut)],
                            capture_output=True, text=True, cwd=str(d))
        assert ce.returncode == 0, ce.stderr[:300]
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, timeout=60, cwd=str(d))
        assert "passed" in (r.stdout + r.stderr).lower()

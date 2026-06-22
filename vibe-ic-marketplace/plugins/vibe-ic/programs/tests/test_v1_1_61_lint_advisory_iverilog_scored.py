"""v1.1.61 — harness_exact_selfverify --lint-advisory: for an IVERILOG-scored
benchmark (VerilogEval / RTLLM Shape C), GATE B (verilator --lint-only -Wall)
must REPORT but NOT block emit — its verilator-only findings (LATCH on an
intended latch, WIDTHEXPAND/WIDTHTRUNC legal-Verilog width rules, BLKLOOPINIT
verilator LIMITATION) false-block host-PASSING designs (VE-human 028/030/044/
144/153 all blocked, all host-PASS). NO-LEAK: GATE A (iverilog standalone -s
codegen) still BLOCKs a genuine iverilog compile error; strict mode (default,
verilator-scored e.g. CVDP) keeps GATE B blocking.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import harness_exact_selfverify as h  # noqa: E402

_HAS_VERILATOR = shutil.which("verilator") is not None
_HAS_IVERILOG = shutil.which("iverilog") is not None

# intended D latch (verilator LATCH warning; iverilog-accepted, host-PASSing)
RTL_LATCH = "module TopModule(input d, input ena, output reg q);\n always @(*) if (ena) q = d;\nendmodule\n"
# WIDTHEXPAND: add a 1-bit select into an 8-bit accumulator (popcount idiom)
RTL_WIDTHEXPAND = ("module TopModule(input [254:0] in, output reg [7:0] out);\n"
                   " integer i; always @(*) begin out=0; for(i=0;i<255;i=i+1) out=out+in[i]; end\nendmodule\n")
# genuine iverilog compile error (must still BLOCK at GATE A even in advisory mode)
RTL_COMPILE_ERR = "module TopModule(output q); assign q = undeclared_xyz & ; endmodule\n"


def _emit(rtl, advisory):
    import tempfile
    d = Path(tempfile.mkdtemp()); p = d / "TopModule.sv"; p.write_text(rtl)
    return h.selfverify(p, "TopModule", None, False, lint_advisory=advisory)["emit"]


@pytest.mark.skipif(not (_HAS_VERILATOR and _HAS_IVERILOG), reason="tools unavailable")
def test_latch_advisory_emits_strict_blocks():
    assert _emit(RTL_LATCH, advisory=True) is True       # iverilog-scored: emit
    assert _emit(RTL_LATCH, advisory=False) is False     # verilator-scored (CVDP): still blocks


@pytest.mark.skipif(not (_HAS_VERILATOR and _HAS_IVERILOG), reason="tools unavailable")
def test_widthexpand_advisory_emits():
    assert _emit(RTL_WIDTHEXPAND, advisory=True) is True


@pytest.mark.skipif(not (_HAS_VERILATOR and _HAS_IVERILOG), reason="tools unavailable")
def test_genuine_compile_error_still_blocks_in_advisory():  # no-leak: GATE A
    r = h.selfverify(Path(_write(RTL_COMPILE_ERR)), "TopModule", None, False, lint_advisory=True)
    assert r["emit"] is False
    assert "A_standalone_compile" in r["blocking_gates"]


def _write(rtl):
    import tempfile, os
    d = tempfile.mkdtemp(); p = os.path.join(d, "TopModule.sv"); open(p, "w").write(rtl); return p


def test_advisory_flag_threads_through_selfverify_signature():
    import inspect
    assert "lint_advisory" in inspect.signature(h.selfverify).parameters

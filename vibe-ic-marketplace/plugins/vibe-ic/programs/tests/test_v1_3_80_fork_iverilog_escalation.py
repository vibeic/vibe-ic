"""Tests for the fork-iverilog-14 SV-2012 escalation rung in score_iverilog_tb.py
(v1.3.80).

Motivation: the golden `_ref.sv` of some VerilogEval problems (e.g. Prob151/156
review2015) uses an SV enum type-cast `States'(...)` that stock host iverilog 11/12
reject with "sorry: This cast operation is not yet supported". Because VerilogEval
compiles TB+ref+sample together, the ref's cast sinks the whole compile → the
scorer reported a false `compile_error` (and even flagged the golden as a dataset
defect). The forked iverilog 14 in the EDA container handles the cast, so the
scorer now escalates on the SV-2012 tool-gap signature and recompiles there,
stripping only the non-functional $dumpfile/$dumpvars (a fork-build forward-ref
quirk that never affects the Mismatches verdict).

§4.05 no-leak: the escalation only changes whether the COMPILE succeeds, never the
PASS/FAIL verdict — a wrong DUT still mismatches through the exact same path
(proven on Prob151: an all-zero stub reports Mismatches 4152/5069). The pure-python
helpers are unit-tested here; the docker path is gated (skips when the container or
docker is absent).
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- _strip_waveform_dumps: removes only waveform-dump lines --------------
def test_strip_waveform_dumps_removes_dump_calls():
    m = _load()
    src = (
        "module tb;\n"
        "  initial begin\n"
        "    $dumpfile(\"wave.vcd\");\n"
        "    $dumpvars(1, tb_mismatch, clk);\n"
        "    a = 1;\n"
        "  end\n"
        "  wire tb_mismatch = ~tb_match;\n"
        "endmodule\n"
    )
    out = m._strip_waveform_dumps(src)
    assert "$dumpfile" not in out
    assert "$dumpvars" not in out
    # functional lines are preserved
    assert "a = 1;" in out
    assert "wire tb_mismatch = ~tb_match;" in out
    assert "module tb;" in out


def test_strip_waveform_dumps_keeps_display_and_finish():
    m = _load()
    src = '  $display("x");\n  $finish;\n  $dumpvars(0, tb);\n'
    out = m._strip_waveform_dumps(src)
    assert "$display" in out and "$finish" in out
    assert "$dumpvars" not in out


# ---- _iverilog_toolgap_signature: fires on tool-gap, not plain syntax -----
@pytest.mark.parametrize("text", [
    "prob_ref.sv:29: sorry: This cast operation is not yet supported.",
    "t.sv:120: error: Unable to bind wire/reg/memory `tb_mismatch' in `tb'",
    "internal error: something in the elaborator",
    "I don't know how to elaborate: this construct",
])
def test_toolgap_signature_fires_on_sv2012_gaps(text):
    m = _load()
    assert m._iverilog_toolgap_signature(text) is True


@pytest.mark.parametrize("text", [
    "sample.sv:4: syntax error",
    "sample.sv:7: error: Unknown module type: FooBar",
    "error: reg 'q' is not a valid l-value",
    "",
])
def test_toolgap_signature_ignores_plain_rtl_errors(text):
    m = _load()
    assert m._iverilog_toolgap_signature(text) is False


# ---- docker-gated integration: fork path recovers the cast + no-leak ------
def _need_container():
    if not shutil.which("docker"):
        pytest.skip("docker not available")
    m = _load()
    r = subprocess.run(["docker", "exec", m._IV13_CONTAINER, "sh", "-c",
                        "iverilog -V >/dev/null 2>&1 && echo ok"],
                       capture_output=True, text=True)
    if "ok" not in r.stdout:
        pytest.skip(f"EDA container {m._IV13_CONTAINER!r} with iverilog not running")
    return m


def test_fork_iverilog_runs_sv_enum_cast_and_no_leak(tmp_path):
    """A minimal TB whose golden uses an SV enum cast: host iverilog rejects it,
    the fork rung runs it. A correct DUT PASSes; a wrong DUT still mismatches."""
    m = _need_container()
    # golden ref uses an enum type-cast in a $dumpvars-bearing TB
    ref = tmp_path / "r.sv"
    ref.write_text(
        "module RefModule(input [1:0] s, output logic [1:0] y);\n"
        "  typedef enum logic [1:0] {A,B,C,D} st_t;\n"
        "  always_comb y = st_t'(s);\n"
        "endmodule\n"
    )
    tb = tmp_path / "t.sv"
    tb.write_text(
        "module tb;\n"
        "  reg [1:0] s; wire [1:0] yr, yd; integer mism=0, i;\n"
        "  initial begin $dumpfile(\"w.vcd\"); $dumpvars(1, mism); end\n"
        "  RefModule good(.s(s), .y(yr));\n"
        "  TopModule dut(.s(s), .y(yd));\n"
        "  initial begin\n"
        "    for (i=0;i<4;i=i+1) begin s=i; #1; if (yr!==yd) mism=mism+1; end\n"
        "    $display(\"Mismatches: %0d in 4 samples\", mism); $finish;\n"
        "  end\n"
        "endmodule\n"
    )
    good = tmp_path / "good.sv"
    good.write_text("module TopModule(input [1:0] s, output [1:0] y);\n"
                    "  assign y = s;\nendmodule\n")
    bad = tmp_path / "bad.sv"
    bad.write_text("module TopModule(input [1:0] s, output [1:0] y);\n"
                   "  assign y = 2'b00;\nendmodule\n")

    out_good = m._fork_iverilog_compile_run([str(good), str(tb), str(ref)], "tb")
    assert out_good is not None, "fork build should succeed on the SV-cast golden"
    assert "Mismatches: 0 in 4 samples" in out_good

    out_bad = m._fork_iverilog_compile_run([str(bad), str(tb), str(ref)], "tb")
    assert out_bad is not None
    # §4.05 no-leak: a wrong DUT still mismatches (verdict never inflated)
    assert "Mismatches: 0 in" not in out_bad

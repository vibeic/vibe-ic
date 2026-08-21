"""verilator_timing_fallback_check — golden-self-test-guarded Verilator fallback.

§4.05 load-bearing: a TB iverilog can't compile is NOT auto-floored if Verilator
can run it FAITHFULLY (golden passes its own TB under Verilator). The no-leak half
is the faithfulness guard — when Verilator runs the TB but the GOLDEN fails under
it (scheduling/CDC mismatch), the FLOOR stands (we never wave through a TB
Verilator runs incorrectly).
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import verilator_timing_fallback_check as vf  # noqa: E402

_HAVE_VERILATOR = vf.verilator_available()

# A correct golden: a registered constant output q = 5.
_GOLDEN_OK = (
    "module dut(input clk, output reg [3:0] q);\n"
    "  initial q = 4'd5;\n"
    "  always @(posedge clk) q <= 4'd5;\n"
    "endmodule\n")
# A WRONG golden: outputs 6, so it fails the TB's q==5 check.
_GOLDEN_BAD = (
    "module dut(input clk, output reg [3:0] q);\n"
    "  initial q = 4'd6;\n"
    "  always @(posedge clk) q <= 4'd6;\n"
    "endmodule\n")
# A TB that uses an SV unpacked-array assignment-pattern '{...} (an iverilog-12
# tool-gap construct) — Verilator runs it. Prints the RTLLM success token only
# when the sampled output matches the expected.
_TB = (
    "module tb;\n"
    "  reg clk = 0; wire [3:0] q;\n"
    "  reg [3:0] expq [0:1];\n"
    "  integer err = 0;\n"
    "  dut uut(.clk(clk), .q(q));\n"
    "  always #5 clk = ~clk;\n"
    "  initial begin\n"
    "    expq = '{4'd5, 4'd5};\n"     # assignment-pattern init (iverilog-12 gap)
    "    #20;\n"
    "    if (q !== expq[0]) begin err = err + 1; $display(\"Failed at 0: got %d\", q); end\n"
    "    if (err == 0) $display(\"===========Your Design Passed===========\");\n"
    "    else $display(\"===========Failed===========\");\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")


def _stage(tmp, golden_src, tb_src):
    g = tmp / "golden.v"; g.write_text(golden_src)
    t = tmp / "tb.v"; t.write_text(tb_src)
    return g, t


# ── verilator-absent: cannot adjudicate → FLOOR-D stands (rc 2) ──────────────
def test_verilator_absent_returns_2(tmp_path, monkeypatch):
    monkeypatch.setattr(vf, "verilator_available", lambda: False)
    g, t = _stage(tmp_path, _GOLDEN_OK, _TB)
    rc, msg = vf.adjudicate(t, g, "tb", "dut", "dut", None,
                            list(vf._DEFAULT_PASS), list(vf._DEFAULT_FAIL))
    assert rc == 2 and "VERILATOR_ABSENT" in msg


# ── POSITIVE: Verilator runs the TB + golden passes → FAITHFUL (rc 0) ────────
@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator absent")
def test_faithful_when_golden_passes_under_verilator(tmp_path):
    g, t = _stage(tmp_path, _GOLDEN_OK, _TB)
    rc, msg = vf.adjudicate(t, g, "tb", "dut", "dut", None,
                            list(vf._DEFAULT_PASS), list(vf._DEFAULT_FAIL))
    assert rc == 0, msg
    assert "VERILATOR_FAITHFUL" in msg


# ── §4.05 NO-LEAK: Verilator runs the TB but the GOLDEN fails → FLOOR stands ─
@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator absent")
def test_unfaithful_when_golden_fails_under_verilator(tmp_path):
    g, t = _stage(tmp_path, _GOLDEN_BAD, _TB)   # golden outputs 6, TB wants 5
    rc, msg = vf.adjudicate(t, g, "tb", "dut", "dut", None,
                            list(vf._DEFAULT_PASS), list(vf._DEFAULT_FAIL))
    assert rc == 1, msg
    assert "VERILATOR_UNFAITHFUL" in msg


# ── build-fail (Verilator can't build either) → FLOOR-D (rc 1) ───────────────
@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator absent")
def test_build_fail_is_floor(tmp_path):
    g, t = _stage(tmp_path, _GOLDEN_OK, "module tb; this is not verilog endmodule\n")
    rc, msg = vf.adjudicate(t, g, "tb", "dut", "dut", None,
                            list(vf._DEFAULT_PASS), list(vf._DEFAULT_FAIL))
    assert rc == 1, msg


# ── golden-top rename (TB instantiates a different name than the golden) ─────
@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator absent")
def test_golden_top_rename(tmp_path):
    # golden module is 'refmod'; the TB instantiates 'dut' — the program renames.
    g, t = _stage(tmp_path, _GOLDEN_OK.replace("dut", "refmod"), _TB)
    rc, msg = vf.adjudicate(t, g, "tb", "dut", "refmod", None,
                            list(vf._DEFAULT_PASS), list(vf._DEFAULT_FAIL))
    assert rc == 0, msg


# --- the exit code is what the caller reads, and no test drove main()

def test_main_returns_the_adjudication_exit_code(monkeypatch, tmp_path):
    """`gate_cli_mutation_probe` reported this gate SILENT.

    The file's only `.main(` is `pytest.main`, so nothing ever drove the
    program's own entry point — every test asserts what `adjudicate()` RETURNS
    and the caller reads the EXIT CODE. Neutering `main()` reddened nothing.
    """
    import verilator_timing_fallback_check as V
    tb = tmp_path / "tb.sv"; tb.write_text("module tb; endmodule\n")
    g = tmp_path / "g.v"; g.write_text("module g; endmodule\n")
    argv = ["--tb", str(tb), "--golden", str(g),
            "--tb-top", "tb", "--dut-name", "g"]

    monkeypatch.setattr(V, "adjudicate",
                        lambda *a, **k: (1, "VERILATOR_UNFAITHFUL: x"))
    assert V.main(argv) == 1

    monkeypatch.setattr(V, "adjudicate",
                        lambda *a, **k: (0, "VERILATOR_FAITHFUL: x"))
    assert V.main(argv) == 0, \
        "a faithful golden must exit 0, or the test above is met by always failing"


def test_main_prints_the_verdict_token(monkeypatch, tmp_path, capsys):
    """The caller greps the token; an exit code with no message is unreadable."""
    import verilator_timing_fallback_check as V
    tb = tmp_path / "tb.sv"; tb.write_text("module tb; endmodule\n")
    g = tmp_path / "g.v"; g.write_text("module g; endmodule\n")
    monkeypatch.setattr(V, "adjudicate",
                        lambda *a, **k: (1, "VERILATOR_SIM_TIMEOUT: x"))
    V.main(["--tb", str(tb), "--golden", str(g),
            "--tb-top", "tb", "--dut-name", "g"])
    assert "VERILATOR_SIM_TIMEOUT" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

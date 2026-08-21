"""RTLLM capture: deterministic NBA repair for delay-driven oscillators."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import rtl_hygiene_lint as lint


REAL_FIXTURES = Path(__file__).parent / "fixtures" / "real_benchmark"
BLOCKING = (REAL_FIXTURES / "delay_driven_output_oscillator.v").read_text()


def _hits(text: str, path: str = "oscillator.v"):
    return lint.rule_delayed_blocking_clock_toggle(
        lint.strip_comments(text), path)


def test_detects_narrow_no_input_delayed_self_toggle():
    hits = _hits(BLOCKING)
    assert [(h.rule, h.symbol) for h in hits] == [
        ("delayed-blocking-clock-toggle", "wave")]


def test_rule_is_wired_into_lint_file(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(BLOCKING)
    assert any(f.rule == "delayed-blocking-clock-toggle"
               for f in lint.lint_file(rtl))


def test_fix_changes_only_toggle_operator_and_is_idempotent(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(BLOCKING)
    count, names = lint.autofix_delayed_blocking_clock_toggle(rtl)
    assert (count, names) == (1, ["wave"])
    fixed = rtl.read_text()
    assert "wave = 1'b0;" in fixed
    assert "#(PERIOD/2) wave <= ~wave;" in fixed
    assert not _hits(fixed)
    assert lint.autofix_delayed_blocking_clock_toggle(rtl) == (0, [])


def test_cli_fix_wires_the_repair_into_the_canonical_emit_path(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(BLOCKING)
    cp = subprocess.run([sys.executable, lint.__file__, "--fix", str(rtl)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    assert "rewrote 1 delayed oscillator self-toggle(s) to NBA" in cp.stdout
    assert "#(PERIOD/2) wave <= ~wave;" in rtl.read_text()


def test_bare_always_delay_oscillator_is_supported(tmp_path):
    text = """
module oscillator(output reg wave);
  initial wave = 0;
  always begin #5 wave = ~wave; end
endmodule
"""
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(text)
    assert len(_hits(text)) == 1
    assert lint.autofix_delayed_blocking_clock_toggle(rtl)[0] == 1
    assert "#5 wave <= ~wave" in rtl.read_text()


@pytest.mark.parametrize("text", [
    # Already deterministic.
    BLOCKING.replace("wave = ~wave", "wave <= ~wave"),
    # A real input means this is not a standalone source/oscillator model.
    BLOCKING.replace("    output reg wave", "    input enable,\n    output reg wave"),
    # Ordinary combinational blocking assignment: no delay, no oscillator.
    "module m(input a, output reg y); always @(*) y = ~a; endmodule\n",
    # Synthesizable edge-clocked blocking assignment: never blanket-rewrite.
    "module m(input clk, output reg y); always @(posedge clk) y = ~y; endmodule\n",
    # Delayed data assignment is not a self-toggle.
    "module m(output reg y); initial begin y=0; forever #5 y = 1'b1; end endmodule\n",
    # An extra functional writer makes intent ambiguous.
    "module m(output reg y); initial begin y=0; forever #5 y=~y; end "
    "initial #2 y=1; endmodule\n",
])
def test_no_leak_near_miss_patterns_are_untouched(text):
    assert _hits(text) == []


def test_testbench_module_is_never_rewritten():
    text = BLOCKING.replace("module oscillator", "module oscillator_tb")
    assert _hits(text, "oscillator_tb.v") == []


def test_fix_reproduces_same_timestamp_official_sampling_semantics(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("iverilog + vvp are required")
    rtl = tmp_path / "oscillator.v"
    tb = tmp_path / "testbench.v"
    rtl.write_text(BLOCKING)
    tb.write_text("""
module tb;
  wire wave;
  reg expected = 1'b0;
  integer errors = 0;
  oscillator dut(.wave(wave));
  initial begin
    repeat (20) begin
      #5;
      if (wave !== expected) errors = errors + 1;
      expected = ~expected;
    end
    if (errors == 0) $display("OFFICIAL PASS");
    else $display("OFFICIAL FAIL %0d", errors);
    $finish;
  end
endmodule
""")

    def run(tag: str) -> str:
        binp = tmp_path / f"{tag}.vvp"
        cp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(binp), str(rtl), str(tb)],
            capture_output=True, text=True, timeout=30)
        assert cp.returncode == 0, cp.stderr
        sim = subprocess.run(["vvp", str(binp)], capture_output=True, text=True,
                             timeout=30)
        return sim.stdout + sim.stderr

    assert "OFFICIAL FAIL" in run("blocking")
    assert lint.autofix_delayed_blocking_clock_toggle(rtl)[0] == 1
    assert "OFFICIAL PASS" in run("nba")

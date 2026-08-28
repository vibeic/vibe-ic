"""RTLLM capture: deterministic NBA repair for delay-driven oscillators."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import rtl_hygiene_lint as lint
from _hostpaths import require_repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


_BLOCKING_FIXTURE_PARTS = (
    "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
    "fixtures", "real_benchmark", "delay_driven_output_oscillator.v",
)
TASK_NEAR_MISS = """
module task_source(output reg y, output reg unrelated_wave);
  initial y = 0;
  initial begin
    forever #5 unrelated_wave = ~unrelated_wave;
  end
  task toggle_y;
    #5 y = ~y;
  endtask
  initial unrelated_wave = 0;
endmodule
"""
DISABLED_PREPROCESSOR_NEAR_MISS = """
module guarded_task_source(output reg y);
`ifdef NEVER
  initial begin
    forever begin
`endif
  initial y = 0;
  task toggle_y;
    #5 y = ~y;
  endtask
endmodule
"""
MACRO_EVENT_CONTROL_NEAR_MISS = r"""
`define EVENT @(posedge trigger)
module macro_event_source(output reg wave);
  reg trigger;
  initial begin trigger = 0; wave = 0; end
  always #1 trigger = ~trigger;
  always `EVENT #5 wave = ~wave;
endmodule
"""


def _blocking_fixture() -> str:
    """Read the checked-in benchmark-derived oscillator through hostpaths."""
    return require_repo(*_BLOCKING_FIXTURE_PARTS).read_text()


def _hits(text: str, path: str = "oscillator.v"):
    return lint.rule_delayed_blocking_clock_toggle(
        lint.strip_comments(text), path)


def test_detects_narrow_no_input_delayed_self_toggle():
    hits = _hits(_blocking_fixture())
    assert [(h.rule, h.symbol) for h in hits] == [
        ("delayed-blocking-clock-toggle", "wave")]


def test_rule_is_wired_into_lint_file(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(_blocking_fixture())
    assert any(f.rule == "delayed-blocking-clock-toggle"
               for f in lint.lint_file(rtl))


def test_fix_changes_only_toggle_operator_and_is_idempotent(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(_blocking_fixture())
    count, names = lint.autofix_delayed_blocking_clock_toggle(rtl)
    assert (count, names) == (1, ["wave"])
    fixed = rtl.read_text()
    assert "wave = 1'b0;" in fixed
    assert "#(PERIOD/2) wave <= ~wave;" in fixed
    assert not _hits(fixed)
    assert lint.autofix_delayed_blocking_clock_toggle(rtl) == (0, [])


def test_cli_fix_wires_the_repair_into_the_canonical_emit_path(tmp_path):
    rtl = tmp_path / "oscillator.v"
    rtl.write_text(_blocking_fixture())
    cp = _pr.run([sys.executable, lint.__file__, "--fix", str(rtl)],
                        capture_output=True, text=True)
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
    # A real input means this is not a standalone source/oscillator model.
    "module m(input enable, output reg wave); initial wave=0; "
    "always #5 wave=~wave; endmodule\n",
    # Ordinary combinational blocking assignment: no delay, no oscillator.
    "module m(input a, output reg y); always @(*) y = ~a; endmodule\n",
    # Synthesizable edge-clocked blocking assignment: never blanket-rewrite.
    "module m(input clk, output reg y); always @(posedge clk) y = ~y; endmodule\n",
    # Delayed data assignment is not a self-toggle.
    "module m(output reg y); initial begin y=0; forever #5 y = 1'b1; end endmodule\n",
    # An extra functional writer makes intent ambiguous.
    "module m(output reg y); initial begin y=0; forever #5 y=~y; end "
    "initial #2 y=1; endmodule\n",
    # A preceding, completed initial/forever block must not lend its process
    # context to a delayed assignment in a later task body.
    TASK_NEAR_MISS,
    # A forever elsewhere in the same initial block does not dominate y.
    "module m(output reg y, output reg z); initial y=0; initial begin "
    "if (1'b0) forever #5 z=~z; #5 y=~y; end initial z=0; endmodule\n",
    # A syntactically bare always that waits on an event before the toggle is
    # event-driven, not the delay-only oscillator class this fixer owns.
    "module m(output reg y, output reg z); initial y=0; initial z=0; "
    "always begin #1; @(posedge z); #5 y=~y; end endmodule\n",
    # The same event-driven boundary inside an initial/forever process.
    "module m(output reg y); reg trigger; "
    "initial begin trigger=0; #1 trigger=1; end "
    "initial begin y=0; forever begin @(posedge trigger); #5 y=~y; end end "
    "endmodule\n",
    # A macro may carry that event control; without preprocessing its meaning
    # is unresolved, so the fixer must decline rather than guess.
    "`define EVENT @(posedge trigger)\n"
    "module m(output reg y); reg trigger; "
    "initial begin trigger=0; #1 trigger=1; end "
    "initial begin y=0; forever begin `EVENT; #5 y=~y; end end "
    "endmodule\n",
])
def test_no_leak_near_miss_patterns_are_untouched(text):
    assert _hits(text) == []


def test_already_deterministic_real_fixture_is_untouched():
    text = _blocking_fixture().replace("wave = ~wave", "wave <= ~wave")
    assert _hits(text) == []


def test_fix_does_not_rewrite_task_body_after_unrelated_oscillator(tmp_path):
    rtl = tmp_path / "task_source.v"
    rtl.write_text(TASK_NEAR_MISS)
    assert lint.autofix_delayed_blocking_clock_toggle(rtl) == (0, [])
    assert rtl.read_text() == TASK_NEAR_MISS


def test_disabled_preprocessor_scope_cannot_rewrite_later_task(tmp_path):
    """Inactive procedural keywords cannot lend scope to live task code."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required")
    rtl = tmp_path / "guarded_task_source.v"
    rtl.write_text(DISABLED_PREPROCESSOR_NEAR_MISS)
    before = subprocess.run(
        ["iverilog", "-g2012", "-tnull", str(rtl)],
        capture_output=True, text=True)
    assert before.returncode == 0, before.stderr

    assert lint.autofix_delayed_blocking_clock_toggle(rtl) == (0, [])
    assert rtl.read_text() == DISABLED_PREPROCESSOR_NEAR_MISS

    after = subprocess.run(
        ["iverilog", "-g2012", "-tnull", str(rtl)],
        capture_output=True, text=True)
    assert after.returncode == 0, after.stderr


def test_macro_event_control_is_not_rewritten_as_a_bare_oscillator(tmp_path):
    """An unresolved macro after ``always`` may expand to an event control."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required")
    rtl = tmp_path / "macro_event_source.v"
    rtl.write_text(MACRO_EVENT_CONTROL_NEAR_MISS)
    before = subprocess.run(
        ["iverilog", "-g2012", "-tnull", str(rtl)],
        capture_output=True, text=True)
    assert before.returncode == 0, before.stderr

    assert lint.autofix_delayed_blocking_clock_toggle(rtl) == (0, [])
    assert rtl.read_text() == MACRO_EVENT_CONTROL_NEAR_MISS

    after = subprocess.run(
        ["iverilog", "-g2012", "-tnull", str(rtl)],
        capture_output=True, text=True)
    assert after.returncode == 0, after.stderr


def test_testbench_module_is_never_rewritten():
    text = _blocking_fixture().replace("module oscillator", "module oscillator_tb")
    assert _hits(text, "oscillator_tb.v") == []


def test_fix_reproduces_same_timestamp_official_sampling_semantics(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("iverilog + vvp are required")
    rtl = tmp_path / "oscillator.v"
    tb = tmp_path / "testbench.v"
    rtl.write_text(_blocking_fixture())
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
        cp = _pr.run(
            ["iverilog", "-g2012", "-o", str(binp), str(rtl), str(tb)],
            capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr
        sim = _pr.run(["vvp", str(binp)], capture_output=True, text=True)
        return sim.stdout + sim.stderr

    assert "OFFICIAL FAIL" in run("blocking")
    assert lint.autofix_delayed_blocking_clock_toggle(rtl)[0] == 1
    assert "OFFICIAL PASS" in run("nba")

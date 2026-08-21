"""Tests for vacuous_testbench_check — the Phase-2 gate that fails a run whose
testbenches print a PASS without ever driving the design.

Pure/structural (no container, no EDA tool): drives the gate over synthetic
Verilog trees.

These tests exercise the gate's PUBLIC behaviour only — the JSON verdict, the
emitted evidence, and the process exit code. They deliberately do NOT reach into
the parsing helpers, so a correct alternative implementation (a different lexer,
a different regex, a real Verilog parser) passes them unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import vacuous_testbench_check as G  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
# The EXACT shape the scaffolder emits and that a filename glob cannot find:
# named for the SCENARIO, DUT instantiation commented out, prints a pass.
VACUOUS_TB = """\
// Auto-generated unit TB for case=corner_operand
`timescale 1ns/1ps
module corner_operand;
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB corner_operand] BEGIN");
    #100 reset_n = 1;
    #1000 $display("[TB corner_operand] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // widget u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
"""

# A genuinely clean testbench: a LIVE DUT instantiation plus a real assertion
# that can actually fail (it compares against a golden model and exits non-zero).
CLEAN_TB = """\
`timescale 1ns/1ps
module tb_widget;
  parameter W = 8;
  reg clk = 0, rst = 1;
  reg  [W-1:0] a = 0, b = 0;
  wire [W-1:0] q;
  integer errors = 0;

  widget #(.W(W)) u_dut (.clk(clk), .rst(rst), .a(a), .b(b), .q(q));
  always #5 clk = ~clk;

  initial begin
    @(negedge clk); rst = 0;
    for (a = 0; a < 16; a = a + 1) begin
      b = a + 1;
      @(posedge clk); #1;
      if (q !== (a + b)) begin
        errors = errors + 1;
        $display("MISMATCH a=%0d b=%0d q=%0d exp=%0d", a, b, q, a + b);
      end
    end
    if (errors != 0) begin
      $display("FAIL %0d mismatches", errors);
      $fatal(1);
    end
    $display("PASS all vectors matched");
    $finish;
  end
endmodule
"""


def _tree(root: Path, files: dict) -> Path:
    sim = root / "phase2" / "stage1" / "sim"
    for rel, body in files.items():
        p = sim / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return sim


# ---------------------------------------------------------------------------
# the FAILING fixture — the exact shape the old filename glob missed
# ---------------------------------------------------------------------------
def test_scenario_named_placeholder_tb_fails(tmp_path):
    _tree(tmp_path, {"tb/corner_operand.v": VACUOUS_TB})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert G.main([str(tmp_path)]) == 1


def test_fixture_matches_no_conventional_tb_filename_glob(tmp_path):
    """Pins WHY a filename-driven audit reported zero hits on a real corpus.

    The offending file is named for the SCENARIO. If a future change narrows
    discovery back to `tb_*.v` / `*_tb.v`, this test fails.
    """
    name = "corner_operand.v"
    assert not name.startswith("tb_")
    assert not name.endswith("_tb.v")
    _tree(tmp_path, {"tb/" + name: VACUOUS_TB})
    assert G.check(tmp_path)["verdict"] == "FAIL"


def test_evidence_carries_path_line_and_text(tmp_path):
    """A verdict with no attached evidence cannot be cross-checked."""
    _tree(tmp_path, {"tb/corner_operand.v": VACUOUS_TB})
    ev = G.check(tmp_path)["evidence"]
    assert ev, "gate must emit the raw evidence it judged on"
    for e in ev:
        assert e["detector"] and e["file"] and "line" in e and e["text"]
    marker = [e for e in ev if e["detector"] == "placeholder_marker"]
    assert marker and marker[0]["line"] == 9   # the $display line
    assert "PASS_PLACEHOLDER" in marker[0]["text"]
    commented = [e for e in ev if e["detector"] == "commented_dut_instantiation"]
    assert commented and commented[0]["line"] == 13  # the commented DUT line
    assert commented[0]["module"] == "widget"


def test_structural_detector_survives_marker_rename(tmp_path):
    """A marker string is trivially renamed — the structural detector must not
    depend on it. Independence of the two detectors is the whole point."""
    renamed = VACUOUS_TB.replace(
        "PASS_PLACEHOLDER (replace with real stimulus)", "OK")
    assert "PASS_PLACEHOLDER" not in renamed
    _tree(tmp_path, {"tb/case_3.v": renamed})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert "commented_dut_instantiation" in res["detectors_tripped"]
    assert G.main([str(tmp_path)]) == 1


def test_deleted_dut_line_still_caught(tmp_path):
    """The actual defect, not its symptoms: strip BOTH the marker and the
    commented DUT line and the TB still drives nothing."""
    stripped = "\n".join(
        l for l in VACUOUS_TB.splitlines()
        if "PASS_PLACEHOLDER" not in l and "u_dut" not in l)
    _tree(tmp_path, {"tb/rv32i_40.v": stripped})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert "no_live_instantiation" in res["detectors_tripped"]


def test_block_commented_dut_with_wrapped_ports_is_caught(tmp_path):
    """A block comment across several lines is the obvious way to evade a
    line-oriented `^\\s*//` regex, and it carries NO placeholder marker."""
    body = """\
`timescale 1ns/1ps
module corner_case;
  reg clk = 0, reset_n = 0;
  initial begin
    $display("[TB] done ok");
    $finish;
  end
  /* widget u_dut (
       .clk(clk),
       .reset_n(reset_n)
     ); */
endmodule
"""
    assert "PASS_PLACEHOLDER" not in body
    _tree(tmp_path, {"tb/corner_case.v": body})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert "commented_dut_instantiation" in res["detectors_tripped"]


# ---------------------------------------------------------------------------
# the PASSING fixture — proof the gate discriminates and can stay silent
# ---------------------------------------------------------------------------
def test_comment_marker_inside_a_string_literal_is_not_a_comment(tmp_path):
    """`//` inside a string is code, not a comment. Mis-lexing it would
    manufacture a commented-DUT finding on a TB that really drives the DUT."""
    body = """\
`timescale 1ns/1ps
module strlit;
  reg clk = 0, rst = 1;
  wire [7:0] q;
  integer errors = 0;
  widget u_dut (.clk(clk), .rst(rst), .q(q));
  always #5 clk = ~clk;
  initial begin
    $display("hint: // widget u_dut (.clk(clk)); is how you wire it");
    #100; if (q !== 8'd0) errors = errors + 1;
    if (errors) $fatal(1);
    $finish;
  end
endmodule
"""
    _tree(tmp_path, {"tb/strlit.v": body})
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", res.get("evidence")



def test_clean_testbench_passes(tmp_path):
    """A detector that cannot stay silent is an alarm, not a detector."""
    _tree(tmp_path, {"tb/tb_widget.v": CLEAN_TB})
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", res.get("evidence")
    assert res["evidence"] == []
    assert G.main([str(tmp_path)]) == 0


def test_clean_scenario_named_testbench_passes(tmp_path):
    """Scenario naming is not itself the defect — a scenario-named TB that
    really drives the DUT must pass."""
    _tree(tmp_path, {"tb/corner_operand.v": CLEAN_TB.replace(
        "module tb_widget;", "module corner_operand;")})
    assert G.check(tmp_path)["verdict"] == "PASS"


def test_commented_debug_alternative_alongside_live_dut_passes(tmp_path):
    """A TB that really drives the DUT and merely keeps a commented-out
    alternative instantiation is NOT vacuous."""
    body = CLEAN_TB.replace(
        "  always #5 clk = ~clk;",
        "  // widget #(.W(16)) u_dut_alt (.clk(clk), .rst(rst), ...);\n"
        "  always #5 clk = ~clk;")
    _tree(tmp_path, {"tb/tb_widget.v": body})
    assert G.check(tmp_path)["verdict"] == "PASS"


def test_macro_and_ifdef_instantiation_is_live(tmp_path):
    """A DUT instantiated behind `ifdef, or whose module type is a macro so the
    TB can be retargeted, is a REAL instantiation."""
    body = """\
`timescale 1ns/1ps
module tb_top;
  reg clk = 0, reset_n = 0;
  wire id_bus;
`ifdef DUT_TOP_NAME
  `DUT_TOP_NAME u_dut (.clk(clk), .reset_n(reset_n), .id_bus(id_bus));
`else
  chip_top u_dut (.clk(clk), .reset_n(reset_n), .id_bus(id_bus));
`endif
  initial begin #100; if (id_bus !== 1'b1) $fatal(1); $finish; end
endmodule
"""
    _tree(tmp_path, {"tb/tb_top.v": body})
    assert G.check(tmp_path)["verdict"] == "PASS"


def test_trace_companion_tb_passes_when_tree_has_a_driving_tb(tmp_path):
    """A portless documentation/trace TB instantiates nothing BY DESIGN. It is
    only vacuous if NOTHING in the sim tree drives the design — hence the
    no-live-instantiation detector is scoped to the tree, not the file."""
    trace = """\
`timescale 1ns/1ps
module l10_coverage_trace;
  initial begin
    $display("L10-TRACE reset PASS");
    $display("L10-TRACE corner_operand PASS");
  end
endmodule
"""
    _tree(tmp_path, {"tb/l10_coverage_trace.v": trace,
                     "tb_widget_func.v": CLEAN_TB})
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", res.get("evidence")


def test_rtl_copy_in_sim_tree_is_not_mistaken_for_a_driving_testbench(tmp_path):
    """Coverage-annotated RTL copies live under the sim tree. They have ports,
    so they are not testbenches — their internal instantiations must NOT be
    counted as 'something drives the design'."""
    rtl = """\
module widget #(parameter W = 8) (input clk, input rst, output [W-1:0] q);
  submod u_sub (.clk(clk), .rst(rst), .q(q));
endmodule
"""
    _tree(tmp_path, {"tb/corner_operand.v": VACUOUS_TB, "cov_annot/widget.v": rtl})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert "no_live_instantiation" in res["detectors_tripped"]


# ---------------------------------------------------------------------------
# contract: exit codes, report emission, non-applicability
# ---------------------------------------------------------------------------
def test_absent_sim_tree_is_not_applicable(tmp_path):
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_APPLICABLE"
    # rc 2 is the flow's disclosed-skip tier (VACUOUS_PASS), never a false
    # FAIL and never an ordinary rc-0 PASS over a zero denominator.
    assert G.main([str(tmp_path)]) == 2


def test_sim_tree_without_testbenches_is_not_applicable(tmp_path):
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text("<testsuite/>")
    assert G.check(tmp_path)["verdict"] == "NOT_APPLICABLE"
    assert G.main([str(tmp_path)]) == 2


def test_json_report_is_written(tmp_path):
    _tree(tmp_path, {"tb/corner_operand.v": VACUOUS_TB})
    out = tmp_path / "reports" / "phase2" / "gates" / "vacuous_testbench.json"
    assert G.main([str(tmp_path), "--json", str(out)]) == 1
    rec = json.loads(out.read_text())
    assert rec["verdict"] == "FAIL"
    assert rec["evidence"] and rec["offending_files"]


def test_sim_root_override(tmp_path):
    alt = tmp_path / "custom" / "tb"
    alt.mkdir(parents=True)
    (alt / "case_3.v").write_text(VACUOUS_TB)
    assert G.main([str(tmp_path), "--sim-root", str(alt.parent)]) == 1


def test_gate_is_chip_agnostic():
    """No chip / vendor / design-name literal may leak into the gate."""
    src = (PROG / "vacuous_testbench_check.py").read_text().lower()
    for token in ("spm", "sha256", "subservient", "sky130", "gf180",
                  "nangate", "asap7", "chip_top"):
        assert token not in src, f"chip/PDK literal {token!r} leaked into the gate"

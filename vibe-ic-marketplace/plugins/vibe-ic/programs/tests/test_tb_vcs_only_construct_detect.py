"""Tests for tb_vcs_only_construct_detect.py (open-benchmark-methodology § 4 Cat D)."""
from __future__ import annotations

import tb_vcs_only_construct_detect as mod

CLEAN_TB = """\
module tb;
  reg clk;
  initial begin
    clk = 0;
    #10 clk = 1;
    $display("ok");
    $finish;
  end
endmodule
"""

VCS_AGGREGATE_TB = """\
module tb;
  int arr[3];
  initial arr = '{1, 2, 3};
endmodule
"""

VCS_BREAK_TB = """\
module tb;
  initial begin
    for (int i = 0; i < 10; i++) begin
      if (i == 5) break;
    end
  end
endmodule
"""


def test_clean_tb_pass(tmp_path):
    p = tmp_path / "tb.v"
    p.write_text(CLEAN_TB)
    rc = mod.main([str(p)])
    assert rc == 0  # no VCS-only construct → not a Cat-D floor


def test_assignment_pattern_detected_fail(tmp_path):
    p = tmp_path / "tb.sv"
    p.write_text(VCS_AGGREGATE_TB)
    rc = mod.main([str(p)])
    assert rc == 1
    hits = mod.scan_text(VCS_AGGREGATE_TB)
    assert any(h["construct"] == "assignment_pattern" for h in hits)


def test_break_detected_fail(tmp_path):
    p = tmp_path / "tb.sv"
    p.write_text(VCS_BREAK_TB)
    rc = mod.main([str(p)])
    assert rc == 1
    assert any(h["construct"] == "break_stmt" for h in mod.scan_text(VCS_BREAK_TB))


def test_urandom_range_detected():
    hits = mod.scan_text("initial x = $urandom_range(0, 7);")
    assert any(h["construct"] == "urandom_range" for h in hits)


def test_construct_in_comment_not_flagged():
    # The construct appears only in comments → must NOT fire (no compile risk).
    text = ("// uses break; in a VCS testbench\n"
            "/* arr = '{1,2,3}; */\n"
            "module tb; endmodule\n")
    assert mod.scan_text(text) == []


def test_missing_file_usage_error(tmp_path):
    rc = mod.main([str(tmp_path / "absent.v")])
    assert rc == 2  # honest usage error, never a vacuous PASS


def test_json_report_fail(tmp_path):
    p = tmp_path / "tb.sv"
    p.write_text(VCS_BREAK_TB)
    out = tmp_path / "r.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 1
    import json
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["category"] == "D"
    assert rep["hits"]


# ---------------------------------------------------------------------------
# THE § 4.1 FLOOR-PROOF EDGE — `verilator_timing_fallback_check` had no caller.
#
# Before this edge the report carried `floor_proof_required`, a STRING asking a
# reader to go and run the golden under Verilator, while the program that runs
# exactly that measurement was reachable from nothing but its own unit test.
# These tests drive the edge in BOTH directions on a real Verilator, and pin
# the byte-for-byte no-op when no golden is supplied.
# ---------------------------------------------------------------------------
import json as _json
import shutil as _shutil

import pytest

_GOLDEN = """\
module counter4 (input wire clk, input wire rst, output reg [3:0] q);
  always @(posedge clk) begin
    if (rst) q <= 4'd0;
    else     q <= q + 4'd1;
  end
endmodule
"""

#: Carries `break;` — one of the constructs this detector flags — so the
#: floor-proof branch is reachable at all. The loop bound and the expected
#: value are the DUT's own contract, so the golden passes its own TB.
_TB_GOLDEN_PASSES = """\
`timescale 1ns/1ps
module tb;
  reg clk = 0, rst = 1;
  wire [3:0] q;
  integer i;
  counter4 dut (.clk(clk), .rst(rst), .q(q));
  always #5 clk = ~clk;
  initial begin
    @(negedge clk); rst = 0;
    for (i = 0; i < 32; i = i + 1) begin
      @(negedge clk);
      if (q !== ((i+1) & 4'hF)) begin
        $display("Test failed at i=%0d q=%0d", i, q);
        break;
      end
    end
    $display("Your Design Passed");
    $finish;
  end
endmodule
"""

#: THE MUTATION IS IN THE TB'S EXPECTATION, NOT IN THE GOLDEN. Same DUT, same
#: construct, same denominator — what changes is whether the golden can satisfy
#: its own TB, which is the exact question the faithfulness guard asks.
_TB_GOLDEN_FAILS = _TB_GOLDEN_PASSES.replace("((i+1) & 4'hF)", "i[3:0]")
assert _TB_GOLDEN_FAILS != _TB_GOLDEN_PASSES


def test_no_golden_leaves_the_report_byte_for_byte_unchanged(tmp_path):
    """A caller with no golden gets the report it always got, and no proof."""
    p = tmp_path / "tb.sv"
    p.write_text(VCS_BREAK_TB)
    out = tmp_path / "r.json"
    assert mod.main([str(p), "--json", str(out)]) == 1
    rep = _json.loads(out.read_text())
    assert "floor_proof" not in rep
    assert rep["disposition"] == "FORK-FIXABLE"
    assert rep["floor_proof_required"]


def test_golden_without_module_names_is_a_usage_error(tmp_path):
    """rc 2, not a vacuous proof: the adjudicator cannot elaborate without them."""
    p = tmp_path / "tb.sv"
    p.write_text(VCS_BREAK_TB)
    g = tmp_path / "g.v"
    g.write_text(_GOLDEN)
    assert mod.main([str(p), "--golden", str(g)]) == 2


@pytest.mark.skipif(_shutil.which("verilator") is None,
                    reason="the floor-proof IS a verilator run")
def test_floor_proof_faithful_when_the_golden_passes_its_own_tb(tmp_path):
    (tmp_path / "g.v").write_text(_GOLDEN)
    p = tmp_path / "tb.sv"
    p.write_text(_TB_GOLDEN_PASSES)
    out = tmp_path / "r.json"
    rc = mod.main([str(p), "--golden", str(tmp_path / "g.v"),
                   "--tb-top", "tb", "--dut-name", "counter4",
                   "--json", str(out)])
    # rc is the DETECTOR's, unchanged by the proof: the construct is present.
    assert rc == 1
    rep = _json.loads(out.read_text())
    assert rep["floor_proof"]["tool"] == "verilator_timing_fallback_check"
    assert rep["floor_proof"]["verdict"] == "VERILATOR_FAITHFUL"
    assert rep["disposition"] == "SCORABLE-UNDER-VERILATOR"


@pytest.mark.skipif(_shutil.which("verilator") is None,
                    reason="the floor-proof IS a verilator run")
def test_floor_proof_unfaithful_leaves_the_floor_standing(tmp_path):
    (tmp_path / "g.v").write_text(_GOLDEN)
    p = tmp_path / "tb.sv"
    p.write_text(_TB_GOLDEN_FAILS)
    out = tmp_path / "r.json"
    assert mod.main([str(p), "--golden", str(tmp_path / "g.v"),
                     "--tb-top", "tb", "--dut-name", "counter4",
                     "--json", str(out)]) == 1
    rep = _json.loads(out.read_text())
    assert rep["floor_proof"]["verdict"] == "VERILATOR_UNFAITHFUL"
    assert rep["disposition"] == "FORK-FIXABLE"

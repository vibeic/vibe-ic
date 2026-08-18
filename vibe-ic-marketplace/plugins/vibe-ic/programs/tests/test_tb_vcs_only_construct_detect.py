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

#!/usr/bin/env python3
"""Tests for verilog_selfcheck_lint — the verilator -Wall self-lint gate.

Honest by-environment behavior: when verilator is absent the gate returns SKIP
(never a fake PASS); when present it PASSes clean RTL and FAILs an over-wide
UNUSEDSIGNAL — the exact defect that sank the IIR_filter coverage-gap case.
"""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "verilog_selfcheck_lint", _PROGRAMS / "verilog_selfcheck_lint.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
selfcheck = _M.selfcheck_lint

_HAVE_VERILATOR = shutil.which("verilator") is not None

CLEAN = """\
module clean_dut (input wire clk, input wire [7:0] a, output reg [7:0] y);
  always @(posedge clk) y <= a;
endmodule
"""

# temp_y is 32-bit but only [15:0] is ever read → verilator %Warning-UNUSEDSIGNAL
DIRTY = """\
module dirty_dut (input wire clk, input wire [15:0] a, output reg [15:0] y);
  reg [31:0] temp_y;
  always @(posedge clk) begin
    temp_y <= {16'b0, a};
    y <= temp_y[15:0];
  end
endmodule
"""


def test_skip_when_no_binary():
    # force an unreachable binary → honest SKIP, never a fake PASS
    r = selfcheck(CLEAN, top="clean_dut", verilator="/nonexistent/verilator")
    assert r["status"] == "SKIP"
    assert r["skip_reason"]
    assert r["returncode"] is None


@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator not installed")
def test_clean_rtl_passes():
    r = selfcheck(CLEAN, top="clean_dut")
    assert r["status"] == "PASS", r["raw"]
    assert r["n_warnings"] == 0


@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator not installed")
def test_dirty_rtl_fails_with_unusedsignal():
    r = selfcheck(DIRTY, top="dirty_dut")
    assert r["status"] == "FAIL", r["raw"]
    assert any("UNUSED" in (c or "") for c in r["codes"]), r["codes"]
    # the over-wide reg is named in a warning
    assert any(w.get("signal") and "temp_y" in w["signal"] for w in r["warnings"]) \
        or "temp_y" in r["raw"]


def test_status_is_one_of_the_three():
    r = selfcheck(CLEAN, top="clean_dut")
    assert r["status"] in ("PASS", "FAIL", "SKIP")


def test_raw_text_with_slash_not_misrouted_as_path(tmp_path):
    # regression: raw SV text containing '/' (a // comment or division) must NOT
    # be treated as a file path. The old `os.path.sep in rtl` heuristic misrouted
    # it as a filename → verilator "Cannot find file containing module" → false FAIL.
    looks = _M._looks_like_path
    raw = ("module m(input wire clk, output reg q);\n"
           "  // divide a/b toggle\n"
           "  always @(posedge clk) q <= ~q;\nendmodule\n")
    assert "/" in raw
    assert looks(raw) is False              # raw text is never a path
    # a genuine file IS recognized as a path
    f = tmp_path / "real.sv"
    f.write_text("module real_dut; endmodule\n")
    assert looks(str(f)) is True
    # an over-long raw source (would blow ENAMETOOLONG) is still "not a path"
    assert looks("x" * 9000) is False


@pytest.mark.skipif(not _HAVE_VERILATOR, reason="verilator not installed")
def test_raw_text_with_slash_lints_clean(tmp_path):
    # end-to-end: with real verilator, the same slash-bearing raw text now lints
    # (routes to a temp file) instead of the old spurious "cannot find file" FAIL.
    raw = ("module m(input wire clk, output reg q);\n"
           "  // divide a/b toggle\n"
           "  always @(posedge clk) q <= ~q;\nendmodule\n")
    r = selfcheck(raw, top="m")
    assert r["status"] == "PASS", r["raw"]
    assert not any("Cannot find file" in (w.get("message") or "") for w in r["warnings"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

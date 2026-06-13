"""Unit tests for bit_level_full_stack_tb_check.py (v0.52 plugin gate).

Regression coverage for the byte-level-sim PASS / FPGA-bit-level-FAIL gap
exposed by the 2026-04-24 phase2+3_v051 fresh-agent run.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'bit_level_full_stack_tb_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import bit_level_full_stack_tb_check as gate  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GOOD_TB = """\
`timescale 1ns/1ps
module tb_aid_top_full;
    wire acc_id;
    reg  drive;
    aid_top u_dut(.acc_id(acc_id), .clk(clk), .rstn(rstn));

    initial begin
        // bit-level driving with realistic timing
        drive = 0; #1800;
        drive = 1; #7100;
        drive = 0; #1800;
        $display("FULL_STACK_PASS");
        $finish;
    end
endmodule
"""

GOOD_RESULTS = {
    "tb": "tb_aid_top_full.v",
    "dut": "aid_top",
    "opcodes_tested": ["0x70", "0x72", "0x74"],
    "responses": [
        {"opcode": "0x70", "rsp_bytes_hex": "F2 02 02 02 02 02 BE AB BA D1 CD D0 D1 D2 AF CD CD D1 B5 AC D2 C1 B8 02 02 FA"},
    ],
    "distinct_non_padding_bytes": 14,
    "padding_byte": "0x02",
    "pass": True,
}


def _make_project(tmp_path, top="aid_top", tb_text=GOOD_TB,
                  results=GOOD_RESULTS, write_rtl=True):
    proj = tmp_path
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    if write_rtl:
        (rtl / f"{top}.v").write_text(f"module {top}(); endmodule\n")
        (rtl / "rx_phy.v").write_text("module rx_phy(); endmodule\n")
    sim = proj / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    if tb_text is not None:
        (sim / f"tb_{top}_full.v").write_text(tb_text)
    if results is not None:
        # Ensure results.json mtime is newer than RTL mtime
        time.sleep(0.05)
        (sim / "results.json").write_text(json.dumps(results, indent=2))
    return proj, rtl, sim


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_full_stack_tb_pass(tmp_path):
    proj, rtl, sim = _make_project(tmp_path)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is True, result


def test_full_stack_tb_pass_via_main(tmp_path):
    proj, rtl, sim = _make_project(tmp_path)
    rc = gate.main.__wrapped__ if hasattr(gate.main, "__wrapped__") else None
    # Use subprocess-style: just call main() with sys.argv override
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj)]
    try:
        rc = gate.main()
    finally:
        sys.argv = old
    assert rc == 0


# ---------------------------------------------------------------------------
# Negative: missing files
# ---------------------------------------------------------------------------
def test_missing_sim_dir_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "aid_top.v").write_text("module aid_top(); endmodule")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"  # not created
    result = gate.check(tmp_path, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert result["rule"] == "SIM_FULL_STACK_DIR_EXISTS"


def test_missing_tb_file_fails(tmp_path):
    proj, rtl, sim = _make_project(tmp_path, tb_text=None)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "TB_FILE_PRESENT" for f in result["findings"])


def test_missing_results_json_fails(tmp_path):
    proj, rtl, sim = _make_project(tmp_path, results=None)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "RESULTS_JSON" for f in result["findings"])


# ---------------------------------------------------------------------------
# Negative: tb does not actually exercise bit level
# ---------------------------------------------------------------------------
def test_tb_without_pad_signal_fails(tmp_path):
    bad_tb = """\
module tb_aid_top_full;
    aid_top u_dut(.clk(clk), .rstn(rstn));
    initial begin
        // byte-level only — no acc_id / sda / pad reference
        $display("done"); $finish;
    end
endmodule
"""
    proj, rtl, sim = _make_project(tmp_path, tb_text=bad_tb)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "TB_DRIVES_BIT_LEVEL" for f in result["findings"])


def test_tb_without_bit_delays_fails(tmp_path):
    """Pad referenced but no `#<n>;` between bit edges → not bit level."""
    bad_tb = """\
module tb_aid_top_full;
    wire acc_id;
    aid_top u_dut(.acc_id(acc_id));
    initial begin
        // mentions acc_id but never times bit edges
        force u_dut.acc_id = 1'b0;
        force u_dut.acc_id = 1'b1;
        $display("done"); $finish;
    end
endmodule
"""
    proj, rtl, sim = _make_project(tmp_path, tb_text=bad_tb)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "TB_DRIVES_BIT_LEVEL" for f in result["findings"])


# ---------------------------------------------------------------------------
# Negative: tb does not instantiate top
# ---------------------------------------------------------------------------
def test_tb_does_not_instantiate_top_fails(tmp_path):
    bad_tb = """\
module tb_aid_top_full;
    wire acc_id;
    // wrong: instantiates only rx_phy, not the chip top
    rx_phy u_dut(.acc_id(acc_id));
    initial begin
        #1800; #7100; $finish;
    end
endmodule
"""
    proj, rtl, sim = _make_project(tmp_path, tb_text=bad_tb)
    result = gate.check(proj, rtl, sim, top="aid_top",
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "TB_INSTANTIATES_TOP" for f in result["findings"])


# ---------------------------------------------------------------------------
# Negative: results.json below thresholds
# ---------------------------------------------------------------------------
def test_results_below_distinct_threshold_fails(tmp_path):
    weak = dict(GOOD_RESULTS)
    weak["distinct_non_padding_bytes"] = 5  # below default 10
    proj, rtl, sim = _make_project(tmp_path, results=weak)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "RESULTS_JSON" for f in result["findings"])


def test_results_below_opcodes_threshold_fails(tmp_path):
    weak = dict(GOOD_RESULTS)
    weak["opcodes_tested"] = ["0x70"]  # only 1 < default 3
    proj, rtl, sim = _make_project(tmp_path, results=weak)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "RESULTS_JSON" for f in result["findings"])


def test_results_pass_false_fails(tmp_path):
    weak = dict(GOOD_RESULTS)
    weak["pass"] = False
    proj, rtl, sim = _make_project(tmp_path, results=weak)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "RESULTS_JSON" for f in result["findings"])


# ---------------------------------------------------------------------------
# Negative: results stale (older than RTL)
# ---------------------------------------------------------------------------
def test_stale_results_fails(tmp_path):
    proj, rtl, sim = _make_project(tmp_path)
    # Touch RTL to be newer than results.json
    time.sleep(0.05)
    (rtl / "aid_top.v").write_text("// edited later\nmodule aid_top(); endmodule")
    # Force RTL mtime ahead
    later = time.time() + 5
    os.utime(rtl / "aid_top.v", (later, later))
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False
    assert any(f["rule"] == "RESULTS_JSON" for f in result["findings"])
    assert "older than" in result["results_check"]["reason"]


# ---------------------------------------------------------------------------
# Top discovery
# ---------------------------------------------------------------------------
def test_top_discovery_via_l9(tmp_path):
    proj, rtl, sim = _make_project(tmp_path, top="aid_top")
    # Provide L9 with a different-named top to ensure preference is honoured
    gen = proj / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "aid_top"}))
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["top_module"] == "aid_top"


def test_explicit_top_overrides_discovery(tmp_path):
    proj, rtl, sim = _make_project(tmp_path, top="aid_top")
    # Even if there is no L9, explicit --top wins
    result = gate.check(proj, rtl, sim, top="aid_top",
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["top_module"] == "aid_top"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------
def test_cli_writes_json_report(tmp_path):
    proj, rtl, sim = _make_project(tmp_path)
    out_json = tmp_path / "reports" / "bit_level_full_stack.json"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj),
                "--json", str(out_json)]
    try:
        rc = gate.main()
    finally:
        sys.argv = old
    assert rc == 0
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert data["pass"] is True


def test_cli_nonexistent_project_returns_2(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(nonexistent)]
    try:
        rc = gate.main()
    finally:
        sys.argv = old
    assert rc == 2

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
# #760 — a declared top the design does not declare
#
# Phase 1 harvested a protocol name out of prose in a register description and
# published it as `L9.top_module`. No module of that name exists anywhere in
# the design; the testbench correctly instantiates the real top, which the rest
# of the run honours throughout. The gate used to demand the testbench
# instantiate the harvested name — a requirement no testbench could satisfy,
# reported as a testbench defect.
# ---------------------------------------------------------------------------
_HIER_TOP = "chip_top_asic"
_HIER_CHILD = "core"

_HIER_TB = """\
`timescale 1ns/1ps
module tb_chip_top_asic_full;
    wire acc_id;
    reg  drive;
    chip_top_asic u_dut(.acc_id(acc_id), .clk(clk), .rstn(rstn));
    integer bit_count;
    initial begin
        drive = 0; #1800;
        drive = 1; #7100;
        $finish;
    end
endmodule
"""


def _make_hierarchical_project(tmp_path, l9_top=None, tb_text=_HIER_TB):
    """A design whose real top is `chip_top_asic` — a name NO filename
    convention (`chip_top.v` / `*_top.v` / `top.v`) matches, so the top is
    knowable only from the design's own hierarchy: `chip_top_asic` instantiates
    `core`, and nothing instantiates `chip_top_asic`.
    """
    proj = tmp_path
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{_HIER_TOP}.v").write_text(
        f"module {_HIER_TOP}(input clk, input rstn, inout acc_id);\n"
        f"    {_HIER_CHILD} u_core(.clk(clk), .rstn(rstn), .acc_id(acc_id));\n"
        f"endmodule\n")
    (rtl / f"{_HIER_CHILD}.v").write_text(
        f"module {_HIER_CHILD}(input clk, input rstn, inout acc_id);\n"
        f"endmodule\n")
    if l9_top is not None:
        gen = proj / "phase1" / "generated_docs"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
            "top_module": l9_top,
            "irq": "Single SPI interrupt request line back to MCU",
        }))
    sim = proj / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    if tb_text is not None:
        (sim / f"tb_{_HIER_TOP}_full.v").write_text(tb_text)
    time.sleep(0.05)
    results = dict(GOOD_RESULTS)
    results["tb"] = f"tb_{_HIER_TOP}_full.v"
    results["dut"] = _HIER_TOP
    (sim / "results.json").write_text(json.dumps(results, indent=2))
    return proj, rtl, sim


def test_l9_top_absent_from_module_set_blames_l9_not_the_tb(tmp_path):
    """#760 — the FAIL must name the declaration, never the testbench."""
    proj, rtl, sim = _make_hierarchical_project(tmp_path, l9_top="SPI")
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    rules = [f["rule"] for f in result["findings"]]
    # The testbench instantiates the design's real top, so blaming it is the
    # defect this test pins.
    assert "TB_INSTANTIATES_TOP" not in rules, result
    assert "TOP_MODULE_NOT_IN_MODULE_SET" in rules, result
    bad = next(f for f in result["findings"]
               if f["rule"] == "TOP_MODULE_NOT_IN_MODULE_SET")
    assert bad["declared_top"] == "SPI"
    assert "L9_INTEGRATION_SPEC.json" in bad["source"]
    # …and the requirement is restated against the top the DESIGN implies.
    assert result["top_module"] == _HIER_TOP, result
    assert result["top_module_resolution"]["source"] == \
        "design instantiation root"


def test_refuted_l9_top_still_bites_a_tb_that_instantiates_nothing(tmp_path):
    """The gate's real purpose survives: the pad path must still be bound."""
    empty_tb = """\
module tb_chip_top_asic_full;
    wire acc_id;
    reg  drive;
    initial begin
        drive = 0; #1800;
        drive = 1; #7100;
        $finish;
    end
endmodule
"""
    proj, rtl, sim = _make_hierarchical_project(tmp_path, l9_top="SPI",
                                                tb_text=empty_tb)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False, result
    rules = [f["rule"] for f in result["findings"]]
    assert "TB_INSTANTIATES_TOP" in rules, result
    tb_fail = next(f for f in result["findings"]
                   if f["rule"] == "TB_INSTANTIATES_TOP")
    assert f"`{_HIER_TOP}`" in tb_fail["message"], tb_fail


def test_refuted_l9_top_still_bites_a_tb_that_binds_only_a_child(tmp_path):
    """A testbench may not self-certify by binding an arbitrary submodule."""
    child_tb = _HIER_TB.replace(f"{_HIER_TOP} u_dut", f"{_HIER_CHILD} u_dut")
    proj, rtl, sim = _make_hierarchical_project(tmp_path, l9_top="SPI",
                                                tb_text=child_tb)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["pass"] is False, result
    assert any(f["rule"] == "TB_INSTANTIATES_TOP"
               for f in result["findings"]), result


def test_l9_top_present_in_module_set_is_untouched(tmp_path):
    """NO-RELAXATION invariant: a declaration the design backs still rules."""
    proj, rtl, sim = _make_hierarchical_project(tmp_path, l9_top=_HIER_CHILD)
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    # L9 names a real (if wrong-role) module, so the gate does NOT second-guess
    # it — and the testbench, which binds chip_top_asic, fails against it.
    assert result["top_module"] == _HIER_CHILD, result
    assert not any(f["rule"] == "TOP_MODULE_NOT_IN_MODULE_SET"
                   for f in result["findings"]), result
    assert any(f["rule"] == "TB_INSTANTIATES_TOP"
               for f in result["findings"]), result


def test_explicit_top_absent_from_module_set_names_the_flag(tmp_path):
    """An operator flag is a declaration too, and is refuted the same way."""
    proj, rtl, sim = _make_hierarchical_project(tmp_path)
    result = gate.check(proj, rtl, sim, top="not_a_module",
                        min_distinct=10, min_opcodes=3, do_run=False)
    bad = [f for f in result["findings"]
           if f["rule"] == "TOP_MODULE_NOT_IN_MODULE_SET"]
    assert bad, result
    assert bad[0]["source"] == "--top"
    assert bad[0]["declared_top"] == "not_a_module"
    assert not any(f["rule"] == "TB_INSTANTIATES_TOP"
                   for f in result["findings"]), result


def test_empty_module_set_refutes_nothing(tmp_path):
    """An unreadable design must not become a finding against a declaration."""
    proj, rtl, sim = _make_project(tmp_path, top="aid_top", write_rtl=False)
    gen = proj / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "aid_top"}))
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    assert result["top_module"] == "aid_top", result
    assert not any(f["rule"] == "TOP_MODULE_NOT_IN_MODULE_SET"
                   for f in result["findings"]), result
    assert result["top_module_resolution"]["verdict"] == "unverifiable"


def test_ambiguous_hierarchy_states_no_top_requirement(tmp_path):
    """Two roots is a non-answer — the gate says so, it does not guess."""
    proj, rtl, sim = _make_hierarchical_project(tmp_path, l9_top="SPI")
    (rtl / "other_root.v").write_text(
        "module other_root(input clk);\nendmodule\n")
    result = gate.check(proj, rtl, sim, top=None,
                        min_distinct=10, min_opcodes=3, do_run=False)
    rules = [f["rule"] for f in result["findings"]]
    assert "TOP_MODULE_NOT_IN_MODULE_SET" in rules, result
    assert "TOP_MODULE_RESOLVED" in rules, result
    assert "TB_INSTANTIATES_TOP" not in rules, result
    unresolved = next(f for f in result["findings"]
                      if f["rule"] == "TOP_MODULE_RESOLVED")
    assert "SPI" in unresolved["message"], unresolved


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

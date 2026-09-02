"""Unit tests for testbench_exists_check.py.

Tests verify correct detection of testbench files and minimum test coverage,
including missing testbenches, insufficient tests, and subdirectory discovery.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'testbench_exists_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import testbench_exists_check as tbc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: testbench templates
# ---------------------------------------------------------------------------
def make_tb_with_n_tests(n: int) -> str:
    """Generate a testbench with n $display("TEST ...") / $display("PASS") lines."""
    lines = [
        "`timescale 1ns/1ps",
        "module my_design_tb;",
        "  reg clk, rst_n;",
        "  wire [7:0] data_out;",
        "",
        "  my_design uut (.clk(clk), .rst_n(rst_n), .data_out(data_out));",
        "",
        "  initial begin",
        "    clk = 0;",
        "    forever #5 clk = ~clk;",
        "  end",
        "",
        "  initial begin",
        "    rst_n = 0;",
        "    #20 rst_n = 1;",
    ]
    for i in range(1, n + 1):
        if i % 2 == 1:
            lines.append(f'    #10; $display("TEST {i}: checking output {i}");')
        else:
            lines.append(f'    #10; $display("PASS: test case {i}");')
    lines += [
        "    #100;",
        "    $finish;",
        "  end",
        "endmodule",
    ]
    return "\n".join(lines)


TB_15_TESTS = make_tb_with_n_tests(15)
TB_5_TESTS = make_tb_with_n_tests(5)
TB_0_TESTS = """\
`timescale 1ns/1ps
module my_design_tb;
  reg clk;
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end
  initial begin
    #1000;
    $finish;
  end
endmodule
"""

EMPTY_TB = """\
// Empty testbench
"""

ASSERT_TB = """\
`timescale 1ns/1ps
module assert_tb;
  reg a, b;
  wire y;
  my_design uut (.a(a), .b(b), .y(y));
  initial begin
    a = 0; b = 0; #10;
    assert(y == 0);
    a = 1; b = 0; #10;
    assert(y == 1);
    a = 0; b = 1; #10;
    assert(y == 1);
    a = 1; b = 1; #10;
    assert(y == 1);
    assert(y !== 1'bx);
    $display("TEST 1: basic logic");
    $display("TEST 2: edge case");
    $display("TEST 3: final check");
    $display("PASS: all assertions passed");
    $display("PASS: no X values");
    $display("PASS: timing correct");
    $finish;
  end
endmodule
"""


# ===========================================================================
# Test 1: Testbench with 15 tests — PASS (min=10)
# ===========================================================================
class TestSufficientTests:
    def test_15_tests_pass(self, tmp_path):
        """Testbench with 15 tests, min=10 → PASS."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design_tb.v").write_text(TB_15_TESTS)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        assert len([f for f in findings if f.severity == "ERROR"]) == 0
        assert infos[0].test_count >= 10

    def test_cli_pass(self, tmp_path):
        """CLI returns exit 0 with sufficient tests."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design_tb.v").write_text(TB_15_TESTS)
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-dir', str(rtl),
             '--min-tests', '10',
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(report.read_text())
        assert data["summary"]["pass"] is True


# ===========================================================================
# Test 2: Testbench with 5 tests — FAIL (min=10)
# ===========================================================================
class TestInsufficientTests:
    def test_5_tests_fail(self, tmp_path):
        """Testbench with 5 tests, min=10 → FAIL."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design_tb.v").write_text(TB_5_TESTS)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) >= 1
        assert any(f.category == "INSUFFICIENT_TESTS" for f in error_findings)

    def test_cli_fail_insufficient(self, tmp_path):
        """CLI returns exit 1 when tests are below minimum."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design_tb.v").write_text(TB_5_TESTS)

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-dir', str(rtl),
             '--min-tests', '10'],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 3: No testbench — FAIL
# ===========================================================================
class TestNoTestbench:
    def test_no_tb_files(self, tmp_path):
        """No testbench files → NO_TESTBENCH finding."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design.v").write_text("module my_design(); endmodule")
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        assert len(findings) >= 1
        assert findings[0].category == "NO_TESTBENCH"

    def test_cli_no_tb(self, tmp_path):
        """CLI returns exit 1 when no testbench found."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design.v").write_text("module my_design(); endmodule")

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-dir', str(rtl)],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 4: Multiple testbench files — aggregate count
# ===========================================================================
class TestMultipleTestbenches:
    def test_two_tbs_aggregate(self, tmp_path):
        """Two testbenches with 5 tests each → total 10 → PASS with min=10."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "module_a_tb.v").write_text(TB_5_TESTS)
        (rtl / "module_b_tb.v").write_text(TB_5_TESTS)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        total = sum(i.test_count for i in infos)
        assert total >= 10
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) == 0


# ===========================================================================
# Test 5: Testbench in subdirectory
# ===========================================================================
class TestSubdirectoryTb:
    def test_tb_in_subdir(self, tmp_path):
        """Testbench in rtl/tb/ subdirectory should be found."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        tb_dir = rtl / "phase2" / "stage1" / "tb"
        tb_dir.mkdir(parents=True)
        (tb_dir / "my_design_tb.v").write_text(TB_15_TESTS)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        assert len(infos) >= 1
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) == 0


# ===========================================================================
# Test 6: Empty testbench — FAIL
# ===========================================================================
class TestEmptyTestbench:
    def test_empty_tb(self, tmp_path):
        """Testbench file with only a comment → EMPTY_TESTBENCH."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "my_design_tb.v").write_text(EMPTY_TB)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) >= 1


# ===========================================================================
# Test 7: Assert-based testbench counting
# ===========================================================================
class TestAssertCounting:
    def test_assert_patterns(self, tmp_path):
        """Testbench using assert() should count each assert as a test."""
        rtl = tmp_path / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "assert_tb.sv").write_text(ASSERT_TB)
        findings, infos = tbc.audit_testbenches(rtl, min_tests=10)
        assert infos[0].test_count >= 10
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) == 0


# ===========================================================================
# Test 8: RTL directory does not exist
# ===========================================================================
class TestRtlDirMissing:
    def test_nonexistent_dir(self, tmp_path):
        """Non-existent RTL directory → NO_TESTBENCH."""
        findings, infos = tbc.audit_testbenches(tmp_path / "nonexistent", min_tests=10)
        assert len(findings) >= 1
        assert findings[0].category == "NO_TESTBENCH"


# ===========================================================================
# Test 9: the generator's OWN unit TBs are discovered by DIRECTORY
#
# MEASURED on spm x gf180mcuD, plugin 1.15.67, 2026-09-02. The run emitted
# 5/5 L10 unit testbenches into `phase2/stage1/sim/tb/`, named for the test
# case rather than `tb_*` — `reset.v`, `corner_operand.v`,
# `random_multiplication_functional_equivalence.v`, `case_3.v`,
# `toggle_branch_coverage.v` — and this gate reported INSUFFICIENT_TESTS
# (7 found, 10 required) over a tree that carried 12. The producer
# (`design_one_shot_runner.step_l10_unit_tb_gen`) and this discoverer
# disagreed about what a testbench is CALLED, and only the discoverer was
# consulted. No amount of design-side test authoring clears that.
#
# BIDIRECTIONAL, on purpose (flow-change-acceptance): the first test fails
# against the pre-fix name-pattern-only discovery, and the second one holds
# in BOTH directions so the fix cannot be "find everything".
# ===========================================================================
class TestTbDirectoryDiscovery:
    def test_files_in_a_tb_directory_are_found_whatever_they_are_named(self, tmp_path):
        """A source file inside `tb/` is a testbench even with no tb_ prefix.

        NEGATIVE CONTROL for the fix: with name-pattern discovery alone this
        directory yields zero files and the gate reports NO_TESTBENCH.
        """
        stage = tmp_path / "phase2" / "stage1"
        (stage / "rtl").mkdir(parents=True)
        (stage / "rtl" / "dut.v").write_text("module dut(); endmodule\n")
        tb = stage / "sim" / "tb"
        tb.mkdir(parents=True)
        for name in ("reset.v", "corner_operand.v",
                     "random_multiplication_functional_equivalence.v"):
            (tb / name).write_text(make_tb_with_n_tests(4))

        found = {p.name for p in tbc.find_testbenches(stage)}
        assert found == {"reset.v", "corner_operand.v",
                         "random_multiplication_functional_equivalence.v"}, found

        findings, infos = tbc.audit_testbenches(stage, min_tests=10)
        assert [f for f in infos], "no testbench info produced"
        assert not [f for f in findings
                    if f.category in ("NO_TESTBENCH", "INSUFFICIENT_TESTS")], \
            [f.message for f in findings]

    def test_directory_discovery_does_not_swallow_non_testbench_trees(self, tmp_path):
        """`rtl/` beside it stays RTL, and non-source files in `tb/` are not tests.

        THE OVER-REACH CONTROL. The assertions below are all NEGATIVE — they
        name what must never be returned — so they hold against the pre-fix
        discovery too and can only be broken by a fix that widens too far.
        The single positive assertion is kept out of this test on purpose;
        the test above owns the direction the fix adds.
        """
        stage = tmp_path / "phase2" / "stage1"
        rtl = stage / "rtl"
        rtl.mkdir(parents=True)
        (rtl / "dut.v").write_text("module dut(); endmodule\n")
        (rtl / "adder.sv").write_text("module adder(); endmodule\n")
        tb = stage / "sim" / "tb"
        tb.mkdir(parents=True)
        (tb / "reset.v").write_text(make_tb_with_n_tests(12))
        (tb / "results.xml").write_text("<testsuite/>\n")
        (tb / "waves.vcd").write_text("$date\n")

        found = {p.name for p in tbc.find_testbenches(stage)}
        assert "results.xml" not in found, found
        assert "waves.vcd" not in found, found
        assert "dut.v" not in found, found
        assert "adder.sv" not in found, found

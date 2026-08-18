"""Unit tests for pdk_consistency_check.py.

Tests verify that the program correctly detects PDK-netlist mismatches,
including wrong-PDK cells, missing liberty files, and empty netlists.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'pdk_consistency_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import pdk_consistency_check as pcc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: sample liberty content
# ---------------------------------------------------------------------------
SKY130_LIB = """\
library (sky130_fd_sc_hd__tt_025C_1v80) {
  cell (sky130_fd_sc_hd__inv_2) {
    pin(A) { direction: input; }
    pin(Y) { direction: output; }
  }
  cell (sky130_fd_sc_hd__and2_1) {
    pin(A) { direction: input; }
    pin(B) { direction: input; }
    pin(X) { direction: output; }
  }
  cell (sky130_fd_sc_hd__buf_1) {
    pin(A) { direction: input; }
    pin(X) { direction: output; }
  }
  cell (sky130_fd_sc_hd__dfxtp_1) {
    pin(CLK) { direction: input; }
    pin(D) { direction: input; }
    pin(Q) { direction: output; }
  }
  cell (sky130_fd_sc_hd__mux2_1) {
    pin(A0) { direction: input; }
    pin(A1) { direction: input; }
    pin(S) { direction: input; }
    pin(X) { direction: output; }
  }
}
"""

GF180_LIB = """\
library (gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30) {
  cell (gf180mcu_fd_sc_mcu7t5v0__inv_1) {
    pin(I) { direction: input; }
    pin(ZN) { direction: output; }
  }
  cell (gf180mcu_fd_sc_mcu7t5v0__buf_1) {
    pin(I) { direction: input; }
    pin(Z) { direction: output; }
  }
  cell (gf180mcu_fd_sc_mcu7t5v0__and2_1) {
    pin(A1) { direction: input; }
    pin(A2) { direction: input; }
    pin(Z) { direction: output; }
  }
}
"""

SKY130_NETLIST = """\
module my_design (
    input wire clk,
    input wire rst_n,
    output wire [7:0] data_out
);
    wire n1, n2, n3;
    sky130_fd_sc_hd__inv_2 _001_ (.A(rst_n), .Y(n1));
    sky130_fd_sc_hd__and2_1 _002_ (.A(clk), .B(n1), .X(n2));
    sky130_fd_sc_hd__buf_1 _003_ (.A(n2), .X(n3));
    sky130_fd_sc_hd__dfxtp_1 _004_ (.CLK(clk), .D(n3), .Q(data_out[0]));
    sky130_fd_sc_hd__mux2_1 _005_ (.A0(n1), .A1(n2), .S(n3), .X(data_out[1]));
endmodule
"""

GF180_IN_SKY130_NETLIST = """\
module my_design (
    input wire clk,
    input wire rst_n,
    output wire [7:0] data_out
);
    wire n1, n2;
    gf180mcu_fd_sc_mcu7t5v0__inv_1 _001_ (.I(rst_n), .ZN(n1));
    gf180mcu_fd_sc_mcu7t5v0__buf_1 _002_ (.I(n1), .Z(n2));
    gf180mcu_fd_sc_mcu7t5v0__and2_1 _003_ (.A1(clk), .A2(n2), .Z(data_out[0]));
endmodule
"""

EMPTY_NETLIST = """\
// Empty synthesized netlist
module my_design (
    input wire clk,
    output wire out
);
endmodule
"""

PROJECT_JSON_SKY130 = json.dumps({"pdk": "sky130", "top_module": "my_design"})


# ===========================================================================
# Test 1: All cells match PDK — PASS
# ===========================================================================
class TestAllCellsMatch:
    def test_sky130_netlist_with_sky130_lib(self):
        """All netlist cells exist in SKY130 liberty → PASS."""
        cells = pcc.extract_netlist_cells(SKY130_NETLIST, "netlist.v")
        pdk_cells = pcc.extract_liberty_cells(SKY130_LIB)
        findings = pcc.audit_pdk_consistency(cells, pdk_cells, "sky130")
        assert len(findings) == 0

    def test_cli_pass(self, tmp_path):
        """CLI returns exit 0 when all cells match."""
        nl = tmp_path / "netlist.v"
        nl.write_text(SKY130_NETLIST)
        lib = tmp_path / "sky130.lib"
        lib.write_text(SKY130_LIB)
        pj = tmp_path / "project.json"
        pj.write_text(PROJECT_JSON_SKY130)
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--netlist', str(nl),
             '--project-json', str(pj),
             '--pdk-lib', str(lib),
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(report.read_text())
        assert data["summary"]["pass"] is True
        assert data["summary"]["total_cell_instances"] == 5


# ===========================================================================
# Test 2: Wrong PDK cells (GF180 cells in SKY130 lib) — FAIL
# ===========================================================================
class TestWrongPdkCells:
    def test_gf180_cells_in_sky130_lib(self):
        """GF180 cells checked against SKY130 lib → all should be missing."""
        cells = pcc.extract_netlist_cells(GF180_IN_SKY130_NETLIST, "netlist.v")
        pdk_cells = pcc.extract_liberty_cells(SKY130_LIB)
        findings = pcc.audit_pdk_consistency(cells, pdk_cells, "sky130")
        error_findings = [f for f in findings if f.severity == "ERROR"]
        assert len(error_findings) >= 3  # 3 missing cells + 1 PDK_MISMATCH
        categories = {f.category for f in error_findings}
        assert "CELL_NOT_IN_PDK" in categories
        assert "PDK_MISMATCH" in categories

    def test_cli_fail_wrong_pdk(self, tmp_path):
        """CLI returns exit 1 when cells don't match PDK."""
        nl = tmp_path / "netlist.v"
        nl.write_text(GF180_IN_SKY130_NETLIST)
        lib = tmp_path / "sky130.lib"
        lib.write_text(SKY130_LIB)
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--netlist', str(nl),
             '--pdk-lib', str(lib),
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 1
        data = json.loads(report.read_text())
        assert data["summary"]["pass"] is False


# ===========================================================================
# Test 3: Missing liberty file — still runs, but all cells missing
# ===========================================================================
class TestMissingLib:
    def test_nonexistent_lib_file(self, tmp_path):
        """When liberty file doesn't exist, all cells are 'not in PDK'."""
        nl = tmp_path / "netlist.v"
        nl.write_text(SKY130_NETLIST)
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--netlist', str(nl),
             '--pdk-lib', str(tmp_path / "nonexistent.lib"),
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 4: Empty netlist — no cells found
# ===========================================================================
class TestEmptyNetlist:
    def test_no_cells_in_netlist(self):
        """Netlist with no cell instances → NO_CELLS finding."""
        cells = pcc.extract_netlist_cells(EMPTY_NETLIST, "empty.v")
        pdk_cells = pcc.extract_liberty_cells(SKY130_LIB)
        findings = pcc.audit_pdk_consistency(cells, pdk_cells, "sky130")
        assert len(findings) == 1
        assert findings[0].category == "NO_CELLS"

    def test_cli_empty_netlist(self, tmp_path):
        """CLI returns exit 1 for empty netlist."""
        nl = tmp_path / "netlist.v"
        nl.write_text(EMPTY_NETLIST)
        lib = tmp_path / "sky130.lib"
        lib.write_text(SKY130_LIB)

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--netlist', str(nl),
             '--pdk-lib', str(lib)],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 5: Netlist file does not exist
# ===========================================================================
class TestNetlistNotFound:
    def test_missing_netlist_file(self, tmp_path):
        """CLI returns exit 2 when netlist file doesn't exist."""
        lib = tmp_path / "sky130.lib"
        lib.write_text(SKY130_LIB)

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--netlist', str(tmp_path / "nonexistent.v"),
             '--pdk-lib', str(lib)],
            capture_output=True, text=True)
        assert res.returncode == 2


# ===========================================================================
# Test 6: Mixed cells — some match, some don't
# ===========================================================================
class TestMixedCells:
    def test_partial_match(self):
        """Some cells match, some don't → CELL_NOT_IN_PDK for missing ones."""
        mixed_netlist = """\
module mixed (input a, output z);
    wire n1;
    sky130_fd_sc_hd__inv_2 _01_ (.A(a), .Y(n1));
    UNKNOWN_CELL_X1 _02_ (.I(n1), .Z(z));
endmodule
"""
        cells = pcc.extract_netlist_cells(mixed_netlist, "mixed.v")
        pdk_cells = pcc.extract_liberty_cells(SKY130_LIB)
        findings = pcc.audit_pdk_consistency(cells, pdk_cells, "sky130")
        missing_findings = [f for f in findings if f.category == "CELL_NOT_IN_PDK"]
        assert len(missing_findings) == 1
        assert missing_findings[0].cell_name == "UNKNOWN_CELL_X1"


# ===========================================================================
# Test 7: Liberty extraction correctness
# ===========================================================================
class TestLibertyExtraction:
    def test_sky130_cell_count(self):
        """SKY130 liberty should have 5 cells."""
        cells = pcc.extract_liberty_cells(SKY130_LIB)
        assert len(cells) == 5
        assert "sky130_fd_sc_hd__inv_2" in cells
        assert "sky130_fd_sc_hd__dfxtp_1" in cells

    def test_gf180_cell_count(self):
        """GF180 liberty should have 3 cells."""
        cells = pcc.extract_liberty_cells(GF180_LIB)
        assert len(cells) == 3
        assert "gf180mcu_fd_sc_mcu7t5v0__inv_1" in cells


# ===========================================================================
# Test 8: Netlist cell extraction — keyword filtering
# ===========================================================================
class TestNetlistExtraction:
    def test_keywords_not_extracted(self):
        """Verilog keywords (assign, wire, etc.) should NOT be extracted as cells."""
        netlist = """\
module test (input a, output z);
    wire n1;
    assign z = n1;
    sky130_fd_sc_hd__inv_2 _01_ (.A(a), .Y(n1));
endmodule
"""
        cells = pcc.extract_netlist_cells(netlist, "test.v")
        cell_names = [c['cell_name'] for c in cells]
        assert "assign" not in cell_names
        assert "wire" not in cell_names
        assert "sky130_fd_sc_hd__inv_2" in cell_names

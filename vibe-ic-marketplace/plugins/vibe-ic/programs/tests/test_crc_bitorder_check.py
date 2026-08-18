"""Unit tests for crc_bitorder_check.py.

Verifies:
  1. Direct assignment detection (no bit reversal)
  2. Bit-reversed concatenation detection (ascending bit indices)
  3. Reverse function / streaming operator detection
  4. No CRC loading found (INFO status)
  5. Multiple CRC loads with conflicting methods (WARN)
  6. Multi-line concatenation (collapsed into single-line for matching)
  7. Bitwise NOT vs bit reversal confusion (WARN)
  8. Descending concatenation (same as direct — MSB-first)
  9. CLI black-box test (JSON report generation)
  10. Partial reordering detection (nibble swap)
"""
import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

SCRIPT = Path(__file__).parent.parent / 'crc_bitorder_check.py'
assert SCRIPT.exists(), f"script missing: {SCRIPT}"

# Import module directly for white-box tests
sys.path.insert(0, str(SCRIPT.parent))
import crc_bitorder_check as cbc  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: write RTL to a temp file and analyze
# ---------------------------------------------------------------------------
def _analyze(tmp_path, rtl_text: str, crc_signal: str = 'crc8_result',
             filename: str = 'dut.v'):
    f = tmp_path / filename
    f.write_text(rtl_text)
    findings = cbc.analyze_file(str(f), crc_signal)
    return findings


# ===========================================================================
# Test Case 1: Direct assignment (no reversal)
# ===========================================================================
class TestDirectAssignment:
    RTL = dedent("""\
        module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
            reg [7:0] crc8_result;
            always @(posedge clk) begin
                tx_data_byte <= crc8_result;
            end
        endmodule
    """)

    def test_detects_direct_assignment(self, tmp_path):
        findings = _analyze(tmp_path, self.RTL)
        assert len(findings) == 1
        f = findings[0]
        assert f.loading_method == 'DIRECT'
        assert f.bit_order == 'MSB_FIRST'
        assert f.status == 'PASS'
        assert f.target_reg == 'tx_data_byte'

    def test_direct_with_slice(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= crc8_result[7:0];
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'DIRECT'
        assert findings[0].bit_order == 'MSB_FIRST'


# ===========================================================================
# Test Case 2: Bit-reversed concatenation
# ===========================================================================
class TestBitReversedConcat:
    RTL = dedent("""\
        module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
            reg [7:0] crc8_result;
            always @(posedge clk) begin
                tx_data_byte <= {crc8_result[0], crc8_result[1], crc8_result[2], crc8_result[3], crc8_result[4], crc8_result[5], crc8_result[6], crc8_result[7]};
            end
        endmodule
    """)

    def test_detects_bit_reversal(self, tmp_path):
        findings = _analyze(tmp_path, self.RTL)
        assert len(findings) == 1
        f = findings[0]
        assert f.loading_method == 'REVERSED'
        assert f.bit_order == 'LSB_FIRST'
        assert f.status == 'PASS'
        assert f.target_reg == 'tx_data_byte'

    def test_descending_concat_is_direct(self, tmp_path):
        """Concatenation with descending indices {crc[7],...,crc[0]} = direct."""
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= {crc8_result[7], crc8_result[6], crc8_result[5], crc8_result[4], crc8_result[3], crc8_result[2], crc8_result[1], crc8_result[0]};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'DIRECT'
        assert findings[0].bit_order == 'MSB_FIRST'


# ===========================================================================
# Test Case 3: Reverse function / streaming operator
# ===========================================================================
class TestReverseFunction:
    def test_reverse_bits_function(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= reverse_bits(crc8_result);
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'FUNCTION'
        assert findings[0].bit_order == 'LSB_FIRST'
        assert findings[0].status == 'PASS'

    def test_bit_reverse_function(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc8_result;
                assign tx_data = bit_reverse(crc8_result);
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'FUNCTION'

    def test_sv_streaming_operator(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= {<<{crc8_result}};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'FUNCTION'
        assert findings[0].bit_order == 'LSB_FIRST'

    def test_sv_streaming_operator_with_width(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= {<<1{crc8_result}};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'FUNCTION'


# ===========================================================================
# Test Case 4: No CRC loading found
# ===========================================================================
class TestNoCrcFound:
    def test_no_crc_signal_in_file(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] some_other_signal;
                always @(posedge clk) begin
                    tx_data <= some_other_signal;
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 0

        report = cbc.build_report('crc8_result', ['dut.v'], findings)
        assert report.summary_status == 'INFO'
        assert 'No CRC loading pattern' in report.summary_message

    def test_crc_signal_only_in_declaration(self, tmp_path):
        """CRC signal declared but never loaded into a TX register."""
        rtl = dedent("""\
            module tx_phy (input wire clk);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    crc8_result <= 8'hFF;
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        # Self-assignment (crc8_result <= X) is excluded
        assert len(findings) == 0

    def test_file_not_found(self, tmp_path):
        findings = cbc.analyze_file('/nonexistent/path.v', 'crc8_result')
        assert len(findings) == 1
        assert findings[0].loading_method == 'ERROR'
        assert findings[0].status == 'WARN'


# ===========================================================================
# Test Case 5: Multiple CRC loads (conflicting methods)
# ===========================================================================
class TestMultipleCrcLoads:
    def test_conflicting_methods_warns(self, tmp_path):
        """Two different loading methods in the same file = WARN."""
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_a, tx_data_b);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_a <= crc8_result;
                    tx_data_b <= {crc8_result[0], crc8_result[1], crc8_result[2], crc8_result[3], crc8_result[4], crc8_result[5], crc8_result[6], crc8_result[7]};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 2
        methods = {f.loading_method for f in findings}
        assert 'DIRECT' in methods
        assert 'REVERSED' in methods

        report = cbc.build_report('crc8_result', ['dut.v'], findings)
        assert report.summary_status == 'WARN'
        assert 'Multiple CRC loading methods' in report.summary_message

    def test_consistent_methods_pass(self, tmp_path):
        """Two direct assignments = PASS."""
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_a, tx_data_b);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_a <= crc8_result;
                    tx_data_b <= crc8_result;
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 2
        assert all(f.loading_method == 'DIRECT' for f in findings)

        report = cbc.build_report('crc8_result', ['dut.v'], findings)
        assert report.summary_status == 'PASS'

    def test_multiple_files(self, tmp_path):
        """CRC loaded differently across two files."""
        rtl_a = dedent("""\
            module tx_a (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc_out;
                always @(posedge clk) tx_data <= crc_out;
            endmodule
        """)
        rtl_b = dedent("""\
            module tx_b (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc_out;
                always @(posedge clk) tx_data <= reverse_bits(crc_out);
            endmodule
        """)
        (tmp_path / 'a.v').write_text(rtl_a)
        (tmp_path / 'b.v').write_text(rtl_b)
        findings_a = cbc.analyze_file(str(tmp_path / 'a.v'), 'crc_out')
        findings_b = cbc.analyze_file(str(tmp_path / 'b.v'), 'crc_out')
        all_findings = findings_a + findings_b
        report = cbc.build_report('crc_out', ['a.v', 'b.v'], all_findings)
        assert report.summary_status == 'WARN'
        assert 'Multiple CRC loading methods' in report.summary_message


# ===========================================================================
# Test Case 6: Multi-line concatenation
# ===========================================================================
class TestMultiLineConcat:
    def test_multiline_reversed_concat(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= {crc8_result[0],
                                     crc8_result[1],
                                     crc8_result[2],
                                     crc8_result[3],
                                     crc8_result[4],
                                     crc8_result[5],
                                     crc8_result[6],
                                     crc8_result[7]};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'REVERSED'
        assert findings[0].bit_order == 'LSB_FIRST'


# ===========================================================================
# Test Case 7: Bitwise NOT confusion
# ===========================================================================
class TestBitwiseNotConfusion:
    def test_tilde_is_not_reversal(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data <= ~crc8_result;
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'UNKNOWN'
        assert findings[0].status == 'WARN'
        assert 'NOT bit reversal' in findings[0].message


# ===========================================================================
# Test Case 8: Partial reordering (nibble swap)
# ===========================================================================
class TestPartialReorder:
    def test_nibble_swap_detected(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data <= {crc8_result[3:0], crc8_result[7:4]};
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'PARTIAL'
        assert findings[0].status == 'WARN'


# ===========================================================================
# Test Case 9: Comment stripping
# ===========================================================================
class TestCommentStripping:
    def test_commented_out_assignment_ignored(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    // tx_data <= crc8_result;
                    /* tx_data <= {crc8_result[0], crc8_result[7]}; */
                    tx_data <= reverse_bits(crc8_result);
                end
            endmodule
        """)
        findings = _analyze(tmp_path, rtl)
        assert len(findings) == 1
        assert findings[0].loading_method == 'FUNCTION'


# ===========================================================================
# Test Case 10: CLI black-box test
# ===========================================================================
class TestCli:
    def _run(self, args, tmp_path):
        cmd = [sys.executable, str(SCRIPT)] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_generates_json_report(self, tmp_path):
        rtl = tmp_path / 'tx_phy.v'
        rtl.write_text(dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data_byte);
                reg [7:0] crc8_result;
                always @(posedge clk) begin
                    tx_data_byte <= crc8_result;
                end
            endmodule
        """))
        out_dir = tmp_path / 'out'
        res = self._run([
            '--rtl-files', str(rtl),
            '--crc-signal', 'crc8_result',
            '--out-dir', str(out_dir),
        ], tmp_path)
        assert res.returncode == 0, f"stdout:{res.stdout}\nstderr:{res.stderr}"
        report_file = out_dir / 'crc_bitorder_report.json'
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report['crc_signal'] == 'crc8_result'
        assert report['summary_status'] == 'PASS'
        assert len(report['findings']) == 1
        assert report['findings'][0]['loading_method'] == 'DIRECT'

    def test_cli_warn_exit_code(self, tmp_path):
        """WARN findings should exit with code 1."""
        rtl = tmp_path / 'tx_phy.v'
        rtl.write_text(dedent("""\
            module tx_phy (input wire clk, output reg [7:0] tx_data);
                reg [7:0] crc8_result;
                always @(posedge clk) tx_data <= ~crc8_result;
            endmodule
        """))
        out_dir = tmp_path / 'out'
        res = self._run([
            '--rtl-files', str(rtl),
            '--crc-signal', 'crc8_result',
            '--out-dir', str(out_dir),
        ], tmp_path)
        assert res.returncode == 1

    def test_cli_no_findings_exit_zero(self, tmp_path):
        """No findings (INFO) should exit with code 0."""
        rtl = tmp_path / 'empty.v'
        rtl.write_text("module empty(); endmodule\n")
        out_dir = tmp_path / 'out'
        res = self._run([
            '--rtl-files', str(rtl),
            '--crc-signal', 'crc8_result',
            '--out-dir', str(out_dir),
        ], tmp_path)
        assert res.returncode == 0
        report = json.loads((out_dir / 'crc_bitorder_report.json').read_text())
        assert report['summary_status'] == 'INFO'


# ===========================================================================
# Test Case 11: CRC signal with different widths
# ===========================================================================
class TestDifferentCrcWidths:
    def test_crc16_direct(self, tmp_path):
        rtl = dedent("""\
            module tx_phy (input wire clk, output reg [15:0] tx_data);
                reg [15:0] crc16_out;
                always @(posedge clk) tx_data <= crc16_out;
            endmodule
        """)
        findings = _analyze(tmp_path, rtl, crc_signal='crc16_out')
        assert len(findings) == 1
        assert findings[0].loading_method == 'DIRECT'

    def test_crc32_reversed(self, tmp_path):
        bits = ', '.join(f'crc32_out[{i}]' for i in range(32))
        rtl = dedent(f"""\
            module tx_phy (input wire clk, output reg [31:0] tx_data);
                reg [31:0] crc32_out;
                always @(posedge clk) tx_data <= {{{bits}}};
            endmodule
        """)
        findings = _analyze(tmp_path, rtl, crc_signal='crc32_out')
        assert len(findings) == 1
        assert findings[0].loading_method == 'REVERSED'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

"""Unit tests for phy_counter_audit.py.

Each test synthesizes a small Verilog snippet and verifies the audit correctly
detects bus-state-sampling anti-patterns or passes clean time-based counters.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'phy_counter_audit.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import phy_counter_audit as pca  # noqa: E402


def run_cli(tmp_path, sv_content, filename='test_tx_phy.v'):
    """Write SV content to a temp file and run the CLI, returning (result, report)."""
    f = tmp_path / filename
    f.write_text(sv_content)
    out_dir = tmp_path / 'audit_out'
    res = subprocess.run(
        [sys.executable, str(SCRIPT),
         '--rtl-files', str(f),
         '--out-dir', str(out_dir)],
        capture_output=True, text=True)
    report_file = out_dir / 'phy_counter_audit_report.json'
    report = json.loads(report_file.read_text()) if report_file.exists() else {}
    return res, report


# -----------------------------------------------------------------------
# Test 1: Classic bus-sampling anti-pattern (USB-HID tester pattern)
# -----------------------------------------------------------------------
class TestBusSamplingDetection:
    def test_detects_bus_gated_low_counter(self, tmp_path):
        """Common anti-pattern: low_cnt gated by ~bus_rx (bus readback)."""
        sv = """
module tx_phy (input clk, input rst_n, input tx_data_enable);
    reg [7:0] low_cnt;
    reg [7:0] high_cnt;
    wire bus_rx;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            low_cnt  <= 8'd0;
            high_cnt <= 8'd0;
        end else if (tx_data_enable) begin
            if (~bus_rx)
                low_cnt <= low_cnt + 1;
            if (bus_rx)
                high_cnt <= high_cnt + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) >= 1
        signals = [f['signal'] for f in warnings]
        bus_sigs = [f['bus_signal'] for f in warnings]
        assert 'low_cnt' in signals or 'high_cnt' in signals
        assert any('bus_rx' in bs for bs in bus_sigs)

    def test_detects_bus_in_gated_counter(self, tmp_path):
        """Generic bus_in signal used to gate tx_low counter."""
        sv = """
module tx_driver (input clk, input rst_n, input tx_en);
    reg [15:0] tx_low;
    wire bus_in;

    always @(posedge clk) begin
        if (!rst_n)
            tx_low <= 0;
        else if (tx_en) begin
            if (!bus_in)
                tx_low <= tx_low + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) >= 1
        assert warnings[0]['signal'] == 'tx_low'
        assert 'bus_in' in warnings[0]['bus_signal']


# -----------------------------------------------------------------------
# Test 2: Clean time-based counter (should PASS)
# -----------------------------------------------------------------------
class TestTimeBasedDetection:
    def test_unconditional_counter_is_clean(self, tmp_path):
        """Vendor-correct pattern: count unconditionally, switch on count target."""
        sv = """
module tx_phy_good (input clk, input rst_n, input tx_data_enable);
    reg [7:0] low_cnt;
    reg [7:0] high_cnt;
    parameter LOW_TARGET = 8'd41;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            low_cnt  <= 8'd0;
            high_cnt <= 8'd0;
        end else if (tx_data_enable) begin
            if (low_cnt < LOW_TARGET)
                low_cnt <= low_cnt + 1;
            else
                high_cnt <= high_cnt + 1;
        end
    end
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) == 0
        assert report['summary']['verdict'] == 'PASS'

    def test_simple_timer_counter_is_clean(self, tmp_path):
        """A plain tx_cnt that increments unconditionally under tx_en."""
        sv = """
module tx_timer (input clk, input rst_n, input tx_en);
    reg [11:0] tx_cnt;

    always @(posedge clk) begin
        if (!rst_n)
            tx_cnt <= 0;
        else if (tx_en)
            tx_cnt <= tx_cnt + 1;
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) == 0
        clean = [f for f in report['findings'] if f['severity'] == 'CLEAN']
        assert len(clean) >= 1
        assert clean[0]['signal'] == 'tx_cnt'


# -----------------------------------------------------------------------
# Test 3: Mixed patterns (one bad, one good in same file)
# -----------------------------------------------------------------------
class TestMixedPatterns:
    def test_mixed_bus_and_time_counters(self, tmp_path):
        """File has both a bus-sampled counter and a time-based counter."""
        sv = """
module tx_mixed (input clk, input rst_n, input tx_data_enable);
    reg [7:0] low_cnt;
    reg [7:0] tx_cnt;
    wire sda_in;

    // BAD: bus-sampled
    always @(posedge clk) begin
        if (!rst_n)
            low_cnt <= 0;
        else if (tx_data_enable) begin
            if (!sda_in)
                low_cnt <= low_cnt + 1;
        end
    end

    // GOOD: time-based
    always @(posedge clk) begin
        if (!rst_n)
            tx_cnt <= 0;
        else if (tx_data_enable)
            tx_cnt <= tx_cnt + 1;
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        clean = [f for f in report['findings'] if f['severity'] == 'CLEAN']
        assert len(warnings) >= 1
        assert len(clean) >= 1
        assert warnings[0]['signal'] == 'low_cnt'
        assert clean[0]['signal'] == 'tx_cnt'


# -----------------------------------------------------------------------
# Test 4: I2C-style bus sampling (SDA/SCL)
# -----------------------------------------------------------------------
class TestI2CBusSampling:
    def test_scl_gated_counter_flagged(self, tmp_path):
        """I2C TX counter gated by scl_in readback."""
        sv = """
module i2c_tx (input clk, input rst_n, input tx_active);
    reg [7:0] tx_low;
    wire scl_in;

    always @(posedge clk) begin
        if (!rst_n)
            tx_low <= 0;
        else if (tx_active) begin
            if (~scl_in)
                tx_low <= tx_low + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) >= 1
        assert 'scl_in' in warnings[0]['bus_signal']


# -----------------------------------------------------------------------
# Test 5: No TX counters at all (empty result)
# -----------------------------------------------------------------------
class TestNoCounters:
    def test_file_without_tx_counters(self, tmp_path):
        """File with no TX counter keywords should produce no findings."""
        sv = """
module rx_only (input clk, input data_in, output reg [7:0] rx_data);
    reg [3:0] bit_cnt;
    always @(posedge clk) begin
        bit_cnt <= bit_cnt + 1;
        rx_data[bit_cnt] <= data_in;
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        assert report['summary']['total_counters_analyzed'] == 0
        assert report['summary']['verdict'] == 'PASS'


# -----------------------------------------------------------------------
# Test 6: Comments should not trigger false positives
# -----------------------------------------------------------------------
class TestCommentHandling:
    def test_commented_bus_sampling_not_flagged(self, tmp_path):
        """Bus-sampling code inside comments must not trigger warnings."""
        sv = """
module tx_phy (input clk, input rst_n, input tx_data_enable);
    reg [7:0] low_cnt;
    parameter TARGET = 8'd41;

    always @(posedge clk) begin
        if (!rst_n)
            low_cnt <= 0;
        else if (tx_data_enable) begin
            // OLD BAD CODE: if (~id_bus_rx_syn2) low_cnt <= low_cnt + 1;
            /* Also bad: if (bus_in) high_cnt <= high_cnt + 1; */
            if (low_cnt < TARGET)
                low_cnt <= low_cnt + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) == 0


# -----------------------------------------------------------------------
# Test 7: Multiple bus signals in one condition
# -----------------------------------------------------------------------
class TestMultipleBusSignals:
    def test_complex_condition_with_bus_signal(self, tmp_path):
        """Counter gated by a complex expression that includes a bus signal."""
        sv = """
module tx_complex (input clk, input rst_n, input tx_data_enable);
    reg [7:0] high_cnt;
    wire rx_syn;

    always @(posedge clk) begin
        if (!rst_n)
            high_cnt <= 0;
        else if (tx_data_enable) begin
            if (rx_syn && high_cnt < 8'd50)
                high_cnt <= high_cnt + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) >= 1
        assert warnings[0]['signal'] == 'high_cnt'
        assert 'rx_syn' in warnings[0]['bus_signal']


# -----------------------------------------------------------------------
# Test 8: CLI exit codes and report structure
# -----------------------------------------------------------------------
class TestCLIBehavior:
    def test_exit_code_zero_for_clean(self, tmp_path):
        """Clean file should produce exit code 0."""
        sv = """
module tx_clean (input clk, input rst_n, input tx_en);
    reg [7:0] tx_cnt;
    always @(posedge clk) begin
        if (!rst_n) tx_cnt <= 0;
        else if (tx_en) tx_cnt <= tx_cnt + 1;
    end
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        assert res.returncode == 0
        assert report['summary']['verdict'] == 'PASS'

    def test_exit_code_one_for_warning(self, tmp_path):
        """File with bus-sampling should produce exit code 1."""
        sv = """
module tx_bad (input clk, input rst_n, input tx_data_enable);
    reg [7:0] low_cnt;
    wire bus_in;
    always @(posedge clk) begin
        if (!rst_n) low_cnt <= 0;
        else if (tx_data_enable) begin
            if (~bus_in) low_cnt <= low_cnt + 1;
        end
    end
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        assert res.returncode == 1
        assert report['summary']['verdict'] == 'FAIL'

    def test_report_has_guidance(self, tmp_path):
        """Report should always include guidance section."""
        sv = """
module tx_any (input clk, input tx_en);
    reg [7:0] tx_cnt;
    always @(posedge clk) if (tx_en) tx_cnt <= tx_cnt + 1;
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        assert 'guidance' in report
        assert 'anti_pattern' in report['guidance']
        assert 'correct_pattern' in report['guidance']

    def test_missing_file_handled(self, tmp_path):
        """Passing a non-existent file should print a warning but not crash."""
        out_dir = tmp_path / 'out'
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-files', str(tmp_path / 'nonexistent.v'),
             '--out-dir', str(out_dir)],
            capture_output=True, text=True)
        assert 'WARNING: file not found' in res.stderr
        # Should still produce a report (empty)
        report_file = out_dir / 'phy_counter_audit_report.json'
        assert report_file.exists()


# -----------------------------------------------------------------------
# Test 9: SPI MISO readback pattern
# -----------------------------------------------------------------------
class TestSPIPattern:
    def test_miso_gated_counter_flagged(self, tmp_path):
        """SPI TX counter gated by MISO readback."""
        sv = """
module spi_tx (input clk, input rst_n, input tx_active);
    reg [7:0] tx_high;
    wire miso;

    always @(posedge clk) begin
        if (!rst_n)
            tx_high <= 0;
        else if (tx_active) begin
            if (miso)
                tx_high <= tx_high + 1;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        warnings = [f for f in report['findings'] if f['severity'] == 'WARNING']
        assert len(warnings) >= 1
        assert 'miso' in warnings[0]['bus_signal']


# -----------------------------------------------------------------------
# Whitebox tests for internal functions
# -----------------------------------------------------------------------
class TestInternalFunctions:
    def test_strip_comments(self):
        src = "wire a; // this is a comment\nwire b; /* block */\n"
        out = pca.strip_comments(src)
        assert 'comment' not in out
        assert 'block' not in out
        assert out.count('\n') == src.count('\n')

    def test_extract_always_blocks(self):
        src = """
always @(posedge clk) begin
    a <= b;
end
always_ff @(posedge clk) begin
    c <= d;
end
"""
        blocks = pca.extract_always_blocks(src)
        assert len(blocks) == 2

    def test_check_bus_sampling_in_condition(self):
        assert pca.check_bus_sampling_in_condition('~bus_rx') is not None
        assert pca.check_bus_sampling_in_condition('bus_in == 1') is not None
        assert pca.check_bus_sampling_in_condition('low_cnt < TARGET') is None
        assert pca.check_bus_sampling_in_condition('tx_data_enable') is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

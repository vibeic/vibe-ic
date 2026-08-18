"""Unit tests for oe_pattern_check.py.

Each test synthesizes a small Verilog snippet and verifies the OE pattern
classifier correctly identifies the pattern type and risk level.

Test cases:
  1. SINGLE_EDGE — OE registered on posedge only
  2. DUAL_EDGE — separate pos/neg edge registers combined with AND
  3. COMBINATIONAL — OE driven by continuous assign (no register)
  4. GATED — OE conditionally assigned based on bit index
  5. No OE found — clean design with no OE signals
  6. Mixed — multiple OE signals with different patterns in one file
  7. Cross-signal dual-edge — two SINGLE_EDGE signals combined → upgraded
  8. Tristate infer — OE detected from assign bus = oe ? data : 8'bz
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'oe_pattern_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import oe_pattern_check as opc  # noqa: E402


def run_cli(tmp_path, sv_content, extra_args=None):
    """Write SV to a temp file, run the CLI, return (result, report_dict)."""
    f = tmp_path / 'test.sv'
    f.write_text(sv_content)
    out_dir = tmp_path / 'out'
    cmd = [sys.executable, str(SCRIPT),
           '--rtl-files', str(f),
           '--out-dir', str(out_dir)]
    if extra_args:
        cmd.extend(extra_args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    report_path = out_dir / 'oe_pattern_report.json'
    if report_path.exists():
        report = json.loads(report_path.read_text())
    else:
        report = None
    return res, report


# ---------------------------------------------------------------------------
# Test 1: SINGLE_EDGE
# ---------------------------------------------------------------------------
class TestSingleEdge:
    def test_posedge_only_oe(self, tmp_path):
        """OE registered on posedge clk only → SINGLE_EDGE, MEDIUM risk."""
        sv = """
module tx_driver(input clk, input rst_n, input tx_en,
                 output reg tx_oe, output reg [7:0] tx_data);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            tx_oe <= 1'b0;
        else
            tx_oe <= tx_en;
    end
    always @(posedge clk) tx_data <= 8'hAB;
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        assert report is not None
        assert report['total_oe_signals'] >= 1
        tx_oe = [s for s in report['signals'] if s['name'] == 'tx_oe']
        assert len(tx_oe) == 1
        assert tx_oe[0]['pattern'] == 'SINGLE_EDGE'
        assert tx_oe[0]['risk'] == 'MEDIUM'
        assert 'posedge' in tx_oe[0]['edges']

    def test_negedge_only_oe(self, tmp_path):
        """OE registered on negedge clk only → SINGLE_EDGE, MEDIUM risk."""
        sv = """
module rx_driver(input clk, input rst_n, input rx_en,
                 output reg bus_oe, output reg [7:0] rx_data);
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n)
            bus_oe <= 1'b0;
        else
            bus_oe <= rx_en;
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        bus_oe = [s for s in report['signals'] if s['name'] == 'bus_oe']
        assert len(bus_oe) == 1
        assert bus_oe[0]['pattern'] == 'SINGLE_EDGE'
        assert 'negedge' in bus_oe[0]['edges']


# ---------------------------------------------------------------------------
# Test 2: DUAL_EDGE
# ---------------------------------------------------------------------------
class TestDualEdge:
    def test_dual_edge_same_signal(self, tmp_path):
        """OE assigned in both posedge and negedge blocks → DUAL_EDGE, LOW risk."""
        sv = """
module tx_phy(input clk, input rst_n, input enable,
              output reg tx_oe);
    // Posedge domain
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            tx_oe <= 1'b0;
        else
            tx_oe <= enable;
    end
    // Negedge domain also drives tx_oe (unusual but valid for classification)
    always @(negedge clk) begin
        tx_oe <= enable;
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        tx_oe = [s for s in report['signals'] if s['name'] == 'tx_oe']
        assert len(tx_oe) == 1
        assert tx_oe[0]['pattern'] == 'DUAL_EDGE'
        assert tx_oe[0]['risk'] == 'LOW'
        assert 'posedge' in tx_oe[0]['edges']
        assert 'negedge' in tx_oe[0]['edges']


# ---------------------------------------------------------------------------
# Test 3: COMBINATIONAL
# ---------------------------------------------------------------------------
class TestCombinational:
    def test_continuous_assign_oe(self, tmp_path):
        """OE driven by continuous assign → COMBINATIONAL, HIGH risk."""
        sv = """
module bus_mux(input sel, input drv_a, input drv_b,
               output wire data_oe);
    assign data_oe = sel ? drv_a : drv_b;
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        data_oe = [s for s in report['signals'] if s['name'] == 'data_oe']
        assert len(data_oe) == 1
        assert data_oe[0]['pattern'] == 'COMBINATIONAL'
        assert data_oe[0]['risk'] == 'HIGH'
        # CLI should return 1 due to HIGH risk
        assert res.returncode == 1

    def test_undriven_oe_wire(self, tmp_path):
        """OE declared as wire but never assigned → COMBINATIONAL, HIGH risk."""
        sv = """
module stub(input clk);
    wire floating_oe;
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        floating = [s for s in report['signals'] if s['name'] == 'floating_oe']
        assert len(floating) == 1
        assert floating[0]['pattern'] == 'COMBINATIONAL'
        assert floating[0]['risk'] == 'HIGH'


# ---------------------------------------------------------------------------
# Test 4: GATED
# ---------------------------------------------------------------------------
class TestGated:
    def test_bit_gated_oe(self, tmp_path):
        """OE conditionally enabled per bit index → GATED, INFO risk."""
        sv = """
module tx_phy_gated(input clk, input rst_n, input [7:0] data,
                    output reg [7:0] bus_oe);
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bus_oe <= 8'h00;
        end else begin
            for (i = 0; i < 8; i = i + 1) begin
                if (data[i])
                    bus_oe[i] <= 1'b1;
                else
                    bus_oe[i] <= 1'b0;
            end
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        gated = [s for s in report['signals'] if s['name'] == 'bus_oe']
        assert len(gated) == 1
        # With bit-indexed assignments, should be GATED
        assert gated[0]['pattern'] == 'GATED'
        assert gated[0]['risk'] == 'INFO'

    def test_condition_gated_oe(self, tmp_path):
        """OE conditionally enabled by a mode signal → GATED, INFO risk."""
        sv = """
module driver(input clk, input rst_n, input mode_h1,
              output reg drv_en);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            drv_en <= 1'b0;
        else begin
            if (mode_h1)
                drv_en <= 1'b1;
            else
                drv_en <= 1'b0;
        end
    end
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        drv = [s for s in report['signals'] if s['name'] == 'drv_en']
        assert len(drv) == 1
        assert drv[0]['pattern'] == 'GATED'
        assert drv[0]['risk'] == 'INFO'


# ---------------------------------------------------------------------------
# Test 5: No OE found
# ---------------------------------------------------------------------------
class TestNoOE:
    def test_no_oe_signals(self, tmp_path):
        """Design with no OE signals at all → empty report, exit 0."""
        sv = """
module counter(input clk, input rst_n, output reg [7:0] count);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= 8'h00;
        else
            count <= count + 1;
    end
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        assert report is not None
        assert report['total_oe_signals'] == 0
        assert len(report['signals']) == 0
        assert res.returncode == 0

    def test_missing_file_warns(self, tmp_path):
        """Non-existent file should warn but not crash."""
        out_dir = tmp_path / 'out'
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-files', str(tmp_path / 'nonexistent.v'),
             '--out-dir', str(out_dir)],
            capture_output=True, text=True)
        assert 'WARNING' in res.stderr


# ---------------------------------------------------------------------------
# Test 6: Mixed — multiple patterns in one file
# ---------------------------------------------------------------------------
class TestMixed:
    def test_mixed_patterns(self, tmp_path):
        """File with COMBINATIONAL + SINGLE_EDGE + DUAL_EDGE OE signals."""
        sv = """
module mixed_bus(input clk, input rst_n, input en_a, input en_b,
                 output wire comb_oe,
                 output reg  single_oe,
                 output reg  dual_oe);

    // COMBINATIONAL — no register
    assign comb_oe = en_a & en_b;

    // SINGLE_EDGE — posedge only
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            single_oe <= 1'b0;
        else
            single_oe <= en_a;
    end

    // DUAL_EDGE — both edges
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            dual_oe <= 1'b0;
        else
            dual_oe <= en_a;
    end
    always @(negedge clk) begin
        dual_oe <= en_b;
    end
endmodule
"""
        res, report = run_cli(tmp_path, sv)
        assert report['total_oe_signals'] == 3

        by_name = {s['name']: s for s in report['signals']}
        assert by_name['comb_oe']['pattern'] == 'COMBINATIONAL'
        assert by_name['comb_oe']['risk'] == 'HIGH'
        assert by_name['single_oe']['pattern'] == 'SINGLE_EDGE'
        assert by_name['single_oe']['risk'] == 'MEDIUM'
        assert by_name['dual_oe']['pattern'] == 'DUAL_EDGE'
        assert by_name['dual_oe']['risk'] == 'LOW'

        # Summary counts
        assert report['summary']['COMBINATIONAL'] == 1
        assert report['summary']['SINGLE_EDGE'] == 1
        assert report['summary']['DUAL_EDGE'] == 1

        # Exit code 1 because of COMBINATIONAL (HIGH risk)
        assert res.returncode == 1


# ---------------------------------------------------------------------------
# Test 7: Cross-signal dual-edge combination detection
# ---------------------------------------------------------------------------
class TestCrossSignalDualEdge:
    def test_vendor_style_dual_edge(self, tmp_path):
        """
        Vendor TX_PHY pattern: tx_oe_pos (posedge) and tx_oe_neg (negedge)
        combined with AND → both should be upgraded to DUAL_EDGE.
        """
        sv = """
module tx_phy_vendor(input clk, input rst_n, input enable,
                     output wire final_oe);
    reg tx_oe_pos;
    reg tx_oe_neg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            tx_oe_pos <= 1'b0;
        else
            tx_oe_pos <= enable;
    end

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n)
            tx_oe_neg <= 1'b0;
        else
            tx_oe_neg <= enable;
    end

    assign final_oe = tx_oe_pos & tx_oe_neg;
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        by_name = {s['name']: s for s in report['signals']}
        # Both component signals should be upgraded to DUAL_EDGE
        assert by_name['tx_oe_pos']['pattern'] == 'DUAL_EDGE'
        assert by_name['tx_oe_pos']['risk'] == 'LOW'
        assert by_name['tx_oe_neg']['pattern'] == 'DUAL_EDGE'
        assert by_name['tx_oe_neg']['risk'] == 'LOW'


# ---------------------------------------------------------------------------
# Test 8: Tristate infer — OE detected from ternary pattern
# ---------------------------------------------------------------------------
class TestTristateInfer:
    def test_ternary_tristate_detects_oe(self, tmp_path):
        """
        assign bus = my_enable ? data : 8'bz;
        Even if 'my_enable' doesn't match OE naming, it should be detected
        as an OE signal from the tristate pattern.
        """
        sv = """
module pad_driver(input clk, input rst_n, input drv_active,
                  input [7:0] tx_data, inout [7:0] bus);
    reg my_enable;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            my_enable <= 1'b0;
        else
            my_enable <= drv_active;
    end
    assign bus = my_enable ? tx_data : 8'bz;
endmodule
"""
        _, report = run_cli(tmp_path, sv)
        inferred = [s for s in report['signals'] if s['name'] == 'my_enable']
        assert len(inferred) == 1
        assert inferred[0]['pattern'] == 'SINGLE_EDGE'


# ---------------------------------------------------------------------------
# White-box unit tests
# ---------------------------------------------------------------------------
class TestStripComments:
    def test_preserves_line_count(self):
        src = "line1\nline2 // comment\nline3\n"
        out = opc.strip_comments(src)
        assert out.count('\n') == src.count('\n')
        assert 'comment' not in out

    def test_block_comment(self):
        src = "a\n/* multi\nline */\nb\n"
        out = opc.strip_comments(src)
        assert out.count('\n') == src.count('\n')
        assert 'multi' not in out


class TestIsOeName:
    def test_standard_suffixes(self):
        assert opc.is_oe_name('tx_oe')
        assert opc.is_oe_name('bus_oen')
        assert opc.is_oe_name('data_oeb')
        assert opc.is_oe_name('drv_en_pad')
        assert opc.is_oe_name('tri_en_x')

    def test_infixes(self):
        assert opc.is_oe_name('tx_oe_pos')
        assert opc.is_oe_name('tx_oe_neg')
        assert opc.is_oe_name('some_oen_reg')

    def test_not_oe(self):
        assert not opc.is_oe_name('clk')
        assert not opc.is_oe_name('data')
        assert not opc.is_oe_name('rst_n')
        assert not opc.is_oe_name('counter')


class TestReturnCode:
    def test_clean_returns_zero(self, tmp_path):
        """No HIGH-risk signals → exit 0."""
        sv = """
module safe(input clk, input rst_n, input en, output reg tx_oe);
    always @(posedge clk) tx_oe <= en;
    always @(negedge clk) tx_oe <= en;
endmodule
"""
        res, _ = run_cli(tmp_path, sv)
        assert res.returncode == 0

    def test_combinational_returns_one(self, tmp_path):
        """COMBINATIONAL OE → exit 1."""
        sv = """
module unsafe(input a, output wire pad_oe);
    assign pad_oe = a;
endmodule
"""
        res, _ = run_cli(tmp_path, sv)
        assert res.returncode == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

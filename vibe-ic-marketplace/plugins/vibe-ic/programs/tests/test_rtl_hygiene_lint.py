"""Unit tests for rtl_hygiene_lint.py.

Each test synthesizes a small Verilog snippet and verifies the lint catches
(or correctly ignores) the specific pattern.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'rtl_hygiene_lint.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import rtl_hygiene_lint as rhl  # noqa: E402


def run_cli(tmp_path, sv_content, severity='INFO'):
    f = tmp_path / 'test.sv'
    f.write_text(sv_content)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--severity', severity,
         '--json', str(tmp_path / 'findings.json'), str(f)],
        capture_output=True, text=True)
    findings = json.loads((tmp_path / 'findings.json').read_text())
    return res, findings


class TestUndrivenWire:
    def test_detects_undriven_wire(self, tmp_path):
        sv = """
module m(input clk, input rst_n, output wire y);
    wire floating_sig;
    reg [7:0] cnt;
    always @(posedge clk) cnt <= cnt + 1;
    assign y = cnt[0];
endmodule
"""
        _, findings = run_cli(tmp_path, sv)
        rules = [f['rule'] for f in findings]
        syms = [f['symbol'] for f in findings]
        assert 'undriven-wire' in rules
        assert 'floating_sig' in syms

    def test_wire_driven_by_assign_is_clean(self, tmp_path):
        sv = """
module m(input a, output y);
    wire w;
    assign w = a;
    assign y = w;
endmodule
"""
        _, findings = run_cli(tmp_path, sv)
        assert not any(f['rule'] == 'undriven-wire' for f in findings)

    def test_wire_driven_by_instance_is_clean(self, tmp_path):
        sv = """
module helper(output out);
    assign out = 1'b0;
endmodule
module top(output y);
    wire from_inst;
    helper u (.out(from_inst));
    assign y = from_inst;
endmodule
"""
        _, findings = run_cli(tmp_path, sv)
        # from_inst appears in .out(from_inst) → conservatively counted as driven
        assert not any(
            f['rule'] == 'undriven-wire' and f['symbol'] == 'from_inst'
            for f in findings)


class TestUnreadReg:
    def test_detects_written_never_read_reg(self, tmp_path):
        """This is the EXAMPLE_TESTER bug #7 pattern: resp_crc declared, written to,
        but never appears on any RHS."""
        sv = """
module m(input clk, input rst_n);
    reg [7:0] resp_crc;
    reg [7:0] ctr;
    always @(posedge clk) begin
        if (!rst_n) begin
            resp_crc <= 8'hFF;
            ctr      <= 8'h00;
        end else begin
            resp_crc <= 8'h12;          // constant write only, never read
            ctr      <= ctr + 1;        // self-read OK
        end
    end
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        unread = [f for f in findings if f['rule'] == 'unread-reg']
        symbols = [f['symbol'] for f in unread]
        assert 'resp_crc' in symbols
        assert 'ctr' not in symbols

    def test_reg_read_on_rhs_is_clean(self, tmp_path):
        sv = """
module m(input clk, input rst_n, output wire [7:0] q);
    reg [7:0] data;
    always @(posedge clk) if (!rst_n) data <= 0; else data <= data + 1;
    assign q = data;
endmodule
"""
        _, findings = run_cli(tmp_path, sv)
        assert not any(
            f['rule'] == 'unread-reg' and f['symbol'] == 'data'
            for f in findings)


class TestCaseCoverage:
    def test_detects_case_without_default(self, tmp_path):
        sv = """
module m(input clk, input [1:0] sel, output reg y);
    always @(posedge clk) begin
        case (sel)
            2'b00: y <= 1'b0;
            2'b01: y <= 1'b1;
        endcase
    end
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert any(f['rule'] == 'case-no-default' for f in findings)

    def test_case_with_default_is_clean(self, tmp_path):
        sv = """
module m(input clk, input [1:0] sel, output reg y);
    always @(posedge clk) begin
        case (sel)
            2'b00:   y <= 1'b0;
            2'b01:   y <= 1'b1;
            default: y <= 1'b0;
        endcase
    end
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert not any(f['rule'] == 'case-no-default' for f in findings)


class TestCommentHandling:
    def test_line_comments_do_not_trigger_false_positives(self, tmp_path):
        sv = """
module m;
    // wire fake_never_driven;   <- commented out, must be ignored
    /* reg fake_reg_never_read; */
endmodule
"""
        _, findings = run_cli(tmp_path, sv)
        syms = [f['symbol'] for f in findings]
        assert 'fake_never_driven' not in syms
        assert 'fake_reg_never_read' not in syms


class TestReturnCode:
    def test_clean_file_returns_zero(self, tmp_path):
        sv = """
module m(input clk, input rst_n, output reg y);
    always @(posedge clk) if (!rst_n) y <= 0; else y <= ~y;
endmodule
"""
        res, _ = run_cli(tmp_path, sv)
        assert res.returncode == 0

    def test_file_with_error_returns_one(self, tmp_path):
        # Multi-line so the port-list heuristic doesn't eat the wire decl
        sv = """module m(input a);
    wire unused_wire;
endmodule
"""
        res, _ = run_cli(tmp_path, sv, severity='ERROR')
        assert res.returncode == 1


class TestStripComments:
    """White-box tests for the comment stripper."""

    def test_strip_line_comment_preserves_line_count(self):
        src = "line1\nline2 // a comment\nline3\n"
        out = rhl.strip_comments(src)
        assert out.count('\n') == src.count('\n')
        assert 'comment' not in out

    def test_strip_block_comment_preserves_line_count(self):
        src = "line1\n/* multi\nline\ncomment */\nafter\n"
        out = rhl.strip_comments(src)
        assert out.count('\n') == src.count('\n')
        assert 'multi' not in out
        assert 'after' in out


class TestDeclarationParser:
    def test_finds_wire_and_reg_decls(self):
        src = """
module m;
    wire w1;
    wire [7:0] w2;
    reg  r1;
    reg  [31:0] r2;
    logic l1;
endmodule
"""
        decls = rhl.find_declarations(rhl.strip_comments(src))
        names = {name for _, name, _ in decls}
        assert {'w1', 'w2', 'r1', 'r2', 'l1'}.issubset(names)

    def test_skips_port_decls(self):
        """wire/reg in module port list should not be flagged."""
        src = """
module m (
    input  wire clk,
    output reg  q
);
    reg internal;
    always @(posedge clk) q <= ~q;
endmodule
"""
        decls = rhl.find_declarations(rhl.strip_comments(src))
        names = {name for _, name, _ in decls}
        # Port-list items are skipped
        assert 'clk' not in names
        assert 'q' not in names
        # Internal declarations are captured
        assert 'internal' in names


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

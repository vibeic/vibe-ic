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
        """This is the USB-HID tester bug #7 pattern: resp_crc declared, written to,
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
        # ORGANIC #770 r4 — a COMBINATIONAL `always @(*)` case with no default
        # CAN infer a latch → still hard-WARNs (block_eligible). (A clocked case
        # cannot infer a latch and is now advisory — see the next test.)
        sv = """
module m(input [1:0] sel, output reg y);
    always @(*) begin
        case (sel)
            2'b00: y = 1'b0;
            2'b01: y = 1'b1;
        endcase
    end
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        hits = [f for f in findings if f['rule'] == 'case-no-default']
        assert hits and all(f.get('block_eligible', True) for f in hits)

    def test_sequential_case_without_default_is_advisory(self, tmp_path):
        # ORGANIC #770 r4 — a case inside a CLOCKED (sequential) always block
        # cannot infer a latch (the reg HOLDS on an unlisted code), so the
        # case-no-default finding is downgraded to ADVISORY (INFO, not a WARN).
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
        _, findings = run_cli(tmp_path, sv, severity='INFO')
        hits = [f for f in findings if f['rule'] == 'case-no-default']
        assert hits and all(f.get('block_eligible', True) is False for f in hits)

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


class TestUninitRegisteredOutput:
    """Rule 5: reset-less registered output with no power-up initializer."""

    def test_flags_resetless_uninit_output(self, tmp_path):
        sv = """
module TopModule(input clk, input [7:0] d, output reg [7:0] q);
    always @(posedge clk) q <= d;
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        rules = {f['rule'] for f in findings}
        assert 'uninit-registered-output' in rules
        hit = next(f for f in findings if f['rule'] == 'uninit-registered-output')
        assert hit['symbol'] == 'q'
        assert hit['severity'] == 'WARN'

    def test_clears_when_initialized_at_decl(self, tmp_path):
        sv = """
module TopModule(input clk, input [7:0] d, output reg [7:0] q = 8'b0);
    always @(posedge clk) q <= d;
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'uninit-registered-output' not in {f['rule'] for f in findings}

    def test_no_false_positive_with_reset(self, tmp_path):
        sv = """
module TopModule(input clk, input reset, input [7:0] d, output reg [7:0] q);
    always @(posedge clk) if (reset) q <= 8'h34; else q <= d;
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'uninit-registered-output' not in {f['rule'] for f in findings}

    def test_ignores_purely_combinational_output(self, tmp_path):
        sv = """
module TopModule(input a, input b, output z);
    assign z = a & b;
endmodule
"""
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'uninit-registered-output' not in {f['rule'] for f in findings}


class TestNonblockingInAlwaysComb:
    """An NBA in always_comb publishes the value one scheduling region late."""

    @staticmethod
    def hits(sv):
        return rhl.rule_nonblocking_in_always_comb(
            rhl.strip_comments(sv), 'test.sv')

    def test_detects_nested_nonblocking_assignment(self):
        sv = """
module m(input logic a, b, output logic y);
  always_comb begin
    if (a) begin
      y <= b;
    end else begin
      y = 1'b0;
    end
  end
endmodule
"""
        hits = self.hits(sv)
        assert [(f.rule, f.symbol, f.severity) for f in hits] == [
            ('nonblocking-in-always-comb', 'y', 'ERROR')]
        assert hits[0].block_eligible is True

    def test_cli_blocks_at_error_threshold(self, tmp_path):
        sv = """
module m(input logic a, output logic y);
  always_comb y <= a;
endmodule
"""
        res, findings = run_cli(tmp_path, sv, severity='ERROR')
        assert res.returncode == 1
        assert [f['rule'] for f in findings] == [
            'nonblocking-in-always-comb']

    def test_relational_less_equal_is_not_an_assignment(self):
        sv = """
module m(input logic [3:0] a, b, output logic y);
  always_comb begin
    if (a <= b) y = 1'b1;
    else y = (a <= b);
  end
endmodule
"""
        assert self.hits(sv) == []

    def test_detects_concat_lhs_but_ignores_for_loop_bound(self):
        sv = """
module m(input logic [1:0] d, output logic a, b);
  integer i;
  always_comb begin
    for (i = 0; i <= 1; i = i + 1) begin
      {a, b} <= d;
    end
  end
endmodule
"""
        hits = self.hits(sv)
        assert len(hits) == 1
        assert hits[0].rule == 'nonblocking-in-always-comb'
        assert hits[0].symbol == 'b'

    def test_detects_beginless_for_body(self):
        sv = """
module m(input logic [3:0] a, output logic [3:0] y);
  integer i;
  always_comb for (i = 0; i < 4; i = i + 1) y[i] <= a[i];
endmodule
"""
        hits = self.hits(sv)
        assert len(hits) == 1
        assert hits[0].symbol == 'y'

    def test_detects_nba_in_beginless_if_else_arm(self):
        sv = """
module m(input logic s, a, b, output logic y);
  always_comb if (s) y = a; else y <= b;
endmodule
"""
        hits = self.hits(sv)
        assert len(hits) == 1
        assert hits[0].symbol == 'y'

    def test_detects_nba_in_beginless_unique_case(self):
        sv = """
module m(input logic s, a, b, output logic y);
  always_comb unique case (s)
    1'b0: y = a;
    default: y <= b;
  endcase
endmodule
"""
        hits = self.hits(sv)
        assert len(hits) == 1
        assert hits[0].symbol == 'y'

    def test_sequential_nba_is_not_in_scope(self):
        sv = """
module m(input logic clk, d, output logic q);
  always_ff @(posedge clk) q <= d;
endmodule
"""
        assert self.hits(sv) == []

    def test_legacy_star_block_is_not_reclassified(self):
        """This rule is deliberately limited to the explicit always_comb
        contract; legacy/latch intent needs separate evidence."""
        sv = """
module m(input logic d, output logic q);
  always @(*) q <= d;
endmodule
"""
        assert self.hits(sv) == []

    def test_comments_and_strings_do_not_create_a_finding(self):
        sv = r'''
module m(input logic a, output logic y);
  always_comb begin
    // y <= a;
    $display("y <= a");
    y = a;
  end
endmodule
'''
        assert self.hits(sv) == []

    def test_escaped_identifier_named_always_comb_is_not_a_keyword(self):
        sv = r'''
module m;
  logic \always_comb ;
  initial \always_comb <= 1'b0;
endmodule
'''
        assert self.hits(sv) == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


class TestIncompleteSensitivity:
    """Rule 6: level-sensitive always with a signal read but not in the sensitivity list."""

    def test_flags_missing_signal(self, tmp_path):
        sv = ("module m(input clock,input a,output reg p,output reg q);\n"
              "  always @(negedge clock) q<=a;\n"
              "  always @(a) if(clock) p<=a;\n"      # clock read but not listed
              "endmodule\n")
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        hits = [f for f in findings if f['rule'] == 'incomplete-sensitivity-list']
        assert hits and 'clock' in hits[0]['symbol']

    def test_star_is_exempt(self, tmp_path):
        sv = ("module m(input clock,input a,output reg p);\n"
              "  always @(*) if(clock) p=a;\n"
              "endmodule\n")
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'incomplete-sensitivity-list' not in {f['rule'] for f in findings}

    def test_clocked_block_exempt(self, tmp_path):
        sv = ("module m(input clk,input rst,input d,output reg q);\n"
              "  always @(posedge clk) if(rst) q<=0; else q<=d;\n"
              "endmodule\n")
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'incomplete-sensitivity-list' not in {f['rule'] for f in findings}

    def test_complete_list_ok(self, tmp_path):
        sv = ("module m(input a,input b,output reg y);\n"
              "  always @(a or b) y = a & b;\n"
              "endmodule\n")
        _, findings = run_cli(tmp_path, sv, severity='WARN')
        assert 'incomplete-sensitivity-list' not in {f['rule'] for f in findings}


# ---------------------------------------------------------------------------
# rule_undriven_output_port — an output with no driver holds X forever, so a
# testbench waiting on it never finishes. Every positive below is paired with a
# negative control of the same shape that must stay green.
# ---------------------------------------------------------------------------
def _undriven(src):
    return [f.symbol for f in
            rhl.rule_undriven_output_port(rhl.strip_comments(src), 't.v')]


def test_undriven_output_port_is_an_error():
    src = """
    module m(input clk, input rst_n, input go, output reg busy, output reg status);
      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) busy <= 1'b0; else busy <= go;
      end
    endmodule
    """
    assert _undriven(src) == ['status']


def test_driven_outputs_are_clean():
    """NEGATIVE CONTROL — the same interface, fully driven."""
    src = """
    module m(input clk, input rst_n, input go, output reg busy, output reg status);
      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin busy <= 1'b0; status <= 1'b0; end
        else begin busy <= go; status <= ~go; end
      end
    endmodule
    """
    assert _undriven(src) == []


def test_output_driven_by_continuous_assign_is_clean():
    src = "module m(input a, input b, output y); assign y = a & b; endmodule"
    assert _undriven(src) == []


def test_output_driven_through_an_instance_is_clean():
    src = """
    module m(input clk, output [3:0] q);
      sub u (.clk(clk), .q(q));
    endmodule
    """
    assert _undriven(src) == []


def test_systemverilog_implicit_port_connection_counts_as_driven():
    """`.q_o` with no parens is shorthand for `.q_o(q_o)` — pervasive in real
    SV. Missing it reported a whole reference codebase as undriven."""
    src = """
    module m(input clk_i, input rst_ni, output logic [3:0] q_o);
      sub u_sync (.clk_i, .rst_ni, .q_o);
    endmodule
    """
    assert _undriven(src) == []


def test_wildcard_port_connection_suppresses_the_rule():
    """`.*` binds every same-named signal; nothing can be shown undriven."""
    src = """
    module m(input clk_i, output logic [3:0] q_o);
      sub u_sync (.*);
    endmodule
    """
    assert _undriven(src) == []


def test_blackbox_stub_module_is_not_flagged():
    src = "module bb(input a, output y); endmodule"
    assert _undriven(src) == []


def test_rule_is_scoped_per_module():
    """A signal driven in a SIBLING module must not credit this module."""
    src = """
    module a(input clk, output reg y);
      always @(posedge clk) y <= 1'b1;
    endmodule
    module b(input clk, output reg y);
      always @(posedge clk) begin end
    endmodule
    """
    assert _undriven(src) == ['y']  # only module b's

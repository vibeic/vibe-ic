"""Rule 25 — use-before-declaration (iverilog-13 / official cvdp-sim REJECTS a
module-scope net/var referenced ABOVE its declaration line; the host iverilog-12
gate TOLERATES it → a false-pass gap).

Validates the three mandated behaviors:
  * PASS    — every decl precedes its use → no finding (zero noise).
  * FIRES   — the genuine forward-reference bug (the interrupt_controller_0019
              shape: a net read in a clocked block, declared several lines below).
  * EXCLUDES— a port read in an always, a localparam used early, a
              generate-assigned net, a hierarchical ref, and an instance port
              connection must NOT fire (zero-FP).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rtl_hygiene_lint import rule_use_before_declaration  # noqa: E402


def _hits(src):
    return [f for f in rule_use_before_declaration(src, "t.sv")
            if f.rule == "use-before-declaration"]


# ---------------------------------------------------------------------------
# PASS — all declarations precede their first use.
# ---------------------------------------------------------------------------
def test_pass_clean_decl_before_use():
    src = """module clean(input clk, input rst_n, input [3:0] req,
                          output reg [1:0] gnt);
  wire       any_pending = |req;
  wire [1:0] best_idx = req[0] ? 2'd0 : req[1] ? 2'd1 : 2'd3;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) gnt <= 2'd0;
    else        gnt <= any_pending ? best_idx : gnt;
endmodule
"""
    assert _hits(src) == []


# ---------------------------------------------------------------------------
# FIRES — the forward-reference bug (nets read in a clocked block, declared
# below). This is the interrupt_controller_0019 real case.
# ---------------------------------------------------------------------------
def test_fires_forward_reference_in_clocked_block():
    src = """module ubd(input clk, input rst_n, input [3:0] req,
                        output reg [1:0] gnt);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) gnt <= 2'd0;
    else        gnt <= any_pending ? best_idx : gnt;
  wire       any_pending = |req;
  wire [1:0] best_idx = req[0] ? 2'd0 : req[1] ? 2'd1 : 2'd3;
endmodule
"""
    hits = _hits(src)
    syms = {h.symbol for h in hits}
    assert syms == {"any_pending", "best_idx"}, syms
    # Reported at the USE line (above the decl); a hard ELABORATION FAILURE in
    # the official iverilog-13 scorer, so ERROR severity + block-eligible (it
    # must survive the canonical `--severity ERROR` lint gate and trip rc=1).
    for h in hits:
        assert h.line == 5, h.line
        assert h.severity == "ERROR", h.severity
        assert h.block_eligible is True


def test_fires_forward_reference_in_continuous_assign():
    src = """module ca(input [7:0] a, output [7:0] y);
  assign y = scratch;
  wire [7:0] scratch = a + 8'd1;
endmodule
"""
    hits = _hits(src)
    assert {h.symbol for h in hits} == {"scratch"}, hits


# ---------------------------------------------------------------------------
# EXCLUDES — none of these legitimate "later text" shapes may fire.
# ---------------------------------------------------------------------------
def test_excludes_port_read_in_always():
    # `en`/`q` are PORTS declared (non-ANSI) BELOW the always; ports are never
    # use-before-declaration candidates.
    src = """module p(clk, en, q);
  input clk;
  always @(posedge clk) q <= en;
  input  en;
  output reg q;
endmodule
"""
    assert _hits(src) == []


def test_excludes_localparam_used_before_decl():
    src = """module lp(input clk, input rst_n, input [3:0] d, output reg [3:0] o);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) o <= 4'd0;
    else        o <= d ^ MASK;
  localparam MASK = 4'hA;
endmodule
"""
    assert _hits(src) == []


def test_excludes_generate_assigned_net():
    # `shifted` is declared below the always read but is DRIVEN inside a generate
    # block → excluded.
    src = """module gen(input clk, input rst_n, input [3:0] din, output reg [3:0] o);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) o <= 4'd0;
    else        o <= shifted;
  wire [3:0] shifted;
  genvar gi;
  generate
    for (gi = 0; gi < 4; gi = gi + 1) begin : g
      assign shifted[gi] = din[3-gi];
    end
  endgenerate
endmodule
"""
    assert _hits(src) == []


def test_excludes_hierarchical_and_instance_connection():
    # `sub.flag` (hierarchical) and the `.din(later_net)` instance connection
    # must not be read as a forward reference of a module-scope net.
    src = """module top(input clk, input [3:0] in);
  child u_child(.clk(clk), .din(later_net), .flag(probe));
  wire       probe;
  wire [3:0] later_net = in;
  reg        seen;
  always @(posedge clk) seen <= u_child.flag;
endmodule
"""
    assert _hits(src) == []


def test_excludes_sibling_module_same_name():
    # A net named `tmp` is declared-before-use in module a (clean) and
    # used-before-decl in module b (forward ref). Per-module-region scope must
    # fire for b ONLY — module a's clean use is never conflated with b's late
    # decl, and b's late decl never suppresses... it fires exactly once.
    src = """module a(input clk, input x, output reg y);
  wire tmp = x;
  always @(posedge clk) y <= tmp;
endmodule

module b(input clk, input z, output reg w);
  always @(posedge clk) w <= tmp;
  wire tmp = z;
endmodule
"""
    hits = _hits(src)
    assert len(hits) == 1, hits
    assert hits[0].symbol == "tmp"
    assert hits[0].line == 7, hits[0].line   # the use line inside module b


def test_excludes_cross_module_reference():
    # The check is STRICTLY module-scoped: a reference in module A to an
    # identifier that is declared ONLY (and later) in a sibling module B is NOT
    # a forward reference of A — A's decl table is built from A's body alone, so
    # B's later `wire shared` never charges against A's use. Zero hits.
    src = """module a(input clk, input d, output reg q);
  always @(posedge clk) q <= shared;
endmodule

module b(input clk, input e, output reg r);
  always @(posedge clk) r <= e;
  wire shared = e;
endmodule
"""
    assert _hits(src) == []


def test_excludes_word_inside_string_literal():
    src = """module s(input clk, output reg done);
  always @(posedge clk) begin
    $display("waiting for ready signal");
    done <= 1'b1;
  end
  wire ready = 1'b0;
endmodule
"""
    # `ready` appears only inside the $display string -> not a read.
    assert _hits(src) == []


# ---------------------------------------------------------------------------
# ORGANIC-20260723 — assignment-pattern member KEY is a field label, NOT a read.
# OpenTitan tlul_sram_byte.sv `'{ … data_intg: <value> }` false-fired
# use-before-declaration and blocked the REUSED-IP AES flow.
# ---------------------------------------------------------------------------
def test_excludes_assignment_pattern_member_key():
    # `data_intg:` is the STRUCT FIELD LABEL of the assignment pattern (a name of
    # the LHS type), not a read of the same-named local net declared below.
    src = """module m(input [6:0] src_intg, output logic [6:0] o);
  assign packed_u = '{rsvd: 1'b0, data_intg: src_intg};
  logic [6:0] data_intg;
  assign o = data_intg;
endmodule
"""
    assert _hits(src) == []


def test_member_key_value_still_flagged():
    # NEGATIVE CONTROL: only the field LABEL is excluded. A declared-below net
    # used as the field VALUE (`data_intg: src_intg`, src_intg the value) is a
    # genuine forward reference and must still fire.
    src = """module m(output logic [6:0] o);
  assign packed_u = '{data_intg: src_intg};
  logic [6:0] src_intg;
  assign o = src_intg;
endmodule
"""
    assert {h.symbol for h in _hits(src)} == {"src_intg"}

#!/usr/bin/env python3
"""Tests for rtl_hygiene_lint.py Rules 26-31 (ORGANIC-20260704) — six
arithmetic-datapath structural traps distilled from the 94 proven-correct
CVDP solved_design_db designs:

  26. divider-missing-final-correction   (non-restoring divider)
  27. multiop-arith-width-consistency    (GCD/LCM width + divisor extend)
  28. cascaded-decrement-priority-order  (BCD/HH:MM:SS borrow chain)
  29. seq-multiplier-width               (shift-and-add multiplier)
  30. variable-partselect-illegal-range  ([hi:lo] with non-const bounds)
  31. booth-shift-before-signext         (Booth recode shifted before widen)

Every rule is ADVISORY ONLY (severity INFO, block_eligible == False, no
--fix): these tests pin (a) a deliberately-broken fixture per pattern FIRES,
(b) the corresponding golden/negative fixture (mirroring the real CVDP
solved-design idiom) stays SILENT, and (c) the finding is INFO + advisory.
The mandatory zero-FP corpus sweep against all 94
benchmark_external/cvdp/solved_design_db/rtl/*.sv designs is run separately
(see ORGANIC-20260704 backlog acceptance) and is NOT re-verified from this
file (no chip-specific literal belongs in a plugin test); this file only pins
the two chip-AGNOSTIC synthetic fixtures per rule.
"""
from __future__ import annotations
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
sys.path.insert(0, str(PROG.parent))
import rtl_hygiene_lint as L  # noqa: E402


def _findings(fn, src: str):
    return fn(L.strip_comments(src), "t.sv")


def _assert_advisory(findings):
    for f in findings:
        assert f.severity == "INFO", f.severity
        assert f.block_eligible is False


# ---------------------------------------------------------------------------
# Rule 26 — divider-missing-final-correction
# ---------------------------------------------------------------------------
BAD_DIVIDER = """
module nonrestoring_div #(parameter WIDTH = 8) (
    input clk, input rst,
    input signed [WIDTH:0] divisor,
    output reg signed [WIDTH:0] remainder
);
    reg signed [WIDTH:0] rem_reg;
    reg [3:0] cnt;
    always @(posedge clk) begin
        if (rst) begin
            cnt <= 0;
        end else begin
            cnt <= cnt + 1;
            if (cnt == WIDTH-1) begin
                remainder <= rem_reg;
            end
        end
    end
endmodule
"""

GOOD_DIVIDER = """
module nonrestoring_div #(parameter WIDTH = 8) (
    input clk, input rst,
    input signed [WIDTH:0] divisor,
    output reg signed [WIDTH:0] remainder
);
    reg signed [WIDTH:0] rem_reg;
    reg [3:0] cnt;
    always @(posedge clk) begin
        if (rst) begin
            cnt <= 0;
        end else begin
            cnt <= cnt + 1;
            if (cnt == WIDTH-1) begin
                if (rem_reg < 0) rem_reg <= rem_reg + divisor;
                remainder <= rem_reg;
            end
        end
    end
endmodule
"""


def test_rule26_fires_on_missing_final_correction():
    fs = _findings(L.rule_divider_missing_final_correction, BAD_DIVIDER)
    assert len(fs) >= 1
    assert fs[0].rule == "divider-missing-final-correction"
    _assert_advisory(fs)


def test_rule26_silent_with_final_correction():
    fs = _findings(L.rule_divider_missing_final_correction, GOOD_DIVIDER)
    assert fs == []


def test_rule26_silent_on_unsigned_restoring_remainder():
    # Mirrors cvdp_copilot_restoring_division_0001: UNSIGNED rem_reg,
    # corrected every cycle (not just at the end) -> never matched (the
    # signed-name gate is the zero-FP safety net for the restoring style).
    src = """
    module restoring_division #(parameter WIDTH = 6) (
        input clk, input rst,
        output reg [WIDTH-1:0] remainder
    );
        reg [WIDTH:0] rem_reg;
        reg [3:0] cnt;
        always @(posedge clk) begin
            if (cnt == WIDTH-1) begin
                remainder <= rem_reg[WIDTH-1:0];
            end
        end
    endmodule
    """
    fs = _findings(L.rule_divider_missing_final_correction, src)
    assert fs == []


# ---------------------------------------------------------------------------
# Rule 27 — multiop-arith-width-consistency
# ---------------------------------------------------------------------------
BAD_MULTIOP = """
module lcm_bad #(parameter WIDTH = 4) (
    input clk,
    input [WIDTH-1:0] A, input [WIDTH-1:0] B, input [WIDTH-1:0] C,
    output reg [WIDTH-1:0] product
);
    always @(posedge clk) begin
        product <= A * B * C;
    end
endmodule
"""

GOOD_MULTIOP = """
module lcm_good #(parameter WIDTH = 4) (
    input clk,
    input [WIDTH-1:0] A, input [WIDTH-1:0] B, input [WIDTH-1:0] C,
    output reg [3*WIDTH-1:0] product
);
    always @(posedge clk) begin
        product <= A * B * C;
    end
endmodule
"""

BAD_DIVEXT = """
module lcm_div_bad #(parameter WIDTH = 4) (
    input [3*WIDTH-1:0] product,
    input [WIDTH-1:0] gcd_result,
    output reg [3*WIDTH-1:0] OUT
);
    always @(*) begin
        OUT = product / gcd_result;
    end
endmodule
"""

GOOD_DIVEXT = """
module lcm_div_good #(parameter WIDTH = 4) (
    input [3*WIDTH-1:0] product,
    input [WIDTH-1:0] gcd_result,
    output reg [3*WIDTH-1:0] OUT
);
    always @(*) begin
        OUT = product / {{2*WIDTH{1'b0}}, gcd_result};
    end
endmodule
"""


def test_rule27_fires_on_underwidened_product():
    fs = _findings(L.rule_multiop_arith_width_consistency, BAD_MULTIOP)
    assert any(f.rule == "multiop-arith-width-consistency" for f in fs)
    _assert_advisory(fs)


def test_rule27_silent_on_correctly_widened_product():
    fs = _findings(L.rule_multiop_arith_width_consistency, GOOD_MULTIOP)
    assert fs == []


def test_rule27_fires_on_bare_narrow_divisor():
    fs = _findings(L.rule_multiop_arith_width_consistency, BAD_DIVEXT)
    assert any(f.rule == "multiop-arith-width-consistency" for f in fs)


def test_rule27_silent_on_zero_extended_divisor():
    # Mirrors the golden CVDP gcd_0040 pattern exactly (concat-wrapped
    # zero-extend before the divide).
    fs = _findings(L.rule_multiop_arith_width_consistency, GOOD_DIVEXT)
    assert fs == []


# ---------------------------------------------------------------------------
# Rule 28 — cascaded-decrement-priority-order
# ---------------------------------------------------------------------------
BAD_CASCADE = """
module bad_cascade (
    input clk, input reset,
    output reg [4:0] hours, output reg [5:0] minutes, output reg [5:0] seconds
);
    always @(posedge clk) begin
        if (hours != 0) begin
            hours <= hours - 1;
        end else if (minutes != 0) begin
            minutes <= minutes - 1;
        end else if (seconds != 0) begin
            seconds <= 59;
            minutes <= 59;
            hours <= hours - 1;
        end
    end
endmodule
"""

GOOD_CASCADE = """
module good_cascade (
    input clk, input reset,
    output reg [4:0] hours, output reg [5:0] minutes, output reg [5:0] seconds
);
    always @(posedge clk) begin
        if (seconds != 0) begin
            seconds <= seconds - 1;
        end else if (minutes != 0) begin
            seconds <= 59;
            minutes <= minutes - 1;
        end else if (hours != 0) begin
            seconds <= 59;
            minutes <= 59;
            hours <= hours - 1;
        end
    end
endmodule
"""


def test_rule28_fires_on_wrong_priority_order():
    fs = _findings(L.rule_cascaded_decrement_priority_order, BAD_CASCADE)
    assert len(fs) == 1
    assert fs[0].rule == "cascaded-decrement-priority-order"
    _assert_advisory(fs)


def test_rule28_silent_on_correct_priority_order():
    # Mirrors cvdp_copilot_digital_stopwatch_0012's cascaded borrow chain
    # exactly (lowest unit first, monotonically-accumulating reload sets).
    fs = _findings(L.rule_cascaded_decrement_priority_order, GOOD_CASCADE)
    assert fs == []


# ---------------------------------------------------------------------------
# Rule 29 — seq-multiplier-width
# ---------------------------------------------------------------------------
BAD_SEQMUL = """
module seqmul_bad #(parameter WIDTH = 8) (
    input clk,
    input [WIDTH-1:0] b_reg,
    output reg [2*WIDTH-1:0] acc
);
    reg [3:0] cnt;
    always @(posedge clk) begin
        acc <= acc + (b_reg << cnt);
    end
endmodule
"""

GOOD_SEQMUL = """
module seqmul_good #(parameter WIDTH = 8) (
    input clk,
    input [WIDTH-1:0] b_reg,
    output reg [2*WIDTH-1:0] acc
);
    wire [2*WIDTH-1:0] b_ext = {{WIDTH{1'b0}}, b_reg};
    reg [3:0] cnt;
    always @(posedge clk) begin
        acc <= acc + (b_ext << cnt);
    end
endmodule
"""


def test_rule29_fires_on_narrow_operand_before_shift():
    fs = _findings(L.rule_seq_multiplier_width, BAD_SEQMUL)
    assert len(fs) == 1
    assert fs[0].rule == "seq-multiplier-width"
    _assert_advisory(fs)


def test_rule29_silent_on_prewidened_operand():
    # Mirrors cvdp_copilot_binary_multiplier_0012's b_ext idiom exactly.
    fs = _findings(L.rule_seq_multiplier_width, GOOD_SEQMUL)
    assert fs == []


def test_rule29_silent_on_constant_shift():
    src = """
    module seqmul_const #(parameter WIDTH = 8) (
        input clk, input [WIDTH-1:0] b_reg,
        output reg [2*WIDTH-1:0] acc
    );
        always @(posedge clk) begin
            acc <= acc + (b_reg << 3);
        end
    endmodule
    """
    fs = _findings(L.rule_seq_multiplier_width, src)
    assert fs == []


# ---------------------------------------------------------------------------
# Rule 30 — variable-partselect-illegal-range
# ---------------------------------------------------------------------------
BAD_PARTSEL = """
module partsel_bad (
    input [31:0] data,
    input [4:0] hi_idx, input [4:0] lo_idx,
    output reg [31:0] slice
);
    always @(*) begin
        slice = data[hi_idx:lo_idx];
    end
endmodule
"""

GOOD_PARTSEL_PLUSCOLON = """
module partsel_good (
    input [31:0] data,
    input [4:0] base,
    output reg [7:0] slice
);
    always @(*) begin
        slice = data[base +: 8];
    end
endmodule
"""

GOOD_PARTSEL_PARAM = """
module partsel_param #(parameter ADDR_WIDTH = 4) (
    input [ADDR_WIDTH:0] rq2,
    output wire eq
);
    assign eq = (rq2 == {~rq2[ADDR_WIDTH:ADDR_WIDTH-1], rq2[ADDR_WIDTH-2:0]});
endmodule
"""


def test_rule30_fires_on_variable_bounded_partselect():
    fs = _findings(L.rule_variable_partselect_illegal_range, BAD_PARTSEL)
    assert len(fs) == 1
    assert fs[0].rule == "variable-partselect-illegal-range"
    _assert_advisory(fs)


def test_rule30_silent_on_plus_colon_indexed_partselect():
    fs = _findings(L.rule_variable_partselect_illegal_range, GOOD_PARTSEL_PLUSCOLON)
    assert fs == []


def test_rule30_silent_on_parameter_derived_range():
    # Mirrors cvdp_copilot_fifo_async_0001's `[ADDR_WIDTH:ADDR_WIDTH-1]`
    # exactly (both bounds resolve to a declared parameter, not a signal).
    fs = _findings(L.rule_variable_partselect_illegal_range, GOOD_PARTSEL_PARAM)
    assert fs == []


# ---------------------------------------------------------------------------
# Rule 31 — booth-shift-before-signext
# ---------------------------------------------------------------------------
BAD_BOOTH = """
module booth_bad (
    input clk,
    input signed [15:0] x,
    output reg signed [31:0] pp0
);
    always @(posedge clk) begin
        pp0 <= x <<< 2;
    end
endmodule
"""

GOOD_BOOTH_FUNC = """
module booth_good (
    input clk,
    input signed [15:0] x_s1,
    output reg signed [31:0] pp0
);
    function signed [31:0] booth_term;
        input signed [31:0] x32;
        input [2:0] g;
        begin
            booth_term = x32;
        end
    endfunction
    wire signed [31:0] x32 = {{16{x_s1[15]}}, x_s1};
    always @(posedge clk) begin
        pp0 <= booth_term(x32, 3'b001) <<< 2;
    end
endmodule
"""


def test_rule31_fires_on_narrow_operand_shifted_before_widen():
    fs = _findings(L.rule_booth_shift_before_signext, BAD_BOOTH)
    assert len(fs) == 1
    assert fs[0].rule == "booth-shift-before-signext"
    _assert_advisory(fs)


def test_rule31_silent_on_full_width_function_return():
    # Mirrors cvdp_copilot_modified_booth_mul_0005's booth_term() idiom
    # exactly (the recoder function's OWN return type is already the full
    # 32-bit product width).
    fs = _findings(L.rule_booth_shift_before_signext, GOOD_BOOTH_FUNC)
    assert fs == []


# ---------------------------------------------------------------------------
# Wiring sanity: all six rules are enabled in lint_file() and stay advisory
# (never contribute to rc=1) end-to-end through the CLI.
# ---------------------------------------------------------------------------
def test_all_six_rules_wired_into_lint_file(tmp_path):
    p = tmp_path / "bad.sv"
    p.write_text(BAD_DIVIDER + BAD_MULTIOP + BAD_CASCADE + BAD_SEQMUL
                 + BAD_PARTSEL + BAD_BOOTH)
    findings = L.lint_file(p)
    fired_rules = {f.rule for f in findings}
    expected = {
        "divider-missing-final-correction",
        "multiop-arith-width-consistency",
        "cascaded-decrement-priority-order",
        "seq-multiplier-width",
        "variable-partselect-illegal-range",
        "booth-shift-before-signext",
    }
    assert expected.issubset(fired_rules), fired_rules
    for f in findings:
        if f.rule in expected:
            assert f.severity == "INFO"
            assert f.block_eligible is False

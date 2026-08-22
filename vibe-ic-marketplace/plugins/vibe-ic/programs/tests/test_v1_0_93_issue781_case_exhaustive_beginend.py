#!/usr/bin/env python3
"""Regression test for ORGANIC #781 (round-8 cluster R8C2).

`rtl_hygiene_lint._case_is_exhaustive` wrongly judged a FULLY-ENUMERATED
symbolic-localparam FSM written with the ubiquitous `LABEL: begin … end` branch
idiom as NON-exhaustive, so a combinational `always @(*)` FSM with no `default`
HARD-BLOCKED (case-no-default WARN, rc=1) — a false positive.

Root cause: the label-head regex's `(?<=\\bbegin\\b)` / `(?<=\\bend\\b)`
statement-boundary lookbehinds do NOT consume the keyword and the head class
admits whitespace, so the trailing `end`(s) of one branch bleed into the next
label head (e.g. head = 'end\\n  ENTRY_PROCESSING'); the old comma-only split
left a single un-resolvable part → `_label_value` returned None → the case was
wrongly judged non-exhaustive.

Fix: split each label head on whitespace AND commas, then drop the structural
Verilog keyword tokens (begin/end/…) before resolving. A fully-enumerated
begin/end FSM is then recognised exactly like its single-statement twin, while
genuinely partial / symbolic-unknown / out-of-range cases still bail and
hard-block (§4.05 no-leak preserved).

Covers:
  POSITIVE  — the FP now passes (rc=0) and matches its single-statement twin.
  §4.05 NO-LEAK (case-class) — partial / symbolic-unknown / missing-state
    begin/end FSMs still hard-block (rc=1).
  §4.05 NO-LEAK (broader gate) — reset-less DFF, free-running output, and a
    genuine cross-domain same-module race still hard-block (rc=1).

Self-contained: every fixture is authored inline; no host artifacts.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'rtl_hygiene_lint.py'
assert SCRIPT.exists(), SCRIPT

sys.path.insert(0, str(SCRIPT.parent))
import rtl_hygiene_lint as rhl  # noqa: E402


def _run(tmp_path, sv, name='dut.sv', severity='WARN'):
    """Run the real program via subprocess; return (returncode, stdout)."""
    f = tmp_path / name
    f.write_text(sv)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--severity', severity, str(f)],
        capture_output=True, text=True)
    return res.returncode, res.stdout


# ---------------------------------------------------------------------------
# Fixtures (inline, self-contained)
# ---------------------------------------------------------------------------

# The round-8 shape: combinational always @(*), symbolic localparams, begin/end
# branch idiom, ALL 4 states of a 2-bit selector enumerated, no default.
FSM_BEGINEND_EXHAUSTIVE = """
module car_parking_fsm (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [1:0]  state,
    input  wire        sensor,
    output reg  [1:0]  next_state,
    output reg         gate_open
);
    localparam IDLE             = 2'd0;
    localparam ENTRY_PROCESSING = 2'd1;
    localparam EXIT_PROCESSING  = 2'd2;
    localparam FULL             = 2'd3;
    always @(*) begin
        case (state)
            IDLE: begin
                next_state = sensor ? ENTRY_PROCESSING : IDLE;
                gate_open  = 1'b0;
            end
            ENTRY_PROCESSING: begin
                next_state = FULL;
                gate_open  = 1'b1;
            end
            EXIT_PROCESSING: begin
                next_state = IDLE;
                gate_open  = 1'b1;
            end
            FULL: begin
                next_state = sensor ? EXIT_PROCESSING : FULL;
                gate_open  = 1'b0;
            end
        endcase
    end
endmodule
"""

# Same FSM, single-statement branch idiom — already passed pre-#781 via #764.
FSM_SINGLESTMT_EXHAUSTIVE = """
module fsm_single (
    input  wire [1:0]  state,
    output reg  [1:0]  next_state
);
    localparam IDLE             = 2'd0;
    localparam ENTRY_PROCESSING = 2'd1;
    localparam EXIT_PROCESSING  = 2'd2;
    localparam FULL             = 2'd3;
    always @(*) begin
        case (state)
            IDLE:             next_state = ENTRY_PROCESSING;
            ENTRY_PROCESSING: next_state = FULL;
            EXIT_PROCESSING:  next_state = IDLE;
            FULL:             next_state = EXIT_PROCESSING;
        endcase
    end
endmodule
"""

# NO-LEAK: only 3 of 4 states enumerated, begin/end, no default -> latch risk.
FSM_BEGINEND_PARTIAL = """
module partial_fsm (
    input  wire [1:0]  state,
    output reg  [1:0]  next_state
);
    localparam IDLE             = 2'd0;
    localparam ENTRY_PROCESSING = 2'd1;
    localparam EXIT_PROCESSING  = 2'd2;
    always @(*) begin
        case (state)
            IDLE: begin
                next_state = ENTRY_PROCESSING;
            end
            ENTRY_PROCESSING: begin
                next_state = EXIT_PROCESSING;
            end
            EXIT_PROCESSING: begin
                next_state = IDLE;
            end
        endcase
    end
endmodule
"""

# NO-LEAK: labels are NOT resolvable localparams (declared elsewhere / unknown).
FSM_BEGINEND_SYMBOLIC_UNKNOWN = """
module symbolic_fsm (
    input  wire [1:0]  state,
    output reg  [1:0]  next_state
);
    always @(*) begin
        case (state)
            S_IDLE: begin
                next_state = S_RUN;
            end
            S_RUN: begin
                next_state = S_DONE;
            end
            S_DONE: begin
                next_state = S_IDLE;
            end
            S_WAIT: begin
                next_state = S_IDLE;
            end
        endcase
    end
endmodule
"""

# NO-LEAK: 2 of 4 states only -> genuinely non-exhaustive, begin/end, no default.
FSM_BEGINEND_MISSING_STATE = """
module missing_state_fsm (
    input  wire [1:0]  state,
    output reg  [1:0]  next_state
);
    localparam IDLE = 2'd0;
    localparam RUN  = 2'd1;
    always @(*) begin
        case (state)
            IDLE: begin
                next_state = RUN;
            end
            RUN: begin
                next_state = IDLE;
            end
        endcase
    end
endmodule
"""

# NO-LEAK (broader gate): reset-less registered output, no power-up init.
RESETLESS_DFF = """
module resetless_dff (
    input  wire clk,
    input  wire d,
    output reg  q
);
    always @(posedge clk) begin
        q <= d;
    end
endmodule
"""

# NO-LEAK (broader gate): free-running output never reset, no init.
FREERUNNING_COUNTER = """
module freerunning_counter (
    input  wire        clk,
    output reg  [7:0]  count
);
    always @(posedge clk) begin
        count <= count + 1'b1;
    end
endmodule
"""

# NO-LEAK (broader gate): genuine cross-domain same-module race (multidriven).
CROSS_DOMAIN_RACE = """
module cross_domain_race (
    input  wire clk_a,
    input  wire clk_b,
    input  wire da,
    input  wire db,
    output reg  shared
);
    always @(posedge clk_a) begin
        shared <= da;
    end
    always @(posedge clk_b) begin
        shared <= db;
    end
endmodule
"""


# ---------------------------------------------------------------------------
# POSITIVE — the #781 FP now passes
# ---------------------------------------------------------------------------
class TestPositiveBeginEndExhaustive:
    def test_combinational_beginend_fsm_passes(self, tmp_path):
        """The exact round-8 shape no longer HARD-BLOCKS."""
        rc, out = _run(tmp_path, FSM_BEGINEND_EXHAUSTIVE)
        assert rc == 0, out
        assert 'case-no-default' not in out, out

    def test_beginend_matches_singlestmt_twin(self, tmp_path):
        """begin/end FSM is recognised exactly like its single-statement twin."""
        rc_begin, _ = _run(tmp_path, FSM_BEGINEND_EXHAUSTIVE, name='begin.sv')
        rc_single, _ = _run(tmp_path, FSM_SINGLESTMT_EXHAUSTIVE, name='single.sv')
        assert rc_begin == rc_single == 0

    def test_case_is_exhaustive_helper_true(self):
        """Direct helper check: the begin/end exhaustive case is True."""
        src = rhl.strip_comments(FSM_BEGINEND_EXHAUSTIVE)
        import re
        m = re.search(r'case\s*\(([^)]+)\)(.*?)endcase', src, re.DOTALL)
        block = m.group(0)
        assert rhl._case_is_exhaustive(src, 'state', block) is True


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — genuine case-class defects still hard-block
# ---------------------------------------------------------------------------
class TestNoLeakCaseClass:
    @pytest.mark.parametrize('sv,name', [
        (FSM_BEGINEND_PARTIAL, 'partial.sv'),
        (FSM_BEGINEND_SYMBOLIC_UNKNOWN, 'symbolic.sv'),
        (FSM_BEGINEND_MISSING_STATE, 'missing.sv'),
    ])
    def test_genuine_nonexhaustive_beginend_still_blocks(self, tmp_path, sv, name):
        rc, out = _run(tmp_path, sv, name=name)
        assert rc == 1, out
        assert 'case-no-default' in out, out

    def test_partial_helper_false(self):
        src = rhl.strip_comments(FSM_BEGINEND_PARTIAL)
        import re
        m = re.search(r'case\s*\(([^)]+)\)(.*?)endcase', src, re.DOTALL)
        assert rhl._case_is_exhaustive(src, 'state', m.group(0)) is False

    def test_symbolic_unknown_helper_false(self):
        src = rhl.strip_comments(FSM_BEGINEND_SYMBOLIC_UNKNOWN)
        import re
        m = re.search(r'case\s*\(([^)]+)\)(.*?)endcase', src, re.DOTALL)
        assert rhl._case_is_exhaustive(src, 'state', m.group(0)) is False


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — broader hygiene gate unaffected (no collateral relaxation)
# ---------------------------------------------------------------------------
class TestNoLeakBroaderGate:
    @pytest.mark.parametrize('sv,name', [
        (RESETLESS_DFF, 'resetless.sv'),
        (FREERUNNING_COUNTER, 'freerun.sv'),
        (CROSS_DOMAIN_RACE, 'race.sv'),
    ])
    def test_other_rules_still_block(self, tmp_path, sv, name):
        rc, out = _run(tmp_path, sv, name=name)
        assert rc == 1, out


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))

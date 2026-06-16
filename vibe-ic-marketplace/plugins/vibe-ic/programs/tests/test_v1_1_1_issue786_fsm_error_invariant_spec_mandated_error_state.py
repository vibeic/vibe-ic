#!/usr/bin/env python3
"""Regression for issue #786 (CVDP convergence round-9 cluster R9C2).

fsm_error_invariant.find_error_assertions() HARD-BLOCKED (rc=1) a
spec-faithful FSM that asserts a spec-mandated error output inside a
fault/error STATE branch (e.g. localparam FAULT: o_error <= 1'b1, the
literal spec requirement "FAULT: Asserts o_error to indicate a fault
condition"). Two root causes:

  (a) the gate never tested whether the enclosing state is one the spec
      mandates to assert error (contradicting its own docstring), and
  (b) the state-label regex (S_\\w+ / numeric only) could not resolve a
      localparam-named label like FAULT, so the spec-mandated branch was
      mis-attributed to "<not in case branch>".

Fix (chip-AGNOSTIC, fsm_error_invariant.py only):
  * widen the case-label regex to capture NAMED localparam/parameter
    labels (excluding `default:` / ternaries / assignments), and
  * add _is_fault_state() reusing the ERROR_NAMES vocabulary (+fault/
    fatal) and SKIP a finding when the enclosing state label semantically
    denotes a fault/error condition.

§4.05 NO-LEAK: a spurious error assertion in a NON-error operational
state (IDLE/RUN/PROCESS/RX), under a numeric-literal label, or the
classic recoverable-error mid-decode anti-pattern must STILL hard-block
(rc=1). These negatives are asserted below.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "fsm_error_invariant.py"
assert PROG.exists(), PROG

sys.path.insert(0, str(PROG.parent))
import fsm_error_invariant as fei  # noqa: E402


def _run(rtl_text: str, tmp_path: Path) -> subprocess.CompletedProcess:
    f = tmp_path / "dut.v"
    f.write_text(rtl_text)
    return subprocess.run(
        [sys.executable, str(PROG), str(f)],
        capture_output=True, text=True)


# ---------------------------------------------------------------------------
# POSITIVE — the round-9 false-positive shape now PASSes (rc=0).
# ---------------------------------------------------------------------------

# A FAULT localparam-named state branch asserting a spec-mandated error
# output. Mirrors cvdp_copilot_concatenate_0001: "FAULT: Asserts o_error
# to indicate a fault condition".
_FAULT_STATE_RTL = """\
module concatenate (
    input  wire clk,
    input  wire rst_n,
    output reg  o_error
);
    localparam IDLE    = 2'd0;
    localparam PROCESS = 2'd1;
    localparam FAULT   = 2'd2;
    reg [1:0] state;
    always @(posedge clk) begin
        case (state)
            IDLE:    o_error <= 1'b0;
            PROCESS: o_error <= 1'b0;
            FAULT: begin
                // FAULT: Asserts o_error to indicate a fault condition
                o_error <= 1'b1;
            end
            default: ;
        endcase
    end
endmodule
"""


def test_issue786_fault_named_state_no_longer_blocks(tmp_path):
    """The spec-mandated error assertion inside a FAULT state must NOT
    hard-block (round-9 FP). Was rc=1 mis-attributed to
    '<not in case branch>'; now rc=0."""
    r = _run(_FAULT_STATE_RTL, tmp_path)
    assert r.returncode == 0, \
        f"FAULT-named state error assert should not block: {r.stdout}"


@pytest.mark.parametrize("label", [
    "ERROR", "ERR", "FAIL", "FAULT", "ABORT", "FATAL",
    "TIMEOUT", "REJECT", "INVALID",
    "S_ERROR", "ST_FAULT", "STATE_ABORT",
])
def test_issue786_fault_vocab_state_labels_recognised(label):
    """_is_fault_state() recognises the full error/fault vocabulary,
    including S_/ST_/STATE_ prefixed variants."""
    assert fei._is_fault_state(label) is True


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — genuine same-class defects must STILL hard-block (rc=1).
# ---------------------------------------------------------------------------

# A spurious error fired in a NON-error operational state (PROCESS). This
# is exactly the cross-layer anti-pattern the gate targets.
_OPERATIONAL_STATE_RTL = """\
module m(input clk, output reg o_error);
    localparam IDLE = 2'd0, PROCESS = 2'd1, DONE = 2'd2;
    reg [1:0] state;
    always @(posedge clk) begin
        case (state)
            IDLE:    o_error <= 1'b0;
            PROCESS: begin
                o_error <= 1'b1;
            end
            DONE:    ;
            default: ;
        endcase
    end
endmodule
"""

# A numeric-literal label state — carries no fault semantics, must fire.
_NUMERIC_LABEL_RTL = """\
module m(input clk, output reg rx_error);
    reg [2:0] state;
    always @(posedge clk) begin
        case (state)
            3'd0: ;
            3'd1: begin
                rx_error <= 1'b1;
            end
            default: ;
        endcase
    end
endmodule
"""

# The classic recoverable-error mid-decode anti-pattern in a named, but
# NON-error, operational state (S_RX_BIT).
_CLASSIC_ANTIPATTERN_RTL = """\
module rx_fsm(input clk);
    reg rx_error;
    reg [3:0] state;
    always @(posedge clk) begin
        case (state)
            S_RX_BIT: begin
                rx_error <= 1'b1;
            end
        endcase
    end
endmodule
"""


def test_issue786_noleak_spurious_error_in_operational_state(tmp_path):
    """NO-LEAK: o_error asserted in PROCESS (non-error operational state)
    still hard-blocks."""
    r = _run(_OPERATIONAL_STATE_RTL, tmp_path)
    assert r.returncode == 1, \
        f"spurious error in operational state must still fire: {r.stdout}"
    assert "PROCESS" in r.stdout


def test_issue786_noleak_numeric_label_state(tmp_path):
    """NO-LEAK: error asserted under a numeric-literal label (3'd1) still
    hard-blocks — numeric labels carry no fault semantics."""
    r = _run(_NUMERIC_LABEL_RTL, tmp_path)
    assert r.returncode == 1, \
        f"numeric-label error assert must still fire: {r.stdout}"


def test_issue786_noleak_classic_mid_decode_antipattern(tmp_path):
    """NO-LEAK: the classic recoverable-error mid-decode anti-pattern in a
    named non-error state (S_RX_BIT) still hard-blocks."""
    r = _run(_CLASSIC_ANTIPATTERN_RTL, tmp_path)
    assert r.returncode == 1, \
        f"classic mid-decode anti-pattern must still fire: {r.stdout}"


def test_issue786_is_fault_state_negatives():
    """_is_fault_state() returns False for non-fault / numeric / empty
    labels so the no-leak path is preserved at the helper level."""
    for label in ("IDLE", "PROCESS", "RUN", "RX", "S_RX_BIT", "READY",
                  "DONE", "S_IDLE", "ST_RUN"):
        assert fei._is_fault_state(label) is False, label
    for label in ("2'b11", "3'd5", "4'hF", "8'd255"):
        assert fei._is_fault_state(label) is False, label
    assert fei._is_fault_state(None) is False
    assert fei._is_fault_state("") is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

"""Boundary tests for ordered one-cycle FSM phase conformance.

The positive fixture collapses a prompt-declared pulse phase and a later input
monitoring phase.  Each negative removes exactly one proof anchor so the rule
cannot grow into a generic "input used in an FSM" false-positive detector.
"""
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import spec_conformance_check as C  # noqa: E402
from _specrtl_common import (classify_rtl_resets, extract_spec_contract,
                             parse_rtl_ports, strip_comments)  # noqa: E402


PROMPT = """
Build a synchronous finite-state controller with inputs clk, resetn, sense and
output pulse. When reset is released, set the output pulse to 1 for one clock
cycle. Then, the controller has to monitor the sense input for a 1,0,1 pattern.

module TopModule(input clk, input resetn, input sense, output pulse);
"""


BAD_RTL = """
module TopModule(input clk, input resetn, input sense, output pulse);
  localparam IDLE=0, PULSE=1, WATCH=2, SEEN=3;
  reg [1:0] state, next;
  always @(*) begin
    case (state)
      IDLE:  next = PULSE;
      PULSE: next = sense ? SEEN : WATCH;
      WATCH: next = sense ? SEEN : WATCH;
      SEEN:  next = SEEN;
      default: next = IDLE;
    endcase
  end
  always @(posedge clk) if (!resetn) state <= IDLE; else state <= next;
  assign pulse = (state == PULSE);
endmodule
"""


GOOD_RTL = BAD_RTL.replace(
    "PULSE: next = sense ? SEEN : WATCH;",
    "PULSE: next = WATCH;")


def _ordered_findings(prompt, rtl):
    body = strip_comments(rtl)
    name, ports = parse_rtl_ports(body, "TopModule")
    findings = C.check(
        extract_spec_contract(prompt), name, ports,
        classify_rtl_resets(body), None, "fixture.sv", body,
        spec_text=prompt)
    return [f for f in findings if f.rule == "ordered-phase-monitoring-early"]


def test_reads_later_input_in_pulse_state_fires():
    got = _ordered_findings(PROMPT, BAD_RTL)
    assert len(got) == 1
    assert got[0].severity == "ERROR"
    assert got[0].symbol == "PULSE"
    assert "sense" in got[0].message


def test_separate_pulse_and_monitor_states_do_not_fire():
    assert _ordered_findings(PROMPT, GOOD_RTL) == []


def test_prompt_that_monitors_during_pulse_does_not_fire():
    concurrent = PROMPT.replace(
        "cycle. Then, the controller has to monitor the sense input",
        "cycle while monitoring the sense input")
    assert _ordered_findings(concurrent, BAD_RTL) == []


def test_conditional_then_is_not_misread_as_temporal_order():
    conditional = PROMPT.replace(
        "cycle. Then, the controller has to monitor the sense input",
        "cycle if armed; if armed, then monitor the sense input")
    assert _ordered_findings(conditional, BAD_RTL) == []


def test_same_input_used_only_in_later_state_does_not_fire():
    assert "sense" in GOOD_RTL
    assert _ordered_findings(PROMPT, GOOD_RTL) == []


def test_indirect_output_decode_is_out_of_scope_and_does_not_fire():
    indirect = BAD_RTL.replace(
        "assign pulse = (state == PULSE);",
        "wire pulse_state = (state == PULSE); assign pulse = pulse_state;")
    assert _ordered_findings(PROMPT, indirect) == []

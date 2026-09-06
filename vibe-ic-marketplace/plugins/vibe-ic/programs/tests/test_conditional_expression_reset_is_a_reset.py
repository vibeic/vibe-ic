"""A reset written as a CONDITIONAL EXPRESSION is a reset.

`_specrtl_common.classify_rtl_resets` only ever looked for an `if` inside a
sequential block, so the idiomatic

    always @(posedge clk) state <= (~resetn) ? A : next;

registered NO reset at all.  `spec_conformance_check` then reported
`reset-not-found` against a spec that plainly declares one, and a `--strict`
caller REJECTED the design.

Measured on VerilogEval-Human `Prob139_2013_q2bfsm` (2026-09-06, host 8hd-3):
the ternary-reset answer scores `Mismatches: 0 in 1002 samples` against the
official golden, and the gate rejected it; the asynchronous-reset rewrite the
rejection invites scores `Mismatches: 33 in 1002 samples`.  So the false
negative pushed a CORRECT design toward a wrong one.

The tests below pin all four directions: the correct design is accepted, the
new detection is classified correctly in both reset modes, an ordinary datapath
ternary is still NOT a reset, and the genuinely-wrong asynchronous design is
still REJECTED (the check did not become vacuous).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).parent.parent
SCRIPT = PROGRAMS / 'spec_conformance_check.py'
assert SCRIPT.exists()
sys.path.insert(0, str(PROGRAMS))
import _specrtl_common as _c  # noqa: E402

SPEC = """
An FSM with a clock input called clk and a reset input (synchronous, active
low) called resetn.

module TopModule (
  input clk,
  input resetn,
  input x,
  output f
);
"""

# The spec-faithful design: a synchronous active-low reset written as a
# conditional expression rather than as an `if`.
TERNARY_SYNC = """
module TopModule (input clk, input resetn, input x, output f);
  reg [1:0] state, next;
  always @(posedge clk) state <= (~resetn) ? 2'd0 : next;
  always @(*) next = x ? 2'd1 : 2'd0;
  assign f = (state == 2'd1);
endmodule
"""

# The rewrite the false rejection invites: an ASYNCHRONOUS reset, which the
# spec does not describe.
ASYNC = """
module TopModule (input clk, input resetn, input x, output f);
  reg [1:0] state, next;
  always @(posedge clk or negedge resetn)
    if (~resetn) state <= 2'd0; else state <= next;
  always @(*) next = x ? 2'd1 : 2'd0;
  assign f = (state == 2'd1);
endmodule
"""


def _run(sv, *extra):
    d = Path(tempfile.mkdtemp())
    (d / 'spec.txt').write_text(SPEC)
    (d / 'dut.sv').write_text(sv)
    jf = d / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(d / 'spec.txt'),
         '--top', 'TopModule', '--json', str(jf), *extra, str(d / 'dut.sv')],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, {f.get('rule') for f in findings}


def test_ternary_reset_is_not_reported_missing():
    """RED fixture: the design the gate used to reject."""
    res, rules = _run(TERNARY_SYNC)
    assert 'reset-not-found' not in rules, res.stdout
    assert res.returncode == 0, res.stdout


def test_ternary_reset_design_survives_strict():
    """A --strict caller must not reject a spec-faithful ternary reset."""
    res, rules = _run(TERNARY_SYNC, '--strict')
    assert res.returncode == 0, res.stdout
    assert 'reset-not-found' not in rules


def test_conditional_sync_reset_is_classified():
    got = _c.classify_rtl_resets(
        'always @(posedge clk) q <= (~resetn) ? 1\'b0 : d;')
    assert got.get('resetn', {}).get('mode') == {'synchronous'}
    assert got.get('resetn', {}).get('polarity') == {'active-low'}


def test_conditional_async_reset_takes_its_mode_from_the_sensitivity_list():
    got = _c.classify_rtl_resets(
        'always @(posedge clk or posedge rst) q <= rst ? 1\'b0 : d;')
    assert got.get('rst', {}).get('mode') == {'asynchronous'}
    assert got.get('rst', {}).get('polarity') == {'active-high'}


def test_a_datapath_ternary_is_not_a_reset():
    """FALSE-POSITIVE guard: an ordinary select must stay invisible."""
    assert _c.classify_rtl_resets(
        'always @(posedge clk) y <= sel ? a : b;') == {}


def test_an_if_reset_still_wins_over_a_later_ternary():
    """The `if` form keeps its exact previous answer; the new path is a
    fallback, never an override."""
    got = _c.classify_rtl_resets(
        'always @(posedge clk) begin if (rst_n == 0) q <= 0; '
        'else q <= sel ? a : b; end')
    assert set(got) == {'rst_n'}
    assert got['rst_n']['mode'] == {'synchronous'}
    assert got['rst_n']['polarity'] == {'active-low'}


def test_mutation_the_check_did_not_become_vacuous():
    """MUTATION: the wrong reset mode must still be REJECTED.  A fix that
    silences `reset-not-found` by silencing the whole rule would pass every
    test above and fail this one."""
    res, rules = _run(ASYNC)
    assert 'reset-mode-spec-mismatch' in rules, res.stdout
    assert res.returncode == 1, res.stdout

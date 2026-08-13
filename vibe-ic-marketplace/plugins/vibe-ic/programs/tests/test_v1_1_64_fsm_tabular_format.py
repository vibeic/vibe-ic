"""v1.1.64 — full_moore_fsm_synth tabular-table format + reset-phrasing robustness.

Extends the Moore-FSM solver to the `State | Next@in=0, Next@in=1 | Output` table
format (in addition to the `A (0) --1--> B` arrow form) and to the "resets the FSM
to state A" / "positive edge triggered asynchronous reset" phrasings. This converts
Prob119_fsm3, Prob120_fsm3s, Prob121_2014_q3bfsm from AI-authored to
program-GENERATED (all host-score PASS).

§4.05: still SKIP on any under-specified reset / incomplete table; binary-named
states are fine because the Moore TB observes only the output (encoding is free).
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import full_moore_fsm_synth as F  # noqa: E402

import pytest

#: The repo's existing tool gate (197 files use this shape). Without
#: it this module raises FileNotFoundError on a host that lacks the
#: tool, instead of disclosing a skip.
_HAVE_TOOLS = bool(shutil.which("iverilog"))

_HDR = (
    "I would like you to implement a module named TopModule with the following\n"
    "interface. All input and output ports are one bit unless otherwise specified.\n\n")

# tabular + "asynchronous reset that resets the FSM to state A" + positive-edge-triggered
TAB_ASYNC = _HDR + (
    " - input  clk\n - input  areset\n - input  in\n - output out\n\n"
    "The module should implement a Moore state machine with the following state\n"
    "transition table. Include a positive edge triggered asynchronous reset that\n"
    "resets the FSM to state A. Assume all sequential logic is triggered on the\n"
    "positive edge of the clock.\n\n"
    "  state | next state in=0, next state in=1 | output\n"
    "  A     | A, B                             | 0\n"
    "  B     | C, B                             | 0\n"
    "  C     | A, D                             | 0\n"
    "  D     | C, B                             | 1\n")

# tabular + synchronous active-high reset to A
TAB_SYNC = _HDR + (
    " - input  clk\n - input  reset\n - input  in\n - output out\n\n"
    "Include a synchronous active high reset that resets the FSM to state A.\n\n"
    "  State | Next state in=0, Next state in=1 | Output\n"
    "  A     | A, B | 0\n  B     | C, B | 0\n  C     | A, D | 0\n  D     | C, B | 1\n")

# binary-named states (Prob121 style) + sync active-high reset to 000
TAB_BIN = _HDR + (
    " - input  clk\n - input  reset\n - input  x\n - output z\n\n"
    "Reset should synchronous active high reset the FSM to state 000.\n\n"
    "  Present state y | Next state x=0, Next state x=1 | Output z\n"
    "  000 | 000, 001 | 0\n  001 | 001, 100 | 0\n  010 | 010, 001 | 0\n"
    "  011 | 001, 010 | 1\n  100 | 011, 100 | 1\n")


def _compiles(rtl, tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    f = tmp_path / "m.sv"
    f.write_text(rtl)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(f)],
                        capture_output=True, text=True)
    return cp.returncode == 0, cp.stderr


def test_tabular_async_fires_compiles(tmp_path):
    rtl = F.synth(TAB_ASYNC, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    assert "posedge clk or posedge areset" in rtl   # async active-high (positive-edge)


def test_tabular_sync_fires_compiles(tmp_path):
    rtl = F.synth(TAB_SYNC, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    assert "if (reset)" in rtl and "or posedge reset" not in rtl


def test_binary_named_states_fire(tmp_path):
    rtl = F.synth(TAB_BIN, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # output z honours the table's per-state Moore value (011 -> 1, 100 -> 1)
    assert "z = 1'b1;" in rtl and "z = 1'b0;" in rtl


def test_tabular_transitions_match_table():
    rtl = F.synth(TAB_ASYNC, "TopModule")
    # A: in=0->A, in=1->B ; D: in=0->C, in=1->B ; D output 1
    assert "S_A: nstate = in ? S_B : S_A;" in rtl
    assert "S_D: nstate = in ? S_B : S_C;" in rtl
    assert "S_D: out = 1'b1;" in rtl
    assert "if (areset) state <= S_A;" in rtl


def test_tabular_incomplete_row_skips():
    # a row missing the second next-state -> table regex won't match it -> SKIP
    bad = TAB_SYNC.replace("  D     | C, B | 1\n", "  D     | C | 1\n")
    assert F.synth(bad, "TopModule") is None


def test_tabular_still_skips_underspecified_reset():
    no_reset = TAB_ASYNC.replace(
        "Include a positive edge triggered asynchronous reset that\n"
        "resets the FSM to state A. ", "")
    assert F.synth(no_reset, "TopModule") is None


def test_skip_intervening_reset_state_clause():
    # Step-2.7 tabular review Finding 1: a clause naming a DIFFERENT state before
    # the real reset target must SKIP (ambiguous), not grab the first "to state X".
    p = TAB_SYNC.replace(
        "Include a synchronous active high reset that resets the FSM to state A.",
        "The active high synchronous reset takes priority over the transition to "
        "state D and forces the machine to state A.")
    assert F.synth(p, "TopModule") is None

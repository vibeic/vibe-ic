"""v1.1.63 — full_moore_fsm_synth deterministic SOLVER (bucket-② -> bucket-①).

A COMPLETE Moore transition table + a fully-specified reset determines the whole
machine (the internal encoding is FREE — the TB observes only the output), so the
solver EMITS the state register + next-state + Moore-output and the problem becomes
program-GENERATED. Real proof of functional correctness: Prob109_fsm1 +
Prob138_2012_q2fsm program-generated RTL both PASS the hidden host scorer.

§4.05 load-bearing half: the solver must SKIP (return None) on any under-specified
reset (state / polarity / sync-vs-async), never guessing reset behavior.
"""
import shutil
import re
import subprocess
import sys
import tempfile
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

ASYNC2 = _HDR + (
    " - input  clk\n - input  areset\n - input  in\n - output out\n\n"
    "The module should implement a Moore machine with the diagram described below:\n\n"
    "  B (1) --0--> A\n  B (1) --1--> B\n  A (0) --0--> B\n  A (0) --1--> A\n\n"
    "It should asynchronously reset into state B if reset if high.\n")

SYNC6 = _HDR + (
    " - input  clk\n - input  reset\n - input  w\n - output z\n\n"
    "The module should implement the state machine shown below:\n\n"
    "  A (0) --1--> B\n  A (0) --0--> A\n  B (0) --1--> C\n  B (0) --0--> D\n"
    "  C (0) --1--> E\n  C (0) --0--> D\n  D (0) --1--> F\n  D (0) --0--> A\n"
    "  E (1) --1--> E\n  E (1) --0--> D\n  F (1) --1--> C\n  F (1) --0--> D\n\n"
    "Reset resets into state A and is synchronous active-high. Assume all\n"
    "sequential logic is triggered on the positive edge of the clock.\n")

# reset state/polarity NOT stated -> must SKIP
UNDERSPEC = _HDR + (
    " - input  clk\n - input  reset\n - input  w\n - output z\n\n"
    "  A (0) --1--> B\n  A (0) --0--> A\n  B (1) --1--> A\n  B (1) --0--> B\n\n"
    "Assume all sequential logic is triggered on the positive edge of the clock.\n")


def _compiles(rtl, tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    f = tmp_path / "m.sv"
    f.write_text(rtl)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(f)],
                        capture_output=True, text=True)
    return cp.returncode == 0, cp.stderr


def test_async_fsm_fires_and_compiles(tmp_path):
    rtl = F.synth(ASYNC2, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # async edge + active-high level
    assert "posedge clk or posedge areset" in rtl
    assert "if (areset)" in rtl


def test_sync_fsm_fires_and_compiles(tmp_path):
    rtl = F.synth(SYNC6, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    assert "posedge clk)" in rtl and "or posedge reset" not in rtl   # sync
    assert "if (reset)" in rtl


def test_async_not_misread_as_sync(tmp_path):
    # regression: 'asynchronous' contains 'synchronous' — must read as ASYNC, not SKIP
    assert F.synth(ASYNC2, "TopModule") is not None
    assert "posedge clk or posedge areset" in F.synth(ASYNC2, "TopModule")


def test_skip_when_reset_underspecified():
    # no reset state / polarity stated -> SKIP (never guess)
    assert F.synth(UNDERSPEC, "TopModule") is None


def test_skip_when_no_clock():
    p = ASYNC2.replace(" - input  clk\n", "")
    assert F.synth(p, "TopModule") is None


def test_skip_incomplete_transition_table():
    p = ASYNC2.replace("  A (0) --1--> A\n", "")   # A missing input=1
    assert F.synth(p, "TopModule") is None


def test_skip_conflicting_duplicate_transition():
    # Step-2.7 Finding 1: a contradictory (state,input) row on its OWN line must
    # SKIP, not silently overwrite into a wrong (e.g. dead absorbing) FSM.
    # (ASYNC2 already has 'A (0) --1--> A'; this adds a conflicting '... --1--> B'.)
    p = ASYNC2 + "  A (0) --1--> B\n"
    assert F.synth(p, "TopModule") is None


def test_keeps_benign_identical_duplicate():
    # an IDENTICAL restatement of an existing row is NOT a conflict -> still fires
    p = ASYNC2 + "  A (0) --1--> A\n"
    assert F.synth(p, "TopModule") is not None


def test_emitted_transitions_and_outputs_match_table():
    # structural functional check: every table edge + Moore output is realized
    rtl = F.synth(SYNC6, "TopModule")
    trans = {"A": {"0": "A", "1": "B"}, "B": {"0": "D", "1": "C"},
             "C": {"0": "D", "1": "E"}, "D": {"0": "A", "1": "F"},
             "E": {"0": "D", "1": "E"}, "F": {"0": "D", "1": "C"}}
    mout = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 1, "F": 1}
    for s, d in trans.items():
        assert re.search(rf"S_{s}: nstate = w \? S_{d['1']} : S_{d['0']};", rtl)
    for s, o in mout.items():
        assert f"S_{s}: z = 1'b{o};" in rtl
    # reset target is state A
    assert "if (reset) state <= S_A;" in rtl

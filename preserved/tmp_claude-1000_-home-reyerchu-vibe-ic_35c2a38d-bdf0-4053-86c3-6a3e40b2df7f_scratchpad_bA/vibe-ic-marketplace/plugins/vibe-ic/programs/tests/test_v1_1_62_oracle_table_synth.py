"""v1.1.62 — oracle_table_synth deterministic SOLVER (moves bucket-② -> bucket-①).

When the prompt embeds a COMPLETE combinational oracle (truth table / K-map /
binary-encoded FSM next-state-bit), oracle_table_synth EMITS the RTL implementing
it directly, so the problem is program-GENERATED (zero authoring variance) rather
than AI-authored-then-gated. These tests verify the emitted RTL is valid Verilog
that EXACTLY matches the parsed oracle (checked by re-running the gate on the
emitted RTL), and that the solver SKIPs (returns None) on any non-oracle prompt
(§4.05 no-leak: a SKIP leaves the author's sample untouched).
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import oracle_table_synth as S            # noqa: E402
import kmap_truth_table_oracle_check as K  # noqa: E402

import shutil  # noqa: E402
import pytest  # noqa: E402

#: The marked tests below reach `iverilog` — through the oracle's own simulate
#: step — and without it they die with FileNotFoundError BEFORE any assertion
#: runs. That is not a verdict about the RTL; it is the tool never having been
#: there. Marked ONE BY ONE from a measured list, not by helper and not by name:
#: two neighbours that call the same `_verdict()` helper are GREEN without a
#: toolchain, because they assert a SKIP the oracle reaches before it compiles,
#: and one marked test uses no helper at all.
#: BOTH binaries, measured rather than assumed: `iverilog` COMPILES and
#: `vvp` RUNS, and this oracle does both. Hiding either one alone fails the
#: same seven tests by name, so a guard naming only the compiler still dies
#: on a host that has it without the runtime — #1409 exactly ("guards on
#: iverilog alone, but ... also refuses without yosys"), and #1355 ("named
#: the BINARY, not the behaviour it needs"). `yosys` is deliberately NOT
#: required: hiding it leaves these files fully green, and over-declaring
#: skips on hosts that could have run.
_HAS_ORACLE_TOOLCHAIN = (shutil.which("iverilog") is not None
                         and shutil.which("vvp") is not None)
_needs_iverilog = pytest.mark.skipif(
    not _HAS_ORACLE_TOOLCHAIN,
    reason="the oracle compiles (iverilog) and runs (vvp) the design; without "
           "EITHER binary this dies with FileNotFoundError before asserting "
           "anything")


TRUTH = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  x3
 - input  x2
 - input  x1
 - output f

Implement the combinational circuit described by this truth table:

  x3 | x2 | x1 | f
  0  | 0  | 0  | 0
  0  | 0  | 1  | 0
  0  | 1  | 0  | 0
  0  | 1  | 1  | 1
  1  | 0  | 0  | 1
  1  | 0  | 1  | 1
  1  | 1  | 0  | 1
  1  | 1  | 1  | 0
"""

FSM = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  y (3 bits)
 - input  w
 - output Y1

The module should implement the state machine shown below:

  A (0) --0--> B
  A (0) --1--> A
  B (0) --0--> C
  B (0) --1--> D
  C (0) --0--> E
  C (0) --1--> D
  D (0) --0--> F
  D (0) --1--> A
  E (1) --0--> E
  E (1) --1--> D
  F (1) --0--> C
  F (1) --1--> D

The FSM should be implemented using three flip-flops and state codes
y = 000, 001, ..., 101 for states A, B, ..., F, respectively. Implement
just the next-state logic for y[1]. The output Y1 is y[1].
"""

NON_ORACLE = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  clk
 - input  reset
 - output q (4 bits)

Build a 4-bit binary counter that increments every clock and resets to 0.
"""


def _synth_then_gate(tmp_path, prompt):
    rtl = S.synth(prompt, "TopModule")
    assert rtl is not None, "solver should fire on a complete oracle"
    f = tmp_path / "synth.sv"
    f.write_text(rtl)
    # the gate re-derives the oracle and simulates the EMITTED rtl exhaustively;
    # PASS proves the emit is valid Verilog that EXACTLY matches the parsed table.
    return K.check(prompt, str(f))[0]


@_needs_iverilog
def test_truth_table_solver_emits_correct_rtl(tmp_path):
    assert _synth_then_gate(tmp_path, TRUTH) == "PASS"


@_needs_iverilog
def test_fsm_next_state_solver_emits_correct_rtl(tmp_path):
    assert _synth_then_gate(tmp_path, FSM) == "PASS"


def test_solver_skips_non_oracle_prompt():
    # §4.05: a sequential counter has no prompt-disclosed combinational oracle
    assert S.synth(NON_ORACLE, "TopModule") is None


def test_emitted_rtl_has_correct_interface(tmp_path):
    rtl = S.synth(FSM, "TopModule")
    assert "module TopModule(" in rtl
    assert "input [2:0] y" in rtl and "input w" in rtl and "output reg Y1" in rtl
    assert "case ({y, w})" in rtl


@_needs_iverilog
def test_truth_table_emitted_matches_hand_truth(tmp_path):
    # exhaustively confirm the emitted RTL realizes the declared table
    rtl = S.synth(TRUTH, "TopModule")
    expect = {(0, 0, 0): 0, (0, 0, 1): 0, (0, 1, 0): 0, (0, 1, 1): 1,
              (1, 0, 0): 1, (1, 0, 1): 1, (1, 1, 0): 1, (1, 1, 1): 0}
    # the gate's parser yields the same table; PASS on the emitted rtl == realized
    ins, outs = K.parse_ports(TRUTH)
    parsed = K.parse_truth_table(TRUTH, ins, outs)
    assert parsed is not None
    _kind, _names, _out, table = parsed
    assert table == expect
    f = tmp_path / "s.sv"
    f.write_text(rtl)
    assert K.check(TRUTH, str(f))[0] == "PASS"

#!/usr/bin/env python3
"""test_v1_1_76_fsm_prose.py — fsm_prose_synth.py (combinational one-hot FSM decode).

Pins the DETERMINISTIC subset this solver closes (Prob079 tabular, Prob143 arrow with
a multi-output K-tuple) and the §4.05 NO-LEAK contract: genuine behavioural-prose FSMs
(Lemmings, PS/2, serial, HDLC, the 1-0-1 / two-of-three counting FSMs) and any
incomplete / non-one-hot / wrong-shape table MUST return None. Host-scoring (iverilog
+ vvp == 0 mismatches) is the authoritative gate done at integration time; here we pin
the structural decode + the SKIP boundary so a future relaxation cannot leak.
"""
from __future__ import annotations
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fsm_prose_synth as F   # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers / real-prompt skeletons
# --------------------------------------------------------------------------- #
PROB079 = """\
 - input  in
 - input  state (4 bits)
 - output next_state (4 bits)
 - output out

The module should implement the state transition table for a Moore state
machine with one input, one output, and four states. Use the following
one-hot state encoding: A=4'b0001, B=4'b0010, C=4'b0100, D=4'b1000.
Implement only the state transition logic and output logic.

  State | Next state in=0, Next state in=1 | Output
  A     | A, B                             | 0
  B     | C, B                             | 0
  C     | A, D                             | 0
  D     | C, B                             | 1
"""

PROB143 = """\
 - input  in
 - input  state (10 bits)
 - output next_state (10 bits)
 - output out1
 - output out2

Given the follow state machine with 1 input and 2 outputs (the outputs
are given as "(out1, out2)"):

  S0 (0, 0) --0--> S0
  S0 (0, 0) --1--> S1
  S1 (0, 0) --0--> S0
  S1 (0, 0) --1--> S2
  S2 (0, 0) --0--> S0
  S2 (0, 0) --1--> S3
  S3 (0, 0) --0--> S0
  S3 (0, 0) --1--> S4
  S4 (0, 0) --0--> S0
  S4 (0, 0) --1--> S5
  S5 (0, 0) --0--> S8
  S5 (0, 0) --1--> S6
  S6 (0, 0) --0--> S9
  S6 (0, 0) --1--> S7
  S7 (0, 1) --0--> S0
  S7 (0, 1) --1--> S7
  S8 (1, 0) --0--> S0
  S8 (1, 0) --1--> S1
  S9 (1, 1) --0--> S0
  S9 (1, 1) --1--> S1

Suppose this state machine uses one-hot encoding, where state[0] through
state[9] correspond to the states S0 though S9, respectively.
"""


def _bit(rtl, sig):
    """return the RHS expression of `assign <sig> = ...;`"""
    m = re.search(rf"assign\s+{re.escape(sig)}\s*=\s*(.*?);", rtl)
    assert m, f"{sig} not assigned in:\n{rtl}"
    return m.group(1)


# --------------------------------------------------------------------------- #
# POSITIVES — the deterministic subset closed (structurally pinned)
# --------------------------------------------------------------------------- #
def test_prob079_tabular_fires():
    rtl = F.synth(PROB079, top="TopModule")
    assert rtl is not None
    assert "module TopModule(" in rtl
    assert "input [3:0] state" in rtl and "output [3:0] next_state" in rtl
    # NO clk/reset/register in the combinational decode.
    assert "clk" not in rtl and "reset" not in rtl and "always" not in rtl
    # out asserted only in state D (bit 3, per A=..0001,B=..0010,C=..0100,D=..1000).
    assert _bit(rtl, "out").strip() == "state[3]"
    # next_state[3] (=D) reached only from C(bit2) on in=1: C|A|D enc -> D from C&in.
    assert _bit(rtl, "next_state[3]").strip() == "(state[2] & in)"


def test_prob143_arrow_multioutput_fires():
    rtl = F.synth(PROB143, top="TopModule")
    assert rtl is not None
    assert "input [9:0] state" in rtl and "output [9:0] next_state" in rtl
    assert "output out1" in rtl and "output out2" in rtl
    # out1 = S8|S9 (bits 8,9); out2 = S7|S9 (bits 7,9) — per the (out1,out2) tuples.
    assert set(re.findall(r"state\[(\d+)\]", _bit(rtl, "out1"))) == {"8", "9"}
    assert set(re.findall(r"state\[(\d+)\]", _bit(rtl, "out2"))) == {"7", "9"}
    # next_state[7] reached from S6(in=1) and S7(in=1).
    nx7 = _bit(rtl, "next_state[7]")
    assert "(state[6] & in)" in nx7 and "(state[7] & in)" in nx7


def test_top_name_propagates():
    rtl = F.synth(PROB079, top="MyDecode")
    assert rtl is not None and "module MyDecode(" in rtl


def test_emitted_rtl_has_one_assign_per_state_bit():
    rtl = F.synth(PROB143, top="TopModule")
    for j in range(10):
        assert f"assign next_state[{j}] =" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK NEGATIVES — these MUST return None (>=5)
# --------------------------------------------------------------------------- #
def test_neg_lemmings_behavioural_prose_skips():
    """Free behavioural prose — no complete table; genuine AI-floor. MUST SKIP."""
    prompt = """\
 - input  clk
 - input  areset
 - input  bump_left
 - input  bump_right
 - output walk_left
 - output walk_right

Lemmings walk left or right and switch direction when bumped. areset is
positive edge triggered asynchronous resetting the machine to walk left.
Implement a Moore state machine with two states.
"""
    assert F.synth(prompt) is None


def test_neg_ps2_framing_prose_skips():
    """PS/2 byte-stream boundary search — no table; behavioural. MUST SKIP."""
    prompt = """\
 - input  clk
 - input  reset
 - input  in (8 bits)
 - output done

Discard bytes until we see one with in[3]=1, assume it is byte 1, and
signal done in the cycle after the third byte. Reset is active high synchronous.
"""
    assert F.synth(prompt) is None


def test_neg_serial_startstop_prose_skips():
    """Serial start/stop-bit recognition — behavioural counting; no table. MUST SKIP."""
    prompt = """\
 - input  clk
 - input  reset
 - input  in
 - output done

Identify a start bit (0), wait for 8 data bits, verify the stop bit (1).
Include an active-high synchronous reset.
"""
    assert F.synth(prompt) is None


def test_neg_incomplete_table_skips():
    """Decode shape + one-hot map but a state is MISSING its in=1 arc. MUST SKIP."""
    prompt = """\
 - input  in
 - input  state (4 bits)
 - output next_state (4 bits)
 - output out

Use one-hot encoding A=4'b0001, B=4'b0010, C=4'b0100, D=4'b1000.

  State | Next state in=0, Next state in=1 | Output
  A     | A, B                             | 0
  B     | C, B                             | 0
"""
    assert F.synth(prompt) is None      # only 2 states for a 4-bit one-hot -> SKIP


def test_neg_missing_onehot_map_skips():
    """Complete table + decode shape but NO explicit one-hot encoding. MUST SKIP."""
    prompt = """\
 - input  in
 - input  state (4 bits)
 - output next_state (4 bits)
 - output out

Implement the state transition logic. (No encoding stated.)

  State | Next state in=0, Next state in=1 | Output
  A     | A, B                             | 0
  B     | C, B                             | 0
  C     | A, D                             | 0
  D     | C, B                             | 1
"""
    assert F.synth(prompt) is None      # encoding is the pinned fact; never guessed


def test_neg_non_onehot_encoding_skips():
    """Explicit encoding is given but it is NOT one-hot (binary). MUST SKIP."""
    prompt = """\
 - input  in
 - input  state (4 bits)
 - output next_state (4 bits)
 - output out

Use the encoding A=2'b00, B=2'b01, C=2'b10, D=2'b11.

  State | Next state in=0, Next state in=1 | Output
  A     | A, B                             | 0
  B     | C, B                             | 0
  C     | A, D                             | 0
  D     | C, B                             | 1
"""
    assert F.synth(prompt) is None      # binary literals are not one-hot -> SKIP


def test_neg_sequential_with_clk_reset_left_to_moore_solver():
    """Has clk+reset (a SEQUENTIAL Moore FSM) — full_moore_fsm_synth's job. MUST SKIP."""
    prompt = """\
 - input  clk
 - input  reset
 - input  in
 - output out

  A (0) --0--> A
  A (0) --1--> B
  B (1) --0--> A
  B (1) --1--> B

Reset is synchronous active high and resets to state A.
"""
    assert F.synth(prompt) is None      # no state/next_state ports; not our shape


def test_neg_output_arity_mismatch_skips():
    """Arrow table annotates 2 outputs but module declares only 1 output. MUST SKIP."""
    prompt = """\
 - input  in
 - input  state (4 bits)
 - output next_state (4 bits)
 - output out

Use one-hot A=4'b0001, B=4'b0010, C=4'b0100, D=4'b1000.

  A (0, 0) --0--> A
  A (0, 0) --1--> B
  B (0, 1) --0--> C
  B (0, 1) --1--> B
  C (1, 0) --0--> A
  C (1, 0) --1--> D
  D (1, 1) --0--> C
  D (1, 1) --1--> B
"""
    assert F.synth(prompt) is None      # 2-tuple outputs vs 1 declared output -> SKIP


# --------------------------------------------------------------------------- #
# host-score on the REAL dataset if present (authoritative)
# --------------------------------------------------------------------------- #
_DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))


def _host_score(prob):
    import shutil
    import subprocess
    import tempfile
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        return None
    ppath = os.path.join(_DS, f"{prob}_prompt.txt")
    ref = os.path.join(_DS, f"{prob}_ref.sv")
    tb = os.path.join(_DS, f"{prob}_test.sv")
    if not all(os.path.exists(p) for p in (ppath, ref, tb)):
        return None
    with open(ppath, errors="replace") as fh:
        rtl = F.synth(fh.read(), top="TopModule")
    if rtl is None:
        return None
    d = tempfile.mkdtemp()
    dut = os.path.join(d, "dut.sv")
    with open(dut, "w") as fh:
        fh.write(rtl)
    vvp = os.path.join(d, "a.vvp")
    r = subprocess.run(["iverilog", "-g2012", "-o", vvp, dut, ref, tb],
                       capture_output=True, text=True, cwd=d)
    if r.returncode != 0:
        return ("COMPILE_FAIL", r.stderr)
    rv = subprocess.run(["vvp", vvp], capture_output=True, text=True, cwd=d)
    return ("RUN", rv.stdout)


def test_host_score_prob079_zero_mismatch():
    res = _host_score("Prob079_fsm3onehot")
    if res is None:
        return                          # dataset/tools absent — skip silently
    kind, out = res
    assert kind == "RUN", out
    assert "Mismatches: 0" in out or "Total mismatched samples is 0" in out, out


def test_host_score_prob143_zero_mismatch():
    res = _host_score("Prob143_fsm_onehot")
    if res is None:
        return
    kind, out = res
    assert kind == "RUN", out
    assert "Mismatches: 0" in out or "Total mismatched samples is 0" in out, out


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

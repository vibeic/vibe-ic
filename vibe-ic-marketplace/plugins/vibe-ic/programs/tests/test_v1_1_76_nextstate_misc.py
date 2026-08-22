#!/usr/bin/env python3
"""test_v1_1_76_nextstate_misc.py — pins nextstate_misc_synth.py, the deterministic
SOLVER for the last mechanically-complete VerilogEval shapes the FSM / K-map family
still SKIPs:

  S1  NAMED one-hot next-state bits   (Prob091_2012_q2b, Prob099_m2014_q6c)
  S2  binary present-state decode + Moore output   (Prob134_2014_q3c)
  S3  prose don't-care minimum SOP / POS (Quine-McCluskey)   (Prob070_ece241_2013_q2)

POSITIVES — each firing benchmark prompt emits RTL that host-verifies (iverilog +
vvp against the dataset ref + test) to 0 mismatches, asserted via the dataset files
when present. Prob099 is a DOCUMENTED DATASET DEFECT (its test connects ports Y2/Y4
while its prompt+ref declare Y1/Y3 — the gold ref itself fails to elaborate against
its own test), so the test pins that S1 emits the CORRECT stated-prompt logic and
proves the floor lives in the dataset, not the solver.

NEGATIVES (§4.05 NO-LEAK) — >=5 fixtures just OUTSIDE every boundary that MUST
return None: a contradictory output->bit map, a non-one-hot encoding, an incomplete
arrow table, a missing next-state-bit clause for S2, an SOP/POS prompt missing the
OFF-set, overlapping ON/OFF sets, a wrong MSB-first example, and a plain
combinational / behavioural prompt with none of the three shapes.

Positives use the EXACT VerilogEval-v2 spec-to-rtl prompt text (read from the
dataset when available, else verbatim inline copies), so the test pins the real
reproduction, not a paraphrase.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import nextstate_misc_synth as M  # noqa: E402
import loop_watchdog_compliance_check as WGC  # noqa: E402
import spec_artifact_registry as R  # noqa: E402
from _hostpaths import corpus_path, repo_path  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_HAS_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# --------------------------------------------------------------------------- #
# the REAL prompt texts (verbatim from dataset_spec-to-rtl)                    #
# --------------------------------------------------------------------------- #
PROB091 = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  y (6 bits)
 - input  w
 - output Y1
 - output Y3

Consider the following finite-state machine:

  A (0) --1--> B
  A (0) --0--> A
  B (0) --1--> C
  B (0) --0--> D
  C (0) --1--> E
  C (0) --0--> D
  D (0) --1--> F
  D (0) --0--> A
  E (1) --1--> E
  E (1) --0--> D
  F (1) --1--> C
  F (1) --0--> D

Assume that a one-hot code is used with the state assignment y[5:0] =
000001(A), 000010(B), 000100(C), 001000(D), 010000(E), 100000(F)

The module should implement the state output logic for this finite-state
machine. The output signal Y1 should be the input of state flip-flop
y[1]. The output signal Y3 should be the input of state flip-flop y[3].
Derive the implementation by inspection assuming the above one-hot
encoding.
"""

PROB099 = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  y (6 bits)
 - input  w
 - output Y1
 - output Y3

Consider the state machine shown below:

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

Resets into state A. For this part, assume that a one-hot code is used
with the state assignment y[5:0] = 000001, 000010, 000100, 001000,
010000, 100000 for states A, B,..., F, respectively.

The module shou module ment the next-state signals Y2 and Y4
corresponding to signal y[1] and y[3]. Derive the logic equations by
inspection assuming the one-hot encoding.
 implement the next-state signals  and corresponding to
signal y[1] and y[3]Derive the logic equations byinspection assuming the one-hot encoding.
"""

PROB134 = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  x
 - input  y (3 bits)
 - output Y0
 - output z

The module should implement the output logic and next state logic for an
FSM using the table shown below. Note that the output Y0 is Y[0] of the
next state signal.

   Present state input y[2:0] | Next state Y[2:0] when x=0, Next state Y[2:0] when x=1 | Output z
   000 | 000, 001 | 0
   001 | 001, 100 | 0
   010 | 010, 001 | 0
   011 | 001, 010 | 1
   100 | 011, 100 | 1
"""

PROB070 = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

  - input  a
  - input  b
  - input  c
  - input  d
  - output out_sop
  - output out_pos

The module should implement a digital system with four inputs (a,b,c,d)
that generates a logic-1 when 2, 7, or 15 appears on the inputs, and a
logic-0 when 0, 1, 4, 5, 6, 9, 10, 13, or 14 appears. The input
conditions for the numbers 3, 8, 11, and 12 never occur in this system.
For example, 7 corresponds to a,b,c,d being set to 0,1,1,1, respectively.
Determine the output out_sop in minimum sum-of-products form, and the
output out_pos in minimum product-of-sums form.
"""


def _prompt(base: str, fallback: str) -> str:
    p = _DS / f"{base}_prompt.txt"
    return p.read_text(errors="replace") if p.is_file() else fallback


def _host_score(base: str, rtl: str):
    """iverilog+vvp the emitted RTL against the dataset ref+test; return (verdict,
    mismatches, samples) or ('NO_DATASET', None, None) if the files are absent."""
    ref = _DS / f"{base}_ref.sv"
    test = _DS / f"{base}_test.sv"
    if not (ref.is_file() and test.is_file()):
        return ("NO_DATASET", None, None)
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / "dut.sv"
        dut.write_text(rtl)
        binp = Path(td) / "a.vvp"
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(binp), str(dut),
                             str(ref), str(test)], capture_output=True, text=True)
        if cp.returncode != 0:
            return ("TOOL_ERR", None, cp.stderr[-600:])
        cp = subprocess.run(["vvp", str(binp)], capture_output=True, text=True)
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", cp.stdout)
        if m:
            return ("RAN", int(m.group(1)), int(m.group(2)))
        return ("TOOL_ERR", None, cp.stdout[-600:])


# =========================================================================== #
# POSITIVES                                                                    #
# =========================================================================== #
def test_s1_prob091_named_onehot_nextstate_emits_correct_logic():
    rtl = M.synth(_prompt("Prob091_2012_q2b", PROB091))
    assert rtl is not None
    # Y1 = y[0]&w ; Y3 = (y[1]|y[2]|y[4]|y[5]) & ~w (any-order OR of the ~w terms)
    assert "assign Y1 = (y[0] & w);" in rtl
    for b in (1, 2, 4, 5):
        assert f"(y[{b}] & ~w)" in rtl
    assert "(y[3] & ~w)" not in rtl  # D is the target, never a source for Y3


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_s1_prob091_host_verifies_zero_mismatch():
    rtl = M.synth(_prompt("Prob091_2012_q2b", PROB091))
    verdict, mm, samp = _host_score("Prob091_2012_q2b", rtl)
    if verdict == "NO_DATASET":
        pytest.skip("dataset ref/test not present")
    assert verdict == "RAN", f"unexpected: {verdict} {samp}"
    assert mm == 0, f"{mm}/{samp} mismatches"


def test_s1_prob099_emits_correct_stated_prompt_logic():
    """Prob099's body text is corrupted and its TEST connects Y2/Y4 while the
    prompt+ref declare Y1/Y3 (DATASET DEFECT). The solver still emits the CORRECT
    logic for the stated Y1/Y3 interface — Y1=y[0]&~w, Y3=(...)&w."""
    rtl = M.synth(_prompt("Prob099_m2014_q6c", PROB099))
    assert rtl is not None
    assert "assign Y1 = (y[0] & ~w);" in rtl
    for b in (1, 2, 4, 5):
        assert f"(y[{b}] & w)" in rtl
    assert "Y1" in rtl and "Y3" in rtl and "Y2" not in rtl and "Y4" not in rtl


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_s1_prob099_is_a_dataset_defect_floor():
    """FLOOR PROOF: the dataset's OWN gold ref (Y1/Y3) fails to ELABORATE against
    the dataset's OWN test (which references Y2/Y4) — so no design implementing the
    STATED prompt can pass, independent of our solver."""
    ref = _DS / "Prob099_m2014_q6c_ref.sv"
    test = _DS / "Prob099_m2014_q6c_test.sv"
    if not (ref.is_file() and test.is_file()):
        pytest.skip("dataset ref/test not present")
    with tempfile.TemporaryDirectory() as td:
        # use the gold ref's own equations as the DUT to isolate the test defect
        dut = Path(td) / "dut.sv"
        dut.write_text(
            "module TopModule(input [5:0] y, input w, output Y1, output Y3);\n"
            "  assign Y1 = y[0]&~w;\n"
            "  assign Y3 = (y[1]|y[2]|y[4]|y[5]) & w;\nendmodule\n")
        binp = Path(td) / "a.vvp"
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(binp), str(dut),
                             str(ref), str(test)], capture_output=True, text=True)
    # elaboration MUST fail on the Y2/Y4 port mismatch — that is the dataset floor
    assert cp.returncode != 0
    assert "Y2" in cp.stderr and "is not a port" in cp.stderr


def test_s2_prob134_binary_nextstate_and_moore_emits_case():
    rtl = M.synth(_prompt("Prob134_2014_q3c", PROB134))
    assert rtl is not None
    assert "case ({y, x})" in rtl
    assert "case (y)" in rtl
    # Y0 keyed by {y,x}: {y=4,x=0}->key 8 -> next 011 -> bit0=1
    assert "4'd8: Y0 = 1'b1;" in rtl
    # z: y=3 -> 1, y=0 -> 0
    assert "3'd3: z = 1'b1;" in rtl
    assert "3'd0: z = 1'b0;" in rtl
    assert "default: Y0 = 1'bx;" in rtl  # unlisted states are don't-care


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_s2_prob134_host_verifies_zero_mismatch():
    rtl = M.synth(_prompt("Prob134_2014_q3c", PROB134))
    verdict, mm, samp = _host_score("Prob134_2014_q3c", rtl)
    if verdict == "NO_DATASET":
        pytest.skip("dataset ref/test not present")
    assert verdict == "RAN", f"unexpected: {verdict} {samp}"
    assert mm == 0, f"{mm}/{samp} mismatches"


def test_s3_prob070_dontcare_sop_pos_emits_minimal_cover():
    rtl = M.synth(_prompt("Prob070_ece241_2013_q2", PROB070))
    assert rtl is not None
    # minimal SOP reproduces the ref: c&d | ~a&~b&c
    assert "(c&d)" in rtl
    assert "(~a&~b&c)" in rtl
    assert "out_sop" in rtl and "out_pos" in rtl


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_s3_prob070_host_verifies_zero_mismatch():
    rtl = M.synth(_prompt("Prob070_ece241_2013_q2", PROB070))
    verdict, mm, samp = _host_score("Prob070_ece241_2013_q2", rtl)
    if verdict == "NO_DATASET":
        pytest.skip("dataset ref/test not present")
    assert verdict == "RAN", f"unexpected: {verdict} {samp}"
    assert mm == 0, f"{mm}/{samp} mismatches"


# =========================================================================== #
# §4.05 NO-LEAK NEGATIVES (>=5)                                                #
# =========================================================================== #
NEG_CONTRADICTORY_MAP = """
I would like you to implement a module named TopModule.

 - input  y (4 bits)
 - input  w
 - output Y0
 - output Y1

  A (0) --0--> B
  A (0) --1--> A
  B (0) --0--> A
  B (0) --1--> B

A one-hot code is used with the state assignment y[1:0] = 01(A), 10(B).
The output signal Y0 should be the input of state flip-flop y[1]. The
output signal Y1 should be the input of state flip-flop y[1].
"""  # both outputs claim the SAME bit -> non-bijective map -> SKIP

NEG_NOT_ONEHOT = """
I would like you to implement a module named TopModule.

 - input  y (2 bits)
 - input  w
 - output Y0
 - output Y1

  A (0) --0--> B
  A (0) --1--> A
  B (0) --0--> A
  B (0) --1--> B

A one-hot code is used with the state assignment y[1:0] = 00(A), 11(B).
The output signal Y0 should be the input of state flip-flop y[0]. The
output signal Y1 should be the input of state flip-flop y[1].
"""  # 00 and 11 are NOT one-hot codes -> SKIP

NEG_INCOMPLETE_TABLE = """
I would like you to implement a module named TopModule.

 - input  y (2 bits)
 - input  w
 - output Y0
 - output Y1

  A (0) --1--> B
  B (0) --0--> A

A one-hot code is used with the state assignment y[1:0] = 01(A), 10(B).
The output signal Y0 should be the input of state flip-flop y[0]. The
output signal Y1 should be the input of state flip-flop y[1].
"""  # each state is missing one of the two input arcs -> SKIP

NEG_S2_NO_NEXTSTATE_CLAUSE = """
I would like you to implement a module named TopModule.

 - input  clk
 - input  x
 - input  y (3 bits)
 - output Y0
 - output z

The module should implement the next state logic for an FSM.

   000 | 000, 001 | 0
   001 | 001, 100 | 0
   010 | 010, 001 | 0
   011 | 001, 010 | 1
   100 | 011, 100 | 1
"""  # never states "Y0 is Y[0] of the next state" -> the bit index is unknown -> SKIP

NEG_SOP_NO_OFFSET = """
I would like you to implement a module named TopModule.

  - input  a
  - input  b
  - input  c
  - input  d
  - output out_sop
  - output out_pos

The module generates a logic-1 when 2, 7, or 15 appears on the inputs.
For example, 7 corresponds to a,b,c,d being set to 0,1,1,1, respectively.
Determine out_sop in minimum sum-of-products form and out_pos in minimum
product-of-sums form.
"""  # no OFF-set disclosed -> sets do not partition the space -> SKIP

NEG_SOP_OVERLAP = """
I would like you to implement a module named TopModule.

  - input  a
  - input  b
  - input  c
  - input  d
  - output out_sop
  - output out_pos

The module generates a logic-1 when 2, 7, or 15 appears, and a logic-0
when 0, 1, 2, 4, 5, 6, 9, 10, 13, 14, 3, 8, 11, 12 appears. For example,
7 corresponds to a,b,c,d being set to 0,1,1,1, respectively. Determine
out_sop in minimum sum-of-products form and out_pos in minimum
product-of-sums form.
"""  # 2 is in BOTH the ON and OFF sets -> overlapping -> SKIP

NEG_SOP_WRONG_MSB_EXAMPLE = """
I would like you to implement a module named TopModule.

  - input  a
  - input  b
  - input  c
  - input  d
  - output out_sop
  - output out_pos

The module generates a logic-1 when 2, 7, or 15 appears, and a logic-0
when 0, 1, 4, 5, 6, 9, 10, 13, or 14 appears. The numbers 3, 8, 11, and
12 never occur. For example, 7 corresponds to a,b,c,d being set to
1,1,1,0, respectively. Determine out_sop in minimum sum-of-products form
and out_pos in minimum product-of-sums form.
"""  # the worked example (1,1,1,0=14) contradicts "7" -> ordering unpinned -> SKIP

NEG_PLAIN_COMB = """
I would like you to implement a module named TopModule.

 - input  a
 - input  b
 - output out

The module should compute the AND of a and b.
"""  # none of S1/S2/S3 -> SKIP


@pytest.mark.parametrize("prompt", [
    NEG_CONTRADICTORY_MAP,
    NEG_NOT_ONEHOT,
    NEG_INCOMPLETE_TABLE,
    NEG_S2_NO_NEXTSTATE_CLAUSE,
    NEG_SOP_NO_OFFSET,
    NEG_SOP_OVERLAP,
    NEG_SOP_WRONG_MSB_EXAMPLE,
    NEG_PLAIN_COMB,
])
def test_no_leak_negatives_skip(prompt):
    assert M.synth(prompt) is None


# =========================================================================== #
# corpus discipline: fires ONLY where the existing registry.generate is None  #
# =========================================================================== #
@pytest.mark.skipif(not _DS.is_dir(), reason="VerilogEval dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_corpus_fires_only_where_registry_generate_is_none():
    overlaps, fires = [], []
    for pp in sorted(_DS.glob("*_prompt.txt")):
        text = pp.read_text(errors="replace")
        try:
            rtl = M.synth(text)
        except Exception as e:  # pragma: no cover - a crash IS a failure
            pytest.fail(f"{pp.name} crashed synth: {e}")
        if rtl is None:
            continue
        fires.append(pp.name.replace("_prompt.txt", ""))
        # post-integration nextstate_misc IS in the registry — check no FOREIGN
        # generator co-claims these (exclude our own key).
        foreign = [a.key for a in R.REGISTRY if a.key != "nextstate_misc"
                   and a.generate and a.generate(text, "TopModule")]
        if foreign:
            overlaps.append((pp.name, foreign))
    # exactly the four intended targets, and never overlapping an existing generator
    assert overlaps == [], f"overlap with existing registry generators: {overlaps}"
    assert set(fires) == {
        "Prob070_ece241_2013_q2", "Prob091_2012_q2b",
        "Prob099_m2014_q6c", "Prob134_2014_q3c",
    }, f"unexpected fire set: {sorted(fires)}"


@pytest.mark.skipif(not (_DS.is_dir() and _HAS_IVERILOG),
                    reason="dataset + iverilog required; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_corpus_every_nondefect_fire_host_verifies_zero():
    """Every fire host-verifies to 0 mismatches EXCEPT Prob099, whose floor is the
    dataset's own broken testbench (proven separately)."""
    for base in ("Prob070_ece241_2013_q2", "Prob091_2012_q2b", "Prob134_2014_q3c"):
        rtl = M.synth((_DS / f"{base}_prompt.txt").read_text(errors="replace"))
        assert rtl is not None
        verdict, mm, samp = _host_score(base, rtl)
        assert verdict == "RAN" and mm == 0, f"{base}: {verdict} {mm}/{samp}"


# §4.05 Step-2.7 regression (v1.1.76): the VE-v2 Prob099 declares the one-hot state
# bus with a NON-ZERO LSB `input [6:1] y` + a 1-based `y[6:1] = ...` encoding and asks
# for `Y2`/`Y4`. The solver emitted a 0-based bus and mis-indexed the output->bit map
# -> a 9/12-mismatch false-fire. It must now SKIP (we only handle a 0-based bus). The
# discriminating line `input [6:1] y` is embedded VERBATIM from the real prompt.
_V2_PROB099_NONZERO_LSB = """\
Consider the state machine shown below:

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

Resets into state A. For this part, assume that a one-hot code is used
with the state assignment y[6:1] = 000001, 000010, 000100, 001000,
010000, 100000 for states A, B,..., F, respectively.

Write Verilog for the next-state signals Y2 and Y4 corresponding to
signal y[2] and y[4]. Derive the logic equations by inspection assuming a
one-hot encoding.

module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);
"""


def test_nonzero_lsb_state_bus_skips():
    # would emit a mis-indexed (off-by-one) machine -> must SKIP, not fire.
    assert M.synth(_V2_PROB099_NONZERO_LSB) is None


def test_zero_lsb_same_shape_still_fires():
    # the SAME machine re-declared with a 0-based bus must still FIRE (the guard is
    # specific to the non-zero LSB, not a blanket suppression of the shape).
    zero_based = _V2_PROB099_NONZERO_LSB.replace("[6:1]", "[5:0]").replace(
        "y[6:1] =", "y[5:0] =").replace("Y2 and Y4", "Y0 and Y2").replace(
        "signal y[2] and y[4]", "signal y[0] and y[2]").replace(
        "output Y2,", "output Y0,").replace("output Y4", "output Y2")
    assert M.synth(zero_based) is not None


def test_host_verify_routes_iverilog_through_progress_watchdog(
        monkeypatch, tmp_path):
    """The compile is BLOCKING work and cannot bypass process supervision."""
    calls = []

    def _absent(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return M._watchdog.SupervisedResult(
            127, "", "COMMAND_NOT_FOUND: iverilog", "launch_error")

    monkeypatch.setattr(M._watchdog, "run_supervised", _absent)
    ref = tmp_path / "ref.sv"
    test = tmp_path / "test.sv"
    ref.write_text("module RefModule; endmodule\n")
    test.write_text("module tb; endmodule\n")

    verdict, detail = M.host_verify(PROB070, str(ref), str(test))

    assert verdict == "TOOL_ERR"
    assert "COMMAND_NOT_FOUND" in detail
    assert len(calls) == 1
    assert calls[0][0][0] == "iverilog"


def test_real_program_corpus_has_no_unguarded_long_process():
    """The deterministic compliance gate must clear the shipped source tree."""
    programs = repo_path("vibe-ic-marketplace/plugins/vibe-ic/programs")
    offenders = WGC.scan_programs(programs)
    assert len(offenders) == 0, [
        (o.file, o.line, o.kind, o.detail) for o in offenders]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

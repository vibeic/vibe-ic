"""comb_advanced_synth — ADVANCED purely-combinational spec families -> RTL synth.

A slice of the still-unsolved VerilogEval combinational prompts state their function
in a STRUCTURED-BUT-PROSE form that no existing artifact recognizer owns: an explicit
input-value -> output-value case map, a minimum/maximum-of-N comparator, a stated
adder (half / full / N-bit / 2's-complement+overflow), per-bit neighbour vector
relations, a one-hot FSM next-state-by-inspection derivation, a dual-implementation
gate/mux (assign + always), a wire connection list, a per-output OR-of-AND-gates
network, a pairwise-equality vector, or an explicit transparent D latch. Each shape
is mechanically extractable and host-verifiable; comb_advanced_synth absorbs them as
a PROGRAM so a blind author cannot mis-wire them per single-shot variance.

§4.05 NO-LEAK: each shape FIRES only on an unambiguous, fully-pinned spec and SKIPs
(returns None) the moment the prose turns descriptive / the structure is incomplete /
a sequential or waveform or K-map cue appears (those are OTHER paths' territory). The
NEGATIVE fixtures below sit JUST OUTSIDE each shape's boundary and MUST still skip —
a wrong-RTL emit is far worse than an honest skip. Every FIRING prompt is host-scored
(iverilog -g2012 dut.sv ref.sv test.sv && vvp -> 0 mismatches), and the whole 156-prompt
corpus is swept to prove the dispatcher never collides with the existing registry and
never fires where it would be wrong.
"""
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import comb_advanced_synth as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


# Every benchmark prompt this module OWNS end-to-end after the v1.1.76 integration
# DEDUP. The adder shapes (Prob016/024/027/033) are owned by the dedicated
# arithmetic_synth, and the one-hot next-state-by-inspection (Prob091/099) by
# nextstate_misc_synth — comb_advanced now DEFERS those (asserted in
# test_dedup_defers_to_dedicated_solvers), so they are no longer in _FIRING.
_FIRING = [
    "Prob026_alwaysblock1",    # AND via assign + always (dual)
    "Prob028_m2014_q4a",       # transparent D latch
    "Prob039_always_if",       # 2-to-1 mux via assign + procedural if (dual)
    "Prob043_vector5",         # pairwise-equality vector
    "Prob055_conditional",     # minimum-of-4 comparator
    "Prob059_wire4",           # wire connection list
    "Prob081_7458",            # per-output OR of named-input AND gates
    "Prob092_gatesv100",       # neighbour vector relations (100-bit)
    "Prob094_gatesv",          # neighbour vector relations (4-bit)
    "Prob106_always_nolatches",# scancode -> one-hot case map
    "Prob114_bugs_case",       # value-map case + valid flag
]


# ===========================================================================
# POSITIVE — self-contained prompts (dataset-independent structural assertions)
# ===========================================================================
def test_half_adder_fires():
    p = """Implement a module named TopModule.
 - input  a
 - input  b
 - output sum
 - output cout
The module should implement a half adder. A half adder adds two bits (with no
carry-in) and produces a sum and carry-out."""
    # v1.1.76 dedup: half/full/N-bit/2's-comp adders are owned by arithmetic_synth.
    assert C.synth(p, "TopModule") is None


def test_full_adder_fires():
    p = """Implement a module named TopModule.
 - input  a
 - input  b
 - input  cin
 - output cout
 - output sum
The module should impement a full adder. A full adder adds three bits (including
carry-in) and produces a sum and carry-out."""
    # v1.1.76 dedup: adders owned by arithmetic_synth.
    assert C.synth(p, "TopModule") is None


def test_nbit_adder_overflow_msb():
    p = """Implement a module named TopModule.
 - input  x   (4 bits)
 - input  y   (4 bits)
 - output sum (5 bits)
Implement a 4-bit adder with full adders. The output sum should include the
overflow bit."""
    # v1.1.76 dedup: adders owned by arithmetic_synth.
    assert C.synth(p, "TopModule") is None


def test_twos_complement_overflow():
    p = """Implement a module named TopModule.
 - input  a (8 bits)
 - input  b (8 bits)
 - output s (8 bits)
 - output overflow
Assume that you have two 8-bit 2's complement numbers, a[7:0] and b[7:0]. The
module should add these numbers to produce s[7:0]. Also compute whether a (signed)
overflow has occurred."""
    # v1.1.76 dedup: 2's-complement adder + overflow owned by arithmetic_synth.
    assert C.synth(p, "TopModule") is None


def test_min_of_four():
    p = """Implement a module named TopModule.
 - input  a   (8 bits)
 - input  b   (8 bits)
 - input  c   (8 bits)
 - input  d   (8 bits)
 - output min (8 bits)
The module should find the minimum of the four input values. Unsigned numbers can
be compared with standard comparison operators (a < b)."""
    rtl = C.synth(p, "TopModule")
    assert rtl is not None
    assert "min = a" in rtl and "if (min > b) min = b" in rtl


def test_d_latch_fires():
    p = """Implement a module named TopModule.
 - input  d
 - input  ena
 - output q
The module should impement a D latch using an always block."""
    rtl = C.synth(p, "TopModule")
    assert rtl is not None
    assert "always @(*) if (ena) q = d" in rtl
    assert "output reg q" in rtl


def test_dual_impl_mux():
    p = """Implement a module named TopModule.
 - input  a
 - input  b
 - input  sel_b1
 - input  sel_b2
 - output out_assign
 - output out_always
The module should implement a 2-to-1 mux that chooses between a and b. Choose b if
both sel_b1 and sel_b2 are true. Otherwise, choose a. Do the same twice, once using
assign statements and once using a procedural if statement."""
    rtl = C.synth(p, "TopModule")
    assert rtl is not None
    assert "assign out_assign = (sel_b1 & sel_b2) ? b : a" in rtl
    assert "always @(*) out_always = (sel_b1 & sel_b2) ? b : a" in rtl


def test_or_of_and_gates():
    p = """Implement a module named TopModule.
 - input  p1a
 - input  p1b
 - input  p1c
 - input  p1d
 - input  p1e
 - input  p1f
 - input  p2a
 - input  p2b
 - input  p2c
 - input  p2d
 - output p1y
 - output p2y
In this circuit, p1y should be the OR of two 3-input AND gates: one that ANDs p1a,
p1b, and p1c, and the second that ANDs p1d, p1e, and p1f. The output p2y is the OR
of two 2-input AND gates: one that ANDs p2a and p2b, and the second that ANDs p2c
and p2d."""
    rtl = C.synth(p, "TopModule")
    assert rtl is not None
    assert "assign p1y = &{p1a, p1b, p1c} | &{p1d, p1e, p1f}" in rtl
    assert "assign p2y = &{p2a, p2b} | &{p2c, p2d}" in rtl


def test_onehot_fsm_inspection():
    p = """Implement a module named TopModule.
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
000001(A), 000010(B), 000100(C), 001000(D), 010000(E), 100000(F). The output
signal Y1 should be the input of state flip-flop y[1]. Derive the implementation
by inspection assuming the above one-hot encoding."""
    # v1.1.76 dedup: one-hot FSM next-state-by-inspection owned by nextstate_misc_synth.
    assert C.synth(p, "TopModule") is None


def test_wire_connections():
    p = """Implement a module named TopModule.
 - input  a
 - input  b
 - input  c
 - output w
 - output x
 - output y
 - output z
The module should behave like wires that makes these connections:
  a -> w
  b -> x
  b -> y
  c -> z"""
    rtl = C.synth(p, "TopModule")
    assert rtl is not None
    assert "{w, x, y, z} = {a, b, b, c}" in rtl


# ===========================================================================
# §4.05 NEGATIVE NO-LEAK — each sits JUST OUTSIDE a shape and MUST skip
# ===========================================================================
def test_neg_descriptive_waveform_skips():
    # "read the simulation waveforms" is the descriptive waveform path, NOT ours.
    p = """Implement a module named TopModule.
 - input  a (3 bits)
 - output q (16 bits)
The module should implement a combinational circuit. Read the simulation waveforms
to determine what the circuit does, then implement it.
  time  a  q
  15ns  0  1232
  20ns  1  aee0"""
    assert C.synth(p, "TopModule") is None


def test_neg_clocked_sequential_skips():
    # a clocked flip-flop is the sequential path; the dual-impl shape must NOT fire
    # on the FF output.
    p = """Implement a module named TopModule.
 - input  clk
 - input  a
 - input  b
 - output out_assign
 - output out_always_comb
 - output out_always_ff
The module should implement an XOR gate three ways, using an assign statement, a
combinational always block, and a clocked always block. Assume all sequential logic
is triggered on the positive edge of the clock."""
    assert C.synth(p, "TopModule") is None


def test_neg_kmap_mux_decomposition_skips():
    # the mux-input K-map decomposition is a documented FLOOR (non-unique reference);
    # a K-map cue MUST keep every shape silent.
    p = """Implement a module named TopModule.
 - input  c
 - input  d
 - output mux_in (4 bits)
For the following Karnaugh map, give the circuit implementation using one 4-to-1
multiplexer.
      ab
  cd  00  01  11  10
  00 | 0 | 0 | 0 | 1 |
  01 | 1 | 0 | 0 | 0 |
  11 | 1 | 0 | 1 | 1 |
  10 | 1 | 0 | 0 | 1 |"""
    assert C.synth(p, "TopModule") is None


def test_neg_chip_name_without_structure_skips():
    # "same functionality as the 7420 chip" with NO explicit gate description: the
    # function is only known from chip knowledge -> SKIP (no keyword-overfit).
    p = """Implement a module named TopModule.
 - input  p1a
 - input  p1b
 - input  p1c
 - input  p1d
 - input  p2a
 - input  p2b
 - input  p2c
 - input  p2d
 - output p1y
 - output p2y
The 7420 is a chip with two 4-input NAND gates. The module should implement the
same functionality as the 7420 chip."""
    assert C.synth(p, "TopModule") is None


def test_neg_min_width_mismatch_skips():
    # "minimum of N" but the output width does not match the operands -> ambiguous.
    p = """Implement a module named TopModule.
 - input  a   (8 bits)
 - input  b   (8 bits)
 - output min (4 bits)
The module should find the minimum of the two input values."""
    assert C.synth(p, "TopModule") is None


def test_neg_d_latch_extra_input_skips():
    # a "D latch" with an EXTRA input that isn't a clean (data, enable) pair -> SKIP
    # (could be a gated/async-reset variant the shape can't pin).
    p = """Implement a module named TopModule.
 - input  d
 - input  ena
 - input  r
 - output q
The module should impement a D latch using an always block with reset r."""
    assert C.synth(p, "TopModule") is None


def test_neg_or_of_ands_foreign_operand_skips():
    # an AND clause that references a token which is NOT a declared input -> SKIP.
    p = """Implement a module named TopModule.
 - input  p1a
 - input  p1b
 - output p1y
The output p1y should be the OR of two AND gates: one that ANDs p1a and p1b, and
the second that ANDs p1a and zz_undeclared."""
    assert C.synth(p, "TopModule") is None


def test_neg_pairwise_wrong_ordering_skips():
    # the explicit example must MATCH the canonical outer/inner ordering; a
    # transcribed-wrong example must keep the shape silent rather than emit a guess.
    p = """Implement a module named TopModule.
 - input  a
 - input  b
 - input  c
 - input  d
 - input  e
 - output out (25 bits)
Compute all 25 pairwise one-bit comparisons. The output should be 1 if the two bits
being compared are equal. Example: out[24] = ~b ^ a; out[23] = ~a ^ b; out[0] = ~e
^ e."""
    assert C.synth(p, "TopModule") is None


def test_neg_empty_and_no_ports():
    assert C.synth("", "TopModule") is None
    assert C.synth("just some prose with no interface at all", "TopModule") is None


# ===========================================================================
# CORPUS NO-LEAK SWEEP — fires only where intended, never collides with the
# existing registry, never fires where it would be wrong.
# ===========================================================================
def _dataset_present() -> bool:
    return _DS.exists() and any(_DS.glob("*_prompt.txt"))


def test_corpus_no_collision_with_registry():
    if not _dataset_present():
        pytest.skip("dataset not present")
    import spec_artifact_registry as R
    fires, collisions = [], []
    for f in sorted(_DS.glob("*_prompt.txt")):
        txt = f.read_text(errors="replace")
        if C.synth(txt, "TopModule"):
            name = f.name.replace("_prompt.txt", "")
            fires.append(name)
            # post-integration comb_advanced IS in the registry — a collision is a
            # FOREIGN generator (not our own key) also firing on the same prompt.
            foreign = [a.key for a in R.REGISTRY if a.key != "comb_advanced"
                       and a.generate and a.generate(txt, "TopModule")]
            if foreign:
                collisions.append((name, foreign))
    # every intended target fires; nothing collides with what the registry solves.
    assert collisions == [], f"collisions with registry: {collisions}"
    expected = set(_FIRING)   # Prob099 one-hot now deferred to nextstate_misc (dedup)
    assert set(fires) == expected, (
        f"fire set drifted.\n extra: {sorted(set(fires) - expected)}\n "
        f"missing: {sorted(expected - set(fires))}")


# ===========================================================================
# HOST-SCORE — end-to-end iverilog 0-mismatch on every firing prompt.
# ===========================================================================
def _iverilog_available() -> bool:
    return which("iverilog") is not None and which("vvp") is not None


@pytest.mark.parametrize("prob", _FIRING)
def test_host_score_zero_mismatch(prob, tmp_path):
    if not _iverilog_available():
        pytest.skip("iverilog/vvp not available")
    prompt = _DS / f"{prob}_prompt.txt"
    ref = _DS / f"{prob}_ref.sv"
    tb = _DS / f"{prob}_test.sv"
    if not (prompt.exists() and ref.exists() and tb.exists()):
        pytest.skip(f"dataset files for {prob} not present")
    rtl = C.synth(prompt.read_text(errors="replace"), "TopModule")
    assert rtl is not None, f"{prob} must FIRE"
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    vvp = tmp_path / "a.vvp"
    comp = subprocess.run(
        ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
        capture_output=True, text=True)
    assert comp.returncode == 0, f"{prob} compile failed:\n{comp.stderr}"
    run = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, timeout=60)
    out = run.stdout + run.stderr
    m = re.search(r"Mismatches:\s*(\d+)\b", out)
    assert m is not None, f"no Mismatches line in vvp output:\n{out}"
    assert int(m.group(1)) == 0, f"{prob} had {m.group(1)} mismatches:\n{out}"


def test_dedup_prob099_deferred_to_nextstate_misc():
    # v1.1.76 dedup: the one-hot next-state-by-inspection shape (incl. Prob099) is
    # owned by nextstate_misc_synth, which classifies Prob099 as a dataset-defect
    # FLOOR (its official TB wires ports Y2/Y4 that the ref never declares). So
    # comb_advanced must DEFER (SKIP) on it — no two solvers claim it.
    prompt = _DS / "Prob099_m2014_q6c_prompt.txt"
    if not prompt.exists():
        pytest.skip("Prob099 dataset files not present")
    assert C.synth(prompt.read_text(errors="replace"), "TopModule") is None

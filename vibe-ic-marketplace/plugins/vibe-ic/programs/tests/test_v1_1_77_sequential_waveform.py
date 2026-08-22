#!/usr/bin/env python3
"""test_v1_1_77_sequential_waveform.py — pins sequential_waveform_synth.py, the
deterministic SOLVER that DECOMPOSES multi-bit / sequential WAVEFORM-table prompts
the binary solvers (waveform_truth_table_synth / waveform_ext_synth) SKIP.

POSITIVES: each firing VerilogEval problem emits the expected RTL structure AND is
HOST-SCORED (iverilog -g2012 + vvp) to "Total mismatched samples is 0" against the
real dataset TB — the authoritative §4.05 proof that the synthesized logic is
correct, not just structurally plausible. (Host-score auto-SKIPs if iverilog or the
dataset is absent on this host; the line-pin assertions still run everywhere.)

NEGATIVES (§4.05 NO-LEAK ABSOLUTE): >=5 fixtures JUST outside the proven envelopes
that MUST return None. A wrong sample is strictly worse than a SKIP.

NO-OVERLAP: the solver fires ONLY where spec_artifact_registry.generate currently
returns None — pinned here so it can never start stealing another solver's envelope.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
if _PROGRAMS not in sys.path:
    sys.path.insert(0, _PROGRAMS)

import sequential_waveform_synth as M  # noqa: E402
import spec_artifact_registry as R     # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))

FIRING = [
    "Prob117_circuit9",   # (a) counter-by-delta (3-bit, load+wrap)
    "Prob126_circuit6",   # (b) multi-bit combinational LUT (3->16 bit hex)
    "Prob130_circuit5",   # (c) symbolic mux (selector c, port-passthrough+literal)
    "Prob145_circuit8",   # (d) negedge-FF + transparent-latch split
    "Prob131_mt2015_q4",  # (e) submodule composition (prose-A + waveform-B + gates)
]


def _prompt(prob):
    p = os.path.join(DS, f"{prob}_prompt.txt")
    if not os.path.isfile(p):
        pytest.skip(f"dataset prompt {prob} not present on this host")
    with open(p, errors="replace") as f:
        return f.read()


def _host_score(prob, rtl):
    """iverilog+vvp the emitted RTL as TopModule against the dataset ref+TB; return
    the mismatch count as int, or None if the toolchain/dataset is unavailable."""
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return None
    ref = os.path.join(DS, f"{prob}_ref.sv")
    tb = os.path.join(DS, f"{prob}_test.sv")
    if not (os.path.isfile(ref) and os.path.isfile(tb)):
        return None
    work = tempfile.mkdtemp()
    try:
        with open(os.path.join(work, "dut.sv"), "w") as f:
            f.write(rtl)
        b = subprocess.run(["iverilog", "-g2012", "-o", "a.vvp", "dut.sv", ref, tb],
                           cwd=work, capture_output=True, text=True)
        assert b.returncode == 0, f"{prob} build failed:\n{b.stderr}"
        r = subprocess.run(["vvp", "a.vvp"], cwd=work, capture_output=True, text=True)
        m = re.search(r"Total mismatched samples is (\d+)", r.stdout)
        assert m, f"{prob} produced no mismatch line:\n{r.stdout}"
        return int(m.group(1))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- #
# POSITIVES — fire + key emitted lines + authoritative host-score (0 mismatches)
# --------------------------------------------------------------------------- #
def test_a_counter_by_delta_prob117():
    rtl = M.synth(_prompt("Prob117_circuit9"))
    assert rtl is not None
    assert "output reg [2:0] q" in rtl
    assert "always @(posedge clk)" in rtl
    assert "if (a)" in rtl
    assert "q <= 4;" in rtl                       # load value inferred from a=1 edges
    assert "else if (q == 6)" in rtl              # modulus pinned by the wrap row
    assert "q <= 0;" in rtl
    assert "q <= q + 1'b1;" in rtl                # +1 increment inferred by diffing
    assert "negedge" not in rtl
    mm = _host_score("Prob117_circuit9", rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"Prob117 host mismatches={mm}"


def test_b_multibit_lut_prob126():
    rtl = M.synth(_prompt("Prob126_circuit6"))
    assert rtl is not None
    assert "input  [2:0] a" in rtl
    assert "output reg [15:0] q" in rtl
    assert "case (a)" in rtl
    assert "3'h0: q = 16'h1232;" in rtl           # first LUT entry (hex preserved)
    assert "3'h6: q = 16'hc526;" in rtl
    assert "3'h7: q = 16'h2f19;" in rtl           # full 8-entry coverage
    assert rtl.count("q = 16'h") == 8
    mm = _host_score("Prob126_circuit6", rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"Prob126 host mismatches={mm}"


def test_c_symbolic_mux_prob130():
    rtl = M.synth(_prompt("Prob130_circuit5"))
    assert rtl is not None
    assert "case (c)" in rtl                       # selector is the varying column
    assert "4'h0: q = b;" in rtl                   # port-passthrough
    assert "4'h1: q = e;" in rtl
    assert "4'h2: q = a;" in rtl
    assert "4'h3: q = d;" in rtl
    assert "q = 4'hf;" in rtl                       # non-port letter -> literal const
    mm = _host_score("Prob130_circuit5", rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"Prob130 host mismatches={mm}"


def test_d_negedge_ff_latch_prob145():
    rtl = M.synth(_prompt("Prob145_circuit8"))
    assert rtl is not None
    assert "output reg p" in rtl
    assert "output reg q" in rtl
    assert "always @(negedge clock)" in rtl        # negedge FF
    assert "q <= a;" in rtl
    assert "always @(*)" in rtl                     # transparent latch
    assert "if (clock)" in rtl
    assert "p = a;" in rtl
    mm = _host_score("Prob145_circuit8", rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"Prob145 host mismatches={mm}"


def test_e_submodule_composition_prob131():
    rtl = M.synth(_prompt("Prob131_mt2015_q4"))
    assert rtl is not None
    # two A + two B submodules wired exactly as the prose states
    assert "ModuleA A1" in rtl and "ModuleA A2" in rtl
    assert "ModuleB B1" in rtl and "ModuleB B2" in rtl
    assert "a1 | b1" in rtl                          # first pair -> OR
    assert "a2 & b2" in rtl                          # second pair -> AND
    assert "z = or_out ^ and_out;" in rtl           # OR ^ AND -> XOR
    assert "assign z = (x^y) & x;" in rtl            # Module A from prose boolean
    # Module B truth table read from its waveform == XNOR: 1 only when x==y
    assert "(~x & ~y) | (x & y)" in rtl
    mm = _host_score("Prob131_mt2015_q4", rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"Prob131 host mismatches={mm}"


# --------------------------------------------------------------------------- #
# All firing problems host-score to 0 (authoritative aggregate §4.05 proof)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prob", FIRING)
def test_every_fire_is_zero_mismatch(prob):
    rtl = M.synth(_prompt(prob))
    assert rtl is not None, f"{prob} should FIRE"
    mm = _host_score(prob, rtl)
    if mm is None:
        pytest.skip("iverilog/dataset unavailable for host-score")
    assert mm == 0, f"{prob} LEAKED a wrong sample (host mismatches={mm})"


# --------------------------------------------------------------------------- #
# NO-OVERLAP — fires only where the existing registry.generate returns None
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prob", FIRING)
def test_no_overlap_with_existing_generate(prob):
    # post-integration this solver IS in the registry, so registry.generate returns
    # OUR result — assert no OTHER (foreign) generator also claims the prompt.
    text = _prompt(prob)
    foreign = [a.key for a in R.REGISTRY if a.key != "sequential_waveform_multibit"
               and a.generate and a.generate(text, "TopModule")]
    assert foreign == [], (
        f"{prob} is ALSO solved by foreign generator(s) {foreign} — overlap.")


# --------------------------------------------------------------------------- #
# NEGATIVES (§4.05 NO-LEAK) — JUST outside each proven envelope -> MUST SKIP
# --------------------------------------------------------------------------- #
NEG_FIXTURES = {
    # 1. counter-by-delta with a NON-CONSTANT, NON-+1 free-run step (q goes 4->6
    #    skipping 5) -> the recurrence is NOT a clean increment -> must SKIP.
    "counter_ambiguous_delta": """
 - input  clk
 - input  a
 - output q (3 bits)
The module implements a sequential circuit.
  time  clk a   q
  0ns   0   1   x
  5ns   1   1   4
  10ns  0   1   4
  15ns  1   0   4
  20ns  0   0   4
  25ns  1   0   6
  30ns  0   0   6
  35ns  1   0   1
""",

    # 2. counter with NO observed wrap row -> the modulus is not forced (natural
    #    2^w rollover is a different, unproven behaviour) -> must SKIP.
    "counter_no_wrap_observed": """
 - input  clk
 - input  a
 - output q (3 bits)
The module implements a sequential circuit.
  time  clk a   q
  0ns   0   1   x
  5ns   1   1   2
  10ns  0   1   2
  15ns  1   0   2
  20ns  0   0   2
  25ns  1   0   3
  30ns  0   0   3
""",

    # 3. multi-bit LUT with an UNCOVERED selector value (only 0,1,2 of a 2-bit a) ->
    #    the missing entry is an unforced default -> must SKIP.
    "lut_incomplete_selector": """
 - input  a (2 bits)
 - output q (8 bits)
The module should implement a combinational circuit.
  time  a   q
  15ns  0   12
  20ns  1   34
  25ns  2   56
""",

    # 4. multi-bit LUT contradiction: a=1 maps to TWO different outputs -> not a
    #    function -> must SKIP.
    "lut_contradiction": """
 - input  a (2 bits)
 - output q (8 bits)
The module should implement a combinational circuit.
  time  a   q
  15ns  0   aa
  20ns  1   bb
  25ns  2   cc
  30ns  3   dd
  35ns  1   ee
""",

    # 5. symbolic mux whose tail is NOT unanimous (c=4 -> f but c=5 -> a) -> the
    #    default is not forced -> must SKIP.
    "symbolic_mux_nonunanimous_tail": """
 - input  a (4 bits)
 - input  b (4 bits)
 - input  c (4 bits)
 - input  d (4 bits)
 - input  e (4 bits)
 - output q (4 bits)
The module should implement a combinational circuit.
  time  a  b  c  d  e  q
  15ns  a  b  0  d  e  b
  20ns  a  b  1  d  e  e
  25ns  a  b  2  d  e  a
  30ns  a  b  3  d  e  d
  35ns  a  b  4  d  e  f
  40ns  a  b  5  d  e  a
""",

    # 6. negedge/latch split where one output is NEITHER a clean negedge FF NOR a
    #    transparent latch (it changes on a rising clk-high step) -> must SKIP.
    "split_not_ff_or_latch": """
 - input  clock
 - input  a
 - output p
 - output q
The module should implement a sequential circuit.
  time   clock   a   p   q
  25ns   1       0   0   x
  30ns   1       1   1   x
  55ns   0       1   1   1
  60ns   0       0   1   1
  85ns   1       1   1   0
""",

    # 7. submodule composition missing Module A's boolean prose -> nothing to read
    #    for the A half -> must SKIP.
    "composition_no_module_a": """
Module B can be described by the following simulation waveform:
  time  x  y  z
  0ns   0  0  1
  25ns  1  0  0
  35ns  0  1  0
  45ns  1  1  1
Now consider a top-level module:
 - input  x
 - input  y
 - output z
The module uses an OR, an AND and an XOR.
""",

    # 8. submodule composition whose Module B waveform is INCOMPLETE (only 3 of the
    #    4 input combos observed) -> B's function is not forced -> must SKIP.
    "composition_incomplete_b": """
Module A implements the boolean function z = (x^y) & x.
Module B can be described by the following simulation waveform:
  time  x  y  z
  0ns   0  0  1
  25ns  1  0  0
  35ns  0  1  0
Now consider a top-level module with two A submodules and two B submodules
connected through an OR, an AND and an XOR.
 - input  x
 - input  y
 - output z
""",
}


@pytest.mark.parametrize("name", sorted(NEG_FIXTURES))
def test_no_leak_negative_must_skip(name):
    assert M.synth(NEG_FIXTURES[name]) is None, f"{name} LEAKED a sample (must SKIP)"


def test_at_least_five_negatives():
    assert len(NEG_FIXTURES) >= 5


# --------------------------------------------------------------------------- #
# structural guards
# --------------------------------------------------------------------------- #
def test_empty_and_garbage_skip():
    assert M.synth("") is None
    assert M.synth("   \n  ") is None
    assert M.synth("hello world, this is not a chip spec") is None


def test_skip_returns_none_not_exception():
    # A plain binary 1-FF / combinational waveform is another solver's job: this
    # multi-bit/sequential solver must SKIP it cleanly (return None, never raise).
    binary_1ff = """
 - input  clk
 - input  a
 - output q
The module implements a sequential circuit.
  time  clk a   q
  0ns   0   1   x
  5ns   1   1   1
  10ns  0   0   1
  15ns  1   0   0
"""
    assert M.synth(binary_1ff) is None


def test_pure_function_is_deterministic():
    # synth() must be a pure function: same input -> same output, no global state.
    txt = _prompt("Prob117_circuit9")
    assert M.synth(txt) == M.synth(txt)

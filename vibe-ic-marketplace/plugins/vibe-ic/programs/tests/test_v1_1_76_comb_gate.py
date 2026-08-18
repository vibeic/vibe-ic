#!/usr/bin/env python3
"""test_v1_1_76_comb_gate.py — pins the deterministic combinational gate / wire /
boolean-equation SOLVER (programs/comb_gate_synth.py) on the REAL VerilogEval prompts
and on the §4.05 no-leak boundary.

POSITIVE: each firing problem (single NOT/AND/NOR/XNOR gate, wire pass-through, the
"same value combinationally" pass-through, the gates4/gates100 reduction bank, the
gates 7-output 2-input bank, and the explicit boolean-equation problem) must FIRE and
emit the load-bearing RTL. Where the dataset's golden test bench is present we ALSO
host-score the emitted RTL to 0 mismatches (the AUTHORITATIVE gate); when iverilog or
the dataset is absent the host-score asserts are skipped but the emit asserts run.

NEGATIVE (§4.05 NO-LEAK): >=5 prompts that sit JUST outside the boundary — a
read-the-waveform circuit, a chip-number-described gate network, a descriptive
neighbour-relationship vector, an unstated/ambiguous gate type, an equation that
references an undeclared signal, a structural bubble/submodule description, and a
sequential (clocked) prompt — MUST return None. A wrong gate is far worse than a skip.

CORPUS: a sweep over the whole spec-to-rtl dataset asserts every fire host-scores to
0 mismatches AND that the firing set stays exactly the audited list (zero false-fires).
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]    # programs/ (the solver dir)
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import comb_gate_synth  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _prompt(prob: str) -> str:
    return (_DS / f"{prob}_prompt.txt").read_text(errors="replace")


def _have_problem(prob: str) -> bool:
    return all(
        (_DS / f"{prob}_{suf}").is_file()
        for suf in ("prompt.txt", "ref.sv", "test.sv")
    )


def _host_score(prob: str, rtl: str):
    """Compile emitted RTL + dataset ref + test; return mismatched-sample count.

    Returns an int (0 == PASS) or None if the toolchain/dataset is unavailable.
    """
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return None
    if not _have_problem(prob):
        return None
    with tempfile.TemporaryDirectory() as wd:
        wd = Path(wd)
        (wd / "dut.sv").write_text(rtl)
        comp = subprocess.run(
            [
                "iverilog", "-g2012", "-o", str(wd / "a.vvp"),
                str(wd / "dut.sv"),
                str(_DS / f"{prob}_ref.sv"),
                str(_DS / f"{prob}_test.sv"),
            ],
            capture_output=True, text=True,
        )
        assert comp.returncode == 0, f"{prob} compile failed:\n{comp.stderr}"
        run = subprocess.run(["vvp", str(wd / "a.vvp")], capture_output=True,
                             text=True)
        out = run.stdout + run.stderr
        m = re.search(r"Total mismatched samples is (\d+)", out)
        assert m is not None, f"{prob}: no mismatch line in vvp output:\n{out}"
        return int(m.group(1))


def _fire_and_score(prob: str, *needles: str) -> None:
    rtl = comb_gate_synth.synth(_prompt(prob))
    assert rtl is not None, f"{prob} should FIRE"
    assert "module TopModule" in rtl
    for n in needles:
        assert n in rtl, f"{prob}: expected {n!r} in emitted RTL:\n{rtl}"
    ms = _host_score(prob, rtl)
    if ms is not None:
        assert ms == 0, f"{prob} host mismatches={ms}"


# --------------------------------------------------------------------------- #
# POSITIVE — single named gate                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob005_notgate"), reason="dataset absent")
def test_prob005_notgate():
    _fire_and_score("Prob005_notgate", "assign out = ~in;")


@pytest.mark.skipif(not _have_problem("Prob011_norgate"), reason="dataset absent")
def test_prob011_norgate():
    _fire_and_score("Prob011_norgate", "assign out = ~(a | b);")


@pytest.mark.skipif(not _have_problem("Prob012_xnorgate"), reason="dataset absent")
def test_prob012_xnorgate():
    _fire_and_score("Prob012_xnorgate", "assign out = ~(a ^ b);")


@pytest.mark.skipif(not _have_problem("Prob014_andgate"), reason="dataset absent")
def test_prob014_andgate():
    _fire_and_score("Prob014_andgate", "assign out = a & b;")


@pytest.mark.skipif(not _have_problem("Prob013_m2014_q4e"), reason="dataset absent")
def test_prob013_nor_named_in1_in2():
    # operands are NOT a/b; the solver must use the actually-declared inputs.
    _fire_and_score("Prob013_m2014_q4e", "assign out = ~(in1 | in2);")


# --------------------------------------------------------------------------- #
# POSITIVE — wire / buffer pass-through                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob007_wire"), reason="dataset absent")
def test_prob007_wire():
    _fire_and_score("Prob007_wire", "assign out = in;")


@pytest.mark.skipif(not _have_problem("Prob008_m2014_q4h"), reason="dataset absent")
def test_prob008_same_value_combinationally():
    _fire_and_score("Prob008_m2014_q4h", "assign out = in;")


# --------------------------------------------------------------------------- #
# POSITIVE — per-output reduction bank                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob051_gates4"), reason="dataset absent")
def test_prob051_gates4_reduction_bank():
    _fire_and_score(
        "Prob051_gates4",
        "assign out_and = &in;", "assign out_or = |in;", "assign out_xor = ^in;",
    )


@pytest.mark.skipif(not _have_problem("Prob052_gates100"), reason="dataset absent")
def test_prob052_gates100_reduction_bank():
    _fire_and_score(
        "Prob052_gates100",
        "[99:0] in", "assign out_and = &in;", "assign out_xor = ^in;",
    )


# --------------------------------------------------------------------------- #
# POSITIVE — 2-input named-scalar gate bank                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob087_gates"), reason="dataset absent")
def test_prob087_gates_2input_bank():
    _fire_and_score(
        "Prob087_gates",
        "assign out_and = a & b;",
        "assign out_nand = ~(a & b);",
        "assign out_nor = ~(a | b);",
        "assign out_anotb = a & ~b;",
    )


# --------------------------------------------------------------------------- #
# POSITIVE — explicit boolean equation                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob010_mt2015_q4a"), reason="dataset absent")
def test_prob010_explicit_boolean_equation():
    _fire_and_score("Prob010_mt2015_q4a", "assign z = (x^y) & x;")


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK — must SKIP (return None)                                      #
# --------------------------------------------------------------------------- #
def test_noleak_read_the_waveform_circuit():
    """A 'read the simulation waveforms to determine what the circuit does' prompt
    encodes the function as a TABLE, not as gate prose — that is the waveform path,
    NOT this solver => SKIP (even though the answer happens to be q = a&b)."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a
 - input  b
 - output q

The module should implement a combinational circuit. Read the simulation
waveforms to determine what the circuit does, then implement it.

  time  a  b  q
  0ns   0  0  0
  45ns  1  1  1
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_chip_number_described_gate_network():
    """A 7400-series chip described by NAME (7420 = two 4-input NAND gates) is a
    descriptive structural spec, not gate-exact prose => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  p1a
 - input  p1b
 - input  p1c
 - input  p1d
 - output p1y

The 7420 is a chip with two 4-input NAND gates. The module should implement
the same functionality as the 7420 chip.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_descriptive_neighbour_relationship():
    """A neighbour-relationship vector ('its neighbour to the left') is descriptive
    prose, not a single named gate / equation => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in       (4 bits)
 - output out_both (4 bits)

out_both: each bit should indicate whether both the corresponding input bit and
its neighbour to the left are '1'.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_unstated_gate_type():
    """'Combine the inputs' with NO stated gate type — the boolean function is
    undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a
 - input  b
 - output out

The module should combine the two inputs into a single output.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_equation_references_undeclared_signal():
    """An explicit boolean equation whose RHS names a signal that is NOT a declared
    input port (here 'c') is under-specified => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  x
 - input  y
 - output z

The module should implement the boolean function z = (x ^ y) & c.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_structural_bubble_description():
    """A bubble/structural circuit description ('an AND gate, but in2 has a bubble')
    is structural prose, not a single named gate => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in1
 - input  in2
 - output out

Two inputs (in1 and in2) go to an AND gate, but the in2 input to the AND gate
has a bubble. The output of the AND gate is connected to 'out'.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_arithmetic_is_not_a_gate():
    """An adder ('out = a + b') is the arithmetic path, not this boolean-gate
    solver — there is no & | ^ ~ gate stated => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a   (4 bits)
 - input  b   (4 bits)
 - output sum (4 bits)

The module should add the two input vectors.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_sequential_prompt_skips():
    """A clocked prompt is not combinational at all => SKIP even if it mentions a
    gate-like word."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  clk
 - input  a
 - input  b
 - output out

The module should implement a 2-input AND gate registered on the clock.
"""
    assert comb_gate_synth.synth(prompt) is None


def test_noleak_partial_bank_leaves_an_output_to_prose():
    """A bank where one declared output is NOT covered by an explicit line is
    partially-specified => SKIP (no guessing the missing output)."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a
 - input  b
 - output out_and
 - output out_mystery

There are 2 outputs:
  (1) out_and: a and b
  (2) out_mystery: something clever involving a and b.
"""
    assert comb_gate_synth.synth(prompt) is None


# --------------------------------------------------------------------------- #
# CORPUS NO-LEAK SWEEP — the firing set is exactly the audited list, every    #
# fire host-scores to 0 mismatches, and nothing else leaks.                   #
# --------------------------------------------------------------------------- #
_EXPECTED_FIRES = {
    "Prob005_notgate", "Prob007_wire", "Prob008_m2014_q4h", "Prob010_mt2015_q4a",
    "Prob011_norgate", "Prob012_xnorgate", "Prob013_m2014_q4e", "Prob014_andgate",
    "Prob051_gates4", "Prob052_gates100", "Prob087_gates",
}


@pytest.mark.skipif(not _DS.is_dir(), reason="dataset absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_corpus_fire_set_and_no_false_fires():
    fired = set()
    for pp in sorted(_DS.glob("*_prompt.txt")):
        base = pp.name[: -len("_prompt.txt")]
        if comb_gate_synth.synth(pp.read_text(errors="replace")):
            fired.add(base)
    # exactly the audited family members fire — no more (zero false-fires), no less.
    assert fired == _EXPECTED_FIRES, (
        f"unexpected={fired - _EXPECTED_FIRES}, missing={_EXPECTED_FIRES - fired}"
    )


@pytest.mark.skipif(not _DS.is_dir() or shutil.which("iverilog") is None,
                    reason="dataset or iverilog absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_corpus_every_fire_zero_mismatch():
    for pp in sorted(_DS.glob("*_prompt.txt")):
        base = pp.name[: -len("_prompt.txt")]
        rtl = comb_gate_synth.synth(pp.read_text(errors="replace"))
        if not rtl:
            continue
        ms = _host_score(base, rtl)
        if ms is not None:
            assert ms == 0, f"{base} host mismatches={ms}"


# --------------------------------------------------------------------------- #
# CLI smoke                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob014_andgate"), reason="dataset absent")
def test_cli_emits_rtl_on_fire():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "comb_gate_synth.py"),
         "--prompt", str(_DS / "Prob014_andgate_prompt.txt")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "module TopModule" in r.stdout
    assert "assign out = a & b;" in r.stdout


def test_cli_skips_with_nonzero_exit(tmp_path):
    p = tmp_path / "ambiguous.txt"
    p.write_text(
        " - input a\n - input b\n - output out\n"
        "The module should combine the two inputs somehow.\n"
    )
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "comb_gate_synth.py"), "--prompt", str(p)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "SKIP" in r.stderr

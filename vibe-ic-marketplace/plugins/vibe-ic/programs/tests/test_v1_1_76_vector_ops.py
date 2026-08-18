#!/usr/bin/env python3
"""test_v1_1_76_vector_ops.py — pins the deterministic VECTOR-MANIPULATION SOLVER
(programs/vector_ops_synth.py) on the REAL VerilogEval-Human vector-family prompts
and on the §4.05 no-leak boundary.

POSITIVE: each of the seven firing problems (byte reverse, two bit reverses,
hi/lo split, sign-extend, passthrough+position-mapped bits, concat-then-split with
stated trailing ones) must FIRE and emit the load-bearing RTL lines. Where the
dataset's golden test bench is present we ALSO host-score the emitted RTL to 0
mismatches (the AUTHORITATIVE gate); when iverilog or the dataset is absent the
host-score asserts are skipped, but the structural emit asserts still run.

NEGATIVE (§4.05 NO-LEAK): these prompts sit JUST outside the boundary — a logic op
masquerading as a remap, an unstated reverse granularity, an extend with the KIND
unstated, a split with no upper/lower naming, a passthrough whose bit positions are
not stated, a concat-split whose bit budgets don't match, and a sequential
(clocked) shift. Each MUST return None. A wrong wiring is far worse than a skip.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]    # programs/ (the solver dir)
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import vector_ops_synth  # noqa: E402
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
        import re
        m = re.search(r"Total mismatched samples is (\d+)", out)
        assert m is not None, f"{prob}: no mismatch line in vvp output:\n{out}"
        return int(m.group(1))


# --------------------------------------------------------------------------- #
# POSITIVE — each firing problem                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob004_vector2"),
                    reason="dataset prompt absent")
def test_prob004_byte_reverse():
    rtl = vector_ops_synth.synth(_prompt("Prob004_vector2"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "{in[7:0], in[15:8], in[23:16], in[31:24]}" in rtl
    ms = _host_score("Prob004_vector2", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob006_vectorr"),
                    reason="dataset prompt absent")
def test_prob006_bit_reverse_8():
    rtl = vector_ops_synth.synth(_prompt("Prob006_vectorr"))
    assert rtl is not None
    assert "output reg [7:0] out" in rtl
    assert "out[i] = in[7 - i];" in rtl
    ms = _host_score("Prob006_vectorr", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob023_vector100r"),
                    reason="dataset prompt absent")
def test_prob023_bit_reverse_100():
    rtl = vector_ops_synth.synth(_prompt("Prob023_vector100r"))
    assert rtl is not None
    assert "output reg [99:0] out" in rtl
    assert "out[i] = in[99 - i];" in rtl
    ms = _host_score("Prob023_vector100r", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob015_vector1"),
                    reason="dataset prompt absent")
def test_prob015_split_hi_lo():
    rtl = vector_ops_synth.synth(_prompt("Prob015_vector1"))
    assert rtl is not None
    assert "assign { out_hi, out_lo } = in;" in rtl
    ms = _host_score("Prob015_vector1", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob042_vector4"),
                    reason="dataset prompt absent")
def test_prob042_sign_extend():
    rtl = vector_ops_synth.synth(_prompt("Prob042_vector4"))
    assert rtl is not None
    assert "{ {24{in[7]}}, in }" in rtl
    ms = _host_score("Prob042_vector4", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob032_vector0"),
                    reason="dataset prompt absent")
def test_prob032_passthrough_position_bits():
    rtl = vector_ops_synth.synth(_prompt("Prob032_vector0"))
    assert rtl is not None
    assert "assign outv = vec;" in rtl
    # bit K -> vec[K]: high index first in the LHS concat.
    assert "assign { o2, o1, o0 } = vec;" in rtl
    ms = _host_score("Prob032_vector0", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob064_vector3"),
                    reason="dataset prompt absent")
def test_prob064_concat_split_trailing_ones():
    rtl = vector_ops_synth.synth(_prompt("Prob064_vector3"))
    assert rtl is not None
    assert "assign { w, x, y, z } = { a, b, c, d, e, f, 2'b11 };" in rtl
    ms = _host_score("Prob064_vector3", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK — must SKIP (return None)                                      #
# --------------------------------------------------------------------------- #
def test_noleak_logic_op_is_not_a_remap():
    """Bitwise/logical OR + NOT (Prob044-style) is a LOGIC op, not a pure bit
    permutation — the vector solver must NOT touch it => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a              (3 bits)
 - input  b              (3 bits)
 - output out_or_bitwise (3 bits)
 - output out_or_logical
 - output out_not        (6 bits)

Implement a module with two 3-bit inputs that computes the bitwise-OR of the two
vectors, the logical-OR of the two vectors, and the inverse (NOT) of both vectors.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_reverse_granularity_unstated():
    """"reverse the input" with NEITHER bit nor byte granularity stated — the
    direction/granularity is ambiguous => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in  (16 bits)
 - output out (16 bits)

The module should reverse the input and write it to the output.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_extend_kind_unstated():
    """Widen 8 -> 16 but the prose never says sign-extend vs zero-extend — the pad
    bits are undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in  (8  bits)
 - output out (16 bits)

The module should extend the 8-bit input to a 16-bit output.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_split_without_upper_lower_naming():
    """A 16->8+8 split whose two outputs are NOT named upper/lower (and the prose
    never says which half is which) — the partition direction is ambiguous => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in  (16 bits)
 - output p   ( 8 bits)
 - output q   ( 8 bits)

The module should split the 16-bit input into two 8-bit outputs p and q.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_passthrough_positions_unstated():
    """One 3-bit echo + three 1-bit outputs whose bit POSITIONS are never stated —
    the per-bit wiring is undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  vec  (3 bits)
 - output outv (3 bits)
 - output x
 - output y
 - output z

The module outputs the same vector and also produces three separate 1-bit signals.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_concat_split_budget_mismatch():
    """Concat 6x5=30 bits but split into 4x8=32 bits with NO stated trailing-bit
    accounting — the 2-bit gap is undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a (5 bits)
 - input  b (5 bits)
 - input  c (5 bits)
 - input  d (5 bits)
 - input  e (5 bits)
 - input  f (5 bits)
 - output w (8 bits)
 - output x (8 bits)
 - output y (8 bits)
 - output z (8 bits)

The module should concatenate the input vectors together then split them up into
several output vectors.
"""
    assert vector_ops_synth.synth(prompt) is None


def test_noleak_sequential_shift_is_out_of_scope():
    """A clocked shift register is sequential, not a combinational wiring op — the
    presence of clk/reset means a different module => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  clk
 - input  areset
 - input  in            (32 bits)
 - output out           (32 bits)

The module should reverse the bit ordering of the input and register it on the
positive edge of clk; areset is an asynchronous reset.
"""
    assert vector_ops_synth.synth(prompt) is None


# --------------------------------------------------------------------------- #
# CLI smoke                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob004_vector2"),
                    reason="dataset prompt absent")
def test_cli_emits_rtl_on_fire():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "vector_ops_synth.py"),
         "--prompt", str(_DS / "Prob004_vector2_prompt.txt")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "module TopModule" in r.stdout


def test_cli_skips_with_nonzero_exit(tmp_path):
    p = tmp_path / "ambiguous.txt"
    p.write_text(
        " - input in (16 bits)\n - output out (16 bits)\n"
        "The module should reverse the input.\n"
    )
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "vector_ops_synth.py"), "--prompt", str(p)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "SKIP" in r.stderr

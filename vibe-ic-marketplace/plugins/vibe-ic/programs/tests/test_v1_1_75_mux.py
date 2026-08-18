#!/usr/bin/env python3
"""test_v1_1_75_mux.py — pins the deterministic multiplexer SOLVER
(programs/mux_synth.py) on the REAL VerilogEval-Human mux-family prompts and on the
§4.05 no-leak boundary.

POSITIVE: each of the six firing problems (2:1 scalar/vector, packed 256:1 1-bit and
4-bit, individual 6:1 with stated zero default, individual 9:1 with stated all-ones
default) must FIRE and emit the load-bearing RTL lines. Where the dataset's golden
test bench is present, we ALSO host-score the emitted RTL to 0 mismatches (the
authoritative gate); when iverilog or the dataset is absent the host-score asserts
are skipped, but the structural emit asserts still run.

NEGATIVE (§4.05 NO-LEAK): four prompts that sit JUST outside the boundary —
unstated out-of-range default, ambiguous/inconsistent data width, an unstated input
count, and a non-mux select-shaped function — MUST return None. A wrong mux is far
worse than an honest skip.
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

import mux_synth  # noqa: E402
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
@pytest.mark.skipif(not _have_problem("Prob017_mux2to1v"),
                    reason="dataset prompt absent")
def test_prob017_mux2to1v_vector_2to1():
    rtl = mux_synth.synth(_prompt("Prob017_mux2to1v"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "[99:0] out" in rtl              # 100-bit vectored output
    assert "1'd0: out = a;" in rtl
    assert "1'd1: out = b;" in rtl
    ms = _host_score("Prob017_mux2to1v", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob018_mux256to1"),
                    reason="dataset prompt absent")
def test_prob018_mux256to1_packed_1bit():
    rtl = mux_synth.synth(_prompt("Prob018_mux256to1"))
    assert rtl is not None
    assert "[255:0] in" in rtl
    assert "[7:0] sel" in rtl
    # 1-bit packed slice is the bare bit-index form.
    assert "assign out = in[sel];" in rtl
    ms = _host_score("Prob018_mux256to1", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob021_mux256to1v"),
                    reason="dataset prompt absent")
def test_prob021_mux256to1v_packed_4bit():
    rtl = mux_synth.synth(_prompt("Prob021_mux256to1v"))
    assert rtl is not None
    assert "[1023:0] in" in rtl
    assert "[3:0] out" in rtl
    # 4-bit packed slice: source k at k*4 +: 4.
    assert "in[sel*4 +: 4]" in rtl
    ms = _host_score("Prob021_mux256to1v", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob022_mux2to1"),
                    reason="dataset prompt absent")
def test_prob022_mux2to1_scalar_2to1():
    rtl = mux_synth.synth(_prompt("Prob022_mux2to1"))
    assert rtl is not None
    assert "1'd0: out = a;" in rtl
    assert "1'd1: out = b;" in rtl
    ms = _host_score("Prob022_mux2to1", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob076_always_case"),
                    reason="dataset prompt absent")
def test_prob076_always_case_6to1_zero_default():
    rtl = mux_synth.synth(_prompt("Prob076_always_case"))
    assert rtl is not None
    assert "3'd0: out = data0;" in rtl
    assert "3'd5: out = data5;" in rtl
    # 6 sources in an 8-wide select space => default REQUIRED; prose says "0".
    assert "default: out = 4'b0;" in rtl
    ms = _host_score("Prob076_always_case", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob097_mux9to1v"),
                    reason="dataset prompt absent")
def test_prob097_mux9to1v_all_ones_default():
    rtl = mux_synth.synth(_prompt("Prob097_mux9to1v"))
    assert rtl is not None
    assert "4'd0: out = a;" in rtl
    assert "4'd8: out = i;" in rtl
    # 9 sources, 16-wide select space => default REQUIRED; prose says all bits '1'.
    assert "default: out = {16{1'b1}};" in rtl
    ms = _host_score("Prob097_mux9to1v", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK — must SKIP (return None)                                      #
# --------------------------------------------------------------------------- #
def test_noleak_unstated_out_of_range_default():
    """A 9:1 mux whose select space (16) exceeds N=9, but the prose NEVER states
    what the unused sel 9..15 should output. The default is undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  a   (16 bits)
 - input  b   (16 bits)
 - input  c   (16 bits)
 - input  d   (16 bits)
 - input  e   (16 bits)
 - input  f   (16 bits)
 - input  g   (16 bits)
 - input  h   (16 bits)
 - input  i   (16 bits)
 - input  sel ( 4 bits)
 - output out (16 bits)

The module should implement a 16-bit wide, 9-to-1 multiplexer. sel=0 chooses a,
sel=1 chooses b, etc.
"""
    assert mux_synth.synth(prompt) is None


def test_noleak_ambiguous_data_width():
    """Individual data ports of DIFFERENT widths — the data width is not single /
    consistent, so the mux is ambiguous => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  sel   (2 bits)
 - input  data0 (4 bits)
 - input  data1 (8 bits)
 - input  data2 (4 bits)
 - input  data3 (4 bits)
 - output out   (4 bits)

The module should implement a 4-to-1 multiplexer. Choose the corresponding data
input for each value of sel.
"""
    assert mux_synth.synth(prompt) is None


def test_noleak_unstated_input_count():
    """A multiplexer prose with NO enumerable data ports — the number of inputs is
    not stated, so the source count is undetermined => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  sel (8 bits)
 - output out

The module should implement a multiplexer that selects one of the inputs based on
sel.
"""
    assert mux_synth.synth(prompt) is None


def test_noleak_non_mux_selection_priority_encoder():
    """A select-SHAPED function that is NOT a multiplexer (priority encoder) MUST
    NOT be solved by the mux solver => SKIP."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  in  (8 bits)
 - output pos (3 bits)

The module should implement a priority encoder. Report the position of the
first high bit. If none, output zero.
"""
    assert mux_synth.synth(prompt) is None


def test_noleak_decoder_is_not_mux():
    """A decoder (1-of-N one-hot generation) is also select-shaped but NOT a mux."""
    prompt = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  sel (3 bits)
 - output out (8 bits)

The module should implement a 3-to-8 decoder. For each value of sel, drive the
corresponding one-hot output bit high.
"""
    assert mux_synth.synth(prompt) is None


# --------------------------------------------------------------------------- #
# CLI smoke                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob022_mux2to1"),
                    reason="dataset prompt absent")
def test_cli_emits_rtl_on_fire():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "mux_synth.py"),
         "--prompt", str(_DS / "Prob022_mux2to1_prompt.txt")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "module TopModule" in r.stdout


def test_cli_skips_with_nonzero_exit(tmp_path):
    p = tmp_path / "decoder.txt"
    p.write_text(
        " - input sel (3 bits)\n - output out (8 bits)\n"
        "The module should implement a 3-to-8 decoder.\n"
    )
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "mux_synth.py"), "--prompt", str(p)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "SKIP" in r.stderr

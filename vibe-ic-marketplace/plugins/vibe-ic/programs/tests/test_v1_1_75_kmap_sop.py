#!/usr/bin/env python3
"""test_v1_1_75_kmap_sop.py — pins the deterministic K-map -> RTL SOLVER
(programs/kmap_sop_synth.py) on the REAL VerilogEval-Human K-map-family prompts and
on the §4.05 no-leak boundary.

POSITIVE: the six firing problems must FIRE, emit a full truth-table case module,
and — where the dataset golden test bench is present — host-score to 0 mismatches
(the authoritative gate; for don't-care maps this is what validates the chosen
assignment is accepted by the TB):
  - Prob050_kmap1   : 3-var, 1-var column axis 'a' + 2-var row 'bc'        (FIRE, 0)
  - Prob057_kmap2   : 4-var standard Gray, no don't-cares                  (FIRE, 0)
  - Prob113_2012_q1g: 4-bit bus axes x[0]x[1]/x[2]x[3] (lookup)            (FIRE, 0)
  - Prob116_m2014_q3: 4-bit bus axes x[1]x[2]/x[3]x[4] + don't-cares->0    (FIRE, 0)
  - Prob122_kmap4   : 4-var standard Gray, no don't-cares (the a^b^c^d map)(FIRE, 0)
  - Prob125_kmap3   : 4-var reordered column header '01 00 10 11' + d.c.   (FIRE, 0)

SKIP (intended, not a leak): Prob093_ece241_2014_q3 — the output is `mux_in (4 bits)`,
a multiplexer transform, NOT the K-map value -> the solver returns None.

NEGATIVE (§4.05 NO-LEAK): prompts that sit JUST outside the parseable boundary —
no K-map keyword, a multi-bit/transform output, a corrupt column header (not a clean
Gray permutation), an incomplete grid (missing rows), axes that do not partition the
declared inputs, and an unparseable cell token — MUST return None. A wrong function
is far worse than an honest skip.
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

import kmap_sop_synth  # noqa: E402
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

    Returns an int (0 == PASS) or None if the toolchain/dataset is unavailable."""
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
        # cwd=wd so the official TB's `$dumpfile("wave.vcd")` lands in the
        # auto-cleaned temp dir, never the plugin tree (ORGANIC #574 hygiene).
        run = subprocess.run(["vvp", str(wd / "a.vvp")], capture_output=True,
                             text=True, cwd=str(wd))
        out = run.stdout + run.stderr
        m = re.search(r"Total mismatched samples is (\d+)", out)
        assert m is not None, f"{prob}: no mismatch line in vvp output:\n{out}"
        return int(m.group(1))


# --------------------------------------------------------------------------- #
# POSITIVE — each firing problem                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob050_kmap1"),
                    reason="dataset prompt absent")
def test_prob050_kmap1_3var_1var_col_axis():
    rtl = kmap_sop_synth.synth(_prompt("Prob050_kmap1"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "case ({a, b, c})" in rtl          # scalar 3-var case over a,b,c
    assert "3'd0: out = 1'b0;" in rtl          # the single 0 cell (a=b=c=0)
    ms = _host_score("Prob050_kmap1", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob057_kmap2"),
                    reason="dataset prompt absent")
def test_prob057_kmap2_4var_standard_gray():
    rtl = kmap_sop_synth.synth(_prompt("Prob057_kmap2"))
    assert rtl is not None
    assert "case ({a, b, c, d})" in rtl
    ms = _host_score("Prob057_kmap2", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob113_2012_q1g"),
                    reason="dataset prompt absent")
def test_prob113_2012_q1g_bus_indexed_lookup():
    rtl = kmap_sop_synth.synth(_prompt("Prob113_2012_q1g"))
    assert rtl is not None
    assert "input [3:0] x" in rtl              # 4-bit bus axes
    assert "case (x)" in rtl
    ms = _host_score("Prob113_2012_q1g", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob116_m2014_q3"),
                    reason="dataset prompt absent")
def test_prob116_m2014_q3_bus_indexed_dontcare():
    rtl = kmap_sop_synth.synth(_prompt("Prob116_m2014_q3"))
    assert rtl is not None
    # The K-map axes are 1-based (x[1]..x[4]); the synth MUST declare the
    # prompt's 1-based bus range [4:1], not a normalized zero-based [3:0]
    # (which the onebased-port-range conformance guard correctly emit-blocks).
    # var_bit maps the smallest axis index to the LSB, so [4:1] keeps x[1] at
    # bit 0 — value-consistent with the case table (host-score confirms below).
    assert "input [4:1] x" in rtl
    assert "input [3:0] x" not in rtl
    assert "case (x)" in rtl
    # the don't-care assignment (->0) must be accepted by the golden TB on the
    # CARE cells; the host-score is the authoritative validation of that choice.
    ms = _host_score("Prob116_m2014_q3", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob122_kmap4"),
                    reason="dataset prompt absent")
def test_prob122_kmap4_4var_xor_map():
    rtl = kmap_sop_synth.synth(_prompt("Prob122_kmap4"))
    assert rtl is not None
    assert "case ({a, b, c, d})" in rtl
    ms = _host_score("Prob122_kmap4", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


@pytest.mark.skipif(not _have_problem("Prob125_kmap3"),
                    reason="dataset prompt absent")
def test_prob125_kmap3_reordered_header_dontcare():
    rtl = kmap_sop_synth.synth(_prompt("Prob125_kmap3"))
    assert rtl is not None
    assert "case ({a, b, c, d})" in rtl
    # reordered column header '01 00 10 11' must be decoded by LABEL, not position;
    # don't-care -> 0 must host-score clean on the CARE cells.
    ms = _host_score("Prob125_kmap3", rtl)
    if ms is not None:
        assert ms == 0, f"host mismatches={ms}"


# --------------------------------------------------------------------------- #
# INTENDED SKIP (not a leak) — transform output                              #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_problem("Prob093_ece241_2014_q3"),
                    reason="dataset prompt absent")
def test_prob093_mux_transform_skips():
    # output is `mux_in (4 bits)` (a multiplexer transform, not the K-map value)
    assert kmap_sop_synth.synth(_prompt("Prob093_ece241_2014_q3")) is None


# --------------------------------------------------------------------------- #
# NEGATIVE — §4.05 NO-LEAK boundary (all MUST return None)                    #
# --------------------------------------------------------------------------- #
def test_neg_no_kmap_keyword():
    p = (
        "I would like you to implement a module named TopModule.\n"
        " - input  a\n"
        " - input  b\n"
        " - output out\n"
        "The module should output a AND b.\n"
    )
    assert kmap_sop_synth.synth(p) is None


def test_neg_multibit_transform_output():
    # a real K-map grid but the output is a multi-bit mux transform -> SKIP
    p = (
        "Implement TopModule from the Karnaugh map below.\n"
        " - input  c\n"
        " - input  d\n"
        " - output mux_in (4 bits)\n"
        "      ab\n"
        "  cd  00  01  11  10\n"
        "  00 | 0 | 0 | 0 | 1 |\n"
        "  01 | 1 | 0 | 0 | 0 |\n"
        "  11 | 1 | 0 | 1 | 1 |\n"
        "  10 | 1 | 0 | 0 | 1 |\n"
    )
    assert kmap_sop_synth.synth(p) is None


def test_neg_corrupt_column_header():
    # column header '00 01 11 11' is not a clean Gray permutation (dup, gap) -> SKIP
    p = (
        "Implement TopModule from the Karnaugh map below.\n"
        " - input  a\n - input  b\n - input  c\n - input  d\n"
        "      ab\n"
        "  cd  00  01  11  11\n"
        "  00 | 1 | 1 | 0 | 1 |\n"
        "  01 | 1 | 0 | 0 | 1 |\n"
        "  11 | 0 | 1 | 1 | 1 |\n"
        "  10 | 1 | 1 | 0 | 0 |\n"
    )
    assert kmap_sop_synth.synth(p) is None


def test_neg_incomplete_grid_missing_rows():
    # only 2 of the 4 required rows present -> incomplete table -> SKIP
    p = (
        "Implement TopModule from the Karnaugh map below.\n"
        " - input  a\n - input  b\n - input  c\n - input  d\n"
        "      ab\n"
        "  cd  00  01  11  10\n"
        "  00 | 1 | 1 | 0 | 1 |\n"
        "  01 | 1 | 0 | 0 | 1 |\n"
    )
    assert kmap_sop_synth.synth(p) is None


def test_neg_axes_do_not_partition_inputs():
    # the column axis 'ae' names 'e' which is not a declared input -> SKIP
    p = (
        "Implement TopModule from the Karnaugh map below.\n"
        " - input  a\n - input  b\n - input  c\n - input  d\n"
        "      ae\n"
        "  cd  00  01  11  10\n"
        "  00 | 1 | 1 | 0 | 1 |\n"
        "  01 | 1 | 0 | 0 | 1 |\n"
        "  11 | 0 | 1 | 1 | 1 |\n"
        "  10 | 1 | 1 | 0 | 0 |\n"
    )
    assert kmap_sop_synth.synth(p) is None


def test_neg_unparseable_cell_token():
    # a cell value '9' is neither 0/1 nor a recognised don't-care token -> SKIP
    p = (
        "Implement TopModule from the Karnaugh map below.\n"
        " - input  a\n - input  b\n - input  c\n"
        "      a\n"
        "   bc   0   1\n"
        "   00 | 0 | 1 |\n"
        "   01 | 9 | 1 |\n"
        "   11 | 1 | 1 |\n"
        "   10 | 1 | 1 |\n"
    )
    assert kmap_sop_synth.synth(p) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

"""v1.1.38 §4.2 absorption — deterministic Karnaugh-map → RTL synth.

A don't-care-FREE K-map is a complete truth table; the answer is the exact SOP.
This was per-round single-shot variance (a blind author flips the axis mapping);
the synth absorbs it as a PROGRAM.

§4.05 no-leak: FIRES only on an exact (0/1-only) grid; SKIPs any don't-care K-map
(under-determined -> the golden picks one of many valid functions = a genuine
floor, not absorbable), mux-decomposition output, or unparseable grid.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import kmap_grid_synth as K  # noqa: E402

_KMAP_2IN = """
Implement a module named TopModule.
 - input  a
 - input  b
 - output q

The module should implement the function shown in the Karnaugh map below.

       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""


def test_kmap_fires_and_is_correct():
    rtl = K.synth(_KMAP_2IN, "TopModule")
    assert rtl is not None
    assert "assign q" in rtl
    # q = a^b : 1-cells at (b=0,a=1) and (b=1,a=0)
    assert "(~b & a)" in rtl and "(b & ~a)" in rtl


def test_kmap_skip_on_dont_care():
    bad = _KMAP_2IN.replace("| 0 | 1 |", "| d | 1 |")
    assert K.synth(bad, "TopModule") is None


def test_kmap_skip_on_mux_decomposition():
    p = _KMAP_2IN.replace("output  q", "output mux_in (4 bits)").replace(
        " q\n", " mux_in (4 bits)\n")
    p = p.replace("function shown", "mux_in function shown") + "\nmux_in"
    assert K.synth(p, "TopModule") is None


def test_kmap_skip_when_not_a_kmap():
    assert K.synth("Implement TopModule, a combinational adder.", "TopModule") is None


# ── Step-2.7 §4.05 remediations ───────────────────────────────────────────────

def test_kmap_skip_multibit_output():
    """A K-map is a single-bit function. A multi-bit output driven by the 1-bit
    SOP (`output [3:0] q; assign q = <sop>`) compiles clean and PASSes
    spec_conformance → it would ship a width-broken sample SILENTLY. SKIP."""
    assert K.synth(_KMAP_2IN.replace(" - output q", " - output q (4 bits)"),
                   "TopModule") is None


def test_kmap_skip_when_axis_not_declared_port():
    """Axis labels are read from grid LAYOUT; a case-mismatch (`A`/`B` vs declared
    `a`/`b`) or stray word makes the SOP reference UNDECLARED signals → a wrong
    sample. Every axis bit must be a declared input port → else SKIP."""
    up = _KMAP_2IN.replace("       a\n", "       A\n").replace("  b   0   1", "  B   0   1")
    assert K.synth(up, "TopModule") is None


def test_kmap_clean_still_fires():
    rtl = K.synth(_KMAP_2IN, "TopModule")
    assert rtl is not None and "(~b & a)" in rtl and "(b & ~a)" in rtl


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── K-map → external-mux DECOMPOSITION (Shannon expansion) ───────────────────
# The grid's columns are printed in GRAY order (00 01 11 10) while a mux data
# input is indexed by the plain BINARY value of the selector. Reading the
# columns left-to-right into mux_in[0..3] swaps the last two data inputs. This
# fixture is built so the two readings DISAGREE, so the assertions discriminate.

_KMAP_MUX_DECOMP = """
Implement a module named TopModule.
 - input  c
 - input  d
 - output mux_in (4 bits)

The module should implement the function shown in the Karnaugh map below,
supplying the data inputs of an external 4-to-1 multiplexer whose select
inputs are {a,b}; ab = 00 is connected to mux_in[0], ab = 01 to mux_in[1],
and so on.

      ab
  cd  00  01  11  10
  00 | 0 | 1 | 1 | 0 |
  01 | 0 | 1 | 0 | 1 |
  11 | 0 | 1 | 0 | 0 |
  10 | 0 | 1 | 0 | 0 |
"""


def test_kmap_mux_decomposition_fires():
    """RED before the mux-decomposition branch existed: synth returned None
    (SKIP) for this whole family, so a coin-flipping blind author decided the
    index mapping instead of the program."""
    assert K.synth(_KMAP_MUX_DECOMP, "TopModule") is not None


def test_kmap_mux_decomposition_indexes_by_binary_not_gray():
    """GREEN: each data input is the column for that SELECTOR VALUE.

    Column ab=11 (binary 3) is 1 only at cd=00, and column ab=10 (binary 2) is
    1 only at cd=01. Indexing by print position instead would swap them -- the
    exact defect this branch removes."""
    rtl = K.synth(_KMAP_MUX_DECOMP, "TopModule")
    body = {ln.split("=")[0].strip(): ln.split("=", 1)[1].strip()
            for ln in rtl.splitlines() if ln.strip().startswith("assign")}
    assert body["assign mux_in[0]"] == "1'b0;"                    # all-zero column
    assert body["assign mux_in[1]"].count("|") == 3               # all-ones column
    assert body["assign mux_in[3]"] == "(~c & ~d);"               # ab=11 -> index 3
    assert body["assign mux_in[2]"] == "(~c & d);"                # ab=10 -> index 2
    # and the two are genuinely different, so the assertion above discriminates
    assert body["assign mux_in[2]"] != body["assign mux_in[3]"]


def test_kmap_mux_decomposition_skips_when_selectors_are_ports():
    """Envelope: if EVERY axis variable is a declared port this is an ordinary
    K-map, not a mux decomposition, and the vector output must still SKIP."""
    p = _KMAP_MUX_DECOMP.replace(" - input  c", " - input  a\n - input  b\n - input  c")
    assert K.synth(p, "TopModule") is None


def test_kmap_mux_decomposition_skips_on_dont_care():
    """An under-determined grid stays a FLOOR (§4.05), decomposition or not."""
    p = _KMAP_MUX_DECOMP.replace("  01 | 0 | 1 | 0 | 1 |", "  01 | 0 | 1 | 0 | d |")
    assert K.synth(p, "TopModule") is None


def test_kmap_mux_decomposition_skips_on_width_mismatch():
    """Output width must equal 2**(number of selector bits), else the reading
    that each bit is one selector value does not hold."""
    p = _KMAP_MUX_DECOMP.replace("mux_in (4 bits)", "mux_in (8 bits)")
    assert K.synth(p, "TopModule") is None

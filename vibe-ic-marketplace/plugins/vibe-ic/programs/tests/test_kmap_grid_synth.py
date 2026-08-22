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

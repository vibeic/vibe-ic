#!/usr/bin/env python3
"""ORGANIC #758 [P2, chip-AGNOSTIC] — spec_coverage_check --strict derived a
PHANTOM registered-latency checklist item for an explicitly COMBINATIONAL design
(a "completes in one clock cycle" idiom sitting beside "purely combinational
logic / changes immediately").

Root cause: `_specrtl_common._detect_latency` returned True on the bare
"one clock cycle" phrase BEFORE its (too-narrow "combinational output") guard
could suppress it, and the `spec_coverage_check` wrapper only tested truthiness,
so a False (explicitly combinational) fell through to the fallback `_LATENCY_RE`
that re-matched "one clock cycle" and re-derived the phantom item.

Fix: `_detect_latency` is tri-state (True=registered, False=explicitly
combinational/zero-latency, None=unknown); explicit "registered output" wins
even amid combinational phrasing; a broadened combinational/zero-latency
declaration suppresses the ambiguous "one clock cycle"; the wrapper honours a
False as authoritative suppression (mirrors the #743 negation guard).

§4.05 NO-LEAK: a genuinely REGISTERED design (incl. one that ALSO mentions
combinational internal logic but declares "registered output") whose TB does NOT
cover the timing requirement must STILL derive the latency item and BLOCK.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _specrtl_common as S  # noqa: E402

_PROG = _PROGRAMS / "spec_coverage_check.py"

_TB_NO_LATENCY = (
    "module tb; reg [3:0] a, b; wire [4:0] sum; dut u(a, b, sum);\n"
    "initial begin a=1; b=2; #1; if (sum!==3) $display(\"FAIL\"); $finish; end\n"
    "endmodule\n")


def _run(tmp_path, spec_text, tb_text=_TB_NO_LATENCY):
    sp = tmp_path / "spec.md"
    tb = tmp_path / "tb.sv"
    sp.write_text(spec_text)
    tb.write_text(tb_text)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(sp), "--tb", str(tb),
         "--strict"], capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ── (a) NEW-PATH: tri-state helper + combinational spec is not charged latency ──
def test_758_detect_latency_tristate():
    assert S._detect_latency(
        "purely combinational logic. output changes immediately. "
        "completes in one clock cycle.") is False
    assert S._detect_latency(
        "the output is registered. completes in one clock cycle.") is True
    # explicit registered-output wins even amid combinational phrasing.
    assert S._detect_latency(
        "registered output. but internal logic is combinational and "
        "changes immediately.") is True


def test_758_combinational_spec_no_phantom_latency(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Adder\nPurely combinational logic. The output `sum` changes "
        "immediately as inputs change. The computation completes in one clock "
        "cycle of propagation. No registers.\n")
    assert rc == 0, out
    assert "spec-coverage ok" in out
    assert "latency" not in out.lower() or "GAP" not in out


def test_758_broad_combinational_variants_all_suppressed():
    for phrase in ("unregistered output, one clock cycle",
                   "zero latency, completes in one clock cycle",
                   "output changes immediately, one clock cycle",
                   "combinational block, one clock cycle"):
        assert S._detect_latency(phrase) is False, phrase


# ── (b) §4.05 NEGATIVE NO-LEAK: a genuinely registered design still BLOCKs ─────
def test_758_noleak_registered_uncovered_still_blocks(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Accumulator\nThe output `acc` is registered. The result appears one "
        "clock cycle after the inputs are valid.\n")
    assert rc == 1, out
    assert "latency" in out.lower() and "GAP" in out


def test_758_noleak_contradictory_registered_output_still_blocks(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Mixed\nThe internal datapath is combinational and changes "
        "immediately, but the output `q` is a registered output, valid one "
        "clock cycle later.\n")
    assert rc == 1, out
    assert "latency" in out.lower() and "GAP" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

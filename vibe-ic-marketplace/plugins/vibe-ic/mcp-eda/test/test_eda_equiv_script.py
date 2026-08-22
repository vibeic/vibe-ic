#!/usr/bin/env python3
"""Tests for eda_equiv MCP tool — Yosys equivalence-check script.

v0.99.1 fix: replaced invalid `read_verilog -gold` / `equiv_make -gold
-gate <top>` flags (Yosys rejected) with the canonical `design -stash`
flow. v0.119.22: this test runs the actual yosys command outside docker
to verify the script structure works end-to-end on real RTL.

The test does two things:

  1. Static check on src/index.js — assert the script structure (no
     dead `-gold`/`-gate` flags, has `design -stash`, has
     `equiv_status -assert` so mismatches actually fail).

  2. Runtime check — invoke `yosys -p '<script>'` on a tiny equivalent
     and a tiny non-equivalent gold/gate pair, assert PASS and FAIL
     respectively.

Skips runtime check if yosys is not on PATH (CI matrix without yosys).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
assert INDEX_JS.is_file(), f"missing {INDEX_JS}"


def _extract_equiv_block(src: str) -> str:
    """Return the body of the eda_equiv tool registration."""
    m = re.search(
        r'server\.tool\(\s*"eda_equiv".*?^\);',
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, "eda_equiv tool registration not found in index.js"
    return m.group(0)


def _strip_js_comments(s: str) -> str:
    """Remove // single-line and /* block */ comments so we test the
    actual code, not the v0.99.1 changelog text mentioning the dead
    flags by name."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def test_index_js_no_dead_yosys_flags():
    """Regression for v0.99.0 → v0.99.1: the dead `-gold` / `-gate`
    flags must NOT reappear in the eda_equiv script (excluding
    comments which document the historical fix)."""
    block = _strip_js_comments(_extract_equiv_block(INDEX_JS.read_text()))
    assert "read_verilog -gold" not in block, \
        "dead `-gold` flag from v0.99.0 must NOT recur"
    assert "read_verilog -gate" not in block, \
        "dead `-gate` flag from v0.99.0 must NOT recur"
    assert "equiv_make -gold -gate" not in block, \
        "dead `-gold -gate` form of equiv_make must NOT recur"


def test_index_js_uses_design_stash_flow():
    """The canonical Yosys flow uses design -stash to keep the two
    RTL trees separate before equiv_make."""
    block = _extract_equiv_block(INDEX_JS.read_text())
    for required in (
        "design -stash gold",
        "design -stash gate",
        "equiv_make gold gate equiv",
        "equiv_status -assert",  # critical: makes mismatch produce non-zero exit
    ):
        assert required in block, f"missing required step: {required!r}"


def test_index_js_runs_induction_and_simple():
    block = _extract_equiv_block(INDEX_JS.read_text())
    assert "equiv_simple" in block
    assert "equiv_induct" in block


YOSYS = shutil.which("yosys")


def _yosys_equiv(tmp_path: Path, gold_text: str, gate_text: str,
                 top: str = "and2") -> subprocess.CompletedProcess:
    """Run the canonical eda_equiv script directly (skip docker / mcp)."""
    gold = tmp_path / "gold.v"
    gate = tmp_path / "gate.v"
    gold.write_text(gold_text)
    gate.write_text(gate_text)
    script = "; ".join([
        f"read_verilog -sv {gold}",
        f"hierarchy -check -top {top}",
        f"prep -top {top}",
        "design -stash gold",
        f"read_verilog {gate}",
        f"hierarchy -check -top {top}",
        f"prep -top {top}",
        "design -stash gate",
        f"design -copy-from gold -as gold {top}",
        f"design -copy-from gate -as gate {top}",
        "equiv_make gold gate equiv",
        "prep -top equiv",
        "equiv_simple",
        "equiv_induct",
        "equiv_status -assert",
    ])
    return subprocess.run(
        [YOSYS, "-p", script],
        capture_output=True, text=True, timeout=60,
    )


@pytest.mark.skipif(not YOSYS, reason="yosys not on PATH")
def test_yosys_equiv_passes_on_equivalent_pair(tmp_path):
    """Two AND2 modules expressed differently must prove equivalent."""
    gold = """\
module and2(input a, input b, output y);
  assign y = a & b;
endmodule
"""
    gate = """\
module and2(input a, input b, output y);
  wire t;
  assign t = ~(a & b);
  assign y = ~t;
endmodule
"""
    r = _yosys_equiv(tmp_path, gold, gate)
    assert r.returncode == 0, \
        f"equivalent pair must PASS, got rc={r.returncode}\n{r.stdout[-500:]}"
    # Yosys 0.33 says "proven", earlier versions say "proved" — accept either.
    assert ("Equivalence successfully prove" in r.stdout), \
        f"missing PASS marker in:\n{r.stdout[-800:]}"


@pytest.mark.skipif(not YOSYS, reason="yosys not on PATH")
def test_yosys_equiv_fails_on_nonequivalent_pair(tmp_path):
    """An AND2 vs OR2 mismatch must FAIL (equiv_status -assert exits 1).

    This is the regression that v0.99.1 fixed — without `-assert`, a
    silent mismatch could appear PASS. With the canonical script,
    yosys returns non-zero rc on real divergence."""
    gold = """\
module and2(input a, input b, output y);
  assign y = a & b;
endmodule
"""
    gate = """\
module and2(input a, input b, output y);
  assign y = a | b;   // wrong — OR instead of AND
endmodule
"""
    r = _yosys_equiv(tmp_path, gold, gate)
    assert r.returncode != 0, \
        f"non-equivalent pair must FAIL, got rc=0\n{r.stdout[-500:]}"
    # Yosys' -assert produces "Found 1 unproven $equiv cells" or
    # "Assertion failed". Either is acceptable as a divergence signal.
    combined = (r.stdout + r.stderr).lower()
    assert ("unproven" in combined or "assert" in combined
            or "not equivalent" in combined or "proof failed" in combined), \
        f"missing divergence marker in:\n{r.stdout[-800:]}\n--- stderr ---\n{r.stderr[-500:]}"

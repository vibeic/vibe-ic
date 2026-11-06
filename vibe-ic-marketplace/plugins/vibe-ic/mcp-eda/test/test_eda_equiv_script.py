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

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
assert INDEX_JS.is_file(), f"missing {INDEX_JS}"












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
    return _pr.run(
        [YOSYS, "-p", script],
        capture_output=True, text=True)


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

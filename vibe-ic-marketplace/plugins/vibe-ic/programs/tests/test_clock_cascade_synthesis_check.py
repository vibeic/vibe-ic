#!/usr/bin/env python3
"""Tests for clock_cascade_synthesis_check.py — see ROOT_CAUSE_ANALYSIS Area 2."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "clock_cascade_synthesis_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _l9(tmp_path: Path, binding: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "clock_binding": binding,
    }))


def _dtop(tmp_path: Path, body: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dtop.v").write_text(body)


def test_no_l9_silent_pass(tmp_path):
    """No L9 → gate skips."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no clock_binding" in r.stdout


def test_single_clock_binding_silent_pass(tmp_path):
    """L9 declares only one clock → cascade not required, skip."""
    _l9(tmp_path, {"rx_phy": "sys_clk", "tx_phy": "sys_clk"})
    _dtop(tmp_path, """module dtop;
  rx_phy u_rx (.clk(sys_clk));
  tx_phy u_tx (.clk(sys_clk));
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "only 1" in r.stdout or "skipped" in r.stdout


def test_multi_clock_correctly_routed_passes(tmp_path):
    """L9 declares 2 distinct clocks AND top routes each instance
    to its respective wire → PASS."""
    _l9(tmp_path, {
        "rx_phy":   "sys_clk_5m",
        "tx_phy":   "sys_clk_2p5m",
        "gen_wake": "sys_clk_312p5k",
    })
    _dtop(tmp_path, """module dtop;
  rx_phy u_rx       (.clk(sys_clk_5m));
  tx_phy u_tx       (.clk(sys_clk_2p5m));
  gen_wake u_wake   (.clk(sys_clk_312p5k));
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "3 distinct" in r.stdout or "distinct clock" in r.stdout


def test_multi_clock_collapsed_to_single_wire_fails(tmp_path):
    """L9 declares 3 distinct clocks but top ties every instance to a
    single `clk_sys` → FAIL (the benchmark_a fingerprint)."""
    _l9(tmp_path, {
        "rx_phy":   "sys_clk_5m",
        "tx_phy":   "sys_clk_2p5m",
        "gen_wake": "sys_clk_312p5k",
    })
    _dtop(tmp_path, """module dtop;
  rx_phy u_rx       (.clk(clk_sys));
  tx_phy u_tx       (.clk(clk_sys));
  gen_wake u_wake   (.clk(clk_sys));
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "single wire" in r.stdout


def test_waiver_skips(tmp_path):
    _l9(tmp_path, {
        "rx_phy":   "sys_clk_5m",
        "tx_phy":   "sys_clk_2p5m",
    })
    _dtop(tmp_path, """module dtop;
  rx_phy u_rx (.clk(clk_sys));
  tx_phy u_tx (.clk(clk_sys));
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "clock_cascade_synthesis_alternative":
            "Single-clock variant validated against EXAMPLE_TESTER oracle in lab",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_top_rtl_silent_pass(tmp_path):
    """L9 ok but no rtl/dtop* — gate skips."""
    _l9(tmp_path, {"rx_phy": "a", "tx_phy": "b"})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no top-level RTL" in r.stdout

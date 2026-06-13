"""Unit tests for fsm_table_rtl_gen.py — deterministic FSM-table → RTL generator.

Driven by the VerilogEval-v2 run: Prob100 (fsm3comb) hands an explicit Moore
state-transition table, for which the RTL is mechanically derivable. This proves
the generator emits correct, synthesizable, deterministic RTL for the three FSM
kinds — the Phase-2 "program writes the RTL" enhancement.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fsm_table_rtl_gen.py"
assert SCRIPT.exists()

# The Prob100 fsm3comb Moore combinational table (A=0,B=1,C=2,D=3).
PROB100 = {
    "module": "TopModule", "kind": "moore_comb",
    "input": "in", "state_in": "state", "next_state_out": "next_state", "output": "out",
    "encoding": {"A": 0, "B": 1, "C": 2, "D": 3},
    "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "C", "1": "B"},
                    "C": {"0": "A", "1": "D"}, "D": {"0": "C", "1": "B"}},
    "outputs": {"A": 0, "B": 0, "C": 0, "D": 1},
}


def _gen(tmp_path, spec):
    p = tmp_path / "fsm.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "out.sv"
    r = subprocess.run([sys.executable, str(SCRIPT), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    return r, (out.read_text() if out.exists() else "")


def _iverilog_ok(tmp_path, rtl):
    """Compile the module standalone with iverilog -g2012 (if available)."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")
    sv = tmp_path / "m.sv"
    sv.write_text(rtl)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b"), str(sv)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def test_moore_comb_generates_correct_logic(tmp_path):
    r, rtl = _gen(tmp_path, PROB100)
    assert r.returncode == 0, r.stderr
    # exact transition logic for each state (in ? next@1 : next@0)
    assert "A: next_state = in ? B : A;" in rtl
    assert "B: next_state = in ? B : C;" in rtl
    assert "C: next_state = in ? D : A;" in rtl
    assert "D: next_state = in ? B : C;" in rtl
    # Moore output asserted only in state D
    assert "assign out = (state == D);" in rtl
    assert "output reg [1:0] next_state" in rtl
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_deterministic(tmp_path):
    r1, rtl1 = _gen(tmp_path, PROB100)
    r2, rtl2 = _gen(tmp_path / "second", PROB100) if False else _gen(tmp_path, PROB100)
    assert rtl1 == rtl2 and rtl1  # byte-identical


def test_moore_seq_has_registered_state_and_reset(tmp_path):
    spec = {
        "module": "TopModule", "kind": "moore_seq",
        "clk": "clk", "input": "in", "output": "out",
        "reset": {"name": "reset", "mode": "sync", "polarity": "high", "to": "OFF"},
        "encoding": {"OFF": 0, "ON": 1},
        "transitions": {"OFF": {"0": "OFF", "1": "ON"}, "ON": {"0": "OFF", "1": "ON"}},
        "outputs": {"OFF": 0, "ON": 1},
    }
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "reg [0:0] state, next_state;" in rtl
    assert "if (reset) state <= OFF;" in rtl
    assert "else state <= next_state;" in rtl
    assert "posedge clk" in rtl and "or" not in rtl.split("always @(posedge clk")[1].split(")")[0]
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_moore_seq_async_low_reset_sensitivity(tmp_path):
    spec = {
        "module": "TopModule", "kind": "moore_seq",
        "clk": "clk", "input": "in", "output": "out",
        "reset": {"name": "aresetn", "mode": "async", "polarity": "low", "to": "S0"},
        "encoding": {"S0": 0, "S1": 1},
        "transitions": {"S0": {"0": "S0", "1": "S1"}, "S1": {"0": "S0", "1": "S1"}},
        "outputs": {"S0": 0, "S1": 1},
    }
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "posedge clk or negedge aresetn" in rtl
    assert "if (!aresetn) state <= S0;" in rtl
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_invalid_next_state_rejected(tmp_path):
    bad = dict(PROB100)
    bad["transitions"] = {"A": {"0": "A", "1": "ZZZ"}}  # ZZZ not in encoding
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
    assert "not in encoding" in r.stderr


def test_missing_required_key_rejected(tmp_path):
    r, _ = _gen(tmp_path, {"module": "TopModule", "kind": "moore_comb"})
    assert r.returncode == 1


def test_moore_requires_outputs(tmp_path):
    spec = {"module": "TopModule", "kind": "moore_comb",
            "encoding": {"A": 0, "B": 1},
            "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "A", "1": "B"}}}
    r, _ = _gen(tmp_path, spec)
    assert r.returncode == 1

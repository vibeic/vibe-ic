"""Unit tests for deterministic_rtl_dispatcher.py — Phase-2 program-first router.

Verifies spec-shape classification routes to the right deterministic generator,
that no-match yields the LLM-fallback verdict (exit 3), and that each route
produces compilable RTL.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
SCRIPT = PROGRAMS / "deterministic_rtl_dispatcher.py"
assert SCRIPT.exists()
sys.path.insert(0, str(PROGRAMS))
import deterministic_rtl_dispatcher as disp  # noqa: E402

FSM = {"module": "TopModule", "kind": "moore_comb", "encoding": {"A": 0, "B": 1},
       "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "A", "1": "B"}},
       "outputs": {"A": 0, "B": 1}}
TT = {"module": "TopModule", "inputs": [{"name": "a"}], "outputs": [{"name": "y"}],
      "rows": [{"in": "0", "out": "0"}, {"in": "1", "out": "1"}]}
GATE = {"module": "TopModule", "inputs": ["a", "b"], "outputs": ["y"],
        "gates": [{"op": "and", "out": "y", "in": ["a", "b"]}]}
VEC = {"module": "TopModule", "op": "reverse", "chunk": 1,
       "inputs": [{"name": "in", "width": 4}], "outputs": [{"name": "out", "width": 4}]}


def test_classify_each_class():
    assert disp.classify(FSM) == "fsm_table"
    assert disp.classify(TT) == "truth_table"
    assert disp.classify(GATE) == "gate_netlist"
    assert disp.classify(VEC) == "vector_op"


def test_classify_no_match_returns_none():
    assert disp.classify({"module": "TopModule", "description": "complex datapath"}) is None


def test_forced_generator():
    assert disp.classify({"module": "TopModule", "generator": "gate_netlist",
                          "inputs": ["a"], "outputs": ["y"],
                          "gates": [{"op": "buf", "out": "y", "in": ["a"]}]}) == "gate_netlist"


def test_forced_unknown_generator_raises():
    with pytest.raises(ValueError):
        disp.classify({"module": "TopModule", "generator": "magic"})


def test_dispatch_produces_rtl():
    for spec in (FSM, TT, GATE, VEC):
        name, rtl = disp.dispatch(spec)
        assert name is not None
        assert "module TopModule" in rtl and "endmodule" in rtl


def _run(tmp_path, spec, *extra):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(spec))
    return subprocess.run([sys.executable, str(SCRIPT), str(p), *extra],
                          capture_output=True, text=True)


def test_cli_explain(tmp_path):
    r = _run(tmp_path, GATE, "--explain")
    assert r.returncode == 0
    assert "gate_netlist" in r.stdout


def test_cli_no_match_exit_3(tmp_path):
    r = _run(tmp_path, {"module": "TopModule", "description": "x"})
    assert r.returncode == 3
    assert "fall back to LLM" in r.stderr


def test_cli_generates_and_compiles(tmp_path):
    out = tmp_path / "o.sv"
    p = tmp_path / "s.json"
    p.write_text(json.dumps(VEC))
    r = subprocess.run([sys.executable, str(SCRIPT), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rtl = out.read_text()
    assert "assign out = {in[0], in[1], in[2], in[3]};" in rtl
    if shutil.which("iverilog"):
        c = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b"), str(out)],
                           capture_output=True, text=True)
        assert c.returncode == 0, c.stderr


def test_matched_generator_invalid_spec_exit_1(tmp_path):
    # routes to gate_netlist (has 'gates') but the gate is malformed (undriven output)
    bad = {"module": "TopModule", "inputs": ["a"], "outputs": ["y", "z"],
           "gates": [{"op": "buf", "out": "y", "in": ["a"]}]}
    r = _run(tmp_path, bad)
    assert r.returncode == 1

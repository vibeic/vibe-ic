"""v1.1.41 §4.2 — the sequential-waveform conformance CHECK is now WIRED into
gates_atomic as an emit-block.

Prob098_circuit7 (a single-stage registered inverter `q<=~a`) was shipped WRONG in
the clean-room: a blind author mis-read the TB's first-edge X-window as an extra
pipeline stage (`r<=a; q<=~r`), which self-verifies but FAILs the hidden TB. The
deterministic waveform_table_conformance_check detected this (it replays the
prompt's literal `time clk a q` table) but was never wired into the per-problem
gate, so the wrong sample shipped. It is now wired (rc==1 → emit-BLOCK).

§4.05 no-leak: the check fires ONLY inside its proven-faithful envelope and SKIPs
(rc==0) on every latch / negedge / multi-bit / combinational case, so it cannot
false-block the correct single-stage read (which ships).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
GATES = PLUGIN / "benchmark" / "gates_atomic.py"

_PROMPT = """\
I would like you to implement a module named TopModule.

  input clk,
  input a,
  output reg q

This is a sequential circuit. Read the simulation waveforms.

  time  clk a   q
  0ns   0   1   x
  5ns   1   1   x
  10ns  0   0   x
  15ns  1   0   1
  20ns  0   0   1
  25ns  1   1   0
  30ns  0   1   0
  35ns  1   0   1
  40ns  0   0   1
  45ns  1   1   0
"""
_CORRECT = "module TopModule(input clk, input a, output reg q);\n  always @(posedge clk) q <= ~a;\nendmodule\n"
_WRONG = ("module TopModule(input clk, input a, output reg q);\n"
          "  reg r;\n  always @(posedge clk) begin r <= a; q <= ~r; end\nendmodule\n")


def _stage(tmp, body):
    ds = tmp / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbXX_circuit7_prompt.txt").write_text(_PROMPT)
    wd = tmp / "work" / "ProbXX_circuit7"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "sample.sv").write_text(body)
    (wd / "spec.yaml").write_text(
        "ic_name: TopModule\nclass_path: sequential-logic\n"
        "L1: {ic_name: TopModule, description: x}\nL9: {module_name: TopModule}\n")
    return ds, wd


def _run(tmp, ds):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbXX_circuit7",
         "--workdir", str(tmp / "work"), "--dataset", str(ds),
         "--bench", "verilogeval-human"], capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog absent")
def test_wrong_sequential_waveform_read_is_blocked(tmp_path):
    ds, wd = _stage(tmp_path, _WRONG)
    r = _run(tmp_path, ds)
    gj = json.loads((wd / "gates.json").read_text())
    assert gj["steps"]["waveform_table_conformance"]["verdict"] == "BLOCK"
    rules = [f["rule"] for f in gj["steps"].get("structural_emit_block", {}).get("findings", [])]
    assert "waveform-table-conformance-mismatch" in rules
    assert not (tmp_path / "samples" / "ProbXX_circuit7_sample01.sv").exists()


# §4.05 no-leak: a COMBINATIONAL prompt is OUTSIDE the sequential-replay envelope,
# so the waveform conformance check must SKIP it (it must NEVER block a problem its
# replay cannot faithfully judge). The combinational class is already handled by the
# deterministic synth; the conformance check must not also fire on it.
_COMB_PROMPT = """\
I would like you to implement a module named TopModule.

  input a,
  input b,
  output q

The module should implement a combinational circuit. Read the simulation waveforms.

  time  a  b  q
  0ns   0  0  0
  5ns   0  1  1
  10ns  1  0  1
  15ns  1  1  0
"""


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog absent")
def test_combinational_is_skipped_not_blocked(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "ProbXX_circuit7_prompt.txt").write_text(_COMB_PROMPT)
    wd = tmp_path / "work" / "ProbXX_circuit7"; wd.mkdir(parents=True)
    (wd / "sample.sv").write_text("module TopModule(input a, input b, output q);\n  assign q = a ^ b;\nendmodule\n")
    (wd / "spec.yaml").write_text(
        "ic_name: TopModule\nclass_path: combinational-logic\n"
        "L1: {ic_name: TopModule, description: x}\nL9: {module_name: TopModule}\n")
    _run(tmp_path, ds)
    gj = json.loads((wd / "gates.json").read_text())
    # the sequential-replay check must NOT block a combinational prompt
    rules = [f["rule"] for f in gj["steps"].get("structural_emit_block", {}).get("findings", [])]
    assert "waveform-table-conformance-mismatch" not in rules


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

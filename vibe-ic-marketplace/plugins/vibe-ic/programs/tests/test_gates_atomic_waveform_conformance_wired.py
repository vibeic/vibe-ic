"""v1.1.41 §4.2 — the sequential-waveform conformance CHECK is now WIRED into
gates_atomic as an emit-block.

Prob098_circuit7 (a single-stage registered inverter `q<=~a`) was shipped WRONG in
the clean-room: a blind author mis-read the TB's first-edge X-window as an extra
pipeline stage (`tmp<=a; q<=~tmp`), which self-verifies but FAILs the hidden TB. The
deterministic waveform_table_conformance_check detected this (it replays the
prompt's literal `time clk a q` table the way the official scorer compares) but was
never wired into the per-problem gate, so the wrong sample shipped. It is now wired
(rc==1 → emit-BLOCK).

CONVENTION (critical — the fixture is the REAL prompt, NOT a hand-crafted table):
the official VerilogEval circuitN testbench drives the input via NBA AT the posedge
(`@(posedge clk) a <= $urandom`), so the DUT samples the PRE-edge input and the
published waveform shows the output LAGGING the displayed input by one posedge
(q is X at the first posedge). The real Prob098_circuit7 table below is therefore
NBA-LEAD, and the golden one-stage `q<=~a` reproduces it exactly. (An earlier draft
of this test used a hand-crafted SAME-EDGE table; that misrepresented the real
convention and is replaced here with the verbatim dataset prompt.)

§4.05 no-leak (the dangerous direction for an emit-BLOCK is FALSE-BLOCK): the check
replays the published waveform with the same NBA-at-posedge convention, so on the
REAL prompt the golden single-stage `q<=~a` PASSes and SHIPs (test_correct_*),
the wrong extra-stage pipe BLOCKs (test_wrong_*), and a combinational prompt is
SKIPped (outside the sequential-replay envelope). Verified end-to-end against the
real golden RefModule and the real shipped-wrong sample.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
GATES = PLUGIN / "benchmark" / "gates_atomic.py"

# The REAL VerilogEval Prob098_circuit7 prompt (dataset_spec-to-rtl), verbatim.
# NBA-lead: q lags the displayed a by one posedge; q is X at the first posedge.
_PROMPT = """\
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  a
 - output q

This is a sequential circuit. Read the simulation waveforms to determine
what the circuit does, then implement it.

  time  clk a   q
  0ns   0   x   x
  5ns   1   0   x
  10ns  0   0   x
  15ns  1   0   1
  20ns  0   0   1
  25ns  1   0   1
  30ns  0   0   1
  35ns  1   1   1
  40ns  0   1   1
  45ns  1   1   0
  50ns  0   1   0
  55ns  1   1   0
  60ns  0   1   0
  65ns  1   1   0
  70ns  0   1   0
  75ns  1   1   0
  80ns  0   1   0
  85ns  1   1   0
  90ns  0   1   0

Assume all sequential logic is triggered on the positive edge of the
clock.
"""
# The REAL golden RefModule (one-stage registered inverter).
_CORRECT = "module TopModule(input clk, input a, output reg q);\n  always @(posedge clk) q <= ~a;\nendmodule\n"
# The REAL shipped-wrong sample (phantom extra pipeline stage).
_WRONG = ("module TopModule(input clk, input a, output reg q);\n"
          "  reg tmp;\n  always @(posedge clk) begin tmp <= a; q <= ~tmp; end\nendmodule\n")


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
def test_correct_sequential_waveform_read_is_NOT_blocked(tmp_path):
    # §4.05 FALSE-BLOCK guard (the dangerous direction for an emit-BLOCK gate): the
    # REAL golden one-stage `q<=~a` reproduces the REAL NBA-lead prompt table and
    # must PASS the replay and SHIP — it must NOT be blocked. The absence of this
    # assertion is what let an inverted-convention misread go unnoticed; pinning it
    # against the verbatim dataset prompt makes the no-leak claim concrete.
    ds, wd = _stage(tmp_path, _CORRECT)
    r = _run(tmp_path, ds)
    gj = json.loads((wd / "gates.json").read_text())
    assert gj["steps"]["waveform_table_conformance"]["verdict"] == "PASS_OR_SKIP", \
        gj["steps"].get("waveform_table_conformance")
    assert "WTC_PASS" in gj["steps"]["waveform_table_conformance"]["log"]
    rules = [f["rule"] for f in gj["steps"].get("structural_emit_block", {}).get("findings", [])]
    assert "waveform-table-conformance-mismatch" not in rules
    # the correct sample is EMITTED (not suppressed by a false-block)
    assert (tmp_path / "samples" / "ProbXX_circuit7_sample01.sv").exists()


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog absent")
def test_wrong_sequential_waveform_read_is_auto_corrected(tmp_path):
    # v1.1.76: gates_atomic now delegates deterministic-synth to
    # spec_artifact_registry.generate(), whose `timing_waveform_ext` solver FIRES on
    # this circuit7-style posedge-1FF prompt and EMITS the correct one-stage
    # `q <= ~a` — REPLACING the author's wrong two-stage `q <= ~tmp` read BEFORE the
    # conformance gate runs. The safety invariant "a wrong waveform read never ships"
    # is preserved in its STRONGER form (auto-corrected, not merely blocked); the
    # BLOCK gate remains the guard for the misreads the synth SKIPs. (timing_waveform_ext
    # is host-verified 0-mismatch on the real Prob098_circuit7.)
    ds, wd = _stage(tmp_path, _WRONG)
    r = _run(tmp_path, ds)
    gj = json.loads((wd / "gates.json").read_text())
    # the deterministic solver fired and produced the CORRECT RTL...
    assert gj["steps"]["deterministic_synth"]["applied"] is True
    assert gj["steps"]["deterministic_synth"]["kind"] in ("timing_waveform_ext", "timing_waveform")
    # ...so the wrong authored read never ships — the emitted sample is the correct
    # one-stage `~a`, NOT the wrong two-stage `~tmp`.
    emitted = (tmp_path / "samples" / "ProbXX_circuit7_sample01.sv").read_text()
    assert "~a" in emitted and "tmp" not in emitted
    # the conformance gate now sees correct RTL (no mismatch finding / no block)
    assert gj["steps"]["waveform_table_conformance"]["verdict"] != "BLOCK"
    rules = [f["rule"] for f in gj["steps"].get("structural_emit_block", {}).get("findings", [])]
    assert "waveform-table-conformance-mismatch" not in rules


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

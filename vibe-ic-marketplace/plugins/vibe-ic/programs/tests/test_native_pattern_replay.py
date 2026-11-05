"""Shared native test-pattern replay verdict controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "librelane_plugins"))

from librelane.state import DesignFormat
from librelane.steps.step import StepError
from librelane_plugin_vibeic import TestPatternReplay as PatternReplayStep


def _subject(tmp_path: Path, outcome="pass", stale=False, wrong_netlist=False):
    netlist = tmp_path / "core.v"
    expression = "~a" if wrong_netlist else "a"
    netlist.write_text(f"module core(input a, output y); assign y={expression}; endmodule\n")
    pattern = tmp_path / "case.vec"
    pattern.write_text("00\n11\n")
    marker = ("VIBEIC_PATTERN_REPLAY PASS case_1 2" if outcome == "pass"
              else "VIBEIC_PATTERN_REPLAY FAIL case_1 vector=1")
    tb = tmp_path / "tb.v"
    tb.write_text(f'''module pattern_tb;
reg a; wire y; reg [1:0] vectors [0:1]; integer i;
core dut(.a(a),.y(y));
initial begin
  $readmemb("{pattern}", vectors);
  for (i=0; i<2; i=i+1) begin
    a=vectors[i][1]; #1;
    if (y !== vectors[i][0]) begin
      $display("VIBEIC_PATTERN_REPLAY FAIL case_1 vector=%0d", i);
      $fatal(1, "pattern readback mismatch");
    end
  end
  $display("{marker}"); $finish;
end
endmodule
''')
    digest = hashlib.sha256(pattern.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"compile_flags": "-g2012", "models": [],
        "cases": [{"id": "case_1", "module": "pattern_tb",
                   "testbench": str(tb), "pattern": str(pattern),
                   "pattern_sha256": "0" * 64 if stale else digest,
                   "testbench_sha256": hashlib.sha256(tb.read_bytes()).hexdigest(),
                   "vector_count": 2}]}))
    step_dir = tmp_path / "step"
    instance = SimpleNamespace(id=PatternReplayStep.id,
        config={"VIBEIC_PATTERN_MANIFEST": str(manifest),
                "VIBEIC_PATTERN_TIMEOUT_S": 30},
        step_dir=str(step_dir), _run=PatternReplayStep._run)
    return instance, {DesignFormat.NETLIST: str(netlist)}, step_dir


def test_native_pattern_replay_passes_exact_population(tmp_path):
    instance, state, folder = _subject(tmp_path)
    _, metrics = PatternReplayStep.run(instance, state)
    assert metrics == {"vibeic__pattern_replay__case__count": 1,
                       "vibeic__pattern_replay__vector__count": 2,
                       "vibeic__pattern_replay__passed": 1}
    assert json.loads((folder / "pattern_replay_results.json").read_text())["verdict"] == "PASS"


@pytest.mark.parametrize("outcome,stale", [("fail", False), ("pass", True)])
def test_native_pattern_replay_blocks_bad_result_or_changed_pattern(
        tmp_path, outcome, stale):
    instance, state, folder = _subject(tmp_path, outcome, stale)
    with pytest.raises(StepError, match="BLOCKING pattern replay"):
        PatternReplayStep.run(instance, state)
    assert json.loads((folder / "pattern_replay_results.json").read_text())["verdict"] == "FAIL"


def test_native_pattern_replay_rejects_wrong_implementation(tmp_path):
    instance, state, folder = _subject(tmp_path, wrong_netlist=True)
    with pytest.raises(StepError, match="BLOCKING pattern replay"):
        PatternReplayStep.run(instance, state)
    result = json.loads((folder / "pattern_replay_results.json").read_text())
    assert result["verdict"] == "FAIL"
    assert result["runs"][0]["compile_rc"] == 0
    assert result["runs"][0]["sim_rc"] != 0
    assert result["runs"][0]["marker_count"] == 0


def _timed_subject(tmp_path, *, sdf=None):
    instance, state, folder = _subject(tmp_path)
    netlist = Path(state[DesignFormat.NETLIST])
    netlist.write_text('module core(input a, output y); delay_cell u0(.A(a),.Z(y)); endmodule\n')
    model = tmp_path / 'cells.v'
    model.write_text('''`timescale 1ns/1ps
module delay_cell(input A, output Z);
 buf (Z,A); specify (A=>Z)=(1,1); endspecify
endmodule
''')
    sdf_file = tmp_path / 'core.sdf'
    sdf_file.write_text(sdf if sdf is not None else '''(DELAYFILE
(SDFVERSION "3.0") (DESIGN "core") (DIVIDER /) (TIMESCALE 1ns)
(CELL (CELLTYPE "core") (INSTANCE)
 (DELAY (ABSOLUTE (INTERCONNECT a u0/A (1:1:1)))))
(CELL (CELLTYPE "delay_cell") (INSTANCE u0)
 (DELAY (ABSOLUTE (IOPATH A Z (1:1:1) (1:1:1)))))
)
''')
    path = Path(instance.config['VIBEIC_PATTERN_MANIFEST'])
    manifest = json.loads(path.read_text())
    bench = Path(manifest['cases'][0]['testbench'])
    bench.write_text(bench.read_text().replace('#1;', '#5;'))
    sha = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    manifest.update(compile_flags='-g2012 -ginterconnect -gspecify -Tmax', models=[str(model)],
                    timing={'sdf': str(sdf_file), 'sdf_sha256': sha(sdf_file),
                            'netlist_sha256': sha(netlist), 'model_sha256': {str(model): sha(model)}})
    manifest['cases'][0].update(testbench_sha256=sha(bench), dut_instance='dut')
    path.write_text(json.dumps(manifest))
    return instance, state, folder


def test_timed_pattern_replay_applies_native_delays_and_keeps_exact_population(tmp_path):
    instance, state, folder = _timed_subject(tmp_path)
    _, metrics = PatternReplayStep.run(instance, state)
    assert metrics['vibeic__pattern_replay__passed'] == 1
    run = json.loads((folder / 'pattern_replay_results.json').read_text())['runs'][0]
    assert run['vector_count'] == 2
    import sdf_gate_sim
    census = sdf_gate_sim.sdf_annotation_census(Path(run['stdout']).read_text())
    assert census['delays_applied'] > 0
    assert run['sdf_annotation']['sdf_errors_unexplained'] == 0


@pytest.mark.parametrize('field', ['sdf_sha256', 'netlist_sha256', 'model_sha256'])
def test_timed_pattern_replay_refuses_changed_consumed_identity(tmp_path, field):
    instance, state, folder = _timed_subject(tmp_path)
    path = Path(instance.config['VIBEIC_PATTERN_MANIFEST'])
    manifest = json.loads(path.read_text())
    manifest['timing'][field] = {} if field == 'model_sha256' else '0' * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(StepError):
        PatternReplayStep.run(instance, state)
    result = json.loads((folder / 'pattern_replay_results.json').read_text())
    assert result['verdict'] == 'FAIL'
    assert result['runs'] == []
    assert len(result['export_roundtrip_errors']) > 0


def test_functional_pass_with_zero_applied_sdf_delays_is_not_timed_pass(tmp_path):
    instance, state, folder = _timed_subject(tmp_path, sdf='''(DELAYFILE
(SDFVERSION "3.0") (DESIGN "core") (TIMESCALE 1ns)
(CELL (CELLTYPE "core") (INSTANCE)))
''')
    with pytest.raises(StepError):
        PatternReplayStep.run(instance, state)
    run = json.loads((folder / 'pattern_replay_results.json').read_text())['runs'][0]
    assert run['marker_count'] == 1 and run['sim_rc'] == 0
    assert run['sdf_annotation']['delays_applied'] == 0
    assert run['verdict'] == 'FAIL'


def test_timed_pattern_replay_blocks_an_unexplained_sdf_record(tmp_path):
    instance, state, folder = _timed_subject(tmp_path)
    path = Path(instance.config['VIBEIC_PATTERN_MANIFEST'])
    manifest = json.loads(path.read_text())
    sdf = Path(manifest['timing']['sdf'])
    sdf.write_text(sdf.read_text().replace('a u0/A', 'a nonexistent/A'))
    manifest['timing']['sdf_sha256'] = hashlib.sha256(sdf.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(StepError):
        PatternReplayStep.run(instance, state)
    run = json.loads((folder / 'pattern_replay_results.json').read_text())['runs'][0]
    assert run['sdf_annotation']['sdf_errors_unexplained'] > 0
    assert run['verdict'] == 'FAIL'


def test_fragmented_native_sdf_error_cannot_disappear_from_classification(tmp_path):
    instance, state, folder = _timed_subject(tmp_path)
    native = instance._run
    def corrupt_transcript(argv, log, limit, cwd=None):
        rc = native(argv, log, limit, cwd=cwd)
        if 'vvp' in argv:
            with open(log, 'a') as stream:
                stream.write('\nSDF ERROR: fragmented native source record\n')
        return rc
    instance._run = corrupt_transcript
    with pytest.raises(StepError):
        PatternReplayStep.run(instance, state)
    run = json.loads((folder / 'pattern_replay_results.json').read_text())['runs'][0]
    assert run['sdf_annotation']['unclassified_sdf_errors'] == 1
    assert run['sdf_annotation']['sdf_errors_unexplained'] == 1
    assert run['verdict'] == 'FAIL'

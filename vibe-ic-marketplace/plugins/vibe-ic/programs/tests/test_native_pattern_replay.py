"""Shared native test-pattern replay verdict controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from librelane.state import DesignFormat
from librelane.steps.step import StepError, StepException
from librelane_plugins.librelane_plugin_vibeic import TestPatternReplay as PatternReplayStep


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
        config={"VIBEIC_PATTERN_MANIFEST": str(manifest), "VIBEIC_PATTERN_TIMEOUT_S": 30},
        step_dir=str(step_dir), _run=PatternReplayStep._run)
    return instance, {DesignFormat.NETLIST: str(netlist)}, step_dir


def test_native_pattern_replay_passes_exact_population(tmp_path):
    instance, state, folder = _subject(tmp_path)
    _, metrics = PatternReplayStep.run(instance, state)
    assert metrics == {"vibeic__pattern_replay__case__count": 1,
                       "vibeic__pattern_replay__vector__count": 2,
                       "vibeic__pattern_replay__passed": 1,
                       "final_pattern_good_machine_errors": 0}
    assert json.loads((folder / "pattern_replay_results.json").read_text())["verdict"] == "PASS"


def test_native_pattern_replay_blocks_a_native_failure(tmp_path):
    instance, state, folder = _subject(tmp_path, "fail")
    with pytest.raises(StepError, match="BLOCKING pattern replay"):
        PatternReplayStep.run(instance, state)
    assert json.loads((folder / "pattern_replay_results.json").read_text())["verdict"] == "FAIL"


def test_native_pattern_replay_trusts_the_tool_without_input_hashes(tmp_path):
    instance, state, folder = _subject(tmp_path, stale=True)
    _, metrics = PatternReplayStep.run(instance, state)
    assert metrics["final_pattern_good_machine_errors"] == 0
    assert "export_roundtrip_errors" not in json.loads((folder / "pattern_replay_results.json").read_text())


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
def test_timed_pattern_replay_uses_native_delays_without_identity_hashes(tmp_path, field):
    instance, state, folder = _timed_subject(tmp_path)
    path = Path(instance.config['VIBEIC_PATTERN_MANIFEST'])
    manifest = json.loads(path.read_text())
    manifest['timing'][field] = {} if field == 'model_sha256' else '0' * 64
    path.write_text(json.dumps(manifest))
    _, metrics = PatternReplayStep.run(instance, state)
    assert metrics["final_pattern_good_machine_errors"] == 0
    result = json.loads((folder / 'pattern_replay_results.json').read_text())
    assert result['verdict'] == 'PASS'
    assert len(result['runs']) == 1
    assert 'export_roundtrip_errors' not in result


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
    def corrupt_transcript(argv, log, *args, **kwargs):
        rc = native(argv, log, *args, **kwargs)
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


def test_missing_native_result_counts_are_unmeasured(tmp_path):
    instance, state, folder = _subject(tmp_path)
    manifest = json.loads(Path(instance.config["VIBEIC_PATTERN_MANIFEST"]).read_text())
    bench = Path(manifest["cases"][0]["testbench"])
    bench.write_text(bench.read_text().replace("VIBEIC_PATTERN_REPLAY PASS case_1 2", "Simulation finished"))
    manifest["cases"][0]["testbench_sha256"] = hashlib.sha256(bench.read_bytes()).hexdigest()
    Path(instance.config["VIBEIC_PATTERN_MANIFEST"]).write_text(json.dumps(manifest))
    with pytest.raises(StepException, match="no check counts"):
        PatternReplayStep.run(instance, state)
    assert json.loads((folder / "pattern_replay_results.json").read_text())["verdict"] == "NOT_MEASURED"


def test_native_replay_has_no_clock_cutoff(tmp_path, monkeypatch):
    instance, state, folder = _subject(tmp_path)
    import librelane_plugins.librelane_plugin_vibeic as native

    original = native.subprocess.run
    def run(*args, **kwargs):
        assert "timeout" not in kwargs
        return original(*args, **kwargs)
    monkeypatch.setattr(native.subprocess, "run", run)
    assert PatternReplayStep.run(instance, state)[1]["final_pattern_good_machine_errors"] == 0


@pytest.mark.parametrize("wrong_netlist,expected", [(False, "NOT_MEASURED"), (True, "FAIL")])
def test_selected_pattern_row_uses_native_results_and_keeps_roundtrip_unmeasured(tmp_path, wrong_netlist, expected):
    import flow_engine as engine
    import flow_native_adapters as adapters

    instance, state, folder = _subject(tmp_path, wrong_netlist=wrong_netlist)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"] if row["name"] == "final_test_pattern_replay")
    result = adapters.execute(tmp_path, tmp_path / "row", row["tool"], {},
        state={"nl": state[DesignFormat.NETLIST]}, config=instance.config)
    native = engine.ToolResult(**result)
    assert native.ran
    assert "final_pattern_good_machine_errors" in native.metrics
    assert "export_roundtrip_errors" not in native.metrics
    checks = engine.measure(row["checks"], native.metrics, {}, {"requires_dft": True})
    assert engine.evaluate(native, checks) == expected

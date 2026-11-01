"""Real native launches and per-child accounting without an external time binary."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from _hostpaths import require_repo
import flow109_final_gls as final_gls

sys.path.insert(0, str(final_gls.HERE / 'librelane_plugins'))
from librelane.state import DesignFormat
from librelane_plugin_vibeic import GateLevelSim


def _resources(log):
    values = dict(line.split('=', 1) for line in Path(str(log) + '.resources.txt').read_text().splitlines())
    assert set(values) == {'max_rss_kib', 'user_s', 'system_s', 'elapsed_s'}
    measured = {key: float(value) for key, value in values.items()}
    assert measured['max_rss_kib'] > 0
    assert measured['elapsed_s'] > 0
    assert measured['user_s'] >= 0 and measured['system_s'] >= 0
    return measured


def test_final_gls_launches_without_time_and_keeps_execution_fields(tmp_path, monkeypatch):
    popen = subprocess.Popen
    def without_time(argv, *args, **kwargs):
        if argv[0] == '/usr/bin/time':
            raise FileNotFoundError('external time binary is absent')
        return popen(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', without_time)
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'sdf_top_port_bus')
    bench = tmp_path / 'probe.v'
    bench.write_text('''
`timescale 1ns/1ps
module probe;
  reg a = 0;
  wire [1:0] q;
  wire p;
  top dut(.a(a), .q(q), .p(p));
  initial begin
    $sdf_annotate("@@VIBEIC_SDF_FILE@@", dut);
    #1 a = 1;
    #2;
    if (q[1] !== 1'b1 || p !== 1'b1) $finish_and_return(1);
    $display("GATE_SIM_RESULT PASS 1/1 vectors");
    $finish;
  end
endmodule
''')
    stubs = tmp_path / 'stubs.v'
    stubs.write_text('')
    manifest = {'cases': [{'id': 'probe', 'module': 'probe', 'testbench': str(bench)}],
                'models': [], 'stubs': str(stubs), 'compile_flags': '-g2012 -ginterconnect -gspecify',
                'sdf_placeholder': '@@VIBEIC_SDF_FILE@@', 'not_a_subject': []}
    step = SimpleNamespace(step_dir=str(tmp_path / 'native'),
                           config={'VIBEIC_GLS_MANIFEST': 'selection.json', 'VIBEIC_GLS_TIMEOUT_S': 10},
                           _run=GateLevelSim._run)
    rows = final_gls.run_native_cases(step, {
        DesignFormat.NETLIST: str(fixture / 'top.v'),
        DesignFormat.SDF: {'typ': str(fixture / 'top.sdf')}}, manifest)
    assert len(rows) == 1
    row = rows[0]
    assert (row['compile_rc'], row['sim_rc']) == (0, 0), row
    assert 'GATE_SIM_RESULT PASS 1/1' in Path(row['stdout']).read_text()
    execution = row['execution']
    assert {'started_ns', 'finished_ns', 'argv', 'worker_output'} <= execution.keys()
    assert execution['finished_ns'] > execution['started_ns']
    assert len(execution['argv']) == 2
    for call in execution['argv']:
        assert {'argv', 'executed_argv', 'log', 'cwd', 'resources', 'returncode'} <= call.keys()
        assert call['returncode'] == 0
        assert call['executed_argv'] == call['argv']
        assert call['resources'] == call['log'] + '.resources.txt'
        _resources(call['log'])
    published = json.loads((Path(step.step_dir) / 'gls_runs.json').read_text())
    assert published['runs'] == rows
    assert json.loads((Path(execution['worker_output']) / 'case_execution.json').read_text()) == row


@pytest.mark.parametrize('exit_code,limit', [(0, 10), (7, 10), (124, 0.2)])
def test_native_resources_preserve_exit_timeout_cwd_and_complete_logs(tmp_path, exit_code, limit):
    log = str(tmp_path / 'child.log')
    code = ("import os,sys,time; print(os.getcwd(), flush=True); "
            "print('child diagnostic', file=sys.stderr, flush=True); "
            + ('time.sleep(10)' if exit_code == 124 else f'sys.exit({exit_code})'))
    rc = GateLevelSim._run([sys.executable, '-c', code], log, limit, cwd=str(tmp_path))
    assert rc == exit_code
    text = Path(log).read_text()
    assert str(tmp_path) in text and 'child diagnostic' in text
    assert Path(log + '.stderr').read_text().strip() == 'child diagnostic'
    assert ('VIBEIC_GLS_TIMEOUT' in text) == (exit_code == 124)
    _resources(log)


def test_parallel_resource_records_belong_to_each_child(tmp_path):
    def run(size):
        log = str(tmp_path / f'{size}.log')
        code = ("import json,resource,time; "
                f"data = bytearray({size} * 1024 * 1024); "
                "time.sleep(0.05); "
                "print(json.dumps({'rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))")
        assert GateLevelSim._run([sys.executable, '-c', code], log, 10) == 0
        own_rss = json.loads(Path(log).read_text())['rss']
        if sys.platform == 'darwin':
            own_rss /= 1024
        measured = _resources(log)
        assert own_rss <= measured['max_rss_kib'] <= own_rss + 4096
        return measured
    run(128)  # A previous child's peak must not be attributed to later children.
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(run, [16, 48, 24, 64]))) == 4

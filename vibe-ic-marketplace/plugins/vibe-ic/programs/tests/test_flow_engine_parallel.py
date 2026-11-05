from pathlib import Path
import json
import sys
import time

import pytest

import flow_adapter_jobs
import flow_engine as engine


WORKER = '''
from pathlib import Path
import pickle, sys, time
payload = pickle.load(sys.stdin.buffer)
project, tool = Path(payload['project']), payload['tool']
(project / 'check.started').touch()
started = time.perf_counter()
if tool.get('hold'):
    while not (project / 'export.done').exists():
        if time.perf_counter() - started > 8:
            raise RuntimeError('physical/export chain did not advance')
        time.sleep(0.01)
    assert not (project / 'steps/summary/result.json').exists()
code = tool.get('native_exit', 0)
native = {'ran': True, 'exit_code': code,
          'metrics': {'errors': tool.get('errors', 0), 'value': tool.get('value', 0)},
          'native_steps': [{'name': 'controlled native check', 'ran': True,
                           'status': 'FAIL' if code else 'PASS', 'exit_code': code}],
          'tool_seconds': time.perf_counter() - started}
with Path(sys.argv[1]).open('wb') as stream:
    pickle.dump({'native': native}, stream)
'''


@pytest.fixture
def worker(tmp_path, monkeypatch):
    script = tmp_path / 'controlled-worker.py'
    script.write_text(WORKER)
    monkeypatch.setattr(flow_adapter_jobs, '_worker_command', lambda output: [
        sys.executable, str(script), str(output)])


def row(name, tool, checks=None):
    return {'name': name, 'title': name, 'when': 'always', 'legacy_id': {}, 'tool': tool,
            'checks': checks if checks is not None else [{'metric': 'errors', 'operator': '<=', 'limit': 0}]}


def command(name, marker=None, wait=False):
    script = "import json,pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
    if wait:
        script += "deadline=time.monotonic()+8\nwhile not (p/'check.started').exists():\n assert time.monotonic()<deadline\n time.sleep(0.01)\n"
    if marker:
        script += f"(p/{marker!r}).touch()\n"
    script += "pathlib.Path(sys.argv[2]).write_text(json.dumps({'errors':0}))"
    return row(name, {'kind': 'command', 'command': [sys.executable, '-c', script,
                                                    '{project}', '{step}/metrics.json']})


def run(project, rows):
    route = {'entry_step': rows[0]['name'], 'verify_through': rows[-1]['name'],
             'delivery_target': 'rtl', 'input_contract': 'structured'}
    return engine.run(project, table={'steps': rows}, route=route)


@pytest.mark.parametrize('name', [
    'netlist_equivalence', 'final_adopted_netlist_equivalence', 'functional_activity_and_external_loads',
    'analog_pre_layout_nominal_performance', 'analog_pre_layout_pvt_and_operating_range',
    'analog_pre_layout_statistics', 'calibration_algorithm_verification',
    'analog_post_layout_performance', 'analog_post_layout_statistics',
    'pre_layout_mixed_signal_verification', 'candidate_mixed_signal_scenarios',
    'final_geometry_mixed_signal_scenarios',
])
def test_actual_background_tools_leave_physical_export_free(tmp_path, worker, name):
    source = next(item for item in engine.read_json(engine.TABLE)['steps'] if item['name'] == name)
    tool = {**source['tool'], 'hold': True}
    report = run(tmp_path, [row(name, tool), command('physical', 'physical.done', wait=True),
                            command('export', 'export.done')])
    assert report['pass'] == 3
    proof = report['steps'][0]
    assert (tmp_path / 'export.done').exists()


@pytest.mark.parametrize('code,check_status,aggregate_status', [(0, 'PASS', 'PASS'), (3, 'FAIL', 'FAIL')])
def test_blocked_check_does_not_delay_physical_export_and_aggregate_waits(
        tmp_path, worker, code, check_status, aggregate_status):
    check = row('check', {'kind': 'adapter', 'adapter': 'formal', 'parallel': True,
                          'hold': True, 'native_exit': code})
    aggregate = row('summary', {'kind': 'aggregate'}, [
        {'metric': 'non_passing_steps', 'operator': '==', 'limit': 0}])
    rows = [check, command('physical', 'physical.done', wait=True), aggregate,
            command('export', 'export.done')]
    report = run(tmp_path, rows)
    assert [item['name'] for item in report['steps']] == [item['name'] for item in rows]
    actual = {item['name']: item for item in report['steps']}
    assert actual['check']['status'] == check_status
    assert actual['physical']['status'] == actual['export']['status'] == 'PASS'
    assert actual['summary']['status'] == aggregate_status
    assert report['pending_steps'] == []
    assert report['background_pending'] == []


def test_report_waits_for_its_later_selected_native_producer(tmp_path):
    report_row = row('reader', {'kind': 'native_report', 'from': 'producer'})
    result = run(tmp_path, [report_row, command('producer')])
    assert [item['status'] for item in result['steps']] == ['PASS', 'PASS']
    assert result['steps'][0]['native_metrics'] == {'errors': 0}


def test_async_result_uses_its_captured_limit_after_parent_config_advances(tmp_path, worker, monkeypatch):
    def execute(chain, directory, tool):
        directory.mkdir(parents=True, exist_ok=True)
        if tool['steps'] == ['prepare']:
            chain.config = {'LIMIT': 10}
            chain.common_started = time.perf_counter()
        else:
            chain.config['LIMIT'] = 20
        return engine.ToolResult(True, 0, {'errors': 0})
    monkeypatch.setattr(engine.NativeChain, 'execute', execute)
    check = row('check', {'kind': 'adapter', 'adapter': 'formal', 'parallel': True, 'value': 15}, [
        {'metric': 'value', 'operator': '<=', 'limit_config': 'LIMIT'}])
    report = run(tmp_path, [row('prepare', {'kind': 'librelane', 'steps': ['prepare']}), check,
                            row('advance', {'kind': 'librelane', 'steps': ['advance']})])
    assert report['steps'][1]['status'] == 'FAIL'
    assert report['steps'][1]['metrics'][0]['limit'] == 10


def test_failure_after_retained_native_row_cancels_the_check_lane(tmp_path, worker, monkeypatch):
    cancellations = []
    original = engine.AdapterJobs

    class RecordingJobs(original):
        def close(self, cancel=False):
            cancellations.append(cancel)
            super().close(cancel=cancel)

    monkeypatch.setattr(engine, 'AdapterJobs', RecordingJobs)
    monkeypatch.setattr(engine.NativeChain, 'prepare', lambda chain: None)
    monkeypatch.setattr(engine.NativeChain, 'restore', lambda chain, directory: None)

    def fail(*args):
        raise RuntimeError('controlled parent failure')

    monkeypatch.setattr(engine, 'command_tool', fail)
    native_dir = tmp_path / 'steps/native'
    native_dir.mkdir(parents=True)
    engine.write_json(native_dir / 'result.json', {
        'status': 'PASS', 'tool_ran': True, 'tool_exit_code': 0,
        'native_metrics': {'errors': 0}, 'native_steps': [
            {'name': 'kept', 'ran': True, 'status': 'PASS', 'exit_code': 0}],
        'tool_seconds': 0.01, 'program_seconds': 0.01, 'wall_seconds': 0.02})
    rows = [row('check', {'kind': 'adapter', 'adapter': 'formal', 'parallel': True, 'hold': True}),
            row('native', {'kind': 'librelane', 'steps': ['kept']}), command('abort')]
    with pytest.raises(RuntimeError, match='controlled parent failure'):
        run(tmp_path, rows)
    assert cancellations == [True]

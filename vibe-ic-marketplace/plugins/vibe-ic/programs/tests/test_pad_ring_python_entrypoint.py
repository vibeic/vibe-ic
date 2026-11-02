"""SOURCE_ONLY actual producer argv and refusals; no native/row PASS credit.

The process edge deliberately returns failure without executing any EDA tool.
The unchanged emitted OpenDB script/request still need actual wheel proof.
"""
import hashlib
import json
from pathlib import Path
import shlex
import sys

import pytest

import analog_hardmacro_gds_emit as staging
import flow109_admission
import librelane_contract
import pad_ring_gen as owner
import pad_ring_check


@pytest.fixture
def source_case(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    floorplan, assignment = project / 'source.def', project / 'assignment.json'
    floorplan.write_text('source-only input; not a native DEF\n')
    assignment.write_text('{}\n')
    data = {'floorplan': str(floorplan), 'assignment': str(assignment),
            'pdk_root': str(project), 'pdk': 'neutral', 'io_lefs': [],
            'lefs': [], 'inputs': {str(floorplan): hashlib.sha256(floorplan.read_bytes()).hexdigest()}}
    calls = []
    monkeypatch.setattr(owner, '_d32_inputs', lambda _: data)
    monkeypatch.setattr(flow109_admission, 'require_launch_admission', lambda *a: {})
    monkeypatch.setattr(librelane_contract, 'local_image_attestation',
                        lambda: {'scope': 'SOURCE_ONLY_IDENTITY_EDGE'})

    def placement(args):
        report = Path(args[0]) / owner.PR.REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'verdict': 'PASS'}))
        return 0
    monkeypatch.setattr(owner, 'main', placement)
    monkeypatch.setattr(pad_ring_check, 'main', lambda _: 0)
    executable = project / 'unused-tool'
    executable.write_text('source-only identity bytes; never executed\n')
    monkeypatch.setattr(__import__('shutil'), 'which', lambda _: str(executable))

    def refused(stage, command, **kwargs):
        calls.append(shlex.split(command))
        return 23, '', 'SOURCE_ONLY_PROCESS_REFUSAL'
    monkeypatch.setattr(staging.Stage, 'sh', refused)
    return project, data, calls


def invoke(project):
    context = {'requested_step': 'D32', 'native_step_id': 'flow109.D32',
               'resolved_row': {'profile': {'id': 'analog_die'}}}
    return owner.execute(project, context)


def test_actual_producer_uses_shared_python_and_records_the_executed_tool(source_case):
    project, _, calls = source_case
    result = invoke(project)
    assert len(calls) == 1
    attempt = next((project / 'reports/flow109/D32').iterdir())
    assert calls[0] == [sys.executable, str(attempt / 'read_db.py'), str(attempt / 'db-request.json')]
    assert set(result['tools']) == {'python3', 'klayout'}
    assert result['tools']['python3'] == {
        'path': sys.executable,
        'sha256': hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
    }
    assert result['executions'][0]['argv'] == calls[0]
    assert result['executions'][0]['returncode'] == 23
    assert (attempt / 'read_db.py').read_text() == owner._D32_DB_READ
    assert json.loads((attempt / 'db-request.json').read_text()) == {
        'lefs': [], 'def': str(attempt / 'case' / owner.PR.PADRING_DEF_REL),
        'odb': str(attempt / 'padring.odb'), 'out': str(attempt / 'native_db.json'),
    }
    assert result['native_started'] is True
    assert result['component_status'] == result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False and result['delivery_accepted'] is False
    assert result['qualification'] == 'NOT_CLAIMED'
    assert result['reason'] == 'D32_NATIVE_READBACK_FAILED: OpenDB'


def test_independent_reread_uses_recorded_python_without_legacy_cli_flags(source_case):
    project, data, calls = source_case
    work = project / 'prior-output'
    work.mkdir()
    (work / 'gds-request.json').write_text('{"masters": []}')
    data['gds'] = []
    # Both keys let the same value-based test execute on the old source;
    # this dictionary is not serialized or accepted as a native receipt.
    tools = {'python3': {'path': sys.executable},
             'openroad': {'path': '/source-only/legacy-openroad'},
             'klayout': {'path': '/source-only/klayout'}}
    with pytest.raises(ValueError, match='D32_METRIC_NATIVE_READBACK_FAILED: OpenDB'):
        owner._d32_metric_readback(project, data, work, tools)
    target = next((project / 'reports/flow109/D32_metric_readback').iterdir())
    assert calls == [[sys.executable, str(target / 'read_db.py'), str(target / 'db-request.json')]]
    assert (target / 'read_db.py').read_text() == owner._D32_DB_READ


def test_stale_inputs_refuse_before_shared_python_is_started(source_case, monkeypatch):
    project, _, calls = source_case
    def stale(_):
        raise ValueError('D32_SELECTED_PDK_VIEW_STALE: IO LEF')
    monkeypatch.setattr(owner, '_d32_inputs', stale)
    result = invoke(project)
    assert calls == [] and result['native_started'] is False
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D32_SELECTED_PDK_VIEW_STALE: IO LEF'
    assert result['completed'] is False and result['delivery_accepted'] is False

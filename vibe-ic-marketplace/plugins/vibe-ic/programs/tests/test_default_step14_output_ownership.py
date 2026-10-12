"""The handoff checker owns its reports, while synthesis owns its netlist."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _flow_yaml
import execution_backend_gates as gates
import execution_policy as policy
import flow_compliance_check as compliance
import flow_declared_producer_run as producers
import step_preflight as preflight
import test_matrix_d5_deps_correct as dependencies
from test_step9_step14_read_the_pnr_netlist import _project, _mapped


REPORTS = [
    'reports/phase2/gates/yosys_hilomap.json',
    'reports/phase2/gates/yosys_script_template.json',
    'reports/phase2/gates/yosys_tiecell_recipe_order.json',
]


def handoff():
    return next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '14')


def test_post_dft_has_no_forward_dependency_on_the_handoff_checker():
    graph = dependencies.derived_dependencies('12')
    assert not any(producer == '14' for producer, _, _ in graph), graph
    assert any(producer == '9' for producer, _, _ in graph), graph


@pytest.mark.parametrize('target', REPORTS)
def test_current_handoff_produces_its_own_report_on_first_execution(tmp_path, target):
    project = _project(tmp_path, mapped_text=_mapped())
    record = producers.run_for_step(project, '14', timeout=30)
    assert (project / target).is_file(), record
    report = json.loads((project / target).read_text())
    assert report, 'the checker must write a substantive report'
    assert target in handoff()['required_outputs']
    assert any(row['target'] == target and row['executed'] for row in record['results'])


def test_retained_handoff_keeps_the_previous_synthesis_input(tmp_path, monkeypatch):
    project = _project(tmp_path, mapped_text=_mapped())
    netlist = project / 'phase2/stage2/synth/netlist.v'
    original = netlist.read_bytes()
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(gates, 'contracts', lambda *a: {'control_fixture': {}})
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'PASS', 'ledger': [], 'step': {'id': '14', 'status': 'PASS'}})
    def check(project):
        assert netlist.read_bytes() == original
        return SimpleNamespace(name='handoff', status='PASS', detail='control checker', extras={})
    preflight.retained_call(project, '14', check, project, canonical_acceptance=True)
    assert netlist.read_bytes() == original


def test_handoff_cannot_accept_reports_without_its_synthesis_input(tmp_path):
    project = _project(tmp_path, mapped_text=_mapped())
    for relative in REPORTS + ['reports/analog/stage_analog_compliance.json']:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"verdict":"PASS"}')
    (project / 'phase2/stage2/synth/netlist.v').unlink()
    result = compliance.check_step(project, handoff(), {}, skip_analog=True)
    assert result.status != 'PASS', result

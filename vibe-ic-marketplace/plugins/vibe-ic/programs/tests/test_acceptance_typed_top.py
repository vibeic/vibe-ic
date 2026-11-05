import json
import subprocess
import sys

import pytest
import yaml

import flow_artifact_paths as paths
import flow_compliance_check as fcc
import phase23_completion_self_audit_check as phase23


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    gds = root / 'phase3/stage4/gds'
    gds.mkdir(parents=True)
    (gds / 'logical.gds').write_text('logical output fixture\n')
    (gds / 'physical_cell.gds').write_text('foreign output fixture\n')
    flow = tmp_path / 'flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [{
        'id': 37, 'name': 'Output selection', 'stage': 'stage4',
        'required_outputs': [paths.GDS_SPEC],
        'gate': {'files_exist': [paths.GDS_SPEC]},
    }]}))
    return root


def _config(project, value):
    target = project / 'phase3/librelane/synthesis_resolved.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value))
    return target


def _audit(project, *extra):
    report = project.parent / 'audit.json'
    report.unlink(missing_ok=True)
    result = subprocess.run([
        sys.executable, fcc.__file__, str(project), '--strict',
        '--flow-def', str(project.parent / 'flow.yaml'),
        '--json', str(report), *extra,
    ], capture_output=True, text=True)
    return result, json.loads(report.read_text()) if report.exists() else None


def test_topless_cli_selects_typed_logical_output(project):
    _config(project, {'DESIGN_NAME': 'logical', 'meta': {'step': 'Yosys.Synthesis'}})
    final = project / 'phase3/librelane/37-default-stream/01-klayout-streamout'
    final.mkdir(parents=True)
    (final / 'config.json').write_text(json.dumps({'DESIGN_NAME': 'physical_cell'}))
    (final / 'state_out.json').write_text(json.dumps({'gds': 'physical_cell.gds'}))

    result, report = _audit(project)

    assert result.returncode == 0, result.stdout + result.stderr
    row = report['steps'][0]
    assert row['status'] == 'PASS'
    assert row['evidence'] == ['phase3/stage4/gds/logical.gds']


def test_final_physical_config_and_sibling_do_not_supply_logical_top(project):
    (project / 'config.json').write_text(json.dumps({'DESIGN_NAME': 'physical_cell'}))
    (project / 'state_out.json').write_text(json.dumps({'gds': 'physical_cell.gds'}))

    result, report = _audit(project)

    assert result.returncode == 1
    row = report['steps'][0]
    assert row['status'] == 'NOT_MEASURED'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in row['reasons'])
    assert row['evidence'] == []
    assert 'Traceback' not in result.stderr


def test_missing_logical_output_cannot_credit_physical_sibling(project):
    _config(project, {'DESIGN_NAME': 'logical'})
    (project / 'phase3/stage4/gds/logical.gds').unlink()

    result, report = _audit(project)

    assert result.returncode == 1
    row = report['steps'][0]
    assert row['status'] == 'FAIL'
    assert row['evidence'] == []
    assert not any('OUTPUT_TOP_UNBOUND' in reason for reason in row['reasons'])


@pytest.mark.parametrize('config', [[], {}, {'DESIGN_NAME': None},
                                   {'DESIGN_NAME': '../physical_cell'},
                                   {'DESIGN_NAME': ['logical']},
                                   {'DESIGN_NAME': '*'}])
def test_invalid_typed_config_refuses_by_name(project, config):
    _config(project, config)

    result, report = _audit(project)

    assert result.returncode == 1
    assert report['steps'][0]['status'] == 'NOT_MEASURED'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in report['steps'][0]['reasons'])
    assert report['steps'][0]['evidence'] == []
    assert 'Traceback' not in result.stderr
    with pytest.raises(paths.OutputTopUnbound, match='synthesis_resolved.json'):
        paths.acceptance_parameters(project)


def test_unreadable_typed_config_refuses_by_name(project):
    _config(project, {}).write_text('{')

    result, report = _audit(project)

    assert result.returncode == 1
    assert report['steps'][0]['status'] == 'NOT_MEASURED'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in report['steps'][0]['reasons'])
    assert report['steps'][0]['evidence'] == []
    assert 'Traceback' not in result.stderr
    with pytest.raises(paths.OutputTopUnbound, match='synthesis_resolved.json'):
        paths.acceptance_parameters(project)


@pytest.mark.parametrize('stage', ['stage_phase1', 'stage2'])
@pytest.mark.parametrize('config', ['{}', '{', '{"DESIGN_NAME": "../physical_cell"}'])
def test_invalid_config_refuses_only_the_selected_gds_row(project, stage, config):
    flow_path = project.parent / 'flow.yaml'
    flow = yaml.safe_load(flow_path.read_text())
    flow['steps'].append({
        'id': 38, 'name': 'Unrelated output', 'stage': stage,
        'required_outputs': ['input.txt'], 'gate': {'files_exist': ['input.txt']},
    })
    flow_path.write_text(yaml.safe_dump(flow))
    (project / 'input.txt').write_text('unrelated stage output\n')

    absent, absent_report = _audit(project, '--stage-id', stage)
    _config(project, {}).write_text(config)
    invalid, invalid_report = _audit(project, '--stage-id', stage)

    assert absent.returncode == invalid.returncode == 0, invalid.stdout + invalid.stderr
    assert invalid_report['steps'] == absent_report['steps']
    assert len(invalid_report['steps']) == 1
    row = invalid_report['steps'][0]
    assert str(row['id']) == '38'
    assert row['status'] == 'PASS'
    assert row['evidence'] == ['input.txt']
    assert 'OUTPUT_TOP_UNBOUND' not in invalid.stdout + invalid.stderr

    result, report = _audit(project, '--stage-id', 'stage4')
    assert result.returncode == 1
    assert len(report['steps']) == 1
    row = report['steps'][0]
    assert str(row['id']) == '37'
    assert row['status'] == 'NOT_MEASURED'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in row['reasons'])
    assert row['evidence'] == []


def test_explicit_top_precedes_retained_config(project):
    _config(project, {'DESIGN_NAME': 'physical_cell'})

    result, report = _audit(project, '--top', 'logical')

    assert result.returncode == 0, result.stdout + result.stderr
    assert report['steps'][0]['evidence'] == ['phase3/stage4/gds/logical.gds']












@pytest.mark.parametrize('top', [None, 'logical'])
def test_phase23_uses_same_typed_resolution(project, monkeypatch, capsys, top):
    _config(project, {'DESIGN_NAME': 'logical' if top is None else 'physical_cell'})
    run = subprocess.run
    commands = []

    def run_fixture_flow(command, **kwargs):
        commands.append(command)
        return run(command + ['--flow-def', str(project.parent / 'flow.yaml')], **kwargs)

    monkeypatch.setattr(phase23.subprocess, 'run', run_fixture_flow)
    argv = [phase23.__file__, str(project), '--json']
    if top is not None:
        argv += ['--top', top]
    monkeypatch.setattr(sys, 'argv', argv)

    assert phase23.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['summary']['overall'] == 'PASS'
    assert report['summary']['certified'] is True
    if top is not None:
        assert commands[0][-2:] == ['--top', top]

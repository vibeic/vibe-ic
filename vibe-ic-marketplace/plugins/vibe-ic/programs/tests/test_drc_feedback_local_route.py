"""The feedback producer must work when the runner is inside its EDA image."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import drc_feedback_repair as feedback


IMAGE = 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'a' * 64


def test_local_image_resolution_uses_the_digest_bound_runner(monkeypatch):
    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', IMAGE)

    def no_docker(*_args, **_kwargs):
        raise AssertionError('local image resolution must not inspect docker')

    monkeypatch.setattr(feedback.subprocess, 'run', no_docker)
    assert feedback.image_for_container('outer-container') == IMAGE


def test_local_image_resolution_leaves_invalid_identity_for_run_refusal(monkeypatch):
    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', 'ghcr.io/vibeic/vibeic-eda:latest')
    assert feedback.image_for_container('outer-container') == 'FEEDBACK_IMAGE_UNBOUND'


def test_feedback_docker_localises_private_program_mount(monkeypatch, tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    seen = {}

    def fake_run(argv, *, cwd, env, capture_output, text, check):
        seen.update(argv=argv, cwd=cwd, env=env,
                    capture_output=capture_output, text=text, check=check)
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(feedback.subprocess, 'run', fake_run)
    result = feedback._docker(
        IMAGE, project,
        ['openroad', '-exit', '/feedback_programs/feedback.tcl'],
        env={'SCRIPT': '/feedback_programs/feedback.tcl'})

    assert result.returncode == 0
    assert seen['argv'][0] == 'openroad'
    assert 'docker' not in seen['argv']
    assert seen['argv'][-1] == str(Path(feedback._HERE) / 'feedback.tcl')
    assert seen['cwd'] == str(project.resolve())
    assert seen['env']['SCRIPT'] == str(Path(feedback._HERE) / 'feedback.tcl')
    assert seen['capture_output'] is True and seen['text'] is True
    assert seen['check'] is False


def test_feedback_docker_keeps_container_route_argv(monkeypatch, tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: False)
    monkeypatch.setattr(feedback, 'docker_memory_flags', lambda: [])
    monkeypatch.setattr(feedback.subprocess, 'run', fake_run)
    feedback._docker(IMAGE, project, ['openroad', '-exit', '/feedback_programs/x.tcl'])

    assert seen['argv'][:3] == ['docker', 'run', '--rm']
    assert seen['argv'][-5:] == [IMAGE, '--skip', 'openroad', '-exit', '/feedback_programs/x.tcl']
    assert seen['kwargs'] == {'capture_output': True, 'text': True, 'check': False}


def test_run_accepts_repository_digest_without_writing_the_routed_layout(
        monkeypatch, tmp_path):
    project = tmp_path / 'project'
    pnr = project / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (project / 'reports/phase3').mkdir(parents=True)
    source = pnr / 'unit.def'
    source.write_text('DESIGN unit ;\n')
    routed = pnr / 'routed.def'
    routed.write_bytes(source.read_bytes())
    before = routed.read_bytes()
    (pnr / 'stream_out.py').write_text('print("EDA stream")\n')
    rule = {
        'id': 'CO.6a', 'source': 'test', 'reason': 'test',
        'obstruction_half_widths_um': [0.1],
    }
    monkeypatch.setattr(feedback, '_rules', lambda _deck: [rule])
    monkeypatch.setattr(
        feedback, '_antenna_baseline',
        lambda *_args: (_ for _ in ()).throw(ValueError('stop after image binding')))
    pdk = SimpleNamespace(
        drc_deck='/pdk/contact.drc', tech_lef='/pdk/tech.lef',
        cell_lef='/pdk/cell.lef', macro_lefs=[], cell_gds='/pdk/cell.gds',
        macro_gds=[], lefdef_layermap='/pdk/map')
    result = feedback.run(project, 'unit', pdk, IMAGE, publish=False)
    assert result['reason'] == 'stop after image binding'
    assert routed.read_bytes() == before


@pytest.mark.parametrize('container', [
    'outer-container',
    'sha256:' + 'a' * 64,
])
def test_run_records_missing_local_image_digest_without_layout_mutation(
        monkeypatch, tmp_path, container):
    project = tmp_path / 'project'
    pnr = project / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (project / 'reports/phase3').mkdir(parents=True)
    source = pnr / 'unit.def'
    source.write_text('DESIGN unit ;\n')
    routed = pnr / 'routed.def'
    routed.write_bytes(source.read_bytes())
    before = routed.read_bytes()
    (pnr / 'stream_out.py').write_text('print("EDA stream")\n')
    monkeypatch.setattr(feedback, '_rules', lambda _deck: [{
        'id': 'CO.6a', 'source': 'test', 'reason': 'test',
        'obstruction_half_widths_um': [0.1],
    }])
    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.delenv('VIBEIC_EDA_IMAGE', raising=False)
    monkeypatch.delenv('IIC_EDA_IMAGE', raising=False)
    tool_calls = []
    def no_tool(*_args, **_kwargs):
        tool_calls.append(True)
        raise AssertionError('unbound local image must not invoke an EDA tool')
    monkeypatch.setattr(feedback, '_docker', no_tool)
    pdk = SimpleNamespace(
        drc_deck='/pdk/contact.drc', tech_lef='/pdk/tech.lef',
        cell_lef='/pdk/cell.lef', macro_lefs=[], cell_gds='/pdk/cell.gds',
        macro_gds=[], lefdef_layermap='/pdk/map')
    image = feedback.image_for_container(container)
    result = feedback.run(project, 'unit', pdk, image, publish=False)
    assert result['status'] == 'REFUSED'
    assert result['reason'] == 'FEEDBACK_IMAGE_DIGEST_REQUIRED'
    assert routed.read_bytes() == before
    assert tool_calls == []
    receipt = project / 'reports/phase3/drc_feedback.json'
    assert receipt.is_file()
    assert 'FEEDBACK_IMAGE_DIGEST_REQUIRED' in receipt.read_text()



def test_verify_streamed_refuses_unbound_image_before_any_tool(
        monkeypatch, tmp_path):
    project = tmp_path / 'project'
    pnr = project / 'phase3/stage3/pnr'
    report = project / 'reports/phase3'
    pnr.mkdir(parents=True)
    report.mkdir(parents=True)
    source = pnr / 'unit.def'
    source.write_text('DESIGN unit ;\n')
    routed = pnr / 'routed.def'
    routed.write_bytes(source.read_bytes())
    gds = pnr / 'unit.gds'
    gds.write_bytes(b'GDS')
    (report / 'drc_feedback.json').write_text(
        __import__('json').dumps({
            'status': 'PASS', 'source_sha256': feedback._sha(source),
        }) + '\n')
    rule = {
        'id': 'CO.6a', 'source': 'test', 'reason': 'test',
        'obstruction_half_widths_um': [0.1],
    }
    monkeypatch.setattr(feedback, '_rules', lambda _deck: [rule])
    tool_calls = []
    def no_tool(*_args, **_kwargs):
        tool_calls.append(True)
        raise AssertionError('unbound image must not reach finished-layout measurement')
    monkeypatch.setattr(feedback, '_measure', no_tool)
    pdk = SimpleNamespace(drc_deck='/pdk/contact.drc')
    result = feedback.verify_streamed(
        project, 'unit', pdk, 'FEEDBACK_IMAGE_UNBOUND', gds)
    assert result['finished_status'] == 'REFUSED'
    assert result['finished_reason'] == 'FEEDBACK_IMAGE_DIGEST_REQUIRED'
    assert tool_calls == []
    receipt = __import__('json').loads(
        (report / 'drc_feedback.json').read_text())
    assert receipt['finished_status'] == 'REFUSED'



def test_local_publication_declares_local_execution_route(monkeypatch, tmp_path):
    project = tmp_path / 'project'
    output = project / 'phase3/stage3/pnr/routed.def'
    output.parent.mkdir(parents=True)
    output.write_text('DESIGN unit ;\n')
    (project / 'reports/phase3').mkdir(parents=True)
    (project / 'provenance.jsonl').write_text('')
    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    record = {
        'source_def': str(output),
        'publication': {
            'output': str(output),
            'replaced': [str(output)],
            'from_sha256': 'b' * 64,
        },
    }
    row = feedback.declare_publication(project, record, IMAGE, 'openroad local')
    assert row['exec_route'] == 'local'
    assert 'local execution' in row['version_capture']
    assert 'digest-bound' in row['version_capture']
    ledger_row = __import__('json').loads(
        (project / 'provenance.jsonl').read_text())
    assert ledger_row['exec_route'] == 'local'

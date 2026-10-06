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


def test_local_image_resolution_refuses_an_unpinned_runner(monkeypatch):
    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', 'ghcr.io/vibeic/vibeic-eda:latest')
    with pytest.raises(RuntimeError, match='FEEDBACK_IMAGE_UNBOUND'):
        feedback.image_for_container('outer-container')


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

"""Source-bound A06/A07 studies select LOCAL startup without a container alias."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import analog_native_flow as native
import analog_incremental_capture as incremental
import librelane_contract as contract
from test_a05_native_model_loading import case


@pytest.mark.parametrize(('step', 'program', 'arguments'), [
    ('A06', '@ngspice', ['-b', 'study.sp']),
    ('A07', '@ngspice', ['-b', 'study.sp']),
    (None, '@env', ['OMP_NUM_THREADS=1', 'ngspice', '-b', 'study.sp']),
])
def test_local_measurement_command_consumes_selected_startup(case, monkeypatch, step, program, arguments):
    project, directory, init, args = case
    observed = []
    def command(argv, **kwargs):
        observed.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', command)
    result = native.NativeCommands(project, directory, '', args.image, step=step)(program, arguments, cwd=directory)
    assert observed[0].get('SPICE_USERINIT_DIR') == str(init.parent)
    assert result['returncode'] == 0
    assert result['native_init']['sha256'] == native._sha(init)


def test_env_other_command_does_not_gain_ngspice_startup(case, monkeypatch):
    project, directory, init, args = case
    seen = []
    def command(argv, **kwargs):
        seen.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', command)
    native.NativeCommands(project, directory, '', args.image)(
        '@env', ['LABEL=ngspice', 'echo', 'ngspice'], cwd=directory)
    assert seen[0].get('SPICE_USERINIT_DIR') is None


@pytest.fixture
def method(tmp_path):
    raw = os.environ.get('A05_PATH_CONTROL_PROJECT')
    if not raw:
        pytest.skip('requires exact prepared source-bound method inputs')
    source = Path(raw)
    project = tmp_path / 'project'
    for relative in ['phase3/analog/delta_sigma/spec.json',
                     'phase3/analog/delta_sigma/topology.json',
                     'phase3/analog/delta_sigma/delta_sigma.sp',
                     'phase3/analog/delta_sigma/tb_delta_sigma.sp',
                     'input/measurement_methods/delta_sigma/incremental_settings.json']:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    entry = {'kind': 'incremental_capture',
             'settings': 'input/measurement_methods/delta_sigma/incremental_settings.json',
             'result': 'reports/coherent/score.json', 'cpus': 1, 'workers': 1}
    return project, entry


def test_normal_incremental_local_selection_reaches_control_reader(method):
    project, entry = method
    calls = []
    def run(program, argv):
        calls.append((program, argv))
        return {'returncode': 2, 'stdout': '', 'stderr': ''}
    result = incremental.consume_study(project, 'delta_sigma', entry,
        {'container': '', 'image': os.environ['VIBEIC_EDA_IMAGE'], 'cpus': 1, 'workers': 1}, run, 'A06')
    assert result['detail'] == 'first native reset conversion has not completed'
    assert result['status'] == 'NOT_MEASURED'
    assert len(calls) == 1 and calls[0][0] == 'analog_incremental_capture.py'
    assert calls[0][1][-2:] == ['--limit-points', '1']


def test_unattested_local_incremental_cannot_launch(method, monkeypatch):
    project, entry = method
    monkeypatch.delenv(contract.LOCAL_ATTESTATION_ENV)
    calls = []
    def run(*args):
        calls.append(args)
        return {'returncode': 0}
    result = incremental.consume_study(project, 'delta_sigma', entry,
        {'container': '', 'image': os.environ['VIBEIC_EDA_IMAGE'], 'cpus': 1, 'workers': 1}, run, 'A06')
    assert result['status'] == 'NOT_MEASURED'
    assert calls == []

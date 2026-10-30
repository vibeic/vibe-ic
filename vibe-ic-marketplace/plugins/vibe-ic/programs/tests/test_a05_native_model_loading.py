"""A05 LOCAL startup uses existing selected-PDK source, not a guessed model."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import analog_native_flow as native
import analog_pdk_availability as availability
from declared_pdk_is_the_pdk_used_check import declared_target
import librelane_contract as contract


@pytest.fixture
def case(tmp_path):
    raw = os.environ.get('A05_PATH_CONTROL_PROJECT')
    if not raw:
        pytest.skip('requires retained declaration and live LOCAL runtime')
    source = Path(raw)
    target, _ = declared_target(source)
    selected = availability.resolve_pdk(target, project=source, container='')
    assert selected['available'], selected
    init = Path(selected['pdk_root']) / 'libs.tech/ngspice/.spiceinit'
    assert init.is_file()
    project = tmp_path / 'case'
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    shutil.copyfile(source / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
                    docs / 'L19_CONSTRAINTS_PDK.json')
    directory = project / 'phase3/analog/neutral'
    directory.mkdir(parents=True)
    (directory.parent / 'analog_block_list.json').write_text(json.dumps({
        'blocks': [{'name': 'neutral', 'type': 'amplifier'}]}))
    deck = directory / 'op.sp'
    deck.write_text('* TEST_ONLY missing model fault\nxmissing a 0 missing_model_neutral\n.op\n.end\n')
    args = SimpleNamespace(entry_step='A05', exit_step='A05', blocks='', container='',
                           image=os.environ['VIBEIC_EDA_IMAGE'], transport='LOCAL', pdk=target)
    return project, directory, init, args


def _window(case, monkeypatch):
    project, directory, _, args = case
    observed = []
    def dispatch(step, project, block, options, commands):
        execution = commands('@ngspice', ['-b', str(directory / 'op.sp')], cwd=directory)
        observed.append(execution)
        return {'status': 'FAIL' if execution['returncode'] else 'NOT_MEASURED',
                'detail': 'SOFTWARE startup transport control; no design qualification',
                'executions': [execution], 'outputs': []}
    monkeypatch.setattr(native, '_dispatch', dispatch)
    return native.run_window(project, args), observed


def test_actual_window_supplies_source_selected_init_and_environment(case, monkeypatch):
    seen = []
    def command(argv, **kwargs):
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', command)
    _, observed = _window(case, monkeypatch)
    _, _, init, _ = case
    env = seen[0][1]['env']
    assert env.get('SPICE_USERINIT_DIR') == str(init.parent)
    assert env.get('PDK') == init.parents[2].name
    assert observed[0]['native_init']['sha256'] == native._sha(init)
    assert observed[0]['native_init']['path'] == str(init)


def test_existing_project_init_is_consumed_without_overwrite(case, monkeypatch):
    _, directory, _, _ = case
    custom = directory / '.spiceinit'
    custom.write_text('* TEST_ONLY explicit project startup\nset num_threads=1\n')
    before = custom.read_bytes()
    seen = []
    def command(argv, **kwargs):
        seen.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', command)
    _, observed = _window(case, monkeypatch)
    assert seen[0].get('SPICE_USERINIT_DIR') == str(directory)
    assert custom.read_bytes() == before
    assert observed[0]['native_init']['path'] == str(custom)


@pytest.mark.parametrize('fault', ['attestation', 'image_root'])
def test_unbound_local_startup_refuses_before_native_launch(case, monkeypatch, fault, tmp_path):
    if fault == 'attestation':
        bad = tmp_path / 'invalid-launch.json'
        bad.write_text('{}')
        monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(bad))
    else:
        monkeypatch.setenv('PDK_ROOT', '/unbound/selected-pdk')
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', command)
    result, _ = _window(case, monkeypatch)
    assert len(calls) == 0
    assert result['window_verdict'] == 'NOT_MEASURED'


def test_actual_missing_model_stays_native_failure(case, monkeypatch):
    result, observed = _window(case, monkeypatch)
    assert observed[0]['returncode'] == 1
    assert result['window_verdict'] == 'FAIL'
    log = Path(observed[0]['log']).read_text()
    assert 'missing_model_neutral' in log.lower()

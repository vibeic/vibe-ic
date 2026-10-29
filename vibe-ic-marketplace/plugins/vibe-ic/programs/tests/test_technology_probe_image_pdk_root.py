"""SOFTWARE image/filesystem controls for the real two-probe producer.

Only Docker transport/metadata is substituted; emitted shell/Python commands,
LEF reading, GDS binary parsing and normal technology_facts run unchanged.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import _container_exec
import _eda_image
import submission_template_fetch as stf
from test_general_precheck import write_gds

IMAGE = 'software-image@sha256:' + '0' * 64


def _kit(root, unit):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'tech.lef').write_text('UNITS\n DATABASE MICRONS 2000 ;\nEND UNITS\n')
    write_gds(root / 'cells.gds', {'software_cell': {}}, dbu_meters=unit * 1e-6)


def _scene(tmp_path, monkeypatch, *, entrypoint=None, declared=True, legacy=False,
           root_value=None, damage=None, quoted=False):
    name = 'registered_neutral'
    legacy_root = tmp_path / 'legacy' / name
    image_root = tmp_path / ("image root ' ; $HOST_VALUE" if quoted else 'image-pdks')
    selected = image_root / name
    _kit(selected, 0.001)
    if legacy:
        _kit(legacy_root, 0.02)  # a real, different stale legacy reading
    if damage == 'missing_file':
        (selected / 'tech.lef').unlink()
    elif damage == 'invalid_file':
        (selected / 'tech.lef').write_text('DATABASE MICRONS invalid ;\n')
    elif damage == 'invalid_gds':
        (selected / 'cells.gds').write_bytes(b'not a GDS stream')
    elif damage == 'missing_gds':
        (selected / 'cells.gds').unlink()
    metadata = {'Entrypoint': entrypoint}
    if declared:
        metadata['Env'] = ['PDK_ROOT=' + (str(image_root) if root_value is None else root_value)]
    monkeypatch.setattr(stf, '_registry_entry', lambda _pdk: {
        'name': name, 'container_path': str(legacy_root),
        'tech_lef_glob': 'tech.lef', 'cell_gds_glob': 'cells.gds'})
    monkeypatch.setattr(_container_exec, 'local_exec_mode', lambda *_: False)
    monkeypatch.setattr(_eda_image, 'judged_image', lambda **_: _eda_image.JudgedImage(
        IMAGE, 'sha256:' + '0' * 64, 'SOFTWARE', 'fixture', ''))
    monkeypatch.setenv('PDK_ROOT', str(tmp_path / 'HOST_ROOT_MUST_NOT_BE_USED'))
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    calls = []

    def transport(argv, timeout=600):
        if argv[:3] == ['docker', 'image', 'inspect']:
            return 0, json.dumps([{'Config': metadata}]), ''
        assert argv[:3] == ['docker', 'run', '--rm']
        assert argv[argv.index('--cpus')+1] == '2'
        assert argv[argv.index('--network')+1] == 'none'
        assert argv[argv.index('--memory')+1] == argv[argv.index('--memory-swap')+1] == '4g'
        command = list(argv[argv.index(IMAGE)+1:])
        if entrypoint:
            assert command.pop(0) == '--skip'
        else:
            assert command[0] != '--skip'
        if command[0] == 'python3':
            assert any(v.endswith(':/vibeic_programs:ro') for v in argv)
            command[0] = sys.executable
        calls.append(command)
        if damage == 'process_failure':
            return 7, '', 'SOFTWARE forced process failure'
        if damage == 'gds_process_failure' and command[0] != 'bash':
            return 9, '', 'SOFTWARE independent GDS process failure'
        env = dict(os.environ, PYTHONPATH=str(stf._HERE), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=timeout)
        return result.returncode, result.stdout, result.stderr

    monkeypatch.setattr(stf, '_run', transport)
    return lambda: stf.technology_facts(name, IMAGE)['database_unit_um'], calls, selected, legacy_root, metadata


@pytest.mark.parametrize('entrypoint', [None, ['/dockerstartup/scripts/ui_startup.sh']])
def test_declared_image_root_over_stale_legacy_is_an_actual_reading(tmp_path, monkeypatch, entrypoint):
    run, calls, selected, _, _ = _scene(tmp_path, monkeypatch, entrypoint=entrypoint, legacy=True)
    fact = run()
    assert fact['value'] == 0.001, fact  # pre-fix reads the real wrong GDS value 0.02
    assert fact['tech_lef'] == str(selected / 'tech.lef')
    assert fact['cell_gds'] == str(selected / 'cells.gds')
    assert len(calls) == 2


@pytest.mark.parametrize('quoted', [False, True])
def test_fresh_declared_root_without_legacy_alias_reaches_both_probes(tmp_path, monkeypatch, quoted):
    run, calls, selected, legacy, _ = _scene(tmp_path, monkeypatch, quoted=quoted)
    fact = run()
    assert fact['value'] == 0.001, fact
    assert fact['lef_database_unit_um'] == 0.0005
    assert fact['tech_lef_source'] == str(selected / 'tech.lef') + ':2'
    assert fact['source'] == str(selected / 'cells.gds') + ':UNITS'
    assert not legacy.exists()  # no alias or bootstrap mutation
    assert len(calls) == 2


def test_supported_legacy_root_without_image_declaration_remains_normal(tmp_path, monkeypatch):
    run, calls, _, legacy, _ = _scene(tmp_path, monkeypatch, declared=False, legacy=True)
    fact = run()
    assert fact['value'] == 0.02, fact
    assert fact['cell_gds'] == str(legacy / 'cells.gds')
    assert len(calls) == 2


@pytest.mark.parametrize('value', ['', 'relative/path', '/a/../b', '/a\n/b', '/wild/*'])
def test_malformed_declared_root_never_uses_stale_legacy(tmp_path, monkeypatch, value):
    run, _, _, _, _ = _scene(tmp_path, monkeypatch, root_value=value, legacy=True)
    fact = run()
    assert fact['value'] is None, fact
    assert fact['unavailable']


@pytest.mark.parametrize('damage', ['missing_root', 'foreign_root'])
def test_unavailable_declared_pdk_does_not_fall_back_or_cross_identity(tmp_path, monkeypatch, damage):
    foreign = tmp_path / 'foreign-pdks'
    if damage == 'foreign_root':
        _kit(foreign / 'another_registered_pdk', 0.125)
    run, _, _, _, _ = _scene(tmp_path, monkeypatch, root_value=str(foreign), legacy=True)
    fact = run()
    assert fact['value'] is None, fact
    assert fact['unavailable']


@pytest.mark.parametrize('damage', ['missing_file', 'invalid_file', 'process_failure',
    'missing_gds', 'invalid_gds', 'gds_process_failure'])
def test_actual_file_and_independent_gds_failures_stay_unavailable(tmp_path, monkeypatch, damage):
    run, calls, _, _, _ = _scene(tmp_path, monkeypatch, damage=damage)
    fact = run()
    assert fact['value'] is None, fact
    assert fact['unavailable']
    if damage in ('missing_gds', 'invalid_gds', 'gds_process_failure'):
        assert fact['lef_database_unit_um'] == 0.0005
        assert len(calls) == 2


def test_malformed_or_duplicate_image_environment_refuses_before_process(tmp_path, monkeypatch):
    run, calls, _, _, metadata = _scene(tmp_path, monkeypatch, legacy=True)
    for env in [{}, '', 42, [False], ['PDK_ROOT'], {'PDK_ROOT': '/foreign'}, ['PDK_ROOT=/one', 'PDK_ROOT=/two']]:
        metadata['Env'] = env
        fact = run()
        assert fact['value'] is None, fact
        assert fact['unavailable']
    assert calls == []

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
from _hostpaths import require_repo


@pytest.mark.parametrize('staged', [False, True])
def test_repo_declared_pdk_startup_is_independent_of_model_staging(tmp_path, monkeypatch, staged):
    import analog_pdk_availability as availability
    from declared_pdk_is_the_pdk_used_check import declared_target
    declaration = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
        'tests', 'fixtures', 'm4_native_top', 'phase1', 'generated_docs', 'L19_CONSTRAINTS_PDK.json')
    project = tmp_path / 'project'
    target = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    target.parent.mkdir(parents=True)
    shutil.copyfile(declaration, target)
    family, _ = declared_target(project)
    root = tmp_path / 'runtime-pdks'
    init = root / family / 'libs.tech/ngspice/.spiceinit'
    init.parent.mkdir(parents=True)
    init.write_text('* runtime-owned startup\nset num_threads=1\n')
    monkeypatch.setattr(availability, 'local_pdks_root', lambda *a: str(root))
    if staged:
        model = project / 'input/pdk/models/device.lib'
        model.parent.mkdir(parents=True)
        model.write_text('.model neutral_diode D\n')
        assert availability.resolve_pdk(family, project=project, container='')['source'] == 'project_custom_pdk'
    environment, source = native._local_ngspice_startup(project, project, 'test-runtime')
    assert environment == {'PDK_ROOT': str(root), 'PDK': family,
                           'SPICE_USERINIT_DIR': str(init.parent)}
    assert source == {'path': str(init), 'sha256': native._sha(init)}


def test_staged_models_do_not_select_an_undeclared_installed_startup(tmp_path, monkeypatch):
    import analog_pdk_availability as availability
    project = tmp_path / 'project'
    declaration = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    declaration.parent.mkdir(parents=True)
    declaration.write_text(json.dumps({'fields': {'pdk_target': 'foreign_omega'}}))
    root = tmp_path / 'runtime-pdks'
    init = root / 'resident_alpha/libs.tech/ngspice/.spiceinit'
    init.parent.mkdir(parents=True)
    init.write_text('* not the declared process\n')
    model = project / 'input/pdk/models/device.lib'
    model.parent.mkdir(parents=True)
    model.write_text('.model neutral_diode D\n')
    monkeypatch.setattr(availability, 'local_pdks_root', lambda *a: str(root))
    assert availability.resolve_pdk('foreign_omega', container='')['available'] is False
    assert native._local_ngspice_startup(project, project, 'test-runtime') == ({}, None)


@pytest.fixture
def psp_runtime():
    import analog_pdk_availability as availability
    image = os.environ.get('VIBEIC_EDA_IMAGE')
    if not os.environ.get(contract.LOCAL_ATTESTATION_ENV) or not shutil.which('ngspice'):
        pytest.skip('requires real ngspice and a live host-attested image')
    root = availability.local_pdks_root(image)
    assert root
    starts = sorted(path for path in Path(root).glob('*/libs.tech/ngspice/.spiceinit')
                    if 'psp103.osdi' in path.read_text(errors='replace'))
    assert starts, 'the pinned image must supply a PSP-capable PDK startup'
    family = starts[0].parents[2].name
    selected = availability.resolve_pdk(family, container='')
    assert selected['available'], selected
    init = Path(selected['pdk_root']) / 'libs.tech/ngspice/.spiceinit'
    return image, family, init


def _psp_project(tmp_path, family, mode, *, model_type='psp103va'):
    project = tmp_path / 'project'
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {'pdk_target': family}}))
    directory = project / 'phase3/analog/device_alpha'
    directory.mkdir(parents=True)
    (directory.parent / 'analog_block_list.json').write_text(json.dumps({'blocks': [{'name': 'device_alpha'}]}))
    spec = {'specs': [{'name': 'vout', 'min': 0.9, 'max': 1.1, 'unit': 'V'}]}
    (directory / 'spec.json').write_text(json.dumps(spec))
    model_text = '.model model_alpha ' + model_type + ' type=1\n'
    if mode != 'canonical':
        model = project / 'input/pdk/models/device.lib'
        model.parent.mkdir(parents=True)
        model.write_text(model_text)
        model_text = '.include ../../../input/pdk/models/device.lib\n'
    (directory / 'device_alpha.sp').write_text('* synthetic PSP device\n' + model_text +
        '.subckt device_alpha d g vss\nn_active d g vss vss model_alpha w=1u l=1u\n.ends device_alpha\n')
    control = ['op', 'let sensed = v(d)', 'echo "MEAS vout=" $&sensed',
               'let device_current = -i(v_force)', 'echo "MEAS device_current=" $&device_current', 'quit']
    canonical = directory / 'tb_device_alpha.sp'
    canonical.write_text('* canonical PSP testbench\n.include device_alpha.sp\n'
        'v_force d 0 1\nv_gate g 0 1\nxdut d g 0 device_alpha\n.control\n' +
        '\n'.join(control) + '\n.endc\n.end\n')
    config = {'blocks': {'device_alpha': {'required_measurements': ['vout']}}}
    if mode in ('declared', 'sidecar'):
        declaration = directory / ('testbench_inputs.json' if mode == 'sidecar' else 'declared.json')
        declaration.write_text(json.dumps({'block': 'device_alpha', 'ports': ['d', 'g', 'vss'],
            'rails': {'vss': 'vss'}, 'testbench': {'supply_exprs': ['1'],
            'stimulus': ['v_force d 0 {supply}', 'v_gate g 0 {supply}'], 'control': control}}))
        if mode == 'declared':
            config['blocks']['device_alpha']['testbench_inputs'] = str(declaration.relative_to(project))
    (project / 'input').mkdir(exist_ok=True)
    (project / 'input/analog_flow.json').write_text(json.dumps(config))
    return project, canonical


@pytest.mark.parametrize('mode', ['canonical', 'declared', 'sidecar'])
def test_real_a07_psp_uses_the_same_runtime_startup(tmp_path, psp_runtime, mode):
    image, family, init = psp_runtime
    project, canonical = _psp_project(tmp_path, family, mode)
    before = canonical.read_bytes()
    args = SimpleNamespace(entry_step='A07', exit_step='A07', blocks='device_alpha',
                           container='', image=image, transport='LOCAL', pdk=family)
    report = native.run_window(project, args)
    row = report['steps'][0]
    assert row['status'] == 'PASS', row
    assert row['metrics']['vout'] == pytest.approx(1.0)
    assert row['metrics']['device_current'] > 0
    execution = row['executions'][0]
    assert execution['native_init'] == {'path': str(init), 'sha256': native._sha(init)}
    assert execution['native_environment']['PDK'] == family
    assert execution['native_environment']['SPICE_USERINIT_DIR'] == str(init.parent)
    assert row['input_views'][str(init)] == native._sha(init)
    assert canonical.read_bytes() == before
    assert ('testbench_inputs' in row['native_inputs']) == (mode != 'canonical')


def test_real_declared_psp_unknown_model_remains_failure(tmp_path, psp_runtime):
    image, family, _ = psp_runtime
    project, _ = _psp_project(tmp_path, family, 'declared', model_type='unavailable_model_type')
    report = native.run_window(project, SimpleNamespace(entry_step='A07', exit_step='A07',
        blocks='device_alpha', container='', image=image, transport='LOCAL', pdk=family))
    row = report['steps'][0]
    assert row['status'] == 'FAIL'
    assert row['executions'][0]['returncode'] != 0


def test_undeclared_staged_case_keeps_coverage_refusal(tmp_path, psp_runtime):
    image, family, _ = psp_runtime
    project, _ = _psp_project(tmp_path, family, 'undeclared')
    spec = project / 'phase3/analog/device_alpha/spec.json'
    spec.write_text(json.dumps({'specs': [{'name': 'vout', 'min': 0.9, 'max': 1.1},
                                       {'name': 'psrr', 'min': 40}]}))
    report = native.run_window(project, SimpleNamespace(entry_step='A07', exit_step='A07',
        blocks='device_alpha', container='', image=image, transport='LOCAL', pdk=family))
    row = report['steps'][0]
    assert row['status'] == 'NOT_MEASURED'
    assert row['executions'] == []
    assert 'psrr' in row['detail']


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

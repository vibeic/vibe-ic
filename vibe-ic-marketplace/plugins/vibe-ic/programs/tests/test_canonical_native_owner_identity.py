"""A native consumer repair must reopen the ordinary canonical admission."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys

import pytest


@pytest.fixture
def admission_case(tmp_path, monkeypatch):
    actual = Path(os.environ.get('VIBEIC_ADMISSION_TEST_PROGRAMS', Path(__file__).parents[1]))
    sys.path.insert(0, str(actual))
    spec = importlib.util.spec_from_file_location('native_owner_admission_under_test', actual / 'canonical_run_admission.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'image_identity', lambda _: 'sha256:79957120d37804ae0d23144307c5c166dcb609831326f19f2edb8729fe807cfe')
    monkeypatch.setattr(module.emit_attestation, 'phase1_provenance', lambda _: {'ran': False})
    project = tmp_path / 'subject'
    (project / 'input/docs').mkdir(parents=True)
    (project / 'input/docs/contract.md').write_text('One clock-sampled transaction interface.\n')
    programs = tmp_path / 'plugin/programs'
    programs.mkdir(parents=True)
    (programs.parent / 'flow').mkdir()
    import librelane_contract
    for name in ['design_one_shot_runner.py', 'phase3_one_shot_runner.py',
                 'librelane_contract.py', 'execution_backend_producers.py',
                 *librelane_contract.PLUGIN_HOST_MODULES]:
        shutil.copyfile(actual / name, programs / name)
    shutil.copytree(actual / 'librelane_plugins', programs / 'librelane_plugins',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    shutil.copyfile(actual.parent / 'flow/phase1_phase2_phase3.yaml', programs.parent / 'flow/phase1_phase2_phase3.yaml')
    return module, project, programs


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
def test_changed_native_owner_reopens_same_canonical_span(admission_case, span):
    module, project, programs = admission_case
    first = module.admit_span(project, span, programs, 'vibeic-eda', {'pdk': 'gf180mcuD'})
    assert first.admitted
    owner = programs / 'librelane_contract.py'
    owner.write_bytes(owner.read_bytes() + b'\n# changed native launch contract\n')
    changed = module.admit_span(project, span, programs, 'vibeic-eda', {'pdk': 'gf180mcuD'})
    assert changed.admitted, changed.reason
    assert changed.identity_sha256 != first.identity_sha256
    repeated = module.admit_span(project, span, programs, 'vibeic-eda', {'pdk': 'gf180mcuD'})
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'


@pytest.mark.parametrize('change_report', [False, True])
def test_unchanged_native_owner_keeps_duplicate_refusal(admission_case, change_report):
    module, project, programs = admission_case
    first = module.admit_span(project, 'phase2', programs, 'vibeic-eda', {'pdk': 'gf180mcuD'})
    assert first.admitted
    if change_report:
        (project / 'reports').mkdir()
        (project / 'reports/result.json').write_text('{"status":"new report bytes"}\n')
    repeated = module.admit_span(project, 'phase2', programs, 'vibeic-eda', {'pdk': 'gf180mcuD'})
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity_sha256 == first.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
@pytest.mark.parametrize('owner', [
    'execution_backend_producers.py',
    'librelane_plugins/librelane_plugin_vibeic/postgpl_fanout_closure.py',
    'librelane_plugins/librelane_plugin_vibeic/postgpl_fanout_closure.tcl',
    'librelane_plugins/librelane_plugin_vibeic/finishing_xor.drc',
    '_spare_plan.py',
    'dynamic_ir_vectored_emit.py',
])
def test_changed_backend_or_plugin_source_reopens_same_span(admission_case, span, owner):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '17', 'exit_step': '17'}
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    path = programs / owner
    path.write_bytes(path.read_bytes() + b'\n# changed native source control\n')
    changed = module.admit_span(project, span, programs, 'fixture-container', config)
    assert changed.reason == 'ADMITTED'
    assert changed.admitted, changed.reason
    assert changed.identity_sha256 != first.identity_sha256
    repeated = module.admit_span(project, span, programs, 'fixture-container', config)
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity_sha256 == changed.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
@pytest.mark.parametrize('operation', ['add', 'delete'])
@pytest.mark.parametrize('suffix', ['.py', '.tcl', '.drc'])
def test_changed_plugin_source_population_reopens_same_span(
        admission_case, span, operation, suffix):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '17', 'exit_step': '17'}
    path = programs / 'librelane_plugins/extra_package' / ('native_owner' + suffix)
    path.parent.mkdir(parents=True)
    if operation == 'delete':
        path.write_text('# synthetic executable source population\n')
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    if operation == 'add':
        path.write_text('# synthetic executable source population\n')
    else:
        path.unlink()
    changed = module.admit_span(project, span, programs, 'fixture-container', config)
    assert changed.reason == 'ADMITTED'
    assert changed.admitted, changed.reason
    assert changed.identity_sha256 != first.identity_sha256
    repeated = module.admit_span(project, span, programs, 'fixture-container', config)
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity_sha256 == changed.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
@pytest.mark.parametrize('output', [
    'librelane_plugins/librelane_plugin_vibeic/__pycache__/native_owner.pyc',
    'librelane_plugins/librelane_plugin_vibeic/__pycache__/generated.py',
    'librelane_plugins/librelane_plugin_vibeic/native_metrics.json',
    'librelane_plugins/librelane_plugin_vibeic/openroad.log',
])
def test_generated_native_outputs_do_not_reopen_same_span(admission_case, span, output):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '17', 'exit_step': '17'}
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    path = programs / output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('changed generated output bytes\n')
    repeated = module.admit_span(project, span, programs, 'fixture-container', config)
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity_sha256 == first.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
def test_same_basename_plugin_move_reopens_same_span(admission_case, span):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk'}
    source = programs / 'librelane_plugins/aaa_left/native_owner.py'
    target = programs / 'librelane_plugins/aaa_right/native_owner.py'
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    body = b'# identical source bytes under a different owning package\n'
    source.write_bytes(body)
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    source.rename(target)
    assert source.name == target.name and target.read_bytes() == body
    changed = module.admit_span(project, span, programs, 'fixture-container', config)
    assert changed.reason == 'ADMITTED'
    assert changed.admitted
    assert changed.identity_sha256 != first.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
def test_identical_source_bytes_swapped_between_package_paths_reopen(admission_case, span):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk'}
    left = programs / 'librelane_plugins/aaa_left/left_owner.py'
    right = programs / 'librelane_plugins/aaa_right/right_owner.py'
    left.parent.mkdir(parents=True)
    right.parent.mkdir(parents=True)
    body = b'# identical code whose owning package path is executable input\n'
    left.write_bytes(body)
    right.write_bytes(body)
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    left.unlink()
    right.unlink()
    (left.parent / right.name).write_bytes(body)
    (right.parent / left.name).write_bytes(body)
    changed = module.admit_span(project, span, programs, 'fixture-container', config)
    assert changed.reason == 'ADMITTED'
    assert changed.admitted
    assert changed.identity_sha256 != first.identity_sha256


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
def test_identical_source_tree_under_another_absolute_root_stays_duplicate(admission_case, span):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk'}
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    assert first.admitted
    elsewhere = programs.parent.parent / 'other-checkout/plugin'
    shutil.copytree(programs.parent, elsewhere)
    repeated = module.admit_span(project, span, elsewhere / 'programs', 'fixture-container', config)
    assert repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert not repeated.admitted
    assert repeated.identity == first.identity

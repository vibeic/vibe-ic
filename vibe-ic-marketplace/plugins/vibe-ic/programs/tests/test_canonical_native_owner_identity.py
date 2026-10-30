"""A native consumer repair must reopen the ordinary canonical admission."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import threading

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
    for name in ['vibe_ic_one_shot_runner.py', 'design_one_shot_runner.py',
                 'phase3_one_shot_runner.py', 'canonical_run_admission.py',
                 'librelane_contract.py', 'execution_backend_producers.py',
                 'execution_policy.py', 'execution_modes.py',
                 'execution_frontend_providers.py',
                 'execution_frontend_worker.py', 'lec_run.py',
                 'drv_capture_plan.py', 'drv_signoff_capture.py',
                 'serial_parallel_mul_synth.py',
                 *librelane_contract.PLUGIN_HOST_MODULES]:
        shutil.copyfile(actual / name, programs / name)
    shutil.copytree(actual / 'librelane_plugins', programs / 'librelane_plugins',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    shutil.copyfile(actual.parent / 'flow/phase1_phase2_phase3.yaml', programs.parent / 'flow/phase1_phase2_phase3.yaml')
    return module, project, programs


def test_step13_owner_change_reopens_then_duplicate_guard_still_refuses(
        admission_case):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'}

    first = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)
    unchanged = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)
    owner = programs / 'lec_run.py'
    owner.write_bytes(owner.read_bytes() + b'\n# changed Step13 owner source\n')
    changed = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)
    repeated = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)

    assert first.admitted and first.reason == 'ADMITTED'
    assert not unchanged.admitted
    assert unchanged.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert unchanged.identity == first.identity
    assert changed.admitted and changed.reason == 'ADMITTED'
    assert changed.identity_sha256 != first.identity_sha256
    assert (changed.identity['program_source_sha256']
            != first.identity['program_source_sha256'])
    for key in first.identity.keys() - {'program_source_sha256'}:
        assert changed.identity[key] == first.identity[key], key
    assert not repeated.admitted
    assert repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity == changed.identity


def test_unrelated_non_program_bytes_do_not_manufacture_new_evidence(
        admission_case):
    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'}
    first = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)
    (programs / 'operator-notes.txt').write_text(
        'not executable canonical program input\n')
    repeated = module.admit_span(
        project, 'phase2', programs, 'fixture-container', config)
    assert not repeated.admitted
    assert repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert repeated.identity == first.identity


@pytest.mark.parametrize('operation', ['missing', 'renamed'])
def test_missing_or_renamed_step13_owner_refuses_before_admission(
        admission_case, operation):
    module, project, programs = admission_case
    owner = programs / 'lec_run.py'
    if operation == 'missing':
        owner.unlink()
    else:
        owner.rename(programs / 'lec_run.relocated.py')

    refused = module.admit_span(
        project, 'phase2', programs, 'fixture-container',
        {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'})
    assert not refused.admitted
    assert refused.reason == 'CANONICAL_PROGRAM_SOURCE_UNAVAILABLE'
    assert 'programs/lec_run.py' in refused.detail
    ledger = module.ledger_path(project)
    assert not ledger.exists() or not ledger.read_text().strip()


def test_step13_owner_unreadable_at_snapshot_binding_refuses_without_ledger(
        admission_case, monkeypatch):
    module, project, programs = admission_case
    owner = (programs / 'lec_run.py').resolve()
    original_open = module.os.open

    def refuse_owner(path, flags, *args, **kwargs):
        if Path(path).resolve() == owner:
            raise PermissionError('injected unreadable Step13 owner')
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, 'open', refuse_owner)
    refused = module.admit_span(
        project, 'phase2', programs, 'fixture-container',
        {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'})

    assert not refused.admitted
    assert refused.reason == 'CANONICAL_PROGRAM_SOURCE_UNAVAILABLE'
    assert 'programs/lec_run.py (unreadable)' in refused.detail
    ledger = module.ledger_path(project)
    assert not ledger.exists() or not ledger.read_text().strip()


def test_step13_owner_is_read_once_for_bound_program_identity(
        admission_case, monkeypatch):
    module, project, programs = admission_case
    owner = (programs / 'lec_run.py').resolve()
    original_open = module.os.open
    owner_opens = 0

    def count_owner(path, flags, *args, **kwargs):
        nonlocal owner_opens
        if Path(path).resolve() == owner:
            owner_opens += 1
            if owner_opens > 1:
                raise PermissionError('second Step13-owner read is forbidden')
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, 'open', count_owner)
    admitted = module.admit_span(
        project, 'phase2', programs, 'fixture-container',
        {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'})

    assert admitted.admitted and admitted.reason == 'ADMITTED'
    assert owner_opens == 1


def test_step13_owner_fifo_refuses_without_blocking_or_ledger(admission_case):
    module, project, programs = admission_case
    owner = programs / 'lec_run.py'
    owner.unlink()
    os.mkfifo(owner)
    observed = []

    def invoke():
        observed.append(module.admit_span(
            project, 'phase2', programs, 'fixture-container',
            {'pdk': 'fixture-pdk', 'entry_step': '14', 'exit_step': '14'}))

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive(), 'FIFO source blocked canonical admission'
    assert len(observed) == 1
    refused = observed[0]
    assert not refused.admitted
    assert refused.reason == 'CANONICAL_PROGRAM_SOURCE_UNAVAILABLE'
    assert 'programs/lec_run.py (not-regular)' in refused.detail
    ledger = module.ledger_path(project)
    assert not ledger.exists() or not ledger.read_text().strip()


def test_step13_owner_extends_existing_canonical_program_population(
        admission_case):
    module, _, programs = admission_case
    relatives = {
        path.relative_to(programs.parent).as_posix()
        for path in module.canonical_program_paths(programs)
    }
    assert 'programs/lec_run.py' in relatives
    assert {
        'programs/vibe_ic_one_shot_runner.py',
        'programs/design_one_shot_runner.py',
        'programs/phase3_one_shot_runner.py',
        'programs/execution_policy.py',
        'programs/execution_modes.py',
        'programs/execution_frontend_providers.py',
        'programs/execution_frontend_worker.py',
        'programs/execution_backend_producers.py',
        'flow/phase1_phase2_phase3.yaml',
    }.issubset(relatives)


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


@pytest.mark.parametrize('span', ['phase2', 'phase3'])
@pytest.mark.parametrize('owner', ['drv_capture_plan.py', 'drv_signoff_capture.py'])
def test_capture_host_owner_change_reopens_and_preserves_duplicate_controls(
        admission_case, span, owner, tmp_path):
    import hashlib
    import json

    module, project, programs = admission_case
    config = {'pdk': 'fixture-pdk', 'entry_step': '22', 'exit_step': '27'}
    path = programs / owner
    original = path.read_bytes()
    first = module.admit_span(project, span, programs, 'fixture-container', config)
    unchanged = module.admit_span(project, span, programs, 'fixture-container', config)
    try:
        path.write_bytes(original + b'\n# neutral capture host source-byte change\n')
        changed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        changed = module.admit_span(project, span, programs, 'fixture-container', config)
        repeated = module.admit_span(project, span, programs, 'fixture-container', config)
    finally:
        path.write_bytes(original)
    reverted = module.admit_span(project, span, programs, 'fixture-container', config)
    elsewhere = tmp_path / 'other-checkout/plugin'
    shutil.copytree(programs.parent, elsewhere)
    portable = module.admit_span(
        project, span, elsewhere / 'programs', 'fixture-container', config)
    relative_keys = tuple(p.relative_to(programs.parent).as_posix()
                          for p in module.canonical_program_paths(programs))
    portable_keys = tuple(p.relative_to(elsewhere).as_posix()
                         for p in module.canonical_program_paths(elsewhere / 'programs'))
    observed = {
        'scope': 'SOURCE_CONTROL: actual admission API; neutral image/provenance I/O',
        'owner': owner, 'span': span,
        'original_sha256': hashlib.sha256(original).hexdigest(),
        'changed_sha256': changed_sha256,
        'restored_exact': path.read_bytes() == original,
        'changed_reason': changed.reason,
        'changed_admitted': changed.admitted,
        'identities': {name: row.identity_sha256 for name, row in (
            ('first', first), ('unchanged', unchanged), ('changed', changed),
            ('repeated', repeated), ('reverted', reverted), ('portable', portable))},
        'same_relative_keys': relative_keys == portable_keys,
    }
    (tmp_path / 'capture-host-admission.observation.json').write_text(
        json.dumps(observed, indent=2) + '\n')
    assert first.admitted and first.reason == 'ADMITTED', observed
    assert not unchanged.admitted and unchanged.reason == 'DUPLICATE_NO_NEW_EVIDENCE', observed
    assert unchanged.identity == first.identity, observed
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE', observed
    assert repeated.identity == changed.identity, observed
    assert not reverted.admitted and reverted.reason == 'DUPLICATE_NO_NEW_EVIDENCE', observed
    assert reverted.identity == first.identity, observed
    assert not portable.admitted and portable.reason == 'DUPLICATE_NO_NEW_EVIDENCE', observed
    assert portable.identity == first.identity, observed
    assert relative_keys == portable_keys, observed
    assert path.read_bytes() == original, observed
    assert changed_sha256 != observed['original_sha256'], observed
    assert observed['changed_reason'] == 'ADMITTED', observed
    assert changed.admitted, observed
    assert changed.identity_sha256 != first.identity_sha256, observed


def test_serial_rtl_producer_fix_reopens_bounded_phase2(admission_case):
    module, project, programs = admission_case
    config = {'pdk': 'gf180mcuD', 'entry_step': '1', 'exit_step': '4'}
    def admit():
        return module.admit_span(project, 'phase2', programs, 'vibeic-eda', config)
    first = admit()
    assert first.admitted
    assert not admit().admitted
    producer = programs / 'serial_parallel_mul_synth.py'
    original = producer.read_bytes()
    producer.write_bytes(original + b'\n# repaired retained RTL contract refresh\n')
    changed = admit()
    assert changed.admitted, changed.reason
    assert changed.identity_sha256 != first.identity_sha256
    assert not admit().admitted
    producer.write_bytes(original)
    restored = admit()
    assert not restored.admitted
    assert restored.identity_sha256 == first.identity_sha256

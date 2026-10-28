"""Reopen actual neutral EQY receipts; never fabricate native or approval data."""
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import flow109
import flow109_metric_acceptance as metrics


pytestmark = pytest.mark.skipif(
    not os.environ.get('FLOW109_D25_QUALIFIED_REFERENCE')
    or not os.environ.get('FLOW109_D25_EXECUTION_DELIVERY'),
    reason='actual native reference and independently authored root delivery required')


@pytest.fixture
def native_subject(request):
    kind = 'bad' if request.node.name == 'test_actual_native_cex_remains_fail' else 'good'
    reference = Path(os.environ['FLOW109_D25_QUALIFIED_REFERENCE']) / kind
    project = Path('/out/canonical/projects') / kind
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    assert any(fields[4] == str(project) and 'rw' in fields[5].split(',') for fields in mounts)
    for child in project.iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(reference, project, dirs_exist_ok=True)
    delivery = json.loads(Path(os.environ['FLOW109_D25_EXECUTION_DELIVERY']).read_text())
    for relative, record in delivery['files'].items():
        raw = Path(record['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        target = project / relative
        assert target.resolve().is_relative_to(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    context = json.loads((project / 'd25-current-component-context.json').read_text())
    return project, context


def test_unchanged_actual_native_receipt_remains_qualified(native_subject):
    project, context = native_subject
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['qualification'] == 'PASS', observed
    assert len(observed['obligations']) == 3
    assert all(o['status'] == 'PASS' for o in observed['obligations'])
    assert observed['native_execution']['execution_authority']['status'] == 'APPROVED'


def test_actual_native_cex_remains_fail(native_subject):
    project, context = native_subject
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['component_status'] == 'FAIL', observed
    assert observed['reason'] == 'D25_NATIVE_CEX'


def test_caller_resealed_derived_gate_cannot_reuse_native_pass(native_subject):
    project, context = native_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    report = project / 'reports/lec_eqy_execution.json'
    execution = json.loads(report.read_text())
    gate = project / execution['native_directory']
    gate = gate.parent / 'gate/after.il'
    lines = gate.read_text().splitlines()
    matches = [i for i, line in enumerate(lines)
               if line.startswith('  connect ') and '# \\count {' in line]
    assert len(matches) == 1
    index = matches[0]
    lhs = lines[index].split()[1]
    lines[index] = f"  connect {lhs} 4'1111  # isolated review: changed actual gate output relation"
    gate.write_text('\n'.join(lines) + '\n')
    relative = str(gate.relative_to(project))
    for records in (execution['files'], execution['derivation']['gate']['files']):
        entries = [entry for entry in records if entry['path'] == relative]
        assert len(entries) == 1
        entries[0]['sha256'] = hashlib.sha256(gate.read_bytes()).hexdigest()
    report.write_text(json.dumps(execution, indent=2) + '\n')
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == 'D25_NATIVE_EXECUTION_UNQUALIFIED'


@pytest.mark.parametrize('damage', [
    'missing_execution', 'rtl', 'gate', 'model', 'missing_model', 'missing_adoption',
    'stale_adoption_source', 'zero_partitions', 'missing_partition', 'skip',
    'foreign_script', 'producer_source', 'blackbox_derived',
])
def test_actual_native_and_authority_inputs_are_current(native_subject, damage):
    project, context = native_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    report = project / 'reports/lec_eqy_execution.json'
    execution = json.loads(report.read_text())
    manifest_path = project / 'input/flow109/D25.json'
    manifest = json.loads(manifest_path.read_text())
    native = project / execution['native_directory']
    reseal = False
    if damage == 'missing_execution':
        report.unlink()
    elif damage in ('rtl', 'gate'):
        item = manifest['rtl'][0] if damage == 'rtl' else manifest['gate_netlist']
        path = project / item['path']
        path.write_bytes(path.read_bytes() + b'\n// changed controlled source\n')
    elif damage in ('model', 'missing_model'):
        manifest['models'][0]['path'] = str(project / 'missing-official-model.v')
        if damage == 'model':
            Path(manifest['models'][0]['path']).write_text('module unqualified; endmodule\n')
        manifest_path.write_text(json.dumps(manifest))
    elif damage == 'missing_adoption':
        (project / 'adopted/base_16/native_execution.json').unlink()
    elif damage == 'stale_adoption_source':
        adopted = json.loads((project / 'adopted/base_16/native_execution.json').read_text())
        source = project / adopted['approval']['source_reference']['path']
        source.write_bytes(source.read_bytes() + b'\n ')
    elif damage == 'zero_partitions':
        (native / 'scratch/partition.list').write_text('')
        reseal = True
    elif damage == 'missing_partition':
        (native / 'scratch/partition.list').unlink()
    elif damage == 'skip':
        execution['native_error'] = 'controlled skipped execution'
        reseal = True
    elif damage == 'foreign_script':
        script = native.parent / 'source-boundary.eqy'
        script.write_text('[gold]\nread_rtlil /foreign/after.il\n')
        reseal = True
    elif damage == 'producer_source':
        execution['sources']['programs/librelane_eqy.py'] = '0' * 64
        reseal = True
    elif damage == 'blackbox_derived':
        path = native.parent / 'gate/after.il'
        path.write_bytes(path.read_bytes() + b'\nattribute \\blackbox 1\nmodule \\unbound\nend\n')
        reseal = True
    if reseal:
        for records in [execution['files'], *(d['files'] for d in execution['derivation'].values())]:
            for entry in records:
                path = project / entry['path']
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        report.write_text(json.dumps(execution, indent=2) + '\n')
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert not observed['obligations']

"""Serial dispatch must preserve compatible upstream declaration bytes."""
import json
import os
from pathlib import Path
import shutil

import pytest
import design_one_shot_runner as runner
import serial_parallel_mul_synth as serial
from test_serial_parallel_mul_synth import _mk_project, _SPM_PORTS


@pytest.fixture
def actual_d01_copy():
    seed = os.environ.get('FLOW109_SPM_D01_REFERENCE')
    if not seed:
        pytest.skip('retained genuine SPM D01 packet required')
    project = Path(os.environ['FLOW109_SPM_D01_PROJECT'])
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    assert any(fields[4] == str(project) and 'rw' in fields[5].split(',')
               for fields in mounts), project
    # The absolute D01 owner binding is retained. This mount is a disposable
    # copy; the live carrier is never mounted in these publication controls.
    for child in project.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(seed, project, dirs_exist_ok=True)
    return project


def test_actual_current_d01_survives_serial_refresh(actual_d01_copy):
    import fault_scan_chain_insert as scan
    project = actual_d01_copy
    before, problems = scan.load_d09_dft_contract(project)
    assert before is not None and problems == [], problems
    path = project / before['path']
    original = path.read_bytes()
    assert serial.main([str(project), '--refresh-contract']) == 0
    assert path.read_bytes() == original
    after, problems = scan.load_d09_dft_contract(project)
    assert problems == [] and after == before, problems
    row = runner.step_arith_declaration_emit(project)
    assert row.status == 'PASS', row.detail
    assert path.read_bytes() == original


def test_actual_reformatted_d01_remains_refused(actual_d01_copy):
    import fault_scan_chain_insert as scan
    project = actual_d01_copy
    binding, problems = scan.load_d09_dft_contract(project)
    assert binding is not None and problems == [], problems
    path = project / binding['path']
    original = path.read_bytes()
    declaration = json.loads(original)
    path.write_text(json.dumps(declaration, indent=2, sort_keys=True) + '\n')
    assert path.read_bytes() != original
    assert json.loads(path.read_text()) == declaration
    refused, problems = scan.load_d09_dft_contract(project)
    assert refused is None and 'publication output differs' in str(problems), problems
    row = runner.step_arith_declaration_emit(project)
    assert row.status == 'NOT_MEASURED'
    assert row.reason_class == runner._V.ReasonClass.UPSTREAM_REFUSED


@pytest.mark.parametrize('action', ['--emit', '--refresh-contract'])
def test_compatible_declaration_is_not_reserialized(tmp_path, action):
    project = _mk_project(tmp_path, ports=_SPM_PORTS, top='neutral_serial',
        l2_text='serial-parallel multiplier: p = (x * y) mod 2^N')
    assert serial.main([str(project), '--emit']) == 0
    path = project / 'plugin_output/declaration.json'
    declaration = json.loads(path.read_text())
    declaration['upstream_choice'] = {'z': 'unchanged', 'a': 'retained'}
    original = (json.dumps(declaration, indent=4) + '\n\n').encode()
    path.write_bytes(original)
    before = path.stat()
    assert serial.main([str(project), action]) == 0
    after = path.stat()
    assert path.read_bytes() == original
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_missing_semantic_fields_are_still_produced(tmp_path):
    project = _mk_project(tmp_path, ports=_SPM_PORTS, top='neutral_serial',
        l2_text='serial-parallel multiplier: p = (x * y) mod 2^N')
    path = project / 'plugin_output/declaration.json'
    path.parent.mkdir()
    original = {'upstream_choice': {'z': 'retained'}}
    path.write_text(json.dumps(original))
    assert serial.main([str(project), '--emit']) == 0
    produced = json.loads(path.read_text())
    assert produced['upstream_choice'] == original['upstream_choice']
    assert produced['latency_cycles'] == 2
    assert produced['integer_encoding'] == 'unsigned'
    assert produced['transaction_rearm'] == 'clocked_reset'


def test_missing_dft_authority_returns_typed_refusal(tmp_path):
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/declaration.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    row = runner.step_arith_declaration_emit(tmp_path)
    assert row.status == 'NOT_MEASURED'
    assert row.reason_class == runner._V.ReasonClass.UPSTREAM_REFUSED
    assert 'D01 DFT intent unavailable' in row.detail
    assert not (tmp_path / 'plugin_output/declaration.json').exists()


def test_dft_contract_inspection_error_returns_typed_refusal(tmp_path, monkeypatch):
    def unreadable_contract(project):
        raise OSError('controlled contract read failure')

    monkeypatch.setattr(runner._decl, 'select_contract', unreadable_contract)
    row = runner.step_arith_declaration_emit(tmp_path)
    assert row.status == 'NOT_MEASURED'
    assert row.reason_class == runner._V.ReasonClass.EXECUTION_ERROR
    assert 'controlled contract read failure' in row.detail
    assert not (tmp_path / 'plugin_output/declaration.json').exists()

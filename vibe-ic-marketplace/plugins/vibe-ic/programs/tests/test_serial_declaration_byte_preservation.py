"""Serial dispatch must preserve compatible upstream declaration bytes."""
import json
import shutil

import pytest
import serial_parallel_mul_synth as serial
from test_serial_parallel_mul_synth import _mk_project, _SPM_PORTS








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


@pytest.mark.parametrize('action', ['--emit', '--refresh-contract'])
@pytest.mark.parametrize('location', ['declaration.json', 'plugin_output/declaration.json'])
@pytest.mark.parametrize('private', [False, True], ids=['source-output', 'private-output'])
def test_supplied_function_does_not_rewrite_complete_plugin_declaration(
        tmp_path, action, location, private):
    project = _mk_project(tmp_path, ports=_SPM_PORTS, top='neutral_serial',
        l2_text='serial-parallel multiplier: p = (x * y) mod 2^N')
    spec, reason = serial.extract_serial_parallel_mul_spec(project, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    declaration = serial.plugin_declaration(spec)
    field = {'result': 'p', 'operands': ['y', 'x'], 'operator': '*', 'modulus_bits': 32}
    path = project / 'plugin_output/declaration.json'
    path.parent.mkdir()
    if location == 'plugin_output/declaration.json':
        declaration['function'] = field
    else:
        (project / location).write_text(json.dumps({'function': field}))
    original = (json.dumps(declaration, indent=4) + '\n\n').encode()
    path.write_bytes(original)
    if action == '--refresh-contract':
        rtl = project / 'phase2/stage1/rtl/neutral_serial.v'
        rtl.parent.mkdir(parents=True)
        rtl.write_text(serial.emit_rtl(spec))
    output = tmp_path / 'private-output' if private else project
    if private:
        shutil.copytree(project, output)
    output_path = output / 'plugin_output/declaration.json'
    before = output_path.stat()
    args = [str(project), action]
    if private:
        args += ['--output-project', str(output)]
    assert serial.main(args) == 0
    assert path.read_bytes() == original
    path = output_path
    after = path.stat()
    assert path.read_bytes() == original
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)

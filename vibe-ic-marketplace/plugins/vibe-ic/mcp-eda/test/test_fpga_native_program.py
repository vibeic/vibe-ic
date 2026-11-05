"""The FPGA driver reports the programmer and optional scope results."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

DRIVER = Path(__file__).resolve().parents[1] / 'src/devices/fpga/terasic-de10lite/driver.py'


@pytest.fixture
def driver():
    spec = importlib.util.spec_from_file_location('fpga_native_driver', DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(('native_rc', 'message', 'expected_rc', 'error'), [
    (0, 'Quartus Prime Programmer was successful', 0, None),
    (0, 'Operations done', 0, None),
    (0, 'No success result', 1, 'protocol_error'),
    (1, 'Operations done', 1, 'protocol_error'),
    (1, 'No cable found', 2, 'device_not_found'),
    (1, 'Permission denied', 2, 'permission_denied'),
])
def test_programmer_result_reaches_cli(tmp_path, native_rc, message, expected_rc, error):
    root = tmp_path / 'tool'
    (root / 'bin').mkdir(parents=True)
    record = tmp_path / 'argv.json'
    binary = root / 'bin/quartus_pgm'
    binary.write_text(
        '#!/usr/bin/env python3\n'
        'import json,os,sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["PROGRAM_ARGV"]).write_text(json.dumps(sys.argv[1:]))\n'
        f'print({message!r})\n'
        f'sys.exit({native_rc})\n')
    binary.chmod(0o755)
    sof = tmp_path / 'image.sof'
    sof.write_bytes(b'programming fixture')
    command = [sys.executable, str(DRIVER), '--mode', 'program', '--json-args',
               json.dumps({'sof_path': str(sof), 'cable_name': 'test-cable', 'device_index': 2})]
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**os.environ, 'QUARTUS_ROOTDIR': str(root),
                                 'PROGRAM_ARGV': str(record)})
    body = json.loads(result.stdout)
    assert result.returncode == expected_rc, result.stdout + result.stderr
    assert json.loads(record.read_text()) == [
        '-m', 'JTAG', '-c', 'test-cable', '-o', f'p;{sof}@2']
    if error is None:
        assert body['success'] is True
        assert body['exit_code'] == native_rc
        assert body['stdout_tail'].strip() == message
    else:
        assert body['error_code'] == error
    assert not (tmp_path / 'reports').exists()


def test_missing_bitstream_stops_before_programmer(driver, tmp_path, monkeypatch):
    monkeypatch.setattr(driver, '_require_quartus_pgm',
                        lambda: pytest.fail('programmer must not run without its bitstream'))
    with pytest.raises(driver.InvalidArgumentError, match='sof_path not found'):
        driver.mode_program({'sof_path': str(tmp_path / 'missing.sof')})


def test_programmer_timeout_keeps_device_error(driver, tmp_path, monkeypatch):
    sof = tmp_path / 'image.sof'
    sof.write_bytes(b'fixture')
    monkeypatch.setattr(driver, '_require_quartus_pgm', lambda: 'quartus_pgm')
    monkeypatch.setattr(driver, 'run', lambda *args, **kwargs: (124, 'partial output', 'timeout'))
    with pytest.raises(driver.DeviceTimeoutError, match='burn timed out'):
        driver.mode_program({'sof_path': str(sof)})


@pytest.mark.parametrize('scope_success', [True, False])
def test_scope_result_keeps_measurement_limits(driver, tmp_path, monkeypatch, scope_success):
    sof = tmp_path / 'image.sof'
    sof.write_bytes(b'fixture')
    monkeypatch.setattr(driver, '_require_quartus_pgm', lambda: 'quartus_pgm')
    monkeypatch.setattr(driver, 'run', lambda *args, **kwargs: (0, 'Operations done', ''))
    check = {'name': 'periodic output', 'channel': 2, 'period_ms': 7,
             'pulse_min_us': 3, 'pulse_max_us': 9, 'expect': 'present'}
    observed = []
    def scope(value):
        observed.append(value)
        return {'name': value['name'], 'success': scope_success}
    monkeypatch.setattr(driver, '_run_post_burn_scope_check', scope)
    rc, body = driver.mode_program({'sof_path': str(sof), 'post_burn_scope_checks': [check]})
    assert observed == [check]
    assert rc == (0 if scope_success else 1)
    assert body['success'] is scope_success
    if not scope_success:
        assert body['failed_scope_checks'] == ['periodic output']

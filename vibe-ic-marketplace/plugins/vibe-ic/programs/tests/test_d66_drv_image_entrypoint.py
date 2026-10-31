"""Fresh DRV launches keep their guards on legacy and entrypoint-free images."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drv_signoff_capture as capture


def setup_launch(monkeypatch, entrypoint, *, inspect_rc=0, tool_text='OpenSTA\n'):
    launched = []
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '8g')
    monkeypatch.setattr(capture._ce, 'no_container_route', lambda: False)
    monkeypatch.setattr(capture.subprocess, 'run', lambda argv, **kw:
                        subprocess.CompletedProcess(argv, inspect_rc, json.dumps(entrypoint), ''))

    def supervised(argv, **kw):
        launched.append(argv)
        Path(kw['log_path']).write_text(tool_text)
        return SimpleNamespace(outcome='natural', rc=0, err='')

    monkeypatch.setattr(capture._watchdog, 'run_supervised', supervised)
    return launched


@pytest.mark.parametrize('entrypoint', [None, ['/entry.sh']])
def test_fresh_drv_image_launch(monkeypatch, tmp_path, entrypoint):
    launched = setup_launch(monkeypatch, entrypoint)
    script = tmp_path / 'measure.tcl'
    script.write_text('puts ready\n')
    capture._run_fresh(script, {tmp_path}, image='pinned-image')
    argv = launched[0]
    assert ('--entrypoint' in argv) == (not bool(entrypoint))
    assert ('--skip' in argv) == bool(entrypoint)
    assert argv[argv.index('--memory') + 1] == '8g'
    assert argv[argv.index('--memory-swap') + 1] == '8g'


def test_drv_unverified_image_never_launches(monkeypatch, tmp_path):
    launched = setup_launch(monkeypatch, None, inspect_rc=1)
    with pytest.raises(RuntimeError, match='entrypoint unverified'):
        capture._run_fresh(tmp_path / 'measure.tcl', {tmp_path}, image='pinned-image')
    assert not launched


def test_drv_tool_error_remains_refused(monkeypatch, tmp_path):
    setup_launch(monkeypatch, None, tool_text='Error: model absent\n')
    with pytest.raises(RuntimeError, match='tool_error=True'):
        capture._run_fresh(tmp_path / 'measure.tcl', {tmp_path}, image='pinned-image')


def test_drv_memory_opt_out_remains_refused(monkeypatch, tmp_path):
    launched = setup_launch(monkeypatch, None)
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', 'off')
    with pytest.raises(RuntimeError, match='memory ceiling unavailable'):
        capture._run_fresh(tmp_path / 'measure.tcl', {tmp_path}, image='pinned-image')
    assert not launched


def test_drv_version_probe_entrypoint_free_image(monkeypatch):
    setup_launch(monkeypatch, None)
    commands = []

    def run(argv, **kw):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0,
            'OPENROAD_BINARY /bin/openroad ' + 'ab' * 32 + ' 1.0-g1234567\n', '')

    result = capture.openroad_identity('pinned-image', run=run)
    assert result['commit'] == '1234567'
    assert '--entrypoint' in commands[0]
    assert '--skip' not in commands[0]

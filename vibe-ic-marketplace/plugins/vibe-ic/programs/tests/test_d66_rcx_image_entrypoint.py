"""The current RCX launch must respect the selected image's real entrypoint."""
import json
import subprocess
import sys
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librelane_contract as contract


@pytest.mark.parametrize('entrypoint', [None, [], ['/entry.sh']])
def test_image_entrypoint_selects_launch(monkeypatch, entrypoint):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if 'inspect' in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(entrypoint), '')
        return subprocess.CompletedProcess(argv, 0, 'executed', '')

    monkeypatch.setattr(contract.subprocess, 'run', run)
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    image = 'registry.invalid/eda@sha256:' + 'ab' * 32
    result = contract.run_container(
        ['docker', 'run', '--rm', '--entrypoint', 'python3', image, '-c', 'print(1)'],
        probe_deadline_s=5)
    assert result.returncode == 0
    launch = calls[-1]
    assert ('--skip' in launch) == bool(entrypoint)
    assert ('--entrypoint' in launch) == (not bool(entrypoint))
    assert launch[-2:] == ['-c', 'print(1)']


def test_unknown_image_entrypoint_refuses_before_launch(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, '', 'image inspect failed')

    monkeypatch.setattr(contract.subprocess, 'run', run)
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    image = 'registry.invalid/eda@sha256:' + 'ab' * 32
    with pytest.raises(contract.Refusal, match='LL_IMAGE_ENTRYPOINT_UNVERIFIED'):
        contract.run_container(
            ['docker', 'run', '--entrypoint', 'python3', image, '-c', 'print(1)'],
            probe_deadline_s=5)
    assert len(calls) == 1
    assert 'inspect' in calls[0]


@pytest.mark.parametrize('copy_succeeds', [True, False])
def test_materialise_readonly_pdk_links(monkeypatch, tmp_path, copy_succeeds):
    source = tmp_path / 'image-pdk'
    source.mkdir()
    config = tmp_path / 'image-owned-config'
    config.write_text('original pinned model bytes')
    (source / '.config').symlink_to(config)
    source.chmod(0o555)
    cache = tmp_path / 'cache'
    monkeypatch.setattr(contract, '_pdk_root_cache', lambda: cache)
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)

    def run(argv, **kwargs):
        if 'run' in argv and copy_succeeds:
            destination = Path(argv[-1])
            shutil.copytree(source, destination, symlinks=False)
            return subprocess.CompletedProcess(argv, 0, '', '')
        return subprocess.CompletedProcess(argv, 1, '', 'copy unavailable')

    monkeypatch.setattr(contract.subprocess, 'run', run)
    found = {'image_id': 'sha256:' + 'ab' * 32, 'pdk_root': '/image/pdks'}
    if copy_succeeds:
        root, mode = contract._materialise_image_pdk('image', found, 'sky130A', 'docker')
        result = root / 'sky130A/.config'
        assert mode == 'copied'
        assert result.read_text() == config.read_text()
        assert not result.is_symlink()
        assert contract._materialise_image_pdk('image', found, 'sky130A', 'docker') == (root, 'reused')
    else:
        with pytest.raises(contract.Refusal):
            contract._materialise_image_pdk('image', found, 'sky130A', 'docker')
        assert not list(cache.rglob('*' + contract.PDK_ROOT_MARKER))

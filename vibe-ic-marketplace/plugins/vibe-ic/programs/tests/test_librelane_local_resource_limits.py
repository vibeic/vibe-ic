"""Observe LOCAL resource translations in real child processes."""
import json
import os
from pathlib import Path
import resource
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librelane_contract as contract
from _hostpaths import require_repo
from test_librelane_contract import local_image, _host_provider


@pytest.fixture(params=['attested', 'provider'])
def target(request, local_image, tmp_path, monkeypatch):
    if request.param == 'provider':
        # The declared host namespace is this --network none test container.
        monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_NETWORK', 'host')
        _, image = _host_provider(tmp_path, monkeypatch)
        return SimpleNamespace(image=image, network='host', tmp=tmp_path)
    return SimpleNamespace(image=local_image.image, network='none', tmp=tmp_path)


REPORT = (
    'import json,os,resource; '
    'print(json.dumps({"affinity":sorted(os.sched_getaffinity(0)), '
    '"as":resource.getrlimit(resource.RLIMIT_AS), '
    '"pids":resource.getrlimit(resource.RLIMIT_NPROC)}))')


def _launch(target, options=(), *, command=None, **kwargs):
    return contract.run_container([
        'docker', 'run', '--rm', '--network', target.network,
        '--memory', '2g', '--memory-swap', '2g', *options, target.image,
        '--skip', *(command or [sys.executable, '-c', REPORT])],
        probe_deadline_s=5, **kwargs)


def _measure(target, options=()):
    result = _launch(target, options)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_memory_limit_is_applied_only_to_the_child(target):
    before = resource.getrlimit(resource.RLIMIT_AS)
    measured = _measure(target)
    assert measured['as'] == [2 * 1024**3, 2 * 1024**3]
    assert resource.getrlimit(resource.RLIMIT_AS) == before


@pytest.mark.parametrize('value,count', [('1', 1), ('1.5', 2)])
def test_cpu_limit_selects_from_inherited_affinity(target, value, count):
    allowed = sorted(os.sched_getaffinity(0))
    measured = _measure(target, ['--cpus', value])
    assert measured['affinity'] == allowed[:count]
    assert sorted(os.sched_getaffinity(0)) == allowed


@pytest.mark.parametrize('limit', [256, 512])
def test_pids_limit_is_applied_only_to_the_child(target, limit):
    before = resource.getrlimit(resource.RLIMIT_NPROC)
    measured = _measure(target, ['--pids-limit', str(limit)])
    assert measured['pids'] == [limit, limit]
    assert resource.getrlimit(resource.RLIMIT_NPROC) == before


def test_stricter_inherited_limits_are_preserved(target, monkeypatch):
    import _watchdog
    original = _watchdog.run_host_supervised
    inherit = (
        'import os,resource,sys; '
        'resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,)*2); '
        'resource.setrlimit(resource.RLIMIT_NPROC,(128,)*2); '
        'os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:1]); '
        'os.execvpe(sys.argv[1],sys.argv[1:],os.environ)')

    def inherited_child(command, **kwargs):
        return original([sys.executable, '-c', inherit, *command], **kwargs)

    monkeypatch.setattr(_watchdog, 'run_host_supervised', inherited_child)
    measured = _measure(target, ['--cpus', '4', '--pids-limit', '512'])
    assert measured['as'] == [256 * 1024**2, 256 * 1024**2]
    assert measured['pids'] == [128, 128]
    assert measured['affinity'] == sorted(os.sched_getaffinity(0))[:1]


def test_combined_limits_drive_an_existing_neutral_tool(target):
    tool = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                        'tests', 'fixtures', 'execution_modes_tool.py')
    inputs, outputs = target.tmp / 'inputs', target.tmp / 'outputs'
    inputs.mkdir()
    outputs.mkdir()
    (outputs / 'value.txt').write_text('CURRENT')
    result = _launch(target, ['--cpus', '4', '--pids-limit', '512'], command=[
        sys.executable, str(tool), str(inputs), str(outputs),
        'measure', 'none', '0', '1'],
        env={**os.environ, 'VIBEIC_EXECUTION_BINDING': '{"scope":"resource-control"}'})
    assert result.returncode == 0, result.stdout + result.stderr
    measured = json.loads((outputs / 'measurement.json').read_text())
    assert measured['affinity'] == sorted(os.sched_getaffinity(0))[:4]
    assert measured['address_space_limit'] == 2 * 1024**3
    assert measured['value'] == 'CURRENT'


@pytest.mark.parametrize('option,value', [
    ('--unknown-limit', '512'), ('--cpus', 'nan'), ('--cpus', '-1'),
    ('--pids-limit', '-2'), ('--pids-limit', '1.5'),
])
def test_unknown_or_invalid_limits_refuse_before_launch(monkeypatch, option, value):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid launch reached attestation or a child process')

    monkeypatch.setattr(contract, 'local_image_attestation', forbidden)
    monkeypatch.setattr(contract.subprocess, 'run', forbidden)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_LAUNCH_UNSUPPORTED'):
        contract._run_local(['docker', 'run', option, value, 'image', '--skip', 'tool'],
                            probe_deadline_s=1, supervised=False, log=None)

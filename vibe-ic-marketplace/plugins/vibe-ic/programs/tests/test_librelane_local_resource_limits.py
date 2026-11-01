"""Observe LOCAL resource translations in real child processes."""
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librelane_contract as contract
from _hostpaths import require_repo
from test_librelane_contract import local_image, _host_provider


@pytest.fixture(scope='module')
def systemd_user_manager():
    reason = 'requires a systemd user manager (host LOCAL route)'
    runner = shutil.which('systemd-run')
    if runner is None:
        pytest.skip(reason)
    try:
        result = subprocess.run(
            [runner, '--user', '--scope', '-q', '--', sys.executable, '-c', 'pass'],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip(reason)
    if result.returncode != 0:
        pytest.skip(reason)


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


FORK_REPORT = '''
import errno,json,os,resource,sys
from pathlib import Path
group=next(line.split(':',2)[2].strip() for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
folder=Path('/sys/fs/cgroup')/group.lstrip('/')
maximum=(folder/'pids.max').read_text().strip()
reader,writer=os.pipe()
children=[]
failure=None
try:
    for _ in range(int(sys.argv[1])):
        try:
            child=os.fork()
        except OSError as exc:
            failure=exc.errno
            break
        if child==0:
            os.close(writer)
            os.read(reader,1)
            os._exit(0)
        children.append(child)
    current=int((folder/'pids.current').read_text())
finally:
    os.close(writer)
    os.close(reader)
    for child in children:
        os.waitpid(child,0)
print(json.dumps(dict(uid=os.getuid(),group=group,maximum=maximum,current=current,
                     forked=len(children),failure=failure,nproc=resource.getrlimit(resource.RLIMIT_NPROC))))
'''


@pytest.mark.parametrize('limit,attempts,saturate', [(512, 3, False), (8, 16, True)])
def test_pids_scope_allows_nonroot_forks_and_enforces_its_own_limit(
        target, limit, attempts, saturate, systemd_user_manager):
    import errno
    before = resource.getrlimit(resource.RLIMIT_NPROC)
    parent_group = Path('/proc/self/cgroup').read_text()
    result = _launch(target, ['--pids-limit', str(limit)],
                     command=[sys.executable, '-c', FORK_REPORT, str(attempts)])
    assert result.returncode == 0, result.stdout + result.stderr
    measured = json.loads(result.stdout)
    print('LOCAL_SCOPE_FORK ' + json.dumps(measured, sort_keys=True))
    assert measured['uid'] != 0
    assert measured['forked'] >= 2
    assert measured['group'].endswith('.scope')
    assert measured['group'] not in parent_group
    assert measured['maximum'] == str(limit)
    assert measured['nproc'] == list(before)
    if saturate:
        assert measured['failure'] == errno.EAGAIN
        assert measured['current'] == limit
    else:
        assert measured['forked'] == attempts and measured['failure'] is None
    assert resource.getrlimit(resource.RLIMIT_NPROC) == before
    assert Path('/proc/self/cgroup').read_text() == parent_group


def test_unavailable_user_manager_refuses_without_starting_the_tool(target):
    marker = target.tmp / 'tool-must-not-run'
    command = [sys.executable, '-c', f'from pathlib import Path;Path({str(marker)!r}).touch()']
    with pytest.raises(contract.Refusal, match='LL_LOCAL_PIDS_LIMIT_UNENFORCEABLE'):
        _launch(target, ['--pids-limit', '512'], command=command,
                env={**os.environ, 'XDG_RUNTIME_DIR': str(target.tmp),
                     'DBUS_SESSION_BUS_ADDRESS': f'unix:path={target.tmp}/absent-bus'})
    assert not marker.exists()


def test_missing_scope_runner_refuses(target, monkeypatch):
    original = contract.shutil.which
    monkeypatch.setattr(contract.shutil, 'which',
                        lambda name, **kwargs: None if name == 'systemd-run' else original(name, **kwargs))
    with pytest.raises(contract.Refusal, match='LL_LOCAL_PIDS_LIMIT_UNENFORCEABLE'):
        _launch(target, ['--pids-limit', '512'])


def test_tool_failure_inside_a_working_scope_keeps_its_exit_code(target, systemd_user_manager):
    result = _launch(target, ['--pids-limit', '512'], command=[
        sys.executable, '-c',
        'import sys;print("Failed to connect to bus",file=sys.stderr);sys.exit(7)'])
    assert result.returncode == 7
    assert 'Failed to connect to bus' in result.stderr


def test_scoped_tool_receives_literal_arguments(target, systemd_user_manager):
    literal = '$HOME/${SCOPE_TEST_VALUE}'
    result = _launch(target, ['--pids-limit', '512'], command=[
        sys.executable, '-c', 'import sys;print(sys.argv[1])', literal])
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == literal


def test_stricter_inherited_limits_are_preserved(target, monkeypatch):
    import _watchdog
    original = _watchdog.run_host_supervised
    inherit = (
        'import os,resource,sys; '
        'resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,)*2); '
        'os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:1]); '
        'os.execvpe(sys.argv[1],sys.argv[1:],os.environ)')

    def inherited_child(command, **kwargs):
        return original([sys.executable, '-c', inherit, *command], **kwargs)

    monkeypatch.setattr(_watchdog, 'run_host_supervised', inherited_child)
    measured = _measure(target, ['--cpus', '4'])
    assert measured['as'] == [256 * 1024**2, 256 * 1024**2]
    assert measured['pids'] == list(resource.getrlimit(resource.RLIMIT_NPROC))
    assert measured['affinity'] == sorted(os.sched_getaffinity(0))[:1]


def test_combined_limits_drive_an_existing_neutral_tool(target, systemd_user_manager):
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

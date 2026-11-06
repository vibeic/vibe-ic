"""Installed Ultra source admission through the real canonical CLI, never an IC.

FROZEN_OFFICIAL_RESPONSE_SEAM: the positive installation response is assembled
from the exact local candidate's real Git objects. The candidate may be unpublished;
this fixture does not claim that its version tag resolves to it on GitHub. Shipping
must additionally exercise the actual official release after publication.

The GitHub response contract follows the observed official v1.29.90 HTTP result:
GET git/trees/<commit> reports that requested commit in response.sha, not its tree.
Resolve GET git/commits/<commit>.tree.sha before GET git/trees/<actual-tree>.
"""
from contextlib import contextmanager
import copy
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tarfile

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_INSTALL_REVIEW_PROGRAMS',
                              str(Path(__file__).resolve().parent.parent))).resolve()
sys.path.insert(0, str(PROGRAMS))
PREFIX = 'vibe-ic-marketplace/plugins/vibe-ic/'


def _git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


@pytest.fixture(scope='module')
def frozen_package(tmp_path_factory):
    """Export actual committed source, including its complete official file set."""
    plugin = PROGRAMS.parent
    repo = Path(_git(plugin, 'rev-parse', '--show-toplevel').decode().strip())
    revision = _git(repo, 'rev-parse', 'HEAD').decode().strip()
    tree = _git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip()
    package = tmp_path_factory.mktemp('source3186') / 'installed cache with spaces' / 'vibe-ic'
    package.mkdir(parents=True)
    archive = _git(repo, 'archive', revision + ':' + PREFIX.rstrip('/'))
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            relative = Path(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts
            target = package / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.extractfile(member).read())
                target.chmod(member.mode)
            elif member.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
    assert subprocess.run(['git', '-C', str(package), 'rev-parse', '--show-toplevel'],
                          capture_output=True).returncode != 0
    version = json.loads((package / '.claude-plugin/plugin.json').read_text())['version']
    rows = []
    for record in _git(repo, 'ls-tree', '-r', '-t', '-z', revision).split(b'\0'):
        if record:
            header, name = record.split(b'\t', 1)
            mode, kind, sha = header.decode().split()
            rows.append(dict(path=name.decode(), mode=mode, type=kind, sha=sha))
    return dict(package=package, revision=revision, tree=tree, version=version, rows=rows)


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache = tmp_path / 'installation-cache'
    monkeypatch.setenv('XDG_CACHE_HOME', str(cache))
    return cache


def _official_fixture(source, frozen_package, calls, *, tree_response_sha=None):
    """Use the real HTTP shapes, including the legacy commit-as-tree request."""
    tag_url = source.API + '/git/ref/tags/v' + frozen_package['version']
    commit_url = source.API + '/git/commits/' + frozen_package['revision']
    tree_url = source.API + '/git/trees/' + frozen_package['tree'] + '?recursive=1'
    legacy_tree_url = source.API + '/git/trees/' + frozen_package['revision'] + '?recursive=1'

    def frozen_official_response(url):
        calls.append(url)
        if url == tag_url:
            return {'object': {'type': 'commit', 'sha': frozen_package['revision']}}
        if url == commit_url:
            return {'sha': frozen_package['revision'], 'tree': {'sha': frozen_package['tree']}}
        assert url in (tree_url, legacy_tree_url), url
        # The legacy shape must expose the published v90 defect rather than
        # silently replacing its response.sha with the desired true tree.
        sha = ((tree_response_sha or frozen_package['tree'])
               if url == tree_url else frozen_package['revision'])
        return dict(sha=sha, truncated=False, tree=copy.deepcopy(frozen_package['rows']))

    return frozen_official_response, [tag_url, commit_url, tree_url]


@pytest.fixture
def prepared(frozen_package, isolated_cache, monkeypatch):
    import execution_source_identity as source
    calls = []
    response, expected_calls = _official_fixture(source, frozen_package, calls)

    monkeypatch.setattr(source, '_official_json', response)
    record = source.prepare_installed(frozen_package['package'])
    frozen_package['transport_calls'] = calls
    frozen_package['expected_transport_calls'] = expected_calls
    identity = source.current(frozen_package['package'])
    assert identity.kind == 'installed'
    assert identity.revision == frozen_package['revision']
    print('FROZEN_OFFICIAL_RESPONSE_SEAM ' + json.dumps({
        'revision': identity.revision, 'version': frozen_package['version'],
        'not_a_live_official_release_claim': True, 'transport_calls': calls}))
    return source, frozen_package['package'], record, identity


@contextmanager
def _changed(path, content):
    original = path.read_bytes()
    path.write_bytes(content)
    try:
        yield
    finally:
        path.write_bytes(original)


def _canonical_issue(package, project, *, bootstrap=False):
    """Use the actual CLI/issuer/consumer and close only this owned transport."""
    project.mkdir(parents=True, exist_ok=True)
    parent, child = socket.socketpair()
    child.set_inheritable(True)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('GIT_', 'VIBEIC_EXECUTION_', 'VIBEIC_LIBRELANE_'))}
    environment.pop('VIBEIC_IC_IP_ROUTE', None)
    environment.update(PYTHONDONTWRITEBYTECODE='1', CLAUDE_PLUGIN_ROOT=str(package),
                       VIBE_IC_PROGRAMS_DIR=str(package / 'programs'))
    # A prepared package must consume its cached source receipt offline.
    environment.update(HTTPS_PROXY='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9', NO_PROXY='')
    argv = [sys.executable, '-I', str(package / 'programs/vibe_ic_one_shot_runner.py'),
            str(project), '--route', 'ic', '--execution-mode', 'ultra',
            '--route-authority-only', '--receipt-channel-fd', str(child.fileno()),
            '--no-dashboard']
    received_fd = None
    stdout_path, stderr_path = project.parent / (project.name + '.stdout'), project.parent / (project.name + '.stderr')
    with stdout_path.open('w') as stdout, stderr_path.open('w') as stderr:
        proc = subprocess.Popen(argv, cwd=project.parent, env=environment,
                                pass_fds=(child.fileno(),), stdout=stdout, stderr=stderr,
                                start_new_session=True)
        child.close()
        parent.settimeout(60)
        payload = None
        try:
            data, ancillary, _, _ = parent.recvmsg(131072, socket.CMSG_SPACE(4))
            if data:
                while b'\n' not in data:
                    part = parent.recv(4096)
                    assert part, 'canonical receipt channel ended inside JSON'
                    data += part
                    assert len(data) <= 131072
                assert ancillary and ancillary[0][0:2] == (socket.SOL_SOCKET, socket.SCM_RIGHTS)
                received_fd = struct.unpack('i', ancillary[0][2][:4])[0]
                payload = json.loads(data.split(b'\n', 1)[0])
                if bootstrap:
                    consumer_env = dict(environment, VIBEIC_EXECUTION_CAP_FD=str(received_fd),
                                        VIBEIC_EXECUTION_AUTH_SOCKET=payload['socket'])
                    consumer = r"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
import execution_policy as policy
policy.configure(SimpleNamespace())
runtime=policy.bootstrap(Path(sys.argv[2]),phase1_only=True)
assert runtime['policy']['mode']=='ultra',runtime
assert runtime['registry'].adapters('0.5ic'),runtime
print('INSTALLED_ULTRA_REGISTRY_READY_NO_PRODUCER')
"""
                    checked = subprocess.run([sys.executable,'-I','-c',consumer,
                                              str(package/'programs'),str(project)],
                                             env=consumer_env,cwd=project.parent,
                                             pass_fds=(received_fd,),capture_output=True,
                                             text=True,timeout=60)
                    (project.parent/(project.name+'.bootstrap.stdout')).write_text(checked.stdout)
                    (project.parent/(project.name+'.bootstrap.stderr')).write_text(checked.stderr)
                    assert checked.returncode==0,checked.stdout+checked.stderr
                    assert 'INSTALLED_ULTRA_REGISTRY_READY_NO_PRODUCER' in checked.stdout
        finally:
            parent.close()
            if received_fd is not None:
                os.close(received_fd)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
                pytest.fail('owned canonical issuer did not finish after receipt transport EOF')
    result = dict(argv=argv, pid=proc.pid, returncode=proc.returncode, payload=payload,
                  stdout=stdout_path.read_text(), stderr=stderr_path.read_text())
    (project.parent / (project.name + '.invocation.json')).write_text(json.dumps(result, indent=2))
    assert not any((project / name).exists() for name in ('phase1', 'phase2', 'phase3'))
    return result


def test_official_installed_package_issues_actual_ultra_route(prepared, frozen_package, tmp_path):
    source, package, record, identity = prepared
    result = _canonical_issue(package, tmp_path / 'legitimate', bootstrap=True)
    assert result['returncode'] == 0, result
    payload = result['payload']
    assert payload['request']['mode'] == 'ultra'
    assert payload['request']['intent_label'] == 'USER_EXPLICIT_ULTRA'
    assert payload['route']['source_sha'] == identity.revision
    # Check the actual CLI result against the real Git object, independently
    # of whatever tree the source manifest happened to record.
    assert payload['route']['source_tree'] == frozen_package['tree']
    assert identity.tree == frozen_package['tree']
    assert frozen_package['transport_calls'] == frozen_package['expected_transport_calls']
    assert payload['source_blobs']
    assert payload['issuer_blob'] == record['files']['programs/execution_authority.py']['blob']
    assert source.current(package).revision == identity.revision


def test_official_tree_response_must_match_commit_tree(frozen_package, isolated_cache, monkeypatch):
    import execution_source_identity as source
    calls = []
    response, expected_calls = _official_fixture(source, frozen_package, calls,
                                                tree_response_sha='0' * 40)
    monkeypatch.setattr(source, '_official_json', response)
    with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_UNAVAILABLE: incomplete official tree'):
        source.prepare_installed(frozen_package['package'])
    assert calls == expected_calls
    assert not source.receipt_path(frozen_package['package']).exists()




@pytest.mark.parametrize('field', ['revision', 'tree'])
def test_rehashed_forged_receipt_cannot_choose_other_source(prepared, tmp_path, field):
    source, package, record, _ = prepared
    forged = copy.deepcopy(record)
    forged[field] = '0' * 40
    forged.pop('receipt_sha256')
    # Rehash through the producer's one format; no duplicate manifest encoder.
    forged['receipt_sha256'] = source._sha(source._encoded(forged))
    path = source.receipt_path(package)
    with _changed(path, source._encoded(forged)):
        with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_UNAVAILABLE'):
            source.current(package)
        result = _canonical_issue(package, tmp_path / ('forged-' + field))
        assert result['returncode'] != 0 and result['payload'] is None, result
        assert 'SOURCE_AUTHORITY_' in result['stderr'], result


@pytest.mark.parametrize('damage', ['missing', 'stale-live', 'foreign-root'])
def test_missing_stale_or_foreign_installed_state_refuses_offline(prepared, tmp_path, damage):
    source, package, record, identity = prepared
    def network_forbidden(_url):
        raise AssertionError('offline current() attempted installation transport')
    source._official_json = network_forbidden
    path = source.receipt_path(package)
    if damage == 'missing':
        original = path.read_bytes()
        path.unlink()
        try:
            with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_UNAVAILABLE'):
                source.current(package)
        finally:
            path.write_bytes(original)
    elif damage == 'stale-live':
        with _changed(path, path.read_bytes() + b'\n'):
            with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_STALE'):
                identity.verify_current()
    else:
        foreign = tmp_path / 'foreign installation'
        shutil.copytree(package, foreign)
        copied = source.receipt_path(foreign)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(source._encoded(record))
        with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_UNAVAILABLE'):
            source.current(foreign)


def test_development_source_keeps_git_and_dirty_currentness(tmp_path, monkeypatch):
    import execution_source_identity as source
    repo = tmp_path / 'development'
    package = repo / PREFIX.rstrip('/')
    file = package / 'programs/neutral_source.py'
    file.parent.mkdir(parents=True)
    file.write_text('VALUE = 1\n')
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    commit = ['git', '-C', str(repo), '-c', 'user.name=Source Fixture',
              '-c', 'user.email=source-fixture@example.invalid', '-c', 'commit.gpgsign=false',
              'commit', '-qm', 'Neutral source fixture']
    subprocess.run(commit, check=True)
    def network_forbidden(_url):
        raise AssertionError('development Git path contacted installation transport')
    monkeypatch.setattr(source, '_official_json', network_forbidden)
    assert source.prepare_installed(package)['kind'] == 'git'
    identity = source.current(package)
    assert identity.kind == 'git' and identity.root == repo
    original = file.read_bytes()
    assert identity.verify(file)
    file.write_bytes(original + b'# controlled drift\n')
    with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_DIRTY'):
        identity.verify(file)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(commit, check=True)
    with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_STALE'):
        identity.verify_current()


def test_installed_default_offline_without_source_receipt(frozen_package, isolated_cache, tmp_path):
    package = frozen_package['package']
    project = tmp_path / 'default-project'
    constraints = project / 'phase2/stage2/constraints/constraint.sdc'
    constraints.parent.mkdir(parents=True)
    real_sdc = package / 'programs/tests/fixtures/ppa/power/activity_basis_pair/constraint.sdc'
    constraints.write_bytes(real_sdc.read_bytes())
    l8 = project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json'
    l8.parent.mkdir(parents=True)
    l8.write_text('{"clocks":{}}\n')
    switch = project / 'phase3/librelane_switch.json'
    switch.parent.mkdir()
    switch.write_text('{"steps":{"8":"direct"}}\n')
    script = r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import execution_policy as policy
import step_preflight as preflight
import design_one_shot_runner as design
project=Path(sys.argv[2])
assert policy.bootstrap(project)['policy']['mode']=='default'
result=preflight.retained_call(project,'8',design.step_sdc_validation,project)
assert result.status=='PASS',result
report=json.loads((project/'reports/sdc_validator.json').read_text())
assert report['verdict']=='PASS',report
print('DEFAULT_OFFLINE_REAL_SDC_PASS')
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'VIBEIC_EXECUTION_', 'VIBEIC_LIBRELANE_'))}
    env.pop('VIBEIC_IC_IP_ROUTE', None)
    env.update(PYTHONDONTWRITEBYTECODE='1', CLAUDE_PLUGIN_ROOT=str(package),
               VIBE_IC_PROGRAMS_DIR=str(package / 'programs'), HTTPS_PROXY='http://127.0.0.1:9',
               HTTP_PROXY='http://127.0.0.1:9', NO_PROXY='')
    result = subprocess.run([sys.executable, '-I', '-c', script, str(package / 'programs'), str(project)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    (tmp_path / 'default-offline.stdout').write_text(result.stdout)
    (tmp_path / 'default-offline.stderr').write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DEFAULT_OFFLINE_REAL_SDC_PASS' in result.stdout
    assert not list(isolated_cache.rglob('*.json'))

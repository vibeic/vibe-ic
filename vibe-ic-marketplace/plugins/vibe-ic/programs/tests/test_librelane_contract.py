"""Real contract consumer with EDA file writes substituted at the process edge."""
import importlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
container_exec = importlib.import_module('_container_exec')
eda_pin = importlib.import_module('_eda_pin')


@pytest.fixture(autouse=True)
def legacy_fixture_image_metadata(monkeypatch):
    """These fictional transport fixtures model the legacy EDA environment.

    Real native/legacy launch inspection is covered separately by
    test_native_image_tool_launch; do not inspect a fictional registry here.
    """
    monkeypatch.setattr(contract, '_image_entrypoint',
                        lambda docker, image: ['/dockerstartup/scripts/ui_startup.sh'])


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


@pytest.fixture
def local_image(tmp_path, monkeypatch, request):
    """Host launch receipt shape, without asking the host for an image."""
    cid, image_id = 'ab' * 32, 'sha256:' + 'cd' * 32
    image = 'registry.invalid/tools@sha256:' + 'ef' * 32
    local_id = getattr(request, 'param', None) == 'local_image_id'
    if local_id:
        image = image_id
    receipt = put(tmp_path / 'launch_identity.json', {
        'image': image, 'cid': cid,
        'image_inspect': [{'Id': image_id, 'RepoDigests': [] if local_id else [image]}],
        'container_inspect': {'Id': cid, 'Image': image_id,
            'Config': {'Hostname': cid[:12], 'Image': image},
            'HostConfig': {'NetworkMode': 'none', 'Memory': 2 * 1024**3,
                           'MemorySwap': 2 * 1024**3, 'AutoRemove': True},
            'State': {'Running': True, 'Paused': False, 'Dead': False}}})
    monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', str(receipt))
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', image)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: True)
    monkeypatch.setattr(socket, 'gethostname', lambda: cid[:12])
    # The pre-fix arm cannot pull a fictional fixture image. Native processes
    # still run normally; only an attempted Docker edge is the absent client.
    original_run = subprocess.run
    def no_docker(argv, **kw):
        if argv[0] == 'docker':
            return subprocess.CompletedProcess(argv, 125, '', 'NO_DOCKER_IN_IMAGE')
        return original_run(argv, **kw)
    monkeypatch.setattr(subprocess, 'run', no_docker)
    return SimpleNamespace(image=image, receipt=receipt, tmp=tmp_path)


@pytest.mark.parametrize('local_image', ['registry_digest', 'local_image_id'], indirect=True)
def test_local_resolver_requires_host_cid_and_records_provenance(local_image):
    project = local_image.tmp / 'project'
    (project / 'phase3').mkdir(parents=True)
    try:
        resolved = contract.resolve_image(project)
    except contract.Refusal as exc:
        resolved = str(exc)
    assert resolved == local_image.image
    recorded = json.loads((project / 'phase3/librelane_image.provenance.json').read_text())
    assert recorded['attestation_sha256'] == contract.digest(local_image.receipt)
    assert recorded['repo_digests'] == ([] if local_image.image.startswith('sha256:') else [local_image.image])
    assert recorded['image_id'] == 'sha256:' + 'cd' * 32
    local_image.receipt.unlink()
    with pytest.raises(contract.Refusal, match='LL_LOCAL_IMAGE_UNATTESTED'):
        contract.resolve_image(project)


def test_generic_no_container_route_keeps_legacy_attested_image(tmp_path, monkeypatch):
    pdk_root = tmp_path / 'pdk-root'
    pdk_root.mkdir()
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(pdk_root))
    monkeypatch.delenv(contract.LOCAL_PROVIDER_ROUTE_ENV, raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_ROOT', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: True)
    calls = []

    def legacy_attestation(image):
        calls.append(image)
        return {'image': 'legacy-attested-image'}

    monkeypatch.setattr(contract, 'local_image_attestation', legacy_attestation)
    assert contract.resolve_image(None) == 'legacy-attested-image'
    assert calls == [None]


def test_declared_host_provider_bypasses_image_resolution_and_binds_pdk(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / 'phase3').mkdir(parents=True)
    pdk_root = tmp_path / 'pdk-root'
    pdk_root.mkdir()
    librelane_root = tmp_path / 'librelane'
    (librelane_root / 'librelane').mkdir(parents=True)
    (librelane_root / 'VERSION').write_text('host-provider')
    (librelane_root / 'librelane/__init__.py').write_text('MARKER = "bound-source"\n')
    put(project / 'phase3/librelane_switch.json', {
        'execution_route': 'LOCAL', 'pdk': 'gf180mcuD',
        'pdk_root_host': str(pdk_root),
        'librelane_root_host': str(librelane_root)})
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: False)
    monkeypatch.setattr(eda_pin, 'image_reference',
                        lambda: (_ for _ in ()).throw(AssertionError('image resolver ran')))

    image = contract.resolve_image(project)
    assert isinstance(image, contract.LocalProviderIdentity)
    assert image.route == 'LOCAL'
    assert image.provider == 'host-owned-librelane'
    answer = contract.pdk_root_resolution(project, 'gf180mcuD', image=image)
    assert answer['source'] == 'local_provider'
    assert answer['path'] == str(pdk_root.resolve())
    assert answer['provider']['reference'] == str(image)
    assert json.loads((project / 'phase3/librelane_pdk_root.provenance.json').read_text()) == answer
    capability = contract.image_capability(image)
    assert capability['execution_route'] == 'LOCAL'
    assert capability['tcl_probe'].startswith('NOT_MEASURED:')


def _host_provider(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / 'phase3').mkdir(parents=True)
    pdk_root = tmp_path / 'pdk-root'
    pdk_root.mkdir()
    source_root = tmp_path / 'librelane'
    (source_root / 'librelane').mkdir(parents=True)
    (source_root / 'VERSION').write_text('host-provider')
    (source_root / 'librelane/__init__.py').write_text('MARKER = "bound-source"\n')
    put(project / 'phase3/librelane_switch.json', {
        'execution_route': 'LOCAL', 'pdk': 'gf180mcuD',
        'pdk_root_host': str(pdk_root),
        'librelane_root_host': str(source_root),
        'librelane_executable': sys.executable})
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: False)
    return project, contract.resolve_image(project)


def test_local_provider_subprocess_edge_executes_native_child_with_bounds(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    docker_calls = []
    original_run = subprocess.run

    def forbid_docker(argv, **kwargs):
        if argv and argv[0] == 'docker':
            docker_calls.append(argv)
            raise AssertionError('typed LOCAL provider reached Docker')
        return original_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'run', forbid_docker)
    script = ('import os,resource,librelane; '
              'print(resource.getrlimit(resource.RLIMIT_AS)[0]); '
              'print(os.readlink("/proc/self/ns/net")); '
              'print(os.environ["VIBEIC_LOCAL_NETWORK_MODE"]); '
              'print(librelane.__file__)')
    result = contract.run_container([
        'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
        '--entrypoint', sys.executable, image, '-c', script], probe_deadline_s=5)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert int(lines[0]) <= 256 * 1024 * 1024
    assert lines[2] == 'none'
    assert lines[1] != os.readlink('/proc/self/ns/net')
    assert lines[3].startswith(str(tmp_path / 'librelane'))
    assert docker_calls == []


def test_local_provider_source_mutation_refuses_before_subprocess(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    (tmp_path / 'librelane/VERSION').write_text('changed-after-admission')
    with pytest.raises(contract.Refusal, match='LL_LOCAL_SOURCE_CHANGED'):
        contract.run_container([
            'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
            '--entrypoint', sys.executable, image, '-c', 'raise SystemExit(0)'],
            probe_deadline_s=1)


def test_local_provider_source_mutation_during_subprocess_refuses_afterward(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    script = f'from pathlib import Path;Path({str(tmp_path / "librelane/VERSION")!r}).write_text("changed-during-run")'
    with pytest.raises(contract.Refusal, match='LL_LOCAL_SOURCE_CHANGED'):
        contract.run_container([
            'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
            '--entrypoint', sys.executable, image, '-c', script],
            probe_deadline_s=1)


def test_local_provider_tool_fail_precedes_postrun_identity_drift(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    script = (f'from pathlib import Path;Path({str(tmp_path / "librelane/VERSION")!r}).write_text("changed-during-run");'
              'raise SystemExit(7)')
    result = contract.run_container([
        'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
        '--entrypoint', sys.executable, image, '-c', script], probe_deadline_s=1)
    assert result.returncode == 7
    assert 'LL_LOCAL_SOURCE_CHANGED' in result.stderr


def test_local_provider_executable_mismatch_refuses_before_subprocess(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_EXECUTABLE_MISMATCH'):
        contract.run_container([
            'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
            '--entrypoint', '/bin/sh', image, '-c', 'true'], probe_deadline_s=1)


def test_local_provider_scan_ignores_provider_text_outside_image(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    docker_calls = []

    def record_docker(argv, **kwargs):
        docker_calls.append(argv)
        return subprocess.CompletedProcess(argv, 125, '', 'reverse Docker edge')

    monkeypatch.setattr(subprocess, 'run', record_docker)
    remote_image = 'registry.invalid/remote-image'
    script = f'print({str(image)!r})'
    result = contract.run_container([
        'docker', 'run', '--memory', '256m', '--memory-swap', '256m', '--rm',
        '--entrypoint', sys.executable, remote_image, '-c', script],
        probe_deadline_s=1)
    assert result.returncode == 125
    assert docker_calls and docker_calls[0][0:2] == ['docker', 'run']


def test_local_provider_reverse_without_registered_identity_uses_docker_edge(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    monkeypatch.delitem(contract._LOCAL_PROVIDER_IDENTITIES, str(image), raising=False)
    monkeypatch.setenv(contract.LOCAL_PROVIDER_ROUTE_ENV, 'LOCAL')
    docker_calls = []

    def record_docker(argv, **kwargs):
        docker_calls.append(argv)
        return subprocess.CompletedProcess(argv, 125, '', 'reverse Docker edge')

    monkeypatch.setattr(subprocess, 'run', record_docker)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_REMOTE_MISMATCH'):
        contract.run_container([
            'docker', 'run', '--cpus', '1', '--memory', '256m', '--memory-swap', '256m', '--rm',
            '--entrypoint', sys.executable, str(image), '-c', 'raise SystemExit(0)'],
            probe_deadline_s=1)
    assert docker_calls == []


def test_local_provider_unresolved_option_refuses_without_docker_fallback(tmp_path, monkeypatch):
    _project, image = _host_provider(tmp_path, monkeypatch)
    monkeypatch.setenv(contract.LOCAL_PROVIDER_ROUTE_ENV, 'LOCAL')
    docker_calls = []

    def record_docker(argv, **kwargs):
        docker_calls.append(argv)
        return subprocess.CompletedProcess(argv, 125, '', 'unexpected Docker fallback')

    monkeypatch.setattr(subprocess, 'run', record_docker)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_IMAGE_UNRESOLVABLE'):
        contract.run_container([
            'docker', 'run', '--unknown-value', '1', '--memory', '256m',
            '--memory-swap', '256m', '--rm', '--entrypoint', sys.executable,
            str(image), '-c', 'raise SystemExit(0)'], probe_deadline_s=1)
    assert docker_calls == []


def test_local_provider_refuses_remote_and_untyped_image_mismatch(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / 'phase3').mkdir(parents=True)
    pdk_root = tmp_path / 'pdk-root'
    pdk_root.mkdir()
    source_root = tmp_path / 'librelane'
    (source_root / 'librelane').mkdir(parents=True)
    (source_root / 'VERSION').write_text('host-provider')
    (source_root / 'librelane/__init__.py').write_text('MARKER = "bound-source"\n')
    put(project / 'phase3/librelane_switch.json', {
        'execution_route': 'LOCAL', 'pdk': 'gf180mcuD',
        'pdk_root_host': str(pdk_root), 'librelane_root_host': str(source_root)})
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: False)
    image = contract.resolve_image(project)
    switch = json.loads((project / 'phase3/librelane_switch.json').read_text())
    switch['execution_route'] = 'REMOTE'
    put(project / 'phase3/librelane_switch.json', switch)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_REMOTE_MISMATCH'):
        contract.pdk_root_resolution(project, 'gf180mcuD', image=image)

    switch['execution_route'] = 'LOCAL'
    put(project / 'phase3/librelane_switch.json', switch)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_REMOTE_MISMATCH'):
        contract.pdk_root_resolution(project, 'gf180mcuD',
                                     image='registry.invalid/librelane@sha256:' + 'ab' * 32)


@pytest.mark.parametrize('change', ['cid', 'image', 'hostname', 'stopped', 'duplicate'])
@pytest.mark.parametrize('local_image', ['registry_digest', 'local_image_id'], indirect=True)
def test_local_changed_identity_refuses_before_execution(local_image, change):
    record = json.loads(local_image.receipt.read_text())
    if change == 'cid':
        record['cid'] = '11' * 32
    elif change == 'image':
        record['image'] = 'registry.invalid/tools@sha256:' + '12' * 32
    elif change == 'hostname':
        record['container_inspect']['Config']['Hostname'] = 'different'
    elif change == 'stopped':
        record['container_inspect']['State']['Running'] = False
    put(local_image.receipt, record)
    if change == 'duplicate':
        local_image.receipt.write_text('{"cid":"bad",' + local_image.receipt.read_text()[1:])
    marker = local_image.tmp / 'should-not-exist'
    with pytest.raises(contract.Refusal, match='LL_LOCAL_IMAGE_UNATTESTED'):
        contract.run_container(['docker', 'run', '--rm', '--entrypoint', sys.executable,
            local_image.image, '-c', f'from pathlib import Path;Path({str(marker)!r}).touch()'],
            probe_deadline_s=3)
    assert not marker.exists()


def test_local_pdk_reads_native_tree_without_docker_copy(local_image, monkeypatch):
    root = local_image.tmp / 'native-pdks'
    (root / 'processA').mkdir(parents=True)
    monkeypatch.setenv('PDK_ROOT', str(root))
    answer = contract.pdk_root_resolution(pdk='processA', image=local_image.image)
    assert answer['path'] == str(root)
    assert answer['derivation']['cache'] == 'native'
    with pytest.raises(contract.Refusal, match='LL_IMAGE_PDK_ABSENT'):
        contract.pdk_root_resolution(pdk='missing', image=local_image.image)


@pytest.mark.parametrize('supervised', [False, True])
@pytest.mark.parametrize('local_image', ['registry_digest', 'local_image_id'], indirect=True)
def test_local_execution_maps_mounts_env_and_preserves_tool_rc(local_image, supervised):
    source = local_image.tmp / 'mount'
    source.mkdir()
    (source / 'input.txt').write_text('current bytes')
    script = 'import os,sys;from pathlib import Path;print(Path("/pdk/input.txt").read_text());print(os.environ["OWNED_ROOT"]);sys.exit(124)'
    result = contract.run_container(['docker', 'run', '--memory', '2g', '--memory-swap', '2g',
        '--rm', '-v', f'{source}:/pdk:ro', '-e', 'OWNED_ROOT=/pdk',
        '--entrypoint', sys.executable, local_image.image, '-c', script],
        **({'supervised': True} if supervised else {'probe_deadline_s': 3}))
    assert result.returncode == 124  # a natural tool rc is not a timeout
    assert result.stdout.splitlines() == ['current bytes', str(source)]


def test_local_attestation_change_during_probe_refuses_result(local_image):
    script = f'from pathlib import Path;p=Path({str(local_image.receipt)!r});p.write_text(p.read_text()+" ")'
    with pytest.raises(contract.Refusal, match='LL_LOCAL_ATTESTATION_CHANGED'):
        contract.run_container(['docker', 'run', '--rm', local_image.image, '--skip',
                                sys.executable, '-c', script], probe_deadline_s=3)


@pytest.mark.parametrize('network_mode', ['bridge', 'none', None])
@pytest.mark.parametrize('supervised', [False, True])
def test_local_network_none_requires_current_outer_isolation(local_image, network_mode, supervised):
    record = json.loads(local_image.receipt.read_text())
    record['container_inspect']['HostConfig']['NetworkMode'] = network_mode
    put(local_image.receipt, record)
    marker = local_image.tmp / 'tool-executed'
    argv = ['docker', 'run', '--rm', '--network', 'none', local_image.image,
            '--skip', sys.executable, '-c',
            f'from pathlib import Path;Path({str(marker)!r}).write_text("current tool bytes")']
    bounds = {'supervised': True} if supervised else {'probe_deadline_s': 3}
    if network_mode == 'none':
        result = contract.run_container(argv, **bounds)
        assert result.returncode == 0
        assert marker.read_text() == 'current tool bytes'
    else:
        with pytest.raises(contract.Refusal, match='LL_LOCAL_NETWORK_UNATTESTED'):
            contract.run_container(argv, **bounds)
        assert not marker.exists()


@pytest.mark.parametrize('field,option,code', [
    ('Memory', '--memory', 'LL_LOCAL_MEMORY_UNATTESTED'),
    ('MemorySwap', '--memory-swap', 'LL_LOCAL_SWAP_UNATTESTED')])
@pytest.mark.parametrize('actual', [1024**3, 2 * 1024**3, 3 * 1024**3, 0, -1, None, True])
def test_local_requested_memory_requires_finite_outer_bound(local_image, field, option, code, actual):
    record = json.loads(local_image.receipt.read_text())
    record['container_inspect']['HostConfig'][field] = actual
    put(local_image.receipt, record)
    marker = local_image.tmp / 'bounded-tool-executed'
    argv = ['docker', 'run', option, '2g', '--rm', local_image.image,
            '--skip', sys.executable, '-c',
            f'from pathlib import Path;Path({str(marker)!r}).touch()']
    if type(actual) is int and 0 < actual <= 2 * 1024**3:
        assert contract.run_container(argv, probe_deadline_s=3).returncode == 0
        assert marker.is_file()
    else:
        with pytest.raises(contract.Refusal, match=code):
            contract.run_container(argv, probe_deadline_s=3)
        assert not marker.exists()


@pytest.mark.parametrize('actual', [True, False, None, 1])
def test_local_rm_requires_current_outer_auto_remove(local_image, actual):
    record = json.loads(local_image.receipt.read_text())
    record['container_inspect']['HostConfig']['AutoRemove'] = actual
    put(local_image.receipt, record)
    marker = local_image.tmp / 'removed-tool-executed'
    argv = ['docker', 'run', '--rm', local_image.image, '--skip', sys.executable,
            '-c', f'from pathlib import Path;Path({str(marker)!r}).touch()']
    if actual is True:
        assert contract.run_container(argv, probe_deadline_s=3).returncode == 0
        assert marker.is_file()
    else:
        with pytest.raises(contract.Refusal, match='LL_LOCAL_AUTOREMOVE_UNATTESTED'):
            contract.run_container(argv, probe_deadline_s=3)
        assert not marker.exists()


def test_local_config_resolution_preserves_declared_mount_paths(local_image, monkeypatch):
    import ast
    root = local_image.tmp / 'native-pdk'
    root.mkdir()
    (root / 'cells.lib').write_text('native library bytes')
    source = put(local_image.tmp / 'declared.json', {
        'meta': {'step': 'Yosys.Synthesis'}, 'SYNTH_LIB': ['/pdk/cells.lib']})
    before = source.read_bytes()
    output = local_image.tmp / 'resolved.json'
    def resolver_edge(argv, **kw):
        script = argv[-1]
        projected = Path(ast.literal_eval(script.split('p=', 1)[1].split('; out=', 1)[0]))
        config = json.loads(projected.read_text())
        if not Path(config['SYNTH_LIB'][0]).is_file():
            return subprocess.CompletedProcess(argv, 1, '', 'declared library is not readable')
        put(output, config)
        return subprocess.CompletedProcess(argv, 0, '', '')
    monkeypatch.setattr(contract, 'run_container', resolver_edge)
    try:
        resolved = contract.resolve_step_config(local_image.tmp, local_image.image,
            source, output, mounts=[(root, '/pdk')], pdk_root='/pdk')
    except contract.Refusal as exc:
        resolved = str(exc)
    assert resolved == output
    assert json.loads(output.read_text())['SYNTH_LIB'] == [str(root / 'cells.lib')]
    assert source.read_bytes() == before


def test_local_measured_stall_reaps_native_descendant(local_image, monkeypatch):
    pid_file = local_image.tmp / 'child.pid'
    script = ('import subprocess,time;from pathlib import Path;'
        'p=subprocess.Popen(["sleep","60"]);'
        f'Path({str(pid_file)!r}).write_text(str(p.pid));time.sleep(60)')
    monkeypatch.setattr(contract, 'TOOL_STALL_GRACE_S', .3)
    with pytest.raises(contract.Refusal, match='LL_TOOL_STALLED'):
        contract.run_container(['docker', 'run', '--rm', local_image.image, '--skip',
                                sys.executable, '-c', script], probe_deadline_s=.05)
    pid = int(pid_file.read_text())
    stat = Path(f'/proc/{pid}/stat')
    assert not stat.exists() or stat.read_text().split()[2] == 'Z'


def design(tmp_path):
    p = tmp_path / 'design'
    put(p / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'role': 'primary', 'pdk_scoped_target': 'processA',
                           'period_ns': 12, 'source_pin': 'clk'}]})
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'block'})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {
        'constraint_declarations': [
            {'token': 'MAX_FANOUT_CONSTRAINT', 'scope': 'processA*', 'value': '4',
             'source': 'input/docs/L9.txt', 'line': 8},
            {'token': 'FP_PDN_SKIPTRIM', 'scope': None, 'value': 'true',
             'source': 'input/docs/L1.txt', 'line': 9}]}})
    put(p / 'input/submission_template/tapeout_declaration.json', {'answers': {
        'top_cell': 'chip_top', 'die_area_um': [0, 0, 100, 100],
        'core_area_um': [10, 10, 90, 90]}})
    put(p / 'phase3/stage3/pnr/pad_assignment.json', {
        'PAD_NORTH': ['u_a'], 'PAD_SITE_NAME': 'siteA',
        'PAD_CORNER_SITE_NAME': 'cornerSiteA', 'PAD_CORNER': 'cornerA',
        'PAD_FILLERS': ['fillA'], 'PAD_EDGE_SPACING': '12.5',
        'PAD_ROTATION_HORIZONTAL': 'R0'})
    return p


def test_emit_declared_values_and_sources(tmp_path):
    p = design(tmp_path)
    (p / 'phase2/stage1/rtl').mkdir(parents=True)
    (p / 'phase2/stage1/rtl/block.v').write_text('module block; endmodule')
    (p / 'phase3/stage3/pnr/chip_top_io.v').write_text('module chip_top; endmodule')
    (p / 'phase3/stage3/pnr/constraint.sdc').write_text('create_clock -period 12 clk')
    result = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
    assert result['CLOCK_PERIOD'] == 12
    assert result['MAX_FANOUT_CONSTRAINT'] == 4
    assert result['DIE_AREA'] == [0, 0, 100, 100]
    assert result['PAD_NORTH'] == ['u_a']
    assert result['PAD_CORNER'] == ['cornerA']
    assert result['PAD_FILLERS'] == ['fillA']
    assert result['PAD_EDGE_SPACING'] == 12.5
    assert result['PAD_ROTATION_HORIZONTAL'] == 'R0'
    assert result['PDN_SKIPTRIM'] is True
    assert result['VERILOG_FILES'][0].endswith('/block.v')
    assert result['PNR_SDC_FILE'].endswith('/constraint.sdc')
    assert 'MAX_TRANSITION_CONSTRAINT' not in result
    provenance = json.loads((p / 'phase3/librelane/config.provenance.json').read_text())
    assert all(k in provenance for k in result)


def test_invalid_declared_pad_spacing_is_refused(tmp_path):
    p = design(tmp_path)
    pads = p / 'phase3/stage3/pnr/pad_assignment.json'
    doc = json.loads(pads.read_text())
    doc['PAD_EDGE_SPACING'] = '-1'
    put(pads, doc)
    with pytest.raises(contract.Refusal, match='LL_PAD_SPACING_INVALID'):
        contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')

def test_synthesis_config_uses_selected_sources_and_lec_hooks(tmp_path):
    p = design(tmp_path)
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    package = rtl / 'pkg.sv'
    block = rtl / 'block.sv'
    package.write_text('package pkg; endpackage')
    block.write_text('module block(input clk, output reg q); always @(posedge clk) q <= 1; endmodule')
    result = contract.emit_synthesis_config(
        p, 'processA', p / 'phase3/librelane/synth.json',
        [package, block], ['SIMULATION'], True)
    assert result['VERILOG_FILES'] == [str(package), str(block)]
    assert result['VERILOG_DEFINES'] == ['SIMULATION']
    assert result['USE_SLANG'] is True
    assert result['SYNTH_SPLITNETS'] is False
    assert result['SYNTH_FSM_ENCFILE'] is True
    assert result['SYNTH_PRESERVE_FSM_REGISTERS'] == []
    assert 'VERILOG_FILES' in json.loads(
        (p / 'phase3/librelane/synth.provenance.json').read_text())
    assert 'hilomap' in json.loads(
        (p / 'phase3/librelane/synth.provenance.json').read_text())['SYNTH_SPLITNETS']


def test_synthesis_config_refuses_external_or_missing_rtl(tmp_path):
    p = design(tmp_path)
    with pytest.raises(contract.Refusal, match='LL_SYNTH_INPUT_MISSING'):
        contract.emit_synthesis_config(p, 'processA', p / 'synth.json',
                                       [tmp_path / 'other.sv'], [], False)


def test_native_stat_binds_area_gate_and_netlist_to_tool_output(tmp_path):
    netlist = tmp_path / 'block.nl.v'
    netlist.write_text('module block; endmodule\n')
    stat = put(tmp_path / 'stat.json', {'modules': {
        '\\block': {'num_cells': 4, 'area': 12.5}}})
    stats = put(tmp_path / 'stats.json', {'cell_count': 4, 'chip_area': 12.5,
        'netlist_sha256': 'sha256:' + contract.digest(netlist)})
    state = {'nl': str(netlist), 'metrics': {
        'design__instance__count': 4, 'design__instance__area': 12.5}}
    output = tmp_path / 'binding.json'
    assert contract.verify_synthesis_stat(stat, state, stats, 'block', output)['status'] == 'PASS'
    assert json.loads(output.read_text())['native_netlist_sha256'] == contract.digest(netlist)

    put(stats, {'cell_count': 3, 'chip_area': 12.5,
                'netlist_sha256': 'sha256:' + contract.digest(netlist)})
    with pytest.raises(contract.Refusal, match='LL_STAT_MISMATCH'):
        contract.verify_synthesis_stat(stat, state, stats, 'block', output)
    assert not output.exists()

    put(stats, {'cell_count': 4, 'chip_area': 12.5,
                'netlist_sha256': 'sha256:' + contract.digest(netlist)})
    netlist.write_text('module block; wire changed; endmodule\n')
    with pytest.raises(contract.Refusal, match='LL_STAT_NETLIST_MISMATCH'):
        contract.verify_synthesis_stat(stat, state, stats, 'block', output)


def test_synthesis_chain_accepts_pre_netlist_state_and_keeps_tool_output(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    initial = put(p / 'initial.json', {'json_h': str(put(p / 'header.json', {}))})
    config = put(p / 'config.json', {'meta': {'step': 'Yosys.Synthesis'}})

    def tool_run(cmd, **_):
        folder = Path(cmd[cmd.index('-o') + 1])
        netlist = folder / 'block.nl.v'
        netlist.write_text('module block; endmodule')
        (folder / 'COMMANDS').write_text(
            'yosys -y /usr/local/lib/python3.12/dist-packages/librelane/'
            'scripts/pyosys/synthesize.py -- --config-in config.json '
            '--extra-in extra.json --output block.nl.v\n')
        put(folder / 'state_out.json', {'nl': str(netlist)})
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool_run)
    folder = contract.run_chain(p, 'candidate', [('Yosys.Synthesis', config, initial)], pdk_root='/pdk')[0]
    assert (folder / 'block.nl.v').is_file()
    assert json.loads((folder / 'state_out.json').read_text())['nl'].endswith('block.nl.v')
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    assert receipt['sha256']['COMMANDS'] == contract.digest(folder / 'COMMANDS')


def test_stapostpnr_receipt_binds_mounted_liberty_bytes(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    project = tmp_path / 'design'
    pdk = tmp_path / 'pdk'
    liberty = pdk / 'cells/a.lib'
    liberty.parent.mkdir(parents=True)
    liberty.write_text('library (a) { nom_voltage : 5.0; }\n')
    guest = '/pdk/process/cells/a.lib'
    views = {key: str(put(project / f'{key}.json', {}))
             for key in ('odb', 'def', 'nl', 'sdc')}
    initial = put(project / 'initial.json', views)
    config = put(project / 'config.json', {
        'meta': {'step': 'OpenROAD.STAPostPNR'},
        'STA_CORNERS': ['nom_typ'], 'CELL_LIBS': {'*': [guest]}})

    def tool_run(cmd, **_):
        folder = Path(cmd[cmd.index('-o') + 1])
        put(folder / 'state_out.json', views)
        log = folder / 'nom_typ/sta.log'
        log.parent.mkdir(parents=True)
        log.write_text(f"Reading cell library for the 'nom_typ' corner at '{guest}'\n")
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract, 'run_container', tool_run)
    folder = contract.run_chain(project, 'candidate',
                                [('OpenROAD.STAPostPNR', config, initial)],
                                mounts=[(pdk, '/pdk/process')],
                                pdk_root='/pdk/process')[0]
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    assert receipt['input']['liberty_files'] == {guest: contract.digest(liberty)}
    assert receipt['sha256']['nom_typ/sta.log'] == contract.digest(folder / 'nom_typ/sta.log')

    def drifting_tool_run(cmd, **kwargs):
        result = tool_run(cmd, **kwargs)
        liberty.write_text(liberty.read_text() + 'cell (changed) {}\n')
        return result

    monkeypatch.setattr(contract, 'run_container', drifting_tool_run)
    with pytest.raises(contract.Refusal, match='LL_STA_LIBERTY_CHANGED_DURING_RUN'):
        contract.run_chain(project, 'candidate',
                           [('OpenROAD.STAPostPNR', config, initial)],
                           mounts=[(pdk, '/pdk/process')], lane='drift',
                           pdk_root='/pdk/process')


def _sta_journal_process_double(tmp_path, monkeypatch, *, step='OpenROAD.STAPrePNR',
                                corners=('nom_typ',), returncode=0):
    """Real receipt owner; substitute only native execution, never signoff."""
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    project = tmp_path / 'design'
    netlist = project / 'neutral.v'
    netlist.parent.mkdir(parents=True)
    netlist.write_text('module neutral; endmodule\n')
    sdc = project / 'neutral.sdc'
    sdc.write_text('# TEST DOUBLE: no approved electrical constraints\n')
    liberty = project / 'neutral.lib'
    liberty.write_text('/* TEST DOUBLE: not a qualified timing model */\n')
    views = {key: str(put(project / (key + '.json'), {})) for key in ('odb', 'def')}
    views.update(nl=str(netlist), sdc=str(sdc))
    initial = put(project / 'initial.json', views)
    config = put(project / 'config.json', {'meta': {'step': step},
        'STA_CORNERS': list(corners), 'PNR_SDC_FILE': str(sdc),
        'CELL_LIBS': {'*': [str(liberty)]}})
    calls = []

    def native_process_double(argv, **_kwargs):
        calls.append(argv)
        folder = Path(argv[argv.index('-o') + 1])
        for flag, name in (('-c', 'config.json'), ('-i', 'state_in.json')):
            (folder / name).write_bytes(Path(argv[argv.index(flag) + 1]).read_bytes())
        put(folder / 'state_out.json', views)
        for corner in corners:
            log = folder / corner / 'sta.log'
            log.parent.mkdir(parents=True)
            log.write_text('TEST DOUBLE: no native STA qualification\n'
                f"Reading cell library for the '{corner}' corner at '{liberty}'\n"
                f"Reading top-level netlist at '{netlist}'\n"
                f"Reading design constraints file at '{sdc}'\n")
        return SimpleNamespace(returncode=returncode, stdout='TEST DOUBLE process output', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *_a, **_k: None)
    monkeypatch.setattr(contract, 'run_container', native_process_double)

    def invoke():
        return contract.run_chain(project, 'candidate', [(step, config, initial)], pdk_root='/pdk')[0]

    return project, invoke, calls


@pytest.mark.parametrize('corners', [('nom_typ',), ('nom_typ', 'nom_other')],
                         ids=['one-journal', 'two-journals'])
def test_staprepnr_success_receipt_seals_emitted_journals(tmp_path, monkeypatch, corners):
    _project, invoke, calls = _sta_journal_process_double(tmp_path, monkeypatch, corners=corners)
    folder = invoke()
    receipt = contract.validate_step_receipt(folder, 'OpenROAD.STAPrePNR')
    assert len(calls) == 1
    recorded = {f'{corner}/sta.log': receipt['sha256'].get(f'{corner}/sta.log', 'UNBOUND')
                for corner in corners}
    expected = {f'{corner}/sta.log': contract.digest(folder / corner / 'sta.log') for corner in corners}
    assert recorded == expected, {'actual': recorded, 'expected': expected}


@pytest.mark.parametrize('step', ['OpenROAD.STAPrePNR', 'OpenROAD.STAPostPNR'])
@pytest.mark.parametrize('damage', ['tampered', 'missing'])
def test_sta_claimed_journal_changes_refused(tmp_path, monkeypatch, step, damage):
    _project, invoke, calls = _sta_journal_process_double(tmp_path, monkeypatch, step=step)
    folder = invoke()
    contract.validate_step_receipt(folder, step)
    before = (folder / 'vibeic_receipt.json').read_bytes()
    log = folder / 'nom_typ/sta.log'
    log.write_text('changed read journal\n') if damage == 'tampered' else log.unlink()
    try:
        contract.validate_step_receipt(folder, step)
        actual = 'ACCEPTED'
    except contract.Refusal as exc:
        actual = exc.code
    assert actual == 'LL_STEP_OUTPUT_UNBOUND', {'actual': actual, 'step': step, 'damage': damage}
    assert (folder / 'vibeic_receipt.json').read_bytes() == before
    assert len(calls) == 1


def test_staprepnr_historical_unsealed_receipt_stays_ineligible_for_d30(tmp_path, monkeypatch):
    """Synthetic historical receipt; actual cache and D30 readset consumers."""
    import flow109_metric_acceptance as metrics
    project, invoke, calls = _sta_journal_process_double(tmp_path, monkeypatch)
    folder = invoke()

    def ref(path):
        return {'path': str(path.relative_to(project)), 'sha256': contract.digest(path)}

    # Isolate the native readset reader. These metadata doubles confer no D26
    # row approval, LEC, timing or full D30 acceptance.
    metadata = put(project / 'readset-metadata.json', {'test_double': 'D26 readset metadata only'})
    admission = {'requires_scan': True, 'pre_route_timing': {'D26_result': ref(metadata),
        'timing_modes': {'receipt': ref(metadata), 'post_scan_arms': {'functional': {
            'native': {'folder': str(folder.relative_to(project))},
            'slack_gate': {'corners': {'nom_typ': {'test_double': True}}}}}}},
        'normalized_preroute_chain': {'points': {'D26': {'input': ref(project / 'neutral.v')}}}}
    current = metrics.d30_consumed_timing(project, admission)
    assert current['status'] == 'MEASURED', current
    # Build the historical fixture by omitting the producer binding that old
    # executions never wrote. Capture its bytes before exercising reuse.
    receipt_path = folder / 'vibeic_receipt.json'
    historical = json.loads(receipt_path.read_text())
    del historical['sha256']['nom_typ/sta.log']
    put(receipt_path, historical)
    before = receipt_path.read_bytes()
    contract.validate_step_receipt(folder, 'OpenROAD.STAPrePNR')
    assert invoke() == folder
    assert len(calls) == 1, 'historical reuse must not manufacture a fresh native execution'
    assert receipt_path.read_bytes() == before, 'cache must not re-sign or upgrade old receipts'
    observed = metrics.d30_consumed_timing(project, admission)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == 'D30_NATIVE_READ_LOG_UNBOUND', observed
    assert receipt_path.read_bytes() == before


def test_staprepnr_failed_native_process_does_not_publish_receipt(tmp_path, monkeypatch):
    project, invoke, calls = _sta_journal_process_double(tmp_path, monkeypatch, returncode=1)
    with pytest.raises(contract.Refusal, match='LL_STEP_FAILED'):
        invoke()
    assert len(calls) == 1
    assert list(project.glob('phase3/librelane/*/nom_typ/sta.log'))
    assert not list(project.glob('phase3/librelane/*/vibeic_receipt.json'))


def test_stream_lane_and_synthesis_namespace_keep_separate_receipts(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    netlist = p / 'block.nl.v'
    netlist.write_text('module block; endmodule')
    initial = put(p / 'initial.json', {'nl': str(netlist)})
    config = put(p / 'config.json', {'meta': {'step': 'OpenROAD.Floorplan'}})

    def tool_run(cmd, **_):
        folder = Path(cmd[cmd.index('-o') + 1])
        put(folder / 'state_out.json', {'nl': str(netlist)})
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool_run)
    steps = [('OpenROAD.Floorplan', config, initial)]
    stream = contract.run_chain(p, 'candidate', steps, lane='stream37', pdk_root='/pdk')[0]
    synth = contract.run_chain(p, 'candidate', steps,
                               namespace='ppa_synthesis/arm0', pdk_root='/pdk')[0]
    assert stream == p / 'phase3/librelane/stream37/01-openroad-floorplan'
    assert synth == p / 'phase3/librelane/ppa_synthesis/arm0/01-openroad-floorplan'
    assert stream.joinpath('vibeic_receipt.json').is_file()
    assert synth.joinpath('vibeic_receipt.json').is_file()
    with pytest.raises(contract.Refusal, match='LL_LANE_NAMESPACE_CONFLICT'):
        contract.run_chain(p, 'candidate', steps, lane='stream37',
                           namespace='ppa_synthesis/arm0', pdk_root='/pdk')


def test_switch_defaults_to_direct_and_rejects_bad_value(tmp_path):
    p = design(tmp_path)
    assert contract.selected_mode(p, '15.5ic') == 'direct'
    put(p / 'phase3/librelane_switch.json', {'steps': {'15.5ic': 'dual'}})
    assert contract.selected_mode(p, '15.5ic') == 'dual'
    put(p / 'phase3/librelane_switch.json', {'steps': {'15.5ic': 'fallback'}})
    with pytest.raises(contract.Refusal, match='LL_INVALID_SWITCH'):
        contract.selected_mode(p, '15.5ic')


def test_step9_dual_does_not_silently_run_direct_without_routed_evidence(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    p = design(tmp_path)
    put(p / 'phase3/librelane_switch.json', {'steps': {'9': 'dual'}})
    result = runner.step_synth(p, 'block', None, '')
    assert result.status == 'FAIL'
    assert 'LL_DUAL_POSTROUTE_NOT_READY' in result.detail


def test_image_incapable_is_named_and_not_fallback(monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    monkeypatch.setattr(contract.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(contract.Refusal, match='LL_IMAGE_INCAPABLE'):
        contract.image_capability('released-image')


def test_chain_resumes_success_and_reruns_failed_step(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    source = p / 'source'
    source.mkdir()
    for name in ('a.odb', 'a.def', 'a.nl', 'a.sdc'):
        (source / name).write_text(name)
    state = put(p / 'initial.json', {k: str(source / ('a.' + k)) for k in ('odb', 'def', 'nl', 'sdc')})
    cfg = put(p / 'config.json', {'meta': {'step': 'OpenROAD.PadRing'}})
    calls = []

    def fake_run(cmd, **_):
        calls.append(cmd)
        folder = Path(cmd[cmd.index('-o') + 1])
        for key in ('odb', 'def', 'nl', 'sdc'):
            (folder / ('b.' + key)).write_text(key)
        put(folder / 'state_out.json', {k: str(folder / ('b.' + k)) for k in ('odb', 'def', 'nl', 'sdc')})
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', fake_run)
    steps = [('OpenROAD.PadRing', cfg, state)]
    folder = contract.run_chain(p, 'candidate', steps, pdk_root='/pdk')[0]
    assert len(calls) == 1
    assert 'state_out.json' in json.loads((folder / 'vibeic_receipt.json').read_text())['sha256']
    contract.run_chain(p, 'candidate', steps, pdk_root='/pdk')
    assert len(calls) == 1
    (folder / 'state_out.json').unlink()
    contract.run_chain(p, 'candidate', steps, pdk_root='/pdk')
    assert len(calls) == 2


def test_chain_stall_is_reaped_by_its_name_and_recorded_unmeasured(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    source = p / 'block.nl.v'
    source.write_text('module block; endmodule\n')
    initial = put(p / 'initial.json', {'nl': str(source)})
    config = put(p / 'config.json', {'meta': {'step': 'OpenROAD.Floorplan'}})
    reaped = threading.Event()
    launched = []
    names = []

    def tool_run(cmd, **_):
        if len(cmd) > 1 and cmd[1] == 'inspect':
            return SimpleNamespace(returncode=0, stdout='0', stderr='')
        if len(cmd) > 1 and cmd[1] == 'rm':
            names.append((cmd[-1], 'stalled'))
            reaped.set()
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        launched.append(cmd)
        folder = Path(cmd[cmd.index('-o') + 1])
        put(folder / 'state_out.json', {'nl': str(source)})
        # The fake tool is allowed to finish on its own, so the pre-fix path
        # returns PASS after one second instead of hanging the test session.
        stopped = reaped.wait(1.0)
        if stopped:
            return SimpleNamespace(returncode=137, stdout='', stderr='stopped')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool_run)
    monkeypatch.setattr(contract, 'TOOL_STALL_GRACE_S', 0.15)
    import _watchdog
    monkeypatch.setattr(_watchdog, 'host_tree_progress', lambda pid: None)

    with pytest.raises(contract.Refusal, match='LL_TOOL_STALLED'):
        contract.run_chain(p, 'candidate', [('OpenROAD.Floorplan', config, initial)],
                           pdk_root='/pdk')
    folder = p / 'phase3/librelane/01-openroad-floorplan'
    record = json.loads((folder / 'vibeic_stalled.json').read_text())
    assert record['verdict'] == 'NOT_MEASURED'
    assert record['reason_class'] == 'stalled'
    assert not (folder / 'state_out.json').exists()
    assert (folder / 'state_out.stalled.json').is_file()
    assert not (folder / 'vibeic_receipt.json').exists()
    assert names and all(reason == 'stalled' for _name, reason in names)
    assert len({name for name, _reason in names}) == 1
    assert launched[0][launched[0].index('--name') + 1] == names[0][0]
    assert '--memory' in launched[0] and '--memory-swap' in launched[0]


def test_chain_progressing_past_stall_grace_is_not_killed(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    source = p / 'block.nl.v'
    source.write_text('module block; endmodule\n')
    initial = put(p / 'initial.json', {'nl': str(source)})
    config = put(p / 'config.json', {'meta': {'step': 'OpenROAD.Floorplan'}})
    reaped = []

    def tool_run(cmd, **_):
        if len(cmd) > 1 and cmd[1] == 'inspect':
            return SimpleNamespace(returncode=0, stdout='123', stderr='')
        if len(cmd) > 1 and cmd[1] == 'rm':
            reaped.append((cmd[-1], 'stalled'))
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        folder = Path(cmd[cmd.index('-o') + 1])
        log = folder / 'tool.log'
        for i in range(7):
            log.write_text('working\n' * (i + 1))
            time.sleep(0.08)
        put(folder / 'state_out.json', {'nl': str(source)})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool_run)
    monkeypatch.setattr(contract, 'TOOL_STALL_GRACE_S', 0.15)
    import _watchdog
    readings = iter(range(1, 1000))
    monkeypatch.setattr(_watchdog, 'host_tree_progress', lambda pid: next(readings))

    folder = contract.run_chain(
        p, 'candidate', [('OpenROAD.Floorplan', config, initial)],
        pdk_root='/pdk')[0]
    assert (folder / 'state_out.json').is_file()
    assert not (folder / 'vibeic_stalled.json').exists()
    assert not reaped


def test_step31_reports_chain_stall_as_unmeasured(tmp_path, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    pv = importlib.import_module('librelane_pv_signoff')
    monkeypatch.setattr(contract, 'resolve_image', lambda project: 'candidate')
    monkeypatch.setattr(contract, 'resolve_pdk_root',
                        lambda project, pdk, image=None: str(tmp_path))

    def stalled(*args, **kwargs):
        raise contract.Refusal('LL_TOOL_STALLED', 'the step made no forward progress')

    monkeypatch.setattr(pv, 'run_half', stalled)
    result = runner._step31_librelane(
        tmp_path, 'block', SimpleNamespace(name='processA'), 'drc', publish=False)
    assert result.status == 'NOT_MEASURED'
    assert result.reason_class == runner._V.ReasonClass.STALLED
    assert 'LL_TOOL_STALLED' in result.detail


def test_floorplan_accepts_netlist_only_before_it_creates_geometry(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    p = design(tmp_path)
    netlist = p / 'source.nl.v'
    netlist.write_text('module block; endmodule\n')
    state = put(p / 'initial.json', {'nl': str(netlist)})
    cfg = put(p / 'config.json', {'meta': {'step': 'OpenROAD.Floorplan'}})

    def fake_floorplan(cmd, **_):
        folder = Path(cmd[cmd.index('-o') + 1])
        views = {}
        for key in ('odb', 'def', 'nl', 'sdc'):
            view = folder / ('block.' + key)
            view.write_text(key)
            views[key] = str(view)
        put(folder / 'state_out.json', views)
        return SimpleNamespace(returncode=0, stdout='floorplan', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', fake_floorplan)
    assert contract.run_chain(p, 'candidate', [('OpenROAD.Floorplan', cfg, state)], pdk_root='/pdk')[0].joinpath('state_out.json').is_file()


def test_tap_step_refuses_missing_geometry_input(tmp_path, monkeypatch):
    p = design(tmp_path)
    netlist = p / 'source.nl.v'
    netlist.write_text('module block; endmodule\n')
    state = put(p / 'initial.json', {'nl': str(netlist)})
    cfg = put(p / 'config.json', {'meta': {'step': 'OpenROAD.TapEndcapInsertion'}})
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    with pytest.raises(contract.Refusal, match='LL_STATE_MISSING'):
        contract.run_chain(p, 'candidate', [('OpenROAD.TapEndcapInsertion', cfg, state)], pdk_root='/pdk')


def test_missing_metric_stays_unmeasured_and_cannot_win(tmp_path):
    folder = tmp_path / 'arm'
    put(folder / 'state_out.json', {'metrics': {'area': 10}})
    first = contract.judge_step(folder, ['area', 'timing'], tmp_path / 'first.json')
    assert first['verdict'] == 'NOT_MEASURED'
    assert first['metrics']['timing']['status'] == 'NOT_MEASURED'
    put(tmp_path / 'second.json', {'verdict': 'PASS', 'scope': {'step': 'same'},
                                   'metrics': {'area': {'status': 'MEASURED', 'value': 11},
                                               'timing': {'status': 'MEASURED', 'value': 2}}})
    result = contract.select_arms({'ll': tmp_path / 'first.json', 'or': tmp_path / 'second.json'},
                                  {'area': 'min', 'timing': 'max'}, tmp_path / 'selection.json')
    assert result['selection'] == 'UNDETERMINED'
    assert result['reason'] == 'LL_ARM_NOT_MEASURED'


def test_missing_report_is_unmeasured(tmp_path):
    folder = tmp_path / 'arm'
    put(folder / 'state_out.json', {'metrics': {'pads': 3}})
    result = contract.judge_step(folder, ['pads'], tmp_path / 'gate.json',
                                 {'pads': {'min': 1}}, ['pad.rpt'])
    assert result['verdict'] == 'NOT_MEASURED'
    (folder / 'pad.rpt').write_text('pad report')
    result = contract.judge_step(folder, ['pads'], tmp_path / 'gate.json',
                                 {'pads': {'min': 1}}, ['pad.rpt'])
    assert result['verdict'] == 'PASS'
    assert result['reports']['pad.rpt']['sha256'] == contract.digest(folder / 'pad.rpt')


def test_pareto_keeps_losing_arm_and_ties(tmp_path):
    for name, area, timing in [('ll', 10, 3), ('or', 12, 2)]:
        put(tmp_path / (name + '.json'), {'verdict': 'PASS', 'scope': {'step': 'same'}, 'metrics': {
            'area': {'status': 'MEASURED', 'value': area},
            'timing': {'status': 'MEASURED', 'value': timing}}})
    arms = {name: tmp_path / (name + '.json') for name in ('ll', 'or')}
    result = contract.select_arms(arms, {'area': 'min', 'timing': 'max'}, tmp_path / 'sel.json')
    assert result['selection'] == 'll'
    assert set(result['arms']) == {'ll', 'or'}


def test_dual_executes_in_separate_directories_and_keeps_loser(tmp_path):
    seen = []

    def arm(name, area, timing):
        def produce(folder):
            seen.append((name, folder))
            return put(folder / 'gate.json', {'verdict': 'PASS', 'scope': {'step': 'same'},
                                              'metrics': {'area': {'status': 'MEASURED', 'value': area},
                                                          'timing': {'status': 'MEASURED', 'value': timing}}})
        return produce

    result = contract.execute_dual(tmp_path, '15.5ic', arm('ll', 10, 3),
                                   arm('or', 12, 2), {'area': 'min', 'timing': 'max'})
    assert result['selection'] == 'librelane'
    assert seen[0][1] != seen[1][1]
    assert all((folder / 'gate.json').is_file() for _, folder in seen)


@pytest.mark.parametrize('state',['progressing','failed','stalled'])
def test_allocated_local_probe_budget_never_kills_progress(local_image,monkeypatch,state):
    import _watchdog as wd
    calls=[]
    def observed(argv,**kw):
        calls.append((argv,kw))
        return wd.SupervisedResult(0 if state=='progressing' else (7 if state=='failed' else wd.RC_STALLED),
            'retained output','WATCHDOG_STALLED' if state=='stalled' else 'retained stderr',
            'stalled' if state=='stalled' else 'natural',elapsed_s=50,
            supervision={'pid':321,'watched':'output+cpu'})
    monkeypatch.setattr(wd,'run_host_supervised',observed)
    class Raw:
        pid=987;returncode=0
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def communicate(self,**kw):return 'raw clock path',''
    monkeypatch.setattr(contract.subprocess,'Popen',lambda *a,**k:Raw())
    argv=['docker','run','--rm',local_image.image,'--skip','neutral-tool','arg']
    if state=='stalled':
        with pytest.raises(contract.Refusal) as refused:
            contract._run_local(argv,probe_deadline_s=.3,supervised=False,log=None)
        assert refused.value.code=='LL_TOOL_STALLED'
    else:
        row=contract._run_local(argv,probe_deadline_s=.3,supervised=False,log=None)
        assert (row.returncode,row.stdout,row.stderr)==(0 if state=='progressing' else 7,'retained output','retained stderr')
    assert len(calls)==1 and calls[0][0]==['neutral-tool','arg']
    assert calls[0][1]['hard_ceiling_s']==.3 and calls[0][1]['env']
    assert callable(calls[0][1]['ceiling_notice'])


def test_optional_tcl_stall_preserves_primary_cli_admission(tmp_path, monkeypatch):
    """Two neutral caller inputs; every tool invocation is an API double."""
    image = 'neutral-optional-tcl-caller-fixture'
    calls = []
    primary_rc = [0]
    monkeypatch.setattr(contract, '_CAPABILITY', {})
    monkeypatch.setattr(contract, '_provider_for_image', lambda value: None)
    monkeypatch.setattr(contract, '_provider_route_mismatch', lambda value: None)
    monkeypatch.setattr(container_exec, 'no_container_route', lambda: False)

    def observed(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, primary_rc[0],
                'neutral primary CLI output', 'neutral primary CLI stderr')
        assert len(calls) == 2
        raise contract.Refusal('LL_TOOL_STALLED', 'neutral optional Tcl made no progress')

    monkeypatch.setattr(contract, 'run_container', observed)
    capability = contract.image_capability(image)
    assert capability['image'] == image
    assert capability['openroad_aliases'] == {}
    assert capability['tcl_probe'] == (
        'NOT_MEASURED: LL_TOOL_STALLED: neutral optional Tcl made no progress')
    assert len(calls) == 2 and calls[1][0][-1] == contract._TCL_PROBE
    assert all(kwargs == {'probe_deadline_s': contract.PROBE_DEADLINE_S}
               for _, kwargs in calls)
    put(tmp_path / 'primary-ok-optional-stalled.json', capability)

    contract._CAPABILITY.clear()
    calls.clear()
    primary_rc[0] = 7
    with pytest.raises(contract.Refusal) as refused:
        contract.image_capability(image)
    assert refused.value.code == 'LL_IMAGE_INCAPABLE'
    assert len(calls) == 1 and calls[0][0][-1] != contract._TCL_PROBE
    assert contract._CAPABILITY == {}
    put(tmp_path / 'primary-failed.json', {
        'primary_rc': 7, 'refusal_code': refused.value.code,
        'optional_stage_called': False, 'scope': 'neutral source/API mock'})


def _declare_vertical_pdn_width(project, value, *, scope=None):
    path = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    doc = json.loads(path.read_text())
    declarations = doc['fields']['constraint_declarations']
    declarations[:] = [row for row in declarations if row['token'] != 'PDN_VWIDTH']
    declarations.append({'token': 'PDN_VWIDTH', 'scope': scope, 'value': value,
                         'source': 'input/docs/pdn.md', 'line': 4})
    put(path, doc)


def test_vertical_pdn_width_flows_from_input_through_l19_and_normal_builder(tmp_path):
    import l19_constraint_token_emit as l19
    project = design(tmp_path)
    source = project / 'input/docs/pdn.md'
    source.parent.mkdir(parents=True)
    source.write_text('# PDN constraints\n\n| setting | value |\n'
                      '|---|---|\n| `PDN_VWIDTH` | 2.75 |\n')
    emitted = l19.run(project)
    assert emitted['status'] != 'ERROR', emitted
    doc = json.loads((project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').read_text())
    row = next(r for r in doc['fields']['constraint_declarations'] if r['token'] == 'PDN_VWIDTH')
    assert float(row['value']) == 2.75 and row['source'] == 'input/docs/pdn.md'
    output = project / 'phase3/librelane/15-config/design.json'
    resolved = contract.emit_config(project, 'processA', output)
    assert resolved['PDN_VWIDTH'] == 2.75
    provenance = json.loads(output.with_suffix('.provenance.json').read_text())
    assert 'input/docs/pdn.md' in provenance['PDN_VWIDTH']
    assert not any(key in resolved for key in ('PDN_VPITCH', 'PDN_HWIDTH', 'PDN_HPITCH'))


@pytest.mark.parametrize('value', ['0', '-0.1', 'NaN', 'inf', '-inf', '3%', 'true', True, 'bad'])
def test_vertical_pdn_width_refuses_invalid_declared_values(tmp_path, value):
    project = design(tmp_path)
    _declare_vertical_pdn_width(project, value)
    with pytest.raises(contract.Refusal, match='LL_PDN_VERTICAL_WIDTH_INVALID'):
        contract.emit_config(project, 'processA', project / 'config.json')


@pytest.mark.parametrize('value, scope', [('', None), ('not_determined', None),
                                        ('2.75', 'other_process*')])
def test_unspecified_vertical_pdn_width_keeps_existing_defaults(tmp_path, value, scope):
    project = design(tmp_path)
    output = project / 'config.json'
    before = contract.emit_config(project, 'processA', output)
    before_sources = output.with_suffix('.provenance.json').read_bytes()
    assert 'PDN_VWIDTH' not in before
    _declare_vertical_pdn_width(project, value, scope=scope)
    assert contract.emit_config(project, 'processA', output) == before
    assert output.with_suffix('.provenance.json').read_bytes() == before_sources


@pytest.mark.parametrize('change', ['width', 'recipe'])
def test_resolved_vertical_pdn_width_and_recipe_invalidate_native_cache(
        local_image, monkeypatch, change):
    """Real config builder, fingerprint/cache/archive; process writes are neutral.

    This source-control transport does not run Chip, GeneratePDN or a solver,
    and its widths are neutral fixtures, not a proposed physical repair size.
    """
    project = design(local_image.tmp)
    _declare_vertical_pdn_width(project, '1.25')
    pdk_root = local_image.tmp / 'pdks'
    (pdk_root / 'processA').mkdir(parents=True)
    recipe = project / 'source/pdn.tcl'
    recipe.parent.mkdir(parents=True)
    recipe.write_text('# neutral recipe\nadd_pdn_stripe -width $::env(PDN_VWIDTH)\n')
    state_views = {}
    for view in ('odb', 'def', 'nl', 'sdc'):
        path = project / 'source' / ('neutral.' + view)
        path.write_text('SOURCE_CONTROL ' + view + '\n')
        state_views[view] = str(path)
    initial = put(project / 'initial.json', state_views)
    step = 'OpenROAD.GeneratePDN'
    native_calls = []

    def process_transport(argv, **_kwargs):
        if '-o' not in argv:
            # The resolver's process edge consumes the actual design emitted
            # by resolve_step_configs; it does not supply a preselected width.
            declared = json.loads(Path(argv[-6]).read_text())
            requested = json.loads(Path(argv[-5]).read_text())
            target = Path(argv[-4])
            assert requested == [step]
            selected = {key: declared[key] for key in ('PDN_CFG', 'PDN_VWIDTH') if key in declared}
            put(target / (step + '.json'), {**selected, 'meta': {'step': step}})
            put(target / (step + '.views.json'), {'inputs': ['odb'], 'outputs': ['odb']})
        else:
            folder = Path(argv[argv.index('-o') + 1])
            config = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
            native_calls.append(config)
            views = {}
            for view in state_views:
                path = folder / ('result.' + view)
                path.write_text('SOURCE_CONTROL neutral ' + view + '\n')
                views[view] = str(path)
            put(folder / 'state_out.json', views)
            put(folder / 'config.json', config)
        return SimpleNamespace(returncode=0, stdout='SOURCE_CONTROL process output', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *_a, **_k: None)
    monkeypatch.setattr(contract, 'run_container', process_transport)

    def invoke():
        configs = contract.resolve_step_configs(project, local_image.image, 'processA',
            [step], pdk_root=pdk_root, folder='15-config',
            overlay={'PDN_CFG': (str(recipe), 'source-owned neutral PDN recipe')})
        return contract.run_chain(project, local_image.image,
            [(step, configs[step], initial)], pdk_root='/pdk')[0]

    folder = invoke()
    assert len(native_calls) == 1
    old_receipt = (folder / 'vibeic_receipt.json').read_bytes()
    old = json.loads(old_receipt)
    assert old['input']['config_files'][str(recipe)] == contract.digest(recipe)
    assert invoke() == folder and len(native_calls) == 1
    assert (folder / 'vibeic_receipt.json').read_bytes() == old_receipt
    if change == 'width':
        _declare_vertical_pdn_width(project, '2.75')
    else:
        recipe.write_text(recipe.read_text() + '# changed source recipe\n')
    assert invoke() == folder
    assert len(native_calls) == 2, 'changed declared width or recipe must execute the native process edge'
    current = contract.validate_step_receipt(folder, step)
    if change == 'width':
        assert native_calls[0]['PDN_VWIDTH'] == 1.25 and native_calls[1]['PDN_VWIDTH'] == 2.75
        assert old['input']['config'] != current['input']['config']
        assert old['input']['config_files'] == current['input']['config_files']
    else:
        assert old['input']['config'] == current['input']['config']
        assert old['input']['config_files'][str(recipe)] != current['input']['config_files'][str(recipe)]
    archives = list((folder.parent / 'attempts').glob(folder.name + '-*'))
    assert len(archives) == 1
    assert (archives[0] / 'vibeic_receipt.json').read_bytes() == old_receipt


@pytest.mark.parametrize('owner', ['flow_segment', 'emit_pdn_cfg'])
@pytest.mark.parametrize('profile', ['local_host', 'local_none', 'remote'])
def test_metadata_owner_uses_bound_provider_network(tmp_path, monkeypatch, owner, profile):
    """Real owner and launch guards; only the native/Docker process leaf is neutral."""
    import _watchdog as watchdog
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    if profile.startswith('local_'):
        network = profile.removeprefix('local_')
        monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_NETWORK', network)
        _project, image = _host_provider(tmp_path, monkeypatch)
        assert image.network_mode == network
    else:
        network = 'none'
        monkeypatch.delenv(contract.LOCAL_PROVIDER_ROUTE_ENV, raising=False)
        monkeypatch.setattr(container_exec, 'no_container_route', lambda: False)
        image = 'registry.invalid/metadata@sha256:' + 'aa' * 32
    calls = []
    native = '# native PDN payload\nadd_pdn_connect -grid stdcell_grid -layers {lower upper}\n'
    order = ['OpenROAD.Floorplan', 'OpenROAD.GeneratePDN', 'Odb.RemovePDNObstructions']

    def payload(argv):
        pdn_read = any(contract._PDN_PAYLOAD_KEY in str(part) for part in argv)
        return json.dumps({contract._PDN_PAYLOAD_KEY: native}) + '\n' if pdn_read else json.dumps(order) + '\n'

    def host_leaf(argv, **kwargs):
        calls.append({'route': 'LOCAL', 'args': list(argv), 'env': kwargs['env']})
        return watchdog.SupervisedResult(0, payload(argv), '', 'natural')

    def remote_leaf(argv, **kwargs):
        calls.append({'route': 'Docker', 'args': list(argv)})
        return subprocess.CompletedProcess(argv, 0, payload(argv), '')

    monkeypatch.setattr(watchdog, 'run_host_supervised', host_leaf)
    monkeypatch.setattr(contract.subprocess, 'run', remote_leaf)
    if owner == 'flow_segment':
        assert contract.flow_segment(image, order[0], order[-1]) == order
    else:
        target = tmp_path / 'pdn_cfg.tcl'
        result = contract.emit_pdn_cfg(image, 'neutral_process', target,
            native_connects=[['lower', 'upper']])
        assert result == target
        assert target.read_text().startswith(native)
    assert len(calls) == 1
    observed = calls[0]
    if profile.startswith('local_'):
        assert observed['route'] == 'LOCAL'
        assert observed['env']['VIBEIC_LOCAL_NETWORK_MODE'] == network
        assert ('--unshare-net' in observed['args']) is (network == 'none')
        assert observed['env']['PYTHONPATH'].split(os.pathsep)[0] == image.librelane_root
    else:
        assert observed['route'] == 'Docker'
        assert observed['args'][observed['args'].index('--network') + 1] == 'none'


@pytest.mark.parametrize('schema', ['modern', 'legacy', 'precedence', 'empty', 'null'])
def test_stapostpnr_receipt_binds_native_lib_schema(tmp_path, monkeypatch, schema):
    """Actual run_chain receipt and drift guard; only tool file writes are neutral."""
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    project = tmp_path / 'design'
    root = tmp_path / 'pdk'
    paths = {}
    for name in ('cell', 'pad', 'extra', 'legacy'):
        path = root / (name + '.lib')
        path.parent.mkdir(exist_ok=True)
        path.write_text('library (' + name + ') { nom_voltage : 5; }\n')
        paths[name] = path
    guests = {name: '/pdk/neutral/' + path.name for name, path in paths.items()}
    views = {key: str(put(project / (key + '.json'), {})) for key in ('odb', 'def', 'nl', 'sdc')}
    initial = put(project / 'initial.json', views)
    config = {'meta': {'step': 'OpenROAD.STAPostPNR'}, 'STA_CORNERS': ['nom_typ'],
              'PAD_LIBS': {'*': [guests['pad']]}, 'EXTRA_LIBS': [guests['extra']]}
    if schema == 'legacy':
        config['CELL_LIBS'] = {'*': [guests['cell']]}
    else:
        config['LIB'] = {} if schema == 'empty' else None if schema == 'null' else {'*': [guests['cell']]}
        if schema in ('precedence', 'empty', 'null'):
            config['CELL_LIBS'] = {'*': [guests['legacy']]}
    config_path = put(project / 'config.json', config)

    def native_leaf(argv, **kwargs):
        folder = Path(argv[argv.index('-o') + 1])
        put(folder / 'state_out.json', views)
        log = folder / 'nom_typ/sta.log'
        log.parent.mkdir(parents=True)
        log.write_text('NEUTRAL_NATIVE_STA_TRANSCRIPT\n')
        return SimpleNamespace(returncode=0, stdout='neutral native process', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *_: None)
    monkeypatch.setattr(contract, 'run_container', native_leaf)
    invoke = lambda lane: contract.run_chain(project, 'candidate',
        [('OpenROAD.STAPostPNR', config_path, initial)], mounts=[(root, '/pdk/neutral')],
        pdk_root='/pdk/neutral', lane=lane)[0]
    folder = invoke('first')
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    wanted = ['pad', 'extra'] + ([] if schema in ('empty', 'null') else ['cell'])
    assert receipt['input']['liberty_files'] == {guests[name]: contract.digest(paths[name]) for name in wanted}
    if schema == 'modern':
        def drift(argv, **kwargs):
            result = native_leaf(argv, **kwargs)
            paths['cell'].write_text(paths['cell'].read_text() + '# changed during STA\n')
            return result
        monkeypatch.setattr(contract, 'run_container', drift)
        with pytest.raises(contract.Refusal, match='LL_STA_LIBERTY_CHANGED_DURING_RUN'):
            invoke('changed')

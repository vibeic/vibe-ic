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


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


@pytest.fixture
def local_image(tmp_path, monkeypatch):
    """Host launch receipt shape, without asking the host for an image."""
    cid, image_id = 'ab' * 32, 'sha256:' + 'cd' * 32
    image = 'registry.invalid/tools@sha256:' + 'ef' * 32
    receipt = put(tmp_path / 'launch_identity.json', {
        'image': image, 'cid': cid,
        'image_inspect': [{'Id': image_id, 'RepoDigests': [image]}],
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
    assert recorded['repo_digests'] == [local_image.image]
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


def test_local_probe_deadline_kills_native_descendant(local_image):
    pid_file = local_image.tmp / 'child.pid'
    script = ('import subprocess,time;from pathlib import Path;'
        'p=subprocess.Popen(["sleep","60"]);'
        f'Path({str(pid_file)!r}).write_text(str(p.pid));time.sleep(60)')
    with pytest.raises(contract.Refusal, match='LL_TOOL_DEADLINE'):
        contract.run_container(['docker', 'run', '--rm', local_image.image, '--skip',
                                sys.executable, '-c', script], probe_deadline_s=.3)
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
    assert result['SYNTH_FSM_ENCFILE'] is True
    assert result['SYNTH_PRESERVE_FSM_REGISTERS'] == []
    assert 'VERILOG_FILES' in json.loads(
        (p / 'phase3/librelane/synth.provenance.json').read_text())


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
        put(folder / 'state_out.json', {'nl': str(netlist)})
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool_run)
    folder = contract.run_chain(p, 'candidate', [('Yosys.Synthesis', config, initial)], pdk_root='/pdk')[0]
    assert (folder / 'block.nl.v').is_file()
    assert json.loads((folder / 'state_out.json').read_text())['nl'].endswith('block.nl.v')


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
        tmp_path, 'block', SimpleNamespace(name='processA'), 'lvs', publish=False)
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

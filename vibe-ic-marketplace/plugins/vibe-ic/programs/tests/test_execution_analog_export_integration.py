"""Automatic callsite controls; local fixture processes confer no native credit."""
from pathlib import Path
import os
import subprocess
import sys
import types

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import execution_analog_installation as installation
import execution_adapters_analog as analog
import execution_analog_pdk_export as export
import analog_pdk_availability as resolver
import _eda_pin as pin
from programs.tests.test_execution_analog_pdk_export import setup_export, IMAGE_REF, IMAGE_ID, MANIFEST


@pytest.fixture
def normal_export(setup_export, monkeypatch, tmp_path):
    project, pdk, _, calls = setup_export
    helper_transport = installation.lc.run_container
    binary = tmp_path / 'bin'
    binary.mkdir()
    for tool in installation.TOOL_COMMANDS:
        path = binary / tool
        path.write_text('#!' + sys.executable + '\nprint("correctness fixture; NOT_NATIVE_EDA")\n')
        path.chmod(0o755)
    # Admission resolves the transport executable before the supervised seam.
    # Supply its explicit fixture identity without borrowing a host daemon or
    # giving an unsupervised Docker invocation any chance to succeed.
    docker = binary / 'docker'
    docker.write_text('#!' + sys.executable +
                      '\nraise SystemExit("UNSUPERVISED_FIXTURE_DOCKER_REFUSED")\n')
    docker.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ.get('PATH', ''))
    image = dict(image_ref=IMAGE_REF, image_id=IMAGE_ID,
        image_manifest_digest=MANIFEST, image_repo_digests=[IMAGE_REF])
    monkeypatch.setattr(installation, 'inspect_image', lambda ref, **kw: image)
    monkeypatch.setattr(pin, 'pinned_image_present', lambda: (IMAGE_REF, ''))
    def no_named_container(*args, **kwargs):
        pytest.fail('normal entry used the named-container docker exec lister')
    monkeypatch.setattr(resolver, '_docker_lister', no_named_container)
    observed = []
    def supervised(argv, *, probe_deadline_s, env):
        assert 'run' in argv and 'exec' not in argv and IMAGE_REF in argv
        assert not any(k.startswith('VIBEIC_EXECUTION') for k in env)
        script = argv[argv.index('--skip') + 3]
        if script == export._CONTAINER_COPY:
            return helper_transport(argv, probe_deadline_s=probe_deadline_s, env=env)
        if script == installation.PROBE:
            command = [sys.executable, '-c', script, argv[-1]]
            env = {**env, 'PATH': str(binary)}
        else:
            local = pdk.parent / Path(argv[-1]).relative_to(resolver.DEFAULT_PDKS_ROOT)
            command = [sys.executable, '-c', script, str(local)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        stdout, stderr = process.communicate(timeout=20)
        observed.append(dict(pid=process.pid, rc=process.returncode, argv=argv))
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    monkeypatch.setattr(installation.lc, 'run_container', supervised)
    args = types.SimpleNamespace(pdk='sky130A', container='NO_SUCH_CONTAINER')
    return project, args, observed, binary, calls


def facts(project, request, step='A8'):
    from execution_synthesis_engines import source_sha
    return analog.installation_facts(project, step, source_sha(), analog.component_sources(), prepared=request)




def test_export_failure_stays_not_measured_and_unqualified(normal_export, monkeypatch):
    project, args, _, _, _ = normal_export
    monkeypatch.setattr(export, 'export_bounded_pdk', lambda *a, **kw:
        dict(status='NOT_MEASURED', not_measured=['PDK_FILE_MISSING']))
    request = installation.prepare_entry_request(project, args)
    assert request['_missing'] == ['PDK_FILE_MISSING']
    assert facts(project, request)[1] is None
    assert not (project / 'phase3').exists()


def test_edited_exported_bytes_refuse_current_installation(normal_export):
    project, args, _, _, _ = normal_export
    request = installation.prepare_entry_request(project, args)
    assert facts(project, request)[1]['status'] == 'MEASURED'
    copied = project / next(iter(request['model_hashes']))
    copied.write_bytes(copied.read_bytes() + b'\n# changed current copied model\n')
    _, receipt, missing = facts(project, request)
    assert receipt is None and 'PDK_EXPORT_UNAVAILABLE:ANALOG_PDK_EXPORT_OUTPUT_CHANGED' in missing
    assert not (project / 'phase3').exists()




def test_missing_tool_stays_nm_and_measured_fail_dominates(normal_export):
    project, args, _, binary, _ = normal_export
    request = installation.prepare_entry_request(project, args)
    (binary / 'ngspice').unlink()
    assert facts(project, request)[1] is None
    (binary / 'magic').write_text('#!' + sys.executable + '\nprint("measured fixture failure")\nraise SystemExit(1)\n')
    params, receipt, missing = facts(project, request)
    assert receipt['status'] == 'FAIL' and params['installation_verdict'] == 'FAIL'
    assert missing == ['MEASURED_INSTALLATION_FAIL']
    assert not (project / 'phase3').exists()

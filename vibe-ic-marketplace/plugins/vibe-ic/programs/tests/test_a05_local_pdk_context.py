"""LOCAL A05 transport reaches the same selected-PDK resolver as A02."""
import json
from pathlib import Path

import pytest
import analog_native_front as front
import analog_a3_netlist_emit as emitter
import analog_pdk_availability as availability


@pytest.mark.parametrize(('options', 'expected'), [
    ({'transport': 'LOCAL', 'container': ''}, ''),
    ({'transport': 'CONTAINER', 'container': 'explicit_eda'}, 'explicit_eda'),
    ({}, 'legacy_eda'),
])
def test_a05_emitter_parser_consumes_selected_transport(tmp_path, monkeypatch, options, expected):
    received = []
    monkeypatch.setattr(emitter, 'DEFAULT_CONTAINER', 'legacy_eda')
    def emit(project, only, pdk, container, verify_sim, **kwargs):
        received.append(container)
        return 2, {'blocks_gap': 1, 'gap_status': 'TEST_ONLY_STOP_BEFORE_EMISSION'}
    monkeypatch.setattr(emitter, 'run', emit)
    def invoke(program, args, **kwargs):
        assert program == 'analog_a3_netlist_emit.py'
        return {'returncode': emitter.main(args), 'stdout': '', 'stderr': ''}
    result = front.run_step('A05', tmp_path, {'name': 'neutral'}, options, invoke)
    assert received == [expected]
    assert result['status'] != 'PASS'


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / 'installed'
    model = root / 'process_alpha/libs.tech/ngspice/models/entry.lib'
    model.parent.mkdir(parents=True)
    model.write_text('.lib typical\n.subckt mos_alpha d g s b\n.ends mos_alpha\n.endl typical\n')
    return root


@pytest.mark.parametrize('container', [None, ''])
def test_no_external_container_consumes_attested_selected_root(installed, monkeypatch, container):
    monkeypatch.setattr(availability, 'local_pdks_root', lambda: str(installed))
    result = availability.resolve_pdk('process_alpha', container=container)
    assert result['available'] is True, result
    assert result['pdk_root'] == str(installed / 'process_alpha')
    assert str(installed) in result['spice_libs'][0]


def test_named_external_container_does_not_consume_local_root(monkeypatch):
    def local():
        raise AssertionError('explicit external must not select LOCAL')
    monkeypatch.setattr(availability, 'local_pdks_root', local)
    monkeypatch.setattr(availability, '_docker_lister', lambda container: lambda path: [])
    availability._RESOLVE_CACHE.clear()
    result = availability.resolve_pdk('process_alpha', container='explicit_eda')
    assert result['available'] is False


@pytest.mark.parametrize('fault', ['missing', 'unbound'])
def test_local_refusal_cannot_become_native_availability(monkeypatch, fault):
    def local():
        if fault == 'unbound':
            raise ValueError('LOCAL_PDK_ROOT_IMAGE_ENV_UNBOUND')
        return None
    monkeypatch.setattr(availability, 'local_pdks_root', local)
    result = availability.resolve_pdk('process_alpha', container='')
    assert result['available'] is False
    assert result['probe_ok'] is False
    if fault == 'unbound':
        assert result['reason'] == 'LOCAL_PDK_ROOT_IMAGE_ENV_UNBOUND'


@pytest.fixture
def path_control(tmp_path):
    import os
    import shutil
    from declared_pdk_is_the_pdk_used_check import declared_target
    raw = os.environ.get('A05_PATH_CONTROL_PROJECT')
    if not raw:
        pytest.skip('requires retained declared source and live LOCAL image receipt')
    retained = Path(raw)
    target, _ = declared_target(retained)
    assert target
    selected = availability.resolve_pdk(target, project=retained, container='')
    assert selected['available'], selected
    library = next(Path(p) for p in selected['spice_libs'] if Path(p).is_file())
    project = tmp_path / 'project'
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    # Source bytes, not a copied acceptance or a new PDK mapping.
    shutil.copyfile(retained / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
                    docs / 'L19_CONSTRAINTS_PDK.json')
    assert declared_target(project)[0] == target
    deck = project / 'phase3/analog/neutral/neutral.sp'
    deck.parent.mkdir(parents=True)
    deck.write_text('.include ' + str(library) + '\n.end\n')
    return project, library, deck


@pytest.mark.parametrize('staged', [False, True])
def test_actual_bound_selected_model_path_is_linted(path_control, tmp_path, staged):
    import analog_netlist_path_lint as lint
    import shutil
    project, library, _ = path_control
    directory = project
    if staged:
        directory = tmp_path / 'verification'
        shutil.copytree(project / 'phase3', directory / 'phase3')
    result = lint.run_audit(directory, real_root=project if staged else None)
    assert result.verdict == 'PASS', result
    assert result.summary['non_whitelisted_absolute_paths'] == 0
    assert library.is_file()


@pytest.mark.parametrize('fault', ['no_attestation', 'bad_attestation', 'wrong_declared_family',
                                    'arbitrary_store', 'missing_file', 'traversal', 'symlink'])
def test_unbound_store_path_is_refused(path_control, tmp_path, monkeypatch, fault):
    import analog_netlist_path_lint as lint
    import librelane_contract as contract
    project, library, deck = path_control
    if fault == 'no_attestation':
        monkeypatch.delenv(contract.LOCAL_ATTESTATION_ENV)
    elif fault == 'bad_attestation':
        broken = tmp_path / 'invalid-launch.json'
        broken.write_text('{}')
        monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(broken))
    elif fault == 'wrong_declared_family':
        (project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').write_text(
            json.dumps({'fields': {'pdk_target': 'unavailable-neutral-process'}}))
    elif fault == 'arbitrary_store':
        # A real immutable file, but outside the selected PDK model tree.
        library = Path('/proc/self/exe').resolve()
        assert str(library).startswith('/nix/store/') and library.is_file()
        deck.write_text('.include ' + str(library) + '\n')
    elif fault == 'missing_file':
        deck.write_text('.include ' + str(library.parent / 'missing-neutral-model.lib') + '\n')
    elif fault == 'traversal':
        deck.write_text('.include ' + str(library.parent) + '/../' + library.parent.name + '/' + library.name + '\n')
    else:
        alias = tmp_path / 'model-alias.lib'
        alias.symlink_to(library)
        deck.write_text('.include ' + str(alias) + '\n')
    result = lint.run_audit(project)
    assert result.verdict == 'FAIL'
    assert result.summary['non_whitelisted_absolute_paths'] == 1

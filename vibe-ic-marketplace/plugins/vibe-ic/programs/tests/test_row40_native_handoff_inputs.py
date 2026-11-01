"""Source-only adapter transport controls. No physical geometry credit."""
import hashlib
import json
from pathlib import Path

import pytest
import librelane_contract as contract
import pad_ring_gen as pads
import _pad_ring as ring
import _seal_ring_frame as frames
from _tapeout_declaration import DECLARATION_REL
from test_pdk_registry_resolves_inside_the_eda_container import in_image, _fake_pdk, _p3
from test_flow109_d32_metric_reader import (
    population,
    test_actual_input_reader_binds_source_declaration_and_selected_views as bind_population,
)


@pytest.mark.parametrize('placement', ['inside', 'outside', None])
def test_pad_adapter_retains_original_declaration_bytes(tmp_path, monkeypatch, placement):
    import flow109_admission as admission
    project = tmp_path / 'project'
    project.mkdir()
    floor = project / 'floorplan.def'
    assignment = project / 'assignment.json'
    floor.write_text('SOURCE_ONLY floorplan\n')
    assignment.write_text('{}\n')
    declaration = project / DECLARATION_REL
    declaration.parent.mkdir(parents=True)
    if placement is not None:
        declaration.write_text(json.dumps({'answers': {'seal_ring_placement': placement}}) + '\n ')
    inputs = {str(floor): hashlib.sha256(floor.read_bytes()).hexdigest()}
    if declaration.exists():
        inputs[str(declaration)] = hashlib.sha256(declaration.read_bytes()).hexdigest()
    monkeypatch.setattr(admission, 'require_launch_admission', lambda *a: {})
    monkeypatch.setattr(contract, 'local_image_attestation', lambda *a: {})
    monkeypatch.setattr(pads, '_d32_inputs', lambda *a: {
        'inputs': inputs, 'floorplan': str(floor), 'assignment': str(assignment),
        'pdk_root': str(project / 'pdks'), 'pdk': 'neutral', 'io_lefs': []})
    observed = []

    def producer(argv):
        case = Path(argv[0])
        copied = case / DECLARATION_REL
        observed.append((frames.placement(case), copied.read_bytes() if copied.exists() else None))
        report = case / ring.REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'verdict': 'FAIL', 'reason': 'SOURCE_ONLY_STOP_BEFORE_NATIVE'}))
        return 1

    monkeypatch.setattr(pads, 'main', producer)
    result = pads.execute(project, {'requested_step': 'D32', 'native_step_id': 'flow109.D32',
                                   'resolved_row': {'profile': {'id': 'analog_die'}}})
    assert observed == [(placement or 'inside', declaration.read_bytes() if placement else None)]
    if placement:
        assert result['inputs'][str(declaration)] == hashlib.sha256(declaration.read_bytes()).hexdigest()
    assert result['native_started'] is False
    assert result['component_status'] == 'FAIL'


@pytest.mark.parametrize('placement', ['inside', 'outside', None])
def test_actual_pad_readset_binds_optional_tapeout_declaration(population, monkeypatch, placement):
    bind_population(population, monkeypatch, 'current')
    project, *_ = population
    declaration = project / DECLARATION_REL
    declaration.parent.mkdir(parents=True, exist_ok=True)
    if placement is not None:
        declaration.write_text(json.dumps({'answers': {'seal_ring_placement': placement}}) + '\n ')
    before = pads._d32_inputs(project)
    if placement is None:
        assert str(declaration) not in before['inputs']
    else:
        assert before['inputs'][str(declaration)] == hashlib.sha256(declaration.read_bytes()).hexdigest()
        declaration.write_bytes(declaration.read_bytes() + b' ')
        after = pads._d32_inputs(project)
        assert before['inputs'][str(declaration)] != after['inputs'][str(declaration)]
    current = pads._d32_inputs(project)
    assert pads._d32_inputs(project) == current


def test_actual_pad_readset_refuses_symlinked_tapeout_declaration(population, monkeypatch):
    bind_population(population, monkeypatch, 'current')
    project, *_ = population
    declaration = project / DECLARATION_REL
    declaration.parent.mkdir(parents=True, exist_ok=True)
    original = project / 'original-declaration.json'
    original.write_text('{"answers":{"seal_ring_placement":"outside"}}\n')
    declaration.symlink_to(original)
    with pytest.raises(ValueError, match='D32_DECLARATION_SOURCE_UNBOUND'):
        pads._d32_inputs(project)


def test_in_image_registry_uses_the_attested_selected_pdk_root(in_image, tmp_path, monkeypatch):
    m = _p3()
    tree = _fake_pdk(tmp_path)
    image = 'example.invalid/eda@sha256:' + 'a' * 64
    monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(tmp_path / 'launch_identity.json'))
    monkeypatch.setenv('PDK_ROOT', str(tree.parent))
    monkeypatch.setattr(contract, 'local_image_attestation', lambda *a: {
        'image': image, 'image_id': 'sha256:' + 'b' * 64, 'repo_digests': [image]})
    registry = {'name': tree.name, 'container_path': '/absent/legacy/pdks/' + tree.name,
                'liberty_glob': 'libs.ref/scl/lib/*tt*.lib',
                'tech_lef_glob': 'libs.ref/scl/techlef/*.tlef',
                'cell_lef_glob': 'libs.ref/scl/lef/*.lef', 'tapcell_master': None}
    resolved = m._pdk_config_from_registry(tmp_path, registry)
    assert resolved is not None, 'selected PDK exists under the attested image root, legacy alias does not'
    assert resolved.liberty == str(tree / 'libs.ref/scl/lib/scl__tt_025C_1v80.lib')
    assert resolved.tech_lef == str(tree / 'libs.ref/scl/techlef/scl__nom.tlef')


def test_in_image_invalid_attestation_cannot_use_legacy_alias(in_image, tmp_path, monkeypatch):
    m = _p3()
    tree = _fake_pdk(tmp_path)
    monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(tmp_path / 'missing-identity.json'))
    monkeypatch.setenv('PDK_ROOT', str(tree.parent))
    with pytest.raises(SystemExit, match='LL_LOCAL_IMAGE_UNATTESTED'):
        m._pdk_config_from_registry(tmp_path, {'name': tree.name, 'container_path': str(tree)})

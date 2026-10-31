"""Source-owned RTL applicability preserves strict physical admission."""
from argparse import Namespace
from pathlib import Path
import json

import pytest

import flow109
import _delivery_route


def _request(tmp_path, monkeypatch):
    registry = flow109.load_registry()
    features = {key: False for key in registry['predicate_names']
                if key not in registry['predicate_definitions']}
    features.update(always=True, has_digital=True, soft_ip=True)
    (tmp_path / 'input/rtl').mkdir(parents=True)
    (tmp_path / 'input/phase1_prompt.md').write_text('Debug the supplied RTL; return corrected Verilog.\n')
    (tmp_path / 'input/rtl/unit.v').write_text('module Unit(input a, output y); assign y=a; endmodule\n')
    manifest = tmp_path / 'input/flow109-manifest.json'
    manifest.write_text(json.dumps({'features': features, 'step_profiles': {}}))
    args = Namespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
                     execution_mode='default', entry_step='D01', exit_step='D01',
                     delivery_target='rtl', route=None)
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.setenv(flow109.ATTEMPT_ENV, "")
    return args


def test_scope_bound_to_sources_manifest_and_project(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    before = (tmp_path / 'input/rtl/unit.v').read_bytes()
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert _delivery_route.admit(tmp_path, 'ip') is None
    assert _delivery_route.report_label(tmp_path)['delivery_route'] == 'RTL'
    assert not (tmp_path / 'input/step_0_5ic_answers.json').exists()
    assert (tmp_path / 'input/rtl/unit.v').read_bytes() == before
    assert _delivery_route.admit(tmp_path, 'ic').startswith('FLOW109_RTL_SCOPE_CONFLICT')
    assert 'no owner-attested' in _delivery_route.admit(tmp_path, allow_rtl_scope=False)
    foreign = tmp_path / 'different_project'
    foreign.mkdir()
    with pytest.raises(flow109.Flow109Error, match='foreign request path'):
        flow109.active_rtl_scope(foreign)


@pytest.mark.parametrize('relative', ['input/phase1_prompt.md', 'input/rtl/unit.v', 'input/flow109-manifest.json'])
def test_scope_refuses_changed_input_bytes(tmp_path, monkeypatch, relative):
    args = _request(tmp_path, monkeypatch)
    flow109.prepare_front_door(args, tmp_path)
    path = tmp_path / relative
    path.write_text(path.read_text() + '\n')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_STALE'):
        flow109.active_rtl_scope(tmp_path)


def test_scope_refuses_changed_source_issuer(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    flow109.prepare_front_door(args, tmp_path)
    original = flow109._file_digest
    monkeypatch.setattr(flow109, '_file_digest', lambda path:
                        '0' * 64 if path.name == 'phase1_one_shot_runner.py' else original(path))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_STALE'):
        flow109.active_rtl_scope(tmp_path)


def test_explicit_scope_cannot_select_physical_manifest(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    manifest = json.loads(args.flow109_manifest.read_text())
    manifest['features'].update(soft_ip=False, hard_ip=True, digital_netlist=True, technology_specific=True)
    args.flow109_manifest.write_text(json.dumps(manifest))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_CONFLICT'):
        flow109.prepare_front_door(args, tmp_path)
    assert not (tmp_path / 'input/step_0_5ic_answers.json').exists()


def test_explicit_scope_cannot_expand_into_synthesis(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    # A synthesis owner is outside the requested RTL evidence.
    args.entry_step = args.exit_step = 'D21'
    with pytest.raises(flow109.Flow109Error):
        flow109.prepare_front_door(args, tmp_path)


def test_scoped_request_cannot_claim_qualification(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    manifest = json.loads(args.flow109_manifest.read_text())
    manifest['qualification_registry'] = 'qualification.json'
    args.flow109_manifest.write_text(json.dumps(manifest))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_CONFLICT'):
        flow109.prepare_front_door(args, tmp_path)


def test_scope_refuses_stale_context_identity(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    flow109.prepare_front_door(args, tmp_path)
    import os
    path = Path(os.environ[flow109.CONTEXT_ENV])
    context = json.loads(path.read_text())
    context['rtl_scope']['project'] = str(tmp_path / 'foreign')
    path.write_text(json.dumps(context))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_CONTEXT_STALE'):
        flow109.active_rtl_scope(tmp_path)


def test_frontdoor_prompt_copy_does_not_change_original_authority(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    flow109.prepare_front_door(args, tmp_path)
    staged = tmp_path / 'input/docs/design_description.md'
    staged.parent.mkdir()
    staged.write_bytes((tmp_path / 'input/phase1_prompt.md').read_bytes())
    assert _delivery_route.admit(tmp_path, 'ip') is None
    staged.write_text('A different unpublished specification.\n')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_RTL_SCOPE_STALE'):
        flow109.active_rtl_scope(tmp_path)


@pytest.mark.parametrize('physical_request', [
    'Build a complete chip and deliver GDS for tapeout.',
    'Deliver a standalone hardmacro with LEF, Liberty and GDS.',
])
def test_scope_cannot_override_physical_source_request(tmp_path, monkeypatch, physical_request):
    args = _request(tmp_path, monkeypatch)
    (tmp_path / 'input/phase1_prompt.md').write_text(physical_request)
    with pytest.raises(flow109.Flow109Error, match='original source requests physical delivery'):
        flow109.prepare_front_door(args, tmp_path)


def test_scope_preserves_prior_declaration_without_using_it_as_authority(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    owner = tmp_path / 'input/step_0_5ic_answers.json'
    owner.write_text(json.dumps({'schema': 'vibe-ic/step_0_5ic_answers/1',
                                'answers': {'deliverable': 'HARDMACRO'},
                                'answer_provenance': {'deliverable': {
                                    'answered_by': 'owner', 'citation': 'Earlier recorded project delivery choice.'}}}))
    before = owner.read_bytes()
    flow109.prepare_front_door(args, tmp_path)
    label = _delivery_route.report_label(tmp_path)
    retained = label['delivery_scope']['retained_delivery_declarations']
    assert label['delivery_route'] == 'RTL'
    assert retained[0]['declared_deliverable'] == 'HARDMACRO'
    assert retained[0]['scope_authority'] is False
    assert owner.read_bytes() == before


def test_current_owner_physical_request_is_not_overridden(tmp_path, monkeypatch):
    args = _request(tmp_path, monkeypatch)
    quotation = 'Deliver a standalone hardmacro with LEF, Liberty and GDS.'
    (tmp_path / 'input/phase1_prompt.md').write_text(quotation)
    owner = tmp_path / 'input/step_0_5ic_answers.json'
    owner.write_text(json.dumps({'answers': {'deliverable': 'HARDMACRO'},
                                'answer_provenance': {'deliverable': {
                                    'answered_by': 'owner', 'citation': quotation}}}))
    before = owner.read_bytes()
    with pytest.raises(flow109.Flow109Error, match='original source requests physical delivery'):
        flow109.prepare_front_door(args, tmp_path)
    assert owner.read_bytes() == before

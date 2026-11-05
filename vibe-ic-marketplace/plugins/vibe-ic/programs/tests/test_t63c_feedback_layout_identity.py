"""The streamed mask and its feedback receipt must describe the same bytes."""
import hashlib
import json
from types import SimpleNamespace
import pytest

import drc_feedback_repair as feedback


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _layout(tmp_path):
    project = tmp_path / 'unit'
    pnr = project / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (project / 'reports/phase3').mkdir(parents=True)
    source = pnr / 'unit.def'
    gds = pnr / 'unit.gds'
    source.write_text('DESIGN unit ;\n')
    (pnr / 'routed.def').write_bytes(source.read_bytes())
    gds.write_bytes(b'finished-mask')
    receipt = project / 'reports/phase3/drc_feedback.json'
    receipt.write_text(json.dumps({
        'status': 'PASS', 'source_sha256': _sha(source.read_bytes()),
        'finished_status': 'PASS', 'finished_gds_sha256': _sha(gds.read_bytes()),
        'finished_counts': {'CO.6a': 0}}))
    return project, source, gds, receipt






def test_finished_gds_mutation_refused_and_exact_bytes_accepted(tmp_path):
    project, _, gds, _ = _layout(tmp_path)
    assert feedback.check_binding(project, 'unit', gds)[0]
    gds.write_bytes(b'finishing-created-a-contact-overlap')
    assert feedback.check_binding(project, 'unit', gds) == (
        False, 'FEEDBACK_LAYOUT_DIGEST_MISMATCH_OR_UNMEASURED')


def test_route_and_stream_def_must_have_the_same_bytes(tmp_path):
    project, _, gds, _ = _layout(tmp_path)
    (project / 'phase3/stage3/pnr/routed.def').write_text(
        'DESIGN unit ;\n# a different routed revision\n')
    assert not feedback.check_binding(project, 'unit', gds)[0]


def test_finished_rule_is_measured_on_the_finished_file(tmp_path, monkeypatch):
    project, _, gds, receipt = _layout(tmp_path)
    seen = []
    def measured(_image, _project, _deck, _rule, path, _top, _scratch):
        seen.append(path)
        return [{'contact_overlap': True}]
    monkeypatch.setattr(feedback, '_measure', measured)
    result = feedback.verify_streamed(
        project, 'unit', SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'),
        'sha256:' + '0' * 64, gds)
    assert seen == [gds]
    assert result['finished_counts'] == {'CO.6a': 1}
    assert result['finished_status'] == 'REFUSED'
    assert not feedback.check_binding(project, 'unit', gds)[0]
    assert json.loads(receipt.read_text())['finished_reason'] == (
        'FEEDBACK_FINISHED_GDS_RULE_NONZERO')


def test_finished_zero_rule_is_bound_to_the_exact_mask(tmp_path, monkeypatch):
    project, _, gds, _ = _layout(tmp_path)
    monkeypatch.setattr(feedback, '_measure', lambda *a: [])
    result = feedback.verify_streamed(
        project, 'unit', SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'),
        'sha256:' + '0' * 64, gds)
    assert result['finished_status'] == 'PASS'
    assert result['finished_counts'] == {'CO.6a': 0}
    assert feedback.check_binding(project, 'unit', gds)[0]


def test_finished_layout_change_during_rule_measurement_is_refused(tmp_path, monkeypatch):
    project, _, gds, _ = _layout(tmp_path)
    def measured(*_args):
        gds.write_bytes(b'mask-changed-while-deck-was-running')
        return []
    monkeypatch.setattr(feedback, '_measure', measured)
    result = feedback.verify_streamed(
        project, 'unit', SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'),
        'sha256:' + '0' * 64, gds)
    assert result['finished_status'] == 'REFUSED'
    assert result['finished_reason'] == (
        'FEEDBACK_FINISHED_LAYOUT_CHANGED_DURING_MEASUREMENT')
    assert not feedback.check_binding(project, 'unit', gds)[0]








def test_an_absent_finished_mask_names_where_it_looked(tmp_path):
    """`reason` stays the bare machine code; the receipt also names the path
    the refusal searched, so "not there" cannot read as "never looked"."""
    project, _, gds, receipt = _layout(tmp_path)
    gds.unlink()
    result = feedback.verify_streamed(
        project, 'unit', SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'),
        'sha256:' + '0' * 64, gds)
    assert result['finished_status'] == 'REFUSED'
    assert result['finished_reason'] == 'FEEDBACK_FINISHED_GDS_MISSING'
    assert str(gds) in result['finished_reason_where']
    assert json.loads(receipt.read_text())['finished_reason_where'] == (
        result['finished_reason_where'])


@pytest.mark.parametrize('deck_text,count', [(None, None),
                                             ('puts no-policy\n', 0)])
def test_an_absent_route_layer_policy_names_the_deck_it_read(
        tmp_path, deck_text, count):
    deck = tmp_path / 'phase3/stage3/pnr/pnr.tcl'
    if deck_text is not None:
        deck.parent.mkdir(parents=True)
        deck.write_text(deck_text)
    with pytest.raises(ValueError) as caught:
        feedback._route_layer_policy(tmp_path)
    assert str(caught.value) == 'FEEDBACK_ROUTE_LAYER_POLICY_MISSING'
    assert str(deck) in caught.value.where
    if count is not None:
        assert f'{count} distinct' in caught.value.where


def test_a_def_without_a_design_statement_names_the_def(tmp_path):
    source = tmp_path / 'unit.def'
    source.write_text('VERSION 5.8 ;\n')
    with pytest.raises(ValueError) as caught:
        feedback._def_design(source)
    assert str(caught.value) == 'FEEDBACK_DEF_DESIGN_MISSING'
    assert str(source) in caught.value.where

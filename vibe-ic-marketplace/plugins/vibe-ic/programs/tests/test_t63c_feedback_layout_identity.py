"""The streamed mask and its feedback receipt must describe the same bytes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

import drc_feedback_repair as feedback
import phase3_one_shot_runner as runner


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


def test_final_drc_without_state_does_not_fall_back_to_old_feedback(tmp_path, monkeypatch):
    project, source, _, _ = _layout(tmp_path)
    source.write_text('DESIGN unit ;\n# later route writer\n')
    monkeypatch.setattr(runner, '_vacuous_on_unrouted',
                        lambda *a: runner.StepResult('drc', 'PASS', 0, 'sentinel'))
    result = runner.step_drc(project, 'unit',
                             SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'), 'eda')
    assert result.status == 'NOT_MEASURED'
    assert result.reason_class == 'input_absent'
    assert 'CURRENT_FINAL_STATE_MISSING: state_out.json' in result.detail


def test_private_sdr_candidate_can_measure_before_feedback_but_signoff_needs_state(tmp_path, monkeypatch):
    project, _, _, receipt = _layout(tmp_path / 'sdr_candidates')
    receipt.unlink()
    monkeypatch.setattr(runner, '_vacuous_on_unrouted',
                        lambda *a: runner.StepResult('drc', 'PASS', 0, 'candidate measured'))
    pdk = SimpleNamespace(drc_deck='/pdk/gf180mcu.drc')
    assert runner.step_drc(project, 'unit', pdk, 'eda', candidate=True).status == 'PASS'
    result = runner.step_drc(project, 'unit', pdk, 'eda')
    assert result.status == 'NOT_MEASURED'
    assert result.reason_class == 'input_absent'
    assert 'CURRENT_FINAL_STATE_MISSING: state_out.json' in result.detail


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
    feedback._instrument_calibration.assert_calibrated('drc_feedback_repair::run')
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
    feedback._instrument_calibration.assert_calibrated('drc_feedback_repair::run')
    monkeypatch.setattr(feedback, '_measure', lambda *a: [])
    result = feedback.verify_streamed(
        project, 'unit', SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'),
        'sha256:' + '0' * 64, gds)
    assert result['finished_status'] == 'PASS'
    assert result['finished_counts'] == {'CO.6a': 0}
    assert feedback.check_binding(project, 'unit', gds)[0]


def test_finished_layout_change_during_rule_measurement_is_refused(tmp_path, monkeypatch):
    project, _, gds, _ = _layout(tmp_path)
    feedback._instrument_calibration.assert_calibrated('drc_feedback_repair::run')
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


def test_prestream_admission_refuses_old_feedback(tmp_path, monkeypatch):
    project, source, _, _ = _layout(tmp_path)
    source.write_text('DESIGN unit ;\n# changed by signoff repair\n')
    monkeypatch.setattr(runner, '_vacuous_on_unrouted', lambda *a: None)
    monkeypatch.setattr(runner, '_layout_basis', lambda *a: ('digest', ''))
    monkeypatch.setattr(runner._ga, 'gate_passed', lambda *a: True)
    result = runner.step_gds(project, 'unit',
                             SimpleNamespace(drc_deck='/pdk/gf180mcu.drc'), 'eda')
    assert result.status == 'FAIL'
    assert 'FEEDBACK_ROUTE_DIGEST_MISMATCH' in result.detail


def test_feedback_reads_the_route_after_si_promotion(tmp_path, monkeypatch):
    project, source, _, _ = _layout(tmp_path)
    pdk = SimpleNamespace(drc_deck='/pdk/gf180mcu.drc')
    monkeypatch.setattr(runner, '_layout_basis',
                        lambda *a: (_sha(source.read_bytes()), ''))
    monkeypatch.setattr(runner, 'step_canonicalize_artefacts',
                        lambda *a, **k: runner.StepResult('canonicalize', 'PASS', 0, 'ok'))
    monkeypatch.setattr(runner, '_signoff_regen', lambda *a: False)
    monkeypatch.setattr(runner, '_si_mcf_repair_seam', lambda *a: object())
    monkeypatch.setattr(runner, '_si_mcf_repair_promote',
                        lambda *a: source.write_text('DESIGN unit ;\n# SI promoted\n'))
    import si_mcf_verdict_basis
    import si_mcf_repair
    monkeypatch.setattr(si_mcf_verdict_basis, 'apply', lambda *a: None)
    calls = iter([{'decision': 'ADOPTED', 'after': {}},
                  {'decision': 'NO_CANDIDATE'}])
    monkeypatch.setattr(si_mcf_repair, 'run_once', lambda *a, **k: next(calls))
    monkeypatch.setattr(feedback, 'has_reviewed_rule', lambda *a: True)
    monkeypatch.setattr(feedback, 'image_for_container', lambda *a: 'image')
    seen = []
    def feedback_run(*_a, **_k):
        seen.append(source.read_text())
        digest = _sha(source.read_bytes())
        return {'status': 'PASS', 'source_sha256': digest,
                'initial_source_sha256': digest}
    monkeypatch.setattr(feedback, 'run', feedback_run)
    def stop_after_feedback(*_a):
        raise RuntimeError('stop after feedback')
    monkeypatch.setattr(runner, '_run_declared_signoff_gate', stop_after_feedback)
    with pytest.raises(RuntimeError, match='stop after feedback'):
        runner.step_prestream_gate(project, 'unit', pdk, 'eda')
    assert seen and set(seen) == {'DESIGN unit ;\n# SI promoted\n'}


def test_port_marker_producer_keeps_mask_bytes_out_of_lvs_copy(tmp_path, monkeypatch):
    project, source, gds, _ = _layout(tmp_path)
    pdk = SimpleNamespace(liberty='', port_label_restore=True)
    monkeypatch.setattr(runner, '_tool_in_path', lambda *a: True)
    monkeypatch.setattr(runner, '_resolve_magic_gds_tech', lambda *a: None)
    monkeypatch.setattr(runner._pl, 'pnr_dir', lambda *a: gds.parent)
    def fake_eda(_container, _cmd, **_kw):
        (gds.parent / 'unit.labeled.gds').write_bytes(b'LVS-only-marker-100/8')
        gds.with_suffix('.mask-labeled.gds').write_bytes(before)
        return 0, 'restored: 1 I/O labels + 0 power-rail markers ()', ''
    monkeypatch.setattr(runner, '_docker_exec', fake_eda)
    before = gds.read_bytes()
    ok, _ = runner._klayout_restore_port_labels(
        project, 'unit', pdk, 'eda', gds, source, force=True)
    assert ok
    assert gds.read_bytes() == before
    assert gds.with_suffix('.lvs.gds').read_bytes() == b'LVS-only-marker-100/8'


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

"""Source-only controls for Step 36 / our 37.5ic native-State consumers.

Maintenance inputs below are neutral protocol fixtures, not physical signoff.
Producer judgments must come from the actual producer program, never a copied
PASS document. Captured native integration has a separate evidence scope.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import signoff_ladder_run as ladder
import general_precheck as precheck
import tapeout_checklist_gen as checklist
from _native_signoff_fixture import producer, finished_producer, antenna_producer, put, IMAGE


@pytest.mark.parametrize('case,expected',[
    ('clean','PASS'),('changed','NOT_MEASURED'),
    ('missing','NOT_MEASURED'),('native_red','FAIL'),('same_project','PASS')])
def test_explicit_external_full_gds_lvs_uses_current_receipted_inputs(tmp_path,monkeypatch,case,expected):
    import librelane_contract as contract
    import librelane_signoff_evidence as evidence
    import librelane_pv_signoff as pv
    measurement=tmp_path/'measurement';measurement.mkdir()
    current=tmp_path/'current-owner';current.mkdir()
    layout=(measurement/'phase3/stage4/gds/current.gds' if case=='same_project'
            else current/'current.gds')
    layout.parent.mkdir(parents=True,exist_ok=True);layout.write_bytes(b'current neutral full-GDS subject')
    if case!='same_project':
        old=measurement/'phase3/stage4/gds/old.gds';old.parent.mkdir(parents=True)
        old.write_bytes(b'older retained stream; not this explicit invocation')
    chain=contract.run_chain
    def explicit_inputs(*args,**kwargs):
        monkeypatch.setattr(contract,'run_chain',chain)
        state=args[2][0][2];doc=json.loads(state.read_text())
        for view in ('def','pnl','nl','sdc'):
            source=Path(doc[view]);target=current/source.name
            target.write_bytes(source.read_bytes());doc[view]=str(target)
        put(state,doc)
        return chain(*args,**kwargs)
    monkeypatch.setattr(contract,'run_chain',explicit_inputs)
    info=producer(measurement,monkeypatch,'lvs',gds_path=layout,
                  counts={'design__lvs_error__count':3} if case=='native_red' else {})
    reference=current/'input.pnl'
    if case=='changed':reference.write_text('changed after actual receipt creation\n')
    elif case=='missing':reference.rename(reference.with_suffix('.held'))
    observed=evidence.obligation(measurement,'lvs',layout=layout)
    assert observed['verdict']==expected,{'observed':observed,'expected':expected}
    if case in ('clean','same_project'):
        assert set(observed['rows'])=={'magic__illegal_overlap__count',*pv.PRODUCED['Netgen.LVS']}
        assert all(type(row['value']) is int and row['value']==0 for row in observed['rows'].values())
        # This allowance does not let a same-project subject bypass its current
        # canonical stream or let another PV kind adopt an external subject.
        internal=measurement/'other.gds'
        internal.write_bytes(b'stale subject' if case=='same_project' else layout.read_bytes())
        assert evidence.obligation(measurement,'lvs',layout=internal)['verdict']=='NOT_MEASURED'
        assert evidence.obligation(measurement,'drc',layout=layout)['verdict']=='NOT_MEASURED'
        if case=='same_project':
            original=reference.read_bytes();reference.write_text('changed external reference after receipt\n')
            assert evidence.obligation(measurement,'lvs',layout=layout)['verdict']=='NOT_MEASURED'
            reference.write_bytes(original)
        record=json.loads(info['record'].read_text());record['scope']['magic_ext_use_gds']=False
        put(info['record'],record)
        assert evidence.obligation(measurement,'lvs',layout=layout)['verdict']=='NOT_MEASURED'
    elif case=='native_red':
        assert observed['rows']['design__lvs_error__count']['value']==3
    observation={'case':case,'expected':expected,'observed':observed,
                 'scope':'Neutral process edge; actual run_chain/judge/current receipt consumer; no native run'}
    (tmp_path/'EXTERNAL_LVS_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    print('EXPLICIT_EXTERNAL_LVS',json.dumps(observation))


def _put(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _select(project: Path, mode: str, step: str = "31") -> None:
    _put(project / "phase3/librelane_switch.json", {"steps": {step: mode}})


def _legacy_reports(project: Path) -> None:
    # These are deliberate legacy-parser controls, not native producer evidence.
    _put(project / "reports/drc/full_deck.json", {"violations": 0})
    path = project / "reports/phase3/lvs.rpt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Netlists match uniquely.\nFinal result: Circuits match uniquely.\n")


@pytest.mark.parametrize("obligation", ["drc", "lvs"])
def test_tool_selected_ladder_cannot_credit_a_legacy_pass(tmp_path, obligation):
    _select(tmp_path, "librelane")
    _legacy_reports(tmp_path)
    check = (ladder.check_tier_1_drc if obligation == "drc"
             else ladder.check_tier_lvs_tapeout)
    result = check(tmp_path)
    assert result.verdict == "NOT_RUN", (result.verdict, result.details)


@pytest.mark.parametrize("obligation", ["drc", "lvs"])
def test_direct_selected_ladder_keeps_its_existing_authority(tmp_path, obligation):
    _select(tmp_path, "direct")
    _legacy_reports(tmp_path)
    check = (ladder.check_tier_1_drc if obligation == "drc"
             else ladder.check_tier_lvs_tapeout)
    result = check(tmp_path)
    if obligation == "lvs":
        # A direct-mode text match is triage, not full-GDS extraction evidence.
        # The default LVS authority must not release it without its producer.
        assert result.verdict == "NOT_RUN", (result.verdict, result.details)
        assert result.details["verdict"] == "NOT_MEASURED"
        assert result.details["reason"] == "LL_FINISHED_GDS_MISSING"
    else:
        assert result.verdict == "PASS", (result.verdict, result.details)


def test_tool_selected_checklist_does_not_credit_a_done_marker(tmp_path):
    _select(tmp_path, "librelane", "34")
    marker = tmp_path / "phase3/stage3/pnr/metal_fill.done"
    marker.parent.mkdir(parents=True)
    marker.write_text("PASS\n")
    assert checklist.main([str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "reports/audit/tapeout_checklist.json").read_text())
    item = next(row for row in payload["items"] if row["name"] == "metal_fill_flag")
    assert item["presence_is_pass"] is False, item


def test_tool_selected_our_drc_does_not_run_a_legacy_delegate(tmp_path):
    _select(tmp_path, "librelane")
    step = next(s for s in precheck.LADDER if s.step_id == "Checker.KLayoutDRC")
    result = precheck._blank(step)
    calls = []

    def legacy_delegate(command, timeout):
        calls.append(command)
        return 0, "legacy checker says clean", ""

    precheck._step_delegate(result, step, tmp_path, legacy_delegate,
                            precheck._HERE, 60)
    assert result.verdict == precheck.NOT_DETERMINED, result
    assert calls == [], calls


@pytest.mark.parametrize('obligation', ['drc', 'lvs'])
def test_current_actual_python_producer_is_consumed(tmp_path, monkeypatch, obligation):
    producer(tmp_path, monkeypatch, obligation, both_lvs=obligation == 'lvs')
    result = (ladder.check_tier_1_drc if obligation == 'drc'
              else ladder.check_tier_lvs_tapeout)(tmp_path)
    assert result.verdict == 'PASS', result.details
    assert all(row['receipt'] for row in result.details['rows'].values())


@pytest.mark.parametrize('obligation,key,count,missing', [
    ('drc', 'magic__drc_error__count', 7, ('KLayout.DRC',)),
    ('lvs', 'design__lvs_error__count', 612, ('KLayout.LVS',)),
])
def test_measured_failure_dominates_missing_engine(tmp_path, monkeypatch, obligation, key, count, missing):
    producer(tmp_path, monkeypatch, obligation, counts={key: count}, missing=missing,
             both_lvs=obligation == 'lvs')
    _legacy_reports(tmp_path)
    result = (ladder.check_tier_1_drc if obligation == 'drc'
              else ladder.check_tier_lvs_tapeout)(tmp_path)
    assert result.verdict == 'FAIL', result.details
    assert result.details['rows'][key]['value'] == count


def test_standalone_old_producer_cannot_drop_second_lvs_engine(tmp_path, monkeypatch):
    producer(tmp_path, monkeypatch, 'lvs', missing=('Netgen.LVS',))
    assert ladder.check_tier_lvs_tapeout(tmp_path).verdict == 'NOT_RUN'


@pytest.mark.parametrize('damage', ['engine', 'inherited', 'gds', 'image', 'pdk',
                                   'config', 'receipt', 'input', 'bool', 'negative', 'text'])
def test_wrong_or_missing_identity_refuses_current_credit(tmp_path, monkeypatch, damage):
    key = 'magic__drc_error__count'
    counts = {key: {'bool': True, 'negative': -1, 'text': '0'}[damage]} if damage in ('bool', 'negative', 'text') else None
    info = producer(tmp_path, monkeypatch, counts=counts,
                    inherited={key: 0} if damage == 'inherited' else None,
                    missing=('KLayout.DRC',) if damage == 'engine' else ())
    if damage == 'gds':
        info['gds'].write_bytes(b'new finished bytes')
    elif damage == 'image':
        path = tmp_path / 'phase3/librelane_switch.json'
        doc = json.loads(path.read_text()); doc['image'] = IMAGE.replace('a' * 64, 'b' * 64); put(path, doc)
    elif damage == 'pdk':
        path = tmp_path / 'phase3/librelane_pdk_root.provenance.json'
        doc = json.loads(path.read_text()); doc['pdk'] = 'foreign'; put(path, doc)
    elif damage == 'config':
        info['configs']['Magic.DRC'].write_text('{}')
    elif damage == 'receipt':
        (info['folders'][0] / 'vibeic_receipt.json').unlink()
    elif damage == 'input':
        info['deck'].write_text('changed input deck')
    _legacy_reports(tmp_path)
    result = ladder.check_tier_1_drc(tmp_path)
    assert result.verdict == 'NOT_RUN', result.details
    assert any(row['value'] == 'NOT_MEASURED' for row in result.details.get('rows', {}).values()) or result.details['reason']


@pytest.mark.parametrize('count,verdict', [(0, precheck.PASS), (4, precheck.FAIL)])
def test_our_cached_drc_is_an_own_authority_without_delegate_execution(tmp_path, monkeypatch, count, verdict):
    info = producer(tmp_path, monkeypatch, counts={'klayout__drc_error__count': count})
    step = next(s for s in precheck.LADDER if s.step_id == 'Checker.KLayoutDRC')
    result = precheck._blank(step)
    def no_legacy(*args):
        pytest.fail('native selected rung ran legacy delegate')
    precheck._step_delegate(result, step, tmp_path, no_legacy, precheck._HERE, 60, layout=info['gds'])
    assert result.verdict == verdict, result
    assert result.returncode is None
    assert result.measured['value'] == count


@pytest.mark.parametrize('count,verdict', [(0, 'PASS'), (9, 'FAIL')])
def test_finished_stream_drc_reads_each_actual_producer(tmp_path, monkeypatch, count, verdict):
    finished_producer(tmp_path, monkeypatch, counts={'magic__drc_error__count': count})
    result = ladder.check_tier_1_drc(tmp_path)
    assert result.verdict == verdict, result.details
    magic = result.details['rows']['magic__drc_error__count']
    klayout = result.details['rows']['klayout__drc_error__count']
    assert magic['value'] == count and klayout['value'] == 0
    assert 'magic-drc/state_out.json' in magic['source']
    assert 'klayout-drc/state_out.json' in klayout['source']


def test_finished_drc_positive_survives_malformed_own_summary(tmp_path, monkeypatch):
    import librelane_signoff_evidence as native

    finished_producer(tmp_path, monkeypatch, counts={'magic__drc_error__count': 3})
    path = tmp_path / 'phase3/librelane/37-magic-final-drc/drc_judgment.json'
    doc = json.loads(path.read_text())
    doc['metrics']['magic__drc_error__count']['value'] = 'malformed'
    put(path, doc)

    result = native.obligation(tmp_path, 'drc')
    assert result['rows']['magic__drc_error__count']['value'] == 3, result
    assert result['rows']['klayout__drc_error__count']['value'] == 0, result
    assert result['verdict'] == 'FAIL', result
    checked = ladder.check_tier_1_drc(tmp_path)
    assert checked.verdict == 'FAIL', checked.details
    assert checked.details['rows']['magic__drc_error__count']['value'] == 3
    step = next(s for s in precheck.LADDER if s.step_id == 'Checker.MagicDRC')
    cached = precheck._blank(step)
    def no_legacy(*args):
        pytest.fail('native selected rung ran legacy delegate')
    precheck._step_delegate(cached, step, tmp_path, no_legacy, precheck._HERE, 60)
    assert cached.verdict == precheck.FAIL, cached


@pytest.mark.parametrize('count,verdict', [(0, 'PASS'), (3, 'FAIL')])
def test_density_uses_the_finished_stream_receipt(tmp_path, monkeypatch, count, verdict):
    finished_producer(tmp_path, monkeypatch, counts={'klayout__density_error__count': count})
    result = ladder.check_tier_metal_density(tmp_path)
    assert result.verdict == verdict, result.details
    assert result.details['rows']['klayout__density_error__count']['value'] == count


def test_old_lvs_cannot_certify_new_finished_stream(tmp_path, monkeypatch):
    producer(tmp_path, monkeypatch, 'lvs', both_lvs=True)
    old = json.loads((tmp_path / 'reports/phase3/librelane_pv_lvs.json').read_text())
    finished_producer(tmp_path, monkeypatch)
    new_source = tmp_path / 'phase3/librelane/maintenance/finished.gds'
    new_source.write_bytes(b'NEW_FINISHED_PROTOCOL_BYTES')
    gds = tmp_path / 'phase3/stage4/gds/maintenance.gds'
    gds.write_bytes(new_source.read_bytes())
    promo = tmp_path / 'phase3/librelane/37-promotion.json'
    doc = json.loads(promo.read_text())
    import librelane_contract as contract
    doc['source_sha256'] = doc['canonical_sha256'] = contract.digest(gds); put(promo, doc)
    _legacy_reports(tmp_path)
    result = ladder.check_tier_lvs_tapeout(tmp_path)
    assert old['scope']['gds_sha256'] != contract.digest(gds)
    assert result.verdict == 'NOT_RUN', result.details
    assert result.details['reason'] == 'LL_JUDGED_SELECTED_GDS_MISMATCH'




def test_native_selection_forwards_same_gds_to_both_independent_authorities(tmp_path, monkeypatch):
    import test_tapeout_precheck_two_arms as existing
    project = existing._project(tmp_path, existing._die_at_origin, existing._DIE_ANSWERS,
                                pdk='gf180mcuD', slots=True)
    gds = project / 'phase3/stage4/gds/chip_top.gds'
    producer(project, monkeypatch, gds_path=gds)
    calls = []
    external_operator = existing._mirror_operator(flip='KLayout.CheckSize', flip_to=precheck.FAIL)
    def runner(command, timeout):
        calls.append(command)
        return external_operator(command, timeout)
    result = existing.TP.evaluate(project, runner=runner)
    assert result.arms_expected == 2 and result.arms_ran == 2
    assert len(calls) == 2
    assert all('--gds' in command for command in calls), calls
    assert all(command[command.index('--gds') + 1] == str(gds) for command in calls)
    assert result.verdict == existing.TP.FAIL
    assert {v['authority_is_ours'] for v in result.disagreements[0]['verdicts']} == {True, False}


@pytest.mark.parametrize('count,verdict', [(0, 'PASS'), (2, 'FAIL')])
def test_step34_actual_density_producer_record_is_consumed(tmp_path, monkeypatch, count, verdict):
    import librelane_contract as contract
    import librelane_fill_dfm as fill
    info = producer(tmp_path, monkeypatch, counts={'klayout__density_error__count': count})
    config = put(tmp_path / 'phase3/librelane/34-config/KLayout.Density.json', {
        'meta': {'step': 'KLayout.Density'}, 'KLAYOUT_DENSITY_RUNSET': str(info['deck'])})
    put(contract.views_path(config), {'step': 'KLayout.Density', 'inputs': ['gds'], 'outputs': []})
    # Ratios are a separate native process edge, outside this count consumer.
    monkeypatch.setattr(fill, 'measure_density_ratios', lambda *a, **kw: {'scope': 'NOT_MEASURED_PROTOCOL_EDGE'})
    actual = fill.run_density(tmp_path, IMAGE, info['tree'].parent, 'procx',
        gds=info['gds'], lane='34-density', configs={'KLayout.Density': config},
        steps=('KLayout.Density',))
    fill.update_record(tmp_path, 'gds', {'shipped': 'librelane', 'librelane': actual})
    result = ladder.check_tier_metal_density(tmp_path)
    assert result.verdict == verdict, result.details
    assert result.details['rows']['klayout__density_error__count']['value'] == count


@pytest.mark.parametrize('field', ['metrics', 'scope', 'metric_row', 'sibling_row'])
def test_malformed_producer_record_refuses_credit_without_fallback(tmp_path, monkeypatch, field):
    info = producer(tmp_path, monkeypatch)
    doc = json.loads(info['record'].read_text())
    if field == 'metric_row':
        doc['metrics']['magic__drc_error__count'] = True
    elif field == 'sibling_row':
        doc['metrics']['klayout__drc_error__count'] = True
    else:
        doc[field] = ['malformed']
    put(info['record'], doc)
    _legacy_reports(tmp_path)
    result = ladder.check_tier_1_drc(tmp_path)
    assert result.verdict == 'NOT_RUN', result.details
    assert 'LL_MALFORMED_OBJECT' in result.details['reason']


@pytest.mark.parametrize('count,verdict', [(0, 'NOT_RUN'), (6, 'FAIL')])
def test_additional_unavailable_declared_engine_does_not_hide_measured_failure(tmp_path, monkeypatch, count, verdict):
    info = producer(tmp_path, monkeypatch, counts={'magic__drc_error__count': count})
    doc = json.loads(info['record'].read_text())
    doc['required_steps'].append('Maintenance.UnavailableEngine')
    put(info['record'], doc)
    _legacy_reports(tmp_path)
    result = ladder.check_tier_1_drc(tmp_path)
    assert result.verdict == verdict, result.details
    assert result.details['rows']['magic__drc_error__count']['value'] == count


def _mismatched_selection(project):
    import librelane_contract as contract
    canonical = project / 'phase3/stage4/gds/chip_top.gds'
    source = project / 'phase3/librelane/maintenance/finished.gds'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(canonical.read_bytes())
    put(project / 'phase3/librelane/37-promotion.json', {
        'selection': 'magic', 'source': str(source), 'source_sha256': contract.digest(source),
        'finished': {'magic': str(source)}, 'canonical': str(canonical),
        'canonical_sha256': contract.digest(canonical)})
    put(project / 'phase3/librelane_switch.json', {
        'steps': {'31': 'direct', '34': 'direct', '37': 'librelane'}})
    source.write_bytes(b'CHANGED_SELECTED_SOURCE_BYTES')
    return canonical


def test_refused_finished_selection_cannot_be_overwritten_by_two_passing_arm_reports(tmp_path):
    import test_tapeout_precheck_two_arms as existing
    project = existing._project(tmp_path, existing._die_at_origin, existing._DIE_ANSWERS,
                                pdk='gf180mcuD', slots=True)
    _mismatched_selection(project)
    # A pure merge control using the EXISTING two-process report fixture.
    # No native producer verdict is fabricated; both authorities still run.
    result = existing.TP.evaluate(project, runner=existing._stub_both(
        existing._all_green([s.step_id for s in precheck.LADDER]),
        existing._all_green(existing._OPERATOR_LADDER)))
    assert result.verdict == precheck.NOT_DETERMINED, result.reason
    assert result.arms_ran == 2
    assert all(arm.verdict == precheck.PASS for arm in result.arms)
    assert 'LL_FINISHED_GDS_CHANGED' in result.reason


def test_general_precheck_discloses_refused_selection_and_retains_its_geometry(tmp_path):
    import test_tapeout_precheck_two_arms as existing
    project = existing._project(tmp_path, existing._die_at_origin, existing._DIE_ANSWERS,
                                pdk='gf180mcuD', slots=True)
    _mismatched_selection(project)
    result = precheck.evaluate(project)
    assert 'LL_FINISHED_GDS_CHANGED' in result.reason, result.reason
    assert result.layout_binding['verdict'] == precheck.NOT_DETERMINED
    reader = next(row for row in result.steps if row.step_id == 'KLayout.ReadLayout')
    assert reader.verdict == precheck.PASS
    assert result.geometry


def test_tool_selected_antenna_cannot_credit_a_legacy_delegate(tmp_path):
    _select(tmp_path, 'librelane', '26')
    step = next(s for s in precheck.LADDER if s.step_id == 'Checker.KLayoutAntenna')
    result = precheck._blank(step); calls = []
    def legacy(command, timeout):
        calls.append(command); return 0, 'legacy says clean', ''
    precheck._step_delegate(result, step, tmp_path, legacy, precheck._HERE, 60)
    assert result.verdict == precheck.NOT_DETERMINED, result
    assert calls == []


@pytest.mark.parametrize('counts,missing,verdict', [
    ({}, False, precheck.PASS),
    ({'klayout__antenna_error__count': 5}, False, precheck.FAIL),
    ({'antenna__violating__pins': 2}, False, precheck.FAIL),
    ({'klayout__antenna_error__count': 5}, True, precheck.FAIL),
    ({'klayout__antenna_error__count': True}, False, precheck.NOT_DETERMINED),
    ({'antenna__violating__nets': -1}, False, precheck.NOT_DETERMINED),
])
def test_actual_antenna_producers_bind_both_models_for_our_rung(tmp_path, monkeypatch, counts, missing, verdict):
    info = antenna_producer(tmp_path, monkeypatch, counts=counts, missing_router=missing)
    step = next(s for s in precheck.LADDER if s.step_id == 'Checker.KLayoutAntenna')
    result = precheck._blank(step); calls = []
    def legacy(command, timeout):
        calls.append(command); return 0, 'legacy says clean', ''
    precheck._step_delegate(result, step, tmp_path, legacy, precheck._HERE, 60, layout=info['gds'])
    assert result.verdict == verdict, result
    assert calls == []
    tier = ladder.check_tier_3_antenna(tmp_path)
    assert tier.verdict == ('NOT_RUN' if verdict == precheck.NOT_DETERMINED else verdict), tier.details


@pytest.mark.parametrize('flag,value,verdict', [
    ('routing_incomplete', True, 'FAIL'),
    ('route_modified_after_last_verification', True, 'FAIL'),
    ('routing_incomplete', None, 'NOT_RUN'),
])
def test_native_antenna_preserves_route_refusal_and_absence(tmp_path, monkeypatch, flag, value, verdict):
    antenna_producer(tmp_path, monkeypatch)
    path = tmp_path / 'reports/phase3/antenna_librelane.json'
    doc = json.loads(path.read_text()); doc[flag] = value; put(path, doc)
    result = ladder.check_tier_3_antenna(tmp_path)
    assert result.verdict == verdict, result.details


@pytest.mark.parametrize('kind,key,malformed', [
    ('drc', 'klayout__drc_error__count', 'magic__drc_error__count'),
    ('antenna', 'antenna__violating__pins', 'gds'),
])
def test_later_current_failure_survives_a_malformed_sibling(tmp_path, monkeypatch, kind, key, malformed):
    if kind == 'drc':
        info = producer(tmp_path, monkeypatch, counts={key: 6})
        path = info['record']; doc = json.loads(path.read_text())
        doc['metrics'][malformed] = True
        check = ladder.check_tier_1_drc
    else:
        antenna_producer(tmp_path, monkeypatch, counts={key: 6})
        path = tmp_path / 'reports/phase3/antenna_librelane.json'
        doc = json.loads(path.read_text()); doc[malformed] = True
        check = ladder.check_tier_3_antenna
    put(path, doc)
    result = check(tmp_path)
    assert result.verdict == 'FAIL', result.details
    assert result.details['rows'][key]['value'] == 6


@pytest.mark.parametrize('kind,step,name', [
    ('antenna', '26', 'antenna_report'), ('density', '34', 'density_report'),
])
def test_tool_selected_advisory_inventory_is_not_measurement(tmp_path, kind, step, name):
    _select(tmp_path, 'librelane', step)
    marker = tmp_path / ('reports/phase3/antenna.rpt' if kind == 'antenna' else 'reports/density.rpt')
    marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text('0 violations\n')
    assert checklist.main([str(tmp_path)]) == 0
    doc = json.loads((tmp_path / 'reports/audit/tapeout_checklist.json').read_text())
    item = next(row for row in doc['items'] if row['name'] == name)
    assert item['presence_is_pass'] is False, item
    assert item['native_evidence']['verdict'] == 'NOT_MEASURED', item


def test_finished_density_metrics_cell_uses_current_density_producer(tmp_path, monkeypatch):
    info = finished_producer(tmp_path, monkeypatch, counts={'klayout__density_error__count': 3})
    earlier = json.loads(info['record'].read_text())
    assert earlier['metrics']['klayout__density_error__count']['value'] == 0




def test_our_zero_rungs_refuse_an_unfinished_aggregate_binding(tmp_path, monkeypatch):
    info = finished_producer(tmp_path, monkeypatch)
    path = tmp_path / 'phase3/librelane/37-magic-final-drc/drc_judgment.json'
    doc = json.loads(path.read_text()); doc['source'] = True; put(path, doc)
    for name in ('Checker.MagicDRC', 'Checker.KLayoutDRC'):
        step = next(s for s in precheck.LADDER if s.step_id == name)
        result = precheck._blank(step)
        precheck._step_delegate(result, step, tmp_path, lambda *a: (0, '', ''),
                                precheck._HERE, 60, layout=info['gds'])
        assert result.verdict == precheck.NOT_DETERMINED, result

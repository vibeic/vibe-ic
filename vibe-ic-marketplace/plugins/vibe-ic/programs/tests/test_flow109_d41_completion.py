"""SOURCE_ONLY D41 completion; reuses only the new D41 neutral fixture.

Unit qualification/source authority APIs are doubles; no runtime/IC PASS.
Previously completed CTS and digital controls are not selected or replayed.
"""
import json
from pathlib import Path
import pytest
import librelane_postroute_repair as repair
from _ppa import closure
from test_flow109_d41_binding import case,sha


def test_no_repair_is_measured_zero_with_complete_native_census(case):
    folders,baseline=case.chains['32-base']
    state=folders[-1]/'state_out.json';body=json.loads(state.read_text())
    for corner in case.corners:
        body['metrics']['timing__setup__ws__corner:'+corner]=.5
        baseline['setup_ws'][corner]=.5
        p=folders[0]/('native_signoff/sta_'+corner+'.rpt');p.write_text('OCV_BASIS flat_ocv\nworst slack max 0.5\nworst slack min 0.2\n')
    state.write_text(json.dumps(body));case.receipts[str(state.parent)]['sha256']['state_out.json']=sha(state)
    baseline.update(setup_ws_min=.5,sta_state_sha256=sha(state))
    case.report.update(baseline=baseline,final=baseline,adopted=None,adopted_state=str(case.initial),candidates=[],closure=[],
        repair_trigger=repair.measured_repair_trigger(baseline))
    case.current.write_text(json.dumps({'candidate':None,'repair_state':str(case.initial),'repair_input':str(case.initial),
        'repair_folder':str(folders[0]),'measurement':baseline}))
    case.ledger.unlink()
    handoff={'state':str(case.initial),'state_sha256':sha(case.initial),'views':{}}
    initial=json.loads(case.initial.read_text())
    for view,filename in [('def','routed.def'),('nl','neutral_pnr.v')]:
        src=Path(initial[view]);dest=case.put('phase3/stage3/pnr/'+filename,src.read_text())
        handoff['views'][view]={'source':str(src),'dest':str(dest),'source_sha256':sha(src),'dest_sha256':sha(dest)}
    case.put('reports/phase3/librelane_postroute_repair_handoff.json',handoff)
    result=case.publish()['metric_acceptance']
    assert result['metric_status']=='PASS',json.dumps(result,indent=2)
    assert result['obligations'][2]['measurement']['value']==0
    assert (case.project/repair.DECLARED_REPAIR_REL/'no_repair_needed.flag').is_file()
    assert not (case.project/repair.DECLARED_REPAIR_REL/'repair_log.json').exists()


@pytest.mark.parametrize('outcome,expected',[('PLATEAU','FAIL'),('BUDGET_EXHAUSTED','FAIL'),('NOT_MEASURED','NOT_MEASURED')])
def test_original_controller_terminal_outcome_cannot_be_reset(case,outcome,expected):
    record=case.report['closure'][0];record['outcome']=outcome;record['closed_loop_success']=False
    record['digest']=closure.cj.digest_of({k:v for k,v in record.items() if k!='digest'})
    case.publish()
    result=case.observe()
    assert result['status']==expected,json.dumps(result,indent=2)
    assert json.loads(case.ledger.read_text())['candidates'][0]['candidate']=='32-cand01'
    assert result['obligations'][2]['history']['candidate_attempts']==1


def test_unmeasured_additional_modes_are_never_filled_by_one_scene(case):
    case.bodies['requirements/base_28/post_repair_timing_drv.json'][1]['modes']=['functional','scan']
    result=case.observe()
    assert result['status']=='NOT_MEASURED'
    assert result['obligations'][0]['reason']=='D41_MODE_POPULATION_UNAVAILABLE'














@pytest.mark.parametrize('missing',[False,True])
def test_original_collateral_failure_or_missing_success_is_not_green(case,missing):
    record=case.report['closure'][0]
    if missing:record.pop('closed_loop_success')
    else:
        record['closed_loop_success']=False
        record['collateral_regressions']=[{'domain':'timing.hold','before':.4,'after':.2,'scope':'SOURCE_ONLY_CONTROLLER_RECORD'}]
    record['digest']=closure.cj.digest_of({k:v for k,v in record.items() if k!='digest'})
    case.publish()
    result=case.observe()
    assert result['status']==('NOT_MEASURED' if missing else 'FAIL'),json.dumps(result,indent=2)

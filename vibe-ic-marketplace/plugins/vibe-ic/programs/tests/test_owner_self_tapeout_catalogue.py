"""Owner DIE plus explicit operator absence retains IC obligations and catalogue evidence."""
import json
import shutil
import pytest
import _submission_template as ST
import _tapeout_declaration as TD
import submission_template_ingest as ING
import submission_template_check as CHK
import tapeout_declaration_gen as GEN
import tapeout_precheck as TP
from _hostpaths import require_repo


def fixture(tmp_path, kind='DIE', change=None, selected=False):
    p=tmp_path/'design';p.mkdir();t=tmp_path/'catalogue';t.mkdir()
    (t/'neutral.json').write_text(json.dumps({'DIE_AREA':[0,0,800,1000],'SEAL_RING_WIDTH':10}))
    assert ING.main([str(p),'--template',str(t)]+(['--slot','neutral'] if selected else []))==0
    raw={'answers':{'deliverable':kind},'answer_provenance':{'deliverable':{'answered_by':'owner','citation':'Neutral owner input: deliver DIE unless this fixture explicitly selects IP.'}},'operator_template':{'path':None,'slot':None,'absent_reason':'Owner selects independent tapeout; no operator purchase or slot applies.'}}
    doc,_=TD.merge_answers(TD.blank_declaration(),dict(raw['answers'],answer_provenance=raw['answer_provenance']))
    if change=='no-owner':raw['answer_provenance']['deliverable']['answered_by']='agent';doc['answer_provenance']['deliverable']['answered_by']='agent'
    elif change=='no-citation':raw['answer_provenance']['deliverable']['citation']='';doc['answer_provenance']['deliverable']['citation']=''
    elif change=='mismatch':raw['answers']['deliverable']='HARDMACRO'
    elif change=='missing-path':raw['operator_template'].pop('path')
    elif change=='missing-slot':raw['operator_template'].pop('slot')
    elif change=='empty-reason':raw['operator_template']['absent_reason']=' '
    elif change=='operator-path':raw['operator_template']['path']=str(t)
    elif change=='operator-slot':raw['operator_template']['slot']='neutral'
    elif change=='unknown':raw['answers']['deliverable']=TD.NOT_DETERMINED;doc['answers']['deliverable']=TD.NOT_DETERMINED
    elif change=='ring-conflict':raw['answers']['seal_ring_required']=True;doc['answers']['seal_ring_required']=False
    own=p/ST.DESIGN_ANSWERS_REL;own.parent.mkdir(exist_ok=True,parents=True);own.write_text(json.dumps(raw))
    (p/TD.DECLARATION_REL).write_text(json.dumps(doc))
    return p,own,t


def test_owner_die_catalogue_slot_gate_and_chip_route(tmp_path):
    p,_,_=fixture(tmp_path)
    assert CHK.slot_rules_are_owed(p,None)[0] is False
    assert CHK.catalogue_selects_ip(p)[0] is False
    assert TP.delivery_route(p)[0]==TP.ROUTE_CHIP
    assert TD.declared_route_on_disk(p,True)==(TD.ROUTE_SELF_TAPEOUT,None)
    doc=json.loads((p/ST.REPORT_REL).read_text())
    result=CHK.evaluate(p,doc,None)
    assert result['verdict']==ST.VERDICT_NOT_APPLICABLE


def test_owner_route_producer_checker_agree_without_deleting_catalogue(tmp_path):
    p,own,_=fixture(tmp_path)
    rec=GEN.build(p,own)
    assert rec['route']==TD.ROUTE_SELF_TAPEOUT
    GEN.write_artefacts(p,rec)
    assert (p/TD.SELF_TAPEOUT_REL).is_file()
    assert list((p/ST.SLOTS_DIR_REL).glob('*.yaml'))
    # Choosing self-tapeout does not remove unanswered physical DIE questions.
    assert TD.audit(rec['declaration'])['sections'][TD.SECTION_PAD_RING]['unanswered']>0


def _relocated_owner_tree(tmp_path):
    """Run the real producer chain shape, then checkpoint-copy the project."""
    original = tmp_path/'original'
    original.mkdir()
    catalogue = original/ST.STAGED_TEMPLATE_REL
    catalogue.mkdir(parents=True)
    (catalogue/'neutral.json').write_text(json.dumps({
        'DIE_AREA':[0,0,800,1000], 'SEAL_RING_WIDTH':10}))
    assert ING.main([str(original), '--template', str(catalogue)]) == 0
    raw = {
        'answers': {'deliverable': 'DIE'},
        'answer_provenance': {'deliverable': {
            'answered_by': 'owner', 'citation': 'Neutral owner DIE route'}},
        'operator_template': {'path': None, 'slot': None,
                              'absent_reason': 'Owner selects independent tapeout; no operator purchase applies.'},
    }
    own = original/ST.DESIGN_ANSWERS_REL
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text(json.dumps(raw))
    GEN.write_artefacts(original, GEN.build(original, own))
    moved = tmp_path/'checkpoint'
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    return moved


def test_relocated_catalogue_remains_information_not_a_second_route(tmp_path):
    moved = _relocated_owner_tree(tmp_path)
    record = json.loads((moved/ST.REPORT_REL).read_text())
    checked = CHK.evaluate(moved, record, None)
    assert checked['verdict'] == ST.VERDICT_NOT_APPLICABLE
    assert checked['examined']['template_files_relocated'] == 1


def test_relocated_catalogue_hash_change_preserves_route_refusal(tmp_path):
    moved = _relocated_owner_tree(tmp_path)
    (moved/ST.STAGED_TEMPLATE_REL/'neutral.json').write_text('{}')
    assert CHK.catalogue_selects_self_tapeout(moved)[0] is False


def test_relocated_catalogue_selected_slot_preserves_route_refusal(tmp_path):
    moved = _relocated_owner_tree(tmp_path)
    record = json.loads((moved/ST.REPORT_REL).read_text())
    record['ingest']['declared_slot'] = 'neutral'
    (moved/ST.REPORT_REL).write_text(json.dumps(record))
    own = moved/ST.DESIGN_ANSWERS_REL
    owner = json.loads(own.read_text())
    owner['operator_template']['slot'] = 'neutral'
    own.write_text(json.dumps(owner))
    assert CHK.catalogue_selects_self_tapeout(moved)[0] is False


def test_relocated_catalogue_source_escape_preserves_route_refusal(tmp_path):
    moved = _relocated_owner_tree(tmp_path)
    outside = tmp_path/'outside.json'
    outside.write_text((moved/ST.STAGED_TEMPLATE_REL/'neutral.json').read_text())
    record = json.loads((moved/ST.REPORT_REL).read_text())
    record['ingest']['slots'][0]['source_relpath'] = '../outside.json'
    (moved/ST.REPORT_REL).write_text(json.dumps(record))
    assert CHK.catalogue_selects_self_tapeout(moved)[0] is False




def test_self_tapeout_operator_arm_not_invoked(tmp_path):
    p,_,_=fixture(tmp_path)
    assert TP.operator_arm_applicability(p,'gf180mcu')[0]==TP.NOT_APPLICABLE


@pytest.mark.parametrize('case',['no-owner','no-citation','mismatch','missing-path','missing-slot','empty-reason','operator-path','operator-slot','unknown','ring-conflict'])
def test_absence_requires_complete_consistent_authority(tmp_path,case):
    p,_,_=fixture(tmp_path,change=case)
    assert CHK.slot_rules_are_owed(p,None)[0] is True
    assert CHK.catalogue_selects_ip(p)[0] is False
    assert TD.declared_route_on_disk(p,True)[0]!=TD.ROUTE_SELF_TAPEOUT
    assert TP.operator_arm_applicability(p,'gf180mcu')[0]!=TP.NOT_APPLICABLE


def test_selected_operator_slot_remains_shuttle(tmp_path):
    p,own,_=fixture(tmp_path,selected=True)
    assert CHK.slot_rules_are_owed(p,'neutral')[0] is True
    assert GEN.build(p,own)['route']==TD.ROUTE_SHUTTLE
    assert TD.declared_route_on_disk(p,True)[0]==TD.ROUTE_SHUTTLE
    assert TP.operator_arm_applicability(p,'gf180mcu')[0]!=TP.NOT_APPLICABLE


def test_hardmacro_remains_ip_without_operator_purchase(tmp_path):
    p,_,_=fixture(tmp_path,kind='HARDMACRO')
    assert CHK.catalogue_selects_ip(p)[0] is True
    assert TP.delivery_route(p)[0]==TP.ROUTE_IP


def test_changed_catalogue_cannot_exempt_operator_arm(tmp_path):
    p,_,t=fixture(tmp_path)
    (t/'neutral.json').write_text('{}')
    assert TP.operator_arm_applicability(p,'gf180mcu')[0]!=TP.NOT_APPLICABLE
    assert CHK.evaluate(p,json.loads((p/ST.REPORT_REL).read_text()),None)['verdict']==ST.VERDICT_FAIL


def _normal_absence(tmp_path, omitted):
    """The actual 0.5ic CLI emits the absence proof; no native tool runs."""
    p=tmp_path/'design';p.mkdir(parents=True)
    reason='Owner independently selects DIE self-tapeout; no operator purchase or slot applies.'
    raw={'answers':{'deliverable':'DIE'},'answer_provenance':{
        'deliverable':{'answered_by':'owner','citation':'Neutral explicit owner DIE route'}},
        'operator_template':{'path':None,'slot':None,'absent_reason':reason}}
    for key in omitted:raw['operator_template'].pop(key)
    own=p/ST.DESIGN_ANSWERS_REL;own.parent.mkdir(parents=True);own.write_text(json.dumps(raw))
    assert ING.main([str(p),'--template',str(tmp_path/'not-an-operator-template'),
                     '--no-template-reason',reason])==0
    GEN.write_artefacts(p,GEN.build(p,own))
    switch=p/'phase3/librelane_switch.json';switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({'steps':{s:'direct' for s in ['26','31','34','37']}}))
    return p,own


def _absence_cli(p, monkeypatch):
    # Only the unrelated physical-arm subprocess is synthetic. The real CLI
    # reads the actual ingest/declaration and decides operator applicability.
    def run(cmd, timeout):
        assert 'general_precheck.py' in cmd[1], 'an operator subprocess must not run without its template'
        target=__import__('pathlib').Path(cmd[cmd.index('--json')+1])
        target.write_text(json.dumps({'verdict':'PASS','steps':[
            {'step_id':'Synthetic.UnrelatedPhysicalArm','verdict':'PASS',
             'evidence':'Synthetic transport only; no physical measurement claimed'}]}))
        return 0,'synthetic unrelated physical arm',''
    monkeypatch.setattr(TP,'default_runner',run)
    return TP.main([str(p),'--pdk','gf180mcu','--json',str(p/'merged.json')])


@pytest.mark.parametrize('omitted',[('path',),('slot',),('path','slot')])
def test_normal_absent_ingest_optional_keys_reach_the_cli(tmp_path,monkeypatch,omitted):
    p,_=_normal_absence(tmp_path,omitted)
    original=(p/TD.DECLARATION_REL).read_bytes()
    rc=_absence_cli(p,monkeypatch)
    assert rc==0, 'typed explicit no-operator selection acquired a phantom operator obligation'
    report=json.loads((p/'merged.json').read_text())
    assert report['arms'][1]['state']==TP.NOT_APPLICABLE
    assert report['arms_ran']==report['arms_expected']==1
    assert (p/TD.DECLARATION_REL).read_bytes()==original


def test_optional_key_absence_still_requires_the_actual_owner_and_ingest(tmp_path,monkeypatch):
    faults=['selected-path','selected-slot','no-owner','no-citation','no-reason',
            'PRESENT','ERROR','NOT_ATTEMPTED','not-attempted','template-present',
            'declared-slot','undeclared-router','different-reason','missing-proof']
    for fault in faults:
        p,own=_normal_absence(tmp_path/fault,('path','slot'))
        raw=json.loads(own.read_text());record=json.loads((p/ST.REPORT_REL).read_text())
        if fault=='selected-path':raw['operator_template']['path']='operator-template'
        elif fault=='selected-slot':raw['operator_template']['slot']='purchased'
        elif fault=='no-owner':raw['answer_provenance']['deliverable']['answered_by']='agent'
        elif fault=='no-citation':raw['answer_provenance']['deliverable']['citation']=''
        elif fault=='no-reason':raw['operator_template']['absent_reason']=''
        elif fault in {'PRESENT','ERROR','NOT_ATTEMPTED'}:record['ingest']['status']=fault
        elif fault=='not-attempted':record['ingest']['lookup']['attempted']=False
        elif fault=='template-present':record['ingest']['lookup']['template_present']=True
        elif fault=='declared-slot':record['ingest']['declared_slot']='purchased'
        elif fault=='undeclared-router':record['ingest']['path_selector']['declared']=False
        elif fault=='different-reason':record['ingest']['no_template_reason']='A different owner decision, not the current input.'
        own.write_text(json.dumps(raw));(p/ST.REPORT_REL).write_text(json.dumps(record))
        if fault=='missing-proof':(p/ST.REPORT_REL).unlink()
        assert _absence_cli(p,monkeypatch)==1, fault
        result=json.loads((p/'merged.json').read_text())
        assert result['arms'][1]['state']!=TP.NOT_APPLICABLE, fault
        print('OPTIONAL_ABSENCE_NEGATIVE',fault,result['arms'][1]['state'])

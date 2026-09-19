"""Owner DIE plus explicit operator absence retains IC obligations and catalogue evidence."""
import json
import pytest
import _submission_template as ST
import _tapeout_declaration as TD
import submission_template_ingest as ING
import submission_template_check as CHK
import tapeout_declaration_gen as GEN
import tapeout_declaration_check as DC
import tapeout_precheck as TP


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
    report=DC.evaluate(p)
    assert not any(x['rule']=='ROUTER_CONTRADICTION' for x in report['refusals'])
    # Choosing self-tapeout does not remove unanswered physical DIE questions.
    assert TD.audit(rec['declaration'])['sections'][TD.SECTION_PAD_RING]['unanswered']>0


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

import json
from test_owner_self_tapeout_catalogue import fixture
import _submission_template as ST
import _tapeout_declaration as TD
import submission_template_check as CHK
import benchmark_evidence_publish as PUB
import slot_pad_budget_check as BUD
import flow_compliance_check as FLOW


def test_catalogue_disclosure_preserves_die_route(tmp_path):
    p,_,_=fixture(tmp_path)
    result=CHK.evaluate(p,json.loads((p/ST.REPORT_REL).read_text()),None)
    assert result['examined'].get('operator_shuttle_available_not_used',{}).get('declared_route')==TD.ROUTE_SELF_TAPEOUT


def test_publisher_preserves_owner_die(tmp_path):
    p,_,_=fixture(tmp_path)
    assert PUB.design_kind(p)[0]==PUB._KIND_IC


def test_no_purchased_pad_budget_receipt_matches_owner_die(tmp_path):
    p,_,_=fixture(tmp_path)
    assert BUD.main([str(p),'--json','budget.json'])==2
    rep=json.loads((p/'budget.json').read_text())
    assert rep['verdict']=='NOT_APPLICABLE'
    assert rep['applicability_evidence']['assertions']==[{'path':'answers.deliverable','equals':'DIE'}]


def test_die_step_applicability_is_not_ip_exemption(tmp_path):
    p,_,_=fixture(tmp_path)
    spec={'declaration':TD.DECLARATION_REL,'field':'answers.deliverable','absent_when':['HARDMACRO']}
    assert FLOW._delivery_declares_absence(p,spec) is None

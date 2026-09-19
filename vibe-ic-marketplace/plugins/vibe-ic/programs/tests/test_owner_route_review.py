import json
from test_owner_self_tapeout_catalogue import fixture
import _tapeout_declaration as TD
import tapeout_declaration_gen as GEN
import tapeout_declaration_check as DC
import benchmark_evidence_publish as PUB


def test_declaration_checker_override_cannot_borrow_default_route(tmp_path):
    p,own,_=fixture(tmp_path)
    # Native producer determines the route; marker is written only by its writer.
    rec=GEN.build(p,own);GEN.write_artefacts(p,rec)
    assert rec['route']==TD.ROUTE_SELF_TAPEOUT
    doc=json.loads((p/TD.DECLARATION_REL).read_text());doc['answers']['deliverable']='HARDMACRO'
    override=tmp_path/'override.json';override.write_text(json.dumps(doc))
    report=DC.evaluate(p,declaration_path=override)
    assert any(x['rule']=='ROUTER_CONTRADICTION' for x in report['refusals'])


def test_publisher_explains_die_without_claiming_slot_owed(tmp_path):
    p,_,_=fixture(tmp_path)
    kind,why=PUB.design_kind(p)
    assert kind==PUB._KIND_IC
    assert 'no operator slot is owed' in why

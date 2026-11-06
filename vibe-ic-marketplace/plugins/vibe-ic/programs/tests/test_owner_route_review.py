import json
from test_owner_self_tapeout_catalogue import fixture
import _tapeout_declaration as TD
import tapeout_declaration_gen as GEN


def test_declaration_checker_override_cannot_borrow_default_route(tmp_path):
    p,own,_=fixture(tmp_path)
    # Native producer determines the route; marker is written only by its writer.
    rec=GEN.build(p,own);GEN.write_artefacts(p,rec)
    assert rec['route']==TD.ROUTE_SELF_TAPEOUT
    doc=json.loads((p/TD.DECLARATION_REL).read_text());doc['answers']['deliverable']='HARDMACRO'
    override=tmp_path/'override.json';override.write_text(json.dumps(doc))

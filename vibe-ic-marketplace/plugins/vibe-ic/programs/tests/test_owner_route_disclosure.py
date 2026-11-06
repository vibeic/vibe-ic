import json
from test_owner_self_tapeout_catalogue import fixture
import _submission_template as ST
import _tapeout_declaration as TD
import submission_template_check as CHK
import slot_pad_budget_check as BUD


def test_catalogue_disclosure_preserves_die_route(tmp_path):
    p,_,_=fixture(tmp_path)
    result=CHK.evaluate(p,json.loads((p/ST.REPORT_REL).read_text()),None)
    assert result['examined'].get('operator_shuttle_available_not_used',{}).get('declared_route')==TD.ROUTE_SELF_TAPEOUT




def test_no_purchased_pad_budget_receipt_matches_owner_die(tmp_path):
    """OWNER RULING R-0915-98(2), 2026-09-20: a DIE still gets a REAL verdict.

    This receipt used to read NOT_APPLICABLE — the HARDMACRO answer, "nobody's
    slot, so no budget" — which a die inherited once `slot_rules_are_owed`
    learned to say the same of a die that bought nothing. A die is not exempt
    from a pad budget: it IS its own operator (37.5self), and its budget is the
    ring the run builds against the pins it declares. The landed contract in
    `test_issue2277_slot_pad_budget_reads_the_designs_own_route.py::
    test_a_DIE_against_the_same_catalogue_still_gets_a_real_verdict` states it
    and was red on main until that branch existed.

    What this fixture still pins is the ROUTE: the die purchased nothing, so
    the receipt names the die's own basis and not an operator slot. This tree
    stages no RTL, so the measurement itself is UNDECIDED with its reason —
    rc 2 exactly as before, and never a pass.
    """
    p,_,_=fixture(tmp_path)
    assert BUD.main([str(p),'--json','budget.json'])==2
    rep=json.loads((p/'budget.json').read_text())
    assert rep['verdict']!='NOT_APPLICABLE'
    assert rep['verdict']=='UNDECIDED'
    assert rep['budget_basis']=='37.5self:own_pad_ring'
    assert 'owner-attested' in rep['deliverable_source']
    assert 'binds no operator template' in rep['reason']

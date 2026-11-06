"""Area producer and D02 lineage boundary controls, not native acceptance.

The lineage envelope is synthetic; its before/after bytes come from the real
area producer. No Phase-1 or design acceptance is claimed by these fixtures.
"""
import hashlib
import json

import pytest

import _tapeout_declaration as declaration
import area_budget_basis_gen as area


def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value) + '\n').encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def project_with_fixed_die(project):
    put(project, 'input/docs/L9_constraints.md',
        b'# Implementation constraints\nDIE_AREA = [0, 0, 80, 120] um\nFP_SIZING = absolute\n')
    doc = {'answers': {'deliverable': 'DIE', 'top_cell': 'neutral_core'},
           'answer_provenance': {'deliverable': {
               'answered_by': 'owner', 'citation': 'The owner requests a physical die.'}},
           area.KEY: declaration.NOT_DETERMINED}
    put(project, 'input/step_0_5ic_answers.json', doc)
    return doc












@pytest.mark.parametrize('location', ['top', 'nested'])
def test_explicit_not_applicable_survives_fixed_die_producer(tmp_path, location):
    doc = project_with_fixed_die(tmp_path)
    budget = {'status': 'NOT_APPLICABLE', 'rationale': 'No synthesized logic is requested.'}
    if location == 'top':
        doc[area.KEY] = budget
    else:
        doc.pop(area.KEY)
        doc['answers'][area.KEY] = budget
    doc['answer_provenance'][area.KEY] = {
        'answered_by': 'owner', 'citation': 'Explicit implementation-area disposition.'}
    put(tmp_path, 'input/step_0_5ic_answers.json', doc)
    before = (tmp_path / 'input/step_0_5ic_answers.json').read_bytes()
    assert area.main([str(tmp_path)]) == 1
    assert (tmp_path / 'input/step_0_5ic_answers.json').read_bytes() == before
    assert declaration.area_budget_resolution({area.KEY: budget})['status'] == 'NOT_APPLICABLE'




def test_absent_budget_still_derives_fixed_die_limit(tmp_path):
    doc = project_with_fixed_die(tmp_path)
    doc.pop(area.KEY)
    put(tmp_path, 'input/step_0_5ic_answers.json', doc)
    assert area.main([str(tmp_path)]) == 0
    after = json.loads((tmp_path / 'input/step_0_5ic_answers.json').read_text())
    assert after['answers'][area.KEY]['status'] == 'LIMIT'
    assert after['answers'][area.KEY]['max_die_dimensions_um'] == [80.0, 120.0]
    assert area.rederive(tmp_path, after)['answer'] == after['answers'][area.KEY]

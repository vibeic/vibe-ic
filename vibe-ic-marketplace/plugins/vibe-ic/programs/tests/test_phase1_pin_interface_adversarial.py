"""All retained independent-review prose counters are non-authoritative."""
import json
from pathlib import Path
import pytest
from test_phase1_pin_interface_condition import INTERFACE,generate_docs

CASES=json.loads((Path(__file__).parent/'fixtures/phase1_pin_interface_prose.json').read_text())
@pytest.mark.parametrize('case',CASES,ids=[c['case'] for c in CASES])
def test_reviewer_prose_never_projects(tmp_path,case):
    docs=dict(case['docs'])
    # Preserve reviewer documents exactly; add a neutral roster only for the
    # old owning snippets which did not package their own interface.
    if docs.get('interface.md')=='':docs['interface.md']=INTERFACE
    l1,l5=generate_docs(tmp_path,docs)
    assert not [r for p in l1.get('pin_table',[]) for r in p.get('electrical_specs',[]) if r.get('kind')=='input_condition']
    assert not [r for b in l5.get('analog_blocks',[]) for r in (b.get('spec') or {}).get('input_conditions',[])]

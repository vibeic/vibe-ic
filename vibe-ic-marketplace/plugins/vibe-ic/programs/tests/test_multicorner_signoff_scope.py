import pytest
import phase1_post_process as P


def emit(tmp_path,text):
    docs=tmp_path/'input/docs';docs.mkdir(parents=True)
    (docs/'requirements.md').write_text(text)
    doc=P.emit_l_doc_skeleton('L24','unknown',project_dir=tmp_path)
    return doc,{r['check']:r for r in doc['fields']['signoff_requirements']}


@pytest.mark.parametrize('sentence',[
    '> **Multi-corner sign-off**: 每個 library 均須在 **SS(slow / worst-case)、TT(typical)、FF(fast)三 corner** 全部 sign-off 通過。',
    'Multi-corner sign-off: each library must pass SS, TT and FF corners.',
],ids=['input-derived-chinese','neutral-english'])
def test_scoped_corner_requirement_reaches_actual_layer(tmp_path,sentence):
    doc,rows=emit(tmp_path,'# Constraints\n## Synopsys Design Constraints (SDC)\n### Library periods\n'+sentence+'\n')
    row=rows['STA']
    assert row['stated'] is True
    assert row['corners']==['FF','SS','TT']
    assert row['requirement']=='pass'
    assert row['citation']['line']==4 and row['citation']['document']=='input/docs/requirements.md'
    assert 'SS' in row['citation']['text']
    assert all(doc['fields'].get(k) is None for k in ['sta_status','drc_status','lvs_status'])
    assert rows['DRC']['corners']==[] and rows['LVS']['corners']==[]


@pytest.mark.parametrize('text',[
    '# Qualification\nMulti-corner sign-off: each library must pass SS, TT and FF corners.',
    '# SDC\n## Timing constraints\n## Mechanical\nMulti-corner sign-off: each library must pass SS, TT and FF corners.',
    '# SDC\nMulti-corner sign-off at SS, TT, FF was passed in a historical run.',
    '# SDC\nMulti-corner sign-off at SS, TT, FF is not required to pass.',
    '# SDC\nMulti-corner sign-off: DRC must pass SS, TT, FF.',
    '# SDC\nExample: Multi-corner sign-off: each library must pass SS, TT and FF corners.',
],ids=['wrong-domain','sibling-scope-reset','historical','negated','other-check','example'])
def test_unbound_corner_sentence_does_not_invent_sta(tmp_path,text):
    _,rows=emit(tmp_path,text)
    assert rows['STA']['stated'] is False and rows['STA']['corners']==[]


def test_explicit_checks_keep_independent_corner_clauses(tmp_path):
    _,rows=emit(tmp_path,'# Timing constraints\nSTA must pass SS and FF; DRC clean at TT.\n')
    assert rows['STA']['corners']==['FF','SS']
    assert rows['DRC']['corners']==['TT']

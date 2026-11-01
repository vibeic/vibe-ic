"""Only the explicit, signed-source table protocol projects input conditions."""
import json
from pathlib import Path
import pytest
import phase1_doc_one_shot_runner as runner
import analog_a1_spec_emit as a1

INTERFACE = """# Neutral interface
## External Interface
| Signal | Direction | Width |
|---|---|---|
| sense_a | input | 1 |
| sense_b | input | 1 |
## Block A — `pll` : analog phase locked loop operating at 1.5 V
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| fclk | 20 | 19–21 | MHz | output |
"""
HEADER = '| pin | condition | nominal | min | max | unit | consumer_blocks | basis |'
ROW = '| sense_a | externally_driven_reference | 2.0 | 1.96 | 2.04 | V | pll | signed owner input |'
def table(row=ROW):
    return '## Pin interface conditions\n\n'+HEADER+'\n|---|---|---|---|---|---|---|---|\n'+row+'\n'

def generate(tmp_path, declaration, interface=INTERFACE):
    return generate_docs(tmp_path, {'interface.md':interface,'conditions.md':declaration})

def generate_docs(tmp_path, docs):
    for name,text in docs.items():
        path=tmp_path/'input/docs'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    l1=json.loads(Path(runner.gen_l1_datasheet(tmp_path,docs).path).read_text())
    l5=json.loads(Path(runner.gen_l5_adi_spec(tmp_path,docs).path).read_text())
    return l1,l5

def pin_rows(l1,pin='sense_a'):
    return next(p for p in l1['pin_table'] if p['name']==pin).get('electrical_specs',[])
def block_rows(l5):
    return next(b for b in l5['analog_blocks'] if b['name']=='pll').get('spec',{}).get('input_conditions',[])

def test_table_reaches_pin_block_and_consumers(tmp_path):
    l1,l5=generate(tmp_path,table());rows=pin_rows(l1)
    assert len(rows)==1
    assert rows[0]['min_typ_max']=={'typ':2.0,'min':1.96,'max':2.04}
    assert rows[0]['evidence']=={'doc':'input/docs/conditions.md','line':5,'row':ROW}
    assert rows[0]['basis']=='signed owner input'
    assert 'tolerance_percent' not in rows[0]
    assert block_rows(l5)==rows
    entry=next(b for b in l5['analog_blocks'] if b['name']=='pll')
    rec=a1.emit_for_block(tmp_path,entry)
    assert rec['emitted']
    assert json.loads((tmp_path/rec['spec_path']).read_text())['input_conditions']==rows
    import phase1_expert_parse_track as expert
    assert expert.subtree_at(l5,'/analog_blocks/0/spec')[0]['input_conditions']==rows

def test_explicit_none_is_l1_only(tmp_path):
    l1,l5=generate(tmp_path,table(ROW.replace('| pll |','| - |')))
    assert len(pin_rows(l1))==1
    assert block_rows(l5)==[]

@pytest.mark.parametrize('change,error',[
    (lambda t:t.replace('consumer_blocks','consumers'),'TABLE_MALFORMED'),
    (lambda t:t.replace('| sense_a |','| phantom |'),'UNKNOWN_PIN'),
    (lambda t:t.replace('| pll |','| nonexistent |'),'UNKNOWN_CONSUMER'),
    (lambda t:t.replace('| V |','| bananas |'),'UNKNOWN_UNIT'),
    (lambda t:t.replace('| 1.96 | 2.04 |','| 3 | 1 |'),'INVALID_RANGE'),
    (lambda t:t.replace('| 2.0 |','| 5.0 |'),'INVALID_RANGE'),
    (lambda t:t.replace('| 2.0 |','| NaN |'),'TABLE_MALFORMED'),
    (lambda t:t.replace('| 1.96 |','| |'),'TABLE_MALFORMED'),
    (lambda t:t.replace('| signed owner input |','| |'),'TABLE_MALFORMED'),
    (lambda t:t.replace('| pll |','| pll,pll |'),'DUPLICATE_CONSUMER'),
    (lambda t:t.replace('| pll |','| -,pll |'),'TABLE_MALFORMED'),
    (lambda t:t.replace('|---|---|---|---|---|---|---|---|','|---|---|'),'TABLE_MALFORMED'),
    (lambda t:t+'| sense_b | bad |\n','TABLE_MALFORMED'),
])
def test_invalid_table_refuses(tmp_path,change,error):
    with pytest.raises(ValueError,match='PIN_INTERFACE_CONDITION_'+error):
        generate(tmp_path,change(table()))

@pytest.mark.parametrize('different',[False,True])
@pytest.mark.parametrize('reverse',[False,True])
def test_duplicate_pin_refuses_regardless_of_document_order(tmp_path,different,reverse):
    other=table(ROW.replace('2.04','2.05')) if different else table()
    docs={'interface.md':INTERFACE,'a.md':table(),'b.md':other}
    if reverse:docs=dict(reversed(list(docs.items())))
    with pytest.raises(ValueError,match='PIN_INTERFACE_CONDITION_'+('CONFLICT' if different else 'DUPLICATE_PIN')):
        generate_docs(tmp_path,docs)

def test_multiple_rows_are_independent(tmp_path):
    l1,l5=generate(tmp_path,table(ROW+'\n'+ROW.replace('sense_a','sense_b').replace('| pll |','| - |')))
    assert len(pin_rows(l1))==len(pin_rows(l1,'sense_b'))==1
    assert len(block_rows(l5))==1

@pytest.mark.parametrize('text',[table().replace('Pin interface conditions','Proposed interface conditions'), '```markdown\n'+table()+'```'])
def test_only_exact_real_section_is_parsed(tmp_path,text):
    l1,l5=generate(tmp_path,text)
    assert not any(r.get('kind')=='input_condition' for r in pin_rows(l1))
    assert block_rows(l5)==[]

def test_unknown_consumer_without_any_analog_block_refuses(tmp_path):
    interface=INTERFACE.split('## Block A')[0]
    with pytest.raises(ValueError,match='PIN_INTERFACE_CONDITION_UNKNOWN_CONSUMER'):
        generate(tmp_path,table(),interface)

def test_explicit_multiple_consumers_need_no_inferred_ports(tmp_path):
    interface=INTERFACE+'''\n## Block B — `opamp` : operational amplifier
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| gain | 40 | 39–41 | dB | output |
'''
    l1,l5=generate(tmp_path,table(ROW.replace('| pll |','| pll, opamp |')),interface)
    selected=[b for b in l5['analog_blocks'] if b['name'] in {'pll','opamp'}]
    assert {b['name'] for b in selected}=={'pll','opamp'}
    assert all(b['spec']['input_conditions']==pin_rows(l1) for b in selected)

def test_none_does_not_acquire_spice_or_mentioned_consumers(tmp_path):
    interface=INTERFACE+'''\n### pll ports
| Pin | Role |
|---|---|
| sense_a | input reference |
```spice
.subckt pll sense_a sense_b
.ends pll
```
'''
    l1,l5=generate(tmp_path,table(ROW.replace('| pll |','| - |')),interface)
    assert len(pin_rows(l1))==1
    assert block_rows(l5)==[]

def test_table_cannot_declare_its_own_pin(tmp_path):
    with pytest.raises(ValueError,match='PIN_INTERFACE_CONDITION_UNKNOWN_PIN'):
        generate(tmp_path,table(),INTERFACE.replace('| sense_a | input | 1 |\n',''))

def test_stale_l1_cannot_authorize_a_new_l5_row(tmp_path):
    generate(tmp_path,table())
    changed={'interface.md':INTERFACE,'conditions.md':table(ROW.replace('2.04','2.05'))}
    with pytest.raises(ValueError,match='PIN_INTERFACE_CONDITION_L1_NOT_CURRENT'):
        runner.gen_l5_adi_spec(tmp_path,changed)

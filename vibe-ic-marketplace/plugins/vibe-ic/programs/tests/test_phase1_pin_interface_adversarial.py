import hashlib,json,os,sys
from pathlib import Path
import phase1_doc_one_shot_runner as runner
INTERFACE='''# Neutral interface
## External Interface
| Signal | Direction | Width |
|---|---|---|
| sense_a | input | 1 |
| sense_b | input | 1 |
## Block A — `pll` : analog phase locked loop operating at 1.5 V
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| fclk | 20 | 19–21 | MHz | output |
### pll ports
| Pin | Role |
|---|---|
| sense_a | input reference |
'''
def run_case(tmp_path,label,condition,interface=INTERFACE):
 docs={'interface.md':interface,'conditions.md':condition};packet={'arm':os.environ.get('REVIEW_ARM', 'test'),'case':label,'docs':docs,'input_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in docs.items()}}
 for name,text in docs.items():
  p=tmp_path/'input/docs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 try:
  l1=json.loads(Path(runner.gen_l1_datasheet(tmp_path,docs).path).read_text());l5=json.loads(Path(runner.gen_l5_adi_spec(tmp_path,docs).path).read_text())
  packet.update(pin_table=l1['pin_table'],analog_blocks=l5['analog_blocks'],error=None)
 except Exception as exc:packet.update(error=type(exc).__name__+': '+str(exc))
 folder=(tmp_path/'counters')/packet['arm'];folder.mkdir(parents=True,exist_ok=True);(folder/(label+'.json')).write_text(json.dumps(packet,indent=2)+'\n');return packet

def pins(packet,pin='sense_a'):
 return [r for p in packet.get('pin_table',[]) if p['name']==pin for r in p.get('electrical_specs',[])]
def blocks(packet,block='pll'):
 return [r for b in packet.get('analog_blocks',[]) if b['name']==block for r in (b.get('spec') or {}).get('input_conditions',[])]

def test_proposed_heading_does_not_create_current_typed_condition(tmp_path):
 p=run_case(tmp_path,'proposed-heading','# Proposed interface condition\nThe sense_a pin is driven by an external reference, 2.0 V +/- 2%.')
 assert p['error'] is None
 assert pins(p)==[] and blocks(p)==[]

def test_other_pins_tolerance_is_not_invented_for_nominal_only_pin(tmp_path):
 p=run_case(tmp_path,'other-pin-tolerance','The sense_a pin is driven by an external reference, 2.0 V; the sense_b pin is driven by an external reference, 3.0 V +/- 5%.')
 assert p['error'] is None
 assert not any('tolerance_percent' in r or 'min' in r['min_typ_max'] or 'max' in r['min_typ_max'] for r in pins(p))

def test_negated_supersession_does_not_remove_current_conflict(tmp_path):
 p=run_case(tmp_path,'negated-supersession','The sense_a pin is driven by an external reference, 2.0 V +/- 5%.\nThe sense_a pin is driven by an external reference, 2.0 V +/- 1%. This does not replace the earlier declaration.')
 assert p['error'] is not None and 'PIN_INTERFACE_CONDITION_CONFLICT' in p['error']

def test_mentioning_another_block_does_not_declare_its_ports(tmp_path):
 interface=INTERFACE.replace('analog phase locked loop operating at 1.5 V','analog phase locked loop operating at 1.5 V, supplying a clock to the opamp')+'''\n## Block B — `opamp` : analog operational amplifier
### opamp ports
| Pin | Role |
|---|---|
| sense_b | input reference |
'''
 p=run_case(tmp_path,'other-block-heading-mention','The sense_a pin is driven by an external reference, 2.0 V +/- 2%.',interface)
 assert p['error'] is None
 assert blocks(p,'opamp')==[]

def test_existing_continuation_aware_spice_ports_are_not_lost(tmp_path):
 interface=INTERFACE.split('### pll ports')[0]+'.subckt pll sense_b\n+ sense_a\n.ends pll\n'
 p=run_case(tmp_path,'spice-continuation','The sense_a pin is driven by an external reference, 2.0 V +/- 2%.',interface)
 metadata=runner._v1_6_350_parse_spice_metadata(interface)
 assert 'sense_a' in next(s['ports'] for s in metadata['subckts'] if s['name']=='pll')
 p['existing_spice_metadata']=metadata
 folder=(tmp_path/'counters')/p['arm'];(folder/'spice-continuation.json').write_text(json.dumps(p,indent=2)+'\n')
 assert p['error'] is None
 assert blocks(p)==pins(p)

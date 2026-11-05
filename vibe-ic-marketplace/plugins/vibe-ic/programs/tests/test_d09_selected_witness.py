"""Selected properties cannot borrow unselected options as implementation proof."""
import json

from test_flow109_d09_owned_metrics import populate, write

CASES=[
    ('LSB-first','L2_FRS','frs_sections','PASS'),
    ('unsigned','L2_FRS','frs_sections','PASS'),
    ('MSB-first','L2_FRS','frs_sections','NOT_MEASURED'),
    ('signed_2c','L2_FRS','frs_sections','NOT_MEASURED'),
    ('FSM','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('SV','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('sub-module','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('16','L2_FRS','frs_sections','NOT_MEASURED'),
]












def test_required_primary_is_not_selected_secondary(tmp_path):
    import serial_parallel_mul_synth as serial
    p=tmp_path/'unit';populate(p)
    path=p/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';doc=json.loads(path.read_text());doc['integration']={'build_declaration':[{'evidence':'| size_param | yes | 64(primary) / 32(secondary) |'}]};write(path,doc)
    spec,reason=serial.extract_serial_parallel_mul_spec(p,'digital_arithmetic_primitive');assert spec,reason
    out=p/'phase2/stage1/rtl/unit.v';out.parent.mkdir(parents=True);out.write_text(serial.emit_rtl(spec));write(p/'plugin_output/declaration.json',dict(serial.plugin_declaration(spec),size_param=32));declaration,_=serial.planned_declaration(p,spec);write(p/'plugin_output/declaration.json',declaration)
    path=p/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text());d={'id':'required-primary','requirement':'Require size_param primary 64.','evidence':['input/spec.md:4 — primary 64 required']};body['source_demands'].append(d);body['expectations'].append(dict(d,layer='L9_INTEGRATION_SPEC',field_path='integration.build_declaration',expected_tokens=['size_param','64']));write(path,body)
    answer=serial.d09_owned_metrics(p,'digital_arithmetic_primitive')
    assert declaration['size_param']==32
    assert answer['missing_items']==['required-primary'],answer['missing_items']

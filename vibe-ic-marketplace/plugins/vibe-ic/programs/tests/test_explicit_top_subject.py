from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D

@pytest.mark.parametrize('text,expected',[
 ('`sha256` 為**單一 top module**,內部包含 register file + hash datapath(具體拆分由 Plugin 自選)。','sha256'),
 ('`packet_unit` 是**單一 top module**。','packet_unit'),
 ('`packet_unit` is the single top module.','packet_unit'),
 ('`packet_unit` is not the single top module.',None),
 ('Previously `old_unit` was the single top module.',None),
 ('The design has no specified top.',None),
 ('`alpha_unit` 為**單一 top module**。\n`beta_unit` 為**單一 top module**。',None),
 ('`alpha_unit` 為**單一 top module**。\n`alpha_unit` 為**單一 top module**。','alpha_unit'),
],ids=['original','opposite_name','english','negated','historical','absent','ambiguous','repeated_same'])
def test_subject(text,expected):
 assert D._extract_top_module_from_docs({'input.md':text})==expected

def test_full_minimal_l9_producer(tmp_path):
 fixture=Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/explicit_top_context_local/L8_submodule_integration.md'
 docs={fixture.name:fixture.read_text()}
 inp=tmp_path/'input/docs';inp.mkdir(parents=True);(inp/fixture.name).write_text(docs[fixture.name])
 import json
 out=D.gen_l9_integration_spec(tmp_path,docs,{})
 data=json.loads(out.path.read_text())
 assert data['top_module']=='sha256'
 assert data['top_module_extraction_strategy']=='doc_module_decl_or_heading'
 assert not data.get('no_top_module_in_input',False)

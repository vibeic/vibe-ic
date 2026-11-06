"""Converged graph uses the existing native renderer, preserving its namespace."""
import json
from pathlib import Path
import sys
import pytest
PLUGIN=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PLUGIN));sys.path.insert(0,str(PLUGIN/'programs'))
from tools.phase1_engine.schema import FactGraph
from tools.phase1_engine.ingest import from_structured_yaml


def staged(tmp_path):
    graph=FactGraph('neutral_top','any-ic')
    registry=json.loads((PLUGIN/'flow/flow109.json').read_text())
    features=dict(next(r['features'] for r in registry['reference_profiles'] if r['features']['rtl_only']))
    graph.metadata={'flow109_manifest':{'features':features}}
    from tools.phase1_engine.gap_detect import _aggregate_required_facts, DEFAULT_CLASS_KB
    for layer,entries in _aggregate_required_facts(['any-ic'],DEFAULT_CLASS_KB/'templates').items():
        for entry in entries:
            if entry.get('required'):
                graph.add_fact(layer+'.'+entry['path'],'source fact',[layer],'user_stated',origin='input/design.md:1')
    ports=[{'name':n,'direction':d,'width':w} for n,d,w in [('enable','input',1),('isolate','input',1),('value','output',8)]]
    data={'L9.top_module':'neutral_top','L9.top_ports':ports,'L9.top_level_ports':ports,'L9.parameters':[],
          'L9.clock_ports':[],'L9.reset_ports':[],
          'L2.requirements':[{'id':'constant','text':'stored holds the declared literal','constant':{'module':'storage','port':'stored','bits':['0','1','0','1','1','0','1','0']}}],
          'L6.submodule_control_logic':{'storage':'initial assignment; no FSM is declared'},
          'L21.retention':[{'name':'hold','elements':['state']}],
          'L22.test_cases':[{'id':'restore','purpose':'preserve declared restoration scenario'}]}
    for path,value in data.items():graph.add_fact(path,value,[path.split('.')[0]],'derived',origin='input/rtl/design.sv:1-2')
    path=tmp_path/'input/phase1_structured.yaml';path.parent.mkdir(parents=True);graph.save(path)
    docs=tmp_path/'input/docs';docs.mkdir()
    (docs/'design.sv').write_text("module storage(output logic [7:0] stored); initial stored=8'h5a; endmodule\nmodule neutral_top(input enable,isolate,output [7:0] value); storage state(value); endmodule\n")
    return graph,path,data


def test_existing_structured_reader_preserves_graph_and_scope(tmp_path):
    graph,path,_=staged(tmp_path)
    actual=from_structured_yaml(path)
    assert actual.to_dict()==graph.to_dict()






@pytest.mark.parametrize('damage',['version','population'])
def test_invalid_explicit_graph_is_not_an_empty_success(tmp_path,damage):
    _,path,_=staged(tmp_path)
    import yaml
    doc=yaml.safe_load(path.read_text())
    if damage=='version':doc['version']=999
    else:doc['facts']={}
    path.write_text(yaml.safe_dump(doc))
    with pytest.raises((ValueError,TypeError)):
        from_structured_yaml(path)

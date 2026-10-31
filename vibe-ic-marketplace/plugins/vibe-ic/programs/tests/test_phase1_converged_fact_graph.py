"""Converged graph uses the existing native renderer, preserving its namespace."""
import json
from pathlib import Path
import sys
import pytest
PLUGIN=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PLUGIN));sys.path.insert(0,str(PLUGIN/'programs'))
from tools.phase1_engine.schema import FactGraph
from tools.phase1_engine.ingest import from_structured_yaml
import phase1_one_shot_runner as runner


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


def test_converged_graph_precedes_stale_heuristic_input_cache(tmp_path):
    staged(tmp_path)
    cache=tmp_path/'phase1/input_doc';cache.mkdir(parents=True);(cache/'old.txt').write_text('older raw corpus')
    assert runner._detect_input_mode(tmp_path)=='prompt'


def test_actual_existing_publisher_keeps_complete_graph_namespace(tmp_path):
    graph,_,data=staged(tmp_path)
    before=(tmp_path/'input/phase1_structured.yaml').read_bytes()
    import _phase1_producer_identity as identity
    with identity.ProducerRecorder(root=PLUGIN) as recorder:
        result=runner.step_ingest_render(tmp_path,'neutral_top')
    assert result.status=='PASS',result.detail
    assert runner.step_human_docs(tmp_path).status == "PASS"
    assert (tmp_path/'input/phase1_structured.yaml').read_bytes()==before
    generated=tmp_path/'phase1/generated_docs'
    assert recorder.written_docs(tmp_path) == {p.name for p in generated.glob('L*.json')}
    for field in ('L9.top_ports','L9.parameters','L2.requirements','L6.submodule_control_logic','L21.retention','L22.test_cases'):
        layer,key=field.split('.',1)
        from tools.phase1_engine.schema import LAYER_FILE_NAMES
        doc=json.loads((generated/LAYER_FILE_NAMES[layer]).read_text())
        assert doc[key]==data[field]
    l6=json.loads((generated/'L6_CONTROL_LOGIC.json').read_text())
    assert not l6.get('fsm_states')
    assert not (tmp_path/'reports/audit/ai_judgements/D1.json').exists()


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


def test_normal_frontdoor_selects_native_graph_for_current_knobs(tmp_path):
    staged(tmp_path)
    import vibe_ic_one_shot_runner as front
    assert front._design_input_present(tmp_path) is True
    assert front._phase1_decision_from_inputs(tmp_path) == (True, "prompt")
    assert front._phase1_decision(tmp_path, False) == (True, "prompt")


def test_normal_regeneration_keeps_the_converged_input_mode(tmp_path,monkeypatch):
    staged(tmp_path)
    import vibe_ic_one_shot_runner as front
    generated=tmp_path/"phase1/generated_docs";generated.mkdir(parents=True)
    for i in range(1,14):(generated/("L"+str(i)+"_OLD.json")).write_text("{}")
    monkeypatch.setattr(front,"_phase1_checkpoint_freshness",lambda *a,**k:{"state":"REGENERATE","reason":"KNOBS_CHANGED"})
    assert front._phase1_decision(tmp_path,False,{"mode":"prompt"},checkpoint=True)==(True,"prompt")


def test_native_graph_checkpoint_does_not_need_unselected_legacy_layers(tmp_path,monkeypatch):
    staged(tmp_path)
    import vibe_ic_one_shot_runner as front
    generated=tmp_path/"phase1/generated_docs";generated.mkdir(parents=True)
    (generated/"L9_INTEGRATION_SPEC.json").write_text("{}")
    monkeypatch.setattr(front,"_phase1_checkpoint_freshness",lambda *a,**k:{"state":"REUSE"})
    assert front._phase1_decision(tmp_path,False,checkpoint=True)==(False,"")


def test_native_graph_uses_existing_expert_second_pass_without_regeneration(tmp_path,monkeypatch):
    staged(tmp_path)
    import vibe_ic_one_shot_runner as front
    generated=tmp_path/"phase1/generated_docs";generated.mkdir(parents=True)
    (generated/"L9_INTEGRATION_SPEC.json").write_text("{}")
    report=tmp_path/"reports/orchestrator/phase1_one_shot.json";report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"mode":"prompt","pass1":{"verdict":"PASS","rc":0}}))
    monkeypatch.setattr(front,"_expert_answer_pending",lambda p:(True,"delivered answer"))
    assert front._phase1_decision(tmp_path,False,checkpoint=True)==(True,front._P1_MODE_EXPERT_SECOND_PASS)

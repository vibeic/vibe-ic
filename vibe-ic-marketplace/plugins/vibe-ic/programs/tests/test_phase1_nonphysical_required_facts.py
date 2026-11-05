"""The common template retains all required functional and physical facts."""
from pathlib import Path
import sys

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN))
from tools.phase1_engine.schema import FactGraph
from tools.phase1_engine import gap_detect as gaps
from tools.phase1_engine.render import compute_required_facts_coverage, enforce_required_facts_threshold, InsufficientRequiredFactsError

OMITTED = {'L1.part_number','L1.package','L1.pinout','L1.pin_count','L1.electrical_characteristics',
           'L5.pads','L7.test_modes','L8.reset_timing.por_to_first_wake_ready_us','L8R.clock_frequency_hz'}


def graph(physical_facts=False):
    result=FactGraph('neutral','any-ic')
    required=gaps._aggregate_required_facts(['any-ic'],gaps.DEFAULT_CLASS_KB/'templates')
    for layer,entries in required.items():
        for entry in entries:
            path=layer+'.'+entry['path']
            if entry.get('required') and (physical_facts or path not in OMITTED):
                result.add_fact(path,'source-supported fact',[layer],'user_stated',origin='input/design.md:1')
    for kind in ('clock','reset'):
        result.add_fact('L9.'+kind+'_ports',[],['L9'],'derived',origin='input/rtl/neutral.sv:1-2; full source interface')
    return result






def test_omitted_selection_retains_full_requirements():
    g=graph();g.metadata={}
    assert compute_required_facts_coverage(g)['pct']==15/24






def test_required_functional_and_power_intent_demands_are_retained(tmp_path):
    g=graph(physical_facts=True);g.facts.remove(g.by_path('L2.requirements'))
    root=tmp_path/'kb';(root/'templates').mkdir(parents=True)
    for filename in ('class-tree.yaml',):
        (root/filename).write_bytes((gaps.DEFAULT_CLASS_KB/filename).read_bytes())
    body=(gaps.DEFAULT_CLASS_KB/'templates/any-ic.yaml').read_text()
    body+='\n  L21:\n    - {path: retention, type: dict, required: true}\n'
    (root/'templates/any-ic.yaml').write_text(body)
    coverage=compute_required_facts_coverage(g,class_kb_root=root)
    assert coverage['missing_by_layer']=={'L2':['requirements'],'L21':['retention']}
    assert coverage['pct']<1.0

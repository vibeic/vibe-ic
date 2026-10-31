"""Real common template: explicit nonphysical scope, with physical requirements preserved."""
from pathlib import Path
import copy
import json
import sys
import pytest

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN))
from tools.phase1_engine.schema import FactGraph
from tools.phase1_engine import gap_detect as gaps
from tools.phase1_engine.render import compute_required_facts_coverage, enforce_required_facts_threshold, InsufficientRequiredFactsError

REGISTRY = json.loads((PLUGIN/'flow/flow109.json').read_text())
PHYSICAL = [r for r in REGISTRY['reference_profiles'] if r['features']['physical']]
OMITTED = {'L1.part_number','L1.package','L1.pinout','L1.pin_count','L1.electrical_characteristics',
           'L5.pads','L7.test_modes','L8.reset_timing.por_to_first_wake_ready_us','L8R.clock_frequency_hz'}


def graph():
    result=FactGraph('neutral','any-ic')
    required=gaps._aggregate_required_facts(['any-ic'],gaps.DEFAULT_CLASS_KB/'templates')
    for layer,entries in required.items():
        for entry in entries:
            path=layer+'.'+entry['path']
            if entry.get('required') and path not in OMITTED:
                result.add_fact(path,'source-supported fact',[layer],'user_stated',origin='input/design.md:1')
    for kind in ('clock','reset'):
        result.add_fact('L9.'+kind+'_ports',[],['L9'],'derived',origin='input/rtl/neutral.sv:1-2; full source interface')
    features=copy.deepcopy(next(r['features'] for r in REGISTRY['reference_profiles'] if r['features']['rtl_only']))
    features['has_power_intent']=True
    result.metadata['flow109_manifest']={'features':features}
    return result


def test_actual_common_template_nonphysical_required_population():
    g=graph();coverage=enforce_required_facts_threshold(g,threshold=1.0)
    assert coverage['pct']==1.0
    assert coverage['total']==coverage['satisfied']==15
    assert coverage['missing_by_layer']=={}
    assert {r['path'] for r in coverage['inapplicable_required_facts']}==OMITTED
    assert not [r for r in gaps.detect_gaps(g) if r.kind=='missing_required']


@pytest.mark.parametrize('profile',PHYSICAL,ids=lambda p:p['name'])
def test_every_existing_physical_profile_retains_full_common_requirements(profile):
    g=graph();g.metadata['flow109_manifest']={'features':profile['features']}
    coverage=compute_required_facts_coverage(g)
    missing={layer+'.'+path for layer,paths in coverage['missing_by_layer'].items() for path in paths}
    assert missing==OMITTED
    assert coverage['total']==24 and coverage['satisfied']==15
    with pytest.raises(InsufficientRequiredFactsError):enforce_required_facts_threshold(g,threshold=1.0)


def test_omitted_selection_retains_full_requirements():
    g=graph();g.metadata={}
    assert compute_required_facts_coverage(g)['pct']==15/24


@pytest.mark.parametrize('damage',['missing','uncited','nonempty','wrong_type'])
def test_absence_must_be_explicit_and_source_cited(damage):
    g=graph()
    for kind in ('clock','reset'):
        fact=g.by_path('L9.'+kind+'_ports')
        if damage=='missing':g.facts.remove(fact)
        elif damage=='uncited':fact.provenance.origin=''
        elif damage=='nonempty':fact.value=[{'name':'signal'}]
        else:fact.value={}
    coverage=compute_required_facts_coverage(g)
    assert coverage['missing_by_layer']=={'L8':['reset_timing.por_to_first_wake_ready_us'],'L8R':['clock_frequency_hz']}


@pytest.mark.parametrize('selection',[{}, {'features':{'physical':False}}, 'rtl-only'])
def test_invalid_explicit_selection_blocks_instead_of_coverage_fallback(selection):
    g=graph();g.metadata['flow109_manifest']=selection
    with pytest.raises(ValueError,match='D01_APPLICABILITY_INVALID'):
        compute_required_facts_coverage(g)


def test_required_functional_and_power_intent_demands_are_retained(tmp_path):
    g=graph();g.facts.remove(g.by_path('L2.requirements'))
    root=tmp_path/'kb';(root/'templates').mkdir(parents=True)
    for filename in ('class-tree.yaml',):
        (root/filename).write_bytes((gaps.DEFAULT_CLASS_KB/filename).read_bytes())
    body=(gaps.DEFAULT_CLASS_KB/'templates/any-ic.yaml').read_text()
    body+='\n  L21:\n    - {path: retention, type: dict, required: true}\n'
    (root/'templates/any-ic.yaml').write_text(body)
    coverage=compute_required_facts_coverage(g,class_kb_root=root)
    assert coverage['missing_by_layer']=={'L2':['requirements'],'L21':['retention']}
    assert coverage['pct']<1.0

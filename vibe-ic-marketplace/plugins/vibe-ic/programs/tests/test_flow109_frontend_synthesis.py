"""D22 actual Default owner controls; test references are not PDK qualification."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import pytest
import flow109
import flow109_frontend as frontend
import flow109_admission as admission


def put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return {'path': str(path.relative_to(project)), 'sha256': frontend._sha(path)}


def d05_case(project):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    features = dict(features, has_power_intent=True)
    context = flow109.execution_context(flow109.resolve_plan(features), 'D05', 'D05')
    manifest = {
        'schema': frontend.D05_SCHEMA, 'top': 'neutral_top',
        'upf': put(project, 'input/power/neutral.upf',
                   'create_power_domain PD_TOP -elements {.}\n'
                   'set_isolation ISO -domain PD_TOP -clamp_value 0\n'),
        'rtl': [put(project, 'input/rtl/neutral.v',
                    'module neutral_top(input a,output y);assign y=a;endmodule\n')],
        'liberty': put(project, 'input/pdk/neutral.lib', 'library(neutral) {}\n'),
        'lefs': [put(project, 'input/pdk/neutral.lef',
                     'VERSION 5.8 ;\nSITE neutral_site\n  CLASS CORE ;\n'
                     '  SIZE 1 BY 1 ;\nEND neutral_site\nEND LIBRARY\n')],
        'evaluation': {'site': 'neutral_site', 'die_area': [0, 0, 100, 100],
                       'core_area': [10, 10, 90, 90], 'domain_areas': {}},
    }
    put(project, frontend.D05_INPUT, manifest)
    return context, features


def d05_launch(monkeypatch, *, returncode=0, marker=True, population=True):
    from types import SimpleNamespace
    monkeypatch.setattr(frontend.shutil, 'which', lambda name: '/usr/bin/openroad')
    lines = []
    if marker:
        lines.append('FLOW109_D05_EVALUATE_UPF=PASS')
    lines += [
        'FLOW109_D05_DOMAINS=PD_TOP' if population else 'FLOW109_D05_DOMAINS=',
        'FLOW109_D05_POWER_SWITCHES=',
        'FLOW109_D05_ISOLATIONS=ISO' if population else 'FLOW109_D05_ISOLATIONS=',
        'FLOW109_D05_LEVEL_SHIFTERS=',
    ]
    def run(args, **kwargs):
        attempt = Path(args[-1]).parent
        if returncode == 0:
            (attempt / 'roundtrip.upf').write_text(
                'create_power_domain PD_TOP -elements {.}\n')
        return SimpleNamespace(returncode=returncode, stdout='\n'.join(lines),
                               stderr='native refusal\n' if returncode else '')
    monkeypatch.setattr(frontend.subprocess, 'run', run)


def test_d05_structural_native_pass_keeps_all_three_row_metrics_not_measured(
        tmp_path, monkeypatch):
    context, _ = d05_case(tmp_path)
    d05_launch(monkeypatch)

    result = frontend.execute(tmp_path, context)

    assert result['native_started'] is True
    assert result['component_status'] == 'PASS'
    assert result['default_row_status'] == result['flow109_acceptance'] == 'NOT_MEASURED'
    assert result['completed'] is False
    assert result['metrics']['native_structure']['status'] == 'PASS'
    for metric in ('semantic_demand_coverage', 'illegal_power_states',
                   'supply_cell_assignments'):
        assert result['metrics'][metric] == {
            'status': 'NOT_MEASURED',
            'reason': 'D05_NATIVE_STATE_AND_SUPPLY_ANALYSIS_UNAVAILABLE'}
    receipt = tmp_path / result['receipt']['path']
    assert frontend._sha(receipt) == result['receipt']['sha256']


def test_d05_native_semantic_refusal_is_canonical_row_failure(tmp_path, monkeypatch):
    context, _ = d05_case(tmp_path)
    d05_launch(monkeypatch, returncode=1)

    result = frontend.execute(tmp_path, context)

    assert result['native_started'] is True
    assert result['native_receipt']['returncode'] == 1
    assert result['component_status'] == result['default_row_status'] == 'FAIL'
    assert result['reason'] == 'D05_OPENROAD_READ_OR_EVALUATE_UPF_FAILED'


def test_d05_rc0_empty_semantic_population_cannot_be_measured_zero(tmp_path, monkeypatch):
    context, _ = d05_case(tmp_path)
    d05_launch(monkeypatch, population=False)

    result = frontend.execute(tmp_path, context)

    assert result['native_started'] is True
    assert result['component_status'] == result['default_row_status'] == 'FAIL'
    assert result['reason'] == 'D05_NATIVE_SEMANTIC_POPULATION_MISSING'


@pytest.mark.parametrize('damage,reason', [
    ('missing', 'D05_INPUT_INVALID'),
    ('stale', 'D05_INPUT_STALE'),
    ('foreign', 'D05_INPUT_OUTSIDE_PROJECT'),
])
def test_d05_missing_stale_or_foreign_input_refuses_before_native(
        tmp_path, monkeypatch, damage, reason):
    context, _ = d05_case(tmp_path)
    manifest_path = tmp_path / frontend.D05_INPUT
    manifest = json.loads(manifest_path.read_text())
    if damage == 'missing':
        manifest_path.unlink()
    elif damage == 'stale':
        manifest['upf']['sha256'] = 'f' * 64
        manifest_path.write_text(json.dumps(manifest))
    else:
        outside = tmp_path.parent / 'foreign-d05.upf'
        outside.write_text('create_power_domain FOREIGN -elements {.}\n')
        manifest['upf'] = {'path': str(outside), 'sha256': frontend._sha(outside)}
        manifest_path.write_text(json.dumps(manifest))
    calls = []
    monkeypatch.setattr(frontend.subprocess, 'run', lambda *a, **k: calls.append(a))

    result = frontend.execute(tmp_path, context)

    assert result['component_status'] == result['default_row_status'] == 'NOT_MEASURED'
    assert result['native_started'] is False
    assert result['reason'] == reason
    assert calls == []


def test_d05_canonical_front_door_publishes_not_measured_not_component_pass(
        tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, 'ic') is None
    _, features = d05_case(tmp_path)
    d05_launch(monkeypatch)
    selection = tmp_path / 'flow109-selection.json'
    selection.write_text(json.dumps({'features': features}))
    args = SimpleNamespace(flow='109', flow109_manifest=selection,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D05', exit_step='D05', container=None)

    assert flow109.prepare_front_door(args, tmp_path) == 2

    row = json.loads((tmp_path / 'reports/flow109/default_rows/D05.json').read_text())
    assert row['component_status'] == 'PASS'
    assert row['default_row_status'] == row['flow109_acceptance'] == 'NOT_MEASURED'
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['completed'] is False


@pytest.fixture(autouse=True)
def actual_attested_image_route(monkeypatch, request):
    # D05 unit controls mock the native boundary; the separate bounded actual
    # consumer run carries its own CID/image identity.
    if request.node.name.startswith('test_d05_'):
        return
    import librelane_contract
    # Tests execute inside the pinned, host-attested image. Do not attach
    # an unrelated ambient container merely because Docker is reachable.
    librelane_contract.local_image_attestation()
    monkeypatch.setattr(librelane_contract._ce, "no_container_route", lambda: True)


def publish_d09(project, intent):
    import spec_declaration_emit as declaration
    docs = project / 'input/docs'
    docs.mkdir(parents=True, exist_ok=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/declaration.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    assert declaration.main(
        [str(project), '--set', 'dft=' + json.dumps(intent)]) == 0


def case(project):
    import fnmatch
    from librelane.config import Config
    from librelane.steps.yosys import EQY
    cfg, _ = Config.load({'PDK':'gf180mcuD','STD_CELL_LIBRARY':'gf180mcu_fd_sc_mcu7t5v0',
        'DESIGN_NAME':'unit_alpha','VERILOG_FILES':[]}, EQY.get_all_config_variables(),
        design_dir=str(project),pdk_root='/foss/pdks')
    libs = [p for pattern,group in cfg['CELL_LIBS'].items()
            if fnmatch.fnmatch(cfg['DEFAULT_CORNER'],pattern) for p in group]
    assert len(libs)==1
    lib=Path(libs[0]);deck={'path':str(lib),'sha256':frontend._sha(lib)}
    put(project,'input/project.json',{'pdk':'gf180mcuD'})
    put(project,'input/submission_template/tapeout_declaration.json',
        {'answers':{'deliverable':'DIE','top_cell':'unit_alpha','fp_sizing':'absolute',
                    'die_area_um':[0,0,100,100],'core_area_um':[10,10,90,90]},
         'answer_provenance':{'deliverable':{'answered_by':'owner','citation':'Developer neutral IC control'}}})
    put(project,'phase1/generated_docs/L8_TIMING_WAVEFORM.json',{'clock_domains':[{'role':'primary','source_pin':'clk','period_ns':20}]})
    publish_d09(project, {'scan_test': False})
    put(project,'phase1/generated_docs/L9_INTEGRATION_SPEC.json',{'top_module':'unit_alpha','synth_top':'unit_alpha'})
    put(project,'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',{'pdk':'gf180mcuD','constraint_declarations':[],'fields':{'die_area_budget_um':'100x100'}})
    put(project,'phase2/stage1/rtl/unit_alpha.v','module unit_alpha(input clk, input a,b, output reg y); always @(posedge clk) y <= a ^ b; endmodule\n')
    put(project,'phase3/librelane_switch.json',{'steps':{'9':'librelane'},'pdk_root':'/foss/pdks'})
    put(project,frontend.INPUT,{'schema':frontend.SCHEMA,'pdk':'gf180mcuD','top':'unit_alpha'})
    operation=put(project,'input/d22-operation.json',{'schema':frontend.SCHEMA,'operation':'Default.NativeMappedSynthesis','pdk':'gf180mcuD','top':'unit_alpha'})
    pdk=put(project,'input/d22-pdk.json',{'pdk':'gf180mcuD','root':'/foss/pdks','liberty':deck})
    reference=put(project,'input/control-reference.json',{'scope':'developer contract control only; not production qualification'})
    features=next(p['features'] for p in flow109.load_registry()['reference_profiles'] if p['name']=='Small digital IC without DFT')
    plan=flow109.resolve_plan(features);uses=[];records=[]
    sources=frontend.operation_sources()
    for use in flow109.resolve_step(plan,'D22')['tool_uses']:
        binary=Path(shutil.which(use['executable_name'])).resolve()
        executable={'path':str(binary),'sha256':frontend._sha(binary)}
        identity={'use_id':use['use_id'],'tool_id':use['tool_id'],'version':'developer control',
            'build_sha256':executable['sha256'],'executable':executable,'config':operation,'pdk':pdk,'deck':deck,
            'corner':cfg['DEFAULT_CORNER'],'semantics':{'purpose':use['purpose'],'native_steps':use['native_steps'],'operation_sources':sources}}
        record={'use_id':use['use_id'],'status':'QUALIFIED','identity':identity,'reference_evidence':[reference]}
        records.append(record);uses.append({**identity,'qualification_sha256':admission.canonical_sha(record)})
    put(project,'qualifications.json',{'schema':'vibeic.flow109.qualifications.v1','uses':records})
    context=flow109.execution_context(plan,'D22','D22',runtime_tool_uses=uses,qualification_registry='qualifications.json')
    put(project,'manifest.json',{'features':features,'runtime_tool_uses':uses,'qualification_registry':'qualifications.json'})
    request=project/'reports/flow109/requests/context.json';request.parent.mkdir(parents=True);request.write_text(json.dumps(context))
    return context,request


def test_actual_default_synthesis_uses_native_librelane_and_complete_existing_consumer(tmp_path,monkeypatch):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    driver = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import librelane_contract as contract
contract.local_image_attestation()
# Explicit test route: real native tools in this inspected current image.
contract._ce.no_container_route=lambda: True
import vibe_ic_one_shot_runner as runner
sys.argv=['vibe_ic_one_shot_runner.py',sys.argv[2],'--flow','109','--flow109-manifest',str(Path(sys.argv[2])/'manifest.json'),'--entry-step','D22','--exit-step','D22','--route','ic','--no-dashboard']
raise SystemExit(runner._main())
'''
    launched=subprocess.run([sys.executable,'-c',driver,str(frontend.HERE),str(tmp_path)],capture_output=True,text=True)
    component = tmp_path/'reports/flow109/components/D22.json'
    assert launched.returncode==0,(launched.stdout+launched.stderr+
        ('\nD22_COMPONENT '+component.read_text() if component.is_file() else ''))
    result=json.loads((tmp_path/'reports/flow109/components/D22.json').read_text())
    if os.environ.get('VIBEIC_FLOW109_EVIDENCE_DIR'):
        target=Path(os.environ['VIBEIC_FLOW109_EVIDENCE_DIR'])/'native-positive'
        shutil.copytree(tmp_path,target)
    print('D22_NATIVE_RESULT', json.dumps({k:result.get(k) for k in ('component_status','reason','producer','native_operations','native_receipt','detail')}, default=str))
    assert result['native_started'], result
    assert 'Yosys.Synthesis' in result['native_operations']
    receipt=tmp_path/result['native_receipt']['path']
    assert frontend._sha(receipt)==result['native_receipt']['sha256']
    native_binding=json.loads(receipt.read_text())['input']['flow109_synthesis']
    assert native_binding['context_sha256']==result['context_sha256']
    assert len(native_binding['qualification_uses'])==3
    assert result['flow109_acceptance']=='PASS'
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert result['producer']['status']=='PASS',result
    assert result['canonical_current_pass'],result
    assert result['canonical_publication']['status']=='PASS',result
    assert result['canonical_publication']['canonical_consumer']['status']=='PASS',result
    assert result['component_status']=='PASS',result


def test_actual_default_none_path_reaches_complete_existing_consumer(tmp_path, monkeypatch):
    context, path = case(tmp_path)
    plan = flow109.resolve_plan(context['features'])
    context = flow109.execution_context(plan, 'D22', 'D22')
    path.write_text(json.dumps(context))
    (tmp_path / 'manifest.json').write_text(json.dumps({'features': context['features']}))
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(path))
    driver = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import librelane_contract as contract
contract.local_image_attestation()
contract._ce.no_container_route=lambda: True
import vibe_ic_one_shot_runner as runner
sys.argv=['vibe_ic_one_shot_runner.py',sys.argv[2],'--flow','109','--flow109-manifest',str(Path(sys.argv[2])/'manifest.json'),'--entry-step','D22','--exit-step','D22','--route','ic','--no-dashboard']
raise SystemExit(runner._main())
'''
    launched = subprocess.run([sys.executable, '-c', driver, str(frontend.HERE),
                               str(tmp_path)], capture_output=True, text=True)
    component = tmp_path / 'reports/flow109/components/D22.json'
    assert launched.returncode == 0, (launched.stdout + launched.stderr +
        ('\nD22_COMPONENT ' + component.read_text() if component.is_file() else ''))
    result = json.loads((tmp_path / 'reports/flow109/components/D22.json').read_text())
    assert context['runtime_tool_uses'] is None
    assert result['native_started'] is True
    assert result['producer']['status'] == 'PASS'
    assert result['canonical_publication']['status'] == 'PASS'
    assert result['canonical_publication']['canonical_consumer']['status'] == 'PASS'
    assert result['canonical_current_pass']['folder'] == result['canonical_publication']['folder']
    assert result['component_status'] == 'PASS'


@pytest.mark.parametrize('damage',['unsupported','source','deck','declaration'])
def test_missing_or_changed_qualification_stops_before_existing_owner(tmp_path,monkeypatch,damage):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    if damage=='declaration': (tmp_path/'input/submission_template/tapeout_declaration.json').unlink()
    elif damage=='source': monkeypatch.setattr(frontend,'operation_sources',lambda:{'changed':'source'})
    elif damage=='deck': context['runtime_tool_uses'][0]['deck']['sha256']='f'*64
    else:
        file=tmp_path/'qualifications.json';x=json.loads(file.read_text());x['uses'][0]['status']='UNSUPPORTED';file.write_text(json.dumps(x))
    calls=[]
    import step_preflight
    monkeypatch.setattr(step_preflight,'retained_call',lambda *a,**k:calls.append('owner'))
    result=frontend.execute(tmp_path,context)
    assert result['component_status']=='NOT_MEASURED' and not result['native_started'],result
    assert calls==[]


@pytest.mark.parametrize('damage', ['missing', 'empty'])
def test_missing_d09_dft_intent_stops_before_existing_owner(tmp_path, monkeypatch, damage):
    context, path = case(tmp_path)
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(path))
    intent = tmp_path / 'plugin_output/declaration.json'
    if damage == 'missing':
        (tmp_path / 'input/docs/L7_verification_plan.md').unlink()
        intent.unlink()
        intent.with_name('declaration.provenance.json').unlink()
        (tmp_path / 'provenance.jsonl').unlink()
    else:
        body = json.loads(intent.read_text()); body['dft'].pop('scan_test')
        intent.write_text(json.dumps(body))
    calls = []
    import step_preflight
    monkeypatch.setattr(step_preflight, 'retained_call', lambda *a, **k: calls.append('owner'))

    result = frontend.execute(tmp_path, context)

    assert result['reason'] in {'D09_DFT_SPEC_MISSING', 'D09_DFT_AUTHORITY_INVALID'}
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['native_started'] is False
    assert calls == []


def test_native_contract_launch_rechecks_original_input_census(tmp_path,monkeypatch):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    prepared=frontend.prepare(tmp_path,context)
    active={'project':tmp_path.resolve(),'context':context,'prepared':prepared,'operations':[]}
    token=frontend._ACTIVE.set(active)
    try:
        source=tmp_path/'phase2/stage1/rtl/unit_alpha.v';source.write_text(source.read_text()+'\n// changed\n')
        with pytest.raises(admission.AdmissionRefusal,match='D22_INPUT_CHANGED'):
            frontend.require_librelane_launch(tmp_path,'Yosys.Synthesis')
        assert active['operations']==[]
    finally:frontend._ACTIVE.reset(token)


def test_native_synthesis_does_not_promote_missing_area_authority(tmp_path,monkeypatch):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    spec=tmp_path/'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    value=json.loads(spec.read_text());value['fields']={};spec.write_text(json.dumps(value))
    result=frontend.execute(tmp_path,context)
    assert result['native_started'],result
    assert result['producer']['status']=='NOT_MEASURED',result
    assert result['component_status']=='NOT_MEASURED',result
    assert result['canonical_current_pass'] is None


def test_actual_native_contract_refuses_qualification_drift_after_owner_preparation(tmp_path,monkeypatch):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    import librelane_contract as contract
    original=contract.resolve_step_config
    seen=[]
    def invalidate_at_native_boundary(*args,**kwargs):
        file=tmp_path/'qualifications.json';record=json.loads(file.read_text())
        record['uses'][0]['status']='UNSUPPORTED';file.write_text(json.dumps(record))
        seen.append('boundary')
        return original(*args,**kwargs)
    monkeypatch.setattr(contract,'resolve_step_config',invalidate_at_native_boundary)
    result=frontend.execute(tmp_path,context)
    assert seen==['boundary']
    assert result['component_status']!='PASS'
    assert result['native_started'] is False,result
    assert result['native_operations']==[]
    assert not (tmp_path/'phase3/librelane/02-yosys-synthesis/state_out.json').exists()


@pytest.mark.parametrize('external', ['`include "outside.vh"', 'initial $readmemh("outside.hex", mem);'])
def test_external_rtl_file_consumption_refuses_before_existing_owner(tmp_path,monkeypatch,external):
    context,path=case(tmp_path);monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(path))
    source=tmp_path/'phase2/stage1/rtl/unit_alpha.v'
    source.write_text(external+'\n'+source.read_text())
    import step_preflight
    calls=[];monkeypatch.setattr(step_preflight,'retained_call',lambda *a,**k:calls.append('owner'))
    result=frontend.execute(tmp_path,context)
    assert result['reason']=='D22_TRANSITIVE_INPUT_UNIMPLEMENTED'
    assert result['native_started'] is False and calls==[]


def engineering_case(project, monkeypatch):
    """Ordinary source-owned entry, without a tool-qualification claim."""
    from types import SimpleNamespace
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D22', 'D22')
    put(project, frontend.INPUT, {'schema': frontend.SCHEMA, 'top': 'unit_alpha', 'pdk': 'unit_pdk'})
    put(project, 'phase2/stage1/rtl/unit_alpha.v', 'module unit_alpha(input a,output y);assign y=a;endmodule')
    put(project, 'phase3/librelane_switch.json', {'steps': {'9': 'librelane'}})
    lib = project / 'unit.lib'; lib.write_text('library(unit) {}')
    import design_one_shot_runner as runner
    monkeypatch.setattr(runner, '_phase2_pdk_config', lambda *a: SimpleNamespace(liberty=lib))
    monkeypatch.setattr(frontend, 'operation_sources', lambda: {'native-source': 'current'})
    path = project / 'context.json'; path.write_text(json.dumps(context))
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(path))
    return context


def test_default_synthesis_uses_registered_owner_without_qualification_claim(tmp_path, monkeypatch):
    context = engineering_case(tmp_path, monkeypatch)
    assert flow109.source_owned_native_admission(context)['admitted'] is True
    assert frontend.prepare(tmp_path, context)['manifest']['top'] == 'unit_alpha'
    # Explicit unsupported qualification is never rescued by Default admission.
    claimed = copy.deepcopy(context); claimed['runtime_tool_uses'] = []
    assert flow109.source_owned_native_admission(claimed) is None


@pytest.mark.parametrize('status,complete,expected', [('PASS', True, 'NOT_MEASURED'),
                                                      ('PASS', False, 'NOT_MEASURED'),
                                                      ('FAIL', False, 'FAIL'),
                                                      ('NOT_MEASURED', False, 'NOT_MEASURED')])
def test_producer_completion_cannot_replace_canonical_publication(tmp_path, monkeypatch, status, complete, expected):
    context = engineering_case(tmp_path, monkeypatch)
    import step_preflight, step_output_collector, design_one_shot_runner as runner
    def result(*args, **kwargs):
        return runner.StepResult('yosys_synth', status, 0.0, 'controlled native disposition',
            extras={'step_id':'9', 'completed':complete,
                    'default_row_status':'PASS' if complete else 'NOT_MEASURED'})
    monkeypatch.setattr(step_preflight, 'retained_call', result)
    monkeypatch.setattr(step_output_collector, 'latest_pass', lambda *a: None)
    result = frontend.execute(tmp_path, context)
    selected = flow109._selected_step_result(tmp_path, context, result, frontend)
    assert selected['default_row_status'] == expected
    assert selected['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert selected['delivery_accepted'] is False


def test_default_synthesis_missing_rtl_or_changed_input_stops_before_launch(tmp_path, monkeypatch):
    context = engineering_case(tmp_path, monkeypatch)
    prepared = frontend.prepare(tmp_path, context)
    source = tmp_path / 'phase2/stage1/rtl/unit_alpha.v'
    source.unlink()
    with pytest.raises(admission.AdmissionRefusal, match='D22_INPUT_CHANGED'):
        frontend._before(tmp_path, context, prepared)
    with pytest.raises(admission.AdmissionRefusal, match='D22_RTL_ABSENT'):
        frontend.prepare(tmp_path, context)


def test_synthesis_config_without_physical_declaration_keeps_physical_entry_strict(tmp_path, monkeypatch):
    import librelane_contract as contract
    put(tmp_path,'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains':[{'role':'primary','source_pin':'clk','period_ns':20}]})
    put(tmp_path,'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {})
    put(tmp_path,'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {})
    output = tmp_path / 'synth.json'
    result = contract.emit_config(tmp_path, 'unit_pdk', output, synthesis_only=True)
    assert result['CLOCK_PERIOD'] == 20
    assert 'DIE_AREA' not in result
    with pytest.raises(FileNotFoundError):
        contract.emit_config(tmp_path, 'unit_pdk', tmp_path / 'physical.json')


def test_default_synthesis_detects_changed_native_sdc(tmp_path, monkeypatch):
    context = engineering_case(tmp_path, monkeypatch)
    put(tmp_path, 'phase3/stage3/pnr/constraint.sdc', 'create_clock -period 20 [get_ports clk]')
    prepared = frontend.prepare(tmp_path, context)
    assert 'phase3/stage3/pnr/constraint.sdc' in prepared['inputs']
    put(tmp_path, 'phase3/stage3/pnr/constraint.sdc', 'create_clock -period 10 [get_ports clk]')
    with pytest.raises(admission.AdmissionRefusal, match='D22_INPUT_CHANGED'):
        frontend._before(tmp_path, context, prepared)


def controlled_canonical_publication(project, monkeypatch, consumer_status):
    """Use the real retained publication machinery with a controlled consumer."""
    context = engineering_case(project, monkeypatch)
    put(project, 'input/submission_template/tapeout_declaration.json',
        {'answers': {'deliverable': 'DIE'}})
    import design_one_shot_runner as runner
    import execution_backend_gates as gates
    import execution_policy
    calls = []
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)

    def producer(actual_project, *_args, **_kwargs):
        frontend.require_librelane_launch(actual_project, 'Yosys.Synthesis')
        put(actual_project, 'phase2/stage2/synth/netlist.v',
            'module unit_alpha(input a,output y);assign y=a;endmodule\n')
        put(actual_project, 'phase2/stage2/synth/stats.json', {'cells': 1})
        return runner.StepResult('yosys_synth', 'PASS', 0.0,
            'controlled successful native producer',
            extras={'step_id': '9', 'completed': True,
                    'default_row_status': 'PASS'})

    def consume(_project, row):
        calls.append(str(row['id']))
        return {'status': consumer_status,
                'step': {'id': row['id'], 'status': consumer_status,
                         'reasons': ['controlled canonical disposition']},
                'ledger': [{'gate': 'controlled_existing_consumer',
                            'rc': 0 if consumer_status == 'PASS' else 1,
                            'verdict': consumer_status}],
                'required_commands': []}

    producer.__name__ = 'step_yosys_synth'
    producer.__module__ = 'design_one_shot_runner'
    monkeypatch.setattr(runner, 'step_yosys_synth', producer)
    monkeypatch.setattr(gates, 'evaluate', consume)
    started = time.time()
    result = frontend.execute(project, context)
    return context, result, calls, started


@pytest.mark.parametrize('consumer_status', ['PASS', 'NOT_MEASURED', 'FAIL'])
def test_default_none_path_publishes_and_preserves_canonical_consumer_verdict(
        tmp_path, monkeypatch, consumer_status):
    import step_output_collector as versions
    context, result, calls, started = controlled_canonical_publication(
        tmp_path, monkeypatch, consumer_status)

    current = [row for row in versions.current_acceptance(tmp_path, started)
               if str(row['id']) == '9']
    assert calls == ['9']
    assert context['runtime_tool_uses'] is None
    assert len(current) == 1
    assert current[0]['status'] == consumer_status
    assert current[0]['result']['canonical_consumer']['status'] == consumer_status
    assert result['component_status'] == consumer_status
    assert result['default_row_status'] == consumer_status
    assert result['canonical_publication']['status'] == consumer_status
    assert bool(versions.latest_pass(tmp_path, '9')) is (consumer_status == 'PASS')


@pytest.mark.parametrize('damage', ['missing', 'foreign', 'stale', 'direct_flag'])
def test_canonical_publication_missing_foreign_stale_or_flag_only_refuses(
        tmp_path, monkeypatch, damage):
    import step_output_collector as versions
    _context, _result, _calls, started = controlled_canonical_publication(
        tmp_path, monkeypatch, 'PASS')
    current = next(row for row in versions.current_acceptance(tmp_path, started)
                   if str(row['id']) == '9')
    record = tmp_path / 'steps' / current['folder'] / 'outputs.json'
    if damage == 'missing':
        record.unlink()
    elif damage == 'foreign':
        body = json.loads(record.read_text()); body['id'] = '8'
        record.write_text(json.dumps(body))
    elif damage == 'direct_flag':
        body = json.loads(record.read_text())
        body['canonical_pass'] = True
        body['result'].pop('canonical_consumer')
        record.write_text(json.dumps(body))
    else:
        started = time.time() + 60

    with pytest.raises(admission.AdmissionRefusal,
                       match='D22_CANONICAL_PUBLICATION_(MISSING_OR_FOREIGN|INVALID|STALE)'):
        frontend._canonical_publication(tmp_path, started)

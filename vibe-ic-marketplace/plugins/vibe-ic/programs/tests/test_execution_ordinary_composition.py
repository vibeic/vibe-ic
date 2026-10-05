"""Bounded ordinary-caller checks against live canonical execution authority."""
import json
from pathlib import Path
import pytest
import execution_modes as em
import execution_policy as policy
from programs.tests import test_execution_receipt_chain as R
from programs.tests import test_execution_modes as H

isolated_transport=R.isolated_transport

@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    import os
    names = (policy.ENV, policy._CAPABILITY_FD_ENV, 'VIBEIC_EXECUTION_AUTH_SOCKET')
    before = {name: os.environ.get(name) for name in names}
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    yield
    # real_entry publishes transport locators directly; keep later unissued
    # caller controls independent of the live-entry fixture's closed FDs.
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_default_bootstrap_is_observationally_inert(tmp_path, monkeypatch):
    import execution_frontend_providers as frontend
    import execution_adapters_backend as backend
    import execution_adapters_release as release
    before=dict(__import__('os').environ)
    def trap(*args,**kwargs):
        raise AssertionError('Default constructed a provider registry')
    for module,name in ((frontend,'register_factories'),(backend,'register_backend_adapters'),(release,'register_release_adapters')):
        monkeypatch.setattr(module,name,trap)
    assert policy.bootstrap(tmp_path) is None
    assert policy.dispatch_fixed_step(tmp_path,'8') is None
    import phase3_one_shot_runner as phase3
    for name in ('prepnr', 'pnr', 'canonicalize_artefacts', 'digital_hardmacro_gen'):
        assert phase3._ordinary_phase3_row(tmp_path,name) is None
    assert policy._ordinary_runtime is None
    assert dict(__import__('os').environ)==before


def test_canonical_default_bootstrap_reaches_producer_receipt_and_consumer(
        tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    issued = R.real_entry('IC', 'default', project)
    constraints = project / 'phase2/stage2/constraints'
    constraints.mkdir(parents=True)
    (constraints / 'top.sdc').write_text(
        'create_clock -period 10 [get_ports clk]\n'
        'set_input_delay 1 -clock clk [all_inputs]\n'
        'set_output_delay 1 -clock clk [all_outputs]\n')
    (constraints / 'pvt_matrix.json').write_text('{"corners":[]}\n')
    l8 = project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json'
    l8.parent.mkdir(parents=True)
    l8.write_text('{"clocks":{"clk":{"period_ns":10}}}\n')

    runtime = policy.bootstrap(project, parameters={'skip_analog': True})
    assert runtime is not None
    assert runtime['policy']['mode_label'] == 'default-mode'
    import design_one_shot_runner as design
    consumed = design.step_sdc_validation(project)
    assert consumed.status == 'PASS', consumed
    result = consumed.extras['execution_result']
    assert result['status'] == 'ADOPTED', result
    run = Path(result['run_root'])
    receipt = json.loads((run / 'frontend_8/receipt.json').read_text())
    assert receipt['status'] == 'ELIGIBLE'
    assert any(item['component'] == 'frontend_worker'
               for item in receipt['processes'])
    assert json.loads((run / 'adoption.json').read_text())['status'] == 'ADOPTED'
    assert (project / 'reports/phase2/sdc_check.json').is_file()


def test_ordinary_ultra_reuses_controller_and_refuses_unmeasured_selection(tmp_path):
    project=tmp_path/'project';project.mkdir()
    issued=R.real_entry('IC','ultra',project)
    runtime=policy.bootstrap(project,parameters={
        'top':'chip_top','design_name':'chip_top','skip_analog':True})
    assert policy.bootstrap(project) is runtime
    assert type(runtime['controller']) is em.Controller
    assert type(runtime['registry']) is em.Registry
    assert runtime['controller'].registry is runtime['registry']
    # Canonical direct gates bind the same portfolio as all_of gates. A stale
    # omission must refuse before a fixed row can construct its Context.
    stale=json.loads(json.dumps(runtime['controller'].portfolio))
    row=next(row for row in stale['steps'] if str(row['id'])=='16')
    assert 'clock_plan_check' in row['mandatory_gate_programs']
    row['mandatory_gate_programs'].remove('clock_plan_check')
    with pytest.raises(em.Refusal,match='PORTFOLIO_GATES_STALE: 16'):
        em._validate_portfolio(stale)
    for step in ('0.5ic','8','16','36','37.5ip'):
        assert runtime['registry'].adapters(step),step
    skipped=policy.dispatch_fixed_step(project,'37.5ip')
    assert skipped['status']=='NOT_APPLICABLE',skipped
    assert '37.5ip' not in runtime['runs']
    # A selected ordinary Phase3 row has no design inputs here. It must run
    # only the fixed row's registered producer and retain honest absence.
    backend=policy.dispatch_fixed_step(project,'16')
    assert backend['step_id']=='16' and backend['status']=='NOT_MEASURED',backend
    root,result=runtime['runs']['16']
    plan=json.loads((root/'plan.json').read_text())
    assert plan['binding']['step_id']=='16'
    assert plan['binding']['route_receipt']==issued['route']
    assert set(result['candidate_statuses'])==set(plan['arms'])
    assert all(value!='ELIGIBLE' for value in result['candidate_statuses'].values())
    again=policy.dispatch_fixed_step(project,'16')
    assert again['run_root']==backend['run_root']
    for arm in plan['arms']:
        receipt=json.loads((root/arm/'receipt.json').read_text())
        assert len(receipt['processes'])<=1
        if receipt['processes']:
            adapter=next(a for a in runtime['registry'].adapters('16') if a.arm_id==arm)
            assert receipt['processes'][0]['component']==adapter.components[0].name
            evidence=json.loads((root/arm/'outputs/release-evidence.json').read_text())
            assert evidence['missing_inputs']==['phase3/stage3/pnr/floorplan.def','phase2/stage2/constraints/*.sdc']
            assert evidence['producer_verdict']=='NOT_MEASURED'
            assert evidence['producer'][0]['program']=='phase3_one_shot_runner.emit_clock_plan'
            assert evidence['producer'][0]['rc']==2
            assert evidence['gate_records'][0]['reason']=='REQUIRED_INPUT_ABSENT'
            assert evidence['gate_records'][0]['rc'] is None
    ctx=runtime['contexts']['16']
    arm=plan['arms'][0]
    with pytest.raises(em.Refusal,match='AI_CHOICE_INELIGIBLE'):
        policy.dispatch_fixed_step(project,'16',choice=H.choice(ctx,root,arm))
    assert not (root/'selected').exists()
    import phase3_one_shot_runner as phase3
    # Existing ordinary-caller control also exercises the new fixed Step9
    # hook. Source registration must not imply native installation readiness.
    step9=phase3.step_synth(project,'chip_top',None,'no-container')
    result9=step9.extras['execution_result']
    assert step9.status=='NOT_MEASURED' and result9['step_id']=='9',result9
    assert runtime['registry'].adapters('9')
    assert all(not arm.available for arm in runtime['registry'].adapters('9'))
    assert not (project/'phase2/stage2/synth/netlist.v').exists()
    assert not (Path(result9['run_root'])/'selected').exists()
    # Missing current capability/share authority must not schedule Step30.
    arms30=runtime['registry'].adapters('30')
    assert arms30 and all(not arm.available for arm in arms30)
    assert all(arm.availability_reason=='STEP30_CAPABILITY_OR_LIVE_SHARE_UNAVAILABLE'
               for arm in arms30)
    row30=policy.dispatch_fixed_step(project,'30')
    assert row30['step_id']=='30' and row30['status']=='NOT_MEASURED',row30
    root30,_=runtime['runs']['30']
    assert not (root30/'selected').exists()
    release=phase3.step_digital_hardmacro_gen(project)
    assert release.extras['execution_results'][0]['step_id']=='37.5ip'
    assert release.extras['execution_results'][0]['status']=='NOT_APPLICABLE'
    assert '37.5ip' not in runtime['runs']


def test_ordinary_step8_uses_live_context_and_existing_selection(tmp_path):
    project=tmp_path/'project';project.mkdir()
    R.real_entry('IC','ultra',project)
    sdc=project/'phase2/stage2/constraints/top.sdc';sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -period 10 [get_ports clk]\nset_input_delay 1 -clock clk [all_inputs]\nset_output_delay 1 -clock clk [all_outputs]\n')
    sdc.with_name('pvt_matrix.json').write_text('{"corners":[]}\n')
    l8=project/'phase1/generated_docs/L8_TIMING_WAVEFORM.json';l8.parent.mkdir(parents=True)
    l8.write_text('{"clocks":{"clk":{"period_ns":10}}}\n')
    runtime=policy.bootstrap(project,parameters={'skip_analog':True})
    import design_one_shot_runner as design
    pending=design.step_sdc_validation(project)
    result=pending.extras['execution_result']
    assert result['status']=='AWAITING_AI_SELECTION',result
    root,_=runtime['runs']['8'];ctx=runtime['contexts']['8']
    plan=json.loads((root/'plan.json').read_text())
    assert plan['arms']==['frontend_8']
    receipt=json.loads((root/'frontend_8/receipt.json').read_text())
    assert receipt['status']=='ELIGIBLE',receipt
    assert [p['component'] for p in receipt['processes']]==['frontend_worker',*ctx.required_gates]
    choice=H.choice(ctx,root,'frontend_8')
    adopted=policy.dispatch_fixed_step(project,'8',choice=choice)
    assert adopted['status']=='ADOPTED',adopted
    assert (project/'reports/phase2/sdc_check.json').is_file()
    again=design.step_sdc_validation(project)
    assert again.status=='PASS'
    assert json.loads((root/'frontend_8/receipt.json').read_text())['processes']==receipt['processes']
    sdc.write_text(sdc.read_text()+'# changed caller input after issuance\n')
    with pytest.raises(policy.Refusal, match='FIXED_STEP_REENTRY_CHANGED'):
        design.step_sdc_validation(project)



def test_source_import_readers_share_exact_content_syntax(monkeypatch):
    import ast
    import execution_provider_catalog as catalog

    content = ("import syntax_count_peer\n"
               "try:\n    from . import optional_peer\n"
               "except ImportError:\n    import fallback_peer\n"
               "importlib.import_module('literal_peer')\n")
    changed = content.replace("literal_peer", "changed_peer")
    original = ast.parse
    parsed = []

    def count_parse(source, *args, **kwargs):
        if source in (content, changed):
            parsed.append(source)
        return original(source, *args, **kwargs)

    monkeypatch.setattr(ast, 'parse', count_parse)
    for reader in (em._python_import_requests, catalog._import_names,
                   catalog._python_import_specs):
        reader.cache_clear()
    assert (1, 'optional_peer') in em._python_import_requests(content)
    assert 'literal_peer' in catalog._import_names(content)
    assert ('', 1, ('optional_peer',), True) in catalog._python_import_specs(content)
    assert parsed == [content], 'one source must be parsed once across readers'

    assert 'changed_peer' in catalog._import_names(changed)
    assert ('changed_peer', 0, (), False) in catalog._python_import_specs(changed)
    em._python_import_requests(changed)
    assert parsed == [content, changed], 'changed bytes need a fresh syntax result'
    assert 'literal_peer' in catalog._import_names(content)
    assert 'changed_peer' not in catalog._import_names(content)


def test_import_syntax_cache_re_resolves_new_local_module(tmp_path):
    entry=tmp_path/'entry.py';entry.write_text('import bounded_source_helper\n')
    helper=tmp_path/'bounded_source_helper.py'
    assert em._local_python_imports(entry)==set()
    before=em._python_import_requests.cache_info().hits
    helper.write_text('')
    assert helper.resolve() in em._local_python_imports(entry)
    assert em._python_import_requests.cache_info().hits > before
    entry.write_text('import changed_source_helper\n')
    changed=tmp_path/'changed_source_helper.py';changed.write_text('')
    assert changed.resolve() in em._local_python_imports(entry)
    assert helper.resolve() not in em._local_python_imports(entry)


def test_long_typed_argv_remains_bound_as_data():
    import execution_backend_worker as worker
    component=em.Component('producer',(__import__('sys').executable,str(Path(worker.__file__).resolve()),
        '{inputs}','{outputs}','--params-json',json.dumps({'input_contract':['phase3/input/'+('x'*300)]})))
    invocation=em._invocation_sources(component)
    assert invocation['argv']==list(component.argv)
    assert str(Path(worker.__file__).resolve()) in invocation['implementation']


def test_relative_runtime_data_argument_is_independent_of_registration_cwd(tmp_path,
                                                                            monkeypatch):
    import sdc_validator_check as validator
    relative = 'phase1/generated_docs/L8_TIMING_WAVEFORM.json'
    component = em.Component('sdc-validator', (
        str(Path(__import__('sys').executable).resolve()),
        str(Path(validator.__file__).resolve()), '.', '--l8', relative,
        '--json', 'reports/sdc_validator.json'))
    empty = tmp_path / 'empty'; empty.mkdir()
    project = tmp_path / 'project'; (project / Path(relative).parent).mkdir(parents=True)
    (project / relative).write_text('{}\n')
    monkeypatch.chdir(empty)
    before = em._invocation_sources(component)
    monkeypatch.chdir(project)
    after = em._invocation_sources(component)
    assert after == before
    assert relative not in after['argument_sources']

    # An explicitly absolute static data argument remains part of the source
    # census, so this cwd fix does not loosen that authority boundary.
    absolute = str((project / relative).resolve())
    bound = em._invocation_sources(em.Component('sdc-validator', (
        *component.argv[:4], absolute, *component.argv[5:])))
    assert absolute in bound['argument_sources']


def test_producer_site_symbols_share_exact_content_and_reject_changes(tmp_path, monkeypatch):
    import ast
    import execution_adapters_backend as backend
    import execution_adapters_release as release
    source = tmp_path / 'producer.py'
    content = 'def produce():\n    pass\n'
    source.write_text(content)
    calls = []
    parse = ast.parse
    def counted(text, *args, **kwargs):
        if text == content:
            calls.append(text)
        return parse(text, *args, **kwargs)
    monkeypatch.setattr(ast, 'parse', counted)
    for module in (backend, release):
        monkeypatch.setattr(module, 'HERE', tmp_path)
        assert module._site_path('producer.py:produce') == source
        assert module._site_path('producer.py:produce') == source
    assert len(calls) == 1
    source.write_text('def replacement():\n    pass\n')
    for module in (backend, release):
        with pytest.raises(em.Refusal, match='PRODUCER_SYMBOL_MISSING'):
            module._site_path('producer.py:produce')
        assert module._site_path('producer.py:replacement') == source
    source.write_text('invalid syntax !')
    for module in (backend, release):
        with pytest.raises(em.Refusal, match='PRODUCER_SITE_UNREADABLE'):
            module._site_path('producer.py:replacement')


@pytest.mark.parametrize('skip_analog', [False, True])
def test_canonical_phase1_entry_defers_post_phase1_registration(tmp_path, monkeypatch,
                                                               skip_analog):
    import sys
    import phase1_one_shot_runner as phase1
    project = tmp_path / 'project'
    project.mkdir()
    R.real_entry('IC', 'default', project)
    declaration = project / 'phase1/analog/analog_block_list.json'
    assert not declaration.exists()
    reached = []
    class ReachedPhase1Producer(Exception):
        pass
    def stop_at_producer(current, **kwargs):
        runtime = policy._ordinary_runtime
        assert current == project
        assert runtime['parameters']['skip_analog'] is skip_analog
        assert runtime['registry'].adapters('0.5ic')
        assert not runtime['registry'].adapters('A1')
        assert not runtime['registry'].adapters('9')
        assert not declaration.exists()
        reached.append(True)
        raise ReachedPhase1Producer
    monkeypatch.setattr(phase1, '_run_step_0_5ic', stop_at_producer)
    argv = ['phase1_one_shot_runner.py', str(project), '--route', 'ic']
    if skip_analog:
        argv.append('--skip-analog')
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(ReachedPhase1Producer):
        phase1.main()
    assert reached == [True]
    assert not declaration.exists()


@pytest.mark.parametrize("damage", [None, "missing", "conflict"])
def test_issued_default_pdk_reaches_real_step9_registration(tmp_path, monkeypatch, damage):
    import execution_production as production
    import design_one_shot_runner as design
    from test_default_frontend_r2 import _synthesis
    project, _, pdk, native_calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    if damage == 'missing':
        (project / 'input/project.json').unlink()
        (project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').unlink()
    elif damage == 'conflict':
        (project / 'phase3').mkdir(parents=True, exist_ok=True)
        (project / 'phase3/librelane_switch.json').write_text('{"pdk":"otherPDK"}')
    R.real_entry('IC', 'default', project)
    measured = []
    def stop_native_probe(image, current):
        measured.append((image, current))
        return 'UNMEASURED:source-only-control', {}, ['SOURCE_ONLY_NATIVE_PROBE_STOP']
    monkeypatch.setattr(production, '_tool_and_image', stop_native_probe)
    class Registry:
        def __init__(self):
            self.arms = []
        def register(self, adapter):
            self.arms.append(adapter)
    registry = Registry()
    observed = {}
    class Execution:
        request = staticmethod(policy.request)
        @staticmethod
        def bootstrap(current, *, parameters):
            observed.update(parameters)
            production.register_synthesis_adapter(registry, project=current,
                                                   parameters=parameters)
            return registry
    assert design._bootstrap_execution_policy(
        Execution, project, top='top', container='unused', ic_class=None,
        skip_analog=True) is registry
    assert len(registry.arms) == 1
    assert not registry.arms[0].available
    if damage:
        assert 'pdk' not in observed
        code = 'LL_PHASE2_PDK_UNDECLARED' if damage == 'missing' else 'LL_PHASE2_PDK_CONFLICT'
        assert observed['pdk_refusal'].startswith(code)
        assert code in registry.arms[0].availability_reason
        assert measured == []
    else:
        assert observed['pdk'] == production._pdk_dict(pdk)
        assert observed['pdk_name'] == pdk.name
        assert measured == [('img', project)]
        assert 'SOURCE_ONLY_NATIVE_PROBE_STOP' in registry.arms[0].availability_reason
    assert native_calls == []

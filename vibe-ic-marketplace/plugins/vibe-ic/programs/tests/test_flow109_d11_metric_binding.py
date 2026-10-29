"""D11 actual consumers with explicit SOFTWARE upstream/authority/native records.

These fixtures isolate metric/currentness/publication behavior. They do NOT
qualify a native tool, sign product authority, or establish a product row.
E supplies separate actual native D11 purpose controls; no native tool runs here.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import inspect

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import librelane_contract as contract
import vibe_ic_one_shot_runner as runner


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
    return {'path': str(p), 'sha256': sha(p)}


def ref(p, path):
    return {'path': str(path.relative_to(p)), 'sha256': sha(path)}


def identity(subject):
    return {'producer': {'kind': 'SOFTWARE_REQUIREMENTS_OWNER_FIXTURE'},
        'checker': {'kind': 'SOFTWARE_ONLY'}, 'tool_execution': {'kind': 'SOURCE_REVIEW_FIXTURE'},
        'consumed_inputs': subject, 'requirements': {'basis': 'fixed neutral source fixture'},
        'configuration': {'purpose': 'D11.default'}}


def context(registry=None, runtime=None):
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                  if p['name'] == 'Small digital IC without DFT'))
    return flow109.execution_context(flow109.resolve_plan(features), 'D11', 'D11',
        runtime_tool_uses=runtime, qualification_registry=registry)


@pytest.fixture
def case(tmp_path):
    """Full native record SOFTWARE fixture, real file/authority/admission readers."""
    import _cdc_netlist as native
    p = tmp_path / 'subject'
    rtl = p / 'phase2/stage1/rtl'
    put(rtl / 'neutral.v', '`include "width.vh"\nmodule neutral(input a,output y); wire n; leaf u(a,n); assign y=n; endmodule\n')
    put(rtl / 'leaf.v', 'module leaf(input a,output y); assign y=a; endmodule\n')
    put(rtl / 'width.vh', '`define NEUTRAL_WIDTH 1\n')
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'neutral'})
    put(p / 'reports/orchestrator/phase1_one_shot.json', {'scope': 'SOFTWARE_D01_ONLY'})
    files = sorted(rtl.glob('*'))
    d09 = {'step_id': 'D09', 'completed': True, 'component_status': 'PASS', 'default_row_status': 'PASS',
        'fixture_scope': 'SOFTWARE_UPSTREAM_ONLY', 'evidence': {'rtl_inventory':
            [{'path': x.name, 'sha256': sha(x)} for x in files]}}
    d09path = p / 'reports/flow109/default_rows/D09.json'
    put(d09path, d09)
    cfg = {'meta': {'step': 'Verilator.Lint'}, 'DESIGN_NAME': 'neutral',
        'VERILOG_FILES': [str(rtl / 'leaf.v'), str(rtl / 'neutral.v')], 'LINTER_ERROR_ON_LATCH': True,
        'LINTER_DISABLE_WARNINGS': ['DECLFILENAME', 'EOFNEWLINE'],
        'LINTER_DISABLE_WARNINGS_BLACKBOX': ['UNDRIVEN', 'UNUSEDSIGNAL'],
        'LINTER_RELATIVE_INCLUDES': True}
    launch = json.loads(Path(os.environ[contract.LOCAL_ATTESTATION_ENV]).read_bytes())
    original_launch = p / 'input/flow109/D11/original-launch.json'
    put(original_launch, launch)
    original = p / 'input/flow109/D11/original-phase2.json'
    values = {'design__lint_error__count': 0, 'design__lint_timing_construct__count': 0,
              'design__inferred_latch__count': 0, 'design__lint_warning__count': 4}
    local = contract.local_image_attestation()
    folders = {}
    for index, sid in enumerate(metrics.D11_STEPS, 1):
        directory = p / 'phase3/librelane/step2' / (f'{index:02d}-' + sid.lower().replace('.', '-'))
        folders[sid] = directory
        put(directory / 'config.json', {**cfg, 'meta': {'step': sid}})
        put(directory / 'state_out.json', {'metrics': values})
        put(directory / 'state_in.json', {'metrics': values})
        put(directory / 'invocation.log', 'SOFTWARE_NATIVE_RECORD_FIXTURE_NOT_EXECUTION\n')
        put(directory / 'pdk_root.json', {'scope': 'SOFTWARE_ONLY'})
        fingerprint = {'step': sid, 'image': launch['image'], 'local_image': local,
                       'config_files': {str(x): sha(x) for x in files}, 'state_files': {}}
        put(directory / 'input_fingerprint.json', fingerprint)
        if sid == 'Verilator.Lint':
            put(directory / 'COMMANDS', 'verilator --lint-only --Wall --Werror-LATCH --relative-includes '
                + '--top-module neutral ' + ' '.join(cfg['VERILOG_FILES']) + '\n')
            put(directory / 'verilator-lint.log', 'SOFTWARE_ONLY four advisory warnings\n')
        seal_native(directory, fingerprint)
    lint = folders['Verilator.Lint']
    checks = {k: v for k, v in folders.items() if k != 'Verilator.Lint'}
    judged = __import__('verilator_lint_gate').judge(lint, [Path(x) for x in cfg['VERILOG_FILES']], checker_dirs=checks)
    native_row = {'name': 'rtl_lint_tool', 'status': 'PASS', 'extras': {'mode': 'librelane',
        'input_sha256': {x: sha(x) for x in cfg['VERILOG_FILES']}, 'native_checks': judged['native_checks']}}
    import design_one_shot_runner as design
    original_producer = p / 'input/source/original-lint.py'
    producer_text = inspect.getsource(design.step_rtl_lint_tool)
    put(original_producer, producer_text)
    producer = {'path': str(original_producer), 'sha256': sha(original_producer)}
    put(original, {'steps': [native_row], 'runner_binding': {'producer': producer}})
    d09['evidence'].update(phase2_report=ref(p, original), producer=producer)
    put(d09path, d09)
    d10subject = metrics.d10_adopted_rtl(p)
    d10subject['rtl_inputs'] = native.source_binding(p, 'neutral')['files']
    reference = {'top': 'neutral', 'ports': {'a': {'direction': 'input', 'width': 1, 'signed': 0},
        'y': {'direction': 'output', 'width': 1, 'signed': 0}},
        'parameterization': 'SOURCE_DEFAULTS_NO_OVERRIDES', 'blackbox_instances': []}
    source = p / 'input/flow109/d10.json'
    source_ref = put(source, {'feature_inventory': {'reference': reference, 'reference_identity': identity(d10subject)}})
    source_ref['path'] = str(source.relative_to(p))
    put(p / 'adopted/base_04/feature_inventory.json', {'schema': 'vibeic.flow109.adopted-reference.v1',
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': source_ref},
        'reference': reference, 'reference_identity': identity(d10subject)})
    put(p / 'reports/flow109/default_rows/D10.json', {'step_id': 'D10', 'completed': True,
        'default_row_status': 'PASS', 'component_status': 'PASS', 'fixture_scope': 'SOFTWARE_ONLY',
        'evidence': {'metric_acceptance': {'subject': d10subject}}})
    subject = metrics.d11_subject(p)
    executable = Path(shutil.which('verilator'))
    readset = metrics.d11_tool_readset()
    reference = {'project': str(p), 'subject': subject, 'owner_report': ref(p, original),
        'lint_dir': str(lint.relative_to(p)), 'checker_dirs': {k: str(v.relative_to(p)) for k, v in checks.items()},
        'launch': ref(p, original_launch), 'image_id': local['image_id'], 'tool_readset': readset,
        'artifacts': [ref(p, x) for d in folders.values() for x in sorted(d.rglob('*')) if x.is_file()]}
    adopted = {'reference': reference, 'reference_identity': identity(subject)}
    source = p / 'input/flow109/d11.json'
    source_ref = put(source, {'fixture_scope': 'SOFTWARE_AUTHORITY_ONLY', 'lint_execution': adopted,
                            'source_file_coverage': {'required_items': subject['source_files'], 'subject': subject}})
    source_ref['path'] = str(source.relative_to(p))
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': source_ref}
    put(p / 'requirements/base_05/source_file_coverage.json', {'schema': metrics.AUTHORITY_SCHEMA,
        'approval': approval, 'required_items': subject['source_files']})
    put(p / 'adopted/base_05/lint_execution.json', {'schema': 'vibeic.flow109.adopted-reference.v1',
        'approval': approval, **adopted})
    policy = {'LINTER_ERROR_ON_LATCH': True, 'warning_blocking': False,
        'LINTER_DISABLE_WARNINGS': cfg['LINTER_DISABLE_WARNINGS'],
        'LINTER_DISABLE_WARNINGS_BLACKBOX': cfg['LINTER_DISABLE_WARNINGS_BLACKBOX']}
    controls = {}
    for kind, status, count in [('positive', 'PASS', 0), ('required_violation', 'FAIL', 1), ('latch', 'FAIL', 1), ('timing_construct', 'FAIL', 1)]:
        control = p / ('input/qualification/' + kind + '.json')
        put(control, {'purpose': 'D11.default', 'image_id': local['image_id'],
            'native_sources': metrics.d11_native_sources(), 'policy': policy, 'tool_readset': readset,
            'status': status, 'required_lint_violations': count,
            'native_metrics': {'design__inferred_latch__count': count, 'design__lint_timing_construct__count': count},
            'artifacts': [ref(p, original)],
            'fixture_scope': 'SOFTWARE_QUALIFICATION_NOT_TOOL_QUALIFICATION'})
        controls[kind] = ref(p, control)
    config = p / 'input/qualification/config.json'
    put(config, {'schema': 'vibeic.flow109.d11-lint-qualification.v1', 'purpose': 'D11.default',
        'native_steps': list(metrics.D11_STEPS), 'checked_metrics': list(metrics.D11_IDS),
        'native_sources': metrics.d11_native_sources(), 'producer_function_sha256': hashlib.sha256(producer_text.rstrip().encode()).hexdigest(),
        'policy': policy, 'image_id': local['image_id'],
        'tool_readset': readset, 'settings': metrics.d11_consumed_settings(cfg),
        'controls': controls})
    ident = {'use_id': 'flow109.D11.default.verilator', 'tool_id': 'verilator', 'version': 'SOFTWARE_FIXTURE',
        'build_sha256': sha(executable), 'executable': {'path': str(executable), 'sha256': sha(executable)},
        'config': ref(p, config), 'pdk': {'applicable': False, 'reason': 'SOFTWARE_SCOPE'},
        'deck': {'applicable': False, 'reason': 'SOFTWARE_SCOPE'}, 'corner': 'RTL',
        'semantics': {'purpose': 'D11.default', 'native_steps': list(metrics.D11_STEPS)}}
    rec = {'use_id': ident['use_id'], 'status': 'QUALIFIED', 'identity': ident,
           'reference_evidence': list(controls.values())}
    registry = p / 'input/qualification/registry.json'
    put(registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [rec]})
    runtime = [{**ident, 'qualification_sha256': admission.canonical_sha(rec)}]
    c = context(str(registry.relative_to(p)), runtime)
    return {'project': p, 'context': c, 'folders': folders, 'source': source, 'original': original,
            'reference': reference, 'registry': registry, 'config': config}


def seal_native(directory, fp):
    hashes = {x.name: sha(x) for x in directory.iterdir() if x.is_file() and x.name != 'vibeic_receipt.json'}
    put(directory / 'vibeic_receipt.json', {'input': fp, 'sha256': hashes})


def accept(c):
    return metrics.accept_d11(c['project'], c['context'])


def test_d11_complete_typed_native_population_and_advisory_policy(case):
    result = accept(case)
    assert result['status'] == 'PASS', result
    assert [x['status'] for x in result['obligations']] == ['PASS', 'PASS']
    assert result['obligations'][0]['observed_value'] == 0
    assert result['native_observation']['counts']['warnings'] == 4
    assert len(result['subject']['source_files']) == 3


@pytest.mark.parametrize('mutation', ['drop', 'rtl', 'header', 'new_header', 'config', 'commands',
    'checker', 'launch', 'extra_native', 'missing_receipt', 'source_authority', 'missing_qualification',
    'forged_qualification', 'missing_control'])
def test_d11_refuses_changed_incomplete_or_foreign_consumed_bytes(case, mutation):
    p = case['project']
    files = {'rtl': p / 'phase2/stage1/rtl/neutral.v', 'header': p / 'phase2/stage1/rtl/width.vh',
        'config': case['folders']['Verilator.Lint'] / 'config.json',
        'commands': case['folders']['Verilator.Lint'] / 'COMMANDS',
        'checker': case['folders']['Checker.LintErrors'] / 'state_out.json',
        'launch': p / case['reference']['launch']['path'], 'source_authority': case['source']}
    if mutation == 'drop': (p / 'phase2/stage1/rtl/leaf.v').unlink()
    elif mutation == 'new_header': put(p / 'phase2/stage1/rtl/extra.svh', '// independently unadopted header\n')
    elif mutation == 'extra_native': put(case['folders']['Verilator.Lint'] / 'unsealed.v', 'module unexpected; endmodule\n')
    elif mutation == 'missing_receipt': (case['folders']['Checker.LintErrors'] / 'vibeic_receipt.json').unlink()
    elif mutation == 'missing_qualification': case['context'] = context()
    elif mutation == 'forged_qualification':
        j = json.loads(case['registry'].read_bytes());j['uses'][0]['identity']['build_sha256'] = '0' * 64;put(case['registry'], j)
    elif mutation == 'missing_control': (p / 'input/qualification/required_violation.json').unlink()
    else: files[mutation].write_bytes(files[mutation].read_bytes() + b'\nchanged\n')
    result = accept(case)
    assert result['status'] == 'NOT_MEASURED', result
    assert result.get('reason') != 'D11_METRICS_PASS'


def reseal_software_native_failure(c, metric):
    """Only synthetic native/upstream fixture construction, NOT production resealing."""
    p = c['project']
    for folder in c['folders'].values():
        doc = json.loads((folder / 'state_out.json').read_bytes());doc['metrics'][metric] = 1
        put(folder / 'state_out.json', doc)
        seal_native(folder, json.loads((folder / 'input_fingerprint.json').read_bytes()))
    import verilator_lint_gate as lint
    dirs = {k: v for k, v in c['folders'].items() if k != 'Verilator.Lint'}
    expected = [p / r['path'] for r in c['reference']['subject']['source_files'] if r['path'].endswith('.v')]
    judged = lint.judge(c['folders']['Verilator.Lint'], expected, checker_dirs=dirs)
    doc = json.loads(c['original'].read_bytes());doc['steps'][0]['status'] = 'FAIL'
    doc['steps'][0]['extras']['native_checks'] = judged['native_checks'];put(c['original'], doc)
    d09path = p / 'reports/flow109/default_rows/D09.json';d09 = json.loads(d09path.read_bytes())
    d09['evidence']['phase2_report'] = ref(p, c['original']);put(d09path, d09)
    # This deliberately scoped upstream fixture supports a negative native
    # observation; it makes no claim that a real D09 accepted failed lint.
    d10path = p / 'reports/flow109/default_rows/D10.json';d10 = json.loads(d10path.read_bytes())
    subject = d10['evidence']['metric_acceptance']['subject'];subject['D09'] = ref(p, d09path)
    put(d10path, d10)
    adopted10 = p / 'adopted/base_04/feature_inventory.json';a = json.loads(adopted10.read_bytes())
    s = p / a['approval']['source_reference']['path'];doc = json.loads(s.read_bytes())
    doc['feature_inventory']['reference_identity']['consumed_inputs'] = subject;put(s, doc)
    a.update(doc['feature_inventory']);a['approval']['source_reference'] = ref(p, s);put(adopted10, a)
    subject = metrics.d11_subject(p)
    src = json.loads(c['source'].read_bytes());r = src['lint_execution']['reference']
    r.update(subject=subject, owner_report=ref(p, c['original']), artifacts=[ref(p,x)
        for folder in c['folders'].values() for x in sorted(folder.rglob('*')) if x.is_file()])
    src['lint_execution']['reference_identity']['consumed_inputs'] = subject
    src['source_file_coverage'] = {'required_items': subject['source_files'], 'subject': subject}
    put(c['source'], src)
    adopted = p / 'adopted/base_05/lint_execution.json';a = json.loads(adopted.read_bytes())
    a.update(src['lint_execution']);a['approval']['source_reference'] = ref(p,c['source']);put(adopted,a)
    req = p / 'requirements/base_05/source_file_coverage.json';a=json.loads(req.read_bytes())
    a.update(required_items=subject['source_files']);a['approval']['source_reference']=ref(p,c['source']);put(req,a)
    # Synthetic qualification reference index follows only this test's fixture.
    for kind in ('positive','required_violation','latch','timing_construct'):
        control=p/('input/qualification/'+kind+'.json');doc=json.loads(control.read_bytes())
        doc['artifacts']=[ref(p,c['original'])];put(control,doc)
    cfg=json.loads(c['config'].read_bytes());cfg['controls']={k:ref(p,p/('input/qualification/'+k+'.json')) for k in cfg['controls']};put(c['config'],cfg)
    reg=json.loads(c['registry'].read_bytes());rec=reg['uses'][0]
    rec['identity']['config']=ref(p,c['config']);rec['reference_evidence']=list(cfg['controls'].values());put(c['registry'],reg)
    c['context']=context(str(c['registry'].relative_to(p)),[{**rec['identity'],'qualification_sha256':admission.canonical_sha(rec)}])


@pytest.mark.parametrize('metric', ['design__lint_error__count', 'design__lint_timing_construct__count',
                                  'design__inferred_latch__count'])
def test_d11_qualified_native_failure_survives_missing_coverage(case, metric):
    reseal_software_native_failure(case, metric)
    (case['project'] / 'requirements/base_05/source_file_coverage.json').unlink()
    result = accept(case)
    assert result['status'] == 'FAIL', result
    assert result['obligations'][0]['status'] == 'FAIL'
    assert result['obligations'][1]['status'] == 'NOT_MEASURED'


def test_d11_registry_binds_both_metrics_and_actual_native_checker_purpose():
    row = context()['resolved_row']
    assert row['metric_acceptance_status'] == 'IMPLEMENTED', row
    assert [x['id'] for x in row['obligations']] == ['base_05.required_lint_violations', 'base_05.source_file_coverage']
    assert row['tool_uses'][0]['purpose'] == 'D11.default'
    assert row['tool_uses'][0]['native_steps'] == list(metrics.D11_STEPS)


def test_d11_tool_purpose_settings_bind_actual_native_reads_only(case):
    n = metrics._d11_native(case['project'], case['reference'])
    original = metrics._d11_qualification(case['project'], case['context'], n)
    # These are real existing raw config keys, excluded by the installed
    # lint's actual access sites. Original execution artifacts are untouched.
    n['config'].update(CLOCK_PERIOD=24, DIE_AREA=[0, 0, 99, 99], CORE_AREA=[1, 1, 98, 98])
    assert metrics._d11_qualification(case['project'], case['context'], n) == original
    assert not {'CLOCK_PERIOD', 'DIE_AREA', 'CORE_AREA'} & metrics.d11_consumed_settings(n['config']).keys()


@pytest.mark.parametrize('key,value', [('LINTER_DEFINES', ['DIFFERENT']),
    ('VERILOG_INCLUDE_DIRS', ['/different/include']), ('LINTER_ERROR_ON_LATCH', False),
    ('LINTER_RELATIVE_INCLUDES', False), ('CELL_VERILOG_MODELS', ['/different/model.v'])])
def test_d11_tool_purpose_refuses_consumed_setting_change(case, key, value):
    n = metrics._d11_native(case['project'], case['reference'])
    metrics._d11_qualification(case['project'], case['context'], n)
    n['config'][key] = value
    with pytest.raises(metrics.MetricRefusal, match='D11_QUALIFICATION_SETTINGS_MISMATCH'):
        metrics._d11_qualification(case['project'], case['context'], n)


def normal_owner(c, monkeypatch):
    """Actual typed producer and ordinary report binding, software dependencies."""
    import design_one_shot_runner as design
    import benchmark_dispatch as dispatch
    from dataclasses import asdict
    p = c['project']
    ctxpath = p / 'context.json';put(ctxpath, c['context'])
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(ctxpath))
    attempt = flow109._new_attempt(p, c['context'])
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    row = design.step_rtl_lint_tool(p)
    assert row.name == 'rtl_lint_tool'
    assert row.extras['completed'] is False
    assert row.extras['native_reused'] is True
    argv = [sys.executable, str(Path(design.__file__).with_name('phase2_one_shot_runner.py')), str(p),
            '--entry-step', '2', '--exit-step', '2']
    invocation = {'invocation_id': 'software-normal-d11-owner', 'argv': argv, 'project': str(p),
                  'source': dispatch._runner_source_snapshot(argv)}
    report = {'project': str(p), 'steps': [asdict(row)], 'verdict': row.status,
              'declared_window': {'entry_step': '2', 'exit_step': '2', 'dispatched_step_ids': ['2']}}
    report = dispatch._bind_runner_report(report, p, design.__file__, 'phase2_one_shot.json', context=invocation)
    put(p / 'reports/orchestrator/phase2_one_shot.json', report)
    return report, invocation, attempt


def test_d11_normal_typed_owner_and_canonical_publication(case, monkeypatch):
    report, invocation, attempt = normal_owner(case, monkeypatch)
    result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    assert result['verdict'] == 'PASS', result
    row = json.loads((case['project'] / 'reports/flow109/default_rows/D11.json').read_bytes())
    assert row['default_row_status'] == 'PASS' and row['completed'] is True
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and row['delivery_accepted'] is False
    assert json.loads((attempt / 'result.json').read_bytes())['default_row_status'] == 'PASS'


@pytest.mark.parametrize('kind', ['missing', 'stale_invocation', 'outer_fail'])
def test_d11_canonical_publication_requires_actual_fresh_owner(case, monkeypatch, kind):
    report, invocation, _ = normal_owner(case, monkeypatch)
    if kind == 'missing': report = {}
    elif kind == 'stale_invocation': invocation['invocation_id'] = 'different'
    else:
        report['verdict'] = 'FAIL'
        put(case['project'] / 'reports/orchestrator/phase2_one_shot.json', report)
    result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    assert result['verdict'] == 'NOT_MEASURED', result
    assert result['metric_acceptance']['status'] == 'PASS'
    row = json.loads((case['project'] / 'reports/flow109/default_rows/D11.json').read_bytes())
    assert row['completed'] is False and row['default_row_status'] == 'NOT_MEASURED'


def test_d11_finalizer_reopens_after_first_genuine_pass(case, monkeypatch):
    report, invocation, _ = normal_owner(case, monkeypatch)
    code = metrics.accept_d11.__code__
    observed = []
    old = sys.getprofile()
    def after(frame, event, arg):
        if event == 'return' and frame.f_code is code:
            observed.append(arg['status'])
            if len(observed) == 1:
                path = case['project'] / 'phase2/stage1/rtl/width.vh'
                path.write_bytes(path.read_bytes() + b'// changed actual header\n')
        if old: old(frame, event, arg)
    sys.setprofile(after)
    try:
        result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    finally:
        sys.setprofile(old)
    assert observed == ['PASS', 'NOT_MEASURED'], observed
    assert result['verdict'] == 'NOT_MEASURED', result
    row = json.loads((case['project'] / 'reports/flow109/default_rows/D11.json').read_bytes())
    assert row['completed'] is False


def test_d11_canonical_immutable_attempt_is_not_rewritten(case, monkeypatch):
    report, invocation, attempt = normal_owner(case, monkeypatch)
    result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    assert result['verdict'] == 'PASS'
    before = (attempt / 'result.json').read_bytes()
    result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    assert result['verdict'] == 'NOT_MEASURED'
    assert (attempt / 'result.json').read_bytes() == before


def test_d11_true_qualified_failure_publishes_fail_with_missing_coverage(case, monkeypatch):
    reseal_software_native_failure(case, 'design__lint_timing_construct__count')
    (case['project'] / 'requirements/base_05/source_file_coverage.json').unlink()
    report, invocation, _ = normal_owner(case, monkeypatch)
    result = runner._finish_d11_selected_owner(case['project'], report, invocation, published_current=True)
    assert result['verdict'] == 'FAIL', result
    row = json.loads((case['project'] / 'reports/flow109/default_rows/D11.json').read_bytes())
    assert row['default_row_status'] == 'FAIL' and row['completed'] is False


def test_d11_native_checker_source_mismatch_is_unqualified(case):
    cfg = json.loads(case['config'].read_bytes())
    cfg['native_sources']['verilator_lint_gate.py:judge'] = '0' * 64
    put(case['config'], cfg)
    reg = json.loads(case['registry'].read_bytes());record = reg['uses'][0]
    record['identity']['config'] = ref(case['project'], case['config']);put(case['registry'], reg)
    case['context'] = context(str(case['registry'].relative_to(case['project'])),
        [{**record['identity'], 'qualification_sha256': admission.canonical_sha(record)}])
    result = accept(case)
    assert result['status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D11_TOOL_QUALIFICATION_UNPROVEN'


def test_d11_partial_required_source_set_cannot_self_adopt(case):
    req = case['project'] / 'requirements/base_05/source_file_coverage.json'
    doc = json.loads(req.read_bytes());doc['required_items'] = doc['required_items'][:1];put(req, doc)
    result = accept(case)
    assert result['status'] == 'NOT_MEASURED', result
    assert result['obligations'][0]['status'] == 'PASS'
    assert result['obligations'][1]['status'] == 'NOT_MEASURED'


def failed_native_case(kind):
    """Reopen E's actual frozen native failure, not a synthetic state_out."""
    root = Path('/evidence')
    frozen = Path(os.environ.get('FLOW109_D11_NATIVE_REFERENCE', '/reference'))
    if not frozen.is_dir():
        pytest.skip('D11 retained native input unavailable: native control NOT_MEASURED')
    case = json.loads((frozen / ('CASE_' + kind + '.json')).read_bytes())
    directory = root / 'fixtures' / kind
    if directory.exists(): shutil.rmtree(directory)
    shutil.copytree(frozen / 'fixtures' / kind, directory)
    base = directory / 'phase3/librelane/step2'
    failure = dict(case['normal_chain_refusal'], artifact_readset={str(root / r['path']): r['sha256']
        for r in case['artifacts']})
    checks = {sid: base / (f'{i:02d}-' + sid.lower().replace('.', '-'))
              for i, sid in enumerate(metrics.D11_STEPS[1:], 2)}
    expected = [Path(x) for x in json.loads((base / '01-verilator-lint/config.json').read_bytes())['VERILOG_FILES']]
    return directory, base / '01-verilator-lint', checks, expected, failure


@pytest.mark.parametrize('kind', ['required_error', 'latch'])
def test_d11_actual_failed_native_checker_remains_fail_without_success_state(kind):
    import verilator_lint_gate as gate
    _, lint, checks, expected, failure = failed_native_case(kind)
    assert not (checks['Checker.LintErrors'] / 'state_out.json').exists()
    assert not checks['Checker.LintWarnings'].exists()
    before = {str(p): sha(p) for p in lint.parent.rglob('*') if p.is_file()}
    result = gate.judge(lint, expected, checker_dirs=checks, native_failure=failure)
    assert result['verdict'] == 'FAIL', result
    assert result['native_failure']['execution_status'] == 'NATIVE_FAILED_NO_SUCCESS_STATE'
    assert result['native_failure']['exit_code'] == 255
    assert {str(p): sha(p) for p in lint.parent.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('mutation', ['no_failure', 'arbitrary_rc', 'log', 'source', 'launch', 'counter'])
def test_d11_actual_failed_native_checker_refuses_missing_tampered_provenance(mutation):
    import verilator_lint_gate as gate
    directory, lint, checks, expected, failure = failed_native_case('required_error')
    if mutation == 'no_failure': failure = None
    elif mutation == 'arbitrary_rc': failure['detail'] = failure['detail'].replace('rc=255', 'rc=137')
    else:
        path = {'log': checks['Checker.LintErrors'] / 'invocation.log', 'source': expected[0],
                'launch': checks['Checker.LintErrors'] / 'input_fingerprint.json',
                'counter': checks['Checker.LintErrors'] / 'state_in.json'}[mutation]
        path.write_bytes(path.read_bytes() + b'\nchanged\n')
    result = gate.judge(lint, expected, checker_dirs=checks, native_failure=failure)
    assert result['verdict'] == 'NOT_MEASURED', result


def software_fresh_owner(c, monkeypatch):
    """SOFTWARE native/upstream isolation; actual current typed owner consumers.

    No native run or product authority is claimed. The existing synthetic
    native records are fed through the real capture/binding/publication code.
    """
    import design_one_shot_runner as design
    import benchmark_dispatch as dispatch
    from dataclasses import asdict
    p = c['project'];ctx = c['context']
    src = json.loads(c['source'].read_bytes())
    src['native_run'] = {'purpose': 'D11.default', 'subject': metrics.d11_subject(p),
                        'qualification_registry': ref(p,c['registry'])}
    put(c['source'],src)
    for name in ['requirements/base_05/source_file_coverage.json', 'adopted/base_05/lint_execution.json']:
        path=p/name;doc=json.loads(path.read_bytes());doc['approval']['source_reference']=ref(p,c['source']);put(path,doc)
    assert metrics.d11_fresh_request(p,ctx)
    configs={sid:json.loads((folder/'config.json').read_bytes()) for sid,folder in c['folders'].items()}
    admitted=metrics.d11_fresh_admission(p,ctx,configs['Verilator.Lint'],configs)
    execution=metrics.d11_capture_execution(p,ctx,c['folders']['Verilator.Lint'].parent,admitted)
    judged=__import__('verilator_lint_gate').judge(c['folders']['Verilator.Lint'],
        [Path(x) for x in configs['Verilator.Lint']['VERILOG_FILES']],
        checker_dirs={k:v for k,v in c['folders'].items() if k!='Verilator.Lint'})
    row=design.StepResult('rtl_lint_tool',judged['verdict'],0,'SOFTWARE_NATIVE_UPSTREAM_ONLY',extras={
        'step_id':'2','mode':'librelane','completed':False,'native_fresh':True,
        'default_row_status':'NOT_MEASURED','context_sha256':ctx['context_sha256'],
        'native_lint_execution':execution,'native_checks':judged['native_checks'],
        'input_sha256':{x:sha(x) for x in configs['Verilator.Lint']['VERILOG_FILES']}})
    producer=p/'runtime/programs/design_one_shot_runner.py';put(producer,Path(design.__file__).read_text())
    argv=[sys.executable,str(Path(design.__file__).with_name('phase2_one_shot_runner.py')),str(p),
          '--entry-step','2','--exit-step','2']
    invocation={'invocation_id':'software-fresh-native-owner','argv':argv,'project':str(p),
                'source':dispatch._runner_source_snapshot(argv)}
    report={'project':str(p),'steps':[asdict(row)],'verdict':row.status,
            'declared_window':{'entry_step':'2','exit_step':'2','dispatched_step_ids':['2']}}
    report=dispatch._bind_runner_report(report,p,str(producer),'phase2_one_shot.json',context=invocation)
    put(p/'reports/orchestrator/phase2_one_shot.json',report)
    ctxpath=p/'context.json';put(ctxpath,ctx);monkeypatch.setenv(flow109.CONTEXT_ENV,str(ctxpath))
    attempt=flow109._new_attempt(p,ctx);monkeypatch.setenv(flow109.ATTEMPT_ENV,str(attempt))
    return report,invocation


def test_d11_current_native_owner_does_not_require_old_d09_execution_adoption(case,monkeypatch):
    report,invocation=software_fresh_owner(case,monkeypatch)
    (case['project']/'adopted/base_05/lint_execution.json').unlink()
    result=runner._finish_d11_selected_owner(case['project'],report,invocation,published_current=True)
    assert result['verdict']=='PASS',result
    assert result['metric_acceptance']['subject']['D09']==metrics.d11_subject(case['project'])['D09']
    row=json.loads((case['project']/'reports/flow109/default_rows/D11.json').read_bytes())
    assert row['completed'] is True and row['metric_acceptance_status']=='PASS'


def test_d11_current_qualified_native_fail_keeps_fail_when_coverage_doc_absent(case,monkeypatch):
    reseal_software_native_failure(case,'design__lint_timing_construct__count')
    report,invocation=software_fresh_owner(case,monkeypatch)
    (case['project']/'requirements/base_05/source_file_coverage.json').unlink()
    (case['project']/'adopted/base_05/lint_execution.json').unlink()
    result=runner._finish_d11_selected_owner(case['project'],report,invocation,published_current=True)
    assert result['verdict']=='FAIL',result
    assert result['metric_acceptance']['obligations'][1]['status']=='NOT_MEASURED'


def test_d11_current_native_owner_missing_fresh_binding_cannot_publish(case,monkeypatch):
    report,invocation=software_fresh_owner(case,monkeypatch)
    (case['project']/'adopted/base_05/lint_execution.json').unlink()
    invocation['invocation_id']='foreign-current-owner'
    result=runner._finish_d11_selected_owner(case['project'],report,invocation,published_current=True)
    assert result['verdict']=='NOT_MEASURED',result


@pytest.mark.parametrize('window', [False, True])
def test_d11_entry_preserves_other_normal_context_shapes(tmp_path, monkeypatch, window):
    import design_one_shot_runner as design
    c=context()
    plan=flow109.resolve_plan(c['features'])
    selected=flow109.execution_context(plan,'D11','D12') if window else flow109.execution_context(plan,'D09','D09')
    path=tmp_path/'other-context.json';put(path,selected)
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(path))
    monkeypatch.setattr(contract,'selected_mode',lambda *args:'direct')
    # Existing structured direct lint returns None without a native call.
    try: observed=design.step_rtl_lint_tool(tmp_path)
    except KeyError as exc: observed={'exception':'KeyError','field':str(exc)}
    assert observed is None,observed

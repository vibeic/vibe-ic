import json
from pathlib import Path
import json
import execution_frontend_providers as p

EXPECTED=('D1','0.5ic','1','2','3','4','5','6','7','8','10','11','FS1','DT1','12','13','DT2','DT3','P0')







def test_step4_zero_skip_denominator_blocks_native_run(tmp_path, monkeypatch):
    import subprocess
    import execution_step4 as step4
    junit = tmp_path / 'results.xml'
    def run(*args, **kwargs):
        junit.write_text('<testsuites><testsuite><testcase name="skipped"><skipped/></testcase></testsuite></testsuites>')
        return subprocess.CompletedProcess(args[0], 0, 'PROFESSIONAL_TB PASS', '')
    monkeypatch.setattr(step4.subprocess, 'run', run)
    result = step4._simulate(tmp_path, 'icarus')
    assert result['rc'] == 0
    assert result['verdict'] == 'FAIL'


def test_step4_vacuous_not_applicable_rc2_is_translated_only_with_typed_report(tmp_path):
    import subprocess
    import sys
    import execution_step4 as step4
    report = tmp_path / 'reports' / 'vacuous.json'
    cp = subprocess.run(
        [sys.executable, str(Path(step4.__file__)), '--gate',
         'vacuous_testbench_check', '.', '--json', str(report.relative_to(tmp_path))],
        cwd=tmp_path, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert json.loads(report.read_text())['verdict'] == 'NOT_APPLICABLE'


def test_step4_functional_argv_overrides_outside_makefile_sources(tmp_path, monkeypatch):
    import subprocess
    import execution_step4 as step4
    project = tmp_path / 'inputs'
    rtl = project / 'phase2' / 'stage1' / 'rtl' / 'top.v'
    makefile = project / 'phase2' / 'stage1' / 'sim_professional' / 'top' / 'Makefile'
    rtl.parent.mkdir(parents=True)
    makefile.parent.mkdir(parents=True)
    rtl.write_text('module top; endmodule\n')
    makefile.write_text('VERILOG_SOURCES := /outside/project/rtl.v\n')
    import hashlib
    files = {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in (rtl, makefile)}
    (project / 'input').mkdir()
    (project / 'input' / 'issued_manifest.json').write_text(json.dumps(
        {'step_id': '4', 'parameters': {'top': 'top'}, 'files': files}))
    output = tmp_path / 'outputs'
    invoked = []

    def run(argv, **kwargs):
        invoked.append(list(argv))
        junit = next(Path(arg.split('=', 1)[1]) for arg in argv
                     if arg.startswith('COCOTB_RESULTS_FILE='))
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0">'
                         '<testcase name="native"/></testsuite>')
        return subprocess.CompletedProcess(argv, 0, 'PROFESSIONAL_TB PASS', '')

    monkeypatch.setattr(step4.subprocess, 'run', run)
    monkeypatch.setattr(step4, 'measure_bundle', lambda *args, **kwargs:
                        {'verdict': 'NOT_MEASURED', 'reason': 'focused control'})
    step4.produce(project, output, 'icarus')
    sources = next(arg for arg in invoked[0] if arg.startswith('VERILOG_SOURCES='))
    assert sources.split('=', 1)[1].split() == [str(output / 'phase2/stage1/rtl/top.v')]
    assert '/outside/project/rtl.v' not in sources


def test_step4_refuses_empty_staged_rtl(tmp_path):
    import execution_step4 as step4
    with __import__('pytest').raises(ValueError, match='staged RTL population is empty'):
        step4.staged_rtl(tmp_path)

def test_machine_readable_coverage_and_default():
    c=p.coverage(); assert tuple(c)==EXPECTED; assert all(c[r]['default_rank']==i for i,r in enumerate(EXPECTED)); assert c['0.5ic']['applicability']=='IC+IP route authority'

def test_missing_provider_is_typed_and_no_pass():
    for row in EXPECTED:
        result=p.produce(row, Path('/nonexistent/project'))
        assert result.state in ('NOT_IMPLEMENTED','NOT_MEASURED'); assert 'PASS' not in result.state
    assert p.produce('opaque', Path('.')).state=='NOT_IMPLEMENTED'



def test_step6_explicitly_not_measured_without_fpga():
    result=p.produce('6', Path('/missing'), fpga=False)
    assert result.state=='NOT_IMPLEMENTED'























@__import__('pytest').mark.parametrize('row,required', [
    ('2', ('top','clock','timeout','baseline_rtl_dir','candidate_rtl_dir')),
    ('3', ('top',)), ('4', ('top','container')), ('5', ('top','container')),
])
def test_rows_2_to_5_missing_typed_params_call_nothing(tmp_path, monkeypatch, row, required):
    import execution_frontend_worker as w
    calls=[]
    monkeypatch.setattr(w.subprocess, 'run', lambda *a, **k: calls.append(('cli',a,k)) or type('R',(),{'returncode':0,'stdout':'','stderr':''})())
    kwargs={name:'x' for name in required}
    for missing in required:
        bad=dict(kwargs); bad.pop(missing)
        calls.clear()
        with __import__('pytest').raises(ValueError): w.run_row(row,tmp_path,tmp_path/'out',**bad)
        assert calls == [], (row, missing, calls)

def test_rows_2_to_5_spy_order_and_argv(tmp_path, monkeypatch):
    import execution_frontend_worker as w
    import design_one_shot_runner as d
    import p0_tool_frontend_check as p0
    import formal_harness_gen as fh, formal_property_run as fp
    calls=[]
    monkeypatch.setattr(p0, 'check', lambda project: calls.append(('p0.check', str(project))) or {'ok':True})
    monkeypatch.setattr(w.subprocess, 'run', lambda argv, **kw: calls.append(('cli', list(argv))) or type('R',(),{'returncode':0,'stdout':'','stderr':''})())
    for name in ('step_professional_tb_gen','step_reference_tb','step_l10_unit_tb_run','step_full_stack_functional_tb'):
        monkeypatch.setattr(d, name, lambda *a, _name=name, **k: calls.append((_name, a, k)) or {'ok':True})
    monkeypatch.setattr(fh, 'generate', lambda *a, **k: calls.append(('formal_harness_gen.generate', a, k)) or {'ok':True})
    monkeypatch.setattr(fp, 'run', lambda *a, **k: calls.append(('formal_property_run.run', a, k)) or {'ok':True})
    monkeypatch.setattr(w, '_write', lambda step,out,producer,**kw: calls.append(('write',step,producer,kw)) or (Path(out).mkdir(parents=True,exist_ok=True) or Path(out)/'report.json'))
    base={'top':'chip_top','clock':'clk','timeout':7,'baseline_rtl_dir':'base','candidate_rtl_dir':'cand','container':'img'}
    (tmp_path/'input').mkdir(exist_ok=True)
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'3','parameters':base,'files':{}}))
    w.produce_2(tmp_path,tmp_path/'o2',**base)
    assert [x[0] for x in calls[:2]] == ['p0.check','cli']
    assert '--baseline-rtl-dir' in calls[1][1] and '--candidate-rtl-dir' in calls[1][1] and '--timeout' in calls[1][1]
    calls.clear(); w.produce_3(tmp_path,tmp_path/'o3',top='chip_top')
    assert [x[0] for x in calls[:4]] == ['cli','cli','cli','cli']
    assert all('--json' in x[1] for x in calls if x[0]=='cli')
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'4','parameters':base,'files':{}}))
    calls.clear(); w.produce_4(tmp_path,tmp_path/'o4',top='chip_top',container='img')
    assert [x[0] for x in calls[:4]] == ['step_professional_tb_gen','step_reference_tb','step_l10_unit_tb_run','cli']
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'5','parameters':base,'files':{}}))
    calls.clear(); w.produce_5(tmp_path,tmp_path/'o5',top='chip_top',container='img')
    assert [x[0] for x in calls] == ['formal_harness_gen.generate','formal_property_run.run','step_full_stack_functional_tb','write']


def test_step7_worker_publishes_a_step_bound_complete_output_set(tmp_path, monkeypatch):
    """The Ultra arm exposes the canonical Step-7 bytes to its own consumers."""
    from types import SimpleNamespace
    import execution_frontend_worker as worker
    import design_one_shot_runner as design

    source = tmp_path / 'source'
    issued = source / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json'
    issued.parent.mkdir(parents=True)
    issued.write_text('{"clocks": {}}\n')
    output = tmp_path / 'output'
    monkeypatch.setattr(worker, '_verify_manifest', lambda root, step: {
        'step_id': step,
        'files': {str(issued.relative_to(source)): __import__('hashlib').sha256(
            issued.read_bytes()).hexdigest()},
        'parameters': {},
    })
    monkeypatch.setattr(worker, '_step7_pdk', lambda *args: object())

    def emit(project, top, container, pdk_config=None, _use_controller=None):
        constraints = project / 'phase2/stage2/constraints'
        constraints.mkdir(parents=True)
        sdc = constraints / f'{top}.sdc'
        matrix = constraints / 'pvt_matrix.json'
        stance = project / 'reports/phase3/single_corner_stance.json'
        stance.parent.mkdir(parents=True)
        sdc.write_text('create_clock -period 10 [get_ports clk]\n')
        matrix.write_text('{"corners": [{"label": "TT"}]}\n')
        stance.write_text('{"verdict": "PASS"}\n')
        return SimpleNamespace(name='asic_sdc', status='PASS', detail='emitted',
                               output_files=[str(sdc), str(matrix), str(stance)])

    monkeypatch.setattr(design, 'step_asic_sdc', emit)
    canonical = worker.produce_7(
        source, output, top='neutral', pdk={'name': 'neutral'}, container='eda')
    assert canonical == output / 'canonical.json'
    index = json.loads((output / 'steps/index.json').read_text())
    assert index['steps'] == [{
        'id': '7', 'name': 'Constraint setup (SDC + PVT matrix)',
        'folder': 'phase2/stage2/7_asic_sdc'}]
    written = json.loads((output /
        'steps/phase2/stage2/7_asic_sdc/written.json').read_text())
    assert written['n_required_outputs'] == 3
    assert {row['spec'] for row in written['produced']} == {
        'phase2/stage2/constraints/*.sdc',
        'phase2/stage2/constraints/pvt_matrix.json',
        'reports/phase3/single_corner_stance.json'}


def test_step7_worker_refuses_an_incomplete_canonical_output_set(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import execution_frontend_worker as worker
    import design_one_shot_runner as design

    source = tmp_path / 'source'
    source.mkdir()
    output = tmp_path / 'output'
    monkeypatch.setattr(worker, '_verify_manifest', lambda root, step: {
        'step_id': step, 'files': {}, 'parameters': {}})
    monkeypatch.setattr(worker, '_step7_pdk', lambda *args: object())

    def incomplete(project, top, container, pdk_config=None, _use_controller=None):
        constraints = project / 'phase2/stage2/constraints'
        constraints.mkdir(parents=True)
        (constraints / f'{top}.sdc').write_text('create_clock -period 10\n')
        return SimpleNamespace(name='asic_sdc', status='PASS', detail='partial',
                               output_files=[])

    monkeypatch.setattr(design, 'step_asic_sdc', incomplete)
    with __import__('pytest').raises(RuntimeError, match='canonical producer outputs incomplete'):
        worker.produce_7(
            source, output, top='neutral', pdk={'name': 'neutral'}, container='eda')





def test_step8_nonzero_and_manifest_mutation_refuse(tmp_path, monkeypatch):
    import hashlib
    project=tmp_path/'p'; sdc=project/'phase2/stage2/constraints/top.sdc'; sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -period 10 [get_ports clk]\nset_input_delay 1 -clock clk [all_inputs]\n')
    l8=project/'phase1/generated_docs/L8_TIMING_WAVEFORM.json'; l8.parent.mkdir(parents=True); l8.write_text(json.dumps({'clocks':{'clk':{'period_ns':11}}}))
    matrix=sdc.with_name('pvt_matrix.json'); matrix.write_text('{"corners":[]}\n')
    files={str(x.relative_to(project)):hashlib.sha256(x.read_bytes()).hexdigest() for x in (sdc,l8,matrix)}
    (project/'input').mkdir(); (project/'input/issued_manifest.json').write_text(json.dumps({'step_id':'8','parameters':{},'files':files}))
    import execution_frontend_worker as w
    # Producer-only unit invocation envelope: real input/manifest bytes and
    # hashes, not a claim of canonical Controller authority or adoption.
    manifest=project/'input/issued_manifest.json'
    manifest_hash=hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setenv(w.ISSUED_MANIFEST_ENV,str(manifest))
    monkeypatch.setenv('VIBEIC_MANIFEST_SHA256',manifest_hash)
    monkeypatch.setenv('VIBEIC_ISSUED_MANIFEST_SHA256',manifest_hash)
    with __import__('pytest').raises(RuntimeError): w.run_row('8',project,tmp_path/'out')
    (project/'input/issued_manifest.json').write_text(json.dumps({'step_id':'9','parameters':{},'files':files}))
    with __import__('pytest').raises(ValueError): w.run_row('8',project,tmp_path/'out2')

def test_05ic_parameter_exclusivity_precedes_tools(tmp_path, monkeypatch):
    import execution_frontend_worker as w
    calls=[]
    monkeypatch.setattr(w.subprocess, 'run', lambda *a, **k: calls.append(a) or None)
    (tmp_path/'input').mkdir(); (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'0.5ic','parameters':{},'files':{}}))
    for kwargs in ({}, {'no_template_reason':'R'}):
        calls.clear()
        with __import__('pytest').raises(ValueError): w.produce_05ic(tmp_path,tmp_path/'out',**kwargs)
        assert calls == []
    with __import__('pytest').raises(ValueError):
        w.produce_05ic(tmp_path, tmp_path/'out', template='P',
                       no_template_reason='a declared absence with a searched path')
    assert calls == []
    with __import__('pytest').raises(ValueError, match='no_template_reason'):
        w.produce_05ic(tmp_path, tmp_path/'out', template='input/template',
                       no_template_reason='')
    assert calls == []

































@__import__('pytest').mark.parametrize('document,row,field,required', [
    (document, row, field, required)
    for document in ('catalog', 'coverage')
    for row, field, required in (
        ('2', 'inputs', {'from': 'D1', 'path': 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'}),
        ('7', 'outputs', 'reports/phase3/single_corner_stance.json'),
        ('FS1', 'outputs', 'reports/phase2/safety/fmeda_coverage_gate.json'),
    )
], ids=['catalog-row2-input', 'catalog-row7-output', 'catalog-FS1-output',
        'coverage-row2-input', 'coverage-row7-output', 'coverage-FS1-output'])
def test_frontend_machine_reader_retains_canonical_input_output_refusals(
        tmp_path, monkeypatch, document, row, field, required):
    """Consume checked-in data first; a missing canonical entry stays refused."""
    catalog, coverage = p._machine_contracts()
    current = p.coverage()[row]
    assert required in current['input_contract' if field == 'inputs' else 'output_contract']
    documents = {'catalog': catalog, 'coverage': coverage}
    changed = json.loads(json.dumps(documents[document]))
    changed['contracts'][row][field].remove(required)
    paths = {}
    for name, payload in documents.items():
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(changed if name == document else payload))
        paths[name] = path
    monkeypatch.setattr(p, '_CATALOG_PATH', paths['catalog'])
    monkeypatch.setattr(p, '_COVERAGE_PATH', paths['coverage'])
    try:
        p.coverage()
        refusal = None
    except ValueError as exc:
        refusal = str(exc)
    observed = {'scope': 'Actual machine-contract reader; neutral copied data, no EDA/70-row claim',
                'document': document, 'row': row, 'field': field, 'removed': required,
                'current_contract': documents[document]['contracts'][row], 'refusal': refusal}
    (tmp_path / 'catalog_contract_observed.json').write_text(json.dumps(observed, indent=2) + '\n')
    assert refusal == ('frontend catalog is out of sync with source routes' if document == 'catalog'
                       else 'frontend coverage is out of sync with source rows'), observed

"""Current ordinary Default source controls. Substituted processes are SOURCE_FIXTURE_ONLY."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
from _hostpaths import require_repo
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
import phase3_one_shot_runner as R
import spice_correlation_check as SC
import path_spice_tool as PST

SPEF = '''*SPEF "IEEE 1481-1998"
*DESIGN "neutral"
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER [ ]
*D_NET a 0.02
*CONN
*I u0:Z O
*I u2:A I
*CAP
1 u0:Z 0.01
2 u0:Z u1:Z 0.01
*RES
1 u0:Z u2:A 10
*END
*D_NET b 0.02
*CONN
*I u1:Z O
*P z O
*CAP
1 u1:Z 0.01
2 u1:Z u0:Z 0.01
*RES
1 u1:Z z 10
*END
'''
NETLIST = 'module neutral(input x, y, output z); wire a,b; BUF u0(.A(x),.Z(a)); BUF u1(.A(y),.Z(b)); BUF u2(.A(a),.Z(z)); endmodule\n'
POWER = '''OpenSTA report_power
Group                    Internal    Switching      Leakage        Total
                            Power        Power        Power        Power (Watts)
------------------------------------------------------------------------
Sequential           0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Combinational        1.000000e-03 1.000000e-03 1.000000e-06 2.001000e-03 100.0%
Clock                0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Macro                0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Pad                  0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
------------------------------------------------------------------------
Total                1.000000e-03 1.000000e-03 1.000000e-06 2.001000e-03 100.0%
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path

def seal(folder, fp):
    put(folder / 'input_fingerprint.json', fp)
    put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': {
        str(p.relative_to(folder)): LC.digest(p) for p in folder.rglob('*')
        if p.is_file() and p.name != 'vibeic_receipt.json'}})

def project(tmp_path, *, corner='nom_typ', liberty_name='neutral.lib'):
    p = tmp_path / 'p'
    nl = write(p / 'phase3/stage3/pnr/neutral_pnr.v', NETLIST)
    spef = write(p / 'phase3/stage3/extracted/neutral.spef', SPEF)
    sdc = write(nl.parent / 'constraint.sdc', 'create_clock -name c -period 10\nset_input_delay 1 -clock c [get_ports {x y}]\nset_output_delay 1 -clock c [get_ports z]\n')
    views = {'nl': str(nl), 'sdc': str(sdc), 'spef': {'*': str(spef)}, 'metrics': {}}
    folder, _ = BF.producer(p, 'OpenROAD.STAPostPNR', views, views,
                           lane='22-23/01-openroad-stapostpnr', config_folder='22-config', name='neutral')
    library = 'neutral_typ' if liberty_name == 'neutral.lib' else 'neutral_' + Path(liberty_name).stem
    lib = write(p / 'fixture_pdk/neutral' / liberty_name,
                f'library({library}) {{ default_operating_conditions: typ; }}\n')
    guest = '/pdk/neutral/' + liberty_name
    write(folder / corner / 'sta.log', f"SOURCE_FIXTURE_ONLY\nReading cell library for the '{corner}' corner at '{guest}'\n")
    write(folder / corner / 'power.rpt', POWER)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    raw = json.loads(config.read_text())
    raw['CELL_LIBS'] = {'*': [guest]}
    put(config, raw)
    put(folder / 'config.json', raw)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config)
    fp['config_files'] = {guest: LC.digest(lib)}
    fp['liberty_files'] = {guest: LC.digest(lib)}
    seal(folder, fp)
    put(p / LP.STEP23_RECORD, {'sta_state': str(folder / 'state_out.json'),
                              'sta_state_sha256': LC.digest(folder / 'state_out.json'),
                              'judgment': {'worst_setup': {'corner': corner}}})
    return p, folder, lib

def pdk(lib):
    return SimpleNamespace(name='neutral', liberty=str(lib), macro_libs=[], macro_lefs=[],
                           tech_lef='', cell_lef='')

def test_step30_copied_correlation_cannot_certify_without_execution(tmp_path):
    p, folder, lib = project(tmp_path)
    write(p / 'phase3/stage3/spice/correlation.spice', '* copied deck\n.end\n')
    put(p / 'reports/phase3/spice_correlation.json', {'correlation': {
        'liberty_spef_cone_delay_ns': 1, 'spice_path_delay_ns': 1,
        'pct_error': 0, 'tolerance_pct': 10, 'verdict': 'CORRELATED'}})
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 1

def spice_produce(p, folder, lib, monkeypatch, *, verdict='PASS'):
    write(p / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp', '.model neutral nmos level=1\n')
    write(p / 'fixture_pdk/neutral/libs.tech/magic/neutral.magicrc', '# SOURCE_FIXTURE_ONLY Magic rules\n')
    write(p / 'fixture_pdk/neutral/libs.tech/librelane/config.tcl', '# SOURCE_FIXTURE_ONLY PDK declaration\n')
    def run(project, image, root, pdk_name, **kwargs):
        detail = {}
        for variant in ('base', 'mutated'):
            directory = p / 'phase3/tool_arms/30/ngspice' / variant
            script = write(directory / 'arm.tcl', 'read_spef current\nwrite_path_spice\n')
            sta_log = write(directory / 'sta.log', 'SOURCE_FIXTURE_ONLY OpenSTA write_path_spice\n')
            deck = write(directory / 'path_1.sp', '* SOURCE_FIXTURE_ONLY tool deck\n.end\n')
            runnable = write(directory / 'path_1.run.sp', '* SOURCE_FIXTURE_ONLY simulator deck\n.end\n')
            sim_log = write(directory / 'path_1.log', 'SOURCE_FIXTURE_ONLY measured 1 ns\n')
            for name in ('path_1.wave', 'path_1.rpt', 'path_1.run.subckt', 'models_ngspice.sp'):
                write(directory / name, 'SOURCE_FIXTURE_ONLY ' + name + '\n')
            detail[variant] = {'sta_execution': {'tool': 'OpenSTA', 'rc': 0,
                'argv': ['sta', '-exit', str(script)], 'script': str(script), 'log': str(sta_log)},
                'paths': [{'deck': str(deck), 'status': 'MEASURED', 'spice_ns': 1,
                    'simulator_execution': {'tool': 'ngspice', 'rc': 0,
                        'argv': ['ngspice', '-b', str(runnable)],
                        'script': str(runnable), 'log': str(sim_log)}}]}
        doc = {'step': '30', 'corner': 'nom_typ', 'verdict': verdict,
               'arms': {'ngspice': {'verdict': 'CORRELATED' if verdict == 'PASS' else 'MISMATCH'}},
               'detail': {'ngspice': detail}}
        put(p / 'reports/phase3/spice_path_tool.json', doc)
        return doc
    monkeypatch.setattr(PST, 'run_step30', run)
    monkeypatch.setattr(LC, 'resolve_image', lambda *a, **k: BF.IMAGE)
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *a, **k: {'path': str(p / 'fixture_pdk')})
    return SC.run_installed_pdk_path_correlation(p, str(lib))

def test_step30_ordinary_caller_adopts_the_existing_tool_product(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    result = spice_produce(p, folder, lib, monkeypatch)
    assert result['status'] == 'RAN', result
    assert SC.main([str(p), '--json', str(p / 'spice-gate.json')]) == 0
    assert (p / 'phase3/stage3/spice/correlation.spice').read_bytes() == (p / 'phase3/tool_arms/30/ngspice/base/path_1.sp').read_bytes()

@pytest.mark.parametrize('mutation', ['netlist', 'spef', 'sdc', 'liberty', 'corner', 'models',
    'execution', 'report_replay', 'wrong_project', 'wrong_stage', 'wrong_path', 'consumption',
    'declared_result', 'waveform', 'path_report', 'subckt', 'generated_models',
    'magicrc', 'pdk_flow_config', 'execution_identity'])
def test_step30_gate_refuses_current_byte_and_consumer_mutations(tmp_path, monkeypatch, mutation):
    p, folder, lib = project(tmp_path)
    assert spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 0
    if mutation == 'declared_result':
        (p / 'phase3/stage3/spice/correlation.json').unlink()
    elif mutation in ('netlist', 'spef', 'sdc', 'liberty', 'models'):
        path = {'netlist': p / 'phase3/stage3/pnr/neutral_pnr.v',
                'spef': p / 'phase3/stage3/extracted/neutral.spef',
                'sdc': p / 'phase3/stage3/pnr/constraint.sdc', 'liberty': lib,
                'models': p / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp'}[mutation]
        path.write_text(path.read_text() + '\n ')
    elif mutation == 'corner':
        path = p / LP.STEP23_RECORD
        doc = json.loads(path.read_text())
        doc['judgment']['worst_setup']['corner'] = 'other'
        put(path, doc)
    elif mutation == 'execution':
        (p / 'phase3/tool_arms/30/ngspice/base/path_1.log').unlink()
    elif mutation == 'report_replay':
        path = p / 'reports/phase3/spice_path_tool.json'
        path.write_text(path.read_text() + '\n ')
    elif mutation in ('waveform', 'path_report', 'subckt', 'generated_models'):
        name = {'waveform': 'path_1.wave', 'path_report': 'path_1.rpt',
                'subckt': 'path_1.run.subckt', 'generated_models': 'models_ngspice.sp'}[mutation]
        path = p / 'phase3/tool_arms/30/ngspice/base' / name
        path.write_text(path.read_text() + '\n ')
    elif mutation in ('magicrc', 'pdk_flow_config'):
        relative = 'magic/neutral.magicrc' if mutation == 'magicrc' else 'librelane/config.tcl'
        path = p / 'fixture_pdk/neutral/libs.tech' / relative
        path.write_text(path.read_text() + '\n ')
    else:
        path = p / 'reports/phase3/spice_correlation.current.json'
        doc = json.loads(path.read_text())
        if mutation == 'wrong_project':
            doc['project'] = str(tmp_path / 'other')
        elif mutation == 'wrong_stage':
            doc['stage'] = 'pre_layout'
        elif mutation == 'wrong_path':
            doc['outputs'][0]['path'] = str(tmp_path / 'outside.sp')
        elif mutation == 'execution_identity':
            doc['execution'][0]['argv'][0] = 'foreign_tool'
        else:
            doc['outputs'] = []
        put(path, doc)
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 1

def test_step30_current_measured_fail_is_still_fail(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    result = spice_produce(p, folder, lib, monkeypatch, verdict='FAIL')
    assert result['status'] == 'RAN'
    assert SC.main([str(p), '--json', str(p / 'spice-gate.json')]) == 1
    assert json.loads((p / 'spice-gate.json').read_text())['summary']['measurement'] == 'MEASURED'

def bounded_step30_caller():
    """Execute the actual Step30 caller block and its existing StepResult exit.

    Unrelated physical steps are outside this declared source fixture. Both
    the frozen parent's caller and the candidate's caller can run this slice.
    """
    import ast
    import inspect
    import textwrap
    source = inspect.getsource(R.step_canonicalize_artefacts)
    start = next(source.index(marker) for marker in (
        '    # Step 30 is BLOCKING:', '    # T106: step 30\'s tool arm') if marker in source)
    block = source[start:source.index('    # --- Step 32b:', start)]
    function = ast.parse(source).body[0]
    stop = next(node for node in function.body if isinstance(node, ast.If)
                and isinstance(node.test, ast.Name) and node.test.id == 'signoff_failures')
    success = function.body[function.body.index(stop) + 1]
    exits = ast.unparse(ast.Module(body=[stop, success], type_ignores=[]))
    body = ('t0 = time.time()\nwritten = []\nnotes = []\nsignoff_failures = []\n'
            + textwrap.dedent(block) + '\n' + exits)
    namespace = dict(vars(R))
    exec('def bounded(project, pdk, container=""):\n' + textwrap.indent(body, '    '), namespace)
    return namespace['bounded']

@pytest.mark.parametrize('verdict', ['PASS', 'FAIL'])
def test_step30_ordinary_phase3_caller_consumes_declared_gate_and_blocks(tmp_path, monkeypatch, verdict):
    import yaml
    flow = yaml.safe_load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'phase1_phase2_phase3.yaml').read_text())
    row = next(row for row in flow['steps'] if str(row['id']) == '30')
    command = next(clause['program_exit_zero'] for clause in row['gate']['all_of']
                   if 'program_exit_zero' in clause)
    assert command.startswith('spice_correlation_check . --json ')
    p, folder, lib = project(tmp_path)
    # A pre-existing report deliberately exercises the parent's presence bypass.
    assert spice_produce(p, folder, lib, monkeypatch, verdict=verdict)['status'] == 'RAN'
    calls = []
    producer, consumer = SC.run_installed_pdk_path_correlation, SC.main
    def produce(*args, **kwargs):
        calls.append('producer')
        return producer(*args, **kwargs)
    def consume(*args, **kwargs):
        calls.append('consumer')
        return consumer(*args, **kwargs)
    monkeypatch.setattr(SC, 'run_installed_pdk_path_correlation', produce)
    monkeypatch.setattr(SC, 'main', consume)
    result = bounded_step30_caller()(p, pdk(lib))
    assert result.status == verdict, result
    assert calls == ['producer', 'consumer']
    gate = json.loads((p / command.split('--json ')[1]).read_text())
    assert gate['summary']['measurement'] == 'MEASURED'
    assert gate['summary']['verdict'] == verdict
    assert gate['passed'] == (verdict == 'PASS')

def test_step30_ordinary_phase3_caller_blocks_current_subject_drift(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    assert spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    producer = SC.run_installed_pdk_path_correlation
    def produce(*args, **kwargs):
        result = producer(*args, **kwargs)
        path = p / 'phase3/stage3/extracted/neutral.spef'
        path.write_text(path.read_text() + '\n ')
        return result
    monkeypatch.setattr(SC, 'run_installed_pdk_path_correlation', produce)
    result = bounded_step30_caller()(p, pdk(lib))
    assert result.status == 'FAIL', result
    gate = json.loads((p / 'reports/phase2/gates/spice_correlation.json').read_text())
    assert gate['summary']['current_binding'] == 'REFUSED'

def test_step30_ordinary_phase3_refusal_retires_previous_current_pass(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    assert spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    def absent_image(*args, **kwargs):
        raise LC.Refusal('LL_IMAGE_ABSENT', 'SOURCE_FIXTURE_ONLY native image unavailable')
    monkeypatch.setattr(LC, 'resolve_image', absent_image)
    result = bounded_step30_caller()(p, pdk(lib))
    assert result.status == 'FAIL', result
    report = json.loads((p / 'reports/phase3/spice_correlation.json').read_text())
    assert report['verdict'] == 'NOT_MEASURED'
    assert not (p / 'reports/phase3/spice_correlation.current.json').exists()
    assert not (p / 'phase3/stage3/spice/correlation.spice').exists()


def _current_backend_step30(project, lib, monkeypatch, *, mode='default', simulators=None):
    import execution_backend_producers as backend
    import phase3_one_shot_runner as runner
    monkeypatch.setattr(backend, '_parameters',
                        lambda *_: (runner, None, pdk(lib), 'SOFTWARE_FIXTURE_ONLY'))
    params = {'step_id': '30', 'top': 'neutral', 'image_id': BF.IMAGE,
              'pdk_root': str(project / 'fixture_pdk')}
    if mode is not None:
        params['execution_mode'] = mode
    if simulators is not None:
        params['simulators'] = simulators
    return backend.produce_signoff(project, params)


@pytest.mark.parametrize('kind,expected', [('CORRELATED', 'PASS'), ('MISMATCH', 'FAIL'),
                                           ('CRITICAL_MISMATCH', 'FAIL')])
@pytest.mark.parametrize('mode', ['default', None], ids=['default', 'unspecified-default'])
def test_backend_step30_uses_the_current_producer_and_preserves_its_product(
        tmp_path, monkeypatch, kind, expected, mode):
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib = project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch=kind, companion='success')
    # Setup supplies native-input-shaped files and substituted process transport.
    # No existing result may stand in for this backend invocation.
    for name in ('reports/phase3/spice_correlation.current.json',
                 'reports/phase3/spice_correlation.json',
                 'phase3/stage3/spice/correlation.json'):
        (p / name).unlink(missing_ok=True)
    actual = PST.run_current_step30
    calls = []
    def observed(*args, **kwargs):
        calls.append(args[0])
        return actual(*args, **kwargs)
    monkeypatch.setattr(PST, 'run_current_step30', observed)
    result = _current_backend_step30(p, lib, monkeypatch, mode=mode)
    assert calls == [p], 'the backend must invoke the current producer once'
    assert result['verdict'] == expected, result
    native = json.loads((p / 'reports/phase3/spice_correlation.json').read_text())
    assert native == json.loads((p / 'phase3/stage3/spice/correlation.json').read_text())
    assert native['verdict'] == expected and 'detail' in native and 'summary' not in native
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED'
    assert gate.summary['verdict'] == expected
    assert gate.passed is (expected == 'PASS')
    published = json.loads((p / 'reports/phase2/gates/spice_correlation.json').read_text())
    assert published['summary']['current_binding'] == 'CURRENT'
    assert published['summary']['verdict'] == expected


def test_backend_step30_digital_pass_cannot_hide_an_uncovered_analog_module(tmp_path, monkeypatch):
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib = project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    write(p / 'phase2/stage1/rtl/adc_helper.sv', 'module adc_helper; endmodule\n')
    result = _current_backend_step30(p, lib, monkeypatch)
    assert result['verdict'] == 'FAIL', result
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['correlation_verdict'] == 'PASS'
    assert gate.summary['measurement'] == 'MEASURED'
    assert gate.summary['verdict'] == 'FAIL' and not gate.passed
    assert any(f.rule == 'ANALOG_SPICE_MISSING' for f in gate.findings)


def test_backend_step30_current_refusal_cannot_reuse_an_earlier_pass(tmp_path, monkeypatch):
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib = project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    assert SC.run_installed_pdk_path_correlation(p, str(lib))['status'] == 'RAN'
    def refuse(*_args, **_kwargs):
        raise LC.Refusal('CURRENT_STEP30_EXECUTION_MISSING', 'SOFTWARE_FIXTURE_ONLY transport refused')
    monkeypatch.setattr(PST, 'run_current_step30', refuse)
    result = _current_backend_step30(p, lib, monkeypatch)
    assert result['verdict'] == 'NOT_MEASURED', result
    assert not (p / 'reports/phase3/spice_correlation.current.json').exists()
    declared = json.loads((p / 'reports/phase3/spice_correlation.json').read_text())
    assert declared['verdict'] == 'NOT_MEASURED' and declared['correlation_ran'] is False
    assert declared == json.loads((p / 'phase3/stage3/spice/correlation.json').read_text())
    assert declared == json.loads((p / 'phase3/stage3/spice/spice_correlation_not_run.json').read_text())
    gate = SC.run_audit(p, run_spice=False)
    assert not gate.passed and gate.summary['measurement'] == 'NOT_MEASURED'


@pytest.mark.parametrize('simulators', [('xyce',), ('ngspice', 'xyce')])
def test_backend_default_step30_cannot_silently_change_the_requested_instrument(
        tmp_path, monkeypatch, simulators):
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib = project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('unqualified current provider must not run another instrument')
    monkeypatch.setattr(PST, 'run_step30', forbidden)
    monkeypatch.setattr(PST, 'run_current_step30', forbidden)
    result = _current_backend_step30(p, lib, monkeypatch, simulators=simulators)
    assert result['verdict'] == 'NOT_MEASURED', result
    assert result['detail'] == 'BACKEND_CURRENT_STEP30_PROVIDER_UNQUALIFIED: ' + repr(simulators)


@pytest.mark.parametrize('kind,expected', [('CORRELATED', 'PASS'), ('MISMATCH', 'FAIL'),
                                         ('REFUSED', 'NOT_MEASURED')])
def test_default_row_loop_consumes_current_step30_and_stops_on_failure(
        tmp_path, monkeypatch, kind, expected):
    import execution_backend_producers as backend
    import flow_compliance_check as compliance
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib = project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED' if kind == 'REFUSED' else kind,
                                     companion='success')
    if kind == 'REFUSED':
        def refuse(*_args, **_kwargs):
            raise LC.Refusal('CURRENT_STEP30_EXECUTION_MISSING', 'SOFTWARE_FIXTURE_ONLY refusal')
        monkeypatch.setattr(PST, 'run_current_step30', refuse)
    cfg = pdk(lib)
    monkeypatch.setattr(backend, '_parameters', lambda *_: (R, None, cfg, 'SOFTWARE_FIXTURE_ONLY'))
    monkeypatch.setattr(R, '_backend_parameter_values', lambda *_: {
        'pdk_root': str(p / 'fixture_pdk'), 'image_id': BF.IMAGE})
    actual_producer = backend.produce
    called = []
    def observed(project_path, params):
        called.append(params['step_id'])
        assert params['step_id'] == '30', 'a failed Step30 must not start the following producer'
        return actual_producer(project_path, params)
    monkeypatch.setattr(backend, 'produce', observed)
    # Substitute process transport only; the runner, producer, canonical gate,
    # ledger, contract resolver, and retained output collector remain real.
    import contextlib
    import io
    actual_transport = compliance._watchdog.run_host_supervised
    consumed = []
    def gate_transport(argv, **kwargs):
        if Path(argv[1]).name != 'spice_correlation_check.py':
            return actual_transport(argv, **kwargs)
        consumed.append(argv[1])
        stdout, stderr = io.StringIO(), io.StringIO()
        with monkeypatch.context() as transport_context:
            transport_context.chdir(kwargs['cwd'])
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = SC.main(argv[2:])
        return compliance._watchdog.SupervisedResult(
            rc=rc, out=stdout.getvalue(), err=stderr.getvalue(), outcome='natural')
    monkeypatch.setattr(compliance._watchdog, 'run_host_supervised', gate_transport)
    ids = ['30'] if expected == 'PASS' else ['30', '33']
    row = R._default_pnr_rows(p, 'neutral', cfg, 'SOFTWARE_FIXTURE_ONLY', ids)
    assert called == ['30']
    assert row.status == expected, row.detail
    receipt = json.loads((p / 'reports/phase3/default_steps/30/backend_result.json').read_text())
    assert receipt['verdict'] == expected
    if expected == 'PASS':
        assert len(consumed) == 1
        assert any(entry['gate'] == 'spice_correlation_check'
                   for entry in receipt['gate_ledger'])
        native = receipt['current_step_declared_producers']
        assert 'reports/phase3/sta_postpnr_signoff.json' in native['inputs']
        assert 'phase3/stage3/extracted/neutral.spef' in native['inputs']
    if expected != 'NOT_MEASURED':
        gate = SC.run_audit(p, run_spice=False)
        assert gate.summary['current_binding'] == 'CURRENT'
        assert gate.summary['measurement'] == 'MEASURED'
        assert gate.summary['verdict'] == expected


@pytest.mark.parametrize('missing', ['reports/phase3/sta_postpnr_signoff.json',
                                    'phase3/stage3/extracted/neutral.spef'])
def test_default_step30_missing_current_input_stops_before_producer(tmp_path, monkeypatch, missing):
    import execution_backend_producers as backend
    p, folder, lib = project(tmp_path)
    (p / missing).unlink()
    def forbidden(*_args, **_kwargs):
        raise AssertionError('missing current input must be reported before the native tool starts')
    monkeypatch.setattr(backend, 'produce', forbidden)
    row = R._default_pnr_rows(p, 'neutral', pdk(lib), 'SOFTWARE_FIXTURE_ONLY', ['30', '33'])
    assert row.status == 'NOT_MEASURED', row.detail
    assert 'missing current inputs' in row.detail
    assert missing in row.detail or ('*.spef' in row.detail and missing.endswith('.spef'))


@pytest.mark.parametrize('mode', ['default', 'direct', 'librelane', 'dual',
                                 'foreign-default', 'invalid'])
def test_step23_native_output_follows_the_current_producer(tmp_path, monkeypatch, mode):
    import execution_policy as policy
    import execution_backend_gates as gates
    import execution_modes as modes
    import flow_compliance_check as compliance
    import yaml
    flow = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow',
                        'phase1_phase2_phase3.yaml')
    row = next(row for row in yaml.safe_load(flow.read_text())['steps'] if row['id'] == 23)
    record = 'reports/phase3/sta_postpnr_signoff.json'
    assert record in row['required_outputs']
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    monkeypatch.delenv(policy.ENV, raising=False)
    monkeypatch.delenv(policy._CAPABILITY_FD_ENV, raising=False)
    # Even an explicit direct switch cannot change Default's actual backend.
    selected = 'direct' if mode in ('default', 'foreign-default') else mode
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'23': selected}})
    if mode == 'default':
        policy.bootstrap(tmp_path)
    elif mode == 'foreign-default':
        foreign = tmp_path / 'other'
        foreign.mkdir()
        policy.bootstrap(foreign)
    owed = mode in ('default', 'librelane', 'dual', 'invalid')
    reason = compliance._output_not_owed(tmp_path, row, record)
    assert (reason is None) is owed
    # Exercise both existing output consumers with the same canonical
    # declaration, leaving the unrelated Step23 timing gates out of this case.
    observed = dict(row, required_outputs=[record], programs=[], gate={})
    audited = compliance.check_step(tmp_path, observed, {})
    assert audited.output_binding['not_owed'] == ([] if owed else [record])
    if owed:
        assert audited.status == 'FAIL'
        assert f"no required_outputs found (expected: ['{record}'])" in audited.reasons
        with pytest.raises(modes.Refusal, match='BACKEND_SUBSTANTIVE_CONTRACT_MISSING'):
            gates.contracts(tmp_path, observed)
        put(tmp_path / record, {'fixture': 'SOURCE_FIXTURE_ONLY'})
        assert record in gates.contracts(tmp_path, observed)
    else:
        assert 'NOT_APPLICABLE' in reason and gates.contracts(tmp_path, observed) == {}


def test_legacy_direct_sta_does_not_excuse_step30_current_input(tmp_path, monkeypatch):
    import execution_backend_producers as backend
    p, folder, lib = project(tmp_path)
    switch = p / 'phase3/librelane_switch.json'
    declaration = json.loads(switch.read_text())
    declaration.setdefault('steps', {})['23'] = 'direct'
    put(switch, declaration)
    (p / 'reports/phase3/sta_postpnr_signoff.json').unlink()
    def forbidden(*args, **kwargs):
        raise AssertionError('no native launch without the Step30 STA input')
    monkeypatch.setattr(backend, 'produce', forbidden)
    row = R._default_pnr_rows(p, 'neutral', pdk(lib), 'SOURCE_FIXTURE_ONLY', ['30'])
    assert row.status == 'NOT_MEASURED'
    assert 'missing current inputs' in row.detail
    assert 'sta_postpnr_signoff.json' in row.detail

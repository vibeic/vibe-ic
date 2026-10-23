"""Current ordinary Default source controls. Substituted processes are SOURCE_FIXTURE_ONLY."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_librelane_contract import local_image  # noqa: F401
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
                f'library({library}) {{\n nom_voltage : 1.8;\n default_operating_conditions: typ;\n}}\n')
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

def current_row_inputs(project, monkeypatch):
    # The real Default issuer binds these original inputs in addition to the
    # row's STA/SPEF contract. They are neutral source documents, not verdicts.
    put(project / 'input/step_0_5ic_answers.json', {})
    put(project / 'input/submission_template/neutral.json', {'scope': 'SOURCE_FIXTURE_ONLY'})
    # This module substitutes native process transport and states a synthetic
    # image. Do not ask the actual LOCAL CID to attest that invented image.
    monkeypatch.setattr(R, '_backend_parameter_values', lambda *_: {
        'pdk_root': str(project / 'fixture_pdk'), 'image_id': BF.IMAGE})


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
    current_row_inputs(p, monkeypatch)
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
    current_row_inputs(p, monkeypatch)
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
    current_row_inputs(p, monkeypatch)
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


def selected_path_transport(p, folder, lib, monkeypatch, *, available=3, mismatch_path=None):
    """Extend the existing neutral executor substitute, without replacing consumers.

    The finite requested count is a maximum. All path values and execution
    records here are SOFTWARE_FIXTURE_ONLY, never native measurements.
    """
    import copy
    import test_step30_r4_current_failures as current_fixture
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    substitute = PST.run_step30
    captured = []

    def run(project, image, root, pdk_name, **kwargs):
        requested = kwargs['paths']
        captured.append(requested)
        doc = substitute(project, image, root, pdk_name, **kwargs)
        arm = doc['detail']['ngspice']
        for variant in ('base', 'mutated'):
            data = arm[variant]
            prototype = data['paths'][0]
            directory = Path(prototype['deck']).parent
            rows = []
            for index in range(1, min(requested, available) + 1):
                row = copy.deepcopy(prototype)
                row.update(path=index, startpoint=f'launch_{index}', endpoint=f'capture_{index}')
                if index > 1:
                    for source in sorted(directory.glob('path_1*')):
                        target = directory / source.name.replace('path_1', f'path_{index}', 1)
                        target.write_bytes(source.read_bytes())
                    row['deck'] = str(directory / f'path_{index}.sp')
                    execution = row['simulator_execution']
                    for key in ('script', 'log'):
                        execution[key] = execution[key].replace('path_1', f'path_{index}')
                    execution['argv'] = [arg.replace('path_1', f'path_{index}')
                                         for arg in execution['argv']]
                if index == mismatch_path:
                    row.update(spice_ns=row['sta_ns'] * 1.15, error_pct=15.0, verdict='MISMATCH')
                rows.append(row)
            data['paths'] = rows
        judgment = PST.judge(arm['base'], arm['mutated'])
        doc.update(arms={'ngspice': judgment},
                   **PST.step_verdict({'ngspice': judgment}, {'ngspice': arm['base']['paths']}))
        put(p / 'reports/phase3/spice_path_tool.json', doc)
        print('SOURCE70_OBSERVATION=' + json.dumps({
            'scope': 'SOFTWARE_FIXTURE_ONLY', 'requested_at_executor': requested,
            'available_paths': available, 'selected_paths': len(arm['base']['paths']),
            'verdict': doc['verdict']}))
        return doc

    monkeypatch.setattr(PST, 'run_step30', run)
    return captured


def requested_backend_step30(p, lib, monkeypatch, *, requested=None, mode='default'):
    import execution_adapters_backend as adapter
    import execution_backend_producers as backend
    monkeypatch.setattr(backend, '_parameters',
                        lambda *_: (R, None, pdk(lib), 'SOFTWARE_FIXTURE_ONLY'))
    supplied = {'top': 'neutral', 'image_id': BF.IMAGE, 'pdk_root': str(p / 'fixture_pdk')}
    if requested is not None:
        supplied['spice_paths'] = requested
    params = adapter._typed_parameters({'step_id': '30'}, 'fixture-source', supplied)
    params['step_id'] = '30'
    if mode is not None:
        params['execution_mode'] = mode
    return backend.produce_signoff(p, params)


@pytest.mark.parametrize('mode', ['default', None], ids=['default', 'unspecified-default'])
@pytest.mark.parametrize('requested,available', [(None, 3), (1, 3), (3, 3), (3, 1)],
                         ids=['omitted-one', 'explicit-one', 'requested-three', 'three-maximum-one-available'])
def test_backend_step30_delivers_requested_path_population(tmp_path, monkeypatch, requested, available, mode):
    p, folder, lib = project(tmp_path)
    captured = selected_path_transport(p, folder, lib, monkeypatch, available=available)
    result = requested_backend_step30(p, lib, monkeypatch, requested=requested, mode=mode)
    assert captured == [requested or 1], f'executor received {captured}; requested {requested or 1}'
    assert result['verdict'] == 'PASS', result
    gate = SC.run_audit(p, run_spice=False)
    assert gate.passed and gate.summary['current_binding'] == 'CURRENT', gate.summary
    doc = json.loads((p / 'reports/phase3/spice_path_tool.json').read_text())
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    named = {row['deck'] for variant in ('base', 'mutated')
             for row in doc['detail']['ngspice'][variant]['paths']}
    bound = {row['path'] for row in receipt['outputs'] if row['role'].startswith('deck:')}
    assert len(named) == 2 * min(requested or 1, available) and bound == named
    canonical = p / 'phase3/stage3/spice/correlation.spice'
    assert canonical.read_bytes() == (p / 'phase3/tool_arms/30/ngspice/base/path_1.sp').read_bytes()
    for path in named:
        assert any(row['path'] == path and row['role'].startswith('product:')
                   for row in receipt['outputs'])


def test_backend_nondefault_step30_preserves_requested_path_population(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    captured = selected_path_transport(p, folder, lib, monkeypatch)
    requested_backend_step30(p, lib, monkeypatch, requested=3, mode='ultra')
    assert captured == [3]


def test_backend_step30_selected_third_path_mismatch_stays_fail(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    captured = selected_path_transport(p, folder, lib, monkeypatch, mismatch_path=3)
    result = requested_backend_step30(p, lib, monkeypatch, requested=3)
    assert captured == [3], captured
    assert result['verdict'] == 'FAIL', result
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED' and not gate.passed
    assert gate.summary['arms']['ngspice']['worst_path'] == 3


@pytest.mark.parametrize('filename', ['path_3.sp', 'path_3.wave', 'path_3.run.subckt'])
def test_backend_step30_selected_third_path_byte_drift_is_refused(tmp_path, monkeypatch, filename):
    p, folder, lib = project(tmp_path)
    captured = selected_path_transport(p, folder, lib, monkeypatch)
    result = requested_backend_step30(p, lib, monkeypatch, requested=3)
    assert captured == [3], captured
    assert result['verdict'] == 'PASS', result
    target = p / 'phase3/tool_arms/30/ngspice/base' / filename
    target.write_text(target.read_text() + '\nSOFTWARE_FIXTURE_ONLY byte drift\n')
    gate = SC.run_audit(p, run_spice=False)
    assert not gate.passed and gate.summary['current_binding'] == 'REFUSED', gate.summary
    assert gate.summary['measurement'] == 'NOT_MEASURED'


@pytest.mark.parametrize('site', ['retained_paths', 'rcx_handoff'])
def test_backend_absence_diagnostics_name_inspected_scope(tmp_path, monkeypatch, site):
    import execution_backend_producers as backend
    p, folder, lib = project(tmp_path)
    if site == 'retained_paths':
        private = tmp_path / 'private'
        missing = private / 'phase3/tool_arms/30/ngspice/base/absent.sp'
        inspected = p / 'phase3/tool_arms/30/ngspice/base/absent.sp'
        code = 'STEP30_RETAINED_ARTIFACT_ABSENT'
        with pytest.raises(backend.em.Refusal) as caught:
            backend._step30_retain_document(p, private, 'ngspice', {'deck': str(missing)})
    else:
        inspected = p / 'reports/phase3/librelane_rcx_handoff.json'
        code = 'BACKEND_CURRENT_RCX_HANDOFF_ABSENT'
        monkeypatch.setattr(backend, '_parameters',
                            lambda *_: (R, None, pdk(lib), 'SOFTWARE_FIXTURE_ONLY'))
        with pytest.raises(backend.em.Refusal) as caught:
            backend.produce_signoff(p, {'step_id': '23', 'top': 'neutral',
                'pdk_root': str(p / 'fixture_pdk'), 'image_id': BF.IMAGE})
    assert caught.value.code == code
    assert str(inspected) in str(caught.value), str(caught.value)
    assert 'inspected' in str(caught.value), str(caught.value)


@pytest.mark.parametrize('missing', ['pdk', 'container', 'spef'])
def test_si_basis_absence_diagnostic_names_supplied_keys(tmp_path, missing):
    p, folder, lib = project(tmp_path)
    arguments = {'pdk': pdk(lib), 'container': 'SOFTWARE_FIXTURE_ONLY',
                 'spef': p / 'phase3/stage3/extracted/neutral.spef'}
    arguments[missing] = None
    report = p / 'reports/phase3/si_crosstalk.rpt'
    assert not R._emit_si_crosstalk_report(p, 'neutral', arguments.pop('spef'),
                                          report.parent / 'ir_drop.rpt', report, [], **arguments)
    body = json.loads(report.with_suffix('.json').read_text())
    assert body['verdict'] == 'NOT_MEASURED'
    reason = body['current_input_reason']
    assert reason.startswith('CURRENT_SI_BASIS_MISSING'), reason
    assert f'{missing}=None' in reason and 'supplied arguments' in reason, reason
    assert not report.with_suffix('.current.json').exists()


def test_si_producer_import_absence_diagnostic_names_import_search(tmp_path, monkeypatch):
    import importlib
    p, folder, lib = project(tmp_path)
    actual_import = importlib.import_module
    attempted = []
    def absent(name, *args, **kwargs):
        if name == 'si_signoff_timing_aware':
            attempted.append(name)
            raise ModuleNotFoundError('SOFTWARE_FIXTURE_ONLY optional import refused')
        return actual_import(name, *args, **kwargs)
    monkeypatch.setattr(importlib, 'import_module', absent)
    notes = []
    extracted = p / 'phase3/stage3/extracted'
    assert not R._emit_si_timing_json(p, 'neutral', pdk(lib), 'SOFTWARE_FIXTURE_ONLY',
        extracted / 'neutral.spef', p / 'phase3/stage3/pnr/constraint.sdc',
        p / 'phase3/stage3/pnr/neutral_pnr.v', extracted / 'neutral_si_timing.json', notes)
    assert attempted == ['si_signoff_timing_aware'], notes
    reason = '\n'.join(notes)
    assert 'CURRENT_SI_TIMING_PRODUCER_MISSING' in reason
    assert 'si_signoff_timing_aware' in reason and 'sys.path' in reason, reason


def test_si_coupling_absence_diagnostic_names_selected_spef(tmp_path, monkeypatch):
    import _opensta_current as current
    p, folder, lib = project(tmp_path)
    actual_subject = current.tool_subject
    selected = p / 'phase3/stage3/extracted/neutral.spef'
    def remove_coupling_after_validation(*args, **kwargs):
        # Exercise the existing second read with real, previously validated
        # input. This public inter-read mutation is only a refusal control.
        result = actual_subject(*args, **kwargs)
        text = selected.read_text()
        selected.write_text(text.replace('2 u0:Z u1:Z 0.01\n', '')
                                .replace('2 u1:Z u0:Z 0.01\n', ''))
        return result
    monkeypatch.setattr(current, 'tool_subject', remove_coupling_after_validation)
    report = p / 'reports/phase3/si_crosstalk.rpt'
    assert not R._emit_si_crosstalk_report(p, 'neutral', selected,
        report.parent / 'ir_drop.rpt', report, [], pdk(lib), 'SOFTWARE_FIXTURE_ONLY')
    body = json.loads(report.with_suffix('.json').read_text())
    assert body['verdict'] == 'NOT_MEASURED'
    reason = body['current_input_reason']
    assert reason.startswith('CURRENT_SPEF_COUPLING_MISSING'), reason
    assert str(selected) in reason and 'coupling' in reason and 'inspected' in reason, reason



def _explicit_step30_subject(tmp_path):
    """SOURCE_FIXTURE_ONLY native inputs with independent module and filenames."""
    p, folder, lib = project(tmp_path)
    old_paths = {'nl': p / 'phase3/stage3/pnr/neutral_pnr.v',
                 'sdc': p / 'phase3/stage3/pnr/constraint.sdc',
                 'spef': p / 'phase3/stage3/extracted/neutral.spef'}
    paths = {'nl': p / 'phase3/stage3/pnr/retained_route_bytes.v',
             'sdc': p / 'phase3/stage3/pnr/selected_scene.sdc',
             'spef': p / 'phase3/stage3/extracted/selected.max.spef'}
    for role, old in old_paths.items():
        text = old.read_text()
        if role in ('nl', 'spef'):
            text = text.replace('neutral', 'package_shell')
        write(paths[role], text)
        old.unlink()
    for name in ('state_in.json', 'state_out.json'):
        state = json.loads((folder / name).read_text())
        state.update(nl=str(paths['nl']), sdc=str(paths['sdc']), spef={'*': str(paths['spef'])})
        put(folder / name, state)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    data = json.loads(config.read_text())
    data['DESIGN_NAME'] = 'package_shell'
    put(config, data)
    put(folder / 'config.json', data)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(config), state_files={str(path): LC.digest(path) for path in paths.values()})
    # run_chain may declare the whole PDK root, not only one process subtree.
    put(folder / 'pdk_root.json', {'cli_pdk_root': '/pdk',
        'stated_by': 'run_chain(pdk_root=...)',
        'mounts_under_it': [[str(p / 'fixture_pdk'), '/pdk']]})
    seal(folder, fp)
    record = json.loads((p / LP.STEP23_RECORD).read_text())
    record['sta_state_sha256'] = LC.digest(folder / 'state_out.json')
    put(p / LP.STEP23_RECORD, record)
    return p, folder, lib, paths


@pytest.mark.parametrize('kind,expected', [('CORRELATED', 'PASS'), ('MISMATCH', 'FAIL')])
def test_default_step30_consumes_explicit_native_timed_paths(tmp_path, monkeypatch, kind, expected):
    import _opensta_current as current
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib, paths = _explicit_step30_subject(tmp_path)
    # Transport substitutes STA/SPICE only; the actual current producer,
    # Default adopter, publication and strict consumer all run below.
    current_fixture.correlation_tool(p, folder, lib, monkeypatch, mismatch=kind, companion='success')
    subject, _ = current.tool_subject(p, 'neutral')
    assert subject['top'] == 'neutral' and subject['physical_top'] == 'package_shell'
    roles = {row['role']: row for row in subject['inputs']}
    for role, key in [('netlist', 'nl'), ('sdc', 'sdc'), ('spef', 'spef')]:
        assert roles[role]['path'] == str(paths[key])
        assert roles[role]['sha256'] == LC.digest(paths[key])
    assert not (paths['nl'].parent / 'neutral_pnr.v').exists()
    assert not (paths['nl'].parent / 'package_shell_pnr.v').exists()
    for image, root in [(BF.IMAGE, p / 'foreign_pdk_root'), ('different-image', p / 'fixture_pdk')]:
        with pytest.raises(LC.Refusal, match='CURRENT_STEP30_IMAGE_OR_PDK_MISMATCH'):
            PST.current_context(p, image, root, 'neutral')
    for name in ('reports/phase3/spice_correlation.current.json',
                 'reports/phase3/spice_correlation.json', 'phase3/stage3/spice/correlation.json'):
        (p / name).unlink(missing_ok=True)
    result = _current_backend_step30(p, lib, monkeypatch)
    assert result['verdict'] == expected, result
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    assert receipt['top'] == 'package_shell'
    consumed = {row['role']: row for row in receipt['inputs']}
    assert all(consumed[role]['path'] == str(paths[key]) for role, key in
               [('netlist', 'nl'), ('sdc', 'sdc'), ('spef', 'spef')])
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT' and gate.summary['measurement'] == 'MEASURED'
    assert gate.summary['verdict'] == expected and gate.passed is (expected == 'PASS')


@pytest.mark.parametrize('damage', ['missing_netlist', 'netlist_hash', 'sdc_hash', 'spef_hash',
                                    'unbound_netlist', 'wrong_module'])
def test_default_step30_explicit_native_paths_do_not_authorize_drift(tmp_path, monkeypatch, damage):
    import _opensta_current as current
    p, folder, lib, paths = _explicit_step30_subject(tmp_path)
    # Establish valid context before applying one adversarial input change.
    assert spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    if damage == 'missing_netlist':
        paths['nl'].unlink()
    elif damage.endswith('_hash'):
        key = {'netlist_hash': 'nl', 'sdc_hash': 'sdc', 'spef_hash': 'spef'}[damage]
        paths[key].write_text(paths[key].read_text() + '\n// changed input bytes\n')
    else:
        fp = json.loads((folder / 'input_fingerprint.json').read_text())
        if damage == 'unbound_netlist':
            foreign = write(paths['nl'].with_name('another_route.v'), paths['nl'].read_text())
            state = json.loads((folder / 'state_out.json').read_text())
            state['nl'] = str(foreign)
            put(folder / 'state_out.json', state)
        else:
            paths['nl'].write_text(paths['nl'].read_text().replace('module package_shell', 'module other_shell'))
            fp['state_files'][str(paths['nl'])] = LC.digest(paths['nl'])
        seal(folder, fp)
        record = json.loads((p / LP.STEP23_RECORD).read_text())
        record['sta_state_sha256'] = LC.digest(folder / 'state_out.json')
        put(p / LP.STEP23_RECORD, record)
    expected_error = ValueError if damage.endswith('_hash') else (current.Refusal, LC.Refusal, OSError)
    expected_reason = 'LL_INPUT_CHANGED:' if damage.endswith('_hash') else None
    with pytest.raises(expected_error, match=expected_reason):
        PST.current_context(p, BF.IMAGE, p / 'fixture_pdk', 'neutral')
    result = _current_backend_step30(p, lib, monkeypatch)
    assert result['verdict'] == 'NOT_MEASURED', result
    assert not (p / 'reports/phase3/spice_correlation.current.json').exists()
    gate = SC.run_audit(p, run_spice=False)
    assert not gate.passed and gate.summary['measurement'] == 'NOT_MEASURED'


def _step30_image_interop_subject(tmp_path, monkeypatch):
    """Real retained/current readers; only tool processes are SOFTWARE_FIXTURE."""
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib, paths = _explicit_step30_subject(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    root = p / 'fixture_pdk'
    gds = write(root / 'neutral/cells.gds', 'SOFTWARE_FIXTURE_ONLY layout bytes\n')
    model = write(root / 'neutral/cells.spice', '.subckt BUF A Z\nR1 A Z 1\n.ends\n')
    config_path = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    config.update(CELL_GDS=['/pdk/neutral/cells.gds'],
                  CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'])
    put(config_path, config)
    put(folder / 'config.json', config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config_path)
    fp['config_files'].update({'/pdk/neutral/cells.gds': LC.digest(gds),
                             '/pdk/neutral/cells.spice': LC.digest(model)})
    seal(folder, fp)
    switch_path = p / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text())
    switch.pop('image')
    put(switch_path, switch)
    put(p / 'phase3/librelane_pdk_root.provenance.json', {
        'source': 'resolved', 'path': str(root),
        'derivation': {'image': BF.IMAGE, 'pdk': 'neutral',
                       'host_path': str(root / 'neutral')}})
    return p, folder, lib, paths, gds, model


@pytest.mark.parametrize('consumer', ['same', 'updated'])
def test_step30_keeps_producer_provenance_with_current_consumer_image(tmp_path, monkeypatch, consumer):
    p, folder, lib, paths, gds, model = _step30_image_interop_subject(tmp_path, monkeypatch)
    image = BF.IMAGE if consumer == 'same' else 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'b' * 64
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', image)
    original_receipt = (folder / 'vibeic_receipt.json').read_bytes()
    doc = PST.run_current_step30(p, image, p / 'fixture_pdk', 'neutral')
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    assert doc['verdict'] == 'PASS'
    assert doc['current_subject']['tool_image'] == BF.IMAGE
    assert receipt['tool_image'] == BF.IMAGE
    assert receipt['context']['image'] == image
    assert (folder / 'vibeic_receipt.json').read_bytes() == original_receipt
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED'
    assert gate.passed and gate.summary['verdict'] == 'PASS'


@pytest.mark.parametrize('damage', ['producer_image', 'netlist', 'sdc', 'liberty',
                                    'cell_gds', 'model', 'pdk_root'])
def test_step30_consumer_update_preserves_producer_and_material_refusals(tmp_path, monkeypatch, damage):
    p, folder, lib, paths, gds, model = _step30_image_interop_subject(tmp_path, monkeypatch)
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', BF.IMAGE)
    assert PST.current_context(p, BF.IMAGE, p / 'fixture_pdk', 'neutral')[0]['tool_image'] == BF.IMAGE
    root = p / 'fixture_pdk'
    if damage == 'producer_image':
        fp = json.loads((folder / 'input_fingerprint.json').read_text())
        fp['image'] = 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'c' * 64
        seal(folder, fp)
        reason = 'CURRENT_STAPOSTPNR_IMAGE_CHANGED|LL_PDK_IMAGE_OR_PROCESS_CHANGED'
    elif damage == 'pdk_root':
        root = p / 'other_root'
        root.mkdir()
        reason = 'CURRENT_STEP30_IMAGE_OR_PDK_MISMATCH'
    else:
        path = {'netlist': paths['nl'], 'sdc': paths['sdc'], 'liberty': lib,
                'cell_gds': gds, 'model': model}[damage]
        path.write_bytes(path.read_bytes() + b'\n ')
        reason = 'LL_INPUT_CHANGED:'
    with pytest.raises((LC.Refusal, ValueError), match=reason):
        PST.current_context(p, BF.IMAGE, root, 'neutral')



def test_step30_native_local_process_uses_its_declared_workdir(tmp_path, local_image):
    # A real LOCAL child runs inside the attested test image. This neutral
    # process control measures the native transport, not an IC or SPICE result.
    p = tmp_path / 'project'
    work = p / 'phase3/tool_arms/30/ngspice/base'
    work.mkdir(parents=True)
    program = ("import json,os; from pathlib import Path; "
               "Path('process.json').write_text(json.dumps({'cwd':os.getcwd(), "
               "'scope':'SOURCE_FIXTURE_ONLY'})); print('LOCAL_PROCESS_DONE')")
    result = PST._docker(local_image.image, p, [],
                         ['python3', '-c', program], work)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'LOCAL_PROCESS_DONE' in result.stdout
    assert json.loads((work / 'process.json').read_text()) == {
        'cwd': str(work), 'scope': 'SOURCE_FIXTURE_ONLY'}
    assert result._vibeic_lifecycle['rc'] == 0



@pytest.mark.parametrize('route', ['LOCAL', 'DOCKER'])
def test_step30_model_publication_matches_the_selected_execution_namespace(tmp_path, monkeypatch, route):
    p, folder, lib = project(tmp_path)
    root = p / 'fixture_pdk'
    nl = p / 'phase3/stage3/pnr/neutral_pnr.v'
    nl.write_text(nl.read_text().replace('BUF ', '\nBUF '))
    tech = root / 'neutral/libs.tech/ngspice'
    write(tech / 'design.ngspice', '.param neutral_scale=1\n')
    write(tech / 'models.ngspice', '.lib typ\n.model neutral nmos level=1\n.endl typ\n')
    write(root / 'neutral/cells.spice', '.subckt BUF A Z VDD VSS\nM0 Z A VSS VSS neutral W=1u L=1u\n.ends\n')
    write(lib, 'library(neutral_typ) {\n voltage_map(VDD, 1.8);\n voltage_map(VSS, 0);\n operating_conditions(typ) { voltage: 1.8; }\n}\n')
    gds = write(root / 'neutral/cells.gds', 'SOURCE_FIXTURE_ONLY original declared cell geometry\n')
    magicrc = write(root / 'neutral/libs.tech/magic/neutral.magicrc',
                    'SOURCE_FIXTURE_ONLY technology uses PDK_ROOT/neutral/libs.tech/magic/neutral.tech\n')
    technology = write(magicrc.with_suffix('.tech'), 'SOURCE_FIXTURE_ONLY unchanged technology\n')
    write(root / 'neutral/libs.tech/librelane/config.tcl',
          'set ::env(MAGICRC) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/magic/neutral.magicrc"\n')
    config = json.loads((folder / 'config.json').read_text())
    config.update(VDD_PIN='VDD', GND_PIN='VSS', CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'],
                  CELL_GDS=[str(gds)])
    put(folder / 'config.json', config)
    original = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    put(original, config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(original), config_files=LC.config_file_hashes(config, [(root / 'neutral', '/pdk/neutral')]),
              liberty_files={'/pdk/neutral/neutral.lib': LC.digest(lib)})
    fp['state_files'][str(nl)] = LC.digest(nl)
    seal(folder, fp)
    # Only the tool process is substituted; the real normal prepare_arm and
    # model-section reader/publication execute in the selected namespace.
    monkeypatch.setattr(LC, '_provider_for_image', lambda *_: None)
    monkeypatch.setattr(LC, '_provider_route', lambda *_: route == 'LOCAL')
    calls, magic_calls = [], []
    def sta(image, project, mounts, argv, cwd, **kwargs):
        if argv[0] == 'magic':
            import _container_exec as ce
            translations = [(guest, str(host)) for host, guest in mounts]
            declared_root = kwargs['env']['PDK_ROOT']
            # LOCAL rewrites env values, not paths assembled inside the rcfile.
            # Docker has the declared guest view; emulate only its file lookup.
            loaded_root = ce.localise_mounted_paths(declared_root, translations) if route == 'LOCAL' else declared_root
            tech_path = str(Path(loaded_root) / 'neutral/libs.tech/magic/neutral.tech')
            if route == 'DOCKER':
                tech_path = ce.localise_mounted_paths(tech_path, translations)
            magic_calls.append({'argv': argv, 'env': kwargs['env'], 'tech': tech_path})
            if not Path(tech_path).is_file():
                return SimpleNamespace(returncode=1,
                    stdout=f'SOURCE_FIXTURE_ONLY: Could not find file {tech_path}\n', stderr='')
            assert Path(tech_path).read_bytes() == technology.read_bytes()
            assert f'gds read {gds}\n' in Path(argv[-1]).read_text()
            # This neutral process substitution emits only a source fixture;
            # production extract_cells must read this invocation's export.
            write(Path(cwd) / 'BUF.spice', '* SOURCE_FIXTURE_ONLY current export\n'
                  + (root / 'neutral/cells.spice').read_text())
            return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY extraction\n', stderr='')
        assert argv[0] == 'sta'
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY STA transport\n', stderr='')
    monkeypatch.setattr(PST, '_docker', sta)
    arm = PST.prepare_arm(p, BF.IMAGE, folder / 'state_out.json', 'nom_typ',
                          pdk_root=root, pdk='neutral', out_dir=p / 'tool-fixture', paths=1)
    assert len(calls) == 1 and arm['prepared'] == []
    text = Path(arm['models']['path']).read_text()
    expected = str(tech) if route == 'LOCAL' else '/pdk/neutral/libs.tech/ngspice'
    assert f'.include {expected}/design.ngspice' in text
    assert f'.lib {expected}/models.ngspice typ' in text
    assert arm['models']['devices'] == ['neutral']
    if route == 'LOCAL':
        assert '/pdk/' not in text
        for line in text.splitlines():
            if line.startswith(('.include ', '.lib ')):
                assert Path(line.split()[1]).is_file()

    expected_root = str(root) if route == 'LOCAL' else '/pdk'
    assert len(magic_calls) == 1
    assert magic_calls[0]['env']['PDK_ROOT'] == expected_root
    assert magic_calls[0]['argv'][4] == expected_root + '/neutral/libs.tech/magic/neutral.magicrc'
    assert arm['cells']['cell_view']['extracted'] == ['BUF']
    assert arm['cells']['cell_view']['missing_exports'] == []


def test_default_step30_native_local_launcher_uses_the_admitted_provider(tmp_path, monkeypatch):
    """Real Default producer/strict reader; native process outputs are neutral."""
    import copy
    import os
    import re
    import subprocess
    import _watchdog as watchdog
    import test_f22_spice_corr as reference

    p, folder, lib = project(tmp_path)
    root = p / 'fixture_pdk'
    source = tmp_path / 'native-source'
    write(source / 'librelane/__init__.py', '# SOURCE_FIXTURE_ONLY native source\n')
    lib.write_text(reference._REFERENCE_LIB.replace('library(neutral_typ) {',
        'library(neutral_typ) {\n voltage_map(VDD, 1.8);\n voltage_map(VSS, 0);'))
    cells = '.subckt BUF A Z VDD VSS\nM0 Z A VSS VSS neutral W=1u L=1u\n.ends\n'
    cell_file = write(root / 'neutral/cells.spice', cells)
    gds = write(root / 'neutral/cells.gds', 'SOURCE_FIXTURE_ONLY cell geometry\n')
    write(root / 'neutral/libs.tech/ngspice/model.sp',
          '.lib typical\n.model neutral nmos level=1\n.endl typical\n')
    write(root / 'neutral/libs.tech/magic/neutral.magicrc', '# SOURCE_FIXTURE_ONLY Magic technology\n')
    write(root / 'neutral/libs.tech/librelane/config.tcl',
          'set ::env(MAGICRC) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/magic/neutral.magicrc"\n')
    netlist = p / 'phase3/stage3/pnr/neutral_pnr.v'
    netlist.write_text(netlist.read_text().replace('BUF ', '\nBUF '))
    config_path = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    config.update(VDD_PIN='VDD', GND_PIN='VSS', CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'],
                  CELL_GDS=['/pdk/neutral/cells.gds'])
    put(config_path, config); put(folder / 'config.json', config)
    put(p / 'phase3/librelane_switch.json', {
        'mode': 'default', 'execution_route': 'LOCAL', 'local_network_mode': 'host',
        'pdk_root_host': str(root), 'librelane_root_host': str(source)})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': 'neutral'}})
    image = LC.resolve_image(p)
    assert isinstance(image, LC.LocalProviderIdentity) and image.network_mode == 'host'
    LC.pdk_root_resolution(p, 'neutral', image=image)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(image=str(image), local_provider=image.as_record(), config=LC.digest(config_path),
              config_files=LC.config_file_hashes(config, [(root / 'neutral', '/pdk/neutral')]),
              liberty_files={'/pdk/neutral/neutral.lib': LC.digest(lib)})
    fp['state_files'][str(netlist)] = LC.digest(netlist)
    seal(folder, fp)
    originals = {str(x): LC.digest(x) for x in
                 [folder / 'vibeic_receipt.json', folder / 'input_fingerprint.json',
                  netlist, lib, cell_file, gds]}
    calls, points = [], {}
    damage = {'tool': False}
    original_leaf = watchdog.run_host_supervised

    def native_leaf(argv, **kwargs):
        # LC has already parsed the Docker-shaped request, admitted the typed
        # provider, rewritten mounts and installed its address-space ceiling.
        marker = 'import os,sys;os.execvp(sys.argv[1],sys.argv[1:])'
        if marker not in argv:
            return original_leaf(argv, **kwargs)
        tool_argv = list(argv[argv.index(marker) + 1:])
        cwd = Path(kwargs['cwd'])
        assert kwargs['env']['VIBEIC_LOCAL_NETWORK_MODE'] == 'host'
        calls.append({'argv': tool_argv, 'cwd': str(cwd),
                      'network': kwargs['env']['VIBEIC_LOCAL_NETWORK_MODE'],
                      'bound_executable': argv[0]})
        tool = tool_argv[0]
        if tool == 'magic':
            script = Path(tool_argv[-1]).read_text()
            assert 'gds read ' in script and 'ext2spice' in script
            write(cwd / 'BUF.spice', '* SOURCE_FIXTURE_ONLY Magic output\n' + cells)
            return watchdog.SupervisedResult(0, 'SOURCE_FIXTURE_ONLY Magic export\n', '', 'natural')
        if tool == 'sta':
            script = Path(tool_argv[-1]).read_text()
            if 'set_pi_model u_ref/Z' in script:
                slew = float(re.search(r'set_input_transition -fall (\S+)',
                                      (cwd / 'reference.sdc').read_text())[1])
                cap = float(re.search(r'set_pi_model u_ref/Z (\S+)', script)[1])
                delay = .8 + .5 * slew + 5 * cap
                points[cwd] = delay
                write(cwd / 'reference.rpt', reference._reference_report(
                    'BUF', 'u_ref', slew, cap, delay, external=True))
                write(cwd / 'reference.sp_1.sp', '* SOURCE_FIXTURE_ONLY reference\n'
                      '.include "reference.sp_1.subckt"\n.tran 1e-13 8e-9\n'
                      '.print tran v(I) v(u_ref/A) v(u_ref/Z) v(Z)\n'
                      'v1 u_ref/VDD 0 1.8\nv2 u_ref/VSS 0 0\n'
                      'v3 I 0 pwl(0 1.8 1e-9 0)\n.end\n')
                write(cwd / 'reference.sp_1.subckt', '.subckt ref I Z\nX0 Z I 0 0 neutral\n.ends\n')
            else:
                assert 'read_spef' in script and 'write_path_spice' in script
                cap, wire = (.025, .2) if cwd.name == 'mutated' else (.02, .1)
                delay = .8 + .5 * .2 + 5 * cap
                points[cwd] = delay * .7 + wire
                report = reference._reference_report('BUF', 'u0', .2, cap + .005, delay)
                report = re.sub(r'^ 0\.2 0\.05 \S+ v capture/D',
                                f' 0.2 0.05 {delay + wire:.9f} v capture/D', report, flags=re.M)
                write(cwd / 'path_1.rpt', report)
                write(cwd / 'reference_clocks.txt', '10\n')
                write(cwd / 'path_1.sp_1.sp', '* SOURCE_FIXTURE_ONLY design path\n'
                      '* Gate u0 A -> Z\nxu0 u0/A u0/Z u0/VDD u0/VSS BUF\n'
                      '.include "path_1.sp_1.subckt"\nv1 u0/VDD 0 1.8\nv2 u0/VSS 0 0\n.ends\n'
                      '.tran 1e-13 8e-9\n.print tran v(launch/Q) v(capture/D)\n.end\n')
                write(cwd / 'path_1.sp_1.subckt', '.subckt design I Z\nX0 Z I 0 0 neutral\n.ends\n')
                dcalc = write(cwd / 'dcalc.rpt', 'Library: neutral_typ\nCell: BUF\nA v -> Z v\n'
                    f'------- input_net_transition = 0.200000000\n'
                    f'| total_output_net_capacitance = {cap:.9f}\nDelay = {delay:.9f}\n')
                write(cwd / 'dcalc_1_1.tsv', f'u0/A\tu0/Z\t{dcalc}\n')
            return watchdog.SupervisedResult(0, 'VIBEIC_WPS_OK 1\nSOURCE_FIXTURE_ONLY STA\n', '', 'natural')
        assert tool in ('ngspice', 'Xyce'), tool_argv
        if damage['tool']:
            return watchdog.SupervisedResult(127, '', 'SOURCE_FIXTURE_ONLY simulator unavailable\n', 'natural')
        text = Path(tool_argv[-1]).read_text()
        wave = Path(re.search(r'wrdata (\S+)', text)[1])
        if 'refs' in cwd.parts:
            delay = points[cwd] * .7
            names, delays = ['I', 'u_ref/A', 'u_ref/Z', 'Z'], [0, 0, delay, delay]
        else:
            names, delays = ['launch/Q', 'capture/D'], [0, points[cwd]]
        rows = ['time ' + ' '.join('v(' + n + ')' for n in names)]
        for t in sorted({0, 8.0, *[1 + d + off for d in delays for off in (-.001, .001)]}):
            rows.append(' '.join([str(t * 1e-9)] +
                [str(1.8 if t <= 1 + d - .001 else 0) for d in delays]))
        write(wave, '\n'.join(rows) + '\n')
        return watchdog.SupervisedResult(0, 'SOURCE_FIXTURE_ONLY simulator\n', '', 'natural')

    monkeypatch.setattr(watchdog, 'run_host_supervised', native_leaf)
    result = _current_backend_step30(p, lib, monkeypatch)
    gate = SC.run_audit(p, run_spice=False)
    note = tmp_path / 'STEP30_LOCAL_LAUNCH_OBSERVATION.json'
    observation = {'scope': 'SOURCE_FIXTURE_ONLY real Default30 producer/strict consumer',
        'provider': image.as_record(), 'producer': result, 'gate': {'passed': gate.passed, 'summary': gate.summary},
        'calls': calls, 'originals': originals}
    write(note, json.dumps(observation, indent=2) + '\n')
    assert result['verdict'] == 'PASS', result
    assert gate.passed and gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED' and gate.summary['verdict'] == 'PASS'
    assert {str(x): LC.digest(x) for x in map(Path, originals)} == originals
    assert {'magic', 'sta', 'ngspice'} <= {x['argv'][0] for x in calls}
    assert any('refs' in Path(x['cwd']).parts for x in calls)
    assert all(x['bound_executable'] == image.executable for x in calls)
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    assert receipt['context']['image'] == str(image)
    assert SC.main([str(p), '--no-spice', '--json', str(tmp_path / 'strict-consumer.json')]) == 0
    # A plain Docker request keeps the exact original command shape. This
    # transport-only control does not replace any LOCAL producer admission.
    with monkeypatch.context() as remote:
        captured = []
        remote.setattr(LC, 'run_container', lambda argv, **kw:
            captured.append((argv, kw)) or subprocess.CompletedProcess(argv, 0, '', ''))
        PST._docker(BF.IMAGE, p, [(root / 'neutral', '/pdk/neutral')],
                    ['ngspice', '-b', 'deck.sp'], p, env={'PDK_ROOT': '/pdk'})
        expected = ['docker', 'run', '--rm', '--network', 'none',
                    *PST._dmem.docker_memory_flags(), '-v', f'{p.resolve()}:{p.resolve()}',
                    '-v', f'{(root / "neutral").resolve()}:/pdk/neutral:ro',
                    '-e', 'PDK_ROOT=/pdk', '--workdir', str(p),
                    '--entrypoint', 'ngspice', BF.IMAGE, '-b', 'deck.sp']
        assert captured == [(expected, {'supervised': True})]
    damage['tool'] = True
    unavailable = _current_backend_step30(p, lib, monkeypatch)
    observation['unavailable_tool'] = unavailable
    assert unavailable['verdict'] == 'NOT_MEASURED', unavailable
    damage['tool'] = False
    model = root / 'neutral/libs.tech/ngspice/model.sp'
    model.rename(model.with_suffix('.absent'))
    missing = _current_backend_step30(p, lib, monkeypatch)
    observation['missing_model'] = missing
    write(note, json.dumps(observation, indent=2) + '\n')
    assert missing['verdict'] == 'NOT_MEASURED', missing

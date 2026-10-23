"""Behavioral front-end controls using existing consumers and neutral circuits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import analog_native_front as front
from _analog_producer_fixture import block, make_project


@pytest.mark.parametrize("prefix", ["not ", "* ", "instruction: "])
def test_op_table_does_not_consume_prose(prefix):
    assert front._op_values("Node Voltage\nout 1.25\n") == {"out": 1.25}
    assert front._op_values(prefix + "Node Voltage\nout 1.25\n") == {}
    assert front._op_values("Node Voltage\n" + prefix + "out 1.25\n") == {}


def _put(project, relative, body):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def _record(project, path):
    return {'path': str(path.relative_to(project)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _project(tmp_path):
    make_project(tmp_path, [block('cell_alpha', 'ldo',
        [{'name': 'Vout', 'target': 1.2, 'unit': 'V'}])])
    return tmp_path, {'name': 'cell_alpha', 'type': 'ldo'}


class Commands:
    def __init__(self, *, native='drain_current = 1.25e-4\n', native_rc=0,
                 gate_failure=None, mock_checks=False):
        self.calls = []
        self.native = native
        self.native_rc = native_rc
        self.gate_failure = gate_failure
        self.mock_checks = mock_checks

    def __call__(self, program, args, *, cwd=None, outputs=None):
        args = list(map(str, args))
        self.calls.append((program, args, cwd))
        if program == '@ngspice':
            log = Path(args[args.index('-o') + 1])
            log.write_text(self.native)
            return {'returncode': self.native_rc, 'stdout': '', 'stderr': '', 'log': str(log)}
        if program == self.gate_failure:
            return {'returncode': 1, 'stdout': 'FAIL: actual checker rejection', 'stderr': ''}
        if self.mock_checks:
            return {'returncode': 0, 'stdout': 'PASS', 'stderr': ''}
        completed = subprocess.run([sys.executable, str(front.HERE / program), *args],
                                   cwd=cwd, capture_output=True, text=True)
        return {'returncode': completed.returncode, 'stdout': completed.stdout,
                'stderr': completed.stderr}


def test_a01_real_producer_and_consumer_bind_current_input(tmp_path):
    project, declared = _project(tmp_path)
    commands = Commands()
    result = front.run_step('A01', project, declared, {}, commands)
    assert result['status'] == 'PASS', result
    spec = json.loads((project / 'phase3/analog/cell_alpha/spec.json').read_text())
    assert spec['specs'][0]['target'] == 1.2
    assert spec['_provenance']['fields_defaulted'] == []
    assert [p for p, _, _ in commands.calls] == [
        'analog_a1_spec_emit.py', 'analog_a1_spec_extract_check.py']


def test_a01_retained_invalid_spec_fails_real_consumer_without_overwrite(tmp_path):
    project, declared = _project(tmp_path)
    path = _put(project, 'phase3/analog/cell_alpha/spec.json', {'specs': []})
    before = path.read_bytes()
    result = front.run_step('A01', project, declared, {}, Commands())
    assert result['status'] == 'FAIL'
    assert 'A1_SPEC_NO_FIELDS' in result['detail']
    assert path.read_bytes() == before


def test_a01_changed_bound_source_refreshes_owned_spec(tmp_path):
    project, declared = _project(tmp_path)
    assert front.run_step('A01', project, declared, {}, Commands())['status'] == 'PASS'
    source = project / 'phase1/generated_docs/L5_ADI_SPEC.json'
    body = json.loads(source.read_text())
    body['analog_blocks'][0]['spec']['specs'][0]['target'] = 1.4
    source.write_text(json.dumps(body))
    result = front.run_step('A01', project, declared, {}, Commands())
    assert result['status'] == 'PASS', result
    spec = json.loads((project / 'phase3/analog/cell_alpha/spec.json').read_text())
    assert spec['specs'][0]['target'] == 1.4


def _smoke_project(tmp_path):
    project, declared = _project(tmp_path)
    model = _put(project, 'input/pdk/models/device_alpha.lib',
                 '.lib typical\n.model device_alpha nmos level=1\n.endl typical\n')
    _put(project, 'input/pdk/klayout/tech/drc/process_alpha.drc', '# foundry control\n')
    _put(project, 'input/pdk/netgen/process_alpha.tcl', '# foundry control\n')
    deck = _put(project, 'input/model_smokes/device_alpha.sp',
                '* real model device load\n.lib input/pdk/models/device_alpha.lib typical\n'
                'vdrain d 0 1.2\nvgate g 0 0\n'
                'mdevice d g 0 0 device_alpha w=1u l=1u\n'
                '.dc vgate 0 1.2 0.6\n.measure dc drain_current find i(vdrain) at=1.2\n.end\n')
    smoke = {'id': 'device_alpha_typical', 'device': 'device_alpha', 'corner': 'typical',
             'model': _record(project, model), 'deck': _record(project, deck),
             'required_measurements': ['drain_current']}
    return project, declared, smoke


def test_a02_native_model_consumer_needs_no_qualification_registry(tmp_path):
    project, declared, smoke = _smoke_project(tmp_path)
    commands = Commands()
    result = front.run_step('A02', project, declared,
                            {'config': {'blocks': {'cell_alpha': {'model_smokes': [smoke]}}}}, commands)
    assert result['status'] == 'PASS', result
    assert result['metrics'][0]['measurements'] == {'drain_current': 1.25e-4}
    assert any(program == '@ngspice' for program, _, _ in commands.calls)
    assert not (project / 'qualifications.json').exists()
    assert not (project / 'input/flow109/A02.json').exists()


@pytest.mark.parametrize('native', [
    'Fatal error: unknown subckt device_alpha\ndrain_current = 1.25e-4\n',
    'drain_current = nan\n',
    'normal simulator banner but no measured value\n',
])
def test_a02_success_exit_cannot_hide_native_error_or_absent_measurement(tmp_path, native):
    project, declared, smoke = _smoke_project(tmp_path)
    result = front.run_step('A02', project, declared,
                            {'config': {'model_smokes': [smoke]}}, Commands(native=native))
    assert result['status'] == 'FAIL', result
    assert result['detail'].startswith('A02_')


def test_a02_missing_deck_is_not_measured_and_runs_no_simulator(tmp_path):
    project, declared, smoke = _smoke_project(tmp_path)
    (project / smoke['deck']['path']).unlink()
    commands = Commands()
    result = front.run_step('A02', project, declared,
                            {'config': {'model_smokes': [smoke]}}, commands)
    assert result['status'] == 'NOT_MEASURED', result
    assert all(program != '@ngspice' for program, _, _ in commands.calls)


@pytest.mark.parametrize(('features', 'expected'), [
    ({'analog_testability': False, 'analog_trim': False}, 'NOT_APPLICABLE'),
    ({'analog_testability': True, 'analog_trim': False}, 'NOT_MEASURED'),
    ({}, 'NOT_MEASURED'),
])
def test_a03_explicit_applicability_is_not_a_presence_only_plan_pass(tmp_path, features, expected):
    project, declared = _project(tmp_path)
    commands = Commands()
    result = front.run_step('A03', project, declared, {'features': features}, commands)
    assert result['status'] == expected
    assert commands.calls == []


def test_a04_existing_real_topology_consumer_preserves_design(tmp_path):
    project, declared = _project(tmp_path)
    markdown = _put(project, 'phase3/analog/cell_alpha/topology.md',
                    '# Designer topology\n' +
                    'A pmos pass transistor uses an nmos differential pair and current mirror.\n' * 15)
    before = markdown.read_bytes()
    commands = Commands()
    result = front.run_step('A04', project, declared, {}, commands)
    assert result['status'] == 'PASS', result
    assert markdown.read_bytes() == before
    assert [program for program, _, _ in commands.calls] == ['analog_a2_topology_select_check.py']


OP_LOG = ('Circuit: neutral operating point\nNo. of Data Rows : 1\n'
          'Node Voltage\n---- -------\n'
          'out 1.200000e+00\nxdut.bias 6.000000e-01\n'
          'Source Current\n------ -------\nv_supply#branch -1.000000e-04\n')


def _op_project(tmp_path):
    project, declared = _project(tmp_path)
    _put(project, 'phase3/analog/cell_alpha/cell_alpha.sp',
         '* neutral delivered analog DUT\n.subckt cell_alpha supply out\n'
         'mdevice out supply 0 0 model_alpha w=1u l=1u\n.ends cell_alpha\n')
    testbench = _put(project, 'phase3/analog/cell_alpha/tb_cell_alpha.sp',
                     '* source stimulus\n.include cell_alpha.sp\n'
                     'v_supply supply 0 1.2\nxdut supply out cell_alpha\n'
                     '.options reltol=1e-4\n.save v(out)\n.control\n'
                     'tran 1n 1m\nmeas tran density avg v(out)\n.endc\n.end\n')
    return project, declared, testbench


def test_a05_op_keeps_delivered_circuit_and_does_not_run_transient_or_claim_accuracy(tmp_path):
    project, declared, testbench = _op_project(tmp_path)
    before = testbench.read_bytes()
    commands = Commands(native=OP_LOG, mock_checks=True)
    result = front.run_step('A05', project, declared, {}, commands)
    assert result['status'] == 'PASS', result
    assert result['metrics']['performance_acceptance'] == 'NOT_MEASURED'
    assert result['metrics']['operating_point']['out'] == 1.2
    assert testbench.read_bytes() == before
    native = [(args, cwd) for program, args, cwd in commands.calls if program == '@ngspice']
    assert len(native) == 1
    deck = Path(native[0][0][-1]).read_text()
    assert '.include cell_alpha.sp' in deck
    assert '.options reltol=1e-4' in deck
    assert '.op\n.end\n' in deck
    assert 'tran 1n' not in deck
    assert 'meas tran density' not in deck
    assert native[0][1] == testbench.parent
    checkers = [(program, args) for program, args, _ in commands.calls
                if program in ('analog_netlist_pdk_check.py', 'analog_netlist_connectivity_check.py',
                               'analog_netlist_include_order_check.py', 'analog_netlist_path_lint.py')]
    assert len(checkers) == 4
    assert all(args[args.index('--block') + 1] == declared['name'] for _, args in checkers)


def test_a05_failed_existing_consumer_blocks_native_launch(tmp_path):
    project, declared, _ = _op_project(tmp_path)
    commands = Commands(native=OP_LOG, mock_checks=True,
                        gate_failure='analog_netlist_connectivity_check.py')
    result = front.run_step('A05', project, declared, {}, commands)
    assert result['status'] == 'FAIL'
    assert all(program != '@ngspice' for program, _, _ in commands.calls)


@pytest.mark.parametrize(('text', 'expected'), [
    ('native exit without measurements\n', 'NOT_MEASURED'),
    (OP_LOG + 'fatal error: model load failed\n', 'FAIL'),
    (OP_LOG.replace('out 1.200000e+00', 'out nan'), 'FAIL'),
])
def test_a05_zero_exit_requires_real_finite_operating_point(tmp_path, text, expected):
    project, declared, _ = _op_project(tmp_path)
    result = front.run_step('A05', project, declared, {}, Commands(native=text, mock_checks=True))
    assert result['status'] == expected, result


def test_a05_existing_rail_consumer_refuses_outside_supply(tmp_path):
    project, declared, _ = _op_project(tmp_path)
    _put(project, 'phase3/analog/cell_alpha/netlist_provenance.json',
         {'testbench': {'conditions': ['supply = vin = 1.2 V']}})
    result = front.run_step('A05', project, declared, {},
                            Commands(native=OP_LOG.replace('xdut.bias 6.000000e-01',
                                                           'xdut.bias 8.000000e+00'),
                                     mock_checks=True))
    assert result['status'] == 'FAIL', result
    assert result['detail'] == 'A05_NATIVE_OP_RAIL_EXCURSION'


def test_usage_error_and_missing_simulator_are_not_design_verdicts(tmp_path):
    project, declared, _ = _op_project(tmp_path)
    result = front.run_step('A05', project, declared, {},
                            Commands(native='', native_rc=127, mock_checks=True))
    assert result['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('replacement', [
    '* unrelated circuit\nvsource another 0 1.2\n.op\n.end\n',
    '* unused DUT library\n.include cell_alpha.sp\nvsource another 0 1.2\n.op\n.end\n',
])
def test_a05_unrelated_or_uninstantiated_dut_cannot_supply_op_pass(tmp_path, replacement):
    project, declared, testbench = _op_project(tmp_path)
    testbench.write_text(replacement)
    commands = Commands(native=OP_LOG, mock_checks=True)
    result = front.run_step('A05', project, declared, {}, commands)
    assert result['status'] == 'FAIL', result
    assert all(program != '@ngspice' for program, _, _ in commands.calls)


def test_op_deck_removes_only_analysis_continuations():
    text = ('* neutral analysis\n.include circuit_alpha.sp\n'
            '.options reltol=1e-4\n+ abstol=1e-12\n'
            '.save v(out)\n+ v(bias)\n'
            '.tran 1n\n+ 1m\n.end\n')
    op = front._op_deck(text)
    assert '+ abstol=1e-12' in op
    assert '+ v(bias)' not in op
    assert '+ 1m' not in op
    assert '.include circuit_alpha.sp' in op

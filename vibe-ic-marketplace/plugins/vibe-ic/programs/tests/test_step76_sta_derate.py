"""Declared OCV controls with STA and simulator transport substituted."""
import subprocess
from types import SimpleNamespace

import pytest

import _plugin_tree  # noqa: F401
import path_spice_tool as PST
from librelane_contract import Refusal


def arm_fixture(tmp_path, monkeypatch, *, factor=1.05, complete=False):
    deck = tmp_path / 'path.sp'
    deck.write_text('.tran 1p 5n\n.end\n')
    parsed = {'startpoint': 'launch', 'endpoint': 'capture',
              'path_delay_ns': 1.05, 'rows': [
                  {'inst': 'u0', 'pin': 'u0/A', 'cell': 'BUF', 'tr': '^',
                   'slew_ns': .1, 'incr': 0.0},
                  {'inst': 'u0', 'pin': 'u0/Z', 'cell': 'BUF', 'tr': '^',
                   'cap_pf': .01, 'incr': .84}]}
    calls = []
    def simulate(*args, **kwargs):
        calls.append('simulator')
        return SimpleNamespace(returncode=0, stdout='fixture', stderr='')
    monkeypatch.setattr(PST, '_simulate', simulate)
    monkeypatch.setattr(PST, 'measure', lambda *_: {'status': 'MEASURED', 'spice_ns': 1.0})
    monkeypatch.setattr(PST, 'transient_step_s', lambda *_: (1e-12, 1e-12))
    tolerances = []
    def tolerance(_liberty, stages, delay):
        tolerances.append((delay, stages[0]['sta_delay_ns']))
        return {'tolerance_pct': 2.0}
    monkeypatch.setattr(PST._scc, 'derive_liberty_path_tolerance', tolerance)
    monkeypatch.setattr(PST, '_reference_sources', lambda *_: {})
    def characterisation(_container, _sources, _subckts, _liberty, stages, *_args, **_kwargs):
        if not complete:
            return {'complete': False}
        identity = {'fixture': 'independent-grid'}
        return {'complete': True, 'references': [
            {'identity': identity, 'request': {'identity': identity},
             'status': 'MEASURED', 'spice_ns': .8}],
            'stages': [{'sta_delay_ns': stages[0]['sta_delay_ns'],
                        'points': [{'weight': 1.0, 'identity': identity}]}]}
    monkeypatch.setattr(PST._scc, 'measure_pdk_characterisation', characterisation)
    arm = {'simulator': 'ngspice', 'header': {}, 'image': 'fixture',
           'project': tmp_path, 'mounts': [], 'sta_rc': 0, 'liberty_text': '',
           'ocv_late_derate': factor,
           'prepared': [{'path': 1, 'parsed': parsed, 'deck': deck,
                         'wps_fail': [], 'dcalc': {}}]}
    return arm, calls, tolerances


@pytest.mark.parametrize('complete', [False, True])
def test_spice_comparison_removes_declared_late_derate(tmp_path, monkeypatch, complete):
    arm, calls, tolerances = arm_fixture(tmp_path, monkeypatch, complete=complete)
    row = PST.simulate_arm(arm)['paths'][0]
    assert row['sta_ns'] == pytest.approx(1.0)
    assert row['spice_ns'] == pytest.approx(1.0)
    assert row['error_pct'] == pytest.approx(0.0)
    assert row['verdict'] == 'CORRELATED'
    assert row['sta_derated_ns'] == 1.05
    assert row['ocv_late_derate'] == 1.05
    assert row['tolerance_pct'] == 2.0
    assert tolerances == [(1.05, .84)]
    assert calls == ['simulator']
    if complete:
        assert row['sta_wire_ns'] == pytest.approx(.2)
        assert row['pdk_characterisation']['stages'][0]['sta_delay_ns'] == pytest.approx(.8)


def test_missing_derate_refuses_before_simulator(tmp_path, monkeypatch):
    arm, calls, _ = arm_fixture(tmp_path, monkeypatch)
    arm.pop('ocv_late_derate')
    try:
        PST.simulate_arm(arm)
        outcome = 'simulated-without-declaration'
    except Refusal as exc:
        outcome = exc.code
    assert outcome == 'LL_STA_DERATE_UNDECLARED'
    assert calls == []


def test_combined_arms_use_their_own_declared_factor(tmp_path, monkeypatch):
    arm, _, _ = arm_fixture(tmp_path, monkeypatch)
    item = arm['prepared'][0]
    arm['prepared'] = [dict(item, arm='base'), dict(item, arm='mutated')]
    arm['reference_arms'] = {'base': {'ocv_late_derate': 1.05},
                             'mutated': {'ocv_late_derate': 2.1}}
    rows = PST.simulate_arm(arm)['paths']
    assert [row['sta_ns'] for row in rows] == pytest.approx([1.0, .5])
    assert [row['ocv_late_derate'] for row in rows] == [1.05, 2.1]


@pytest.mark.parametrize('declaration', [
    '', 'set_timing_derate -early .95', 'set_timing_derate -late 0',
    'set_timing_derate -late -1', 'set_timing_derate -late NaN',
    'set_timing_derate -late Inf', 'set_timing_derate -late $unresolved',
    'set_timing_derate -late 1.05 u0',
    'set_timing_derate -late -cell_delay 1.05',
    'set_timing_derate -late -rise 1.05',
    'set_timing_derate -late -cell_delay 1.05\nVIBEIC_STA_DERATE set_timing_derate -late -net_delay 1.1',
    'set_timing_derate -late 1.05\nVIBEIC_STA_DERATE unset_timing_derate',
])
def test_unreadable_or_nonuniform_native_declaration_refuses(declaration):
    with pytest.raises(Refusal, match='LL_STA_DERATE_UNDECLARED'):
        PST.declared_sta_late_derate('VIBEIC_STA_DERATE ' + declaration + '\n')


def test_uniform_native_declaration_can_be_split_by_delay_kind():
    transcript = ('VIBEIC_STA_DERATE set_timing_derate -early .95\n'
                  'VIBEIC_STA_DERATE set_timing_derate -late -cell_delay 1.05\n'
                  'VIBEIC_STA_DERATE set_timing_derate -late -net_delay 1.05\n')
    assert PST.declared_sta_late_derate(transcript) == 1.05


def test_early_or_clock_only_scopes_do_not_change_late_data_reference():
    transcript = ('VIBEIC_STA_DERATE set_timing_derate -early .95 u0\n'
                  'VIBEIC_STA_DERATE set_timing_derate -late -clock 1.1 clkbuf\n'
                  'VIBEIC_STA_DERATE set_timing_derate -late -cell_check 1.1 u0\n'
                  'VIBEIC_STA_DERATE set_timing_derate -late -data 1.05\n')
    assert PST.declared_sta_late_derate(transcript) == 1.05


def test_actual_tcl_trace_reads_resolved_sdc_and_stops_after_read(tmp_path):
    included = tmp_path / 'derate.sdc'
    included.write_text('set_timing_derate -early .95\nset_timing_derate -late $late\n')
    sdc = tmp_path / 'scene.sdc'
    sdc.write_text(f'set late 1.05\nif {{$late > 1}} {{source {{{included}}}}}\n')
    inputs = {'liberties': [], 'sta_netlist': 'unused.v', 'sdc': str(sdc)}
    script = PST.arm_tcl(inputs, tmp_path, 'neutral', 'unused.spef', ('lib', 'typ'), [],
                         tmp_path, 'cells.sp', 'models.sp', 'VDD', 'VSS', 'ngspice')
    prelude = ('proc unknown {args} {return {}}\n'
               'proc set_timing_derate {args} {}\n'
               'proc unset_timing_derate {} {}\n'
               'proc read_sdc {path} {uplevel #0 [list source $path]}\n')
    target = tmp_path / 'trace.tcl'
    target.write_text(prelude + script + 'set_timing_derate -late 1.2\n')
    run = subprocess.run(['tclsh', str(target)], capture_output=True, text=True, check=True)
    assert PST.declared_sta_late_derate(run.stdout) == 1.05
    assert '1.2' not in run.stdout

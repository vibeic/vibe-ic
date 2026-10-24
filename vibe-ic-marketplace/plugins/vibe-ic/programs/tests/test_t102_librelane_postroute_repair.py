"""T102: step 32 (post-route repair) as a LibreLane custom step under the PPA closure.

The closure, the registry, the measurement and actuator CLIs, the supply
ownership gate and the runner's deck builder run for real. Only an EDA tool's
file writes are substituted: `librelane_contract.run_chain` and the native
OpenROAD timing measurement are replaced by writers of the step folders and
scene metrics a real run leaves.
"""
import importlib
from types import SimpleNamespace
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / 'tests'))
prr = importlib.import_module('librelane_postroute_repair')
closure = importlib.import_module('_ppa.closure')
contract = importlib.import_module('librelane_contract')
native = importlib.import_module('_native_postroute_timing')
REAL_NATIVE_MEASURE = native.measure

from _stated_eda_image import state_the_image  # noqa: E402

STEP_DIR = PROGRAMS / 'librelane_plugins' / 'librelane_plugin_vibeic'


def _tool_written_native_scene(ctx, repair_state, out_dir):
    sta = repair_state.parent.parent / '04-openroad-stapostpnr/state_out.json'
    metrics = json.loads(sta.read_text())['metrics']
    summary = prr.summarize(metrics, ctx['corners'])
    return {k: summary[k] for k in ('setup_ws', 'hold_ws',
                                   'setup_ws_min', 'hold_ws_min')}


@pytest.fixture(autouse=True)
def _stated_image(monkeypatch):
    # the identity is stated, never asked of this host (no docker in the image)
    state_the_image(monkeypatch)
    for name in ('VIBEIC_LIBRELANE_IMAGE', 'VIBEIC_LIBRELANE_PDK_ROOT'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(native, 'measure', _tool_written_native_scene)
REGISTRY = PLUGIN / 'config' / 'ppa_actuator_registry.yaml'
CORNERS = ['nom_tt_025C_5v00', 'nom_ss_125C_4v50', 'nom_ff_n40C_5v50']


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------- the fork capability ---

#: Recorded on vibeic-eda 0.3.79 (sha256:93d88e9e…), 2026-09-27, by
#: `fork_capability`: the fork accepts `-detailed_routing` (it gets as far as
#: "no network"), and rejects the bogus control flag at the parser.
FORK_TRANSCRIPT = (
    "[INFO] Executing command: 'bash -c openroad -no_init -no_splash -exit /dev/stdin 2>&1'\n"
    "VIBEIC_PRR_PROBE_REAL: Error: no network has been linked.\n"
    "[ERROR STA-0562] estimate_parasitics -vibeic_probe_unknown_control_flag is not "
    "a known keyword or flag.\n"
    "VIBEIC_PRR_PROBE_CTRL: STA-0562\n")
#: An OpenROAD without the flag rejects it exactly as it rejects the control
#: (the same parser, the same answer); both answer forms the parser gives.
STOCK_TRANSCRIPTS = (
    "VIBEIC_PRR_PROBE_REAL: STA-0562\nVIBEIC_PRR_PROBE_CTRL: STA-0562\n",
    "VIBEIC_PRR_PROBE_REAL: estimate_parasitics -detailed_routing is not a known "
    "keyword or flag.\nVIBEIC_PRR_PROBE_CTRL: estimate_parasitics "
    "-vibeic_probe_unknown_control_flag is not a known keyword or flag.\n")


def test_the_fork_flag_is_told_from_a_bogus_flag_not_from_help_text():
    assert prr.flag_accepted_vs_control(FORK_TRANSCRIPT) is True
    for stock in STOCK_TRANSCRIPTS:
        assert prr.flag_accepted_vs_control(stock) is False
    # An answer that is absent is unmeasured, never a capability.
    assert prr.flag_accepted_vs_control("VIBEIC_PRR_PROBE_REAL: x\n") is None
    assert prr.flag_accepted_vs_control("") is None


def test_fork_capability_probe_uses_shared_supervisor_without_raw_stdin(
        monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 0, stdout=FORK_TRANSCRIPT, stderr="")

    monkeypatch.setattr(contract, "run_container", run)
    result = prr.fork_capability("img")
    assert result["capable"] is True
    assert calls[0][1] == {"probe_deadline_s": contract.PROBE_DEADLINE_S}
    assert "-i" not in calls[0][0]
    assert prr._PROBE_REAL in calls[0][0][-1]


def test_fork_capability_deadline_is_unmeasured(monkeypatch):
    def deadline(*_args, **_kwargs):
        raise contract.Refusal("LL_TOOL_DEADLINE", "probe deadline elapsed")

    monkeypatch.setattr(contract, "run_container", deadline)
    result = prr.fork_capability("img")
    assert result["capable"] is None
    assert result["code"] == "LL_TOOL_DEADLINE"
    assert "LL_TOOL_DEADLINE" in result["reason"]


def test_probe_deadline_is_recorded_as_unmeasured_not_incapable(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(prr, "fork_capability", lambda *_a, **_k: {
        "capable": None, "image": "img", "code": "LL_TOOL_DEADLINE",
        "reason": "LL_TOOL_DEADLINE: named probe container was reaped"})
    monkeypatch.setattr(contract, "resolve_step_configs",
                        lambda *_a, **_k: pytest.fail("no config may be resolved"))
    report = prr.run(tmp_path, image="img", pdk="processA", pdk_root=tmp_path,
                     views={}, sdc=tmp_path / "x.sdc", derate=(0.95, 1.05))
    assert report["verdict"] == "NOT_MEASURED"
    assert report["code"] == "LL_TOOL_DEADLINE"
    assert report["reason_class"] == "execution_error"
    assert "named probe container" in report["reason"]
    assert json.loads((tmp_path / prr.REPORT_REL).read_text()) == report


def test_an_incapable_image_refuses_before_any_state_is_built(tmp_path, monkeypatch):
    monkeypatch.setattr(prr, 'fork_capability',
                        lambda image, docker='docker': {'capable': False, 'image': image})
    monkeypatch.setattr(contract, 'resolve_step_configs',
                        lambda *a, **k: pytest.fail('no config may be resolved'))
    report = prr.run(tmp_path, image='img', pdk='pdk', pdk_root=tmp_path,
                     views={}, sdc=tmp_path / 'x.sdc', derate=(0.95, 1.05))
    assert report['verdict'] == 'NOT_MEASURED'
    assert report['code'] == 'LL_PRR_TOOL_INCAPABLE'
    assert json.loads((tmp_path / prr.REPORT_REL).read_text())['code'] == 'LL_PRR_TOOL_INCAPABLE'


# ------------------------------------------------------------- measurement ---

def test_native_sta_applies_and_attests_signoff_ocv_before_slack(tmp_path, monkeypatch):
    """An undrated positive candidate must be red under signoff's OCV recipe.

    Only OpenROAD's file writes are substituted; the real native measurement
    builds its Tcl and the real controller consumes the returned worst slack.
    """
    runner = importlib.import_module('phase3_one_shot_runner')
    early = runner._FLAT_OCV_DERATE_EARLY
    late = runner._FLAT_OCV_DERATE_LATE
    odb = write(tmp_path / 'route.odb', 'routed database')
    sdc = write(tmp_path / 'route.sdc', 'create_clock -period 20 [get_ports clk]\n')
    lib = write(tmp_path / 'cells.lib', 'liberty view')
    rules = write(tmp_path / 'rules.rcx', 'extraction rules')
    state = put(tmp_path / 'state.json', {'odb': str(odb), 'sdc': str(sdc)})
    cfg = put(tmp_path / 'rcx.json', {
        'RCX_RULESETS': {'*': str(rules)},
        'CELL_LIBS': {'*': [str(lib)]},
        'DEFAULT_CORNER': 'nom_ss_125C_4v50',
    })
    ctx = {'project': str(tmp_path), 'image': 'tool image', 'mounts': [],
           'configs': {'OpenROAD.RCX': str(cfg)},
           'corners': ['nom_ss_125C_4v50'], 'derate': [early, late]}
    seen = []

    def tool_writes(_ctx, script, output):
        text = script.read_text()
        if script.name.startswith('extract_'):
            output.write_text('*SPEF "IEEE 1481-1998"\n')
            return
        seen.append(text)
        early_cmd = f'set_timing_derate -early {early}'
        late_cmd = f'set_timing_derate -late {late}'
        derated = (early_cmd in text and late_cmd in text
                   and text.index(late_cmd) < text.index('report_worst_slack -max'))
        output.write_text(('OCV_BASIS flat_ocv\n' if derated else '')
                          + f'worst slack max {"-0.040000" if derated else "0.010000"}\n'
                          + 'worst slack min 0.200000\n')

    monkeypatch.setattr(native, '_run', tool_writes)
    result = REAL_NATIVE_MEASURE(ctx, state, tmp_path / 'native')
    assert seen and result['setup_ws_min'] == -0.04
    assert result['ocv_applied'] == {'mode': 'flat_ocv', 'early': early, 'late': late}
    assert result['measurement_basis'].endswith('+flat_ocv')


def test_native_sta_removes_embedded_flat_derate_before_explicit_recipe(tmp_path, monkeypatch):
    """A LibreLane write_sdc can already contain OCV; normalize it once."""
    runner = importlib.import_module('phase3_one_shot_runner')
    early = runner._FLAT_OCV_DERATE_EARLY
    late = runner._FLAT_OCV_DERATE_LATE
    odb = write(tmp_path / 'route.odb', 'routed database')
    sdc = write(tmp_path / 'route.sdc',
                f'create_clock -period 20 [get_ports clk]\n'
                f'set_timing_derate -early {early:.4f}\n'
                f'set_timing_derate -late {late:.4f}\n')
    lib = write(tmp_path / 'cells.lib', 'liberty view')
    rules = write(tmp_path / 'rules.rcx', 'extraction rules')
    state = put(tmp_path / 'state.json', {'odb': str(odb), 'sdc': str(sdc)})
    cfg = put(tmp_path / 'rcx.json', {
        'RCX_RULESETS': {'*': str(rules)}, 'CELL_LIBS': {'*': [str(lib)]},
        'DEFAULT_CORNER': 'nom_ss_125C_4v50'})
    ctx = {'project': str(tmp_path), 'image': 'tool image', 'mounts': [],
           'configs': {'OpenROAD.RCX': str(cfg)},
           'corners': ['nom_ss_125C_4v50'], 'derate': [early, late]}

    def tool_writes(_ctx, script, output):
        if script.name.startswith('extract_'):
            output.write_text('*SPEF "IEEE 1481-1998"\n')
            return
        text = script.read_text()
        match = re.search(r'^read_sdc \{([^}]+)\}$', text, re.M)
        assert match is not None
        measured_sdc = Path(match.group(1)).read_text()
        assert 'set_timing_derate' not in measured_sdc
        assert text.count('set_timing_derate -early') == 1
        assert text.count('set_timing_derate -late') == 1
        output.write_text('OCV_BASIS flat_ocv\nworst slack max -0.040000\n'
                          'worst slack min 0.200000\n')

    monkeypatch.setattr(native, '_run', tool_writes)
    result = REAL_NATIVE_MEASURE(ctx, state, tmp_path / 'native')
    assert result['setup_ws_min'] == -0.04
    assert result['native_sdc_sha256'] == contract.digest(sdc)


def test_native_sdc_derate_parser_refuses_nonformal_commands(tmp_path):
    """The SDC reader recognizes executable Tcl, never prose or a near-match."""
    runner = importlib.import_module('phase3_one_shot_runner')
    early = runner._FLAT_OCV_DERATE_EARLY
    late = runner._FLAT_OCV_DERATE_LATE
    ctx = {'derate': [early, late]}
    out = tmp_path / 'native'
    out.mkdir()
    valid = write(tmp_path / 'valid.sdc',
                  f'# no derate claim in this comment\n'
                  f'set_timing_derate -early {early:.4f}\n'
                  f'set_timing_derate -late {late:.4f}\n')
    measured, _, _ = native._measurement_sdc(ctx, valid, out)
    assert measured.read_text() == '# no derate claim in this comment\n'
    wrong = write(tmp_path / 'wrong.sdc',
                  f'set_timing_derate -early {early:.4f}\n'
                  'set_timing_derate -late 1.10\n')
    with pytest.raises(contract.Refusal, match='NATIVE_POSTROUTE_OCV_MISMATCH'):
        native._measurement_sdc(ctx, wrong, out)
    malformed = write(tmp_path / 'malformed.sdc',
                      f'set_timing_derate -early {early:.4f}\n'
                      f'set_timing_derate -late {late:.4f} -cell_delay\n')
    with pytest.raises(contract.Refusal, match='NATIVE_POSTROUTE_OCV_AMBIGUOUS'):
        native._measurement_sdc(ctx, malformed, out)

def _sta_metrics(setup, hold, drv=(0, 0, 0), corners=CORNERS):
    metrics = {}
    for c in corners:
        metrics[f'timing__setup__ws__corner:{c}'] = setup.get(c, 5.0) if isinstance(setup, dict) else setup + (0 if 'ss' in c else 4)
        metrics[f'timing__hold__ws__corner:{c}'] = hold.get(c, 0.5) if isinstance(hold, dict) else hold + (0 if 'ss' in c else 0.3)
        for kind, n in zip(('slew', 'cap', 'fanout'), drv):
            metrics[f'design__max_{kind}_violation__count__corner:{c}'] = n if 'ss' in c else 0
    return metrics


def test_the_summary_is_the_worst_of_every_declared_corner():
    s = prr.summarize(_sta_metrics(0.7, 0.1, (2, 1, 0)), CORNERS)
    assert s['setup_ws_min'] == 0.7 and s['hold_ws_min'] == 0.1
    assert s['drv_count'] == 3 and s['unmeasured_corners'] == []


def test_a_corner_the_tool_did_not_report_leaves_the_summary_unmeasured():
    m = _sta_metrics(0.7, 0.1)
    del m['timing__hold__ws__corner:nom_ff_n40C_5v50']
    s = prr.summarize(m, CORNERS)
    assert s['setup_ws_min'] is None and s['hold_ws_min'] is None and s['drv_count'] is None
    assert s['unmeasured_corners'] == ['nom_ff_n40C_5v50']


def test_drv_pin_census_counts_distinct_pairs_across_scenes(tmp_path):
    corners = ('ss_a', 'ss_b')
    metrics = _sta_metrics(1.0, 0.2, (0, 0, 1), corners=corners)
    # Both scenes have one fanout violator.  The identity decides whether this
    # is one residual check or two distinct checks across the scene union.
    for corner, pin in zip(corners, ('u1/Y', 'u1/Y')):
        log = tmp_path / corner / 'sta.log'
        log.parent.mkdir(parents=True)
        log.write_text(f'Max Slew\nmax slew violation count 0\n'
                       f'Max Capacitance\nmax cap violation count 0\n'
                       f'Max Fanout\n{pin} 1.0 2.0 -1.0 (VIOLATED)\n'
                       'max fanout violation count 1\n')
    summary = prr.summarize(metrics, corners)
    census = prr.drv_pin_census(tmp_path, summary, corners)
    assert census['drv_pin_checks_state'] == 'PASS'
    assert census['drv_pin_checks'] == [['u1/Y', 'fanout']]
    assert prr.fanout_residue({**summary, **census}, corners)['violations'] == 1
    log = tmp_path / 'ss_b' / 'sta.log'
    log.write_text(log.read_text().replace('u1/Y', 'u2/Y'))
    assert prr.drv_pin_census(tmp_path, summary, corners)['drv_pin_checks'] == [
        ['u1/Y', 'fanout'], ['u2/Y', 'fanout']]


def test_final_non_fanout_drv_residue_keeps_step32_failed():
    report = {'corners': ['tt'], 'final': {
        'drv': {'fanout': {'tt': 0}}, 'drv_count': 1}}
    prr._set_final_fanout_verdict(report)
    prr._set_final_drv_verdict(report)
    assert report['final_fanout']['verdict'] == 'PASS'
    assert report['verdict'] == 'FAIL'
    assert report['code'] == 'LL_PRR_DRV_VIOLATION'
    assert prr.summarize(_sta_metrics(0.7, 0.1), [])['setup_ws_min'] is None


def _impl_with(tmp_path, measurement, antenna=0):
    impl = tmp_path / 'impl'
    sta = put(tmp_path / 'sta/state_out.json', {'metrics': {}})
    put(impl / prr.CURRENT, {'candidate': None, 'measurement': dict(
        measurement, drv_members=[], antenna_nets=antenna, sta_state=str(sta),
        sta_state_sha256=contract.digest(sta))})
    return impl, sta


def test_measure_reads_the_adopted_candidate_and_refuses_what_it_cannot_answer(tmp_path):
    impl, sta = _impl_with(tmp_path, {'setup_ws_min': -0.2, 'hold_ws_min': 0.1, 'drv_count': 3})
    out = tmp_path / 'm.json'
    assert prr.measure(impl, 'setup', out) == 0
    assert json.loads(out.read_text())['value'] == -0.2
    assert prr.measure(impl, 'antenna', out) == 0 and json.loads(out.read_text())['value'] == 0
    impl2, _ = _impl_with(tmp_path / 'b', {'setup_ws_min': None})
    assert prr.measure(impl2, 'setup', out) == prr.RC_UNDETERMINED
    sta.write_text('{"metrics": {"changed": 1}}')          # not the adopted state
    assert prr.measure(impl, 'setup', out) == prr.RC_UNDETERMINED
    assert prr.measure(tmp_path / 'nothing', 'hold', out) == prr.RC_UNDETERMINED


# ------------------------------------------------------ the registry binding ---

def test_the_repair_actuator_and_its_domains_are_executable_and_in_the_tree():
    reg = closure.load_registry(REGISTRY)
    assert reg.verify_bindings() == []
    act = reg.actuators['timing.repair_setup']
    assert act.binding is closure.Binding.EXECUTABLE
    assert act.program_path() == PROGRAMS / 'librelane_postroute_repair.py'
    for name in ('timing.setup', 'timing.hold', 'timing.drv', 'antenna.violations'):
        assert name in act.remeasure_domains
        dom = reg.domains[name]
        assert dom.binding is closure.Binding.EXECUTABLE, name
        assert dom.program_path() == PROGRAMS / 'librelane_postroute_repair.py'
    for cid in prr.CONTROLLERS:
        assert reg.controllers[cid].actuator_id == 'timing.repair_setup'
    # Every actuator parameter reaches a variable the plugin step declares.
    assert set(act.parameters) == set(prr.PARAM_VARS)
    assert reg.controllers['postroute.repair_drv'].plan == (
        {'bounded_drive_strength': True, 'cap_margin_pct': 10},
        {'bounded_drive_strength': True, 'cap_margin_pct': 20},
        {'bounded_drive_strength': True, 'max_wire_length_um': 0},
        {'targeted_cap_buffer': True},)
    # The native plugin already supports repair_design -cap_margin.  The DRV
    # controller must carry that parameter through instead of retrying the
    # exact same max-cap no-op at every rung.
    assert prr.PARAM_VARS['cap_margin_pct'] == 'VIBEIC_PRR_CAP_MARGIN_PCT'
    assert act.bind_params({'bounded_drive_strength': True,
                            'cap_margin_pct': 10})['cap_margin_pct'] == 10
    assert prr.PARAM_VARS['max_wire_length_um'] == 'VIBEIC_PRR_MAX_WIRE_LENGTH'
    assert act.bind_params({'bounded_drive_strength': True,
                            'max_wire_length_um': 0})['max_wire_length_um'] == 0


@pytest.mark.parametrize('failed_half', ('drc', 'lvs'))
@pytest.mark.parametrize('actuator', ('max_wire', 'targeted_cap'))
def test_geometry_drv_improvement_cannot_replace_current_when_fresh_pv_fails(
        tmp_path, monkeypatch, failed_half, actuator):
    """The max-wire actuator changes geometry, so old-geometry PV is unusable.

    Even a real DRV improvement stays rejected when either fresh sign-off half
    says FAIL; rollback means the exact current.json bytes remain adopted.
    """
    project, arm, impl, _shim = _scenario_impl(
        tmp_path, baseline=(1.0, 0.4, (0, 1, 0)),
        candidates=[_cand(0.9, 0.4, (0, 0, 0))])
    ns = {}
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    _shim_close_arm(ns, monkeypatch)
    current = json.loads((impl / prr.CURRENT).read_text())
    input_state = Path(current['repair_input'])
    baseline_def = write(tmp_path / 'baseline.def',
                         'UNITS DISTANCE MICRONS 1000 ;\n'
                         'DIEAREA ( 0 0 ) ( 3000000 2400000 ) ;\n')
    put(input_state, {'def': str(baseline_def)})
    before = (impl / prr.CURRENT).read_bytes()

    def pv_gate(_ctx, _state, lane):
        assert lane == '32-cand01'
        return {
            'drc': {'verdict': 'FAIL' if failed_half == 'drc' else 'PASS',
                    'scope': {'gds_sha256': 'd' * 64, 'def_sha256': 'e' * 64}},
            'lvs': {'verdict': 'FAIL' if failed_half == 'lvs' else 'PASS',
                    'scope': {'gds_sha256': 'd' * 64, 'def_sha256': 'e' * 64}},
        }

    monkeypatch.setattr(prr, '_candidate_native_signoff', pv_gate)
    requested = ({'bounded_drive_strength': True, 'max_wire_length_um': 0}
                 if actuator == 'max_wire' else {'targeted_cap_buffer': True})
    params = closure.load_registry(REGISTRY).actuators[
        'timing.repair_setup'].bind_params(requested)
    assert prr.actuate(impl, params) == 0
    resolved = json.loads((project / 'phase3/librelane/32-config/'
                           'Vibeic.PostRouteRepair@32-cand01.json').read_text())
    if actuator == 'max_wire':
        assert resolved['VIBEIC_PRR_MAX_WIRE_LENGTH'] == 800
    else:
        assert resolved['VIBEIC_PRR_TARGETED_CAP_BUFFER'] is True
    assert resolved['VIBEIC_PRR_CAP_MARGIN_PCT'] == 0
    assert (impl / prr.CURRENT).read_bytes() == before
    row = json.loads((arm / prr.LEDGER).read_text())['candidates'][-1]
    assert row['decision'] == 'REFUSED'
    assert row['native_signoff'][failed_half]['verdict'] == 'FAIL'
    assert f'fresh sign-off {failed_half.upper()} is FAIL' in row['reason']


def test_bounded_drive_strength_cli_is_strict_boolean():
    assert prr._bool_arg('true') is True
    assert prr._bool_arg('0') is False
    with pytest.raises(prr.argparse.ArgumentTypeError, match='expected true/false'):
        prr._bool_arg('maybe')


def _resume_fixture(tmp_path):
    project = tmp_path / 'project'
    impl = project / prr.ARM_REL / prr.IMPL_DIR
    measurement = {
        'sta_state_sha256': 'a' * 64, 'native_odb_sha256': 'b' * 64,
        'drv_count': 1, 'drv_pin_checks_state': 'PASS',
        'drv_pin_checks': [['u/wire/Z', 'cap']], 'antenna_nets': 0,
    }
    put(project / prr.REPORT_REL, {
        'verdict': 'FAIL', 'code': 'LL_PRR_DRV_VIOLATION',
        'adopted': '32-cand01', 'final': measurement,
        'closure': [], 'candidates': []})
    put(impl / prr.CURRENT, {
        'candidate': '32-cand01', 'measurement': measurement,
        'repair_state': '/project/old/state_out.json'})
    put(impl / prr.CONTEXT, {'project': str(project)})
    put(project / prr.ARM_REL / prr.LEDGER, {'candidates': []})
    return project, impl, measurement


def _fresh_resume_fixture(tmp_path):
    project, impl, measurement = _resume_fixture(tmp_path)
    lane = project / 'phase3/librelane/32-cand01'
    pnr = project / 'phase3/stage3/pnr'
    files = {
        'def': write(lane / '01-vibeic-postrouterepair/top.def', 'current def\n'),
        'nl': write(lane / '01-vibeic-postrouterepair/top.nl.v', 'module top; endmodule\n'),
        'sdc': write(pnr / 'constraint.sdc', 'create_clock -period 10 clk\n'),
        'odb': write(lane / '01-vibeic-postrouterepair/top.odb', 'native odb\n'),
        'model': write(project / 'models/cells.lib', 'library cells {}\n'),
    }
    state = put(lane / '01-vibeic-postrouterepair/state_out.json',
                {key: str(files[key]) for key in ('def', 'nl', 'sdc', 'odb')})
    sta = put(lane / '04-openroad-stapostpnr/state_out.json',
              {key: str(files[key]) for key in ('def', 'nl', 'sdc', 'odb')})
    put(sta.parent / 'input_fingerprint.json', {'state_files': {
        str(files['sdc']): contract.digest(files['sdc']),
        str(files['odb']): contract.digest(files['odb']),
    }})
    live_def = write(pnr / 'routed.def', files['def'].read_text())
    live_nl = write(pnr / 'top_pnr.v', files['nl'].read_text())
    put(project / 'reports/phase3/librelane_postroute_repair_handoff.json', {
        'state': str(state), 'state_sha256': contract.digest(state),
        'views': {
            'def': {'source': str(files['def']), 'source_sha256': contract.digest(files['def']),
                    'dest': str(live_def), 'dest_sha256': contract.digest(live_def)},
            'nl': {'source': str(files['nl']), 'source_sha256': contract.digest(files['nl']),
                   'dest': str(live_nl), 'dest_sha256': contract.digest(live_nl)},
        }})
    ctx = {'project': str(project), 'image': 'image@sha256:' + '1' * 64,
           'pdk': 'processA', 'mounts': [[str(project / 'pdk'), '/pdk']]}
    put(impl / prr.CONTEXT, ctx)
    current = json.loads((impl / prr.CURRENT).read_text())
    current.update(repair_folder=str(lane / '01-vibeic-postrouterepair'),
                   repair_state=str(state), repair_input=str(state))
    current['measurement'].update(
        sta_state=str(sta), sta_state_sha256=contract.digest(sta),
        native_odb_sha256=contract.digest(files['odb']))
    put(impl / prr.CURRENT, current)
    report = json.loads((project / prr.REPORT_REL).read_text())
    report['final'] = current['measurement']
    put(project / prr.REPORT_REL, report)
    return project, impl, files


@pytest.mark.parametrize('view', ('def', 'nl', 'sdc', 'odb'))
def test_resume_drv_refuses_each_changed_live_or_adopted_subject_before_controller(
        tmp_path, monkeypatch, view):
    project, _impl, files = _fresh_resume_fixture(tmp_path)
    monkeypatch.setattr(
        prr, '_validate_resume_readset',
        lambda *_a: {'verdict': 'PASS',
                     'next_actuator_plugin': {
                         'postroute_repair.tcl': 'current'}})
    entered = []
    monkeypatch.setattr(closure, 'ClosureController',
                        lambda *_a, **_k: entered.append(True))
    files[view].write_text(files[view].read_text() + 'changed\n')
    with pytest.raises(contract.Refusal, match='LL_PRR_RESUME_SUBJECT_STALE'):
        prr.resume_drv(project)
    assert entered == []


def test_resume_drv_unchanged_subject_enters_controller(tmp_path, monkeypatch):
    project, _impl, _files = _fresh_resume_fixture(tmp_path)
    monkeypatch.setattr(
        prr, '_validate_resume_readset',
        lambda *_a: {'verdict': 'PASS',
                     'next_actuator_plugin': {
                         'postroute_repair.tcl': 'current'}})
    entered = []

    class StopHere:
        def __init__(self, *_a, **_k):
            entered.append(True)

        def run_controller(self, _controller):
            raise RuntimeError('positive reached controller')

    monkeypatch.setattr(closure, 'ClosureController', StopHere)
    with pytest.raises(RuntimeError, match='positive reached controller'):
        prr.resume_drv(project)
    assert entered == [True]


def _install_resume_readset(project, impl, files, monkeypatch):
    lane = project / 'phase3/librelane/32-cand01'
    ctx = json.loads((impl / prr.CONTEXT).read_text())
    Path(ctx['mounts'][0][0]).mkdir(parents=True, exist_ok=True)
    image_identity = {
        'image': ctx['image'], 'image_id': 'sha256:' + '1' * 64,
        'repo_digests': [ctx['image']], 'network_mode': 'none',
        'memory': 17179869184, 'memory_swap': 17179869184,
        'auto_remove': True,
    }
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda _image: dict(image_identity, cid='c' * 64))
    producer_plugins = contract._plugin_digests(prr.REPAIR_STEP)
    producer_tree = project / '.vibeic/runtime-program-trees/fixture-producer'
    manifest_files = {}
    for rel, digest in producer_plugins.items():
        source = PROGRAMS / rel
        target = producer_tree / 'plugin/programs' / rel
        write(target, source.read_text())
        assert contract.digest(target) == digest
        manifest_files[f'programs/{rel}'] = digest
    put(producer_tree / 'manifest.json', {'files': manifest_files})
    folders = {}
    for number, step in enumerate((prr.REPAIR_STEP, *prr.MEASURE_STEPS), 1):
        folder = lane / (f'{number:02d}-' + step.lower().replace('.', '-'))
        if step == prr.REPAIR_STEP:
            folder = lane / '01-vibeic-postrouterepair'
        folder.mkdir(parents=True, exist_ok=True)
        state_out = folder / 'state_out.json'
        if not state_out.is_file():
            put(state_out, {key: str(files[key]) for key in ('def', 'nl', 'sdc', 'odb')})
        state_in = put(folder / 'state_in.json',
                       {key: str(files[key]) for key in ('def', 'nl', 'sdc', 'odb')})
        config = put(folder / 'config.json', {'MODEL_FILE': str(files['model'])})
        pdk_root = put(folder / 'pdk_root.json', {
            'requested_mounts': [[str(Path(ctx['mounts'][0][0]).resolve()), '/pdk']]})
        write(folder / 'invocation.log', 'native tool ran\n')
        fp = {
            'step': step, 'image': ctx['image'],
            'config': contract.digest(config), 'state': contract.digest(state_in),
            'state_files': {str(files[key]): contract.digest(files[key])
                            for key in ('def', 'nl', 'sdc', 'odb')},
            'config_files': {str(files['model']): contract.digest(files['model'])},
            'local_image': image_identity, 'openroad_aliases': {},
        }
        if step == prr.REPAIR_STEP:
            fp['plugin'] = producer_plugins
        if step == 'OpenROAD.RCX':
            fp['rcx_pdk_files'] = {str(files['model']): contract.digest(files['model'])}
        if step == 'OpenROAD.STAPostPNR':
            fp['liberty_files'] = {str(files['model']): contract.digest(files['model'])}
        put(folder / 'input_fingerprint.json', fp)
        hashes = {name: contract.digest(folder / name) for name in (
            'state_out.json', 'state_in.json', 'config.json', 'pdk_root.json',
            'invocation.log', 'input_fingerprint.json')}
        for path in files.values():
            if path.is_relative_to(folder):
                hashes[str(path.relative_to(folder))] = contract.digest(path)
        put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': hashes})
        folders[step] = folder
    context = json.loads((impl / prr.CONTEXT).read_text())
    context['configs'] = {step: str(folder / 'config.json')
                          for step, folder in folders.items()}
    put(impl / prr.CONTEXT, context)
    ledger_path = project / prr.ARM_REL / prr.LEDGER
    ledger = json.loads(ledger_path.read_text())
    adopted = next((row for row in ledger['candidates']
                    if row.get('candidate') == '32-cand01'), None)
    if adopted is None:
        adopted = {'candidate': '32-cand01'}
        ledger['candidates'].append(adopted)
    adopted['config'] = str(folders[prr.REPAIR_STEP] / 'config.json')
    put(ledger_path, ledger)
    return folders, image_identity


@pytest.mark.parametrize('changed', ('config', 'model', 'pdk', 'tool',
                                     'producer_source', 'producer_missing'))
def test_resume_drv_readset_change_refuses_before_controller(
        tmp_path, monkeypatch, changed):
    project, impl, files = _fresh_resume_fixture(tmp_path)
    folders, image_identity = _install_resume_readset(project, impl, files, monkeypatch)
    if changed == 'config':
        (folders[prr.REPAIR_STEP] / 'config.json').write_text('{"changed":true}\n')
    elif changed == 'model':
        files['model'].write_text('changed model\n')
    elif changed == 'pdk':
        (folders['OpenROAD.RCX'] / 'pdk_root.json').write_text('{"changed":true}\n')
    elif changed == 'producer_source':
        producer = next((project / '.vibeic/runtime-program-trees').glob(
            '*/plugin/programs/librelane_plugins/librelane_plugin_vibeic/postroute_repair.tcl'))
        producer.write_text(producer.read_text() + '# stale\n')
    elif changed == 'producer_missing':
        next((project / '.vibeic/runtime-program-trees').glob(
            '*/manifest.json')).unlink()
    else:
        monkeypatch.setattr(contract, 'local_image_attestation',
                            lambda _image: dict(image_identity, image_id='sha256:' + '2' * 64))
    entered = []
    monkeypatch.setattr(closure, 'ClosureController',
                        lambda *_a, **_k: entered.append(True))
    with pytest.raises(contract.Refusal, match='LL_PRR_RESUME_READSET_STALE'):
        prr.resume_drv(project)
    assert entered == []


def test_resume_drv_unchanged_full_readset_enters_controller(tmp_path, monkeypatch):
    project, impl, files = _fresh_resume_fixture(tmp_path)
    _install_resume_readset(project, impl, files, monkeypatch)
    entered = []

    class StopHere:
        def __init__(self, *_a, **_k):
            entered.append(True)

        def run_controller(self, _controller):
            raise RuntimeError('full readset reached controller')

    monkeypatch.setattr(closure, 'ClosureController', StopHere)
    with pytest.raises(RuntimeError, match='full readset reached controller'):
        prr.resume_drv(project)
    assert entered == [True]


def test_resume_drv_refuses_a_stale_current_pointer(tmp_path):
    project, impl, _ = _resume_fixture(tmp_path)
    current = json.loads((impl / prr.CURRENT).read_text())
    current['measurement']['sta_state_sha256'] = 'c' * 64
    put(impl / prr.CURRENT, current)
    with pytest.raises(contract.Refusal, match='LL_PRR_RESUME_CURRENT_MISMATCH'):
        prr.resume_drv(project)


def test_resume_drv_keeps_the_ledger_and_records_only_the_new_controller(
        tmp_path, monkeypatch):
    project, impl, measurement = _resume_fixture(tmp_path)
    old = {'candidate': '32-cand01', 'controller': 'postroute.repair_setup'}
    put(project / prr.ARM_REL / prr.LEDGER, {'candidates': [old]})
    repaired = dict(measurement, drv_count=0, drv_pin_checks=[])

    class FakeRun:
        def to_record(self):
            return {'controller': 'postroute.repair_drv', 'outcome': 'CONVERGED',
                    'iterations': [{'argv': ['actuate'], 'decision': 'PROMOTED',
                                    'decision_reason': 'DRV 1 -> 0'}]}

    class FakeController:
        def __init__(self, _reg, _impl, _work):
            pass

        def run_controller(self, controller):
            assert controller == 'postroute.repair_drv'
            put(project / prr.ARM_REL / prr.LEDGER, {'candidates': [old, {
                'candidate': '32-cand02', 'measurement': repaired}]})
            put(impl / prr.CURRENT, {
                'candidate': '32-cand02', 'measurement': repaired,
                'repair_state': '/project/new/state_out.json',
                'supply_ownership': {'verdict': 'PASS'}})
            return FakeRun()

    monkeypatch.setattr(closure, 'ClosureController', FakeController)
    monkeypatch.setattr(prr, '_validate_resume_subject',
                        lambda *_a: {'live_def_sha256': 'fixture'})
    monkeypatch.setattr(prr, '_validate_resume_readset',
                        lambda *_a: {'verdict': 'PASS',
                                     'next_actuator_plugin': {
                                         'postroute_repair.tcl': 'current'}})
    monkeypatch.setattr(prr, '_stamp_verdict',
                        lambda report: report.update(verdict='PASS', code=None))
    monkeypatch.setattr(prr, '_step32_drv_signoff', lambda *_a: None)
    monkeypatch.setattr(prr, '_publish_declared_repair', lambda *_a: None)
    report = prr.resume_drv(project)
    assert report['resume']['candidate_ledger_start'] == 1
    assert report['resume']['candidate_ledger_end'] == 2
    assert report['adopted'] == '32-cand02'
    assert report['candidates'][0] == old
    assert report['candidates'][1]['closure_decision'] == 'PROMOTED'


def test_resume_drv_skips_measured_global_noops_and_binds_targeted_frontdoor(
        tmp_path, monkeypatch):
    project, impl, measurement = _resume_fixture(tmp_path)
    prior = [{
        'candidate': f'32-cand0{index + 2}',
        'controller': 'postroute.repair_drv',
        # Native CLI parsing records number parameters as floats.  They must
        # compare equal to the registry's YAML integer spelling.
        'params': {'bounded_drive_strength': True,
                   'cap_margin_pct': float(margin)},
        'decision': 'REFUSED', 'closure_decision': 'ROLLED_BACK',
    } for index, margin in enumerate((10, 20))]
    prior.append({
        'candidate': '32-cand04', 'controller': 'postroute.repair_drv',
        'params': {'bounded_drive_strength': True,
                   'max_wire_length_um': 0.0},
        'decision': 'REFUSED', 'closure_decision': 'ROLLED_BACK',
    })
    put(project / prr.ARM_REL / prr.LEDGER, {'candidates': prior})
    seen = {}

    class FakeRun:
        def to_record(self):
            return {'controller': 'postroute.repair_drv', 'outcome': 'PLATEAU',
                    'iterations': []}

    class FakeController:
        def __init__(self, reg, _impl, _work):
            ctl = reg.controllers['postroute.repair_drv']
            seen['plan'] = ctl.plan
            seen['max_iterations'] = ctl.max_iterations
            act = reg.actuators[ctl.actuator_id]
            seen['argv'] = act.build_argv(_impl, act.bind_params(ctl.plan[0]))

        def run_controller(self, _controller):
            return FakeRun()

    monkeypatch.setattr(closure, 'ClosureController', FakeController)
    monkeypatch.setattr(prr, '_validate_resume_subject',
                        lambda *_a: {'live_def_sha256': 'fixture'})
    monkeypatch.setattr(prr, '_validate_resume_readset',
                        lambda *_a: {
                            'verdict': 'PASS',
                            'next_actuator_plugin': {
                                'postroute_repair.tcl': 'current'},
                        })
    monkeypatch.setattr(prr, '_stamp_verdict', lambda *_a: None)
    monkeypatch.setattr(prr, '_step32_drv_signoff', lambda *_a: None)
    monkeypatch.setattr(prr, '_publish_declared_repair', lambda *_a: None)
    prr.resume_drv(project)
    assert seen['plan'] == ({'targeted_cap_buffer': True},)
    assert seen['max_iterations'] == 1
    assert seen['argv'][-2:] == ['--targeted-cap-buffer', 'true']
    assert seen['argv'][seen['argv'].index('--max-wire-length-um') + 1] == '-1'
    assert seen['argv'][seen['argv'].index('--cap-margin-pct') + 1] == '0'
    assert json.loads((impl / prr.CURRENT).read_text())['measurement'] == measurement


@pytest.mark.parametrize(
    'decision,targeted,recorded,expected',
    [
        ('ACTUATOR_FAILED', True, {'postroute_repair.tcl': 'old'}, False),
        ('ACTUATOR_FAILED', True, {'postroute_repair.tcl': 'current'}, True),
        ('ACTUATOR_FAILED', False, {'postroute_repair.tcl': 'old'}, True),
        ('TOOL_REFUSED', True, {'postroute_repair.tcl': 'old'}, True),
        ('ACTUATOR_FAILED', True, None, True),
    ],
)
def test_resume_targeted_retry_requires_changed_proven_actuator(
        tmp_path, decision, targeted, recorded, expected):
    project = tmp_path / 'project'
    folder = project / 'phase3/librelane/32-cand07/01-vibeic-postrouterepair'
    folder.mkdir(parents=True)
    if recorded is not None:
        put(folder / 'input_fingerprint.json', {'plugin': recorded})
    row = {
        'decision': decision,
        'params': {'targeted_cap_buffer': targeted},
        'reason': ('LL_STEP_FAILED: Vibeic.PostRouteRepair: rc=255; '
                   '/project/phase3/librelane/32-cand07/'
                   '01-vibeic-postrouterepair/invocation.log'),
    }
    assert prr._attempted_by_current_actuator(
        project, {'project': '/project', 'mounts': []}, row,
        {'postroute_repair.tcl': 'current'}) is expected


def test_the_hold_buffer_budget_above_the_guardrail_is_refused_not_clamped():
    act = closure.load_registry(REGISTRY).actuators['timing.repair_setup']
    with pytest.raises(closure.ParameterError):
        act.bind_params({'hold_max_buffer_pct': 6})
    with pytest.raises(closure.ParameterError):
        act.bind_params({'max_utilization_pct': 50})


# ------------------------------------------------ the closure, end to end ---

LEF = textwrap.dedent('''\
    MACRO buf
      CLASS CORE ;
      PIN A
        DIRECTION INPUT ;
        USE SIGNAL ;
      END A
      PIN VDD
        DIRECTION INOUT ;
        USE POWER ;
      END VDD
      PIN VSS
        DIRECTION INOUT ;
        USE GROUND ;
      END VSS
    END buf
    ''')


def _def(extra_owned=True):
    specials = ('- VDD ( * VDD ) + USE POWER ;\n- VSS ( * VSS ) + USE GROUND ;\n'
                if extra_owned else
                '- VDD ( u1 VDD ) + USE POWER ;\n- VSS ( u1 VSS ) + USE GROUND ;\n')
    return ('VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            'COMPONENTS 2 ;\n- u1 buf + PLACED ( 0 0 ) N ;\n- hold1 buf + PLACED ( 10 0 ) N ;\n'
            'END COMPONENTS\nSPECIALNETS 2 ;\n' + specials + 'END SPECIALNETS\nEND DESIGN\n')


SHIM = textwrap.dedent('''\
    """Test shim: the real program with only `run_chain` (the docker run of a
    LibreLane step) replaced by a writer of the folders a real run leaves."""
    import json, os, sys, subprocess, signal
    from pathlib import Path
    sys.path.insert(0, os.environ["PRR_REAL_PROGRAMS"])
    import librelane_contract as ll
    import librelane_postroute_repair as prr
    import _native_postroute_timing as native
    SCENARIO = json.loads(Path(os.environ["PRR_SCENARIO"]).read_text())

    def run_chain(project, image, steps, *, mounts=None, lane=None, **kw):
        base = Path(project) / "phase3/librelane" / lane
        spec = SCENARIO[lane]
        if spec.get("crash"):
            crashed = subprocess.run([sys.executable, "-c",
                "import os, signal, resource; "
                "resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); "
                "os.kill(os.getpid(), signal.SIGSEGV)"])
            assert crashed.returncode == -signal.SIGSEGV
            log = base / "01-vibeic-postrouterepair/invocation.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("OpenROAD: Signal 11 in rsz::Resizer::repairSetup\\n")
            raise ll.Refusal("LL_STEP_FAILED", f"Vibeic.PostRouteRepair: rc={crashed.returncode}; {log}")
        if spec.get("refuse"):
            # The step's own measured "no": it prints its named refusal and
            # exits 1, and run_chain books LL_STEP_FAILED (no signal).
            log = base / "01-vibeic-postrouterepair/invocation.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("[INFO] repair done\\n" + spec["refuse"] + "\\n")
            raise ll.Refusal("LL_STEP_FAILED", f"Vibeic.PostRouteRepair: rc=1; {log}")
        folders = []
        for i, (step, cfg, state) in enumerate(steps, 1):
            folder = base / f"{i:02d}-{step.lower().replace('.', '-')}"
            folder.mkdir(parents=True, exist_ok=True)
            if step == prr.REPAIR_STEP:
                d = folder / "top.def"
                d.write_text(spec["def"])
                metrics = dict(spec["repair_metrics"])
                metrics.setdefault("vibeic__prr__before__unrouted__count", 0)
                metrics.setdefault("vibeic__prr__after__unrouted__count", 0)
                metrics.setdefault("vibeic__prr__unrouted__added", 0)
                doc = {"def": str(d), "metrics": metrics}
            elif step.endswith("CheckAntennas"):
                doc = {"metrics": spec.get("antenna_metrics", {})}
            else:
                doc = {"metrics": spec["sta_metrics"] if step.endswith("STAPostPNR") else {}}
            (folder / "state_out.json").write_text(json.dumps(doc))
            if step.endswith("STAPostPNR"):
                corners = {key.split("__corner:", 1)[1]
                           for key in spec["sta_metrics"] if "__corner:" in key}
                for corner in corners:
                    lines = []
                    for kind, title in (("slew", "Max Slew"),
                                        ("cap", "Max Capacitance"),
                                        ("fanout", "Max Fanout")):
                        count = spec["sta_metrics"].get(
                            f"design__max_{kind}_violation__count__corner:{corner}")
                        if count is None:
                            continue
                        lines.append(title)
                        lines.extend(f"fixture/pin_{i} 1.0 2.0 -1.0 (VIOLATED)"
                                     for i in range(count))
                        lines.append(f"max {kind} violation count {count}")
                    log = folder / corner / "sta.log"
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text("\\n".join(lines) + "\\n")
            folders.append(folder)
        return folders

    ll.run_chain = run_chain
    def native_scene(ctx, repair_state, out_dir):
        lane = repair_state.parent.parent.name
        spec = SCENARIO[lane]
        summary = prr.summarize(spec["sta_metrics"], ctx["corners"])
        result = {k: summary[k] for k in ("setup_ws", "hold_ws",
                                         "setup_ws_min", "hold_ws_min")}
        if "native_setup" in spec:
            result["setup_ws_min"] = spec["native_setup"]
            result["setup_ws"] = {c: spec["native_setup"] for c in ctx["corners"]}
        return result
    native.measure = native_scene
    sys.exit(prr.main())
    ''')


def _scenario_impl(tmp_path, baseline, candidates):
    """An implementation root exactly as `run` leaves it after its baseline,
    and a shim program directory whose `run_chain` plays `candidates`."""
    project = tmp_path / 'proj'
    lef = write(tmp_path / 'cells.lef', LEF)
    cfg = put(project / 'phase3/librelane/32-config/Vibeic.PostRouteRepair.json',
              {'meta': {'step': prr.REPAIR_STEP}, 'CELL_LEFS': [str(lef)]})
    ctx = {'project': str(project), 'image': 'img', 'pdk': 'pdk', 'mounts': [],
           'configs': {step: str(cfg) for step in (prr.REPAIR_STEP, *prr.MEASURE_STEPS)},
           'corners': CORNERS}
    arm = project / prr.ARM_REL
    impl = arm / prr.IMPL_DIR
    put(impl / prr.CONTEXT, ctx)
    sta = put(project / 'phase3/librelane/32-base/03-sta/state_out.json',
              {'metrics': _sta_metrics(*baseline)})
    input_state = put(project / 'phase3/librelane/32-config/bridge/state_in.json', {'def': 'x'})
    base_summary = prr.summarize(_sta_metrics(*baseline), CORNERS)
    base_pairs = [[f'fixture/pin_{i}', kind]
                  for kind, n in zip(('slew', 'cap', 'fanout'),
                                     baseline[2] if len(baseline) > 2 else (0, 0, 0))
                  for i in range(n)]
    put(impl / prr.CURRENT, {'candidate': None, 'repair_input': str(input_state),
                            'repair_state': str(input_state),
                            'measurement': dict(base_summary,
                                                drv_pin_checks_state='PASS',
                                                drv_pin_checks=base_pairs,
                                                drv_members=base_pairs,
                                                antenna_nets=0, antenna_pins=0,
                                                sta_state=str(sta),
                                                sta_state_sha256=contract.digest(sta))})
    scenario = {f'32-cand{i:02d}': c for i, c in enumerate(candidates, 1)}
    put(tmp_path / 'scenario.json', scenario)
    shim = tmp_path / 'shim'
    write(shim / 'librelane_postroute_repair.py', SHIM)
    return project, arm, impl, shim


def _controller(impl, arm, shim, monkeypatch, tmp_path):
    monkeypatch.setenv('PRR_REAL_PROGRAMS', str(PROGRAMS))
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    reg = closure.load_registry(REGISTRY, programs_dir=shim)
    return closure.ClosureController(reg, impl, arm / 'closure')


def _ant(nets):
    return {} if nets is None else {'antenna__violating__nets': nets,
                                    'antenna__violating__pins': nets}


def _cand(setup, hold, drv=(0, 0, 0), *, changed=1, owned=True, antenna=0):
    return {'def': _def(owned), 'sta_metrics': _sta_metrics(setup, hold, drv),
            'antenna_metrics': _ant(antenna),
            'repair_metrics': {'vibeic__prr__changed': changed}}


def _shim_close_arm(ns, monkeypatch):
    """The SHIM's run_chain and native-scene writers, in-process, for a
    direct `close_arm` call (the baseline census runs in this process)."""
    import _native_postroute_timing as native
    body = SHIM.replace('sys.path.insert(0, os.environ["PRR_REAL_PROGRAMS"])', '')
    for line in ('ll.run_chain = run_chain\n', 'native.measure = native_scene\n',
                 'sys.exit(prr.main())\n'):
        assert line in body, line
        body = body.replace(line, '')
    exec(compile(body, 'shim', 'exec'), ns)
    monkeypatch.setattr(contract, 'run_chain', ns['run_chain'])
    monkeypatch.setattr(native, 'measure', ns['native_scene'])


def test_native_signal_is_failed_and_retried_with_a_different_order(tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(1.0, 0.2, (0, 0, 3)),
        candidates=[{'crash': True}])
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    scenario['32-cand01-retry'] = _cand(1.0, 0.2, (0, 0, 0))
    put(tmp_path / 'scenario.json', scenario)
    run = _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_drv')
    rows = json.loads((arm / prr.LEDGER).read_text())['candidates']
    assert run.outcome is closure.Outcome.CONVERGED
    assert len(run.iterations) == 1 and run.rolled_back == 0
    assert rows[0]['decision'] == 'ACTUATOR_FAILED'
    assert rows[0]['measurement_status'] == 'NOT_MEASURED'
    assert 'Signal 11' in rows[0]['tool_crash_signature']
    assert 'rc=-11' in rows[0]['reason']
    assert rows[1]['move_sequence'] == 'hold_first'
    assert rows[1]['config'] != rows[0]['config']
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] == '32-cand01-retry'


def test_two_native_failures_are_not_a_measured_plateau(tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(1.0, 0.2, (0, 0, 3)), candidates=[{'crash': True}])
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    scenario['32-cand01-retry'] = {'crash': True}
    put(tmp_path / 'scenario.json', scenario)
    run = _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_drv')
    assert run.outcome is closure.Outcome.NOT_MEASURED
    assert run.iterations[0].decision == 'ACTUATOR_FAILED'
    assert run.rolled_back == 0 and run.promoted == 0
    assert 'Signal 11' in json.loads((arm / prr.LEDGER).read_text())['candidates'][1]['tool_crash_signature']


#: The plugin step's own named candidate refusals (postroute_repair.tcl): a
#: measured tool "no" for THIS candidate, not a failed actuator.
NAMED_REFUSALS = (
    'VIBEIC_PRR_ECO_ROUTE_REFUSED: the scoped route added whole-design violations '
    'on every attempt (3); the candidate is not written',
    'VIBEIC_PRR_LOST_ROUTE_REFUSED: 2 signal net(s) the input had routed carry no '
    'wire after the repair: [net1 net2]; the candidate is not written',
    'LL_PRR_FANOUT_LIMIT_BROKEN: 1 net(s) over max_fanout 4 that became newly over '
    'or worsened after repair_design: net7 5; the candidate is not written',
    'VIBEIC_PRR_PLACEMENT_REFUSED: check_placement: DPL-0033; the candidate is '
    'not written',
)


def test_every_check_placement_is_a_named_refusal():
    """check_placement ends the step on an illegal placement; every call goes
    through the step's own named refusal, so no tool error text has to be
    read to tell a refused candidate from a crash."""
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    calls = [line.strip() for line in tcl.splitlines()
             if 'check_placement -verbose' in line
             and not line.lstrip().startswith('#')]
    assert len(calls) >= 3 and all(
        c == 'if {[catch {check_placement -verbose} err]} {' for c in calls), calls
    assert tcl.count('VIBEIC_PRR_PLACEMENT_REFUSED:') == len(calls)
    assert 'VIBEIC_PRR_PLACEMENT_REFUSED:' in tcl
    assert prr._STEP_REFUSAL.match('VIBEIC_PRR_PLACEMENT_REFUSED: check_placement: x')


@pytest.mark.skipif(not __import__('shutil').which('tclsh'), reason='tclsh absent')
@pytest.mark.parametrize('placement_ok', (True, False))
def test_targeted_cap_checks_placement_before_direct_insert(tmp_path, placement_ok):
    """The targeted front door enters its actuator only after the full public
    placement check succeeds.  A bad placement is a named refusal and cannot
    create a buffer or write candidate geometry."""
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    start = tcl.index('if {$::vic_targeted_cap} {')
    end = tcl.index('\n\n# Removing a buffer', start)
    section = tmp_path / 'targeted_branch.tcl'
    section.write_text(tcl[start:end])
    harness = tmp_path / 'harness.tcl'
    harness.write_text(textwrap.dedent(f'''\
        set ::vic_targeted_cap 1
        set ::events [list]
        set ::env(VIBEIC_PRR_SETUP_SEQUENCE) default
        proc check_placement {{args}} {{
            lappend ::events CHECK_PLACEMENT
            {'return' if placement_ok else 'error "DPL-0033"'}
        }}
        proc vic_targeted_cap_buffer {{}} {{lappend ::events ACTUATOR}}
        proc log_cmd {{args}} {{lappend ::events REPAIR_DESIGN}}
        rename exit real_exit
        proc exit {{code}} {{lappend ::events EXIT; error "EXIT:$code"}}
        set rc [catch {{source {{{section}}}}} err]
        puts "RC=$rc ERR=$err EVENTS=$::events"
    '''))
    result = subprocess.run(['tclsh', str(harness)], text=True,
                            capture_output=True, check=True)
    if placement_ok:
        assert 'RC=0' in result.stdout
        assert 'EVENTS=CHECK_PLACEMENT ACTUATOR' in result.stdout
    else:
        assert 'RC=1 ERR=EXIT:1 EVENTS=CHECK_PLACEMENT EXIT' in result.stdout
        assert 'ACTUATOR' not in result.stdout
        assert 'VIBEIC_PRR_PLACEMENT_REFUSED: check_placement: DPL-0033' in result.stderr


@pytest.mark.parametrize('line', NAMED_REFUSALS)
def test_a_named_step_refusal_keeps_the_pointer_and_the_ladder_goes_on(
        tmp_path, monkeypatch, line):
    """U7 wave 57 (1): a refusal the step prints by name (DRT-0712 scoped
    route, lost route, fanout limit, check_placement) is TOOL_REFUSED with rc 0:
    the pointer stays and the controller tries its next declared rung. Only a
    native failure is ACTUATOR_FAILED / NOT_MEASURED."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.5, 0.2),
        candidates=[{'refuse': line}, _cand(0.1, 0.2)])
    run = _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_setup')
    rows = json.loads((arm / prr.LEDGER).read_text())['candidates']
    assert [r['candidate'] for r in rows] == ['32-cand01', '32-cand02']
    assert rows[0]['decision'] == 'TOOL_REFUSED'
    assert rows[0]['measurement_status'] == 'MEASURED'
    assert rows[0]['tool_refusal'] == line
    assert rows[0].get('tool_crash_signature') is None
    assert 'move_sequence' not in rows[1], 'a named refusal is not retried'
    assert [it.decision for it in run.iterations] == ['ROLLED_BACK', 'PROMOTED']
    assert run.outcome is closure.Outcome.CONVERGED
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] == '32-cand02'


def test_a_crash_signature_outranks_a_refusal_line(tmp_path, monkeypatch):
    """A log that carries a signal line is a native failure even when a
    refusal line precedes it: the crash is what ended the step."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.5, 0.2),
        candidates=[{'refuse': NAMED_REFUSALS[0] +
                     '\nOpenROAD: Signal 11 in rsz::Resizer::repairSetup'}])
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    scenario['32-cand01-retry'] = {'crash': True}
    put(tmp_path / 'scenario.json', scenario)
    run = _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_setup')
    rows = json.loads((arm / prr.LEDGER).read_text())['candidates']
    assert rows[0]['decision'] == 'ACTUATOR_FAILED'
    assert 'Signal 11' in rows[0]['tool_crash_signature']
    assert rows[1]['move_sequence'] == 'hold_first'
    assert run.outcome is closure.Outcome.NOT_MEASURED


def test_close_arm_binds_each_row_to_its_own_controller(tmp_path, monkeypatch):
    """U7 wave 57 (2): the first controller ends ACTUATOR_FAILED (both the
    candidate and its retry crash); the second promotes. The adopted row is the
    second controller's PROMOTED row, never the first one's ACTUATOR_FAILED."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.5, -0.1), candidates=[{'crash': True}])
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    scenario['32-base'] = _cand(-0.5, -0.1, changed=0)
    scenario['32-cand01-retry'] = {'crash': True}
    scenario['32-cand03'] = _cand(-0.5, 0.1)
    put(tmp_path / 'scenario.json', scenario)
    monkeypatch.setenv('PRR_REAL_PROGRAMS', str(PROGRAMS))
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    ns = {}
    _shim_close_arm(ns, monkeypatch)
    ctx = json.loads((impl / prr.CONTEXT).read_text())
    state0 = Path(json.loads((impl / prr.CURRENT).read_text())['repair_input'])
    report = prr.close_arm(project, 'librelane', state0, image='img', pdk='pdk',
                           configs={k: Path(v) for k, v in ctx['configs'].items()},
                           corners=CORNERS, mounts=[], programs_dir=shim,
                           derate=(0.95, 1.05),
                           controllers=('postroute.repair_setup',
                                        'postroute.repair_hold'))
    assert report['adopted'] == '32-cand03'
    rows = {r['candidate']: r for r in report['candidates']}
    assert set(rows) == {'32-cand01', '32-cand01-retry', '32-cand03'}
    for lane in ('32-cand01', '32-cand01-retry'):
        assert rows[lane]['controller'] == 'postroute.repair_setup'
        assert rows[lane]['closure_decision'] == 'ACTUATOR_FAILED'
    assert rows['32-cand03']['controller'] == 'postroute.repair_hold'
    assert rows['32-cand03']['closure_decision'] == 'PROMOTED'
    setup_run, hold_run = report['closure']
    assert [r['candidate'] for r in setup_run['refused_candidates']] == [
        '32-cand01', '32-cand01-retry']
    assert hold_run['refused_candidates'] == []


def test_closure_discloses_a_refused_candidates_measured_nine(tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(1.0, 0.2, (0, 0, 36)),
        candidates=[_cand(1.0, 0.2, (0, 0, 9), antenna=1)])
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    scenario['32-base'] = _cand(1.0, 0.2, (0, 0, 36), changed=0)
    put(tmp_path / 'scenario.json', scenario)
    monkeypatch.setenv('PRR_REAL_PROGRAMS', str(PROGRAMS))
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    ns = {}
    _shim_close_arm(ns, monkeypatch)
    ctx = json.loads((impl / prr.CONTEXT).read_text())
    state0 = Path(json.loads((impl / prr.CURRENT).read_text())['repair_input'])
    report = prr.close_arm(project, 'librelane', state0, image='img', pdk='pdk',
                           configs={k: Path(v) for k, v in ctx['configs'].items()},
                           corners=CORNERS, mounts=[], programs_dir=shim,
                           derate=(0.95, 1.05),
                           controllers=('postroute.repair_drv',))
    refused = report['closure'][0]['refused_candidates'][0]
    assert refused['measured']['drv_count'] == 9
    assert refused['retained']['drv_count'] == 36
    assert refused['decision'] == 'ROLLED_BACK'


def _with_floors(impl, floors):
    ctx = json.loads((impl / prr.CONTEXT).read_text())
    ctx['floors'] = floors
    (impl / prr.CONTEXT).write_text(json.dumps(ctx))


def test_the_ll21_max_fanout_repair_is_adopted_with_setup_still_met(tmp_path, monkeypatch):
    """OWNER RULING (T102 r3), on the case measured on the spm LL15..21 chain:
    3 max_fanout violations per corner (27), the only fix costs setup
    +5.259 -> +3.086. A HARD-violation repair may spend MET setup slack down
    to the declared floor (spm declares none: WNS >= 0)."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.259, 0.391, (0, 0, 3)),
        candidates=[_cand(3.086, 0.391, (0, 0, 0))])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_drv')
    assert [it.decision for it in run.iterations] == ['PROMOTED'], run.to_record()
    assert run.outcome is closure.Outcome.CONVERGED
    assert 'hard-violation repair spent: timing.setup.wns_ns: 5.259 -> 3.086' \
        in run.iterations[0].decision_reason
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] == '32-cand01'


@pytest.mark.parametrize('changed', [0, 1])
def test_residual_fanout_refuses_even_a_noop_candidate(tmp_path, monkeypatch, changed):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.0, 0.2, (0, 0, 3)),
        candidates=[_cand(4.0, 0.2, (0, 0, 3), changed=changed)])
    _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_drv')
    rows = json.loads((arm / prr.LEDGER).read_text())['candidates']
    assert rows[0]['decision'] == 'REFUSED'
    assert rows[0]['fanout']['verdict'] == 'FAIL'
    assert rows[0]['fanout']['violations'] == 3
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None


def test_routed_fanout_failure_blocks_the_phase3_step(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    result = runner._postroute_repair_librelane_result(
        tmp_path, tmp_path / 'pnr',
        {'verdict': 'FAIL', 'code': 'LL_PRR_FANOUT_VIOLATION',
         'reason': 'declared postroute max fanout has 3 residual violations'},
        0.0, handed=False)
    assert result.status == 'FAIL'
    assert 'LL_PRR_FANOUT_VIOLATION' in result.detail
    assert result.reason_class == ''


def test_a_hard_repair_that_makes_setup_negative_is_rejected(tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(0.8, 0.391, (0, 0, 3)),
        candidates=[_cand(-0.05, 0.391, (0, 0, 0))])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_drv')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert 'below its floor 0.0' in run.iterations[0].decision_reason
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None


def test_a_fanout_reduction_with_one_remaining_violation_is_adopted_but_not_signed_off(
        tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.0, 0.4, (0, 0, 4)),
        candidates=[_cand(1.6, 0.4, (0, 0, 1))])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_drv')
    assert run.iterations[0].decision == 'PROMOTED'
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] == '32-cand01'
    row = json.loads((arm / prr.LEDGER).read_text())['candidates'][0]
    assert row['measurement']['drv_count'] == 1
    assert row['decision'] != 'REFUSED'


def test_hold_closure_can_adopt_with_unchanged_measured_drv_residue(
        tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.0, -0.335, (0, 0, 1)),
        candidates=[_cand(4.999, 0.326, (0, 0, 1))])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert run.iterations[0].decision == 'PROMOTED'
    final = json.loads((impl / prr.CURRENT).read_text())
    assert final['measurement']['hold_ws_min'] == 0.326
    assert final['measurement']['drv_count'] == 1


def test_unmeasured_candidate_drv_is_still_refused(tmp_path, monkeypatch):
    candidate = _cand(4.999, 0.326, (0, 0, 0))
    key = next(k for k in candidate['sta_metrics'] if 'max_fanout_violation' in k)
    del candidate['sta_metrics'][key]
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.0, -0.335, (0, 0, 1)),
        candidates=[candidate])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None


def test_the_deck_repairs_drv_after_timing_and_antenna_cell_insertion():
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    calls = [m.start() for m in re.finditer(r'^\s*log_cmd repair_design', tcl, re.M)]
    assert len(calls) >= 3
    assert calls[0] < tcl.index('log_cmd repair_timing {*}$setup_args')
    assert tcl.index('log_cmd repair_timing {*}$hold_args') < calls[1]
    assert calls[1] < tcl.index('vic_census after_timing_drv_recheck')
    assert tcl.index('log_cmd repair_antennas {*}$ant_args') < calls[-1]
    assert calls[-1] < tcl.index('# ---- 7. re-verify')


def test_post_antenna_drv_recheck_runs_even_without_a_fanout_row(tmp_path):
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    after_antenna = tcl[tcl.index('log_cmd repair_antennas'):]
    assert len(re.findall(r'^\s*log_cmd repair_design', after_antenna, re.M)) == 1
    start = tcl.index('set ::vic_fo_rounds 0')
    end = tcl.index('# ---- 7. re-verify', start)
    section = tmp_path / 'post_antenna_drv.tcl'
    section.write_text(tcl[start:end])
    harness = textwrap.dedent(r"""
        namespace eval utl { proc metric_integer {args} {} }
        set ::env(VIBEIC_PRR_MAX_FANOUT) 4
        set ::vic_fo_repaired [dict create]
        set ::calls 0
        set rd_args [list]
        set ::block block
        proc block {method args} {if {$method eq "getInsts"} {return {}}}
        proc vic_fanout_over {} {return [dict create]}
        proc vic_fanout_added {before now} {return [dict create]}
        proc vic_say {line} {puts $line}
        proc log_cmd {name args} {
            if {$name eq "repair_design"} {incr ::calls}
        }
        source __SECTION__
        puts "DRV_RECHECK_CALLS $::calls"
    """).replace('__SECTION__', str(section))
    run = subprocess.run(['tclsh'], input=harness, text=True,
                         capture_output=True, check=False)
    assert run.returncode == 0, run.stderr
    assert 'DRV_RECHECK_CALLS 1' in run.stdout, run.stdout


def test_timing_cannot_remove_the_buffers_that_closed_declared_fanout():
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    assert re.search(r'^set setup_args \[list -setup -verbose -skip_buffer_removal\]$',
                     tcl, re.M)
    assert re.search(r'^set hold_args \[list -hold -verbose -skip_buffer_removal\]$',
                     tcl, re.M)


def test_a_hard_repair_stops_at_the_declared_floor(tmp_path, monkeypatch):
    """T98's case (+3.33 -> +0.14) against a design that DECLARES 0.5 ns of
    setup margin: the floor is the declaration's, and 0.14 is below it."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(3.33, 0.2, (4, 0, 0)),
        candidates=[_cand(0.14, 0.2, (0, 0, 0))])
    _with_floors(impl, {'setup': [0.5, 'L8_TIMING_WAVEFORM.json setup_margin_ns']})
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_drv')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert 'below its floor 0.5' in run.iterations[0].decision_reason
    rec = run.to_record()['iterations'][0]['measurements']['timing.setup']
    assert rec['floor'] == {'value': 0.5, 'source': 'L8_TIMING_WAVEFORM.json setup_margin_ns'}


def test_a_soft_only_candidate_still_follows_the_one_ps_rule(tmp_path, monkeypatch):
    """No hard violation is being fixed (a hold repair): setup may not move
    more than the declared 1 ps, however much slack stays."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(5.259, -0.1),
        candidates=[_cand(5.0, 0.2)])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert 'timing.setup.wns_ns: 5.259 -> 5.0 (maximize)' in run.iterations[0].decision_reason


def test_the_floor_comes_from_declared_inputs_only(tmp_path):
    project = tmp_path / 'p'
    sdc = write(project / 'c.sdc', 'create_clock -name clk -period 10 [get_ports clk]\n')
    f = prr.declared_timing_floor(project, sdc)
    assert f['setup'][0] == 0.0 and 'WNS >= 0' in f['setup'][1]
    write(sdc, 'set_clock_uncertainty -setup 0.25 [get_clocks clk]\n'
               'set_clock_uncertainty 0.1 [get_clocks clk] # both checks\n')
    f = prr.declared_timing_floor(project, sdc)
    assert f['setup'][0] == 0.25 and 'set_clock_uncertainty' in f['setup'][1]
    assert f['hold'][0] == 0.1
    put(project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'timing': {'setup_margin_ns': 0.4}})
    f = prr.declared_timing_floor(project, sdc)
    assert f['setup'] == (0.4, 'L8_TIMING_WAVEFORM.json setup_margin_ns')
    assert f['hold'][0] == 0.1


def test_hardness_and_floor_are_declared_in_the_registry(tmp_path):
    import yaml
    reg = closure.load_registry(REGISTRY)
    assert reg.domains['timing.drv'].hardness == 'hard'
    assert reg.domains['antenna.violations'].hardness == 'hard'
    assert reg.domains['timing.setup'].hardness == 'soft'
    assert reg.domains['timing.setup'].floor_pointer == '/floor'
    doc = yaml.safe_load(REGISTRY.read_text())
    doc['domains']['timing.drv']['floor_pointer'] = '/floor'
    bad = write(tmp_path / 'r.yaml', yaml.safe_dump(doc))
    with pytest.raises(closure.RegistryError, match='HARD domain has no floor'):
        closure.load_registry(bad)


def test_native_signoff_slack_controls_setup_stop_when_librelane_is_optimistic(tmp_path, monkeypatch):
    """A positive LibreLane WNS cannot end closure while direct RCX is red."""
    first = _cand(0.012, 0.2)
    first['native_setup'] = -0.02
    second = _cand(0.037, 0.2)
    second['native_setup'] = 0.01
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.2, 0.2), candidates=[first, second])
    run = _controller(impl, arm, shim, monkeypatch, tmp_path).run_controller(
        'postroute.repair_setup')
    assert [it.decision for it in run.iterations] == ['PROMOTED', 'PROMOTED']
    assert run.outcome is closure.Outcome.CONVERGED
    final = json.loads((impl / prr.CURRENT).read_text())
    assert final['candidate'] == '32-cand02'
    assert final['measurement']['setup_ws_min'] == 0.01
    assert final['measurement']['librelane_setup_ws']['nom_ss_125C_4v50'] == 0.037

def test_a_setup_violation_is_repaired_and_the_improving_candidate_adopted(tmp_path, monkeypatch):
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.5, 0.2),
        candidates=[_cand(-0.1, 0.2), _cand(0.05, 0.2)])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_setup')
    assert [it.decision for it in run.iterations] == ['PROMOTED', 'PROMOTED']
    assert run.outcome is closure.Outcome.CONVERGED
    cur = json.loads((impl / prr.CURRENT).read_text())
    assert cur['candidate'] == '32-cand02'
    # The next candidate starts from the adopted one, never from the input.
    ledger = json.loads((arm / prr.LEDGER).read_text())['candidates']
    assert ledger[1]['from'] == '32-cand01'
    assert ledger[0]['params']['setup_margin_ns'] == 0
    assert ledger[1]['params']['setup_margin_ns'] == 0.05


def test_a_candidate_with_a_supply_pin_off_its_net_is_never_adopted(tmp_path, monkeypatch):
    """F24: the inserted buffer's supply pins on no net. The candidate improves
    setup and is refused anyway, by the supply-ownership gate on its own DEF."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(-0.5, 0.2),
        candidates=[_cand(0.3, 0.2, owned=False)])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_setup')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None
    row = json.loads((arm / prr.LEDGER).read_text())['candidates'][0]
    assert row['decision'] == 'REFUSED'
    assert row['supply_ownership']['verdict'] == 'FAIL'


def test_a_hold_repair_is_adopted_through_extraction_noise_on_setup(tmp_path, monkeypatch):
    """MEASURED on spm (arm L): 17 hold buffers took worst hold -0.335 ->
    +0.326 ns and moved worst setup 4.026052 -> 4.025948 ns on paths they never
    touched. That is not a regression the step may roll a hold closure back
    for; the declared 1 ps tolerance is what tells the two apart."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(4.026052, -0.335),
        candidates=[_cand(4.025948, 0.326)])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert [it.decision for it in run.iterations] == ['PROMOTED'], run.to_record()
    assert run.outcome is closure.Outcome.CONVERGED
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] == '32-cand01'


def test_a_regression_tolerance_is_declared_and_never_negative(tmp_path):
    import yaml
    doc = yaml.safe_load(REGISTRY.read_text())
    assert doc['domains']['timing.setup']['regression_tolerance'] == 0.001
    assert 'regression_tolerance' not in doc['domains']['timing.drv']
    doc['domains']['timing.setup']['regression_tolerance'] = -0.1
    bad = write(tmp_path / 'r.yaml', yaml.safe_dump(doc))
    with pytest.raises(closure.RegistryError, match='regression_tolerance'):
        closure.load_registry(bad)
    reg = closure.load_registry(REGISTRY)
    setup = reg.domains['timing.setup']
    assert not setup.regresses(4.025948, 4.026052)
    assert setup.regresses(0.14, 3.33)
    # the objective's own test is untouched: a smaller loss is still no gain
    assert not setup.improves(4.0259, 4.0260)
    assert reg.domains['pnr.repair_deck.required_completeness'].regression_tolerance == 0


@pytest.mark.parametrize('antenna', [4, None])
def test_a_repair_that_creates_an_antenna_violation_is_never_adopted(tmp_path, monkeypatch, antenna):
    """Lane mig99 measured it on spm: the direct SDR DRV repair candidate
    ADDED 4 antenna violations to an antenna-clean route. Every candidate is
    counted by the step-26 instrument (OpenROAD.CheckAntennas) and one that
    creates a violation -- or cannot be counted -- is refused, however much it
    closed timing."""
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(1.0, -0.2),
        candidates=[_cand(1.0, 0.05, antenna=antenna)])
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None
    row = json.loads((arm / prr.LEDGER).read_text())['candidates'][0]
    assert row['decision'] == 'REFUSED' and row['reason'].startswith('antenna (OpenROAD.CheckAntennas)')
    assert row['antenna'] == {'before': 0, 'after': antenna,
                              'before_pins': 0, 'after_pins': antenna}


@pytest.mark.parametrize('missing', [None, 'baseline', 'candidate'])
def test_pin_census_blocks_promotion_with_zero_violating_nets(
        tmp_path, monkeypatch, missing):
    candidate = _cand(1.0, 0.05)
    candidate['antenna_metrics']['antenna__violating__pins'] = 1
    if missing == 'candidate':
        del candidate['antenna_metrics']['antenna__violating__pins']
    project, arm, impl, shim = _scenario_impl(
        tmp_path, baseline=(1.0, -0.2), candidates=[candidate])
    if missing == 'baseline':
        current = json.loads((impl / prr.CURRENT).read_text())
        del current['measurement']['antenna_pins']
        put(impl / prr.CURRENT, current)
    ctl = _controller(impl, arm, shim, monkeypatch, tmp_path)
    run = ctl.run_controller('postroute.repair_hold')
    assert run.iterations[0].decision == 'ROLLED_BACK'
    assert json.loads((impl / prr.CURRENT).read_text())['candidate'] is None
    row = json.loads((arm / prr.LEDGER).read_text())['candidates'][0]
    assert row['decision'] == 'REFUSED'
    assert 'pins' in row['reason']


def test_antenna_is_measured_by_the_step_26_instrument_on_every_candidate():
    assert prr.MEASURE_STEPS[0] == 'OpenROAD.CheckAntennas'
    import librelane_ir_antenna as step26
    assert set(prr.ANTENNA_METRICS) == set(step26.ROUTER_METRICS)


def test_run_bridges_measures_closes_and_records_every_candidates_fate(tmp_path, monkeypatch):
    """`run` end to end: the bridge, the census baseline (same instruments),
    the three controllers in order, and a report naming the adopted candidate
    and the closure's verdict on every candidate."""
    project = tmp_path / 'proj'
    lef = write(tmp_path / 'cells.lef', LEF)
    base, cand = (4.026052, -0.335), _cand(4.025948, 0.326)
    scenario = {'32-base': {'def': _def(True), 'sta_metrics': _sta_metrics(*base),
                            'antenna_metrics': _ant(0),
                            'repair_metrics': {'vibeic__prr__changed': 0}},
                '32-cand01': cand}
    put(tmp_path / 'scenario.json', scenario)
    shim = tmp_path / 'shim'
    write(shim / 'librelane_postroute_repair.py', SHIM)
    monkeypatch.setenv('PRR_REAL_PROGRAMS', str(PROGRAMS))
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    ns = {}
    exec(compile(SHIM.split('ll.run_chain = run_chain')[0].replace(
        'sys.path.insert(0, os.environ["PRR_REAL_PROGRAMS"])', ''), 'shim', 'exec'), ns)
    monkeypatch.setattr(contract, 'run_chain', ns['run_chain'])
    monkeypatch.setattr(prr, 'fork_capability',
                        lambda image, docker='docker': {'capable': True, 'image': image})
    seen = {}

    def configs(project_, image, pdk, ids, *, pdk_root, folder, overlay, docker):
        seen['overlay'] = overlay
        root = project_ / 'phase3/librelane' / folder
        return {i: put(root / f'{i}.json', {'meta': {'step': i}, 'CELL_LEFS': [str(lef)],
                                            'STA_CORNERS': CORNERS}) for i in ids}
    monkeypatch.setattr(contract, 'resolve_step_configs', configs)
    monkeypatch.setattr(contract, 'state_from_direct',
                        lambda project_, image, cfg, views, out, **k: put(out / 'state_in.json',
                                                                         {'def': str(views['def'])}))
    sdc = write(project / 'phase3/stage3/pnr/constraint.sdc', 'create_clock -period 10 [get_ports clk]\n')
    report = prr.run(project, image='img', pdk='pdk', pdk_root=tmp_path, views={'def': sdc},
                     sdc=sdc, derate=(0.95, 1.05), programs_dir=shim)
    assert report['verdict'] == 'PASS' and report['adopted'] == '32-cand01'
    assert [r['outcome'] for r in report['closure']] == ['NOT_TRIGGERED', 'CONVERGED', 'NOT_TRIGGERED']
    assert report['candidates'][0]['closure_decision'] == 'PROMOTED'
    assert report['candidates'][0]['controller'] == 'postroute.repair_hold'
    assert report['baseline']['hold_ws_min'] == -0.335 and report['final']['hold_ws_min'] == 0.326
    # the repair scene is the sign-off scene
    scene = Path(seen['overlay']['PNR_SDC_FILE'][0])
    assert seen['overlay']['SIGNOFF_SDC_FILE'][0] == str(scene)
    assert scene.read_text().endswith('set_timing_derate -early 0.95\nset_timing_derate -late 1.05\n')
    census = json.loads((project / 'phase3/librelane/32-config/Vibeic.PostRouteRepair@census.json').read_text())
    assert census['VIBEIC_PRR_CENSUS_ONLY'] is True


# ----------------------------------------------------- the plugin step ---

def _tcl_env_vars():
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    return set(re.findall(r'::env\((VIBEIC_PRR_[A-Z_]+)\)', tcl)) | set(
        re.findall(r'\b(VIBEIC_PRR_[A-Z_]+)\b', tcl))


def test_every_variable_the_script_reads_is_declared_by_the_step():
    src = (STEP_DIR / 'postroute_repair.py').read_text()
    declared = set(re.findall(r'"(VIBEIC_PRR_[A-Z_]+)"', src))
    used = {v for v in _tcl_env_vars() if not v.endswith(('_TOOL_INCAPABLE', '_EXTRACTION_FAILED',
                                                           '_CORNER_UNANNOTATED', '_ROUTE_REFUSED',
                                                           '_PLACEMENT_REFUSED'))}
    assert used <= declared, sorted(used - declared)
    assert set(prr.PARAM_VARS.values()) <= declared


def test_bounded_strength_is_only_the_drv_recovery_and_keeps_existing_judges():
    main = (STEP_DIR / 'postroute_repair.tcl').read_text()
    helper = (STEP_DIR / 'bounded_drive_strength.tcl').read_text()
    assert 'VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH' in main
    gate = main.index('if {[info exists ::env(VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH)]')
    assert main.index('[sta::max_slew_violation_count] > 0', gate) > gate
    assert main.index('vic_bounded_drive_strength', gate) > gate
    # Target and candidate identity come from the running EDA session.
    for required in ('report_check_types -max_slew -violators',
                     'sta::find_equiv_cells', 'get_lib_cells -quiet',
                     'get_property $cell dont_use', 'isDoNotTouch',
                     '_PNR_EXCLUDED_CELLS', 'swapMaster'):
        assert required in helper
    # A candidate is still judged by the already-shipping route and signoff
    # chain after the helper changes a master.
    assert main.index('vic_bounded_drive_strength', gate) < main.index(
        '# ---- 5. what changed')
    assert 'vic_eco_route ::vic_dirty eco_route' in main
    assert 'vic_annotate after' in main
    assert 'check_antennas' in main


def test_the_step_is_registered_with_every_earlier_plugin_step():
    init = (STEP_DIR / '__init__.py').read_text()
    for name in ('InsertSpareCells', 'GateLevelSim', 'ClockPathDriveSizing',
                 'IRDropChecker', 'TransientIR', 'PostRouteRepair'):
        assert re.search(rf'\b{name}\b', init), name
    src = (STEP_DIR / 'postroute_repair.py').read_text()
    assert 'id = "Vibeic.PostRouteRepair"' in src
    assert src.count('@Step.factory.register()') == 1


def test_the_script_orders_the_repair_and_connects_before_it_writes():
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    lines = [ln.strip() for ln in tcl.splitlines() if ln.strip() and not ln.strip().startswith('#')]

    def at(pattern):
        hits = [i for i, ln in enumerate(lines) if re.search(pattern, ln)]
        assert hits, pattern
        return hits[0]
    # parasitics from the router's wires, then the fork flag, then repairs
    assert at(r'extract_parasitics') < at(r'estimate_parasitics -detailed_routing')
    assert at(r'estimate_parasitics -detailed_routing') < at(r'log_cmd repair_design')
    # setup, then hold
    assert at(r'log_cmd repair_design') < at(r'repair_timing \{\*\}\$setup_args') < at(r'repair_timing \{\*\}\$hold_args')
    # a no-op repair stops before anything is re-routed
    assert at(r'vic_changed == 0') < at(r'detailed_placement')
    # supply connected after legalization, before the ECO route and the write
    assert at(r'detailed_placement') < at(r'^global_connect') < at(r'detailed_route') < at(r'^write_views')
    assert 'set_global_connections' in tcl
    # the ECO route is scoped to the touched nets
    assert '-nets [dict keys $dirty]' in tcl
    assert 'vic_eco_route ::vic_dirty eco_route' in tcl
    # antenna residue goes to the tool's repair, on the new diodes' nets only,
    # after the ECO route and before anything is written
    assert at(r'set ::vic_eco_ok \[vic_eco_route') < at(r'log_cmd repair_antennas') \
        < at(r'vic_eco_route ::vic_ant_dirty antenna_route') < at(r'^write_views')


@pytest.mark.skipif(not __import__('shutil').which('tclsh'), reason='tclsh absent')
def test_noop_branch_emits_real_after_route_census_before_exit(tmp_path):
    """A valid identity/no-op still measures its unchanged input database."""
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    start = tcl.index('if {$::vic_changed == 0} {')
    end = tcl.index('\n# ---- 6. legalize', start)
    branch = tcl[start:end]
    section = tmp_path / 'noop_census.tcl'
    section.write_text(branch)
    harness = textwrap.dedent(r"""
        namespace eval utl {
            proc metric_integer {name value} {lappend ::metrics [list $name $value]}
        }
        set ::metrics [list]
        set ::vic_changed 0
        set ::vic_fanout_pending 0
        set ::vic_unrouted_before [dict create net_a 1]
        proc vic_unrouted_nets {} {return [dict create net_a 1]}
        proc vic_say {line} {puts $line}
        rename exit real_exit
        proc exit {code} {
            puts "METRICS $::metrics"
            puts "EXIT $code"
            real_exit $code
        }
        source __SECTION__
    """).replace('__SECTION__', str(section))
    run = subprocess.run(['tclsh'], input=harness, text=True,
                         capture_output=True, check=False)
    assert run.returncode == 0, run.stderr
    assert 'no-op route census after_unrouted=1 unrouted_added=0' in run.stdout
    assert 'vibeic__prr__after__unrouted__count 1' in run.stdout
    assert 'vibeic__prr__unrouted__added 0' in run.stdout
    assert 'EXIT 0' in run.stdout


@pytest.mark.skipif(not __import__('shutil').which('tclsh'), reason='tclsh absent')
def test_the_neighbour_reader_takes_the_nets_that_share_a_violation(tmp_path):
    """The script's own proc, run by tclsh on the router's report grammar
    (recorded from the fork's DRT-0712 refusal on spm, 2026-09-27)."""
    tcl = (STEP_DIR / 'postroute_repair.tcl').read_text()
    proc = tcl[tcl.index('proc vic_violation_neighbours'):]
    proc = proc[:proc.index('\n}\n') + 3]
    drc = write(tmp_path / 'eco.drc', textwrap.dedent('''\
        violation type: Metal Spacing
        \tsrcs: net:u_core/_092_ net:net7
        \tbbox = (621.1800, 2753.0500) - (621.4100, 2753.1000) on Layer Metal2
        violation type: Min Area
        \tsrcs: net:y__core
        \tbbox = (418.6900, 2236.4500) - (419.0700, 2236.8300) on Layer Metal2
        violation type: Metal Spacing
        \tsrcs: net:VDD net:net7
        \tbbox = (1.0, 2.0) - (3.0, 4.0) on Layer Metal1
        '''))
    script = write(tmp_path / 't.tcl', textwrap.dedent('''\
        # odb, reduced to the three calls the proc makes
        proc ::blk_find {cmd name} {
            if {$name eq "VDD"} { return ::net_vdd }
            return ::net_sig
        }
        proc ::net_vdd {cmd} { if {$cmd eq "getSigType"} { return POWER }; return 0 }
        proc ::net_sig {cmd} { if {$cmd eq "getSigType"} { return SIGNAL }; return 0 }
        set ::block ::blk_find
        ''') + proc + f'''
set got [vic_violation_neighbours {drc} [dict create net7 x]]
puts [lsort [dict keys $got]]
''')
    import subprocess
    out = subprocess.run(['tclsh', str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ['u_core/_092_'], out.stdout


# ------------------------------------------------------------ the runner ---

def test_the_switch_selects_step_32_and_refuses_dual(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    assert runner._librelane_postroute_repair_mode(tmp_path) == 'direct'
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'32': 'librelane'}})
    assert runner._librelane_postroute_repair_mode(tmp_path) == 'librelane'
    assert prr.refusal('librelane') is None
    # dual needs step 21 on LibreLane: its pre-DRT arm is that chain's own
    assert prr.refusal('dual').startswith('LL_PRR_DUAL_NEEDS_LL21')
    assert prr.refusal('dual', 'librelane') is None and prr.refusal('dual', 'dual') is None


def _deck_kwargs(tmp_path, monkeypatch, switch):
    import test_librelane_cts_hold as harness
    runner = harness.runner
    monkeypatch.setattr(runner, '_openroad_supports_postroute_spef_repair', lambda c: True)
    return harness._drive_step_pnr(tmp_path, monkeypatch, switch)


def test_with_step_32_on_librelane_the_deck_carries_no_repair_of_its_own(tmp_path, monkeypatch):
    """The custom step owns the post-route repair: the deck's two sign-off DRV
    repair transactions are not emitted, and nothing else changes."""
    direct = _deck_kwargs(tmp_path / 'd', monkeypatch, None)
    ll = _deck_kwargs(tmp_path / 'l', monkeypatch, {'32': 'librelane'})
    other = _deck_kwargs(tmp_path / 'o', monkeypatch, {'19': 'direct'})
    joined = lambda kw: '\n'.join(str(v) for v in kw.values() if isinstance(v, str))
    assert 'postroute_drv_repair' in joined(direct)
    assert 'postroute_drv_reconverge' in joined(direct)
    assert 'postroute_drv_repair' not in joined(ll).replace('SDR_SKIP_STOCK_OPENROAD', '')
    assert 'SDR2_BEGIN' not in joined(ll)
    # a switch that names other steps leaves the deck exactly as it was
    norm = lambda kw: {k: str(v).replace(str(tmp_path / 'o'), 'P').replace(str(tmp_path / 'd'), 'P')
                       for k, v in kw.items()}
    assert norm(other) == norm(direct)


def _runner_step(tmp_path, monkeypatch, report):
    import test_pad_connected_pdn_ring as ring_fixture
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'proj'
    pnr = project / 'phase3/stage3/pnr'
    write(pnr / 'routed.def', 'DESIGN top ;\nEND DESIGN\n')
    write(pnr / 'dut_pnr.v', 'module top(); endmodule\n')
    write(pnr / 'constraint.sdc', '')
    write(pnr / 'pnr.tcl', 'add_global_connection -net VDD -pin_pattern {^VDD$} -power\n')
    put(project / 'phase3/librelane_switch.json', {'steps': {'32': 'librelane'}})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    monkeypatch.setattr(contract, 'resolve_image', lambda p=None: 'img')
    monkeypatch.setattr(contract, 'pdk_root_resolution',
                        lambda *a, **k: {'path': str(tmp_path / 'pdkroot')})
    calls = {}

    def run(project_, **kw):
        calls.update(kw)
        return report(project_)
    monkeypatch.setattr(prr, 'run', run)
    result = runner.step_postroute_repair_librelane(project, 'dut', pdk, 'unused')
    return runner, project, pnr, result, calls


def test_the_runner_hands_the_adopted_route_to_the_direct_paths(tmp_path, monkeypatch):
    def report(project):
        folder = project / 'phase3/librelane/32-cand01/01-vibeic-postrouterepair'
        d = write(folder / 'top.def', 'DESIGN top ;\n# repaired\nEND DESIGN\n')
        n = write(folder / 'top.nl.v', 'module top(); /* repaired */ endmodule\n')
        state = put(folder / 'state_out.json', {'def': str(d), 'nl': str(n)})
        # the adopted candidate's own measurement of its output (cmp3 D15):
        # OpenROAD.CheckAntennas after the repair, and its unrouted census
        return {'verdict': 'PASS', 'adopted': '32-cand01', 'adopted_state': str(state),
                'baseline': {'hold_ws_min': -0.335, 'drv_count': 0},
                'final': {'hold_ws_min': 0.326, 'drv_count': 0, 'antenna_nets': 0,
                          'antenna_pins': 0, 'antenna_state': 'cand01/02-checkantennas'},
                'candidates': [{'candidate': '32-cand01',
                                'repair_metrics': {'vibeic__prr__unrouted__added': 0}}],
                'corners': CORNERS,
                'final_supply_ownership': {'verdict': 'PASS'}}
    runner, project, pnr, result, calls = _runner_step(tmp_path, monkeypatch, report)
    assert result.status == 'PASS' and result.detail.startswith('ADOPTED 32-cand01'), result.detail
    assert '# repaired' in (pnr / 'routed.def').read_text()
    assert 'repaired' in (pnr / 'dut_pnr.v').read_text()
    assert '# repaired' not in (pnr / 'routed_base_prerepair.def').read_text()
    claim = json.loads((pnr / runner._DRV_PROMOTION_CLAIM).read_text())
    assert claim['program'] == 'librelane_postroute_repair' and claim['promoted'] is True
    assert not (pnr / runner._DRV_PROMOTION_NOT_RUN).exists()
    # the deck's own supply rules and fill policy travel with the database
    assert 'add_global_connection' in Path(calls['pg_rules_tcl']).read_text()
    assert calls['derate'] == (runner._FLAT_OCV_DERATE_EARLY, runner._FLAT_OCV_DERATE_LATE)
    handoff = json.loads((project / 'reports/phase3/librelane_postroute_repair_handoff.json').read_text())
    assert set(handoff['views']) == {'def', 'nl'}


def test_the_runner_keeps_the_input_route_and_says_why_when_nothing_is_adopted(tmp_path, monkeypatch):
    def report(project):
        return {'verdict': 'PASS', 'adopted': None, 'baseline': {}, 'final': {},
                'closure': [{'controller': 'postroute.repair_hold', 'outcome': 'PLATEAU'}]}
    runner, project, pnr, result, _ = _runner_step(tmp_path, monkeypatch, report)
    assert result.status == 'PASS' and 'no candidate adopted' in result.detail
    assert (pnr / 'routed.def').read_text() == 'DESIGN top ;\nEND DESIGN\n'
    assert not (pnr / 'routed_base_prerepair.def').exists()
    rec = json.loads((pnr / runner._DRV_PROMOTION_NOT_RUN).read_text())
    assert rec['not_run_stage'] == 'librelane_closure_kept_input'
    assert 'postroute.repair_hold: PLATEAU' in rec['reason']


def test_the_main_flow_replaces_the_direct_repair_producers_only_when_selected():
    """Source contract of the one call site: the LibreLane producer runs only
    when selected, and then neither direct producer does."""
    src = (PROGRAMS / 'phase3_one_shot_runner.py').read_text()
    at = src.index('_prr_on_librelane = _librelane_postroute_repair_mode(project) != "direct"')
    block = src[at:at + 3000]
    # Default owns Step32 through its canonical row; the enclosing legacy
    # arms must stay disabled there to avoid a duplicate repair invocation.
    legacy_guard = "_chain_ok and _execution.request()['mode'] != 'default'"
    assert f'if {legacy_guard} and _prr_on_librelane:' in block
    assert block.index('step_postroute_repair_librelane') < block.index('step_signoff_spef_repair')
    assert block.count(f'if {legacy_guard} and not _prr_on_librelane:') == 2


# --------------------------------------------- r2: inside the LL21 chain, dual ---

def _chain_setup(tmp_path, monkeypatch, scenario):
    """`run_in_chain` with the real closure (subprocess shim), the real
    registry and only the docker runs faked."""
    project = tmp_path / 'proj'
    lef = write(tmp_path / 'cells.lef', LEF)
    put(tmp_path / 'scenario.json', scenario)
    shim = tmp_path / 'shim'
    write(shim / 'librelane_postroute_repair.py', SHIM)
    monkeypatch.setenv('PRR_REAL_PROGRAMS', str(PROGRAMS))
    monkeypatch.setenv('PRR_SCENARIO', str(tmp_path / 'scenario.json'))
    ns = {}
    exec(compile(SHIM.split('ll.run_chain = run_chain')[0].replace(
        'sys.path.insert(0, os.environ["PRR_REAL_PROGRAMS"])', ''), 'shim', 'exec'), ns)
    monkeypatch.setattr(contract, 'run_chain', ns['run_chain'])
    monkeypatch.setattr(prr, 'fork_capability',
                        lambda image, docker='docker': {'capable': True, 'image': image})

    def configs(project_, image, pdk, ids, *, pdk_root, folder, overlay, docker):
        root = project_ / 'phase3/librelane' / folder
        return {i: put(root / f'{i}.json', {'meta': {'step': i}, 'CELL_LEFS': [str(lef)],
                                            'STA_CORNERS': CORNERS}) for i in ids}
    monkeypatch.setattr(contract, 'resolve_step_configs', configs)
    monkeypatch.setattr(contract, 'state_from_direct',
                        lambda *a, **k: pytest.fail('inside the chain nothing is bridged'))
    sdc = write(project / 'phase3/stage3/pnr/constraint.sdc', '')
    route = put(project / 'phase3/librelane/21-route/13-fill/state_out.json',
                {'odb': 'r.odb', 'def': 'r.def'})
    return project, shim, sdc, route


def _base(setup, hold, antenna=0):
    return {'def': _def(True), 'sta_metrics': _sta_metrics(setup, hold),
            'antenna_metrics': _ant(antenna), 'repair_metrics': {'vibeic__prr__changed': 0}}


def test_in_the_chain_the_route_state_is_repaired_without_a_bridge(tmp_path, monkeypatch):
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': _base(4.026052, -0.335), '32-cand01': _cand(4.025948, 0.326)})
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    assert report['site'] == 'after_route' and report['adopted'] == '32-cand01'
    assert report['baseline']['hold_ws_min'] == -0.335
    ctx = json.loads((project / prr.ARM_REL / prr.IMPL_DIR / prr.CONTEXT).read_text())
    assert ctx['derate'] == [0.95, 1.05]
    assert ctx['aocv_table'] is None
    assert 'VIBEIC_PRR_REFILL_TCL' not in json.loads(
        Path(ctx['configs'][prr.REPAIR_STEP]).read_text()), \
        "the LL21 route's fillers are LibreLane's; the refill is too"


def test_in_chain_clean_census_replaces_a_stale_repair_decision_before_stream(
        tmp_path, monkeypatch):
    import flow_step_output_content_check as content
    import postroute_timing_repair_audit as audit
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': _base(4.0, 0.2)})
    decision = put(project / 'phase3/stage3/postroute_timing_repair' /
                   'postroute_timing_repair_decision.json', {'repair_needed': True})
    write(decision.parent / 'repair_log.json', '{}\n')
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    assert report['verdict'] == 'PASS' and report['adopted'] is None
    assert json.loads(decision.read_text())['repair_needed'] is False
    assert not (decision.parent / 'repair_log.json').exists()
    assert content.check(project, 'repair') == []
    assert not [f for f in audit.audit(project)[0] if f.severity == 'ERROR']


def test_in_chain_adopted_repair_keeps_its_input_trigger_and_passes_audit(
        tmp_path, monkeypatch):
    import postroute_timing_repair_audit as audit
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': _base(4.026052, -0.335),
        '32-cand01': _cand(4.025948, 0.326)})
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    output = project / 'phase3/stage3/postroute_timing_repair'
    decision = json.loads((output / 'postroute_timing_repair_decision.json').read_text())
    log = json.loads((output / 'repair_log.json').read_text())
    assert report['adopted'] == '32-cand01'
    assert decision['repair_needed'] is True
    assert decision['baseline']['hold_ws_min'] < 0 < decision['final']['hold_ws_min']
    assert log['changes'][0]['candidate'] == report['adopted']
    assert log['re_verified'] is True
    assert not (output / 'no_repair_needed.flag').exists()
    assert not [f for f in audit.audit(project)[0] if f.severity == 'ERROR']


def test_dual_route_with_pin_violation_cannot_publish_clean_repair(
        tmp_path, monkeypatch):
    import postroute_timing_repair_audit as audit
    scenario = {
        '32-postdrt-base': _base(4.0, -0.3),
        '32-pregrt-base': _base(4.2, 0.10),
        '32-pregrt_postdrt-base': _base(4.1, 0.05),
    }
    for step in scenario.values():
        step['antenna_metrics']['antenna__violating__pins'] = 1
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, scenario)
    pre_state = put(project / 'phase3/librelane/21-route-pregrt/13-fill/state_out.json',
                    {'odb': 'p.odb', 'def': 'p.def'})
    report = prr.run_in_chain(
        project, mode='dual', image='img', pdk='pdk', pdk_root=tmp_path,
        sdc=sdc, derate=(0.95, 1.05), route_state=route, route_drc=0,
        variant_arm=lambda lane, extra: {
            'final': pre_state, 'route_drc': [{'run': 'drt-run-0', 'markers': 0}]},
        programs_dir=shim)
    assert report['selected_arm'] == 'pregrt'
    assert report['selection']['feasible'] == []
    output = project / prr.DECLARED_REPAIR_REL
    decision = json.loads((output / 'postroute_timing_repair_decision.json').read_text())
    log = json.loads((output / 'repair_log.json').read_text())
    assert decision['repair_needed'] is True
    assert log['final']['antenna_nets'] == 0
    assert log['final']['antenna_pins'] == 1
    assert log['re_verified'] is False
    assert 'NOT_REVERIFIED' in [f.category for f in audit.audit(project)[0]
                                if f.severity == 'ERROR']


def test_missing_input_pin_census_refuses_declared_repair(
        tmp_path, monkeypatch):
    import postroute_timing_repair_audit as audit
    baseline = _base(4.0, -0.3)
    del baseline['antenna_metrics']['antenna__violating__pins']
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': baseline, '32-cand01': _cand(3.99995, 0.3)})
    report = prr.run_in_chain(
        project, mode='librelane', image='img', pdk='pdk', pdk_root=tmp_path,
        sdc=sdc, derate=(0.95, 1.05), route_state=route, route_drc=0,
        programs_dir=shim)
    assert report['adopted'] is None
    assert report['declared_repair_publication']['status'] == 'NOT_MEASURED'
    assert 'CheckAntennas' in report['declared_repair_publication']['reason']
    assert not (project / prr.DECLARED_REPAIR_REL /
                'postroute_timing_repair_decision.json').exists()
    assert 'NO_REPAIR_ARTIFACT' in [f.category for f in audit.audit(project)[0]
                                    if f.severity == 'ERROR']


@pytest.mark.parametrize('which', ['baseline', 'final'])
def test_missing_sta_digest_cannot_publish_a_measured_repair(
        tmp_path, monkeypatch, which):
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': _base(4.0, -0.3),
        '32-cand01': _cand(3.99995, 0.3)})
    report = prr.run_in_chain(
        project, mode='librelane', image='img', pdk='pdk', pdk_root=tmp_path,
        sdc=sdc, derate=(0.95, 1.05), route_state=route, route_drc=0,
        programs_dir=shim)
    assert report['adopted'] == '32-cand01'
    # A producer that loses either digest must invalidate its earlier receipt.
    report[which].pop('sta_state_sha256')
    prr._clear_declared_repair(project)
    prr._set_census_verdict(report, report['baseline'], report['final'])
    source = project / prr.REPORT_REL
    prr.write_json(source, report)
    prr._publish_declared_repair(project, report, source)
    assert report['verdict'] == 'NOT_MEASURED'
    assert report['declared_repair_publication']['status'] == 'NOT_MEASURED'
    assert 'digest' in report['declared_repair_publication']['reason']
    assert not (project / prr.DECLARED_REPAIR_REL /
                'postroute_timing_repair_decision.json').exists()


def test_in_chain_tool_refusal_invalidates_the_prior_declared_decision(
        tmp_path, monkeypatch):
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {})
    output = project / 'phase3/stage3/postroute_timing_repair'
    decision = put(output / 'postroute_timing_repair_decision.json',
                   {'repair_needed': False})
    write(output / 'no_repair_needed.flag', 'stale\n')
    write(output / 'repair_log.json', '{}\n')
    monkeypatch.setattr(prr, 'fork_capability',
                        lambda image, docker='docker': {'capable': False, 'image': image})
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    assert report['verdict'] != 'PASS'
    assert not decision.exists()
    assert not (output / 'no_repair_needed.flag').exists()
    assert not (output / 'repair_log.json').exists()


def test_unmeasured_publication_names_its_missing_floor_in_step32_report(
        tmp_path, monkeypatch):
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': _base(4.0, 0.2)})
    monkeypatch.setattr(prr, 'declared_timing_floor', lambda project, sdc: {})
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    record = json.loads((project / prr.REPORT_REL).read_text())
    publication = record.get('declared_repair_publication')
    status = (publication or {}).get('status', 'MISSING')
    assert status == 'NOT_MEASURED'
    assert 'timing floors' in publication.get('reason', '')
    assert report.get('declared_repair_publication') == publication
    assert not (project / prr.DECLARED_REPAIR_REL /
                'postroute_timing_repair_decision.json').exists()


def test_in_chain_residual_drv_replaces_a_stale_clean_decision_before_stream(
        tmp_path, monkeypatch):
    import flow_step_output_content_check as content
    import postroute_timing_repair_audit as audit
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': {'def': _def(True), 'sta_metrics': _sta_metrics(5.0, 0.4, (0, 0, 4)),
                    'antenna_metrics': _ant(0),
                    'repair_metrics': {'vibeic__prr__changed': 0}},
        '32-cand01': _cand(1.6, 0.4, (0, 0, 1))})
    output = project / 'phase3/stage3/postroute_timing_repair'
    decision = put(output / 'postroute_timing_repair_decision.json',
                   {'repair_needed': False})
    write(output / 'no_repair_needed.flag', 'stale estimate\n')
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    assert report['verdict'] == 'FAIL' and report['adopted'] == '32-cand01'
    assert report['code'] == 'LL_PRR_FANOUT_VIOLATION'
    assert json.loads(decision.read_text())['repair_needed'] is True
    assert not (output / 'no_repair_needed.flag').exists()
    assert json.loads((output / 'repair_log.json').read_text())['final']['drv_count'] == 1
    assert content.check(project, 'repair') == []
    errors = [f.category for f in audit.audit(project)[0] if f.severity == 'ERROR']
    assert 'NOT_REVERIFIED' in errors


def test_refused_candidate_names_the_residual_drv_in_the_audit(tmp_path, monkeypatch):
    import postroute_timing_repair_audit as audit
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-base': {'def': _def(True), 'sta_metrics': _sta_metrics(0.8, 0.4, (0, 0, 4)),
                    'antenna_metrics': _ant(0),
                    'repair_metrics': {'vibeic__prr__changed': 0}},
        '32-cand01': _cand(-0.05, 0.4, (0, 0, 1))})
    # The baseline has measured DRV residue; no candidate may trade setup
    # below its floor to clear it.
    report = prr.run_in_chain(project, mode='librelane', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim)
    assert report['adopted'] is None
    decision_path = project / prr.DECLARED_REPAIR_REL / 'postroute_timing_repair_decision.json'
    decision = json.loads(decision_path.read_text())
    assert decision['action'] == 'input_route_kept'
    assert (decision.get('residual') or {}).get('drv_count', 0) > 0
    errors = [f.category for f in audit.audit(project)[0] if f.severity == 'ERROR']
    assert 'REPAIR_REFUSED_RESIDUAL_DRV' in errors
    assert 'EMPTY_CHANGES' not in errors and 'NOT_REVERIFIED' not in errors


def test_dual_runs_three_arms_and_selects_by_hold_then_setup(tmp_path, monkeypatch):
    """review70 step 32 dual: A = the pre-DRT repair (step 21's LibreLane
    route with the flow's RUN_POST_GRT_* gates on), B = this repair after
    DRT, and A then B. Every arm is measured by the same instruments."""
    scenario = {
        '32-postdrt-base': _base(4.0, -0.3), '32-postdrt-cand01': _cand(3.99995, 0.30),
        '32-pregrt-base': _base(4.2, 0.10),
        '32-pregrt_postdrt-base': _base(4.2, 0.10)}
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, scenario)
    pre_state = put(project / 'phase3/librelane/21-route-pregrt/13-fill/state_out.json',
                    {'odb': 'p.odb', 'def': 'p.def'})
    seen = {}

    def variant_arm(lane, extra):
        seen[lane] = extra
        return {'final': pre_state, 'route_drc': [{'run': 'drt-run-0', 'markers': 0}]}
    report = prr.run_in_chain(project, mode='dual', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, variant_arm=variant_arm,
                              programs_dir=shim)
    assert set(seen['21-route-pregrt']) == set(prr.PREGRT_GATES)
    assert all(v[0] is True for v in seen['21-route-pregrt'].values())
    assert set(report['arms']) == set(prr.DUAL_ARMS)
    assert report['arms']['pregrt']['closure'] == [], 'arm A is the route alone'
    assert report['selected_arm'] == 'postdrt', report['selection']
    assert report['adopted'] == '32-postdrt-cand01'


def test_dual_publishes_decision_from_step32_input_when_pregrt_route_wins(
        tmp_path, monkeypatch):
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, {
        '32-postdrt-base': _base(4.0, -0.3),
        '32-pregrt-base': _base(4.2, 0.10),
        '32-pregrt_postdrt-base': _base(4.1, 0.05)})
    pre_state = put(project / 'phase3/librelane/21-route-pregrt/13-fill/state_out.json',
                    {'odb': 'p.odb', 'def': 'p.def'})

    def variant_arm(lane, extra):
        return {'final': pre_state, 'route_drc': [{'run': 'drt-run-0', 'markers': 0}]}

    report = prr.run_in_chain(project, mode='dual', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, variant_arm=variant_arm,
                              programs_dir=shim)
    assert report['selected_arm'] == 'pregrt'
    assert report.get('floors', {}) == report['arms']['pregrt']['floors']
    assert (report.get('input_baseline') or {}).get('hold_ws_min') == -0.3
    decision = json.loads((project / prr.DECLARED_REPAIR_REL /
                           'postroute_timing_repair_decision.json').read_text())
    assert decision['repair_needed'] is True
    assert decision['action'] == 'alternate_route_selected'
    assert decision['baseline']['hold_ws_min'] == -0.3
    assert decision['final']['hold_ws_min'] == 0.10
    assert not (project / prr.DECLARED_REPAIR_REL / 'no_repair_needed.flag').exists()


def test_dual_never_selects_an_arm_with_a_route_or_antenna_violation(tmp_path, monkeypatch):
    scenario = {
        '32-postdrt-base': _base(4.0, 0.2),
        '32-pregrt-base': _base(4.5, 0.5, antenna=2),
        '32-pregrt_postdrt-base': _base(4.5, 0.5, antenna=2)}
    project, shim, sdc, route = _chain_setup(tmp_path, monkeypatch, scenario)
    pre_state = put(project / 'phase3/librelane/21-route-pregrt/13-fill/state_out.json',
                    {'odb': 'p.odb', 'def': 'p.def'})
    report = prr.run_in_chain(
        project, mode='dual', image='img', pdk='pdk', pdk_root=tmp_path, sdc=sdc,
        derate=(0.95, 1.05), route_state=route, route_drc=0, programs_dir=shim,
        variant_arm=lambda lane, extra: {'final': pre_state, 'route_drc': []})
    assert report['selection']['feasible'] == ['postdrt']
    assert report['selected_arm'] == 'postdrt'


def test_the_route_chain_calls_step_32_before_its_handoff():
    """Source contract of step 21's one call site: step 32 runs on the
    selected route before the views are copied and the tail resumes."""
    src = (PROGRAMS / 'librelane_route.py').read_text()
    at = src.index('step32 = getattr(R, "postroute_repair_after_route", None)')
    assert at < src.index('targets = {"odb": out_dir / "routed_preantenna.odb",')
    assert 'views = dict(views, **post32["views"])' in src
    runner = importlib.import_module('phase3_one_shot_runner')
    assert callable(runner.postroute_repair_after_route)


def test_the_runner_records_the_in_chain_repair_without_repairing_twice(tmp_path, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    pnr = project / 'phase3/stage3/pnr'
    write(pnr / 'routed.def', 'DESIGN top ;\n# adopted\nEND DESIGN\n')
    write(pnr / 'dut_pnr.v', 'module top(); endmodule\n')
    write(pnr / 'constraint.sdc', '')
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'21': 'librelane', '32': 'librelane'}})
    report = put(project / prr.REPORT_REL, {
        'verdict': 'PASS', 'site': 'after_route', 'adopted': '32-cand01',
        'baseline': {'hold_ws_min': -0.3},
        'final': {'hold_ws_min': 0.3, 'antenna_nets': 0, 'antenna_pins': 0,
                  'antenna_state': 'cand01/02-checkantennas'},
        'candidates': [{'candidate': '32-cand01',
                        'repair_metrics': {'vibeic__prr__unrouted__added': 0}}]})
    put(project / 'reports/phase3/librelane_route_handoff.json',
        {'postroute_repair': {'report_sha256': contract.digest(report)},
         'views': {'def': {'dest_sha256': contract.digest(pnr / 'routed.def')}}})
    monkeypatch.setattr(prr, 'run', lambda *a, **k: pytest.fail('repaired twice'))
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    result = runner.step_postroute_repair_librelane(project, 'dut', pdk, 'unused')
    assert result.status == 'PASS' and 'in the step-21 LibreLane chain' in result.detail
    assert '# adopted' in (pnr / 'routed.def').read_text()
    assert json.loads((pnr / runner._DRV_PROMOTION_CLAIM).read_text())['promoted'] is True
    # a report the route receipt does not name is not this run's
    put(project / 'reports/phase3/librelane_route_handoff.json',
        {'postroute_repair': {'report_sha256': 'other'}})
    assert runner._postroute_repair_in_chain_report(project) is None


def test_the_route_hook_hands_on_the_adopted_database_and_keeps_the_base(tmp_path, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    put(project / 'phase3/librelane_switch.json', {'steps': {'21': 'librelane', '32': 'dual'}})
    base_def = write(tmp_path / 'route.def', 'DESIGN top ;\nEND DESIGN\n')
    route_state = put(tmp_path / 'route_state.json', {'odb': 'r.odb', 'def': str(base_def)})
    adopted = put(tmp_path / 'cand/state_out.json', {'odb': str(tmp_path / 'c.odb'),
                                                     'def': str(tmp_path / 'c.def')})
    calls = {}

    def run_in_chain(project_, **kw):
        calls.update(kw)
        return put(project_ / prr.REPORT_REL, {'verdict': 'PASS', 'adopted': '32-postdrt-cand01',
                                               'adopted_state': str(adopted),
                                               'selected_arm': 'postdrt',
                                               # its own measurement (cmp3 D15)
                                               'final': {'antenna_nets': 0, 'antenna_pins': 0},
                                               'candidates': [{
                                                   'candidate': '32-postdrt-cand01',
                                                   'repair_metrics': {
                                                       'vibeic__prr__unrouted__added': 0}}]}) and \
            json.loads((project_ / prr.REPORT_REL).read_text())
    monkeypatch.setattr(prr, 'run_in_chain', run_in_chain)
    monkeypatch.setattr(runner, '_discover_aocv_table',
                        lambda project_, pdk_, container_: '/declared/table.aocv')
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    out = runner.postroute_repair_after_route(
        project=project, pdk=pdk, image='img', pdk_root=tmp_path, sdc=base_def,
        deck='add_global_connection -net VDD -pin_pattern {^VDD$} -power\n',
        route_state=route_state, route_views={'odb': tmp_path / 'r.odb', 'def': base_def},
        route_drc=0, variant_arm=lambda *a: None, container='eda')
    assert calls['mode'] == 'dual' and calls['route_state'] == route_state
    assert calls['aocv_table'] == '/declared/table.aocv'
    assert out['views'] == {'odb': tmp_path / 'c.odb', 'def': tmp_path / 'c.def'}
    assert out['record']['report_sha256'] == contract.digest(project / prr.REPORT_REL)
    assert (runner._pl.pnr_dir(project) / 'routed_base_prerepair.def').read_text() == base_def.read_text()
    # step 32 direct, or a direct route handed over: nothing runs here
    put(project / 'phase3/librelane_switch.json', {'steps': {'21': 'librelane'}})
    assert runner.postroute_repair_after_route(
        project=project, pdk=pdk, image='img', pdk_root=tmp_path, sdc=base_def, deck='',
        route_state=route_state, route_views={}, route_drc=0, variant_arm=None) is None


def test_the_class_default_route_resolves_the_pdk_like_every_other_step(tmp_path, monkeypatch):
    """r4: with no switch file the route asks the contract's resolver for THIS
    design's PDK and image (materialised from the image), as 15..20 and 32 do;
    measured on spm: asking with no PDK/image refused LL_PDK_ROOT_NOT_DECLARED."""
    import test_librelane_route as tr
    runner = tr.runner
    project, out_dir, pnr_tcl = tr._route_project(tmp_path, {'steps': {'21': 'librelane'}})
    (project / 'phase3/librelane_switch.json').unlink(missing_ok=True)

    def docker(container, cmd, *a, **k):
        for ext in ('odb', 'def', 'nl.v'):
            write(out_dir / f'route_split/pre_route.{ext}', 'x\n')
        return 0, '', ''
    asked = {}

    def resolver(*a, **k):
        asked.update(args=a, kwargs=k)
        return None
    monkeypatch.setattr(runner, '_docker_exec', docker)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    monkeypatch.setattr(contract, 'resolve_pdk_root', resolver)
    rc, out, _ = tr.route.execute(
        runner, project=project, pdk=SimpleNamespace(name='pdkX'), container='c',
        out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl, mode='librelane',
        cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None,
        exec_kwargs={})
    assert asked['args'][:2] == (project, 'pdkX')
    assert asked['kwargs']['image'] == contract.resolve_image(project)


def test_every_geometry_step_reads_the_routes_tech_lef(tmp_path, monkeypatch):
    """T105: the route's via-legalized tech LEF, bound by sha256, is what
    step 32's RCX and bridge read; an APPLIED record whose file is gone
    refuses by name instead of falling back to the PDK's LEF."""
    import librelane_pv_signoff as pv
    project = tmp_path / 'proj'
    sdc = write(project / 'phase3/stage3/pnr/constraint.sdc', '')
    lef = write(project / 'phase3/stage3/pnr/active_via_legalized.tlef', 'VERSION 5.8 ;\n')
    put(project / pv.VIA_LEGALIZATION_REL, {'status': 'APPLIED', 'derived_tech_lef': str(lef),
                                            'derived_sha256': contract.digest(lef)})
    seen = {}

    def configs(project_, image, pdk, ids, *, pdk_root, folder, overlay, docker):
        seen.update(overlay)
        root = project_ / 'phase3/librelane' / folder
        return {i: put(root / f'{i}.json', {'meta': {'step': i}, 'STA_CORNERS': CORNERS})
                for i in ids}
    monkeypatch.setattr(contract, 'resolve_step_configs', configs)
    prr._prepare(project, image='img', pdk='pdk', pdk_root=tmp_path, sdc=sdc,
                 derate=(0.95, 1.05), pg_rules_tcl=None, refill_tcl=None, docker='docker')
    assert seen['TECH_LEFS'][0] == {'*': str(lef.resolve())}
    lef.write_text('changed\n')
    with pytest.raises(contract.Refusal) as exc:
        prr._prepare(project, image='img', pdk='pdk', pdk_root=tmp_path, sdc=sdc,
                     derate=(0.95, 1.05), pg_rules_tcl=None, refill_tcl=None, docker='docker')
    assert exc.value.code == 'LL_ROUTE_TECH_LEF_UNBOUND'


@pytest.mark.parametrize('changed', [False, True], ids=['same-route', 'new-route'])
def test_chain_reuse_requires_the_current_route_not_just_an_old_report_hash(tmp_path, changed):
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'proj'
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'21': 'librelane', '32': 'librelane'}})
    route = write(project / 'phase3/stage3/pnr/routed.def',
                  'DESIGN top ;\n# first route\nEND DESIGN\n')
    old_hash = contract.digest(route)
    old_state = put(project / 'old/state_out.json', {'def': str(route)})
    report = put(project / prr.REPORT_REL,
                 {'site': 'after_route', 'verdict': 'FAIL',
                  'route_state': str(old_state), 'adopted_state': str(old_state),
                  'code': 'OLD_ROUTE_DRV', 'reason': 'old measured route failed'})
    put(project / 'reports/phase3/librelane_route_handoff.json', {
        'views': {'def': {'dest_sha256': old_hash}},
        'postroute_repair': {'report_sha256': contract.digest(report)}})
    if changed:
        # The mutable state still names this path, and the old report/hash
        # pair is valid. Neither proves this newly published route was measured.
        route.write_text('DESIGN top ;\n# new placement and routing\nEND DESIGN\n')
    reused, why = runner._postroute_repair_in_chain(project)
    if changed:
        assert reused is None, 'the consumer returned results for the old route'
        assert 'current route' in why
    else:
        assert reused is not None, why
        assert reused['verdict'] == 'FAIL' and reused['code'] == 'OLD_ROUTE_DRV'


def test_a_repair_not_found_in_the_chain_says_so_and_why(tmp_path, monkeypatch, capsys):
    """silent_decline_audit: when step 32 is not taken from the step-21 chain,
    the decline is disclosed with its reason before the after-route repair."""
    runner = importlib.import_module('phase3_one_shot_runner')
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    put(project / 'phase3/librelane_switch.json', {'steps': {'21': 'direct', '32': 'librelane'}})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    runner.step_postroute_repair_librelane(project, 'dut', pdk, 'unused')
    err = capsys.readouterr().err
    assert 'PRR_NOT_IN_CHAIN: step 21 routed direct' in err
    put(project / 'phase3/librelane_switch.json', {'steps': {'21': 'librelane', '32': 'librelane'}})
    put(project / 'reports/phase3/librelane_route_handoff.json', {'postroute_repair': None})
    report, why = runner._postroute_repair_in_chain(project)
    assert report is None and 'names no step-32 report' in why



@pytest.mark.parametrize("owner", ["fork_capability", "openroad_convert", "native_sta"])
@pytest.mark.parametrize("profile", ["local_host", "local_none", "remote"])
def test_native_postroute_callers_use_the_current_provider(tmp_path, monkeypatch, owner, profile):
    """Real owners and LOCAL guards; only expensive process leaves are neutral."""
    import _watchdog as watchdog
    import _container_exec as container_exec
    from test_librelane_contract import _host_provider

    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "4g")
    if profile.startswith("local_"):
        network = profile.removeprefix("local_")
        monkeypatch.setenv("VIBEIC_LIBRELANE_LOCAL_NETWORK", network)
        project, image = _host_provider(tmp_path, monkeypatch)
        assert image.network_mode == network
    else:
        network = "none"
        monkeypatch.delenv(contract.LOCAL_PROVIDER_ROUTE_ENV, raising=False)
        monkeypatch.setattr(container_exec, "no_container_route", lambda: False)
        image = "registry.invalid/capability@sha256:" + "aa" * 32
        project = tmp_path / "project"
        project.mkdir()
    folder = project / "neutral-tool"
    folder.mkdir()
    output = folder / "native.rpt"
    script = folder / "native.tcl"
    script.write_text("# neutral native process input\n")
    observed = {"owner": owner, "profile": profile, "calls": [], "launches": [],
                "provider": image.as_record() if profile.startswith("local_") else None}
    original_run_container = contract.run_container

    def record_launch(argv, **kwargs):
        observed["launches"].append(list(argv))
        return original_run_container(argv, **kwargs)

    def payload():
        if owner == "fork_capability":
            return FORK_TRANSCRIPT
        output.write_text("NEUTRAL_NATIVE_REPORT\n")
        return "NEUTRAL_NATIVE_STDOUT\n"

    def host_leaf(argv, **kwargs):
        call = {"route": "Docker" if argv[0] == "docker" else "LOCAL", "argv": list(argv)}
        if call["route"] == "LOCAL":
            call.update(network=kwargs["env"]["VIBEIC_LOCAL_NETWORK_MODE"],
                        pythonpath=kwargs["env"]["PYTHONPATH"])
        observed["calls"].append(call)
        return watchdog.SupervisedResult(0, payload(), "", "natural")

    def docker_leaf(argv, **kwargs):
        observed["calls"].append({"route": "Docker", "argv": list(argv)})
        return subprocess.CompletedProcess(argv, 0, payload(), "")

    monkeypatch.setattr(contract, "run_container", record_launch)
    monkeypatch.setattr(watchdog, "run_host_supervised", host_leaf)
    monkeypatch.setattr(contract.subprocess, "run", docker_leaf)
    try:
        if owner == "fork_capability":
            result = prr.fork_capability(image)
            assert result["capable"] is True
            native_command = ["bash", "-c"]
        elif owner == "openroad_convert":
            tech = tmp_path / "neutral.tech.lef"
            tech.write_text("# neutral process material\n")
            result = contract._openroad_convert(project, image,
                {"TECH_LEFS": {"nom_*": str(tech)}}, ["exit"], folder, "convert", [], "docker")
            assert result.is_file() and "read_lef" in result.read_text()
            native_command = ["openroad", "-exit", str(result)]
        else:
            native._run({"project": str(project), "image": image, "mounts": []}, script, output)
            assert output.read_text() == "NEUTRAL_NATIVE_REPORT\n"
            native_command = ["openroad", "-no_init", "-exit", str(script)]
        observed["completed"] = True
    except contract.Refusal as exc:
        observed["refusal"] = {"code": exc.code, "detail": str(exc)}
        raise
    finally:
        (tmp_path / "STEP32_PROVIDER_OBSERVATION.json").write_text(
            json.dumps(observed, indent=2) + "\n")
    assert len(observed["calls"]) == len(observed["launches"]) == 1
    call, launch = observed["calls"][0], observed["launches"][0]
    if profile.startswith("local_"):
        assert call["route"] == "LOCAL" and call["network"] == network
        assert ("--unshare-net" in call["argv"]) is (network == "none")
        assert call["pythonpath"].split(os.pathsep)[0] == image.librelane_root
        launcher = "import os,sys;os.execvp(sys.argv[1],sys.argv[1:])"
        index = call["argv"].index(launcher)
        assert call["argv"][index - 2:index] == [image.executable, "-c"]
        assert call["argv"][index + 1:index + 1 + len(native_command)] == native_command
        assert launch[launch.index("--network") + 1] == network
    else:
        assert call["route"] == "Docker"
        assert ("--network" in launch) is (owner != "native_sta")
        if "--network" in launch:
            assert launch[launch.index("--network") + 1] == "none"
        assert not any("os.execvp" in str(part) for part in launch)
        assert call["argv"][-len(native_command):] == native_command or owner == "fork_capability"


def test_native_sta_consumes_normalized_lib_for_every_declared_scene(tmp_path, monkeypatch):
    """The real measure builds every script; only OpenROAD file writes are neutral."""
    odb = write(tmp_path / 'route.odb', 'neutral routed database')
    sdc = write(tmp_path / 'route.sdc', 'create_clock -period 20 [get_ports clk]\n')
    state = put(tmp_path / 'state.json', {'odb': str(odb), 'sdc': str(sdc)})
    corners = [f'{rc}_{pvt}' for rc in ('nom', 'min', 'max')
               for pvt in ('tt_025C_5v00', 'ss_125C_4v50', 'ff_n40C_5v50')]
    libraries = {f'*_{pvt}': [str(write(tmp_path / f'{pvt}.lib', 'neutral liberty'))]
                 for pvt in ('tt_025C_5v00', 'ss_125C_4v50', 'ff_n40C_5v50')}
    pads = {pattern: [str(write(tmp_path / f'pad_{i}.lib', 'neutral pad liberty'))]
            for i, pattern in enumerate(libraries)}
    rules = {f'{rc}_*': str(write(tmp_path / f'{rc}.rcx', 'neutral extraction rules'))
             for rc in ('nom', 'min', 'max')}
    config = {'RCX_RULESETS': rules, 'LIB': libraries, 'PAD_LIBS': pads,
              'STA_CORNERS': corners, 'DEFAULT_CORNER': corners[0]}
    path = put(tmp_path / 'rcx.json', config)
    ctx = {'project': str(tmp_path), 'image': 'neutral image', 'mounts': [],
           'configs': {'OpenROAD.RCX': str(path)}, 'corners': corners,
           'derate': [0.95, 1.05]}
    scripts = {}

    def tool_writes(_ctx, script, output):
        scripts[script.name] = script.read_text()
        output.write_text('*SPEF "IEEE 1481-1998"\n' if script.name.startswith('extract_')
                          else 'OCV_BASIS flat_ocv\nworst slack max 1.250000\n'
                               'worst slack min 0.125000\n')

    monkeypatch.setattr(native, '_run', tool_writes)
    result = REAL_NATIVE_MEASURE(ctx, state, tmp_path / 'normalized')
    assert set(result['setup_ws']) == set(result['hold_ws']) == set(corners)
    assert result['setup_ws_min'] == 1.25 and result['hold_ws_min'] == 0.125
    assert len([name for name in scripts if name.startswith('extract_')]) == 3
    default_lib = libraries['*_tt_025C_5v00'][0]
    for name, text in scripts.items():
        if name.startswith('extract_'):
            assert f'read_liberty {{{default_lib}}}' in text
        else:
            corner = name[len('sta_'):-len('.tcl')]
            group = next(pattern for pattern in libraries if native.fnmatch.fnmatch(corner, pattern))
            assert [line for line in text.splitlines() if line.startswith('read_liberty ')] == [
                f'read_liberty {{{lib}}}' for lib in [*libraries[group], *pads[group]]]
            assert text.index('set_timing_derate -late') < text.index('report_worst_slack -max')
    # An explicit modern declaration wins; legacy data cannot rescue empty/invalid LIB.
    for invalid in ({}, None):
        put(path, {**config, 'LIB': invalid, 'CELL_LIBS': libraries})
        before = len(scripts)
        with pytest.raises((ValueError, AttributeError, TypeError)):
            REAL_NATIVE_MEASURE(ctx, state, tmp_path / 'invalid')
        assert len(scripts) == before
    legacy = {key: value for key, value in config.items() if key != 'LIB'}
    put(path, {**legacy, 'CELL_LIBS': libraries})
    prior = REAL_NATIVE_MEASURE(ctx, state, tmp_path / 'legacy')
    assert prior['setup_ws'] == result['setup_ws'] and prior['hold_ws'] == result['hold_ws']
    (tmp_path / 'LIB_SCENE_OBSERVATION.json').write_text(json.dumps({
        'modern_key': 'LIB', 'legacy_fallback': True, 'corners': corners,
        'default_corner': config['DEFAULT_CORNER'], 'read_liberty_by_script': {
            name: [line for line in text.splitlines() if line.startswith('read_liberty ')]
            for name, text in scripts.items()}, 'setup': result['setup_ws'],
        'hold': result['hold_ws'], 'neutral_process_leaf_only': True}, indent=2) + '\n')


@pytest.mark.parametrize('changed,enabled,slew,expected', [
    (5, 1, 10, 1), (0, 1, 10, 1), (5, 0, 10, 0),
    (5, 1, 0, 0), (5, None, 10, 0)])
def test_bounded_sizing_finishes_native_buffer_repair(changed, enabled, slew, expected):
    """Execute the shipped Tcl dispatch; native edits must not suppress repair.

    The native EDA calls are controlled here, not the branch under test.
    Existing adoption tests still judge the final candidate after rerouting.
    """
    script = (STEP_DIR / 'postroute_repair.tcl').read_text()
    start = script.index('if {[info exists ::env(VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH)]')
    branch = script[start:script.index('# ---- 5. what changed', start)]
    enable = ('unset -nocomplain ::env(VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH)' if enabled is None
              else f'set ::env(VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH) {enabled}')
    harness = f"""
namespace eval sta {{}}
set ::vic_native_changed {changed}
set ::calls 0
{enable}
proc sta::max_slew_violation_count {{}} {{return {slew}}}
proc vic_say {{msg}} {{}}
proc vic_bounded_drive_strength {{}} {{incr ::calls}}
{branch}
puts "CALLED=$::calls"
"""
    result = subprocess.run(['tclsh'], input=harness, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert result.stdout.strip() == f'CALLED={expected}'


def test_routed_wire_bound_reuses_shared_def_geometry_spellings(tmp_path):
    routed = tmp_path / "native.def"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"def": str(routed)}))
    observed = []
    for rectangle in ("( 0 0 ) ( 3000000 2400000 )", "( 0 0 3000000 2400000 )"):
        routed.write_text("UNITS DISTANCE MICRONS 1000 ;\nDIEAREA " + rectangle + " ;\n")
        try:
            observed.append(prr._die_derived_max_wire_length(state))
        except ValueError:
            observed.append("REJECTED")
    assert observed == [800.0, 800.0]


# ---------------- retained density-refused candidate finishing continuation --

def _finishing_controller_fixture(tmp_path):
    project = tmp_path / 'project'
    impl = project / prr.ARM_REL / prr.IMPL_DIR

    def candidate_state(name, drv, members):
        root = project / f'phase3/librelane/{name}/01-vibeic-postrouterepair'
        odb = write(root / 'top.odb', f'{name} odb\n')
        state = put(root / 'state_out.json', {'odb': str(odb)})
        sta = put(project / f'phase3/librelane/{name}/04-openroad-stapostpnr/state_out.json',
                  {'metrics': {}})
        return state, {
            'sta_state': str(sta), 'sta_state_sha256': contract.digest(sta),
            'native_odb_sha256': contract.digest(odb),
            'setup_ws_min': 1.0, 'hold_ws_min': 0.5,
            'drv_count': drv, 'drv_members': members,
            'antenna_nets': 0, 'antenna_pins': 0,
        }

    old_state, old_measurement = candidate_state('32-cand01', 1, [['u/Z', 'cap']])
    new_state, new_measurement = candidate_state('32-cand09', 0, [])
    put(impl / prr.CONTEXT, {'project': str(project), 'floors': {}})
    put(impl / prr.CURRENT, {
        'candidate': '32-cand01', 'repair_input': str(old_state),
        'repair_state': str(old_state), 'repair_folder': str(old_state.parent),
        'measurement': old_measurement})
    ledger = project / prr.ARM_REL / prr.LEDGER
    put(ledger, {'candidates': [{
        'candidate': '32-cand09', 'from': '32-cand01',
        'repair_state': str(new_state), 'measurement': new_measurement,
        'supply_ownership': {'verdict': 'PASS'}}]})
    finished = write(tmp_path / 'finished.gds', 'finished geometry\n')
    current = impl / prr.CURRENT
    record = put(tmp_path / 'ready.json', {
        'schema': 'vibeic.prr.candidate_finishing.v1',
        'verdict': 'READY_FOR_CONTROLLER', 'candidate': '32-cand09',
        'current_before_sha256': contract.digest(current),
        'ledger_sha256': contract.digest(ledger),
        'repair_state_sha256': contract.digest(new_state),
        'sealed_inputs': {str(finished): contract.digest(finished)},
        'finished_gds': str(finished),
        'finished_gds_sha256': contract.digest(finished)})
    return project, impl, current, record, finished


def test_finished_candidate_uses_normal_controller_measurement_and_promotes(tmp_path):
    project, _impl, current, record, _finished = _finishing_controller_fixture(tmp_path)
    run = prr._run_finished_candidate_controller(
        project, record, registry=REGISTRY, programs_dir=PROGRAMS)
    assert run['outcome'] == 'CONVERGED'
    assert run['iterations'][0]['decision'] == 'PROMOTED'
    assert run['iterations'][0]['objective_before'] == 1
    assert run['iterations'][0]['objective_after'] == 0
    adopted = json.loads(current.read_text())
    assert adopted['candidate'] == '32-cand09'
    assert adopted['finished_gds_sha256'] == contract.digest(
        Path(adopted['finished_gds']))


def test_finished_candidate_stale_sealed_input_never_enters_adopted_state(tmp_path):
    project, _impl, current, record, finished = _finishing_controller_fixture(tmp_path)
    before = current.read_bytes()
    finished.write_text('stale geometry\n')
    run = prr._run_finished_candidate_controller(
        project, record, registry=REGISTRY, programs_dir=PROGRAMS)
    assert run['outcome'] == 'NOT_MEASURED'
    assert run['iterations'][0]['decision'] == 'ACTUATOR_FAILED'
    assert current.read_bytes() == before


def test_finished_candidate_wrong_identity_refuses_before_any_native_consumer(tmp_path):
    project = tmp_path / 'project'
    impl = project / prr.ARM_REL / prr.IMPL_DIR
    put(impl / prr.CONTEXT, {'project': str(project)})
    put(impl / prr.CURRENT, {'candidate': '32-cand01'})
    put(project / prr.REPORT_REL, {'adopted': '32-cand01'})
    put(project / prr.ARM_REL / prr.LEDGER, {'candidates': []})
    before = (impl / prr.CURRENT).read_bytes()
    with pytest.raises(contract.Refusal, match='LL_PRR_FINISHING_CANDIDATE_UNKNOWN'):
        prr._retained_candidate_finishing_inputs(project, '32-cand08')
    assert (impl / prr.CURRENT).read_bytes() == before


@pytest.mark.parametrize('case,reason', [
    ('density', 'LL_PRR_FINISHING_DENSITY_FAILED'),
    ('lvs_scope', 'LL_PRR_FINISHING_LVS_SUBJECT_MISMATCH'),
])
def test_finishing_or_pv_refusal_never_calls_controller_or_changes_pointer(
        tmp_path, monkeypatch, case, reason):
    project = tmp_path / 'project'
    impl = project / prr.ARM_REL / prr.IMPL_DIR
    current = put(impl / prr.CURRENT, {'candidate': '32-cand01'})
    before = current.read_bytes()
    state = put(tmp_path / 'state.json', {})
    config = put(tmp_path / 'config.json', {})
    gds = write(tmp_path / 'before.gds', 'before\n')
    finished_gds = write(tmp_path / 'after.gds', 'after\n')
    retained = {
        'ctx': {'project': str(project), 'image': 'image', 'pdk': 'processA',
                'mounts': [[str(tmp_path / 'pdk'), contract.PDK_GUEST_ROOT]]},
        'current': {'candidate': '32-cand01'},
        'row': {'decision': 'REFUSED'}, 'report': {},
        'report_path': project / prr.REPORT_REL,
        'ledger_path': put(project / prr.ARM_REL / prr.LEDGER, {'candidates': []}),
        'paths': {'repair_state': state, 'config': config, 'gds': gds},
        'hashes': {'repair_state': contract.digest(state),
                   'config': contract.digest(config), 'gds': contract.digest(gds),
                   'def': 'd' * 64},
        'current_freshness': {'verdict': 'PASS'}, 'density_before': 3,
    }
    monkeypatch.setattr(prr, '_retained_candidate_finishing_inputs',
                        lambda *_a, **_k: retained)
    fill = importlib.import_module('librelane_fill_dfm')
    density = 1 if case == 'density' else 0
    monkeypatch.setattr(fill, 'finish_candidate_gds', lambda *_a, **_k: {
        'gds': str(finished_gds), 'gds_sha256': contract.digest(finished_gds),
        'density': {'klayout__density_error__count': density,
                    'checker_error': None}})
    lvs_scope = {'gds_sha256': contract.digest(finished_gds),
                 'def_sha256': 'd' * 64, 'magic_ext_use_gds': True,
                 'extracted_gds_sha256': (('e' * 64) if case == 'lvs_scope'
                                           else contract.digest(finished_gds))}
    monkeypatch.setattr(prr, '_finished_candidate_pv', lambda *_a, **_k: {
        'drc': {'verdict': 'PASS', 'scope': {
            'gds_sha256': contract.digest(finished_gds), 'def_sha256': 'd' * 64}},
        'lvs': {'verdict': 'PASS', 'scope': lvs_scope}})
    entered = []
    monkeypatch.setattr(prr, '_run_finished_candidate_controller',
                        lambda *_a, **_k: entered.append(True))
    with pytest.raises(contract.Refusal, match=reason):
        prr.resume_candidate_finishing(project, '32-cand09', f'lane-{case}')
    assert entered == []
    assert current.read_bytes() == before


def test_retained_finish_lane_uses_resume_helper_then_the_same_pv_gate(
        tmp_path, monkeypatch):
    project = tmp_path / 'project'
    impl = project / prr.ARM_REL / prr.IMPL_DIR
    current = put(impl / prr.CURRENT, {'candidate': '32-cand01'})
    state = put(tmp_path / 'state.json', {})
    config = put(tmp_path / 'config.json', {})
    old_gds = write(tmp_path / 'old.gds', 'old\n')
    finished_gds = write(tmp_path / 'finished.gds', 'finished\n')
    ledger = put(project / prr.ARM_REL / prr.LEDGER, {'candidates': []})
    retained = {
        'ctx': {'project': str(project), 'image': 'image', 'pdk': 'processA',
                'mounts': [[str(tmp_path / 'pdk'), contract.PDK_GUEST_ROOT]]},
        'current': {'candidate': '32-cand01'}, 'row': {'decision': 'REFUSED'},
        'report': {}, 'report_path': project / prr.REPORT_REL,
        'ledger_path': ledger,
        'paths': {'repair_state': state, 'config': config, 'gds': old_gds},
        'hashes': {'repair_state': contract.digest(state),
                   'config': contract.digest(config), 'gds': contract.digest(old_gds),
                   'def': 'd' * 64},
        'current_freshness': {'verdict': 'PASS'}, 'density_before': 3,
    }
    monkeypatch.setattr(prr, '_retained_candidate_finishing_inputs',
                        lambda *_a, **_k: retained)
    fill = importlib.import_module('librelane_fill_dfm')
    calls = []
    monkeypatch.setattr(fill, 'finish_candidate_gds',
                        lambda *_a, **_k: pytest.fail('must not replay finishing'))
    def resume(*_args, **kwargs):
        calls.append(kwargs)
        return {'gds': str(finished_gds),
                'gds_sha256': contract.digest(finished_gds),
                'density': {'klayout__density_error__count': 0,
                            'checker_error': None}}
    monkeypatch.setattr(fill, 'resume_candidate_gds', resume)
    monkeypatch.setattr(prr, '_finished_candidate_pv', lambda *_a, **_k: {
        'drc': {'verdict': 'FAIL', 'scope': {}},
        'lvs': {'verdict': 'PASS', 'scope': {}}})
    with pytest.raises(contract.Refusal, match='LL_PRR_FINISHING_DRC_FAIL'):
        prr.resume_candidate_finishing(
            project, '32-cand09', '32-cand09-finishing-02',
            reuse_finished_lane='32-cand09-finishing-01')
    assert calls == [{
        'gds': old_gds, 'state': state, 'config': config,
        'lane': '32-cand09-finishing-01',
        'ratio_lane': '32-cand09-finishing-02-ratios'}]
    assert json.loads(current.read_text())['candidate'] == '32-cand01'

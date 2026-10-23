"""T100: steps 22/23 through LibreLane OpenROAD.RCX + STAPostPNR (opt-in).

The contract, the module and the runner helpers run for real; only an EDA
tool's file writes are substituted at the subprocess edge.  The STA log lines
and metric names are LibreLane 3.1's own (copied from a 0.3.79 STAPostPNR run
on the spm chip).
"""
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
from _stated_eda_image import stated_image, state_the_image, mock_docker_route  # noqa: E402
import _eda_pin  # noqa: E402
signoff = importlib.import_module('librelane_signoff')

CORNERS = ('nom_tt_025C_5v00', 'max_ss_125C_4v50', 'min_ff_n40C_5v50')
RULESETS = {'nom_*': '/pdk/x/rules.nom', 'min_*': '/pdk/x/rules.min', 'max_*': '/pdk/x/rules.max'}


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    mock_docker_route(monkeypatch)
    monkeypatch.setattr(contract, '_CAPABILITY', {}, raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    state_the_image(monkeypatch)   # the identity is stated, never asked of this host


# ------------------------------------------------------- the extra Tcl ---

def _tcl_run(tmp_path, extra: Path, env: dict) -> tuple[str, str]:
    """Source the extra corner Tcl in tclsh with OpenSTA's derate command
    recorded, the way LibreLane's corner.tcl sources it."""
    harness = write(tmp_path / 'harness.tcl', (
        'set ::calls {}\n'
        'proc set_timing_derate {flag value} { lappend ::calls $flag $value }\n'
        'set corner_name max_ss_125C_4v50\n'
        f'source {extra}\n'
        'puts [join $::calls " "]\n'))
    run_env = {'PATH': '/usr/bin:/bin', '_LIB_SAVE_DIR': str(tmp_path), **env}
    out = subprocess.run(['tclsh', str(harness)], capture_output=True, text=True, env=run_env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip(), (tmp_path / signoff.CORNER_REPORT).read_text()


@pytest.mark.skipif(shutil.which('tclsh') is None, reason='needs tclsh')
def test_integer_percent_derates_by_that_percent_not_by_zero(tmp_path):
    """The PDK declares TIME_DERATING_CONSTRAINT 5; LibreLane's base.sdc
    computes 1-[expr 5 / 100] = 1 (no derate).  The extra Tcl divides by 100.0."""
    extra = signoff.write_extra_corner_tcl(tmp_path)
    calls, report = _tcl_run(tmp_path, extra, {'TIME_DERATING_CONSTRAINT': '5'})
    assert calls == '-early 0.95 -late 1.05'
    assert 'OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV source=TIME_DERATING_CONSTRAINT=5' in report
    assert 'STA_BASIS_CORNER: max_ss_125C_4v50' in report


@pytest.mark.skipif(shutil.which('tclsh') is None, reason='needs tclsh')
def test_an_undeclared_percent_applies_no_derate_and_says_so(tmp_path):
    extra = signoff.write_extra_corner_tcl(tmp_path)
    calls, report = _tcl_run(tmp_path, extra, {})
    assert calls == ''
    assert signoff.NO_DERATE_MARKER in report and signoff.DERATE_MARKER not in report


def test_report_body_is_the_direct_decks_emitters_on_the_corner_report():
    runner = importlib.import_module('phase3_one_shot_runner')
    body = runner._librelane_signoff_report_body()
    for needle in ('report_worst_slack -max >> $_vibeic_rpt', 'report_worst_slack -min >> $_vibeic_rpt',
                   'report_check_types -recovery -removal', runner._SIGNOFF_CHECK_TYPES_MARKER,
                   runner._SIGNOFF_WNS_MARKER, runner._SIGNOFF_WORST_PATHS_MARKER):
        assert needle in body


# ------------------------------------------------ run(): the chain edge ---

def _tool_edge(tmp_path, *, rulesets=RULESETS, calls=None):
    """SOURCE_FIXTURE producer; no native extraction or PDK accuracy claim.

    The real run_chain owns the fingerprint and receipt. This double supplies
    mounted, digestible fixture inputs and the files LibreLane would write;
    it does not replace any producer validator or signoff consumer.
    """
    calls = calls if calls is not None else []
    fixture_pdk = tmp_path / 'pdkroot/gf/source-fixture'
    tech_lef = write(fixture_pdk / 'tech.lef',
                     'VERSION 5.8 ;\nUNITS\n  DATABASE MICRONS 1000 ;\n'
                     'END UNITS\nEND LIBRARY\n')
    fixture_rules = {}
    for pattern, declared in rulesets.items():
        rule = put(fixture_pdk / f'rules.{pattern.strip("*_")}.json',
                   {'scope': 'SOURCE_FIXTURE', 'corner_pattern': pattern,
                    'declared_fixture_path': declared,
                    'native_accuracy': 'NOT_MEASURED'})
        fixture_rules[pattern] = '/pdk/gf/source-fixture/' + rule.name

    def fake(cmd, **_):
        calls.append(cmd)
        text = ' '.join(map(str, cmd))
        if 'librelane.steps run --help' in text or 'bash' in cmd:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if 'from librelane.flows.chip import Chip' in text:
            design, requested, output = Path(cmd[-6]), Path(cmd[-5]), Path(cmd[-4])
            for step in json.loads(requested.read_text()):
                cfg = {'meta': {'step': step},
                       'TECH_LEFS': {'nom_*': '/pdk/gf/source-fixture/' + tech_lef.name},
                       'RCX_RULESETS': fixture_rules,
                       'STA_CORNERS': [c for c in CORNERS if c.split('_', 1)[0] + '_*' in rulesets],
                       'TIME_DERATING_CONSTRAINT': 5,
                       **json.loads(design.read_text()),
                       'DESIGN_NAME': 'chip_top'}
                put(output / f'{step}.json', cfg)
                ins = ['def'] if step == 'OpenROAD.RCX' else ['nl', 'spef', 'odb']
                outs = ['spef'] if step == 'OpenROAD.RCX' else ['sdf', 'lib']
                put(output / f'{step}.views.json', {'step': step, 'inputs': ins, 'outputs': outs})
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if 'openroad' in cmd and '-exit' in cmd:
            tcl = Path(cmd[-1])
            odb = tcl.read_text().split('write_db {')[1].split('}')[0]
            write(Path(odb), 'odb')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if '-o' in cmd:
            folder = Path(cmd[cmd.index('-o') + 1])
            input_path = Path(cmd[cmd.index('-i') + 1])
            config_path = Path(cmd[cmd.index('-c', cmd.index('--id')) + 1])
            shutil.copyfile(input_path, folder / 'state_in.json')
            shutil.copyfile(config_path, folder / 'config.json')
            put(folder / 'source_fixture.json',
                {'scope': 'SOURCE_FIXTURE', 'constructor': '_tool_edge',
                 'native_execution': 'NOT_RUN', 'native_accuracy': 'NOT_MEASURED'})
            state = json.loads(input_path.read_text())
            step = cmd[cmd.index('--id') + 1]
            if step == 'OpenROAD.RCX':
                state['spef'] = {p: str(write(folder / p.strip('*_') / f'chip_top.{p.strip("*_")}.spef',
                                              RCX_FIXTURE_SPEFS[p])) for p in rulesets}
            put(folder / 'state_out.json', state)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(f'unexpected tool call: {cmd}')
    return fake


def _project(tmp_path):
    p = tmp_path / 'design'
    put(p / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains': [{'role': 'primary', 'period_ns': 24, 'source_pin': 'clk'}]})
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {})
    put(p / 'input/submission_template/tapeout_declaration.json', {'answers': {'top_cell': 'spm'}})
    pnr = p / 'phase3/stage3/pnr'
    write(pnr / 'spm.def', 'VERSION 5.8 ;\nDESIGN chip_top ;\nCOMPONENTS 0 ;\n')
    write(pnr / 'spm_pnr.v', 'module spm(); endmodule\n')
    write(pnr / 'constraint.sdc', 'create_clock -period 24 [get_ports clk]\n')
    root = tmp_path / 'pdkroot'
    (root / 'gf').mkdir(parents=True)
    return p, pnr, root


def test_step_23_alone_times_the_direct_spefs_bound_to_the_pdk_corner_patterns(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    calls = []
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path, calls=calls))
    direct = {c: write(p / f'phase3/stage3/extracted/spef_corners/spm.{c}.spef', f'direct {c}')
              for c in ('nom', 'min', 'max')}
    result = signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                         sdc=pnr / 'constraint.sdc', extract=False, time=True, direct_spefs=direct)
    steps = [c[c.index('--id') + 1] for c in calls if '--id' in c]
    assert steps == ['OpenROAD.STAPostPNR']           # no RCX when 22 stays direct
    state_in = json.loads((result['sta'] / 'state_out.json').read_text())
    assert state_in['spef'] == {p_: str(direct[p_.strip('*_')].resolve()) for p_ in RULESETS}
    cfg = json.loads(result['configs']['OpenROAD.STAPostPNR'].read_text())
    assert cfg['STA_EXTRA_CORNER_TCL_FILE'] == 'dir::' + signoff.EXTRA_TCL
    provenance = json.loads((p / 'phase3/librelane/22-config/design.provenance.json').read_text())
    assert 'TIME_DERATING_CONSTRAINT' in provenance['STA_EXTRA_CORNER_TCL_FILE']


def test_a_corner_with_no_direct_spef_refuses_before_any_step(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    calls = []
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path, calls=calls))
    direct = {c: write(p / f'x/spm.{c}.spef', c) for c in ('nom', 'min')}
    with pytest.raises(contract.Refusal, match='LL_DIRECT_SPEF_MISSING: max_'):
        signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                    sdc=pnr / 'constraint.sdc', extract=False, time=True, direct_spefs=direct)
    assert not [c for c in calls if '--id' in c]


def test_a_pdk_without_rcx_rules_is_refused_not_extracted(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path, rulesets={}))
    with pytest.raises(contract.Refusal, match='LL_RCX_RULESETS_UNDECLARED'):
        signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                    sdc=pnr / 'constraint.sdc', extract=True, time=False)


def test_rcx_consumes_the_supplied_final_odb_without_deriving_a_replacement(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    final_odb = write(pnr / 'spm.filled.odb', 'final filled odb bytes')
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path))
    result = signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def',
                         routed_odb=final_odb, netlist=pnr / 'spm_pnr.v',
                         sdc=pnr / 'constraint.sdc', extract=True, time=False)
    state = json.loads((result['rcx'] / 'state_in.json').read_text())
    receipt = json.loads((p / 'phase3/librelane/22-config/bridge/bridge_receipt.json').read_text())
    assert state['odb'] == str(final_odb.resolve())
    assert receipt['views']['odb']['source'] == str(final_odb.resolve())
    assert 'odb' not in receipt['derived']


def test_missing_supplied_final_odb_refuses_before_native_step(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    calls = []
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path, calls=calls))
    missing = pnr / 'missing-final.odb'
    with pytest.raises(contract.Refusal, match='LL_ROUTE_VIEW_MISSING'):
        signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def',
                    routed_odb=missing, netlist=pnr / 'spm_pnr.v',
                    sdc=pnr / 'constraint.sdc', extract=True, time=False)
    assert not [call for call in calls if '--id' in call]


def test_rcx_spefs_reach_the_direct_consumers_bound_by_sha(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path))
    result = signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                         sdc=pnr / 'constraint.sdc', extract=True, time=False)
    extracted = p / 'phase3/stage3/extracted'
    write(extracted / 'spef_corners/spm.max.spef', 'an older direct corner')
    receipt = p / 'reports/phase3/librelane_rcx_handoff.json'
    signoff.publish_spefs(result, 'spm', extracted / 'spm.spef', extracted / 'spef_corners', receipt,
                          physical_top='chip_top')
    assert (extracted / 'spm.spef').read_text() == RCX_FIXTURE_SPEFS['nom_*']
    assert (extracted / 'spef_corners/spm.max.spef').read_text() == RCX_FIXTURE_SPEFS['max_*']
    runner = importlib.import_module('phase3_one_shot_runner')
    handed = runner._librelane_handed_spefs(receipt)
    assert sorted(handed) == ['max', 'min', 'nom']
    # a file the receipt no longer binds (edited after the handoff) is not read
    write(extracted / 'spef_corners/spm.min.spef', 'edited')
    assert sorted(runner._librelane_handed_spefs(receipt)) == ['max', 'nom']


def test_a_missing_nominal_corner_names_the_state_it_searched(tmp_path, monkeypatch):
    """An absence refusal says where it looked: the RCX state_out.json whose
    SPEF map lacks the nominal corner, and the corners that map does hold."""
    p, pnr, root = _project(tmp_path)
    no_nom = {k: v for k, v in RULESETS.items() if not k.startswith('nom')}
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path, rulesets=no_nom))
    result = signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                         sdc=pnr / 'constraint.sdc', extract=True, time=False)
    extracted = p / 'phase3/stage3/extracted'
    with pytest.raises(contract.Refusal) as caught:
        signoff.publish_spefs(result, 'spm', extracted / 'spm.spef', extracted / 'spef_corners',
                              p / 'reports/phase3/librelane_rcx_handoff.json',
                              physical_top='chip_top')
    assert caught.value.code == 'LL_RCX_NOMINAL_MISSING'
    assert str(result['rcx'] / 'state_out.json') in str(caught.value)
    assert "['max_*', 'min_*']" in str(caught.value)
    assert not (extracted / 'spm.spef').exists()


def test_rcx_publication_rejects_foreign_physical_subject(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path))
    result = signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def',
                         netlist=pnr / 'spm_pnr.v', sdc=pnr / 'constraint.sdc',
                         extract=True, time=False)
    extracted = p / 'phase3/stage3/extracted'
    with pytest.raises(contract.Refusal, match='physical subject'):
        signoff.publish_spefs(result, 'spm', extracted / 'spm.spef',
                              extracted / 'spef_corners',
                              p / 'reports/phase3/librelane_rcx_handoff.json',
                              physical_top='foreign_top')
    assert not (extracted / 'spm.spef').exists()


def test_rcx_caller_resolves_existing_pad_top_mapping(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    p, pnr, _root = _project(tmp_path)
    put(p / 'reports/phase3/io_pad_chip_top.json', {
        'verdict': 'WROTE', 'core_module': 'spm', 'chip_top_module': 'chip_top'})
    assert runner._librelane_rcx_physical_top(p, 'spm', pnr / 'spm.def') == 'chip_top'


def test_a_corner_absent_from_the_direct_map_names_the_corners_offered(tmp_path, monkeypatch):
    p, pnr, root = _project(tmp_path)
    monkeypatch.setattr(contract.subprocess, 'run', _tool_edge(tmp_path))
    direct = {c: write(p / f'x/spm.{c}.spef', c) for c in ('nom', 'min')}
    with pytest.raises(contract.Refusal) as caught:
        signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                    sdc=pnr / 'constraint.sdc', extract=False, time=True, direct_spefs=direct)
    assert str(caught.value) == ("LL_DIRECT_SPEF_MISSING: max_*: no 'max' entry among the "
                                 "direct corner SPEFs ['min', 'nom']")
    # a corner the map names but whose file is gone names that file
    direct['max'] = p / 'x/spm.max.spef'
    with pytest.raises(contract.Refusal) as caught:
        signoff.run(p, 'img', root, 'gf', routed_def=pnr / 'spm.def', netlist=pnr / 'spm_pnr.v',
                    sdc=pnr / 'constraint.sdc', extract=False, time=True, direct_spefs=direct)
    assert str(caught.value) == f"LL_DIRECT_SPEF_MISSING: max_*: no file at {direct['max']}"


# ----------------------------------------------------------- SPEF census ---

SPEF = '''*SPEF "IEEE 1481-1998"
*DESIGN "chip_top"
*T_UNIT 1 NS
*C_UNIT 1 FF
*R_UNIT 1 OHM
*NAME_MAP
*1 net_a
*2 net_b
*D_NET *1 3.0
*CONN
*I u1:Z O
*CAP
1 *1:1 1.0
2 *1:2 *2:1 2.0
*RES
1 *1:1 *1:2 5.0
*END
*D_NET *2 2.5
*CAP
1 *2:1 0.5
2 *2:1 *1:2 2.0
*END
'''


RCX_FIXTURE_SPEFS = {
    'nom_*': '// SOURCE_FIXTURE nominal; no native extraction claim\n' + SPEF,
    'min_*': '// SOURCE_FIXTURE minimum; no native extraction claim\n' + SPEF,
    'max_*': '// SOURCE_FIXTURE maximum; no native extraction claim\n' + SPEF,
}


def test_spef_census_splits_grounded_and_coupling_in_pf(tmp_path):
    census = signoff.spef_census(write(tmp_path / 'a.spef', SPEF))
    assert census['nets'] == {'net_a': pytest.approx(0.003), 'net_b': pytest.approx(0.0025)}
    assert census['ground_pf'] == pytest.approx(0.0015)
    assert census['coupling_pf'] == pytest.approx(0.004) and census['coupling_rows'] == 2
    assert census['total_pf'] == pytest.approx(0.0055)


def test_extraction_comparison_reports_per_net_deltas(tmp_path):
    a = write(tmp_path / 'a.spef', SPEF)
    b = write(tmp_path / 'b.spef', SPEF.replace('*D_NET *1 3.0', '*D_NET *1 1.5'))
    rows = signoff.compare_extraction({'nom': a, 'max': a}, {'nom': b}, ['net_a', 'net_b'])
    assert rows['max']['status'] == 'NOT_MEASURED'
    assert rows['nom']['sampled'][0]['delta_pct'] == -50.0
    assert rows['nom']['sampled'][1]['delta_pct'] == 0.0


# -------------------------------------------------- per-corner judgment ---

STA_LOG = ("Reading timing models for corner {c}…\n"
           "Reading cell library for the '{c}' corner at '/pdk/x/libs.ref/sc/lib/sc__{p}.lib'…\n"
           "Reading cell library for the '{c}' corner at '/pdk/x/libs.ref/io/lib/io__{p}.lib'…\n"
           "Reading top-level netlist at '/w/spm_pnr.v'…\n")


def _sta_folder(tmp_path, *, setup=1.0, hold=0.4, ideal=(), derate=True, drop=None,
                violations=None, spefs=None):
    folder = tmp_path / 'sta'
    metrics = {}
    for c in CORNERS:
        process = c.split('_', 1)[1]
        write(folder / c / 'sta.log', STA_LOG.format(c=c, p=process))
        write(folder / c / 'unpropagated.rpt', '\n'.join(ideal))
        if derate:
            write(folder / c / signoff.CORNER_REPORT,
                  'OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV source=TIME_DERATING_CONSTRAINT=5\n')
        for key, metric in signoff.TIMING_METRICS.items():
            value = (setup if key == 'setup_ws' else hold if key == 'hold_ws'
                     else (violations or {}).get(key, 0))
            metrics[f'{metric}__corner:{c}'] = value
    if drop:
        metrics.pop(drop)
    put(folder / 'state_out.json', {'metrics': metrics, 'nl': '/w/spm_pnr.v', 'sdc': '/w/c.sdc',
                                    'spef': spefs or {p: f'/w/{p.strip("*_")}.spef' for p in RULESETS}})
    put(folder / 'config.json', {'meta': {'step': 'OpenROAD.STAPostPNR'}, 'DESIGN_NAME': 'chip_top',
                                 'SIGNOFF_SDC_FILE': '/w/c.sdc', 'TIME_DERATING_CONSTRAINT': 5,
                                 'STA_EXTRA_CORNER_TCL_FILE': '/w/extra.tcl'})
    return folder


def test_every_corner_measured_derated_and_propagated_passes(tmp_path):
    judged = signoff.judge_timing(signoff.corner_timing(_sta_folder(tmp_path)))
    assert judged['verdict'] == 'PASS'
    assert judged['worst_setup']['ws'] == 1.0


def test_an_ideal_clock_on_a_post_route_corner_fails(tmp_path):
    judged = signoff.judge_timing(signoff.corner_timing(_sta_folder(tmp_path, ideal=('clk',))))
    assert judged['verdict'] == 'FAIL' and judged['reason'] == 'LL_POSTROUTE_IDEAL_CLOCK'


def test_an_absent_metric_or_derate_record_is_not_measured_never_zero(tmp_path):
    missing = f'timing__hold__ws__corner:{CORNERS[1]}'
    assert signoff.judge_timing(signoff.corner_timing(
        _sta_folder(tmp_path / 'a', drop=missing)))['verdict'] == 'NOT_MEASURED'
    assert signoff.judge_timing(signoff.corner_timing(
        _sta_folder(tmp_path / 'b', derate=False)))['verdict'] == 'NOT_MEASURED'


def test_a_negative_corner_fails(tmp_path):
    judged = signoff.judge_timing(signoff.corner_timing(_sta_folder(tmp_path, hold=-0.2)))
    assert judged['verdict'] == 'FAIL' and judged['failing_corners'] == sorted(CORNERS)


@pytest.mark.parametrize('metric', (
    'setup_vio', 'hold_vio', 'max_slew_vio', 'max_cap_vio', 'max_fanout_vio'))
def test_each_measured_violation_count_fails(metric, tmp_path):
    judged = signoff.judge_timing(signoff.corner_timing(
        _sta_folder(tmp_path, violations={metric: 1})))
    assert judged['verdict'] == 'FAIL'
    assert judged['failing_corners'] == sorted(CORNERS)


# --------------------------------------------------- the agreement arms ---

def _arm_edge(values, calls):
    def fake(cmd, **_):
        calls.append(cmd)
        corner = next(x.split('=', 1)[1] for x in cmd if str(x).startswith('VIBEIC_ARM_CORNER='))
        row = values(corner)
        return SimpleNamespace(returncode=0, stderr='', stdout=''.join(
            f'VIBEIC_ARM {k} {v}\n' for k, v in row.items()))
    return fake


def _same(corner):
    return {'setup_ws': 1.0, 'setup_tns': 0, 'setup_vio': 0, 'hold_ws': 0.4, 'hold_tns': 0,
            'hold_vio': 0, 'max_slew_vio': 0, 'max_cap_vio': 0}


def test_standalone_opensta_agreeing_on_every_corner_is_agree(tmp_path, monkeypatch):
    folder = _sta_folder(tmp_path)
    calls = []
    monkeypatch.setattr(signoff.subprocess, 'run', _arm_edge(_same, calls))
    doc = signoff.agreement(tmp_path, 'img', folder, [], tmp_path / 'agree.json')
    assert doc['verdict'] == 'AGREE' and len(calls) == len(CORNERS)
    first = next(c for c in calls if f'VIBEIC_ARM_CORNER={CORNERS[0]}' in c)
    assert first[first.index('--entrypoint') + 1] == 'sta'
    assert '--memory' in first   # every docker run carries the ceiling
    # the same inputs the tool read: its corner libraries, SPEF, SDC and extra Tcl
    assert 'VIBEIC_ARM_LIBS=/pdk/x/libs.ref/sc/lib/sc__tt_025C_5v00.lib /pdk/x/libs.ref/io/lib/io__tt_025C_5v00.lib' in first
    assert 'VIBEIC_ARM_EXTRA=/w/extra.tcl' in first and 'TIME_DERATING_CONSTRAINT=5' in first


def test_a_corner_the_engines_disagree_on_is_a_refusal_not_a_pick(tmp_path, monkeypatch):
    folder = _sta_folder(tmp_path)
    monkeypatch.setattr(signoff.subprocess, 'run', _arm_edge(
        lambda c: {**_same(c), 'hold_ws': 0.3} if c == CORNERS[2] else _same(c), []))
    doc = signoff.agreement(tmp_path, 'img', folder, [], tmp_path / 'agree.json')
    assert doc['verdict'] == 'DISAGREE' and doc['disagreeing_corners'] == [CORNERS[2]]


OCV = '''=== SETUP corner: process=SS liberty=/foss/pdks/x/libs.ref/sc/lib/sc__ss_125C_4v50.lib, SPEF=spm.max.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /foss/pdks/x/libs.ref/sc/lib/sc__ss_125C_4v50.lib
STA_BASIS_SPEF: spm.max.spef
STA_BASIS_CORNER: max
worst slack max {setup}
=== HOLD corner: process=FF liberty=/foss/pdks/x/libs.ref/sc/lib/sc__ff_n40C_5v50.lib, SPEF=spm.min.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS_LIBERTY: /foss/pdks/x/libs.ref/sc/lib/sc__ff_n40C_5v50.lib
STA_BASIS_SPEF: spm.min.spef
STA_BASIS_CORNER: min
worst slack min {hold}
'''


def _deck_fixture(tmp_path, *, tool_min_bytes='min'):
    spef_dir = tmp_path / 'spef_corners'
    tool = {'nom_*': write(tmp_path / 'tool/nom.spef', 'nom'),
            'max_*': write(tmp_path / 'tool/max.spef', 'max'),
            'min_*': write(tmp_path / 'tool/min.spef', tool_min_bytes)}
    for c in ('nom', 'max', 'min'):
        write(spef_dir / f'spm.{c}.spef', c)
    folder = _sta_folder(tmp_path, spefs={k: str(v) for k, v in tool.items()})
    return folder, spef_dir


def test_our_deck_and_the_tool_agree_on_the_corners_they_share(tmp_path):
    folder, spef_dir = _deck_fixture(tmp_path)
    doc = signoff.deck_agreement(OCV.format(setup='1.00', hold='0.40'), folder,
                                 tmp_path / 'deck.json', spef_dir=spef_dir)
    assert doc['verdict'] == 'AGREE'
    assert [r['tool_corner'] for r in doc['stanzas']] == ['max_ss_125C_4v50', 'min_ff_n40C_5v50']


def test_our_deck_disagreeing_on_a_shared_corner_is_disagree(tmp_path):
    folder, spef_dir = _deck_fixture(tmp_path)
    doc = signoff.deck_agreement(OCV.format(setup='0.36', hold='0.40'), folder,
                                 tmp_path / 'deck.json', spef_dir=spef_dir)
    assert doc['verdict'] == 'DISAGREE'


def test_a_deck_timed_on_other_spef_bytes_is_not_comparable(tmp_path):
    folder, spef_dir = _deck_fixture(tmp_path, tool_min_bytes='re-extracted')
    doc = signoff.deck_agreement(OCV.format(setup='1.00', hold='9.99'), folder,
                                 tmp_path / 'deck.json', spef_dir=spef_dir)
    rows = {r['stanza']: r['verdict'] for r in doc['stanzas']}
    assert rows == {'SETUP': 'AGREE', 'HOLD': 'NOT_COMPARABLE'} and doc['verdict'] == 'AGREE'


# --------------------------------------------------- the runner's record ---

def _record(tmp_path, monkeypatch, m22, m23, *, engines='AGREE', hold=0.4):
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'proj'
    folder = _sta_folder(tmp_path, hold=hold)
    monkeypatch.setattr(runner, '_librelane_signoff_run', lambda *a, **k: {
        'sta': folder, 'image': 'img', 'mounts': [], 'rcx': folder,
        'spef': {p: Path(f'/w/{p}') for p in RULESETS}})
    monkeypatch.setattr(signoff, 'agreement', lambda *a, **k: {
        'verdict': engines, 'disagreeing_corners': [] if engines == 'AGREE' else [CORNERS[0]]})
    notes, failures, written = [], [], []
    runner._librelane_signoff_record(project, 'spm', SimpleNamespace(name='gf'), m22, m23,
                                     project / 'phase3/stage3/extracted/spef_corners',
                                     project / 'absent.rpt', notes, failures, written)
    return notes, failures, written, project


def test_librelane_step_23_fails_the_step_on_the_tools_verdict(tmp_path, monkeypatch):
    notes, failures, written, project = _record(tmp_path, monkeypatch, 'direct', 'librelane', hold=-0.1)
    assert any('step 23 LibreLane STAPostPNR: FAIL' in f for f in failures)
    record = json.loads((project / 'reports/phase3/sta_postpnr_signoff.json').read_text())
    assert record['spef_producer'] == 'direct:_emit_spef_corners' and len(record['corners']) == 3


def test_dual_step_23_records_a_tool_fail_without_failing(tmp_path, monkeypatch):
    notes, failures, _, _ = _record(tmp_path, monkeypatch, 'direct', 'dual', hold=-0.1)
    assert not failures and any('STAPostPNR: FAIL' in n for n in notes)


@pytest.mark.parametrize('hold,expected', [(0.4, 'PASS'), (-0.1, 'FAIL')])
def test_default_sta_keeps_native_quality_without_other_engine_qualification(
        tmp_path, monkeypatch, hold, expected):
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'proj'
    folder = _sta_folder(tmp_path, hold=hold)
    monkeypatch.setattr(runner, '_librelane_signoff_run', lambda *args, **kwargs: {
        'sta': folder, 'image': 'img', 'mounts': []})
    monkeypatch.setattr(signoff, 'agreement', lambda *args, **kwargs:
                        pytest.fail('Default launched another timing engine'))
    monkeypatch.setattr(signoff, 'deck_agreement', lambda *args, **kwargs:
                        pytest.fail('Default qualified another timing deck'))
    notes, failures, written = [], [], []
    runner._librelane_signoff_record(
        project, 'unit', SimpleNamespace(name='unit'), 'direct', 'librelane',
        project / 'phase3/stage3/extracted/spef_corners',
        project / 'absent.rpt', notes, failures, written, qualify=False)
    record = json.loads((project / 'reports/phase3/sta_postpnr_signoff.json').read_text())
    assert record['judgment']['verdict'] == expected
    assert bool(failures) == (expected == 'FAIL')
    assert record['engine_agreement']['verdict'] == 'NOT_APPLICABLE'
    assert record['deck_agreement']['verdict'] == 'NOT_APPLICABLE'


def test_an_engine_disagreement_refuses_in_either_mode(tmp_path, monkeypatch):
    for mode in ('dual', 'librelane'):
        _, failures, _, _ = _record(tmp_path / mode, monkeypatch, 'direct', mode, engines='DISAGREE')
        assert any(f.startswith('LL_STA_ARMS_DISAGREE') for f in failures)


def test_no_declared_pdk_root_refuses_by_name(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    with pytest.raises(contract.Refusal, match='LL_PDK_ROOT_NOT_DECLARED'):
        runner._librelane_signoff_run(tmp_path, 'spm', SimpleNamespace(name='gf'),
                                      extract=True, time=False)


def test_modes_default_to_direct_and_follow_the_switch(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    assert runner._librelane_signoff_modes(tmp_path) == ('direct', 'direct')
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'22': 'librelane', '23': 'dual'}})
    assert runner._librelane_signoff_modes(tmp_path) == ('librelane', 'dual')


# ------------------------------------ the FasterCap arm's routed geometry ---

def test_def_wires_are_found_on_the_tech_lefs_own_layer_names():
    """gf180's tech LEF names its routing layers `Metal1`..`Metal5`.  The DEF
    reader matched `MET\\d|metal\\d|M\\d` only, so the routed spm DEF read as
    unrouted (0 of 6,490 segments) and the FasterCap accuracy arm and the
    analytical augment had nothing to work on."""
    sc = importlib.import_module('_spef_coupling')
    lef = ('LAYER Metal1\n  TYPE ROUTING ;\n  DIRECTION HORIZONTAL ;\n  WIDTH 0.23 ;\n'
           '  THICKNESS 0.54 ;\nEND Metal1\nLAYER Via1\n  TYPE CUT ;\nEND Via1\n'
           'LAYER Metal2\n  TYPE ROUTING ;\n  DIRECTION VERTICAL ;\n  WIDTH 0.28 ;\n'
           '  THICKNESS 0.54 ;\nEND Metal2\n')
    layers = sc.parse_lef_layers(lef)
    body = ('DESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\nNETS 1 ;\n'
            '    - a ( i1 A ) ( i2 Y ) + USE SIGNAL\n'
            '      + ROUTED Metal2 ( 5000 1000 ) ( * 9000 )\n'
            '      NEW Metal1 ( 0 1000 ) ( 5000 * )\n'
            '      NEW Metal1 ( 5000 1000 ) Via1_HV ;\nEND NETS\n')
    segs = sc.parse_def_wires(body, layers, 1000)
    assert sorted((s.layer, s.horizontal) for s in segs) == [('Metal1', True), ('Metal2', False)]


def test_step_23_times_the_handed_tool_spefs_not_a_second_extraction(tmp_path, monkeypatch):
    """A second RCX run re-derives the bridge ODB and writes a SPEF that differs
    from the handed one (measured: only its *DATE line), so our deck and the
    tool would read different parasitics.  Step 23 times the receipt-bound files."""
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'proj'
    corner_dir = project / 'phase3/stage3/extracted/spef_corners'
    handed = {c: write(corner_dir / f'spm.{c}.spef', f'rcx {c}') for c in ('nom', 'min', 'max')}
    put(project / 'reports/phase3/librelane_rcx_handoff.json', {'views': {
        f'spef:{c}_*': {'dest': str(p), 'dest_sha256': contract.digest(p)} for c, p in handed.items()}})
    seen = {}
    folder = _sta_folder(tmp_path)

    def fake_run(*a, **k):
        seen.update(k)
        return {'sta': folder, 'image': 'img', 'mounts': [], 'spef': {}}
    monkeypatch.setattr(runner, '_librelane_signoff_run', fake_run)
    monkeypatch.setattr(signoff, 'agreement', lambda *a, **k: {'verdict': 'AGREE'})
    notes, failures, written = [], [], []
    runner._librelane_signoff_record(project, 'spm', SimpleNamespace(name='gf'), 'librelane',
                                     'librelane', corner_dir, project / 'absent.rpt',
                                     notes, failures, written)
    assert seen['extract'] is False and seen['time'] is True
    assert seen['direct_spefs'] == handed
    assert not failures, failures


# ------------------------------------------------ step 27 on the tool state ---

si = importlib.import_module('si_signoff_timing_aware')

SI_SPEF = '''*SPEF "IEEE 1481-1998"
*C_UNIT 1 FF
*NAME_MAP
*1 a
*2 b
*3 c
*D_NET *1 3.0
*CONN
*I u1:Z O
*CAP
1 *1:1 1.0
2 *1:1 *2:1 1.0
3 *1:1 *3:1 1.0
*END
*D_NET *2 2.0
*CONN
*I u2:Z O
*CAP
1 *2:1 1.0
*END
*D_NET *3 2.0
*CONN
*I u3:Z O
*CAP
1 *3:1 1.0
*END
'''


def _timing(windows):
    return {'pins': {pin: {'arr_rise_min': lo, 'arr_rise_max': hi,
                                                      'arr_fall_min': lo, 'arr_fall_max': hi,
                                                      'slew_rise_max': 0.0, 'slew_fall_max': 0.0}
                     for pin, (lo, hi) in windows.items()}}


def test_windows_are_timed_on_the_propagated_clock_when_asked():
    tcl = si.build_opensta_si_tcl('l', 'n', 't', 's', 'sp', 'o', propagated_clock=True)
    head = tcl.split('proc _si_capture')[0]
    assert head.index('read_spef sp') < head.index('set_propagated_clock [all_clocks]')
    assert 'set_propagated_clock' not in si.build_opensta_si_tcl('l', 'n', 't', 's', 'sp', 'o')


def test_the_kernel_agreeing_with_the_window_arithmetic_is_agree():
    rows, unknown = si.kernel_overlap_rows(SI_SPEF, _timing({'u1:Z': (1.0, 2.0), 'u2:Z': (1.5, 3.0),
                                                              'u3:Z': (5.0, 6.0)}))
    assert unknown == 0 and len(rows) == 4
    tcl = si.kernel_overlap_tcl(rows)
    assert tcl.count('timing_window_overlap -victim_window') == 4
    fractions = {i: (0.5 if r['python_overlap'] else 0.0) for i, r in enumerate(rows)}
    out = ''.join(f'VIBEIC_KOV {i} {f}\n' for i, f in fractions.items())
    assert si.compare_kernel_overlap(rows, out)['verdict'] == 'AGREE'


def test_the_kernel_contradicting_the_arithmetic_is_disagree_and_touching_is_named():
    rows, _ = si.kernel_overlap_rows(SI_SPEF, _timing({'u1:Z': (1.0, 2.0), 'u2:Z': (2.0, 3.0),
                                                       'u3:Z': (5.0, 6.0)}))
    # a/b only touch at t=2.0: the closed-interval test says overlap, the kernel 0
    touching = ''.join(f'VIBEIC_KOV {i} 0.0\n' for i in range(len(rows)))
    doc = si.compare_kernel_overlap(rows, touching)
    assert doc['verdict'] == 'AGREE' and doc['touching_only'] == 2
    # the kernel claiming an overlap for disjoint windows (a/c) is a disagreement
    wrong = ''.join(f'VIBEIC_KOV {i} {0.3 if {rows[i]["victim"], rows[i]["aggressor"]} == {"*1", "*3"} else 0.0}\n'
                    for i in range(len(rows)))
    doc = si.compare_kernel_overlap(rows, wrong)
    assert doc['verdict'] == 'DISAGREE' and doc['disagreement_count'] == 2
    assert si.compare_kernel_overlap(rows, '')['verdict'] == 'NOT_MEASURED'


def test_a_kernel_disagreement_withdraws_the_delta_delay_reading(tmp_path, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    spef = write(tmp_path / 'c.spef', SI_SPEF)
    timing = put(tmp_path / 't.json', _timing({'u1:Z': (1.0, 2.0), 'u2:Z': (1.5, 3.0), 'u3:Z': (5.0, 6.0)}))
    # the kernel says "no overlap" for every pair, contradicting a/b
    monkeypatch.setattr(signoff, 'run_sta_script', lambda *a, **k: SimpleNamespace(
        returncode=0, stderr='', stdout=''.join(f'VIBEIC_KOV {i} 0.0\n' for i in range(4))))
    sbody = {'delta_delay': {'verdict': 'PASS', 'pairs_slack_checked': 3}, 'delta_delay_verdict': 'PASS'}
    notes = []
    runner._librelane_si_kernel_check(tmp_path, 'spm', {'image': 'img', 'mounts': []}, spef, timing,
                                      sbody, notes)
    assert sbody['kernel_cross_check']['verdict'] == 'DISAGREE'
    assert sbody['delta_delay']['verdict'] == 'NOT_MEASURED' and sbody['delta_delay_verdict'] == 'NOT_MEASURED'
    basis = importlib.import_module('si_mcf_verdict_basis').reconcile({'verdict': 'FAIL'}, sbody)
    assert basis['verdict'] == 'FAIL' and basis['verdict_basis']['verdict_from'] == 'mcf_envelope'


def _step23_tool_record(tmp_path):
    project = tmp_path / 'p'
    folder = project / 'phase3/librelane/23/01-openroad-stapostpnr'
    corner = 'max_ss_125C_4v50'
    spef = write(project / 'x/max.spef', 's')
    nl = write(project / 'x/spm_pnr.v', 'n')
    sdc = write(project / 'x/c.sdc', 'c')
    put(folder / 'state_out.json', {'nl': str(nl), 'sdc': str(sdc), 'spef': {'max_*': str(spef)}})
    put(folder / 'config.json', {'meta': {'step': 'OpenROAD.STAPostPNR'}, 'DESIGN_NAME': 'chip_top'})
    write(folder / corner / 'sta.log', STA_LOG.format(c=corner, p='ss_125C_4v50').replace('/pdk/x/', '/pdk/gfx/'))
    put(project / 'reports/phase3/sta_postpnr_signoff.json', {
        'sta_state': str(folder / 'state_out.json'),
        'judgment': {'worst_setup': {'corner': corner, 'ws': 1.0}}})
    put(project / 'phase3/librelane_switch.json', {'steps': {'23': 'librelane'},
                                                   'pdk_root_host': str(tmp_path / 'root')})
    return project, corner, spef, nl


def test_step_27_reads_the_step_23_tool_corner(tmp_path):
    runner = importlib.import_module('phase3_one_shot_runner')
    assert runner._librelane_si_corner_inputs(tmp_path / 'p') is None      # 23 direct
    project, corner, spef, nl = _step23_tool_record(tmp_path)
    tool = runner._librelane_si_corner_inputs(project)
    # the image is the one resolve_image resolved, stated by the fixture
    assert tool['image'] == stated_image()
    assert tool['design'] == 'chip_top' and tool['corner'] == corner
    assert tool['spef'] == spef.resolve() and tool['netlist'] == nl.resolve()
    assert tool['liberties'][0].endswith('sc__ss_125C_4v50.lib')
    assert tool['mounts'] == [(tmp_path / 'root' / 'gfx', '/pdk/gfx')]


def test_step_27_with_no_resolvable_image_keeps_the_direct_inputs(tmp_path, monkeypatch):
    """An unresolvable image is one more reason step 27 has no tool corner
    (None, the function's stated answer), never an uncaught refusal."""
    runner = importlib.import_module('phase3_one_shot_runner')
    project, _corner, _spef, _nl = _step23_tool_record(tmp_path)

    def unresolvable(env=None, *, allow_pull=False):
        raise _eda_pin.ImageNotResolvable(['this host: none'])
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', unresolvable)
    assert runner._librelane_si_corner_inputs(project) is None


def test_the_direct_si_windows_are_re_derived_after_a_re_extraction(tmp_path, monkeypatch):
    """The timing JSON was produced only when absent: a re-extracted SPEF was
    then scored against the previous extraction's windows."""
    import os
    runner = importlib.import_module('phase3_one_shot_runner')
    project = tmp_path / 'p'
    extracted = project / 'phase3/stage3/extracted'
    old = put(extracted / 'spm_si_timing.json', {'pins': {}})
    os.utime(old, (1_000_000, 1_000_000))
    spef = write(extracted / 'spm.spef', SI_SPEF)
    write(project / 'phase3/stage3/pnr/sta.rpt', 'x')
    calls = []
    monkeypatch.setattr(runner, '_emit_si_timing_json',
                        lambda *a, **k: calls.append(a) or False)
    runner._merge_si_timing_aware(project, 'spm', SimpleNamespace(), 'c', spef, {}, [])
    assert len(calls) == 1


def test_a_deck_with_a_different_derate_is_not_comparable(tmp_path):
    """The direct deck's derate is its own constant; the tool's is the PDK's
    declared percent.  Where they differ the slacks answer different questions,
    so a gap is NOT_COMPARABLE, never a disagreement."""
    folder, spef_dir = _deck_fixture(tmp_path)
    text = OCV.format(setup='0.36', hold='0.40').replace(
        'OCV_DERATE_APPLIED early=0.95 late=1.05', 'OCV_DERATE_APPLIED early=0.92 late=1.08', 1)
    doc = signoff.deck_agreement(text, folder, tmp_path / 'deck.json', spef_dir=spef_dir)
    rows = {r['stanza']: r['verdict'] for r in doc['stanzas']}
    assert rows == {'SETUP': 'NOT_COMPARABLE', 'HOLD': 'AGREE'} and doc['verdict'] == 'AGREE'


def test_standalone_sta_uses_shared_supervisor_and_preserves_log(tmp_path,
                                                                 monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="STA complete", stderr="")

    monkeypatch.setattr(signoff, "run_container", run)
    log = tmp_path / "sta" / "arm.log"
    cp = signoff.run_sta_script(tmp_path, "img", [], tmp_path / "arm.tcl", log)
    assert cp.returncode == 0
    assert log.read_text() == "STA complete\n"
    assert calls[0][1] == {"supervised": True, "log": log}


@pytest.mark.parametrize('schema', ['modern', 'legacy', 'precedence', 'empty', 'null'])
def test_step23_tool_arm_reads_native_lib_schema(tmp_path, schema):
    """The existing receipt-bound nine-corner reader chooses native LIB first."""
    from test_f15_step23_gates_read_the_tool_arm import tool_project, rebind, STA
    project = tool_project(tmp_path)
    folder = project / STA
    config_path = folder / 'config.json'
    config = json.loads(config_path.read_text())
    original = config['CELL_LIBS']
    if schema != 'legacy':
        config['LIB'] = {} if schema == 'empty' else None if schema == 'null' else original
        if schema == 'modern':
            config.pop('CELL_LIBS')
        elif schema == 'precedence':
            config['CELL_LIBS'] = {'*': ['/pdk/unused/legacy.lib']}
    config_path.write_text(json.dumps(config))
    # Unit native-output constructor: establish the recipe's initial config bytes
    # before invoking the unchanged receipt/current consumer, never field evidence.
    rebind(project)
    arm = signoff.step23_tool_arm(project)
    assert len(arm['corners']) == 9
    if schema in ('empty', 'null'):
        assert all(row['liberty'] is None and 'process' in row['scope_gaps']
                   for row in arm['corners'].values())
    else:
        for name, row in arm['corners'].items():
            assert row['process'] == name.split('_')[1]
            assert row['liberty'] in [p for group in original.values() for p in group]
            assert not row['scope_gaps'], row['scope_gaps']
            assert all(v['role'] == 'CELL_LIBS' and v['run_sha256'] == v['sha256']
                       for v in row['liberties'])
        if schema == 'modern':
            pdk = tmp_path / 'pdk_root'
            library = next(pdk.rglob('*.lib'))
            library.write_text(library.read_text() + '# changed after native STA\n')
            changed = signoff.step23_tool_arm(project)
            assert any('liberty_digest' in row['scope_gaps'] for row in changed['corners'].values())

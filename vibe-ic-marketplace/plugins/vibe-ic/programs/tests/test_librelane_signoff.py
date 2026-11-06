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
from _hostpaths import require_repo  # noqa: E402
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

def _tcl_run(tmp_path, extra: Path, env: dict, *, precision=0) -> tuple[str, str]:
    """Source the extra corner Tcl in tclsh with OpenSTA's derate command
    recorded, the way LibreLane's corner.tcl sources it."""
    harness = write(tmp_path / 'harness.tcl', (
        'set ::calls {}\n'
        f'set ::tcl_precision {precision}\n'
        'proc set_timing_derate {flag value} { lappend ::calls $flag [format %.17g $value] }\n'
        'set corner_name max_ss_125C_4v50\n'
        f'source {extra}\n'
        f'if {{$::tcl_precision != {precision}}} {{error "writer changed tcl_precision"}}\n'
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
    assert calls.split()[::2] == ['-early', '-late']
    assert tuple(map(float, calls.split()[1::2])) == (0.95, 1.05)
    marker = report.splitlines()[0].split()
    assert marker[0] == signoff.DERATE_MARKER
    assert tuple(float(field.split('=')[1]) for field in marker[1:3]) == (0.95, 1.05)
    assert marker[3:] == ['flat-OCV', 'source=TIME_DERATING_CONSTRAINT=5']
    assert 'STA_BASIS_CORNER: max_ss_125C_4v50' in report


@pytest.mark.skipif(shutil.which('tclsh') is None, reason='needs tclsh')
def test_an_undeclared_percent_applies_no_derate_and_says_so(tmp_path):
    extra = signoff.write_extra_corner_tcl(tmp_path)
    calls, report = _tcl_run(tmp_path, extra, {})
    assert calls == ''
    assert signoff.NO_DERATE_MARKER in report and signoff.DERATE_MARKER not in report


@pytest.mark.skipif(shutil.which('tclsh') is None, reason='needs tclsh')
@pytest.mark.parametrize('precision', (0, 6))
def test_derate_writer_round_trips_factors_independent_of_tcl_precision(tmp_path, precision):
    percent = 1.23456789
    extra = signoff.write_extra_corner_tcl(tmp_path)
    calls, report = _tcl_run(tmp_path, extra, {'TIME_DERATING_CONSTRAINT': str(percent)},
                             precision=precision)
    expected = (1.0 - percent / 100.0, 1.0 + percent / 100.0)
    assert calls.split()[::2] == ['-early', '-late']
    assert tuple(map(float, calls.split()[1::2])) == expected
    folder = _sta_folder(tmp_path)
    config = json.loads((folder / 'config.json').read_text())
    config['TIME_DERATING_CONSTRAINT'] = percent
    put(folder / 'config.json', config)
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, report)
    judged = signoff.judge_timing(signoff.corner_timing(folder))
    assert judged['verdict'] == 'PASS', judged
    marker = report.splitlines()[0].split()
    assert tuple(float(field.split('=')[1]) for field in marker[1:3]) == expected


# ------------------------------------------------ run(): the chain edge ---

IMAGE_INSPECT = ['docker', 'image', 'inspect', 'img', '--format',
                 '{{json .Config.Entrypoint}}']


def _fixture_command(cmd, entrypoint):
    if cmd[:3] == ['docker', 'image', 'inspect']:
        assert cmd == IMAGE_INSPECT, f'unexpected image inspection: {cmd}'
        return None
    assert cmd[:3] == ['docker', 'run', '--name'], f'unexpected tool call: {cmd}'
    argv = [*cmd[:2], *cmd[4:]]
    assert contract._container_image_arg(argv) == 'img', f'unexpected image: {cmd}'
    at = argv.index('img')
    assert '--entrypoint' not in argv[:at]
    command = argv[at + 1:]
    if entrypoint == ['/dockerstartup/scripts/ui_startup.sh']:
        assert command[:1] == ['--skip']
        command = command[1:]
    else:
        assert entrypoint in (None, [])
    return command


def _tool_edge(tmp_path, *, rulesets=RULESETS, calls=None, entrypoint=None):
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
        command = _fixture_command(cmd, entrypoint)
        if command is None:
            return SimpleNamespace(returncode=0, stdout=json.dumps(entrypoint), stderr='')
        if command == ['sh', '-c',
                       'python3 -m librelane.steps run --help >/dev/null && '
                       'yosys -Q -T -y /dev/null -p help >/dev/null'] or command == [
                           'bash', '-c', contract._TCL_PROBE]:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if (command[:2] == ['python3', '-c'] and len(command) == 9
                and 'from librelane.flows.chip import Chip' in command[2]):
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
        if command[:2] == ['openroad', '-exit'] and len(command) == 3:
            tcl = Path(cmd[-1])
            odb = tcl.read_text().split('write_db {')[1].split('}')[0]
            write(Path(odb), 'odb')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if command[:4] == ['python3', '-m', 'librelane.steps', 'run']:
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
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': 'gf'}})
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


@pytest.mark.parametrize('name', ('setup_ss_125c_4v50.rpt', 'hold_ff_n40c_5v50.rpt'))
def test_checked_in_derate_reports_preserve_marker_compatibility(tmp_path, name):
    """Replay real report bytes with fixture metrics; this does not remeasure timing."""
    report = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'tests', 'fixtures', 'ppa', 'sta', 'known_answer', 'views', name).read_text()
    marker = next(line for line in report.splitlines() if line.startswith(signoff.DERATE_MARKER))
    folder = _sta_folder(tmp_path)
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, report)
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] == 'PASS'
    write(folder / CORNERS[0] / signoff.CORNER_REPORT,
          report.replace(marker, marker + ' late=1.0'))
    judged = signoff.judge_timing(signoff.corner_timing(folder))
    assert judged['verdict'] == 'NOT_MEASURED', judged
    assert judged['derate_unrecorded'] == [CORNERS[0]]


@pytest.mark.parametrize('marker', (
    'OCV_DERATE_NOT_DECLARED',
    'OCV_DERATE_APPLIED early=1.0 late=1.0',
    'OCV_DERATE_APPLIED early=0.95 late=1.0',
    'OCV_DERATE_APPLIED early=nan late=1.05',
    'OCV_DERATE_APPLIED early=0.95 late=inf',
    'OCV_DERATE_APPLIED early=0.95',
    'OCV_DERATE_APPLIED_BOGUS early=0.95 late=1.05',
    'OCV_DERATE_APPLIED early=0.95 late=1.05\nOCV_DERATE_NOT_DECLARED',
    'OCV_DERATE_APPLIED early=0.95 late=1.05\nOCV_DERATE_APPLIED early=1.0 late=1.0',
    'OCV_DERATE_APPLIED early=0.95 late=1.05 early=1.0 late=1.0',
    'OCV_DERATE_APPLIED early=0.95 late=1.05 early=0.95',
    'OCV_DERATE_APPLIED early=0.95 late=1.05 late=1.05',
    'OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV early=1.0 late=1.0',
    'OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV source=TIME_DERATING_CONSTRAINT=5 early=1.0 late=1.0',
))
def test_declared_percent_rejects_inconsistent_derate_marker(tmp_path, marker):
    folder = _sta_folder(tmp_path)
    write(folder / CORNERS[0] / signoff.CORNER_REPORT, marker + '\n')
    judged = signoff.judge_timing(signoff.corner_timing(folder))
    assert judged['verdict'] != 'PASS', judged


@pytest.mark.parametrize(('percent', 'marker'), (
    (5.0, 'OCV_DERATE_APPLIED early=0.95 late=1.05'),
    (2.5, 'OCV_DERATE_APPLIED early=0.975 late=1.025'),
    (100, 'OCV_DERATE_APPLIED early=0.0 late=2.0'),
    (0, 'OCV_DERATE_APPLIED early=1.0 late=1.0'),
    ('0', 'OCV_DERATE_APPLIED early=1.0 late=1.0'),
    (None, 'OCV_DERATE_NOT_DECLARED'),
    ('', 'OCV_DERATE_NOT_DECLARED'),
))
def test_derate_marker_preserves_configured_zero_and_undeclared_cases(tmp_path, percent, marker):
    folder = _sta_folder(tmp_path)
    config = json.loads((folder / 'config.json').read_text())
    config['TIME_DERATING_CONSTRAINT'] = percent
    put(folder / 'config.json', config)
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, marker + '\n')
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] == 'PASS'


def test_absent_derate_setting_requires_undeclared_marker(tmp_path):
    folder = _sta_folder(tmp_path)
    config = json.loads((folder / 'config.json').read_text())
    config.pop('TIME_DERATING_CONSTRAINT')
    put(folder / 'config.json', config)
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] != 'PASS'
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, 'OCV_DERATE_NOT_DECLARED\n')
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] == 'PASS'


@pytest.mark.parametrize(('percent', 'marker'), (
    (float('nan'), 'OCV_DERATE_APPLIED early=nan late=nan'),
    (float('inf'), 'OCV_DERATE_APPLIED early=-inf late=inf'),
    (True, 'OCV_DERATE_APPLIED early=0.99 late=1.01'),
))
def test_invalid_derate_setting_cannot_be_hidden_by_a_marker(tmp_path, percent, marker):
    folder = _sta_folder(tmp_path)
    config = json.loads((folder / 'config.json').read_text())
    config['TIME_DERATING_CONSTRAINT'] = percent
    put(folder / 'config.json', config)
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, marker + '\n')
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] != 'PASS'


def test_missing_config_is_not_evidence_of_undeclared_derate(tmp_path):
    folder = _sta_folder(tmp_path)
    (folder / 'config.json').unlink()
    for corner in CORNERS:
        write(folder / corner / signoff.CORNER_REPORT, 'OCV_DERATE_NOT_DECLARED\n')
    assert signoff.judge_timing(signoff.corner_timing(folder))['verdict'] != 'PASS'


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

def _arm_edge(values, calls, *, entrypoint=None):
    def fake(cmd, **_):
        calls.append(cmd)
        command = _fixture_command(cmd, entrypoint)
        if command is None:
            return SimpleNamespace(returncode=0, stdout=json.dumps(entrypoint), stderr='')
        assert command[:4] == ['sta', '-no_init', '-no_splash', '-exit'] and len(command) == 5
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
    assert doc['verdict'] == 'AGREE' and len(calls) == 2 * len(CORNERS)
    assert calls[::2] == [IMAGE_INSPECT] * len(CORNERS)
    first = next(c for c in calls if f'VIBEIC_ARM_CORNER={CORNERS[0]}' in c)
    assert '--entrypoint' not in first[:first.index('img')]
    assert first[first.index('img') + 1:] == [
        'sta', '-no_init', '-no_splash', '-exit',
        str(tmp_path / 'phase3/tool_arms/23/opensta/arm.tcl')]
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


@pytest.mark.parametrize('edge', ('tool', 'arm'))
@pytest.mark.parametrize('command', (
    ['docker', 'image', 'inspect', 'foreign-image', '--format', '{{json .Config.Entrypoint}}'],
    ['docker', 'run', '--name', 'fixture', '--rm', 'foreign-image', 'bash'],
    ['docker', 'image', 'inspect', 'img', '--format', '{{json .Config.Cmd}}'],
    ['docker', 'ps'],
))
def test_signoff_fixture_rejects_foreign_image_and_protocol(tmp_path, edge, command):
    fake = _tool_edge(tmp_path) if edge == 'tool' else _arm_edge(_same, [])
    with pytest.raises(AssertionError, match='unexpected'):
        fake(command)


@pytest.mark.parametrize('edge', ('tool', 'arm'))
@pytest.mark.parametrize('entrypoint', (['/unknown-entrypoint'], ['sta']))
def test_signoff_fixture_unsupported_entrypoint_refuses_before_launch(tmp_path, monkeypatch,
                                                                    edge, entrypoint):
    calls = []
    fake = (_tool_edge(tmp_path, calls=calls, entrypoint=entrypoint) if edge == 'tool'
            else _arm_edge(_same, calls, entrypoint=entrypoint))
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    with pytest.raises(contract.Refusal, match='LL_IMAGE_ENTRYPOINT_UNSUPPORTED'):
        contract.run_container(['docker', 'run', '--rm', '--entrypoint', 'sta', 'img',
                                '-no_init', '-no_splash', '-exit', 'arm.tcl'],
                               probe_deadline_s=3)
    assert calls == [IMAGE_INSPECT]


def test_signoff_foreign_image_inspect_failure_refuses_before_launch(monkeypatch):
    calls = []
    def missing_image(cmd, **_):
        calls.append(cmd)
        assert cmd == ['docker', 'image', 'inspect', 'foreign-image', '--format',
                       '{{json .Config.Entrypoint}}']
        return SimpleNamespace(returncode=1, stdout='', stderr='fixture image absent')
    monkeypatch.setattr(contract.subprocess, 'run', missing_image)
    with pytest.raises(contract.Refusal, match='LL_IMAGE_ENTRYPOINT_UNAVAILABLE'):
        contract.run_container(['docker', 'run', '--rm', '--entrypoint', 'sta',
                                'foreign-image', '-exit', 'arm.tcl'], probe_deadline_s=3)
    assert len(calls) == 1


@pytest.mark.parametrize('edge', ('tool', 'arm'))
def test_signoff_fixture_preserves_legacy_image_entrypoint(tmp_path, monkeypatch, edge):
    entrypoint = ['/dockerstartup/scripts/ui_startup.sh']
    calls = []
    fake = (_tool_edge(tmp_path, calls=calls, entrypoint=entrypoint) if edge == 'tool'
            else _arm_edge(_same, calls, entrypoint=entrypoint))
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    command = (['sh', '-c', 'python3 -m librelane.steps run --help >/dev/null && '
                           'yosys -Q -T -y /dev/null -p help >/dev/null'] if edge == 'tool'
               else ['sta', '-no_init', '-no_splash', '-exit', 'arm.tcl'])
    result = contract.run_container([
        'docker', 'run', '--rm', '-e', f'VIBEIC_ARM_CORNER={CORNERS[0]}',
        '--entrypoint', command[0], 'img', *command[1:]], probe_deadline_s=3)
    assert result.returncode == 0 and len(calls) == 2
    assert calls[0] == IMAGE_INSPECT
    assert calls[1][calls[1].index('img') + 1:] == ['--skip', *command]


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
            assert all(v['role'] == 'CELL_LIBS'
                       for v in row['liberties'])


@pytest.mark.parametrize('changed', [False])
def test_step23_carrier_move_uses_original_content_identity(tmp_path, monkeypatch, changed):
    """Exercise the receipt-bound public reader, including its unresolved verdict gaps."""
    from _hostpaths import require_repo
    from test_f15_step23_gates_read_the_tool_arm import tool_project, rebind, STA
    registry = json.loads(require_repo(
        'vibe-ic-marketplace/plugins/vibe-ic/programs/pdk_registry.json').read_text())
    family = next(row['name'] for row in registry['pdks'] if row['name'] != 'custom_auto_detect')
    project = tool_project(tmp_path)
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (tmp_path / 'pdk_root/p').rename(runtime / family)
    old_prefix = str(tmp_path / 'gone-carrier' / family) + '/'
    for path in project.rglob('*'):
        if path.is_file():
            path.write_text(path.read_text().replace('/pdk/p/', old_prefix))
    config_path = project / STA / 'config.json'
    config = json.loads(config_path.read_text())
    config['PDK'] = family
    config_path.write_text(json.dumps(config))
    provenance = project / 'phase3/librelane_pdk_root.provenance.json'
    provenance.write_text(json.dumps({'path': str(tmp_path / 'gone-carrier'),
                                     'derivation': {'pdk': family}}))
    rebind(project)
    monkeypatch.setenv('PDK_ROOT', str(runtime))
    arm = signoff.step23_tool_arm(project)
    assert len(arm['corners']) == 9
    for row in arm['corners'].values():
        assert not row['scope_gaps'], row['scope_gaps']
        assert all(v['resolved_path'].startswith(str(runtime)) for v in row['liberties'])

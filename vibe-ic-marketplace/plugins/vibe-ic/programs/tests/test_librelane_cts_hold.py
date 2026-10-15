"""T98: steps 19 (CTS) and 20 (post-CTS hold repair) on LibreLane.

The runner, the contract and the gates run for real. Only an EDA tool's file
writes are substituted, at the process edge (`_docker_exec`, the contract's
`subprocess.run` / `run_chain`).
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
sys.path.insert(0, str(PROGRAMS / 'tests'))
contract = importlib.import_module('librelane_contract')
runner = importlib.import_module('phase3_one_shot_runner')
llev = importlib.import_module('_librelane_cts_hold_evidence')
cts = importlib.import_module('librelane_cts_hold')
from _stated_eda_image import state_the_image  # noqa: E402

CORNERS = ['nom_tt_025C_5v00', 'nom_ss_125C_4v50', 'nom_ff_n40C_5v50']


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(contract, '_CAPABILITY', {}, raising=False)
    state_the_image(monkeypatch)   # the identity is stated, never asked of this host
    for name in ('VIBEIC_LIBRELANE_IMAGE', 'VIBEIC_LIBRELANE_PDK_ROOT'):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------ the real deck ---

def _cmds(deck):
    """The deck's command lines (comments name commands too)."""
    return [ln.strip() for ln in deck.splitlines()
            if ln.strip() and not ln.lstrip().startswith('#')]


def _has(deck, command):
    """A command INVOKED by the deck: first word of a line, or of a `catch`."""
    import re
    pat = re.compile(r'^(?:if \{\[catch \{)?' + re.escape(command) + r'(?:\s|\}|$)')
    return any(pat.match(ln) for ln in _cmds(deck))


def _drive_step_pnr(tmp_path, monkeypatch, switch, *, stop_at_builder=True, calls=None,
                    declared=False):
    """The REAL step_pnr with only the process edge substituted (T89's harness).

    With ``stop_at_builder`` it returns the deck-builder kwargs; otherwise the
    real builder runs and every session command is recorded in ``calls``."""
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    if switch is not None:
        put(project / 'phase3/librelane_switch.json', {'steps': switch})
    if declared:
        _l19(project)
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')

    def docker(container, cmd, *a, **k):
        if calls is not None:
            calls.append(('docker', cmd))
        return 1, '', 'no container in this test'

    for name, value in {
            'pnr_input_netlist': lambda *a: (netlist, 'test DUT', False),
            '_v1_6_599_check_wrapper_pin_order_cfg': lambda *a: None,
            '_stage_via_legalized_tech_lef': lambda *a: {'status': 'NOT_NEEDED'},
            'set_invocation_provenance_sink': lambda *a: None,
            '_macro_supply_preroute_decision': lambda *a, **k: None,
            '_resolve_staged_silicon_sdc': lambda *a: None,
            '_liberty_drv_limits': lambda *a: {},
            '_build_auto_silicon_sdc': lambda *a, **k: '',
            '_docker_exec': docker,
            '_docker_exec_raw': lambda *a, **k: (1, '', 'no container in this test')}.items():
        monkeypatch.setattr(runner, name, value)

    class AtBuilder(Exception):
        pass

    seen = {}
    real_builder = runner._build_pnr_tcl_text

    def builder(**kwargs):
        seen.update(kwargs)
        if stop_at_builder:
            raise AtBuilder
        return real_builder(**kwargs)

    monkeypatch.setattr(runner, '_build_pnr_tcl_text', builder)
    if stop_at_builder:
        with pytest.raises(AtBuilder):
            runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
        return seen
    return runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)


@pytest.fixture
def real_deck(tmp_path, monkeypatch):
    """pnr.tcl exactly as the runner's own builder emits it for a design."""
    real_builder = runner._build_pnr_tcl_text
    kwargs = _drive_step_pnr(tmp_path / 'deck', monkeypatch, None)
    return real_builder(**kwargs)


def test_the_cts_hold_region_is_delimited_once_at_the_decks_top_level(real_deck):
    lines = real_deck.splitlines()
    begin = [i for i, ln in enumerate(lines) if ln.strip() == runner._PNR_CTS_HOLD_BEGIN]
    end = [i for i, ln in enumerate(lines) if ln.strip() == runner._PNR_CTS_HOLD_END]
    assert len(begin) == 1 and len(end) == 1 and begin[0] < end[0]
    region = '\n'.join(lines[begin[0]:end[0]])
    assert 'clock_tree_synthesis' in region and 'repair_timing -hold' in region
    assert 'global_route' not in region and 'detailed_route' not in region
    assert cts.tcl_brace_depth(lines[:begin[0]]) == 0
    assert cts.tcl_brace_depth(lines[begin[0]:end[0] + 1]) == 0


def test_head_deck_stops_at_the_region_with_a_complete_checkpoint(real_deck):
    head = cts.head_deck(runner, real_deck, odb_c='/w/pre.odb', def_c='/w/pre.def',
                                          nl_c='/w/pre.v', insts_c='/w/pre.insts')
    assert _has(head, 'global_placement')
    assert not _has(head, 'clock_tree_synthesis') and not _has(head, 'repair_timing -hold')
    assert not _has(head, 'global_route')
    tail_lines = head.rstrip().splitlines()[-12:]
    assert tail_lines[-1] == 'exit 0'
    for view in ('write_db /w/pre.odb', 'write_def /w/pre.def', 'write_verilog /w/pre.v',
                 'open /w/pre.insts w'):
        assert any(view in ln for ln in tail_lines), view


def test_tail_deck_resumes_from_the_handed_over_odb_after_the_region(real_deck):
    tail = cts.tail_deck(runner, real_deck, odb_c='/w/post_hold.odb',
                                          def_c='/w/post_hold.def',
                                          after_restore_tcl='AFTER_RESTORE_MARKER\n')
    assert 'read_db /w/post_hold.odb' in tail and 'read_verilog' not in tail
    assert not any(ln.startswith('read_lef ') for ln in tail.splitlines())
    assert tail.index('read_db /w/post_hold.odb') < tail.index('AFTER_RESTORE_MARKER')
    assert not _has(tail, 'clock_tree_synthesis') and not _has(tail, 'global_placement')
    assert _has(tail, 'global_route') and _has(tail, 'detailed_route')
    assert 'post_cts.def' not in tail and '/post_hold.def\n' not in tail.replace(
        'read_def /w/post_hold.def', '')
    # read_liberty / read_sdc stay: the ODB carries no timing libraries.
    assert 'read_sdc' in tail


def test_the_three_decks_are_valid_tcl(real_deck, tmp_path):
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('no tclsh on this host')
    decks = {
        'head': cts.head_deck(runner, real_deck, odb_c='a', def_c='b', nl_c='c',
                                               insts_c='d'),
        'tail': cts.tail_deck(runner, real_deck, odb_c='a', def_c='b',
                                               after_restore_tcl=''),
        'arm': cts.direct_arm_deck(runner, real_deck, pre_odb_c='a', pre_def_c='b',
                                                    out_dir_c='/x', arm_c='/arm',
                                                    after_restore_tcl='')}
    for name, deck in decks.items():
        script = write(tmp_path / f'{name}.tcl', deck)
        probe = write(tmp_path / f'{name}.probe.tcl',
                      f'set f [open {script}]; set t [read $f]; close $f\n'
                      'puts [info complete $t]\n')
        out = subprocess.run([tclsh, str(probe)], capture_output=True, text=True)
        assert out.stdout.strip() == '1', (name, out.stderr)


def test_direct_arm_runs_only_the_region_and_writes_only_into_its_arm(real_deck):
    out_dir_c = next(ln.split()[1].rsplit('/', 1)[0] for ln in real_deck.splitlines()
                     if ln.startswith('write_def ') and ln.endswith('/post_cts.def'))
    arm = cts.direct_arm_deck(runner, real_deck, pre_odb_c='/w/pre.odb',
                                               pre_def_c='/w/pre.def', out_dir_c=out_dir_c,
                                               arm_c='/arm', after_restore_tcl='')
    assert 'read_db /w/pre.odb' in arm
    assert _has(arm, 'clock_tree_synthesis') and _has(arm, 'repair_timing -hold')
    assert not _has(arm, 'global_placement') and not _has(arm, 'global_route')
    assert 'write_def /arm/post_cts.def' in arm and 'write_def /arm/post_hold.def' in arm
    writes = [ln for ln in _cmds(arm) if f'{out_dir_c}/' in ln and (
        ln.startswith(('write_', 'report_')) or '>' in ln or ' w]' in ln or ' a]' in ln)]
    assert writes == []
    assert arm.rstrip().endswith('exit 0')


# ------------------------------------------------------------- the switch ---

def test_switch_absent_or_for_other_steps_keeps_19_20_direct(tmp_path):
    assert cts.modes(tmp_path) == {'19': 'direct', '20': 'direct'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'15': 'librelane', '9': 'dual'}})
    assert cts.modes(tmp_path) == {'19': 'direct', '20': 'direct'}
    assert cts.refusal({'19': 'direct', '20': 'direct'}) is None
    assert cts.refusal({'19': 'librelane', '20': 'librelane'}) is None
    assert cts.refusal({'19': 'dual', '20': 'dual'}) is None


@pytest.mark.parametrize('switch', [{'19': 'librelane'}, {'20': 'librelane'},
                                    {'19': 'dual', '20': 'librelane'}])
def test_a_split_selection_is_refused_before_any_session(tmp_path, monkeypatch, switch):
    calls = []
    result = _drive_step_pnr(tmp_path, monkeypatch, switch, stop_at_builder=False, calls=calls)
    assert result.status == 'FAIL'
    assert result.detail.startswith('LL_CTS_HOLD_SPLIT_UNSUPPORTED')
    assert not any('pnr.tcl' in cmd for _, cmd in calls)


def test_the_producer_call_site_takes_the_librelane_split_only_when_selected(tmp_path, monkeypatch):
    seen = []

    def split(_runner, **kwargs):
        seen.append(kwargs)
        return 1, 'stopped by test', ''

    monkeypatch.setattr(cts, 'execute', split)
    direct_calls = []
    _drive_step_pnr(tmp_path / 'direct', monkeypatch, None, stop_at_builder=False,
                    calls=direct_calls)
    assert seen == []
    assert any(cmd.rstrip().endswith('openroad.log') and '/pnr.tcl' in cmd
               for _, cmd in direct_calls)
    ll_calls = []
    _drive_step_pnr(tmp_path / 'll', monkeypatch, {'19': 'librelane', '20': 'librelane'},
                    stop_at_builder=False, calls=ll_calls, declared=True)
    assert seen and seen[0]['modes'] == {'19': 'librelane', '20': 'librelane'}
    assert not any('/pnr.tcl ' in cmd for _, cmd in ll_calls)
    overlay = seen[0]['overlay']
    assert overlay['CTS_DISTANCE_BETWEEN_BUFFERS'][0] == \
        runner._CTS_DEFAULT_DISTANCE_BETWEEN_BUFFERS_UM > 0
    assert overlay['PL_RESIZER_HOLD_MAX_BUFFER_PCT'][0] == 5.0


# ------------------------------------------------------ the declared config ---

def _l19(project, max_fanout='4', scope='gf*'):
    root = project / 'phase1/generated_docs'
    put(root / 'L8_TIMING_WAVEFORM.json', {'clock_domains': [
        {'role': 'primary', 'period_ns': 24, 'source_pin': 'clk'}]})
    put(root / 'L9_INTEGRATION_SPEC.json', {'top_module': 'core'})
    rows = [] if max_fanout is None else [
        {'token': 'MAX_FANOUT_CONSTRAINT', 'scope': scope, 'value': max_fanout,
         'source': 'L9_constraints.txt', 'line': 53}]
    put(root / 'L19_CONSTRAINTS_PDK.json', {'fields': {'constraint_declarations': rows}})
    put(project / 'input/submission_template/tapeout_declaration.json',
        {'answers': {'top_cell': 'chip_top'}})


def test_emit_config_caps_cts_clusters_at_the_declared_fanout(tmp_path):
    _l19(tmp_path)
    result = contract.emit_config(tmp_path, 'gfX', tmp_path / 'c.json')
    assert result['CTS_SINK_CLUSTERING_SIZE'] == result['MAX_FANOUT_CONSTRAINT'] == 4
    provenance = json.loads((tmp_path / 'c.provenance.json').read_text())
    assert 'MAX_FANOUT_CONSTRAINT' in provenance['CTS_SINK_CLUSTERING_SIZE']
    _l19(tmp_path, max_fanout=None)
    assert 'CTS_SINK_CLUSTERING_SIZE' not in contract.emit_config(
        tmp_path, 'gfX', tmp_path / 'c.json')


def test_overlay_sources_every_value_and_never_exceeds_the_declared_cap(tmp_path):
    _l19(tmp_path)
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    overlay = cts.overlay(runner, tmp_path, 'gfX', {}, 8, 'runner cap', scratch)
    assert 'CTS_SINK_CLUSTERING_SIZE' not in overlay           # L19's 4 via emit_config
    assert overlay['CTS_DISTANCE_BETWEEN_BUFFERS'][0] > 0
    assert all(isinstance(src, str) and src for _, src in overlay.values())
    knob = cts.overlay(
        runner,
        tmp_path, 'gfX', {'cts_cluster_size': 3, 'cts_distance_between_buffers': 40.0},
        8, 'runner cap', scratch)
    assert knob['CTS_SINK_CLUSTERING_SIZE'][0] == 3
    assert knob['CTS_DISTANCE_BETWEEN_BUFFERS'] == (40.0, knob['CTS_DISTANCE_BETWEEN_BUFFERS'][1])
    with pytest.raises(ValueError, match='LL_CTS_CLUSTER_EXCEEDS_FANOUT'):
        cts.overlay(runner, tmp_path, 'gfX', {'cts_cluster_size': 9}, 8,
                                           'runner cap', scratch)
    _l19(tmp_path, max_fanout=None)
    fallback = cts.overlay(runner, tmp_path, 'gfX', {}, 6, 'runner cap', scratch)
    assert fallback['CTS_SINK_CLUSTERING_SIZE'] == (6, 'runner cap')


def test_derived_step_config_keeps_the_step_and_records_every_change(tmp_path):
    cfg = put(tmp_path / 'OpenROAD.STAMidPNR.json', {'meta': {'step': 'OpenROAD.STAMidPNR'},
                                                     'PNR_CORNERS': None})
    put(tmp_path / 'OpenROAD.STAMidPNR.views.json', {'inputs': ['odb'], 'outputs': []})
    out = contract.derive_step_config(cfg, tmp_path / 'OpenROAD.STAMidPNR@c1.json',
                                      {'PNR_CORNERS': (['c1'], 'one corner per run')})
    doc = json.loads(out.read_text())
    assert doc['meta']['step'] == 'OpenROAD.STAMidPNR' and doc['PNR_CORNERS'] == ['c1']
    prov = json.loads(out.with_suffix('.provenance.json').read_text())
    assert prov['keys'] == {'PNR_CORNERS': 'one corner per run'}
    assert prov['derived_from_sha256'] == contract.digest(cfg)
    assert json.loads(contract.views_path(out).read_text())['inputs'] == ['odb']


def test_only_a_vibeic_step_gets_the_plugin_on_its_path(tmp_path, monkeypatch):
    project = tmp_path / 'p'
    views = {k: write(project / f'in/x.{k}', k) for k in ('odb', 'def', 'nl', 'sdc')}
    state = put(project / 'in/state.json', {k: str(v) for k, v in views.items()})
    calls = []

    def tool(cmd, **_):
        calls.append(cmd)
        out = Path(cmd[cmd.index('-o') + 1])
        put(out / 'state_out.json', {k: str(v) for k, v in views.items()})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', tool)
    steps = []
    for step in ('OpenROAD.CTS', 'Vibeic.ClockPathDriveSizing'):
        steps.append((step, put(project / f'cfg/{step}.json', {'meta': {'step': step}}), state))
    folders = contract.run_chain(project, 'img', steps, pdk_root='/pdk')
    root = str(contract.PLUGIN_ROOT.resolve())
    programs = str(contract.PLUGIN_ROOT.parent.resolve())
    assert f'PYTHONPATH={root}' not in calls[0]
    assert f'PYTHONPATH={root}' in calls[1] and f'{programs}:{programs}:ro' in calls[1]
    fingerprint = json.loads((folders[1] / 'input_fingerprint.json').read_text())
    # the OpenROAD script is the step's code too (T98 extended T97's digest)
    assert {'librelane_plugins/librelane_plugin_vibeic/__init__.py',
            'librelane_plugins/librelane_plugin_vibeic/clock_path_drive_sizing.tcl'} \
        <= set(fingerprint['plugin'])
    assert 'plugin' not in json.loads((folders[0] / 'input_fingerprint.json').read_text())


def test_the_plugin_step_sources_the_runners_one_sizing_pass():
    pkg = contract.PLUGIN_ROOT / 'librelane_plugin_vibeic'
    init = (pkg / '__init__.py').read_text()
    tcl = (pkg / 'clock_path_drive_sizing.tcl').read_text()
    assert 'id = "Vibeic.ClockPathDriveSizing"' in init
    assert 'source $::env(VIBEIC_CLKPATH_SIZING_TCL)' in tcl
    assert 'swapMaster' not in tcl          # the algorithm lives in the runner only
    assert '_vic_prects_insts' in tcl and 'write_views' in tcl
    assert 'utl::metric_integer "vibeic__cts__max_fanout"' in tcl


# ------------------------------------------------- the split, end to end ---

def _fake_tool_run(project, corners, *, hold, cts_buffers=7, fail_step=None):
    """What LibreLane writes for each step, at the run_chain edge."""
    seen = {}

    def chain(proj, image, triples, **kwargs):
        seen['steps'] = [s for s, _, _ in triples]
        seen['configs'] = [c for _, c, _ in triples]
        seen['kwargs'] = kwargs
        base = proj / 'phase3/librelane' / kwargs.get('lane', 'x')
        folders, metrics = [], {}
        for i, (step, _, _) in enumerate(triples, 1):
            folder = base / f'{i:02d}-{step.lower().replace(".", "-")}'
            if step == fail_step:
                raise contract.Refusal('LL_STEP_FAILED', step)
            views = {k: write(folder / f'chip_top.{k}', f'{step} {k}\n') for k in ('odb', 'def')}
            if step == 'OpenROAD.CTS':
                write(folder / 'cts.rpt', f'Total number of Buffers Inserted: {cts_buffers}.\n'
                                          'Total number of Sinks: 9.\n')
                write(folder / 'openroad-cts.log', '[INFO CTS-0010]  Clock net "clk" has 9 sinks.\n')
                metrics['design__instance__area__stdcell'] = 1000.0
            if step == 'OpenROAD.ResizerTimingPostCTS':
                write(folder / 'openroad-resizertimingpostcts.log', '[INFO RSZ-0032] Inserted 2 hold buffers.\n')
                metrics.update({'design__instance__count__hold_buffer': 2,
                                'design__instance__count__setup_buffer': 0,
                                'design__instance__area__stdcell': 1010.0})
            if step == 'OpenROAD.STAMidPNR':
                corner = json.loads(triples[i - 1][1].read_text())['PNR_CORNERS'][0]
                metrics[f'timing__hold__ws__corner:{corner}'] = hold[corner]
                metrics[f'timing__setup__ws__corner:{corner}'] = 5.0
                metrics[f'clock__skew__worst_setup__corner:{corner}'] = -0.1
                views = {}
            state = {k: str(v) for k, v in views.items()} or json.loads(
                ((folders[-1] / 'state_out.json') if folders else triples[0][2]).read_text())
            state = dict(state, metrics=dict(metrics))
            put(folder / 'state_out.json', state)
            folders.append(folder)
        return folders

    def resolve(proj, image, pdk, step_ids, **kwargs):
        seen['overlay'] = kwargs.get('overlay')
        root = proj / 'phase3/librelane' / kwargs['folder']
        lib = write(proj.parent / 'pdkroot' / pdk / 'neutral.lib',
                    'library(x) {\n cell (neutral__dly_1) { }\n}\n')
        out = {}
        for step in step_ids:
            doc = {'meta': {'step': step}, 'STA_CORNERS': corners,
                   'PNR_CORNERS': None}
            if step in ('OpenROAD.CTS', 'OpenROAD.ResizerTimingPostCTS'):
                doc.update(CELL_LIBS={'nom': [f'/pdk/{pdk}/{lib.name}']},
                           EXTRA_EXCLUDED_CELLS=[])
            out[step] = put(root / f'{step}.json', doc)
            put(root / f'{step}.views.json', {'inputs': ['odb'], 'outputs': []})
        return out

    return chain, resolve, seen


def _split_project(tmp_path, switch):
    project = tmp_path / 'proj'
    out_dir = project / 'phase3/stage3/pnr'
    put(project / 'phase3/librelane_switch.json',
        dict(switch, pdk_root_host=str(tmp_path / 'pdkroot'), image='img@sha256:x'))
    (tmp_path / 'pdkroot/pdkX').mkdir(parents=True)
    write(out_dir / 'constraint.sdc', 'create_clock -period 24 clk\n')
    deck = ('read_lef /t.lef\nread_liberty /l.lib\nread_verilog /n.v\nlink_design chip_top\n'
            f'read_sdc {out_dir}/constraint.sdc\n'
            f'{runner._PNR_RESUME_ELIDE_BEGIN}\nglobal_placement\n'
            f'{runner._PNR_CTS_HOLD_BEGIN}\nclock_tree_synthesis -buf_list b\n'
            f'write_def {out_dir}/post_cts.def\nrepair_timing -hold\n'
            f'write_def {out_dir}/post_hold.def\n{runner._PNR_CTS_HOLD_END}\n'
            f'global_route\ndetailed_route\nwrite_def {out_dir}/routed_preantenna.def\n'
            f'{runner._PNR_RESUME_ELIDE_END}\nwrite_def {out_dir}/routed.def\n')
    pnr_tcl = write(out_dir / 'pnr.tcl', deck)
    return project, out_dir, pnr_tcl


def _run_split(tmp_path, monkeypatch, *, switch=None, hold=None, arm_hold=None, fail_step=None):
    switch = switch or {'steps': {'19': 'librelane', '20': 'librelane'}}
    project, out_dir, pnr_tcl = _split_project(tmp_path, switch)
    hold = hold or {c: 0.2 for c in CORNERS}
    chain, resolve, seen = _fake_tool_run(project, CORNERS, hold=hold, fail_step=fail_step)
    arm_hold = arm_hold or hold

    def chains(proj, image, triples, **kwargs):
        if kwargs.get('lane') == '19-cts-hold-direct-arm':
            c2, _, s2 = _fake_tool_run(project, CORNERS, hold=arm_hold)
            seen['arm_steps'] = [s for s, _, _ in triples]
            return c2(proj, image, triples, **kwargs)
        return chain(proj, image, triples, **kwargs)

    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'run_chain', chains)
    monkeypatch.setattr(contract, 'state_from_direct', lambda p, i, cfg, views, out, **k: (
        seen.setdefault('bridged', []).append({v: str(x) for v, x in views.items()})
        or put(out / 'state_in.json', {'odb': str(views['odb'])})))
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '# after restore\n')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    execs = []

    def docker(container, cmd, *a, **k):
        execs.append(cmd)
        if 'pnr_cts_head.tcl' in cmd:
            for ext in ('odb', 'def', 'nl.v', 'insts'):
                write(out_dir / f'cts_hold_split/pre_cts.{ext}', f'pre {ext}\n')
            return 0, 'head ok', ''
        if 'pnr_cts_direct_arm.tcl' in cmd:
            arm = project / 'phase3/tool_arms/19/openroad'
            for name in ('post_cts.def', 'post_hold.def', 'post_hold.odb'):
                write(arm / name, f'direct arm {name}\n')
            return 0, 'arm ok', ''
        return 0, 'tail ok', ''

    monkeypatch.setattr(runner, '_docker_exec', docker)
    cmd = (f'openroad -no_init -exit -metrics {out_dir}/openroad.metrics.json '
           f'{pnr_tcl} 2>&1 | tee {out_dir}/openroad.log')
    modes = cts.modes(project)
    rc, out, err = cts.execute(
        runner,
        project=project, pdk=SimpleNamespace(name='pdkX'), container='c', out_dir=out_dir,
        out_dir_c=str(out_dir), pnr_tcl=pnr_tcl, modes=modes, cmd=cmd, spare_plan=None,
        overlay={'CTS_DISTANCE_BETWEEN_BUFFERS': (10.0, 'policy')}, exec_kwargs={})
    return SimpleNamespace(rc=rc, out=out, project=project, out_dir=out_dir, seen=seen,
                           execs=execs)


def test_librelane_views_reach_the_paths_the_direct_route_reads(tmp_path, monkeypatch):
    run = _run_split(tmp_path, monkeypatch)
    assert run.rc == 0
    assert run.seen['steps'] == ['OpenROAD.CTS', 'Vibeic.ClockPathDriveSizing',
                                 'Vibeic.ExternalCaptureLaunchRetap',
                                 'OpenROAD.ResizerTimingPostCTS'] + ['OpenROAD.STAMidPNR'] * 3
    assert run.seen['kwargs']['lane'] == '19-cts-hold'
    # head, then the tail appended to the same log, never the unsplit deck
    assert len(run.execs) == 2 and 'pnr_cts_head.tcl' in run.execs[0]
    assert 'pnr_cts_tail.tcl' in run.execs[1] and 'tee -a' in run.execs[1]
    assert not any('/pnr.tcl ' in c for c in run.execs)
    receipt = json.loads((run.project / llev.RECEIPT_REL).read_text())
    base = run.project / 'phase3/librelane/19-cts-hold'
    assert (run.out_dir / 'post_cts.def').read_text() == \
        (base / '03-vibeic-externalcapturelaunchretap/chip_top.def').read_text()
    assert (run.out_dir / 'post_hold.odb').read_text() == \
        (base / '04-openroad-resizertimingpostcts/chip_top.odb').read_text()
    assert (run.project / 'phase3/stage3/cts/clock_tree.rpt').read_text().startswith(
        'Total number of Buffers Inserted: 7.')
    for view in receipt['views'].values():
        assert contract.digest(run.project / view['dest']) == view['dest_sha256']
    assert receipt['measured_state'].endswith('07-openroad-stamidpnr/state_out.json')
    # the per-corner STA configs each name one corner
    assert [json.loads(c.read_text())['PNR_CORNERS'] for c in run.seen['configs'][4:]] == \
        [[c] for c in CORNERS]
    sizing = json.loads(run.seen['configs'][1].read_text())
    assert sizing['PNR_CORNERS'] == CORNERS
    retap = json.loads(run.seen['configs'][2].read_text())
    assert retap['PNR_CORNERS'] == CORNERS
    assert Path(retap['VIBEIC_CLKPATH_PRECTS_INSTANCES']).is_file()
    assert Path(sizing['VIBEIC_CLKPATH_SIZING_TCL']).read_text() == \
        runner._clock_path_drive_sizing_tcl()
    log = (run.out_dir / 'openroad.log').read_text()
    assert 'PNR_STAGE: cts' in log and 'PNR_STAGE: hold_repair' in log
    assert 'CTS-0010' in log and 'RSZ-0032' in log
    # hold is repaired and measured in the sign-off's own scene (its OCV derate)
    sdc_path, source = run.seen['overlay']['PNR_SDC_FILE']
    scene = Path(sdc_path).read_text()
    assert scene.startswith('create_clock -period 24 clk\n')
    assert f'set_timing_derate -early {runner._FLAT_OCV_DERATE_EARLY}' in scene
    assert f'set_timing_derate -late {runner._FLAT_OCV_DERATE_LATE}' in scene
    assert 'constraint.sdc' in source and '_FLAT_OCV_DERATE' in source
    area = json.loads((run.project / 'reports/phase3/pnr/hold_area.json').read_text())
    assert (area['before_total_area'], area['after_total_area'], area['hold_buffer_count']) \
        == (1000.0, 1010.0, 2)


def test_cts_local_route_binds_the_resolved_pdk_root_at_the_cli_root(tmp_path, monkeypatch):
    """The real CTS caller and LOCAL run_chain agree on the /pdk root."""
    switch = {'steps': {'19': 'librelane', '20': 'librelane'}}
    project, out_dir, pnr_tcl = _split_project(tmp_path, switch)
    pdk_root = tmp_path / 'pdkroot'
    pdk_root.mkdir(exist_ok=True)
    pdk_name = 'pdkX'
    (pdk_root / pdk_name).mkdir(exist_ok=True)
    image = 'img@sha256:' + '7c' * 32
    attestation = {'image': image, 'image_id': 'sha256:' + '7c' * 32,
                   'repo_digests': [image], 'cid': 'ab' * 32,
                   'network_mode': 'none', 'memory': 64 * 1024**3,
                   'memory_swap': 64 * 1024**3, 'auto_remove': True}
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(contract, 'local_image_attestation', lambda _image: attestation)
    monkeypatch.setattr(contract, 'image_capability', lambda *_a, **_k: None)
    monkeypatch.setattr(runner, '_resolved_cell_policy', lambda configs, *_a, **_k:
                        (configs, set()))

    corners = ['nom_tt_025C_5v00']

    def resolve(_project, _image, _pdk, step_ids, *, folder, **_kwargs):
        root = project / 'phase3/librelane' / folder
        result = {}
        for step in step_ids:
            config = put(root / f'{step}.json', {
                'meta': {'step': step}, 'STA_CORNERS': corners, 'PNR_CORNERS': corners})
            put(contract.views_path(config), {
                'step': step, 'inputs': ['odb', 'def', 'nl', 'sdc'], 'outputs': []})
            result[step] = config
        return result

    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'pdk_root_resolution',
                        lambda *_a, **_k: {'path': str(pdk_root)})

    def bridge(_project, _image, _config, views, output, **_kwargs):
        state = {key: str(Path(value).resolve()) for key, value in views.items()}
        return put(output / 'state_in.json', state)

    monkeypatch.setattr(contract, 'state_from_direct', bridge)
    direct_calls = []

    def direct(_container, cmd, *args, **kwargs):
        direct_calls.append(cmd)
        if 'pnr_cts_head.tcl' in cmd:
            for ext in ('odb', 'def', 'nl.v', 'insts'):
                write(out_dir / f'cts_hold_split/pre_cts.{ext}', f'pre {ext}\n')
        return 0, 'head ok', ''

    monkeypatch.setattr(runner, '_docker_exec', direct)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *_a, **_k: '# restore\n')
    monkeypatch.setattr(runner, '_container_mounts', lambda _container: [])

    import _watchdog as watchdog
    native_argv = []

    class StopAfterLocalCommand(RuntimeError):
        pass

    def supervised(command, **_kwargs):
        native_argv.append(command)
        out = Path(command[command.index('-o') + 1])
        views = {key: str(path.resolve()) for key, path in {
            'odb': out_dir / 'cts_hold_split/pre_cts.odb',
            'def': out_dir / 'cts_hold_split/pre_cts.def',
            'nl': out_dir / 'cts_hold_split/pre_cts.nl.v',
            'sdc': out_dir / 'constraint.sdc'}.items()}
        put(out / 'state_out.json', views)
        return SimpleNamespace(outcome='completed', rc=0, out='', err='', supervision={})

    monkeypatch.setattr(watchdog, 'run_host_supervised', supervised)
    original_chain = contract.run_chain

    def stop_after_chain(*args, **kwargs):
        folders = original_chain(*args, **kwargs)
        raise StopAfterLocalCommand(folders)

    monkeypatch.setattr(contract, 'run_chain', stop_after_chain)
    with pytest.raises(StopAfterLocalCommand) as stopped:
        cts.execute(
            runner, project=project, pdk=SimpleNamespace(name=pdk_name), container='c',
            out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl,
            modes={'19': 'librelane', '20': 'librelane'},
            cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None,
            overlay={}, exec_kwargs={})

    assert stopped.value.args[0]
    assert native_argv
    assert all(command[command.index('--pdk-root') + 1] == str(pdk_root.resolve())
               for command in native_argv)
    pdk_record = json.loads((stopped.value.args[0][0] / 'pdk_root.json').read_text())
    assert pdk_record['cli_pdk_root'] == str(pdk_root.resolve())
    assert pdk_record['requested_pdk_root'] == '/pdk'
    assert pdk_record['execution_route'] == 'LOCAL'
    assert pdk_record['requested_mounts'] == [[str(pdk_root.resolve()), '/pdk']]
    assert pdk_record['mounts_under_it'] == [[str(pdk_root.resolve()),
                                               str(pdk_root.resolve())]]


def test_cts_local_route_still_refuses_a_missing_selected_pdk(tmp_path, monkeypatch):
    switch = {'steps': {'19': 'librelane', '20': 'librelane'}}
    project, out_dir, pnr_tcl = _split_project(tmp_path, switch)
    shutil.rmtree(tmp_path / 'pdkroot' / 'pdkX')
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda image: {'image': image})
    monkeypatch.setattr(contract, 'image_capability', lambda *_a, **_k: None)
    calls = []

    def direct(_container, cmd, *args, **kwargs):
        calls.append(cmd)
        for ext in ('odb', 'def', 'nl.v', 'insts'):
            write(out_dir / f'cts_hold_split/pre_cts.{ext}', f'pre {ext}\n')
        return 0, 'head ok', ''

    monkeypatch.setattr(runner, '_docker_exec', direct)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *_a, **_k: '# restore\n')
    monkeypatch.setattr(runner, '_container_mounts', lambda _container: [])
    result = cts.execute(
        runner, project=project, pdk=SimpleNamespace(name='pdkX'), container='c',
        out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl,
        modes={'19': 'librelane', '20': 'librelane'},
        cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None,
        overlay={}, exec_kwargs={})
    assert result[0] != 0 and 'LL_PDK_MISSING' in result[1]
    assert len(calls) == 1 and 'pnr_cts_head.tcl' in calls[0]
    assert not (project / 'phase3/librelane/19-cts-hold/01-openroad-cts/invocation.log').exists()


def test_a_missing_pdk_root_refuses_and_never_resumes_the_route(tmp_path, monkeypatch):
    switch = {'steps': {'19': 'librelane', '20': 'librelane'}}
    project, out_dir, pnr_tcl = _split_project(tmp_path, switch)
    put(project / 'phase3/librelane_switch.json', switch)
    execs = []

    def docker(container, cmd, *a, **k):
        execs.append(cmd)
        for ext in ('odb', 'def', 'nl.v', 'insts'):
            write(out_dir / f'cts_hold_split/pre_cts.{ext}', 'x\n')
        return 0, '', ''

    monkeypatch.setattr(runner, '_docker_exec', docker)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    rc, out, _ = cts.execute(
        runner,
        project=project, pdk=SimpleNamespace(name='pdkX'), container='c', out_dir=out_dir,
        out_dir_c=str(out_dir), pnr_tcl=pnr_tcl, modes={'19': 'librelane', '20': 'librelane'},
        cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None, overlay={},
        exec_kwargs={})
    assert rc != 0 and 'LL_PDK_ROOT_NOT_DECLARED' in out
    assert len(execs) == 1 and not (out_dir / 'post_hold.def').exists()


def test_a_failing_tool_step_refuses_by_name(tmp_path, monkeypatch):
    run = _run_split(tmp_path, monkeypatch, fail_step='OpenROAD.ResizerTimingPostCTS')
    assert run.rc != 0 and 'LL_STEP_FAILED' in run.out
    assert len(run.execs) == 1 and not (run.out_dir / 'post_hold.def').exists()


def test_dual_judges_both_arms_by_the_same_sta_and_hands_over_the_winner(tmp_path, monkeypatch):
    better = {c: 0.3 for c in CORNERS}
    worse = dict(better, nom_ss_125C_4v50=-0.5)
    run = _run_split(tmp_path, monkeypatch, switch={'steps': {'19': 'dual', '20': 'dual'}},
                     hold=better, arm_hold=worse)
    assert run.rc == 0
    assert run.seen['arm_steps'] == ['OpenROAD.STAMidPNR'] * 3
    selection = json.loads((run.project / 'phase3/tool_arms/19/selection.json').read_text())
    assert selection['selection'] == 'librelane'
    # and the other way round: the direct arm wins and ITS views are handed over
    run2 = _run_split(tmp_path / 'b', monkeypatch, switch={'steps': {'19': 'dual', '20': 'dual'}},
                      hold=worse, arm_hold=better)
    assert run2.rc == 0
    assert (run2.out_dir / 'post_hold.odb').read_text() == 'direct arm post_hold.odb\n'
    receipt = json.loads((run2.project / llev.RECEIPT_REL).read_text())
    assert receipt['selected'] == 'openroad' and 'cts_rpt' not in receipt['views']
    assert 'direct-arm' in receipt['measured_state']


# ------------------------------------------------------------------ gates ---

def _handoff(project, hold, *, stale=False, corners=CORNERS, extra=None,
             buffers=2, cap=4, drop=()):
    """The receipt and views as the runner leaves them after the split."""
    pnr = project / 'phase3/stage3/pnr'
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'19': 'librelane', '20': 'librelane'}})
    defs = {}
    master = 'clkbuf_8' if buffers else 'inv_1'
    body = ('VERSION 5.8 ;\nDESIGN chip_top ;\nCOMPONENTS 2 ;\n'
            f'- u1 {master} + PLACED ( 0 0 ) N ;\n- u2 {master} + PLACED ( 1 0 ) N ;\n'
            'END COMPONENTS\nEND DESIGN\n')
    for name in ('post_cts.def', 'post_hold.def'):
        defs[name] = write(pnr / name, body)
    rpt = write(project / 'phase3/stage3/cts/clock_tree.rpt',
                'Total number of Clock Roots: 1.\n'
                f'Total number of Buffers Inserted: {buffers}.\n'
                'Total number of Sinks: 9.\n')
    cts_folder = project / 'phase3/librelane/19-cts-hold/01-openroad-cts'
    put(cts_folder / 'config.json', {'meta': {'step': 'OpenROAD.CTS'},
                                     'MAX_FANOUT_CONSTRAINT': cap})
    metrics = {f'timing__hold__ws__corner:{c}': v for c, v in hold.items()}
    metrics['vibeic__cts__max_fanout'] = 3
    metrics.update({f'clock__skew__worst_setup__corner:{c}': -0.12 for c in corners},
                   **{'design__instance__count__hold_buffer': 3}, **(extra or {}))
    for key in drop:
        metrics.pop(key)
    state = put(project / 'phase3/librelane/19-cts-hold/06-openroad-stamidpnr/state_out.json',
                {'metrics': metrics})
    views = {n: {'dest': str(p.relative_to(project)), 'dest_sha256': contract.digest(p)}
             for n, p in (('post_cts_def', defs['post_cts.def']),
                          ('post_hold_def', defs['post_hold.def']), ('cts_rpt', rpt))}
    put(project / llev.RECEIPT_REL, {
        'selected': 'librelane', 'corners': corners, 'views': views,
        'chain': {'OpenROAD.CTS': str(cts_folder.relative_to(project))},
        'measured_state': str(state.relative_to(project)),
        'measured_state_sha256': contract.digest(state)})
    if stale:
        write(defs['post_hold.def'], body.replace('( 1 0 )', '( 2 0 )'))


def _gate(name, project, *extra):
    out = project / f'{name}.json'
    proc = subprocess.run([sys.executable, str(PROGRAMS / f'{name}.py'), str(project),
                           '--json', str(out), *extra], capture_output=True, text=True)
    doc = json.loads(out.read_text()) if out.is_file() else {}
    return proc.returncode, doc, proc.stdout + proc.stderr


def test_hold_gate_judges_the_tools_hold_at_every_corner(tmp_path):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS})
    rc, doc, text = _gate('hold_closure_check', tmp_path)
    assert rc == 0 and doc['verdict'] == 'PASS', text
    assert any(f.get('rule') == 'HOLD_CLEAN_EVERY_CORNER' for f in doc['findings'])


@pytest.mark.parametrize('hold,rule', [
    ({**{c: 0.15 for c in CORNERS}, 'nom_ss_125C_4v50': -0.81}, 'HOLD_VIOLATION'),
    ({c: 0.15 for c in CORNERS[:2]}, 'HOLD_CORNER_NOT_MEASURED'),
])
def test_hold_gate_fails_a_violating_or_unmeasured_corner(tmp_path, hold, rule):
    _handoff(tmp_path, hold)
    rc, doc, text = _gate('hold_closure_check', tmp_path)
    assert rc == 1 and doc['verdict'] == 'FAIL', text
    assert any(f.get('rule') == rule for f in doc['findings'])
    if rule == 'HOLD_VIOLATION':
        assert 'nom_ss_125C_4v50' in text


def test_hold_gate_refuses_a_def_that_is_no_longer_what_the_tool_handed_over(tmp_path):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS}, stale=True)
    rc, doc, text = _gate('hold_closure_check', tmp_path)
    assert rc == 1 and 'HANDOFF_STALE' in text


def test_hold_gate_without_a_switch_keeps_its_direct_evidence(tmp_path):
    _handoff(tmp_path, {**{c: 0.15 for c in CORNERS}, 'nom_ss_125C_4v50': -0.81})
    (tmp_path / 'phase3/librelane_switch.json').unlink()
    write(tmp_path / 'phase3/stage3/pnr/post_hold_timing.rpt', 'worst hold slack 0.25\n')
    rc, doc, text = _gate('hold_closure_check', tmp_path)
    assert rc == 0 and 'librelane' not in doc.get('summary', {}), text


def test_cts_gate_reads_report_cts_and_the_tools_skew(tmp_path):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS})
    rc, doc, text = _gate('cts_quality_check', tmp_path)
    assert rc == 0 and doc['verdict'] == 'PASS', text
    assert doc['metrics']['report_created_buffers'] == 2
    assert doc['metrics']['skew_value'] == pytest.approx(0.12)
    assert any(f.get('rule') == 'SKEW_FROM_TOOL_METRICS' for f in doc['findings'])


def test_cts_gate_fails_zero_buffers_and_a_stale_handoff(tmp_path):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS}, buffers=0)
    rc, doc, text = _gate('cts_quality_check', tmp_path)
    assert rc == 1 and any(f.get('rule') == 'ZERO_CLOCK_BUFFERS' for f in doc['findings']), text
    _handoff(tmp_path / 'b', {c: 0.15 for c in CORNERS})
    rpt = tmp_path / 'b/phase3/stage3/cts/clock_tree.rpt'
    rpt.write_text(rpt.read_text().replace('Inserted: 2', 'Inserted: 20'))
    rc, _, text = _gate('cts_quality_check', tmp_path / 'b')
    assert rc == 1 and 'HANDOFF_STALE' in text      # the receipt binds the report


@pytest.mark.parametrize('kwargs,rule', [
    ({'extra': {'vibeic__cts__max_fanout': 9}}, 'CLOCK_FANOUT_EXCEEDS_CAP'),
    ({'drop': ('vibeic__cts__max_fanout',)}, 'CLOCK_FANOUT_NOT_MEASURED'),
])
def test_cts_gate_holds_the_clock_tree_to_the_declared_fanout(tmp_path, kwargs, rule):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS}, **kwargs)
    rc, doc, text = _gate('cts_quality_check', tmp_path)
    assert rc == 1 and any(f.get('rule') == rule for f in doc['findings']), text


def test_cts_gate_passes_a_tree_within_the_cap_and_records_it(tmp_path):
    _handoff(tmp_path, {c: 0.15 for c in CORNERS})
    rc, doc, text = _gate('cts_quality_check', tmp_path)
    assert rc == 0, text
    assert doc['metrics']['clock_tree_fanout']['max_fanout'] == 3
    assert doc['metrics']['clock_tree_fanout']['cap'] == 4


def test_identical_stage_defs_are_legitimate_only_on_the_tools_clean_hold(tmp_path):
    import def_stage_progression_check as dsp
    _handoff(tmp_path, {c: 0.15 for c in CORNERS})
    assert dsp._hold_clean_noop_ok(tmp_path) is True
    _handoff(tmp_path / 'v', {**{c: 0.15 for c in CORNERS}, 'nom_ff_n40C_5v50': -0.01})
    assert dsp._hold_clean_noop_ok(tmp_path / 'v') is False
    _handoff(tmp_path / 's', {c: 0.15 for c in CORNERS}, stale=True)
    assert dsp._hold_clean_noop_ok(tmp_path / 's') is False


def test_hold_area_budget_reads_the_resizers_own_area_and_count(tmp_path):
    area = tmp_path / 'reports/phase3/pnr/hold_area.json'
    put(area, {'before_total_area': 1000.0, 'after_total_area': 1010.0,
               'hold_buffer_count': 2})
    rc, doc, _ = _gate('hold_area_budget_check', tmp_path)
    assert rc == 0 and doc['verdict'] == 'PASS' and doc['overhead_pct'] == pytest.approx(0.990099, 1e-4)
    put(area, {'before_total_area': 1000.0, 'after_total_area': 1100.0, 'hold_buffer_count': 40})
    rc, doc, _ = _gate('hold_area_budget_check', tmp_path)
    assert rc == 1 and doc['reason'] == 'AREA_BUDGET_EXCEEDED'
    # The tool measured ZERO hold buffers: nothing to budget, and that is a
    # measurement, not a step that did no work.
    put(area, {'before_total_area': 1000.0, 'after_total_area': 1000.0, 'hold_buffer_count': 0})
    rc, doc, _ = _gate('hold_area_budget_check', tmp_path)
    assert rc == 0 and doc['reason'] == 'NO_HOLD_BUFFERS_NEEDED'


def test_a_ppa_candidate_sets_only_the_declared_knobs_within_the_cap(tmp_path):
    _l19(tmp_path)
    scratch = tmp_path / 'scratch'
    put(tmp_path / 'phase3/librelane_switch.json', {
        'steps': {'19': 'librelane', '20': 'librelane'},
        'knobs': {'CTS_SINK_CLUSTERING_SIZE': 2, 'PL_RESIZER_HOLD_SLACK_MARGIN': 0.05}})
    out = cts.overlay(runner, tmp_path, 'gfX', {'cts_cluster_size': 3}, 8, 'cap', scratch)
    assert out['CTS_SINK_CLUSTERING_SIZE'][0] == 2
    assert out['PL_RESIZER_HOLD_SLACK_MARGIN'] == (
        0.05, 'phase3/librelane_switch.json knobs (PPA candidate)')
    put(tmp_path / 'phase3/librelane_switch.json', {'knobs': {'CTS_SINK_CLUSTERING_SIZE': 16}})
    with pytest.raises(ValueError, match='LL_CTS_CLUSTER_EXCEEDS_FANOUT'):
        cts.overlay(runner, tmp_path, 'gfX', {}, 8, 'cap', scratch)
    put(tmp_path / 'phase3/librelane_switch.json', {'knobs': {'GRT_ADJUSTMENT': 0.1}})
    with pytest.raises(ValueError, match='LL_CTS_HOLD_KNOB_UNKNOWN'):
        cts.overlay(runner, tmp_path, 'gfX', {}, 8, 'cap', scratch)


def test_clock_skew_is_a_timing_metric_ppa_can_optimise():
    backend = importlib.import_module('_ppa.backends.librelane')
    assert {'clock__skew__worst_setup', 'clock__skew__worst_hold'} <= set(backend.TIMING_METRICS)


def test_the_split_works_on_the_step_17_18_librelane_consumer_deck(real_deck):
    """T97 hands placement to the direct deck at `puts "<marker> cts"`
    (`placement_consumer_tcl`); the 19/20 region must survive that seam and
    split the same way, so LL 15..18 -> LL 19/20 -> direct tail is one chain."""
    consumer = contract.placement_consumer_tcl(real_deck, '/w/ll_placed.def',
                                               runner._PNR_STAGE_MARKER)
    assert consumer.count(runner._PNR_CTS_HOLD_BEGIN) == 1
    assert consumer.count(runner._PNR_CTS_HOLD_END) == 1
    head = cts.head_deck(runner, consumer, odb_c='/w/pre.odb', def_c='/w/pre.def',
                         nl_c='/w/pre.v', insts_c='/w/pre.insts')
    assert 'read_def /w/ll_placed.def' in head and 'write_db /w/pre.odb' in head
    assert not _has(head, 'global_placement') and not _has(head, 'clock_tree_synthesis')
    tail = cts.tail_deck(runner, consumer, odb_c='/w/post_hold.odb',
                         def_c='/w/post_hold.def', after_restore_tcl='')
    assert 'read_db /w/post_hold.odb' in tail and 'read_def /w/ll_placed.def' not in tail
    assert _has(tail, 'detailed_route') and not _has(tail, 'clock_tree_synthesis')


# SOURCE_CONTROL: the complete installed Tcl entry runs under tclsh. Only the
# OpenROAD/ODB process edge and its view writer are replaced; the closure and
# final census are the product source, and the consumer below is the real CLI.
_CTS_FANOUT_WORLD = r"""
namespace eval ord {}; namespace eval sta {}; namespace eval utl {}
set ::insts {}; set ::nets {}; set ::terms {}; set ::metrics [dict create]
set ::inserted 0; set ::pg 0; set ::legal 0; set ::written 0
proc object {kind name} { interp alias {} $name {} dispatch $kind $name; return $name }
proc net {name} {
    lappend ::nets $name; set ::world_nt($name) {}; set ::world_bt($name) {}
    set ::world_sig($name) SIGNAL; object net $name
}
proc connect {term net} {
    if {[info exists ::world_tn($term)] && $::world_tn($term) ne "NULL"} {
        set old $::world_tn($term); set i [lsearch -exact $::world_nt($old) $term]
        set ::world_nt($old) [lreplace $::world_nt($old) $i $i]
    }
    set ::world_tn($term) $net
    if {$net ne "NULL"} { lappend ::world_nt($net) $term }
}
proc inst {name master} {
    lappend ::insts $name; set ::world_im($name) $master; set ::world_ps($name) PLACED
    set ::world_it($name) {}; object inst $name; object master $master
    foreach {pin dir sig} {I INPUT SIGNAL Z OUTPUT SIGNAL VP INOUT POWER VG INOUT GROUND} {
        set term $name/$pin; lappend ::world_it($name) $term; lappend ::terms $term
        set ::world_ti($term) $name; set ::world_td($term) $dir; set ::world_ts($term) $sig
        set ::world_tp($term) $pin; set ::world_tn($term) NULL; object term $term
    }
}
proc dispatch {kind obj method args} {
    switch -- $kind {
        block {
            switch -- $method {
                getInsts { return $::insts }
                findInst { set x [lindex $args 0]; if {[info exists ::world_im($x)]} {return $x}; return NULL }
                findNet { set x [lindex $args 0]; if {[info exists ::world_nt($x)]} {return $x}; return NULL }
            }
        }
        inst {
            switch -- $method {
                getName { return $obj }
                getMaster { return $::world_im($obj) }
                getITerms { return $::world_it($obj) }
                findITerm { set t $obj/[lindex $args 0]; if {[info exists ::world_tn($t)]} {return $t}; return NULL }
                getPlacementStatus { return $::world_ps($obj) }
                setPlacementStatus { set ::world_ps($obj) [lindex $args 0]; return }
            }
        }
        master { if {$method eq "getName"} { return $obj } }
        net {
            switch -- $method {
                getName { return $obj }
                getITerms { return $::world_nt($obj) }
                getBTerms { return $::world_bt($obj) }
                getSigType { return $::world_sig($obj) }
            }
        }
        term {
            switch -- $method {
                getMTerm { return $obj }
                getInst { return $::world_ti($obj) }
                getIoType { return $::world_td($obj) }
                getSigType { return $::world_ts($obj) }
                getName { return $::world_tp($obj) }
                getNet { return $::world_tn($obj) }
                disconnect { connect $obj NULL; return }
                connect { connect $obj [lindex $args 0]; return }
            }
        }
    }
    error "unsupported DB operation $kind $obj $method $args"
}
object block B
proc ord::get_db_block {} { return B }
proc all_clocks {} { return clock }
proc sta::find_clk_nets {clock} {
    set nets {}; foreach n $::nets { if {$n ni {n_data n_power n_ground}} {lappend nets $n} }; return $nets
}
proc get_cells {args} {
    set n [lindex $args end]
    if {[lsearch -exact $args -of_objects] >= 0} { return [lindex [split $n /] 0] }
    return $n
}
proc get_lib_cells {args} { return $::world_im([lindex $args end]) }
proc get_property {obj field} {
    switch -- $field {
        is_buffer { return [expr {$obj ne "unsafe_role"}] }
        is_inverter { return [expr {$::env(DAMAGE) eq "inverter"}] }
        dont_use { return [expr {$::env(DAMAGE) eq "dont-use"}] }
        is_propagated { return 1 }
        period { return 20 }
        is_register_clock { return 1 }
        lib_pin_name { return I }
        startpoint { return r0/Z }
        slack {
            if {$::env(RETAP) eq "none"} { return 5 }
            if {$::world_tn(r0/I) eq "n_root"} {return 0.2}; return -0.2
        }
    }
    error "unsupported STA property $obj $field"
}
proc get_pins {args} {
    if {[lindex $args 0] eq "-of_objects"} { return [list [lindex $args 1]/I] }
    set pins [lindex $args 0]
    foreach pin $pins { if {![info exists ::world_tn($pin)]} {error "unknown load $pin"} }
    return $pins
}
proc get_full_name {x} { return $x }
proc all_outputs {} { return out }
proc all_registers {} { return r0 }
proc find_timing_paths {args} { return path }
proc sta::worst_slack {which} {
    if {$which eq "-min" && $::env(RETAP) eq "rollback" && $::world_tn(r0/I) eq "n_root"} {return -0.1}
    return 0.1
}
proc sta::total_negative_slack {args} { return 0 }
proc set_propagated_clock {args} {}
proc unset_propagated_clock {args} {}
proc estimate_parasitics {args} { lappend ::events estimate }
proc read_current_odb {} {}
proc utl::metric_integer {key value} { dict set ::metrics $key $value }
proc insert_buffer {args} {
    if {[llength $args] != 8} {error "unexpected insert_buffer arity"}
    array set a $args
    if {[lsort [array names a]] ne [lsort {-buffer_cell -load_pins -buffer_name -net_name}]} {error "wrong native flags"}
    if {$::env(DAMAGE) eq "insert-error"} {error "injected native insert error"}
    incr ::inserted
    # The API accepts base names; a legal receiver may uniquify both names.
    set actual_name "$a(-buffer_name)_native"
    set actual_net "$a(-net_name)_native"
    inst $actual_name $a(-buffer_cell); net $actual_net
    set old $::world_tn([lindex $a(-load_pins) 0])
    connect $actual_name/I $old; connect $actual_name/Z $actual_net
    foreach pin $a(-load_pins) {
        if {$::world_tn($pin) ne $old} {error "mixed source nets"}
        connect $pin $actual_net
    }
    lappend ::events insert
}
proc detailed_placement {args} {
    if {[info exists ::env(PL_MAX_DISPLACEMENT_X)] && [info exists ::env(PL_MAX_DISPLACEMENT_Y)]} {
        if {$args ne {-max_displacement {10 20}}} {error "unexpected placement flags $args"}
    } elseif {$args ne {}} {error "missing pair must use native default: $args"}
    foreach i $::insts { if {![string match vic_cts_fanout_* $i] && $::world_ps($i) ni {LOCKED FIRM COVER}} {error "original cell moved $i"} }
    if {$::env(DAMAGE) eq "placement-error"} {error "injected placement error"}
    set ::legal 1; lappend ::events placement
}
proc check_placement {args} {
    if {$args ne {-verbose}} {error "unexpected check flags"}
    if {$::env(DAMAGE) eq "illegal"} {error "injected illegal placement"}
}
proc set_global_connections {} {
    foreach i $::insts { connect $i/VP n_power; connect $i/VG n_ground }
    set ::pg 1; lappend ::events pg
}
proc write_views {} {
    # The real image writer also applies global connections before serializing.
    set_global_connections
    foreach i $::insts {
        if {$::world_tn($i/VP) ne "n_power" || $::world_tn($i/VG) ne "n_ground"} {error "PG absent $i"}
        if {$::world_ps($i) ne "PLACED" && $i ni {spare payload}} {error "placement protection leaked $i"}
    }
    incr ::written; lappend ::events write
    set f [open $::env(WORLD_OUT) w]
    puts $f "meta|$::inserted|$::legal|$::pg|$::written"
    dict for {k v} $::metrics { puts $f "metric|$k|$v" }
    foreach i $::insts { puts $f "inst|$i|$::world_im($i)|$::world_ps($i)" }
    foreach n $::nets { puts $f "net|$n|[join $::world_nt($n) ,]|[join $::world_bt($n) ,]" }
    puts $f "events|[join $::events ,]"
    close $f
}
set ::events {}
foreach n {n_input n_root n_data n_power n_ground} { net $n }
inst origin mux_role; connect origin/Z n_input
if {$::env(DAMAGE) eq "no-role"} {inst root unsafe_role} else {inst root relay_role}
connect root/I n_input; connect root/Z n_root
for {set i 0} {$i < $::env(LOADS)} {incr i} {
    inst leaf$i relay_role; connect leaf$i/I n_root; net n_leaf$i; connect leaf$i/Z n_leaf$i
    inst r$i storage_role; connect r$i/I n_leaf$i
}
inst payload logic_role; connect payload/Z n_data
inst spare spare_role; set ::world_ps(spare) FIRM
for {set i 0} {$i < 17} {incr i} {inst d$i logic_role; connect d$i/I n_data}
if {$::env(DAMAGE) eq "port-load"} {set ::world_bt(n_root) {out_clock}}
if {$::env(DAMAGE) eq "multi-driver"} {connect spare/Z n_root}
set f [open $::env(VIBEIC_CLKPATH_PRECTS_INSTANCES) w]
foreach i $::insts {if {$i ne "root" && ![string match leaf* $i]} {puts $f $i}}
close $f
source $::env(ENTRY)
"""


def _clock_fanout_entry(tmp_path, *, entry="sizing", cap=4, loads=16,
                        damage="none", retap="none", displacement=("10", "20")):
    """Reusable real-entry API; no helper copied out of the product source."""
    import os
    root = tmp_path / "native-boundary"
    common = root / "openroad/common"
    common.mkdir(parents=True)
    for name in ("io.tcl", "resizer.tcl", "set_rc.tcl"):
        write(common / name, "# SOURCE_CONTROL image I/O boundary\n")
    sizing = write(root / "sizing.tcl", "# sizing process boundary; topology unchanged\n")
    step_dir = PROGRAMS / "librelane_plugins/librelane_plugin_vibeic"
    script = step_dir / ("clock_path_drive_sizing.tcl" if entry == "sizing"
                         else "external_capture_launch_retap_step.tcl")
    output = root / "world.tsv"
    env = dict(os.environ, SCRIPTS_DIR=str(root), VIBEIC_CLKPATH_PRECTS_INSTANCES=str(root / "pre.txt"),
               VIBEIC_CLKPATH_SIZING_TCL=str(sizing), ENTRY=str(script), WORLD_OUT=str(output),
               LOADS=str(loads), DAMAGE=damage, RETAP=retap,
               PL_MAX_DISPLACEMENT_X="10", PL_MAX_DISPLACEMENT_Y="20")
    for key, value in zip(("PL_MAX_DISPLACEMENT_X", "PL_MAX_DISPLACEMENT_Y"), displacement):
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    if cap is None:
        env.pop("MAX_FANOUT_CONSTRAINT", None)
    else:
        env["MAX_FANOUT_CONSTRAINT"] = str(cap)
    harness = write(root / "run.tcl", _CTS_FANOUT_WORLD)
    proc = subprocess.run(["tclsh", str(harness)], text=True,
                          capture_output=True, env=env, timeout=15)
    write(root / "stdout.log", proc.stdout)
    write(root / "stderr.log", proc.stderr)
    put(root / "PROCESS.json", {"scope": "SOURCE_CONTROL", "argv": ["tclsh", str(harness)],
                                "rc": proc.returncode, "entry": entry, "cap": cap,
                                "loads": loads, "damage": damage, "retap": retap})
    lines = [x.split("|") for x in output.read_text().splitlines()] if output.exists() else []
    metrics = {x[1]: int(x[2]) for x in lines if x[0] == "metric"}
    nets = {x[1]: x[2].split(",") if x[2] else [] for x in lines if x[0] == "net"}
    instances = {x[1]: (x[2], x[3]) for x in lines if x[0] == "inst"}
    return SimpleNamespace(rc=proc.returncode, text=proc.stdout + proc.stderr,
                           metrics=metrics, nets=nets, instances=instances,
                           rows=lines, written=output.exists())


def _clock_fanout_gate(project, run, cap):
    _handoff(project, {c: 0.15 for c in CORNERS}, cap=cap, extra=run.metrics)
    return _gate("cts_quality_check", project)


@pytest.mark.parametrize("entry", ["sizing", "retap"])
@pytest.mark.parametrize("cap", [2, 3, 4])
def test_clock_fanout_actual_entry_closes_active_cap(tmp_path, entry, cap):
    run = _clock_fanout_entry(tmp_path, entry=entry, cap=cap)
    assert run.rc == 0 and run.written, run.text
    observed_max = run.metrics["vibeic__cts__max_fanout"]
    created = {x for x in run.instances if x == "root" or x.startswith(("leaf", "vic_cts_fanout_"))}
    graph_max = max(len(pins) - 1 for pins in run.nets.values()
                    if any(f"{x}/Z" in pins for x in created))
    assert observed_max == graph_max, {"metric": observed_max, "actual_graph_max": graph_max}
    all_pins = [p for pins in run.nets.values() for p in pins]
    assert len(all_pins) == len(set(all_pins)), "a terminal was duplicated across nets"
    assert {"n_input", "n_root", "n_data", *[f"n_leaf{i}" for i in range(16)]} <= run.nets.keys()
    actual_excess = max(0, observed_max - cap)
    assert actual_excess == 0, {"observed_max": observed_max, "cap": cap, "raw": run.text}
    assert observed_max <= cap, {"observed_max": observed_max, "cap": cap, "raw": run.text}
    rc, doc, text = _clock_fanout_gate(tmp_path / "project", run, cap)
    assert (rc, doc.get("verdict")) == (0, "PASS"), text
    assert run.nets["n_data"] == ["payload/Z", *[f"d{i}/I" for i in range(17)]]
    assert run.instances["spare"] == ("spare_role", "FIRM")
    assert all(run.instances[x][0] == "relay_role" for x in run.instances if x.startswith("vic_cts_fanout_"))
    # Every original register still traces through noninverting relays to the
    # same source. This checks actual connectivity, not a reported fanout token.
    driver = {n: [p for p in pins if p.endswith("/Z")][0] for n, pins in run.nets.items()
              if any(p.endswith("/Z") for p in pins)}
    pin_net = {p: n for n, pins in run.nets.items() for p in pins}
    for i in range(16):
        net = pin_net[f"r{i}/I"]
        seen = set()
        while driver[net] != "origin/Z":
            cell = driver[net].rsplit("/", 1)[0]
            assert cell not in seen and run.instances[cell][0] == "relay_role"
            seen.add(cell)
            net = pin_net[f"{cell}/I"]
    assert run.rows[-1][1].endswith("estimate,pg,write"), run.rows[-1]


@pytest.mark.parametrize("entry", ["sizing", "retap"])
@pytest.mark.parametrize("damage,reason", [
    ("no-role", "BUFFER_UNAVAILABLE"), ("inverter", "BUFFER_UNAVAILABLE"),
    ("dont-use", "BUFFER_UNAVAILABLE"), ("insert-error", "injected native insert error"),
    ("placement-error", "injected placement error"), ("illegal", "injected illegal placement"),
    ("port-load", "LOAD_UNSUPPORTED"), ("multi-driver", "DRIVER_UNSUPPORTED"),
])
def test_clock_fanout_unusable_native_state_refuses_without_views(tmp_path, entry, damage, reason):
    run = _clock_fanout_entry(tmp_path, entry=entry, damage=damage)
    observed = "VIC_CTS_FANOUT_REFUSED" if run.rc == 1 and not run.written else (
        f"rc={run.rc},written={run.written},max={run.metrics.get('vibeic__cts__max_fanout')}")
    assert observed == "VIC_CTS_FANOUT_REFUSED", {"actual_receiver_outcome": observed, "raw": run.text}
    assert reason in run.text, run.text


@pytest.mark.parametrize("cap", [0, 1])
def test_clock_fanout_impossible_cap_is_bounded_refusal(tmp_path, cap):
    run = _clock_fanout_entry(tmp_path, cap=cap)
    observed = "UNSPLITTABLE" if run.rc == 1 and not run.written else f"rc={run.rc},written={run.written}"
    assert observed == "UNSPLITTABLE", {"actual_receiver_outcome": observed, "raw": run.text}
    assert "CAP_UNSPLITTABLE" in run.text


@pytest.mark.parametrize("cap,loads", [(4, 4), (1, 1), (None, 16)])
def test_clock_fanout_valid_or_undeclared_population_is_unchanged(tmp_path, cap, loads):
    run = _clock_fanout_entry(tmp_path, cap=cap, loads=loads)
    assert run.rc == 0 and run.written, run.text
    assert run.metrics["vibeic__cts__max_fanout"] == loads
    assert not any(x.startswith("vic_cts_fanout_") for x in run.instances)


@pytest.mark.parametrize("retap,loads,marker", [("keep", 4, "VIC_RETAP keep"), ("rollback", 16, "VIC_RETAP reject")])
def test_clock_fanout_final_retap_branch_is_closed_before_census(tmp_path, retap, loads, marker):
    run = _clock_fanout_entry(tmp_path, entry="retap", retap=retap, loads=loads)
    assert run.rc == 0 and run.written, run.text
    assert marker in run.text, run.text
    actual_excess = max(0, run.metrics["vibeic__cts__max_fanout"] - 4)
    assert actual_excess == 0, {"actual_max": run.metrics, "raw": run.text}
    assert run.metrics["vibeic__cts__max_fanout"] <= 4, {"actual_max": run.metrics, "raw": run.text}
    rc, doc, text = _clock_fanout_gate(tmp_path / "project", run, 4)
    assert (rc, doc.get("verdict")) == (0, "PASS"), text


@pytest.mark.parametrize("entry", ["sizing", "retap"])
@pytest.mark.parametrize("displacement", [(None, None), ("10", None), (None, "20")])
def test_clock_fanout_entry_uses_native_default_without_complete_displacement_pair(
        tmp_path, entry, displacement):
    run = _clock_fanout_entry(tmp_path, entry=entry, displacement=displacement)
    actual_process_rc = run.rc
    assert actual_process_rc == 0, {"actual_rc": actual_process_rc, "raw": run.text}
    assert run.written, run.text
    actual_max = run.metrics["vibeic__cts__max_fanout"]
    assert actual_max == 4, {"actual_max": actual_max, "raw": run.text}
    rc, doc, text = _clock_fanout_gate(tmp_path / "project", run, 4)
    assert (rc, doc.get("verdict")) == (0, "PASS"), text

"""mig99: step 21 (global + detailed routing) on LibreLane.

The runner, the contract and the selection run for real. Only an EDA tool's
file writes are substituted, at the process edge (`_docker_exec`, the
contract's `run_chain` / `resolve_step_configs` / `state_from_direct`,
`flow_segment`'s docker call), and the plugin's `librelane` import.
"""
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / 'tests'))
contract = importlib.import_module('librelane_contract')
runner = importlib.import_module('phase3_one_shot_runner')
cts = importlib.import_module('librelane_cts_hold')
route = importlib.import_module('librelane_route')
from _stated_eda_image import state_the_image  # noqa: E402

CORNERS = ['nom_tt_025C_5v00', 'nom_ss_125C_4v50', 'nom_ff_n40C_5v50']
#: OpenROAD.GlobalRouting .. OpenROAD.FillInsertion as the 0.3.79 image's own
#: Chip flow orders it (`librelane_contract.flow_segment`, MEASURED).
IMAGE_SEGMENT = [
    'OpenROAD.GlobalRouting', 'OpenROAD.CheckAntennas', 'OpenROAD.RepairDesignPostGRT',
    'Odb.DiodesOnPorts', 'Odb.HeuristicDiodeInsertion', 'OpenROAD.RepairAntennas',
    'OpenROAD.ResizerTimingPostGRT', 'OpenROAD.STAMidPNR-3', 'OpenROAD.DetailedRouting',
    'Odb.RemoveRoutingObstructions', 'OpenROAD.CheckAntennas-1', 'Checker.TrDRC',
    'Odb.ReportDisconnectedPins', 'Checker.DisconnectedPins', 'Odb.ReportWireLength',
    'Checker.WireLength', 'OpenROAD.FillInsertion']


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
    state_the_image(monkeypatch)
    # These route tests exercise the selected image/source fields without a
    # live host launch. The actual host-CID authority contract is tested at
    # its own boundary; route fixtures must state their image identity.
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda image=None: {'image': image or 'img@sha256:x'})
    for name in ('VIBEIC_LIBRELANE_IMAGE', 'VIBEIC_LIBRELANE_PDK_ROOT'):
        monkeypatch.delenv(name, raising=False)


def _cmds(deck):
    return [ln.strip() for ln in deck.splitlines()
            if ln.strip() and not ln.lstrip().startswith('#')]


def _has(deck, command):
    import re
    pat = re.compile(r'^(?:if \{\[catch \{)?' + re.escape(command) + r'(?:\s|\}|$)')
    return any(pat.match(ln) for ln in _cmds(deck))


@pytest.fixture
def real_deck(tmp_path, monkeypatch):
    """pnr.tcl exactly as the runner's own builder emits it for a design."""
    import test_librelane_cts_hold as t98
    real_builder = runner._build_pnr_tcl_text
    kwargs = t98._drive_step_pnr(tmp_path / 'deck', monkeypatch, None)
    return real_builder(**kwargs)


# ------------------------------------------------------------ the real deck ---

def test_the_route_region_is_delimited_once_at_the_decks_top_level(real_deck):
    lines = real_deck.splitlines()
    begin = [i for i, ln in enumerate(lines) if ln.strip() == runner._PNR_ROUTE_BEGIN]
    end = [i for i, ln in enumerate(lines) if ln.strip() == runner._PNR_RESUME_ELIDE_END]
    assert len(begin) == 1 and len(end) == 1 and begin[0] < end[0]
    region = '\n'.join(lines[begin[0]:end[0]])
    assert _has(region, 'global_route') and 'detailed_route {*}$_vic_drc_opt' in region
    assert 'clock_tree_synthesis' not in region
    # after the CTS/hold region; the DRT-0305 PG-net cleanup opens it, before
    # the main global_route
    assert lines.index(runner._PNR_CTS_HOLD_END) < begin[0]
    first_route = next(i for i in range(begin[0], end[0]) if lines[i].startswith('global_route'))
    assert 'PG_CLEANUP_DONE' in '\n'.join(lines[begin[0]:first_route])
    assert cts.tcl_brace_depth(lines[:begin[0]]) == 0
    assert cts.tcl_brace_depth(lines[begin[0]:end[0] + 1]) == 0


def test_head_deck_stops_before_the_route_with_a_complete_checkpoint(real_deck):
    head = route.head_deck(runner, real_deck, odb_c='/w/pre.odb', def_c='/w/pre.def',
                           nl_c='/w/pre.v')
    assert _has(head, 'clock_tree_synthesis') and 'PG_CLEANUP_DONE' in head
    assert not _has(head, 'global_route') and not _has(head, 'detailed_route')
    tail = _cmds(head)[-5:]
    assert tail[:3] == ['write_db /w/pre.odb', 'write_def /w/pre.def', 'write_verilog /w/pre.v']
    assert tail[-1] == 'exit 0'


def test_bridge_deck_resumes_the_19_20_handoff_up_to_the_route(real_deck):
    bridge = route.bridge_deck(runner, real_deck, post_hold_odb_c='/o/post_hold.odb',
                               post_hold_def_c='/o/post_hold.def',
                               after_restore_tcl='# after restore\n',
                               odb_c='/w/pre.odb', def_c='/w/pre.def', nl_c='/w/pre.v')
    assert 'read_db /o/post_hold.odb' in bridge and '# after restore' in bridge
    assert not _has(bridge, 'clock_tree_synthesis') and not _has(bridge, 'global_placement')
    assert 'PG_CLEANUP_DONE' in bridge
    assert not _has(bridge, 'global_route') and not _has(bridge, 'detailed_route')
    assert 'write_db /w/pre.odb' in bridge and bridge.rstrip().endswith('exit 0')


def test_tail_deck_is_the_resume_deck_from_the_routed_odb(real_deck):
    tail = route.tail_deck(runner, real_deck, odb_c='/o/routed_preantenna.odb',
                           def_c='/o/routed_preantenna.def', after_restore_tcl='# ar\n')
    assert 'read_db /o/routed_preantenna.odb' in tail and '# ar' in tail
    assert runner._PNR_ROUTE_BEGIN not in tail and 'PG_CLEANUP_DONE' not in tail
    assert not _has(tail, 'clock_tree_synthesis')
    assert any(ln.startswith('write_def ') and ln.endswith('/routed.def')
               for ln in _cmds(tail))
    # byte-identical to the fatal-signal resume deck from the same checkpoint
    assert tail == runner._build_pnr_resume_tcl_text(
        real_deck, checkpoint_def_c='/o/routed_preantenna.def', after_restore_tcl='# ar\n',
        restore_odb_c='/o/routed_preantenna.odb')


def test_the_four_decks_are_valid_tcl(real_deck, tmp_path):
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('no tclsh on this host')
    ck = dict(odb_c='a', def_c='b', nl_c='c')
    decks = {
        'head': route.head_deck(runner, real_deck, **ck),
        'bridge': route.bridge_deck(runner, real_deck, post_hold_odb_c='x',
                                    post_hold_def_c='y', after_restore_tcl='', **ck),
        'tail': route.tail_deck(runner, real_deck, odb_c='a', def_c='b', after_restore_tcl=''),
        'arm': route.direct_arm_deck(runner, real_deck, pre_odb_c='a', pre_def_c='b',
                                     out_dir_c='/x', arm_c='/arm', after_restore_tcl='')}
    for name, deck in decks.items():
        script = write(tmp_path / f'{name}.tcl', deck)
        probe = write(tmp_path / f'{name}.probe.tcl',
                      f'set f [open {script}]; set t [read $f]; close $f\n'
                      'puts [info complete $t]\n')
        out = subprocess.run([tclsh, str(probe)], capture_output=True, text=True)
        assert out.stdout.strip() == '1', (name, out.stderr)


def test_direct_arm_runs_only_the_route_region_and_writes_only_into_its_arm(real_deck):
    out_dir_c = next(ln.split()[1].rsplit('/', 1)[0] for ln in real_deck.splitlines()
                     if ln.startswith('write_def ') and ln.endswith('/post_cts.def'))
    arm = route.direct_arm_deck(runner, real_deck, pre_odb_c='/w/pre.odb',
                                pre_def_c='/w/pre.def', out_dir_c=out_dir_c, arm_c='/arm',
                                after_restore_tcl='')
    assert 'read_db /w/pre.odb' in arm
    assert _has(arm, 'global_route') and 'detailed_route {*}$_vic_drc_opt' in arm
    assert not _has(arm, 'clock_tree_synthesis') and not _has(arm, 'repair_antennas')
    assert 'write_def /arm/routed_preantenna.def' in arm
    assert f'/arm/{runner.ROUTER_DRC_REPORT_NAME}' in arm
    writes = [ln for ln in _cmds(arm) if f'{out_dir_c}/' in ln and (
        ln.startswith(('write_', 'report_')) or '>' in ln or ' w]' in ln or ' a]' in ln)]
    assert writes == []
    assert _cmds(arm)[-4:] == ['write_db /arm/routed.odb', 'write_verilog /arm/routed.nl.v',
                               'puts "PNR_ROUTE_DIRECT_ARM: done"', 'exit 0']


# ------------------------------------------------------------- the switch ---

def test_switch_absent_or_for_other_steps_keeps_21_direct(tmp_path):
    assert route.modes(tmp_path) == {'21': 'direct'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'19': 'librelane', '20': 'librelane'}})
    assert route.modes(tmp_path) == {'21': 'direct'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'21': 'dual'}})
    assert route.modes(tmp_path) == {'21': 'dual'}


def test_a_ppa_candidate_sets_only_the_declared_route_knobs(tmp_path):
    put(tmp_path / 'phase3/librelane_switch.json',
        {'steps': {'21': 'librelane'}, 'route_knobs': {'GRT_ADJUSTMENT': 0.2,
                                                       'VIBEIC_DRT_OR_SEED': 7}})
    knobs = route.switch_knobs(tmp_path)
    assert knobs['GRT_ADJUSTMENT'][0] == 0.2 and knobs['VIBEIC_DRT_OR_SEED'][0] == 7
    assert all('route_knobs' in src for _, src in knobs.values())
    put(tmp_path / 'phase3/librelane_switch.json', {'route_knobs': {'FP_CORE_UTIL': 40}})
    with pytest.raises(ValueError, match='LL_ROUTE_KNOB_UNKNOWN'):
        route.switch_knobs(tmp_path)
    put(tmp_path / 'phase3/librelane_switch.json', {'route_seeds': [3, 3, 11]})
    assert route.seed_arms(tmp_path) == [3, 11]
    put(tmp_path / 'phase3/librelane_switch.json', {'route_seeds': ['3']})
    with pytest.raises(ValueError, match='LL_ROUTE_SEEDS_INVALID'):
        route.seed_arms(tmp_path)


def test_a_conflicting_ppa_timing_knob_refuses_without_weakening(tmp_path,
                                                                 monkeypatch):
    put(tmp_path / 'phase3/librelane_switch.json', {
        'route_knobs': {'RUN_POST_GRT_RESIZER_TIMING': False}})
    sdc = tmp_path / 'constraint.sdc'
    sdc.write_text('create_clock -period 10 clk\n')
    monkeypatch.setattr(cts, 'signoff_scene_sdc', lambda *args: sdc)
    with pytest.raises(ValueError, match='LL_STRICT_TIMING_OVERRIDE_FORBIDDEN'):
        route.overlay(runner, tmp_path, sdc, tmp_path / 'scratch')


def test_the_route_knobs_never_trip_the_19_20_knob_allow_list(tmp_path):
    put(tmp_path / 'phase3/librelane_switch.json',
        {'steps': {'19': 'librelane', '20': 'librelane', '21': 'librelane'},
         'route_knobs': {'DRT_OPT_ITERS': 20}})
    assert cts._switch_knobs(tmp_path) == {}


def test_the_chain_is_the_images_own_segment_with_the_reroute_after_the_route():
    def segment(image, first, last):
        assert (first, last) == route.SEGMENT
        return IMAGE_SEGMENT
    ids = route.chain_ids('img', flow_segment=segment)
    assert ids[0] == 'OpenROAD.GlobalRouting' and ids[-1] == 'OpenROAD.FillInsertion'
    assert 'OpenROAD.STAMidPNR' not in ids
    assert ids.count('OpenROAD.CheckAntennas') == 2
    assert ids[ids.index('OpenROAD.DetailedRouting') + 1] == route.NVR
    for step in ('OpenROAD.RepairAntennas', 'Checker.TrDRC', 'Checker.DisconnectedPins',
                 'Checker.WireLength'):
        assert step in ids
    seeded = route.chain_ids('img', seeded=True, flow_segment=segment)
    assert route.DRT_SEEDED in seeded and 'OpenROAD.DetailedRouting' not in seeded


def test_the_producer_call_site_takes_the_route_split_only_when_selected(tmp_path, monkeypatch):
    import test_librelane_cts_hold as t98
    seen = []

    def split(_runner, **kwargs):
        seen.append(kwargs)
        return 1, 'stopped by test', ''

    monkeypatch.setattr(route, 'execute', split)
    t98._drive_step_pnr(tmp_path / 'direct', monkeypatch, None, stop_at_builder=False, calls=[])
    t98._drive_step_pnr(tmp_path / 'cts', monkeypatch, {'19': 'librelane', '20': 'librelane'},
                        stop_at_builder=False, calls=[], declared=True)
    assert seen == []
    calls = []
    t98._drive_step_pnr(tmp_path / 'r', monkeypatch, {'21': 'librelane'},
                        stop_at_builder=False, calls=calls)
    assert seen and seen[0]['mode'] == 'librelane' and seen[0]['cts_hold'] is None
    assert not any('/pnr.tcl ' in cmd for _, cmd in calls)
    t98._drive_step_pnr(tmp_path / 'chain', monkeypatch,
                        {'19': 'librelane', '20': 'librelane', '21': 'dual'},
                        stop_at_builder=False, calls=[], declared=True)
    bound = seen[-1]['cts_hold']
    assert seen[-1]['mode'] == 'dual'
    assert bound.func is cts.execute
    assert bound.keywords['modes'] == {'19': 'librelane', '20': 'librelane'}


def test_an_unknown_route_knob_refuses_before_any_session(tmp_path, monkeypatch):
    import test_librelane_cts_hold as t98
    calls = []
    real_put = t98.put
    monkeypatch.setattr(t98, 'put', lambda p, o: real_put(
        p, dict(o, route_knobs={'NOT_A_KNOB': 1}) if p.name == 'librelane_switch.json' else o))
    result = t98._drive_step_pnr(tmp_path, monkeypatch, {'21': 'librelane'},
                                 stop_at_builder=False, calls=calls)
    assert result.status == 'FAIL' and 'LL_ROUTE_KNOB_UNKNOWN' in result.detail
    assert not any('pnr.tcl' in cmd for _, cmd in calls)


# ------------------------------------------------- the split, end to end ---

ROUTER_LOG = ('OpenROAD v2.0-26Q3\n[INFO DRT-0195] Start detail routing.\n'
              '[INFO DRT-0199]   Number of violations = {v}.\n'
              '[INFO DRT-0198] Complete detail routing.\n'
              '[INFO DRT-0702] Post-route verification: {v} violation(s).\n'
              'Total wire length = {wl} um.\nTotal number of vias = {vias}.\n')


def _fake_tools(project, *, route_ll=None, seed_ll=None, fail_step=None):
    """What LibreLane writes for each step, at the run_chain edge."""
    route_ll = route_ll or {'v': 0, 'wl': 1000.0, 'vias': 300, 'ant': 0, 'wns': 2.0, 'tns': 0.0}
    seen = {'chains': []}

    def chain(proj, image, triples, **kwargs):
        lane = kwargs.get('lane', 'x')
        seen['chains'].append((lane, [s for s, _, _ in triples], [c for _, c, _ in triples]))
        seen.setdefault('mounts', []).append((lane, kwargs.get('mounts')))
        base = proj / 'phase3/librelane' / lane
        folders, metrics = [], {}
        arm = route_ll
        if 'seed' in lane and seed_ll:
            arm = seed_ll
        if lane.startswith('21-route-direct-measure'):
            arm = seen['direct']
        for i, (step, cfg, first_state) in enumerate(triples, 1):
            folder = base / f'{i:02d}-{step.lower().replace(".", "-")}'
            if step == fail_step:
                raise contract.Refusal('LL_STEP_FAILED', step)
            views = {k: write(folder / f'chip_top.{k}', f'{lane} {step} {k}\n')
                     for k in ('odb', 'def', 'nl')}
            if step in (route.DRT, route.DRT_SEEDED):
                write(folder / 'openroad-detailedrouting.log', ROUTER_LOG.format(**arm))
                metrics['route__drc_errors'] = arm['v']
                write(folder / 'drt-run-0/chip_top.drc', 'violation type: Short\n' * 4)
                write(folder / 'drt-run-1/chip_top.drc', 'violation type: Short\n' * arm['v'])
                write(folder / 'chip_top.drc', 'violation type: Short\n' * arm['v'])
            if step == route.NVR:
                doc = json.loads(cfg.read_text())
                seen.setdefault('nvr', []).append(doc)
                write(folder / 'named_viol_after.drc', 'violation type: Short\n' * arm['v'])
                write(folder / 'openroad-namedviolationreroute.log',
                      '[INFO ORD-0030] NAMED_VIOL_REROUTE_CLEAN: pass 1\n')
            if step == 'OpenROAD.GlobalRouting':
                write(folder / 'openroad-globalrouting.log',
                      '[WARNING GRT-0273] Clock net clk has no NDR.\n')
            if step == 'OpenROAD.CheckAntennas':
                metrics['antenna__violating__nets'] = arm['ant']
            if step == 'OpenROAD.STAMidPNR':
                corner = json.loads(cfg.read_text())['PNR_CORNERS'][0]
                metrics[f'timing__setup__ws__corner:{corner}'] = arm['wns']
                metrics[f'timing__setup__tns__corner:{corner}'] = arm['tns']
            if step.startswith(('Checker.', 'OpenROAD.STAMidPNR', 'OpenROAD.CheckAntennas')):
                views = {}
            prev = (folders[-1] / 'state_out.json') if folders else first_state
            state = {k: str(v) for k, v in views.items()} or {
                k: v for k, v in json.loads(prev.read_text()).items() if k != 'metrics'}
            put(folder / 'state_out.json', dict(state, metrics=dict(metrics)))
            folders.append(folder)
        return folders

    def resolve(proj, image, pdk, step_ids, **kwargs):
        seen['overlay'] = kwargs.get('overlay')
        seen['resolved'] = list(step_ids)
        root = proj / 'phase3/librelane' / kwargs['folder']
        out = {}
        for step in step_ids:
            out[step] = put(root / f'{step}.json', {'meta': {'step': step},
                                                   'STA_CORNERS': CORNERS, 'PNR_CORNERS': None,
                                                   'DESIGN_NAME': 'chip_top'})
            put(root / f'{step}.views.json', {'inputs': ['odb'], 'outputs': []})
        # the flow's own gates, as the image resolves them for spm (MEASURED)
        put(root / 'flow_gates.json', {
            'OpenROAD.RepairDesignPostGRT': {'RUN_POST_GRT_DESIGN_REPAIR': False},
            'Odb.HeuristicDiodeInsertion': {'RUN_HEURISTIC_DIODE_INSERTION': False},
            'OpenROAD.RepairAntennas': {'RUN_ANTENNA_REPAIR': True},
            'OpenROAD.ResizerTimingPostGRT': {'RUN_POST_GRT_RESIZER_TIMING': False},
            'OpenROAD.DetailedRouting': {'RUN_DRT': True}})
        return out

    return chain, resolve, seen


def _route_project(tmp_path, switch):
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
            f'puts "PNR_STAGE: global_route"\n{runner._PNR_ROUTE_BEGIN}\npg_cleanup\n'
            f'global_route\ndetailed_route -output_drc {out_dir}/{runner.ROUTER_DRC_REPORT_NAME}\n'
            f'write_def {out_dir}/routed_preantenna.def\n'
            f'{runner._PNR_RESUME_ELIDE_END}\nrepair_antennas\n'
            f'write_def {out_dir}/routed.def\n')
    pnr_tcl = write(out_dir / 'pnr.tcl', deck)
    return project, out_dir, pnr_tcl


def _run(tmp_path, monkeypatch, *, switch=None, route_ll=None, direct=None, seed_ll=None,
         fail_step=None, cts_hold=None):
    switch = switch or {'steps': {'21': 'librelane'}}
    project, out_dir, pnr_tcl = _route_project(tmp_path, switch)
    chain, resolve, seen = _fake_tools(project, route_ll=route_ll, seed_ll=seed_ll,
                                       fail_step=fail_step)
    seen['direct'] = direct or {'v': 0, 'wl': 1000.0, 'vias': 300, 'ant': 0, 'wns': 2.0,
                                'tns': 0.0}
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(contract, 'flow_segment', lambda image, a, b: IMAGE_SEGMENT)
    monkeypatch.setattr(contract, 'state_from_direct', lambda p, i, cfg, views, out, **k: (
        seen.setdefault('bridged', []).append({v: str(x) for v, x in views.items()})
        or put(out / 'state_in.json', {'odb': str(views['odb'])})))
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '# after restore\n')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    execs = []

    def docker(container, cmd, *a, **k):
        execs.append(cmd)
        if 'pnr_route_head.tcl' in cmd:
            for ext in ('odb', 'def', 'nl.v'):
                write(out_dir / f'route_split/pre_route.{ext}', f'pre {ext}\n')
            return 0, 'head ok', ''
        if 'pnr_route_direct_arm.tcl' in cmd:
            arm = project / 'phase3/tool_arms/21/openroad'
            for name in ('routed.odb', 'routed_preantenna.def', 'routed.nl.v'):
                write(arm / name, f'direct arm {name}\n')
            write(arm / runner.ROUTER_DRC_REPORT_NAME,
                  'violation type: Short\n' * seen['direct']['v'])
            write(arm / 'openroad.log', ROUTER_LOG.format(**seen['direct']))
            return 0, 'arm ok', ''
        return 0, 'tail ok', ''

    monkeypatch.setattr(runner, '_docker_exec', docker)
    cmd = (f'openroad -no_init -exit -metrics {out_dir}/openroad.metrics.json '
           f'{pnr_tcl} 2>&1 | tee {out_dir}/openroad.log')
    rc, out, err = route.execute(
        runner, project=project, pdk=SimpleNamespace(name='pdkX'), container='c',
        out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl,
        mode=route.modes(project)['21'], cmd=cmd, spare_plan=None, exec_kwargs={},
        cts_hold=cts_hold)
    return SimpleNamespace(rc=rc, out=out, project=project, out_dir=out_dir, seen=seen,
                           execs=execs)


def test_librelane_route_reaches_the_paths_the_post_route_tail_reads(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    assert run.rc == 0, run.out
    lane, steps, configs = run.seen['chains'][0]
    assert lane == '21-route'
    # the flow's own gates hold: a step the Chip flow skips is not run
    assert steps == ['OpenROAD.GlobalRouting', 'OpenROAD.CheckAntennas', 'Odb.DiodesOnPorts',
                     'OpenROAD.RepairAntennas', 'OpenROAD.DetailedRouting', route.NVR,
                     'Odb.RemoveRoutingObstructions', 'OpenROAD.CheckAntennas',
                     'Checker.TrDRC', 'Odb.ReportDisconnectedPins', 'Checker.DisconnectedPins',
                     'Odb.ReportWireLength', 'Checker.WireLength', 'OpenROAD.FillInsertion']
    # head, then the tail appended to the same log; the unsplit deck never runs
    assert len(run.execs) == 2 and 'pnr_route_head.tcl' in run.execs[0]
    assert 'pnr_route_tail.tcl' in run.execs[1] and 'tee -a' in run.execs[1]
    assert not any('/pnr.tcl ' in c for c in run.execs)
    tail = (run.out_dir / 'pnr_route_tail.tcl').read_text()
    assert f'read_db {run.out_dir}/routed_preantenna.odb' in tail
    assert 'repair_antennas' in tail and 'global_route' not in tail
    # the preroute_fill stage's PG re-connect + ownership audit, on the tool's
    # filled database, with no re-route, before any post-route stage
    audit = tail.index('PG_NET_OWNERSHIP_AUDIT')
    assert tail.index('read_db') < audit < tail.index('repair_antennas')
    assert 'PG_RECONNECT_DONE' in tail and not _has(tail, 'detailed_route')
    base = run.project / 'phase3/librelane/21-route'
    fill = base / f'{len(steps):02d}-openroad-fillinsertion'
    assert (run.out_dir / 'routed_preantenna.odb').read_text() == \
        (fill / 'chip_top.odb').read_text()
    assert (run.out_dir / 'routed_preantenna.def').read_text() == \
        (fill / 'chip_top.def').read_text()
    nvr_folder = base / f'{steps.index(route.NVR) + 1:02d}-vibeic-namedviolationreroute'
    assert (run.out_dir / runner.ROUTER_DRC_REPORT_NAME).read_text() == \
        (nvr_folder / 'named_viol_after.drc').read_text()
    receipt = json.loads((run.project / 'reports/phase3/librelane_route_handoff.json').read_text())
    for view in receipt['views'].values():
        assert contract.digest(run.project / view['dest']) == view['dest_sha256']
    assert receipt['selected'] == 'librelane'
    assert receipt['flow_gated_off']['Odb.HeuristicDiodeInsertion'] == \
        ['RUN_HEURISTIC_DIODE_INSERTION']
    # the router's own per-run reports, each read on its own (review70 correction)
    assert [r['markers'] for r in receipt['arms']['librelane']['drt_runs']] == [4, 0]
    log = (run.out_dir / 'openroad.log').read_text()
    assert 'PNR_STAGE: global_route' in log and 'PNR_STAGE: detailed_route' in log
    assert 'GRT-0273' in log and 'DRT-0199' in log
    assert 'PNR_ROUTE_HANDOFF: selected=librelane' in log


def test_route_mounts_the_resolved_whole_pdk_root_for_its_pdk_root_cli(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    assert run.rc == 0, run.out
    lane, mounts = run.seen['mounts'][0]
    assert lane == '21-route'
    assert len(mounts) == 1
    host_root, cli_root = mounts[0]
    assert host_root.resolve() == (tmp_path / 'pdkroot').resolve()
    assert cli_root == contract.PDK_GUEST_ROOT


def test_librelane_handoff_mints_receipt_from_selected_drt(tmp_path, monkeypatch):
    """The selected tool step supplies the invocation evidence to step_pnr.

    On the original branch, the on-disk log contains DRT-0702 but execute's
    return contains only head/tail text, so the writer refuses the receipt.
    """
    run = _run(tmp_path, monkeypatch, route_ll=GOOD)
    assert run.rc == 0
    drt = run.project / 'phase3/librelane/21-route/05-openroad-detailedrouting'
    state = json.loads((drt / 'state_out.json').read_text())
    assert state['metrics']['route__drc_errors'] == 0
    assert 'DRT-0702] Post-route verification: 0 violation(s).' in run.out
    assert (run.out_dir / runner.ROUTER_DRC_REPORT_NAME).stat().st_size == 0
    routed_def = write(run.out_dir / 'routed.def', 'VERSION 5.8 ;\nDESIGN widget ;\nEND DESIGN\n')
    receipt = runner._write_router_drc_receipt(run.out_dir, routed_def, run.out)
    assert receipt is not None and receipt.is_file()
    doc = json.loads(receipt.read_text())
    assert doc['schema'] == 'vibeic.router_drc_receipt.v1'
    assert doc['final_drt_count'] == doc['current_invocation_count'] == 0
    from eda_report_audit import _empty_router_drc_receipt
    assert _empty_router_drc_receipt(run.out_dir / runner.ROUTER_DRC_REPORT_NAME) == receipt


def test_the_reroute_step_gets_the_runners_one_reroute_pass_and_the_routers_report(
        tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    doc = run.seen['nvr'][0]
    assert Path(doc['VIBEIC_NVR_TCL']).read_text() == runner._named_violation_reroute_tcl(
        doc['VIBEIC_NVR_REPORT_PATH'])
    steps = run.seen['chains'][0][1]
    drt = f'{steps.index(route.DRT) + 1:02d}-openroad-detailedrouting'
    assert doc['VIBEIC_NVR_DRC_REPORT'].endswith(f'21-route/{drt}/chip_top.drc')
    assert doc['VIBEIC_NVR_REPORT_PATH'].endswith(
        f'21-config/nvr/21-route/{runner.ROUTER_DRC_REPORT_NAME}')


def test_the_route_repairs_in_the_signoff_scene_and_the_checkers_only_record(
        tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    ov = run.seen['overlay']
    scene = Path(ov['PNR_SDC_FILE'][0]).read_text()
    assert scene.startswith('create_clock -period 24 clk\n')
    assert f'set_timing_derate -late {runner._FLAT_OCV_DERATE_LATE}' in scene
    for key in ('ERROR_ON_TR_DRC', 'ERROR_ON_DISCONNECTED_PINS', 'ERROR_ON_LONG_WIRE'):
        assert ov[key][0] is False and ov[key][1]


def test_the_route_declares_the_post_grt_design_repair_the_drv_standard_requires(
        tmp_path, monkeypatch):
    """R-0929-POSTGRT: LibreLane gates RepairDesignPostGRT off by default; the
    step-21 overlay switches the design (DRV) repair on, with its source, and
    also enables the strict native timing repair required by the ordinary
    backend."""
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    run = _run(tmp_path, monkeypatch)
    ov = run.seen['overlay']
    assert ov['RUN_POST_GRT_DESIGN_REPAIR'][0] is True
    assert 'R-0929-POSTGRT' in ov['RUN_POST_GRT_DESIGN_REPAIR'][1]
    assert ov['RUN_POST_GRT_RESIZER_TIMING'][0] is True
    for key in ('TIMING_VIOLATION_CORNERS', 'SETUP_VIOLATION_CORNERS',
                'HOLD_VIOLATION_CORNERS'):
        assert ov[key][0] == ['*'] and ov[key][1]


def test_a_missing_pdk_root_refuses_and_never_resumes(tmp_path, monkeypatch):
    project, out_dir, pnr_tcl = _route_project(tmp_path, {'steps': {'21': 'librelane'}})
    put(project / 'phase3/librelane_switch.json', {'steps': {'21': 'librelane'}})
    execs = []

    def docker(container, cmd, *a, **k):
        execs.append(cmd)
        for ext in ('odb', 'def', 'nl.v'):
            write(out_dir / f'route_split/pre_route.{ext}', 'x\n')
        return 0, '', ''

    monkeypatch.setattr(runner, '_docker_exec', docker)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    monkeypatch.setattr(contract, 'resolve_pdk_root', lambda *a, **k: None)
    rc, out, _ = route.execute(
        runner, project=project, pdk=SimpleNamespace(name='pdkX'), container='c',
        out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl, mode='librelane',
        cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None,
        exec_kwargs={})
    assert rc != 0 and 'LL_PDK_ROOT_NOT_DECLARED' in out
    assert len(execs) == 1 and not (out_dir / 'routed_preantenna.odb').exists()


def test_a_failing_tool_step_refuses_by_name_and_never_resumes(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, fail_step='OpenROAD.DetailedRouting')
    assert run.rc != 0 and 'LL_STEP_FAILED' in run.out
    assert len(run.execs) == 1 and not (run.out_dir / 'routed_preantenna.odb').exists()


def test_chained_behind_19_20_the_route_starts_from_their_handoff(tmp_path, monkeypatch):
    handed = {}

    def cts_hold(after_handoff):
        # what librelane_cts_hold.execute does once its views are handed over
        handed['called'] = True
        return after_handoff('/o/post_hold.odb', '/o/post_hold.def', '# cts after\n',
                             'cts out', '')

    run = _run(tmp_path, monkeypatch, cts_hold=cts_hold)
    assert handed and run.rc == 0, run.out
    head = (run.out_dir / 'pnr_route_head.tcl').read_text()
    assert 'read_db /o/post_hold.odb' in head and '# cts after' in head
    assert 'clock_tree_synthesis' not in head and 'pg_cleanup' in head
    assert 'global_route' not in head.split(runner._PNR_STAGE_MARKER + ' route_checkpoint')[0] \
        .split('pg_cleanup')[1]
    assert 'tee -a' in run.execs[0] and 'pnr_route_tail.tcl' in run.execs[1]


def test_cts_hold_hands_over_to_the_route_instead_of_resuming_the_deck(tmp_path, monkeypatch):
    import test_librelane_cts_hold as t98
    got = {}

    def after(odb_c, def_c, after_restore, out, err):
        got.update(odb=odb_c, deff=def_c, after=after_restore)
        return 0, out + 'routed', err

    real = cts.execute
    monkeypatch.setattr(cts, 'execute', lambda R, **kw: real(R, **kw, after_handoff=after))
    run = t98._run_split(tmp_path, monkeypatch)
    assert run.rc == 0 and run.out.endswith('routed')
    assert got['odb'].endswith('/post_hold.odb') and got['deff'].endswith('/post_hold.def')
    # the 19/20 tail deck never ran: the route owns what comes after the handoff
    assert len(run.execs) == 1 and 'pnr_cts_head.tcl' in run.execs[0]
    assert (run.out_dir / 'post_hold.odb').is_file()


GOOD = {'v': 0, 'wl': 1000.0, 'vias': 300, 'ant': 0, 'wns': 2.0, 'tns': 0.0}


def test_dual_measures_every_arm_by_one_instrument_and_hands_over_the_winner(
        tmp_path, monkeypatch):
    worse = dict(GOOD, wl=1200.0, vias=350)
    run = _run(tmp_path, monkeypatch, switch={'steps': {'21': 'dual'}},
               route_ll=GOOD, direct=worse)
    assert run.rc == 0, run.out
    root = run.project / 'phase3/tool_arms/21'
    selection = json.loads((root / 'selection.json').read_text())
    assert selection['selection'] == 'librelane'
    lanes = [lane for lane, _, _ in run.seen['chains']]
    assert '21-route-measure' in lanes and '21-route-direct-measure' in lanes
    measure = {lane: steps for lane, steps, _ in run.seen['chains'] if 'measure' in lane}
    assert measure['21-route-measure'] == measure['21-route-direct-measure'] == \
        ['OpenROAD.CheckAntennas'] + ['OpenROAD.STAMidPNR'] * len(CORNERS)
    for arm in ('librelane', 'openroad_judge'):
        gate = json.loads((root / arm / 'gate.json').read_text())
        assert gate['verdict'] == 'PASS'
        assert set(gate['metrics']) == {k for k, _ in route.OBJECTIVES}
    # and the other way round: the direct arm wins and ITS views are handed over
    run2 = _run(tmp_path / 'b', monkeypatch, switch={'steps': {'21': 'dual'}},
                route_ll=worse, direct=GOOD)
    assert run2.rc == 0
    assert (run2.out_dir / 'routed_preantenna.odb').read_text() == 'direct arm routed.odb\n'
    receipt = json.loads((run2.project / 'reports/phase3/librelane_route_handoff.json').read_text())
    assert receipt['selected'] == 'openroad'
    assert 'DIRECT ROUTE ARM' in (run2.out_dir / 'openroad.log').read_text()


def test_a_router_drc_residual_or_an_antenna_net_loses_to_a_clean_arm(tmp_path, monkeypatch):
    dirty = dict(GOOD, v=1, wl=800.0, vias=200, wns=3.0)
    run = _run(tmp_path, monkeypatch, switch={'steps': {'21': 'dual'}},
               route_ll=dirty, direct=GOOD)
    selection = json.loads((run.project / 'phase3/tool_arms/21/selection.json').read_text())
    assert selection['selection'] == 'openroad' and selection['feasible'] == ['openroad']
    antenna = dict(GOOD, ant=2, wl=800.0)
    run2 = _run(tmp_path / 'b', monkeypatch, switch={'steps': {'21': 'dual'}},
                route_ll=antenna, direct=GOOD)
    selection = json.loads((run2.project / 'phase3/tool_arms/21/selection.json').read_text())
    assert selection['selection'] == 'openroad'


def test_a_declared_seed_is_one_more_arm_through_the_seeded_router(tmp_path, monkeypatch):
    seed_better = dict(GOOD, wl=900.0, vias=290)
    run = _run(tmp_path, monkeypatch,
               switch={'steps': {'21': 'dual'}, 'route_seeds': [7]},
               route_ll=GOOD, seed_ll=seed_better, direct=dict(GOOD, wl=1100.0))
    assert run.rc == 0, run.out
    seeded = [(lane, steps, cfgs) for lane, steps, cfgs in run.seen['chains']
              if lane == '21-route-seed7']
    assert seeded and route.DRT_SEEDED in seeded[0][1]
    cfg = seeded[0][2][seeded[0][1].index(route.DRT_SEEDED)]
    assert json.loads(cfg.read_text())['VIBEIC_DRT_OR_SEED'] == 7
    prov = json.loads(cfg.with_suffix('.provenance.json').read_text())
    assert 'route_seeds' in prov['keys']['VIBEIC_DRT_OR_SEED']
    selection = json.loads((run.project / 'phase3/tool_arms/21/selection.json').read_text())
    assert selection['selection'] == 'librelane_seed7'
    assert (run.out_dir / 'routed_preantenna.odb').read_text().startswith('21-route-seed7 ')


def test_a_pareto_tie_is_broken_in_the_reviews_order(tmp_path):
    gates = {}
    for name, (wl, wns) in {'a': (1000.0, 1.0), 'b': (1100.0, 2.0)}.items():
        gates[name] = put(tmp_path / f'{name}.json', {
            'verdict': 'PASS', 'scope': {'s': 1},
            'metrics': {k: {'status': 'MEASURED', 'value': v} for k, v in {
                'vibeic__route__drc_errors': 0, 'vibeic__antenna__violating_nets': 0,
                'vibeic__route__wirelength_um': wl, 'vibeic__route__vias': 10,
                'vibeic__setup__ws__worst_corner': wns,
                'vibeic__setup__tns__worst_corner': 0.0}.items()}})
    out = route.select(gates, tmp_path / 'sel.json', write=lambda p, t: p.write_text(t))
    assert out['reason'] == 'LL_PARETO_TIE' and out['selection'] == 'a'
    assert 'wirelength' in out['tie_break']


def test_drt_runs_are_read_per_run_not_from_the_mixed_state(tmp_path):
    drt = tmp_path / 'drt'
    write(drt / 'drt-run-0/chip_top.drc', 'violation type: Short\n' * 2)
    write(drt / 'drt-run-2/chip_top.drc', '')
    write(drt / 'drt-run-10/chip_top.drc', 'violation type: Cut Spacing\n')
    runs = route.drt_runs(drt)
    assert [(r['run'], r['markers']) for r in runs] == [
        ('drt-run-0', 2), ('drt-run-2', 0), ('drt-run-10', 1)]


# ------------------------------------------------------- the plugin steps ---

def _load_plugin_routing(monkeypatch):
    """`librelane_plugin_vibeic/routing.py` with LibreLane's classes stubbed
    (the image, not this host, has LibreLane)."""
    class _Registry:
        def register(self):
            return lambda cls: cls

    class Step:
        factory = _Registry()

    class OpenROADStep(Step):
        config_vars = []

        def get_script_path(self):
            return self._stock

        def run(self, state_in, **kwargs):
            self.ran = True
            with open(self.config['VIBEIC_NVR_REPORT_PATH'], 'w') as fh:
                fh.write(self._after)
            return {}, {}

    class DetailedRouting(OpenROADStep):
        pass

    class StepError(RuntimeError):
        pass

    mods = {'librelane': types.ModuleType('librelane'),
            'librelane.common': types.ModuleType('librelane.common'),
            'librelane.config': types.ModuleType('librelane.config'),
            'librelane.state': types.ModuleType('librelane.state'),
            'librelane.steps': types.ModuleType('librelane.steps'),
            'librelane.steps.openroad': types.ModuleType('librelane.steps.openroad'),
            'librelane.steps.step': types.ModuleType('librelane.steps.step')}
    mods['librelane.common'].Path = str
    mods['librelane.config'].Variable = lambda *a, **k: (a, k)
    mods['librelane.state'].State = dict
    mods['librelane.steps.openroad'].DetailedRouting = DetailedRouting
    mods['librelane.steps.openroad'].OpenROADStep = OpenROADStep
    for name in ('MetricsUpdate', 'ViewsUpdate'):
        setattr(mods['librelane.steps.step'], name, dict)
    mods['librelane.steps.step'].Step = Step
    mods['librelane.steps.step'].StepError = StepError
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    path = contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / 'routing.py'
    spec = importlib.util.spec_from_file_location('mig99_plugin_routing', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, StepError


#: The seed line of the 0.3.79 image's librelane/scripts/openroad/drt.tcl
#: (MEASURED, lines 87-91).
STOCK_DRT = ('set drt_args [list]\n'
             'lappend drt_args -droute_end_iter $::env(DRT_OPT_ITERS)\n'
             'lappend drt_args -or_seed 42\n'
             'lappend drt_args -verbose 1\n'
             'drt_run $i {*}$drt_args\n')


def test_the_seeded_router_changes_exactly_the_seed_line(tmp_path, monkeypatch):
    plugin, StepError = _load_plugin_routing(monkeypatch)
    out = plugin.seeded_script(STOCK_DRT)
    assert out == STOCK_DRT.replace('-or_seed 42', '-or_seed $::env(VIBEIC_DRT_OR_SEED)')
    for bad in (STOCK_DRT.replace('-or_seed 42', '-or_seed 7'), STOCK_DRT + STOCK_DRT):
        with pytest.raises(ValueError, match='seed cannot be located'):
            plugin.seeded_script(bad)
    step = plugin.DetailedRoutingSeeded()
    step._stock = str(write(tmp_path / 'drt.tcl', STOCK_DRT))
    step.step_dir = str(tmp_path / 'step')
    Path(step.step_dir).mkdir()
    assert Path(step.get_script_path()).read_text() == out
    step._stock = str(write(tmp_path / 'other.tcl', 'detailed_route\n'))
    with pytest.raises(StepError):
        step.get_script_path()


def test_the_reroute_step_records_the_routers_count_before_and_after(tmp_path, monkeypatch):
    plugin, _ = _load_plugin_routing(monkeypatch)
    step = plugin.NamedViolationReroute()
    step.step_dir = str(tmp_path / 'step')
    Path(step.step_dir).mkdir()
    step._after = 'violation type: Short\n'
    step.config = {'VIBEIC_NVR_DRC_REPORT': str(write(tmp_path / 'drt.drc',
                                                      'violation type: Short\n' * 3)),
                   'VIBEIC_NVR_REPORT_PATH': str(tmp_path / 'work/routed_router.drc.rpt')}
    _, metrics = step.run({})
    assert metrics == {'vibeic__route__named_reroute__markers_before': 3,
                       'vibeic__route__named_reroute__markers_after': 1}
    assert (Path(step.step_dir) / 'named_viol_after.drc').read_text() == step._after
    tcl = (contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / 'named_violation_reroute.tcl')
    assert 'source $::env(VIBEIC_NVR_TCL)' in tcl.read_text()
    assert not _has(tcl.read_text(), 'detailed_route')   # the pass lives in the runner only


def test_every_plugin_step_stays_registered():
    init = (contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / '__init__.py').read_text()
    for name in ('InsertSpareCells', 'GateLevelSim', 'ClockPathDriveSizing', 'IRDropChecker',
                 'TransientIR', 'DetailedRoutingSeeded', 'NamedViolationReroute'):
        assert f'"{name}"' in init


def test_the_flow_gates_are_read_from_the_resolved_config_and_required(tmp_path):
    put(tmp_path / 'flow_gates.json', {'A.x': {'RUN_A': False, 'RUN_B': True},
                                       'B.y': {'RUN_B': True}})
    assert contract.flow_gated_off(tmp_path) == {'A.x': ['RUN_A']}
    with pytest.raises(contract.Refusal, match='LL_FLOW_GATES_UNRESOLVED'):
        contract.flow_gated_off(tmp_path / 'absent')
    ids = route.chain_ids('img', flow_segment=lambda *a: IMAGE_SEGMENT,
                          gated_off={'Odb.HeuristicDiodeInsertion': ['RUN_HEURISTIC_DIODE_INSERTION']})
    assert 'Odb.HeuristicDiodeInsertion' not in ids and 'OpenROAD.DetailedRouting' in ids
    with pytest.raises(ValueError, match='NO_DETAILED_ROUTE'):
        route.chain_ids('img', flow_segment=lambda *a: IMAGE_SEGMENT,
                        gated_off={'OpenROAD.DetailedRouting': ['RUN_DRT']})


def test_the_resolver_writes_the_flows_own_gates():
    src = Path(contract.__file__).read_text()
    assert 'getattr(Chip, "gating_config_vars", {})' in src
    assert '"flow_gates.json"' in src

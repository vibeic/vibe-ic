"""T96: step 15 / 15.5ic on the tool -- the gates the cut-over keeps.

review70 step 15 harvest 2 (deck distance + tap coverage, as a gate on the
tool's output) and harvest 4 (the unplaceable-master cap, as EXTRA_EXCLUDED_CELLS
derived from the tool's own tap lattice), and their wiring into the LibreLane
floorplan producer and the end of step_pnr.

The DEFs are real OpenROAD output (calibration/tap_coverage_*.def: one
calibration structure tapped at two distances, provenance in
instrument_calibration.py); the programs, the runner helpers and the contract
run for real. Only the container and LibreLane's chain are substituted at the
edge, and the chain writes the real calibration DEF as its TapEndcapInsertion
output.
"""
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
runner = importlib.import_module('phase3_one_shot_runner')
T = importlib.import_module('tap_row_coverage_check')
from _stated_eda_image import state_the_image  # noqa: E402
import test_librelane_state_bridge as bridge  # noqa: E402  (T89 fixtures)
import test_mig97_placement_spares as mig97  # noqa: E402  (T97 deck)

put, write = bridge.put, bridge.write
CAL = PROGRAMS / 'calibration'
LEF = CAL / 'tap_coverage_cells.lef'
COVERED = CAL / 'tap_coverage_covered_negative.def'     # tapcell -distance 20
GAP = CAL / 'tap_coverage_gap_positive.def'             # tapcell -distance 40
TAP = 'gf180mcu_fd_sc_mcu7t5v0__filltie'
ENDCAP = 'gf180mcu_fd_sc_mcu7t5v0__endcap'
DECK = (15.0, 'libs.tech/klayout/tech/drc/rule_decks/comp.rb: DF.13_MV/DF.14_MV')


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(contract, '_CAPABILITY', {}, raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    state_the_image(monkeypatch)


def _cli(tmp_path, def_path, *extra, lef=LEF):
    out = tmp_path / 'r.json'
    rc = T.main([str(tmp_path), '--def', str(def_path), '--lef', str(lef),
                 '--tap-master', TAP, '--endcap-master', ENDCAP,
                 '--distance-um', str(DECK[0]), '--distance-source', DECK[1],
                 '--json', str(out), *extra])
    return rc, json.loads(out.read_text())


# ============================================================= the gate ====

def test_the_real_tool_pair_is_judged_by_its_well_islands(tmp_path):
    rc, rep = _cli(tmp_path, COVERED)
    assert (rc, rep['verdict']) == (0, 'PASS'), rep
    assert rep['measured']['anchors'] == 3 and rep['measured']['uncovered'] == []
    rc, rep = _cli(tmp_path, GAP)
    assert (rc, rep['verdict']) == (1, 'FAIL')
    assert [f['rule'] for f in rep['findings']] == ['TAP_ROW_COVERAGE_GAP']
    assert rep['measured']['worst_island_distance_um'] == 17.36


def test_the_lattice_scope_measures_what_the_tool_built(tmp_path):
    rc, rep = _cli(tmp_path, COVERED, '--scope', 'lattice')
    assert (rc, rep['measured']['lattice_gaps']) == (0, [])
    rc, rep = _cli(tmp_path, GAP, '--scope', 'lattice')
    assert rc == 1 and rep['findings'][0]['rule'] == 'TAP_LATTICE_GAP'
    assert rep['measured']['worst_island_distance_um'] == 19.88
    # the tool's knob is recorded, never judged: the lattice is
    rc, rep = _cli(tmp_path, COVERED, '--scope', 'lattice', '--tool-distance-um', '20',
                   '--tool-distance-source', 'OpenROAD.TapEndcapInsertion FP_TAPCELL_DIST')
    assert rc == 0 and rep['tool_distance_um'] == 20.0


def test_a_neighbour_across_the_other_edge_is_not_the_same_island():
    lef = LEF.read_text()
    covered = COVERED.read_text()
    # rows 0/1 share the n-well (N under FS), rows 1/2 the substrate
    rows = T.read_def(covered)['rows']
    nwell, sub = T.well_islands(rows, 7840, True)
    y = sorted(rows)
    assert nwell[y[0]] == nwell[y[1]] != nwell[y[2]] == nwell[y[3]]
    # the substrate edges, by name: row 0 (N) its bottom, rows 1/2 their shared
    # ground rail, row 3 (FS) its top -- three distinct strips
    assert sub[y[1]] == sub[y[2]] == y[2]
    assert {r: sub[r] for r in (y[0], y[1], y[3])} == {
        y[0]: y[0], y[1]: y[2], y[3]: y[3] + 7840}
    # f1 (row 2) keeps its n-well ties in row 3 but loses its substrate ties
    # when row 1's go: the two rules pair rows the opposite way
    rep = T.audit(re.sub(r'.*TAP_TAPCELL_ROW_1_.*\n', '', covered), [lef], TAP, 15.0, ENDCAP)
    assert [(u['instance'], u['islands']) for u in rep['uncovered']] == [('f1', ['substrate'])]


def test_the_endcap_ties_the_well_only_on_its_own_lefs_evidence():
    lef = LEF.read_text()
    rep = T.audit(COVERED.read_text(), [lef], TAP, 15.0, ENDCAP)
    assert rep['tie_masters'] == [ENDCAP, TAP]
    body = re.search(r'(?ms)^MACRO %s$.*?^END %s$' % (ENDCAP, ENDCAP), lef).group(0)
    bare = re.sub(r'(?m)^\s*LAYER [NP]well ;\n\s*RECT[^\n]*\n', '', body)
    rep = T.audit(COVERED.read_text(), [lef.replace(body, bare)], TAP, 15.0, ENDCAP)
    assert rep['tie_masters'] == [TAP]
    assert rep['endcap_counted'] == {'master': ENDCAP, 'ties_well': False}


@pytest.mark.parametrize('mutate,reason', [
    (lambda d, l: (re.sub(r'.*- [fi][01] .*\n', '', d), l), 'TAP_NO_ANCHOR'),
    (lambda d, l: (d, re.sub(r'(?ms)^MACRO \S+__dffq_1$.*?^END \S+__dffq_1$', '', l)),
     'TAP_MASTER_GEOMETRY_UNKNOWN'),
    (lambda d, l: (d, re.sub(r'(?ms)^MACRO \S+__filltie$.*?^END \S+__filltie$', '', l)),
     'TAP_MASTER_NOT_IN_LEF'),
    (lambda d, l: (d.replace('UNITS DISTANCE', 'UNITS NOTHING'), l), 'TAP_DEF_UNREADABLE'),
])
def test_what_cannot_be_measured_is_not_measured(tmp_path, mutate, reason):
    d, lef = mutate(COVERED.read_text(), LEF.read_text())
    rc, rep = _cli(tmp_path, write(tmp_path / 'x.def', d), lef=write(tmp_path / 'x.lef', lef))
    assert (rc, rep['verdict']) == (2, 'NOT_MEASURED') and rep['reason'].startswith(reason)


def test_a_deck_that_states_no_distance_is_not_a_guess(tmp_path):
    rep = T.judge(COVERED, [LEF], TAP, None, 'comp.rb states no DF.13/DF.14 distance')
    assert rep['verdict'] == 'NOT_MEASURED'
    assert rep['reason'].startswith('TAP_DECK_DISTANCE_UNDECLARED')


def test_the_unplaceable_cap_is_the_lattices_longest_free_run():
    lef = LEF.read_text()
    got = T.unplaceable_masters(COVERED.read_text(), [lef])
    assert got == {'longest_free_run_um': 38.08, 'unplaceable': []}
    wide = re.search(r'(?ms)^MACRO \S+__inv_1$.*?^END \S+__inv_1$', lef).group(0)
    wide = wide.replace('__inv_1', '__inv_wide').replace('SIZE 2.240', 'SIZE 40.320')
    assert 'SIZE 40.320' in wide
    got = T.unplaceable_masters(COVERED.read_text(), [lef, wide])
    assert got['unplaceable'] == ['gf180mcu_fd_sc_mcu7t5v0__inv_wide']
    # a candidate list narrows the answer to what the flow could offer
    assert T.unplaceable_masters(COVERED.read_text(), [lef, wide],
                                 candidates=[f'{TAP[:-9]}inv_1'])['unplaceable'] == []


# ========================================================= the runner ====

def _lattice_folder(tmp_path, def_src, *, lef_text=None):
    """TapEndcapInsertion's step folder as run_chain leaves it: its resolved
    config (container paths) and its State's DEF."""
    pdk_host = tmp_path / 'pdkroot' / 'gf180mcuD'
    write(pdk_host / 'libs.ref/cells.lef', lef_text or LEF.read_text())
    f = tmp_path / 'p/phase3/librelane/15-floorplan/09-openroad-tapendcapinsertion'
    put(f / 'config.json', {'meta': {'step': 'OpenROAD.TapEndcapInsertion'},
                            'CELL_LEFS': ['/pdk/gf180mcuD/libs.ref/cells.lef'],
                            'WELLTAP_CELL': TAP, 'ENDCAP_CELL': ENDCAP, 'FP_TAPCELL_DIST': 20})
    put(f / 'state_out.json', {'def': str(write(f / 'chip_top.def', def_src.read_text()))})
    return f, [(pdk_host, '/pdk/gf180mcuD')]


def test_later_steps_are_not_offered_a_master_no_row_can_hold(tmp_path):
    lef = LEF.read_text()
    wide = re.search(r'(?ms)^MACRO \S+__inv_1$.*?^END \S+__inv_1$', lef).group(0)
    wide = wide.replace('__inv_1', '__inv_wide').replace('SIZE 2.240', 'SIZE 40.320')
    lattice, mounts = _lattice_folder(tmp_path, COVERED, lef_text=lef + '\n' + wide + '\n')
    cfg = tmp_path / 'p/phase3/librelane/15-config'
    configs = {
        'OpenROAD.GlobalPlacement': put(cfg / 'OpenROAD.GlobalPlacement.json', {
            'meta': {'step': 'OpenROAD.GlobalPlacement'}, 'EXTRA_EXCLUDED_CELLS': ['dly']}),
        'Yosys.JsonHeader': put(cfg / 'Yosys.JsonHeader.json', {
            'meta': {'step': 'Yosys.JsonHeader'}})}
    notes = []
    out, masters = runner._librelane_exclude_unplaceable(
        tmp_path / 'p', configs, list(configs), lattice, mounts, notes)
    assert masters == ['gf180mcu_fd_sc_mcu7t5v0__inv_wide']
    gpl = json.loads(out['OpenROAD.GlobalPlacement'].read_text())
    assert gpl['EXTRA_EXCLUDED_CELLS'] == ['dly', 'gf180mcu_fd_sc_mcu7t5v0__inv_wide']
    prov = json.loads(out['OpenROAD.GlobalPlacement'].with_suffix('.provenance.json').read_text())
    assert 'longest free row run 38.08 um' in prov['keys']['EXTRA_EXCLUDED_CELLS']
    assert out['Yosys.JsonHeader'] == configs['Yosys.JsonHeader']
    assert '38.08 um' in notes[0]
    tcl = runner._unplaceable_dont_use_tcl(masters)
    assert 'set_dont_use [get_lib_cells {gf180mcu_fd_sc_mcu7t5v0__inv_wide}]' in tcl
    assert 'UNPLACEABLE_MASTERS_EXCLUDED: 1' in tcl and runner._unplaceable_dont_use_tcl([]) == ''
    # the spm lattice holds every master: nothing changes
    lattice, mounts = _lattice_folder(tmp_path / 'b', COVERED)
    same, none = runner._librelane_exclude_unplaceable(
        tmp_path / 'b/p', configs, list(configs), lattice, mounts, [])
    assert (same, none) == (configs, [])


def _local_docker(monkeypatch, calls):
    """The container runs the gate program on this host (same paths)."""
    def docker(container, cmd, **k):
        calls.append(cmd)
        if 'tap_row_coverage_check.py' not in cmd:
            return 0, 'ok', ''
        cp = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
        return cp.returncode, cp.stdout, cp.stderr
    monkeypatch.setattr(runner, '_docker_exec', docker)
    monkeypatch.setattr(runner, '_to_container_path', lambda p, c: str(p))
    monkeypatch.setattr(runner, 'deck_tap_max_distance_um', lambda pdk, c=None: DECK)


@pytest.mark.parametrize('def_src,rc', [(COVERED, 0), (GAP, 1)])
def test_the_final_layout_is_judged_by_the_deck(tmp_path, monkeypatch, def_src, rc):
    calls = []
    _local_docker(monkeypatch, calls)
    project = tmp_path / 'p'
    put(project / 'phase3/librelane/15-config/OpenROAD.TapEndcapInsertion.json',
        {'WELLTAP_CELL': TAP, 'ENDCAP_CELL': ENDCAP, 'FP_TAPCELL_DIST': 20})
    pdk = bridge._pdk(tmp_path)
    pdk.cell_lef = str(LEF)
    got, note = runner._librelane_tap_coverage(project, pdk, 'c', def_src, 'cells')
    assert got == rc, note
    rep = json.loads((project / 'reports/phase3/pnr/tap_row_coverage.cells.json').read_text())
    assert rep['deck_distance_um'] == 15.0 and DECK[1] in rep['deck_distance_source']
    assert rep['tool_distance_um'] == 20.0 and rep['endcap_master'] == ENDCAP
    # no resolved TapEndcap config: nothing to judge with, never a FAIL
    (project / 'phase3/librelane/15-config/OpenROAD.TapEndcapInsertion.json').unlink()
    assert runner._librelane_tap_coverage(project, pdk, 'c', def_src, 'cells')[0] == 2


def _floorplan_producer(tmp_path, monkeypatch, tap_def):
    """`_prepare_librelane_floorplan_for_route` (15 + 15.5ic on LibreLane)
    with the chain substituted: TapEndcapInsertion writes `tap_def`."""
    project = tmp_path / 'project'
    out_dir = project / 'phase3/stage3/pnr'
    wrapper = write(out_dir / 'chip_top_io.v', 'module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n')
    netlist = write(project / 'phase3/stage2/core.v', 'module core(a);\n  input a;\nendmodule\n')
    put(project / 'phase3/librelane_switch.json', {
        'steps': {'15': 'librelane', '15.5ic': 'librelane'},
        'pdk_root_host': str(tmp_path / 'pdkroot')})
    write(tmp_path / 'pdkroot/probe_pdk/libs.ref/cells.lef', LEF.read_text())
    write(tmp_path / 'pdkroot/probe_pdk/libs.ref/cells.lib',
          'library(x) {\n cell (probe__dly_1) { }\n}\n')
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda p: {
        'core_module': 'core', 'chip_top_module': 'chip_top',
        'chip_top_verilog': str(wrapper.relative_to(project))})
    monkeypatch.setattr(runner, 'pnr_input_netlist', lambda p, core: (netlist, 'n', False))
    calls = []
    _local_docker(monkeypatch, calls)
    segment = ['OpenROAD.Floorplan', 'OpenROAD.PadRing', 'OpenROAD.TapEndcapInsertion',
               'OpenROAD.GeneratePDN', 'Odb.RemovePDNObstructions']
    monkeypatch.setattr(contract, 'flow_segment', lambda image, first, last, **k: (
        segment[:segment.index(last) + 1]))

    def resolve(project, image, pdk, step_ids, **k):
        out = {}
        for s in step_ids:
            cfg = bridge._declared(tmp_path, s)
            doc = json.loads(cfg.read_text())
            doc.update({'CELL_LEFS': ['/pdk/probe_pdk/libs.ref/cells.lef'],
                        'WELLTAP_CELL': TAP,
                        'ENDCAP_CELL': ENDCAP, 'FP_TAPCELL_DIST': 20})
            if s.startswith('OpenROAD.'):
                doc.update({'CELL_LIBS': {'nom': ['/pdk/probe_pdk/libs.ref/cells.lib']},
                            'EXTRA_EXCLUDED_CELLS': []})
            out[s] = put(project / 'phase3/librelane/15-config' / f'{s}.json', doc)
        return out
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'emit_pdn_cfg', lambda image, pdk, out, **k: None)
    monkeypatch.setattr(contract, 'state_from_direct', lambda *a, **k: put(
        project / 'state0.json', {'nl': str(netlist)}))
    chains = []

    def chain(project, image, triples, **k):
        chains.append([t[0] for t in triples])
        folders = []
        for i, (step, cfg, _st) in enumerate(triples, 1):
            f = project / 'phase3/librelane/15-floorplan' / f'{i:02d}-{step.lower()}'
            text = (tap_def.read_text() if step == 'OpenROAD.TapEndcapInsertion'
                    else bridge.DEF_TEXT.replace('END DESIGN', f'# {step}\nEND DESIGN'))
            put(f / 'state_out.json', {'def': str(write(f / 'chip_top.def', text)),
                                       'odb': str(write(f / 'chip_top.odb', step))})
            write(f / 'config.json', Path(cfg).read_text())
            folders.append(f)
        return folders
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(runner._pr, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='PASS', stderr=''))
    pdk = bridge._pdk(tmp_path)
    pdk.macro_lefs, pdk.macro_gds = [], []
    pdk.cell_lef = str(LEF)
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, pdk, 'c', out_dir, mig97._ll_deck(), {'15': 'librelane', '15.5ic': 'librelane'},
        io_view_discover=lambda *a: ([], []))
    return project, result, chains


def test_the_tools_lattice_is_gated_before_anything_is_placed(tmp_path, monkeypatch):
    project, result, chains = _floorplan_producer(tmp_path / 'a', monkeypatch, COVERED)
    assert result.status == 'PASS', result.detail
    # the lattice ran first, alone; the full chain reused it
    assert chains[0][-1] == 'OpenROAD.TapEndcapInsertion'
    assert chains[1][-1] == 'Odb.RemovePDNObstructions'
    assert 'tap_row_coverage_check --scope lattice: rc=0' in result.detail
    assert 'longest free row run 38.08 um' in result.detail
    rep = json.loads((project / 'reports/phase3/pnr/tap_row_coverage.lattice.json').read_text())
    assert rep['verdict'] == 'PASS' and rep['tool_distance_um'] == 20.0

    project, result, _c = _floorplan_producer(tmp_path / 'b', monkeypatch, GAP)
    assert result.status == 'FAIL'
    assert result.extras['finding'] == 'TAP_LATTICE_GATE_FAILED'
    assert 'TAP_LATTICE_GAP' in result.detail


def test_the_isolated_antenna_eco_puts_the_fillers_back(tmp_path, monkeypatch):
    """The deck clears every filler site before `repair_antennas`; the tail that
    adopts its candidate resumes after the antenna stage (the only other
    refill), so the candidate must carry the PnR's own refill -- measured on
    spm: 0 fillers shipped, 321 sign-off markers at the one-site gaps."""
    spec = {'filler_masters': ['fx__fill_2', 'fx__fill_1'], 'slot_pinned_core': False,
            'design_declared_die': True, 'sparse_active_row_fill': True,
            'welltie_repair_tcl': ''}
    real = runner._pnr_rollback_refused_antenna_repair
    import functools
    monkeypatch.setattr(runner, '_pnr_rollback_refused_antenna_repair',
                        functools.partial(real, filler_spec=spec))
    refill = runner._postroute_filler_bracket_from_spec('ANTENNA_ISOLATED', spec)[1]
    assert refill and 'filler_placement' in refill and 'ANTENNA_ISOLATED_REFILL_DONE' in refill
    # after every move / wire / placement check, before the candidate is written
    # no spec (a direct call of the builder): the deck is what it was
    bare = runner._antenna_isolated_scoped_retry_tcl('/s.odb', '/c.odb', 'D')
    assert 'filler_placement' not in bare


def test_step_pnr_hands_its_filler_facts_to_the_antenna_rollback():
    import inspect
    src = inspect.getsource(runner.step_pnr)
    call = src[src.index('_pnr_rollback_refused_antenna_repair('):]
    call = call[:call.index('if _ant_roll.get(')]
    assert 'filler_spec=_postroute_filler_spec' in call

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

"""#86: real OpenROAD, neutral ODBs, through the final-evidence consumer.

The transport runs locally inside the requested EDA image; no signoff claim
about any product or canonical carrier is made by these fixtures.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import _pad_ring as pr
import phase3_one_shot_runner as runner
from test_f23_ll_seam_padring import _gds


LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS DATABASE MICRONS 1000 ; END UNITS
MANUFACTURINGGRID 0.001 ;
MACRO EDGE_CELL
 CLASS PAD ;
 ORIGIN 0 0 ;
 SIZE 10 BY 10 ;
 SYMMETRY X Y R90 ;
END EDGE_CELL
END LIBRARY
'''


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    # Other suites reload the canonical runner during collection. Keep the
    # native helper import on the same runner whose transport this fixture owns.
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", runner)
    pnr = runner._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    reports = tmp_path / 'reports/phase3'
    reports.mkdir(parents=True)
    # Nonzero die origin and a declared 2um edge setback; all four sides.
    pads = [dict(instance=f'edge_{side}', master='EDGE_CELL', side=side,
                 order=0, x=x, y=y, orient=orient)
            for side, x, y, orient in [('S', 30000, 22000, 'N'),
                                       ('N', 50000, 108000, 'FS'),
                                       ('W', 12000, 60000, 'FW'),
                                       ('E', 98000, 80000, 'W')]]
    if getattr(request, 'param', None) == 'two_south':
        pads.append(dict(instance='edge_S1', master='EDGE_CELL', side='S',
                         order=1, x=50000, y=22000, orient='N'))
    assignment = {pr.SIDE_VAR[side]: [p['instance'] for p in pads if p['side'] == side]
                  for side in pr.SIDES}
    (tmp_path / pr.ASSIGNMENT_REL).write_text(json.dumps(assignment))
    components = '\n'.join(f'- {p["instance"]} {p["master"]} + FIXED ( {p["x"]} {p["y"]} ) {p["orient"]} ;' for p in pads)
    final_def = ('VERSION 5.8 ;\nDESIGN neutral_top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
                 f'DIEAREA ( 10000 20000 ) ( 110000 120000 ) ;\nCOMPONENTS {len(pads)} ;\n'
                 + components + '\nEND COMPONENTS\nEND DESIGN\n')
    for name in ['padring.def', 'routed.def', 'neutral_top.def']:
        (pnr / name).write_text(final_def)
    (pnr / 'neutral_top.gds').write_bytes(_gds('neutral_top', ['EDGE_CELL'] * len(pads)))
    (reports / 'padring.json').write_text(json.dumps({'producer': {
        'die': {'units': 1000}, 'config': {'PAD_EDGE_SPACING': 2,
            'pads_per_side': {key: len(value) for key, value in assignment.items()}},
        'pads': pads, 'corners': [], 'fillers': []}}))
    odb = pnr / 'final.odb'
    (tmp_path / 'state_out.json').write_text(json.dumps({
        'odb': str(odb), 'def': str(pnr / 'routed.def'),
        'metrics': {'route__drc_errors_final': 0}}))
    lef = tmp_path / 'neutral.lef'
    lef.write_text(LEF)
    build = tmp_path / 'build.tcl'
    build.write_text(f'read_lef {lef}\nread_def {pnr / "routed.def"}\nwrite_db {odb}\n')
    proc = subprocess.run(['openroad', '-no_init', '-exit', str(build)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert odb.is_file()
    monkeypatch.setattr(runner, '_to_container_path', lambda p, c: p)

    def transport(container, command, **kwargs):
        assert kwargs['inputs'] == [odb]
        assert kwargs['marker'].endswith('.tcl')
        proc = subprocess.run(shlex.split(command), capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    monkeypatch.setattr(runner, '_docker_exec', transport)
    return tmp_path, odb, pads


def run(case):
    project, _, _ = case
    row = runner.step_pad_ring_final_evidence(project, 'neutral_top',
        runner.StepResult('gds', 'PASS', 0, 'neutral fixture',
                          extras={'streamout_engine': 'fixture'}), container='fixture')
    doc = json.loads((project / 'reports/phase3/pad_ring_route_evidence.json').read_text())
    return row, doc


def mutate(case, command):
    project, odb, _ = case
    script = project / 'mutate.tcl'
    script.write_text(f'read_db {odb}\nset b [ord::get_db_block]\n'
                      'set i [$b findInst edge_S]\n' + command + f'\nwrite_db {odb}\n')
    proc = subprocess.run(['openroad', '-no_init', '-exit', str(script)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_final_state_reads_native_pads_without_tcl_or_log(case):
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert doc['findings'] == []
    assert doc['native_pad_evidence']['verdict'] == 'PASS'


@pytest.mark.parametrize('damage', ['missing', 'moved', 'placed', 'rotated', 'master', 'interior'])
def test_native_bad_pad_fails_even_when_all_defs_and_gds_match(case, damage):
    commands = {'missing': 'odb::dbInst_destroy $i',
                'moved': '$i setPlacementStatus PLACED\n$i setOrigin 40000 22000\n$i setPlacementStatus FIRM',
                'placed': '$i setPlacementStatus PLACED',
                'rotated': '$i setPlacementStatus PLACED\n$i setOrient R180\n$i setPlacementStatus FIRM',
                'master': '$i getMaster'}
    if damage == 'interior':
        mutate(case, '$i setPlacementStatus PLACED\n$i setLocation 40000 50000\n$i setPlacementStatus FIRM')
        project, _, _ = case
        report = project / 'reports/phase3/padring.json'
        doc = json.loads(report.read_text())
        doc['producer']['pads'][0].update(x=40000, y=50000)
        report.write_text(json.dumps(doc))
    elif damage == 'master':
        # A producer naming a different master must not pass on position alone.
        project, _, _ = case
        report = project / 'reports/phase3/padring.json'
        doc = json.loads(report.read_text())
        doc['producer']['pads'][0]['master'] = 'OTHER_EDGE_CELL'
        report.write_text(json.dumps(doc))
    else:
        mutate(case, commands[damage])
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert 'PADRING_NATIVE_PAD_MISSING_OR_MISPLACED:edge_S' in doc['findings']


@pytest.mark.parametrize('damage', ['missing', 'unreadable', 'tool_rc', 'partial', 'exception'])
def test_unreadable_odb_or_incomplete_tool_is_not_measured(case, monkeypatch, damage):
    _, odb, _ = case
    if damage == 'missing':
        odb.unlink()
    elif damage == 'unreadable':
        odb.write_bytes(b'invalid OpenDB')
    elif damage == 'exception':
        def unavailable(*args, **kwargs):
            raise OSError('native tool unavailable')
        monkeypatch.setattr(runner, '_docker_exec', unavailable)
    else:
        monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k:
                            (1 if damage == 'tool_rc' else 0, '', ''))
    row, doc = run(case)
    assert row.status == 'NOT_MEASURED', doc
    assert doc['findings'] == []
    assert doc['not_measured']


def test_legacy_still_requires_tcl_and_live_marker(case):
    project, _, _ = case
    (project / 'state_out.json').unlink()
    row, doc = run(case)
    assert row.status == 'FAIL'
    assert any(f.startswith('PADRING_CONSUMER_MISSING:') for f in doc['findings'])
    pnr = runner._pl.pnr_dir(project)
    (pnr / 'pnr.tcl').write_text('puts "PADRING_ROUTING_CONSUMED:"\nglobal_placement\ndetailed_route\n')
    (pnr / 'openroad.log').write_text('PADRING_ROUTING_CONSUMED:\n')
    assert run(case)[0].status == 'PASS'
    (pnr / 'openroad.log').write_text('')
    row, doc = run(case)
    assert row.status == 'FAIL'
    assert 'PADRING_CONSUMER_NOT_OBSERVED_IN_LIVE_LOG' in doc['findings']


def test_native_success_does_not_bypass_existing_gds_check(case):
    project, _, _ = case
    (runner._pl.pnr_dir(project) / 'neutral_top.gds').unlink()
    row, doc = run(case)
    assert row.status == 'FAIL'
    assert 'PADRING_GDS_MISSING_OR_EMPTY' in doc['findings']


def test_producer_def_units_are_converted_to_native_dbu(case):
    project, _, _ = case
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    doc['producer']['die']['units'] = 2000
    for pad in doc['producer']['pads']:
        pad['x'] *= 2
        pad['y'] *= 2
    report.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'PASS', doc


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'empty', 'extra', 'side', 'order'])
def test_producer_population_must_match_every_declared_pad(case, damage):
    project, _, pads = case
    assert run(case)[0].status == 'PASS'
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    records = doc['producer']['pads']
    expected = ['edge_S']
    if damage == 'missing':
        records.pop(0)
        mutate(case, 'odb::dbInst_destroy $i')
    elif damage == 'duplicate':
        records[1] = dict(records[0])
        mutate(case, 'set i [$b findInst edge_N]\nodb::dbInst_destroy $i')
        expected.append('edge_N')
    elif damage == 'empty':
        records.clear()
        expected = [pad['instance'] for pad in pads]
    elif damage == 'extra':
        records.append(dict(records[0], instance='edge_extra', order=1))
        expected = ['edge_extra']
    elif damage == 'side':
        records[0]['side'] = 'N'
    else:
        records[0]['order'] = 1
    report.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    native = doc['native_pad_evidence']
    assert native['verdict'] == 'FAIL', native
    for instance in expected:
        assert any(instance in finding for finding in native['failures']), native
    assert native['expected_pads'] == len(pads)


@pytest.mark.parametrize('case', ['two_south'], indirect=True)
@pytest.mark.parametrize('damage', ['sequence', 'order_fields'])
def test_same_side_pad_order_must_match_declaration(case, damage):
    project, _, _ = case
    assert run(case)[0].status == 'PASS'
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    records = doc['producer']['pads']
    if damage == 'sequence':
        records[0], records[-1] = records[-1], records[0]
    else:
        records[0]['order'], records[-1]['order'] = 1, 0
    report.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    native = doc['native_pad_evidence']
    assert native['verdict'] == 'FAIL', native
    for instance in ['edge_S', 'edge_S1']:
        assert any(instance in finding for finding in native['failures']), native


@pytest.mark.parametrize('case', ['two_south'], indirect=True)
def test_producer_can_interleave_sides_preserving_each_side_order(case):
    project, _, pads = case
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    records = doc['producer']['pads']
    doc['producer']['pads'] = [records[i] for i in [1, 0, 2, 4, 3]]
    report.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert doc['native_pad_evidence']['expected_pads'] == len(pads)


@pytest.mark.parametrize('damage', ['duplicate', 'side_list', 'json', 'missing'])
def test_assignment_must_supply_unique_ordered_pad_names(case, damage):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    if damage == 'duplicate':
        doc['PAD_NORTH'].append('edge_S')
        assignment.write_text(json.dumps(doc))
    elif damage == 'side_list':
        doc['PAD_SOUTH'] = 'edge_S'
        assignment.write_text(json.dumps(doc))
    elif damage == 'json':
        assignment.write_text('{invalid')
    else:
        assignment.unlink()
    row, doc = run(case)
    expected = 'NOT_MEASURED' if damage == 'missing' else 'FAIL'
    assert row.status == expected, doc
    native = doc['native_pad_evidence']
    assert native['verdict'] == expected, native
    if damage in ['duplicate', 'side_list']:
        assert any('edge_S' in finding for finding in native['failures']), native


@pytest.mark.parametrize('unavailable', ['odb', 'tool'])
def test_known_population_violation_fails_when_native_is_unavailable(case, monkeypatch, unavailable):
    project, odb, _ = case
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    doc['producer']['pads'].pop(0)
    report.write_text(json.dumps(doc))
    if unavailable == 'odb':
        odb.unlink()
    else:
        monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (1, '', ''))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    native = doc['native_pad_evidence']
    assert native['verdict'] == 'FAIL', native
    assert any('edge_S' in finding for finding in native['failures']), native

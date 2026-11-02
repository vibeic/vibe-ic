"""#99: assignment intent is compared with a complete final-State ODB census.

The producer fixture uses the actual emitter. These neutral local OpenROAD
fixtures make no signoff claim about a product or canonical carrier.
"""
import hashlib
import json
import shlex
import subprocess
import sys

import pytest
import _pad_ring as pr
import pad_ring_check
import phase3_one_shot_runner as runner
from test_f23_ll_seam_padring import _gds


LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS DATABASE MICRONS 1000 ; END UNITS
MANUFACTURINGGRID 0.001 ;
'''
for name, kind, width, height in [('EDGE_CELL', 'PAD', 8, 14),
                                  ('INPUT_CELL', 'PAD INPUT', 8, 14),
                                  ('CORNER_CELL', 'PAD', 14, 14),
                                  ('FILL_CELL', 'PAD SPACER', 2, 14),
                                  ('CORE_CELL', 'CORE', 4, 4)]:
    LEF += f'''MACRO {name}
 CLASS {kind} ;
 ORIGIN 0 0 ;
 SIZE {width} BY {height} ;
 SYMMETRY X Y R90 ;
END {name}
'''
LEF += 'END LIBRARY\n'


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    # Collection can reload the runner; transport and native reader must share it.
    monkeypatch.setitem(sys.modules, 'phase3_one_shot_runner', runner)
    pnr = runner._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    reports = tmp_path / 'reports/phase3'
    reports.mkdir(parents=True)
    pads = [dict(instance=f'edge_{side}', master='EDGE_CELL', side=side,
                 x=x, y=y, orient=orient)
            for side, x, y, orient in [('S', 30000, 22000, 'N'),
                                       ('N', 50000, 104000, 'FS'),
                                       ('W', 12000, 60000, 'FW'),
                                       ('E', 94000, 80000, 'W')]]
    mode = getattr(request, 'param', None)
    if mode in ('two_south', 'two_each'):
        pads.append(dict(instance='ahead_of_edge_S', master='INPUT_CELL', side='S',
                         x=50000, y=22000, orient='N'))
    if mode == 'two_each':
        pads += [dict(instance=f'ahead_of_edge_{side}', master='INPUT_CELL',
                      side=side, x=x, y=y, orient=orient)
                 for side, x, y, orient in [('N', 70000, 104000, 'FS'),
                                            ('W', 12000, 80000, 'FW'),
                                            ('E', 94000, 96000, 'W')]]
    assignment = {pr.SIDE_VAR[side]: [p['instance'] for p in pads if p['side'] == side]
                  for side in pr.SIDES}
    assignment.update(PAD_EDGE_SPACING=2, PAD_CORNER='CORNER_CELL',
                      PAD_FILLERS=['FILL_CELL'])
    (tmp_path / pr.ASSIGNMENT_REL).write_text(json.dumps(assignment))
    cells = pads + [dict(instance='corner', master='CORNER_CELL', x=12000, y=22000, orient='N'),
                    dict(instance='filler', master='FILL_CELL', x=40000, y=22000, orient='N'),
                    dict(instance='core', master='CORE_CELL', x=60000, y=60000, orient='N')]
    # Enumeration and name order differ from the geometric declaration order.
    cells.reverse()
    components = '\n'.join(f'- {p["instance"]} {p["master"]} + FIXED ( {p["x"]} {p["y"]} ) {p["orient"]} ;' for p in cells)
    final_def = ('VERSION 5.8 ;\nDESIGN neutral_top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
                 f'DIEAREA ( 10000 20000 ) ( 110000 120000 ) ;\nCOMPONENTS {len(cells)} ;\n'
                 + components + '\nEND COMPONENTS\nEND DESIGN\n')
    for name in ['padring.def', 'routed.def', 'neutral_top.def']:
        (pnr / name).write_text(final_def)
    (pnr / 'neutral_top.gds').write_bytes(_gds('neutral_top', [p['master'] for p in cells]))
    odb = pnr / 'final.odb'
    (tmp_path / 'state_out.json').write_text(json.dumps({
        'odb': str(odb), 'def': str(pnr / 'routed.def'),
        'metrics': {'route__drc_errors_final': 0}}))
    lef = tmp_path / 'neutral.lef'
    lef.write_text(LEF)
    producer = pad_ring_check._librelane_report(
        tmp_path, tmp_path / 'state_out.json', assignment, pr.IoLibrary([lef]))
    assert 'die' not in producer
    assert all(not {'order', 'x', 'y'} & pad.keys() for pad in producer['pads'])
    (reports / 'padring.json').write_text(json.dumps({'producer': producer}))
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


def assert_native_complete(case, doc):
    body = (case[0] / 'reports/phase3/padring_final_state.log').read_text()
    assert 'PADRING_NATIVE_COMPLETE ' in body, doc
    assert not doc['native_pad_evidence']['not_measured'], doc


@pytest.mark.parametrize('case', [None, 'two_each'], indirect=True)
def test_real_producer_shape_admits_bbox_order_and_auxiliary_cells(case):
    _, odb, pads = case
    before = hashlib.sha256(odb.read_bytes()).hexdigest()
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert doc['findings'] == []
    assert doc['native_pad_evidence']['verdict'] == 'PASS'
    assert doc['native_pad_evidence']['expected_pads'] == len(pads)
    assert_native_complete(case, doc)
    assert hashlib.sha256(odb.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('damage', ['missing', 'placed', 'interior', 'outside', 'wrong_side'])
def test_native_bad_pad_fails_even_when_all_defs_and_gds_match(case, damage):
    commands = {'missing': 'odb::dbInst_destroy $i',
                'placed': '$i setPlacementStatus PLACED',
                'interior': '$i setPlacementStatus PLACED\n$i setLocation 40000 50000\n$i setPlacementStatus FIRM',
                'outside': '$i setPlacementStatus PLACED\n$i setLocation 30000 18000\n$i setPlacementStatus FIRM',
                'wrong_side': '$i setPlacementStatus PLACED\n$i setLocation 30000 104000\n$i setPlacementStatus FIRM'}
    mutate(case, commands[damage])
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any('edge_S' in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('case', ['two_each'], indirect=True)
@pytest.mark.parametrize('side', pr.SIDES)
@pytest.mark.parametrize('damage', ['reversed', 'tied'])
def test_native_side_local_order_uses_bbox_axis(case, side, damage):
    variable = 'x' if side in ('S', 'N') else 'y'
    mutate(case, f'''set a [$b findInst edge_{side}]
set z [$b findInst ahead_of_edge_{side}]
lassign [$a getLocation] ax ay
lassign [$z getLocation] zx zy
$a setPlacementStatus PLACED
$z setPlacementStatus PLACED
$a setLocation $zx $zy
$z setLocation ${'z' if damage == 'tied' else 'a'}x ${'z' if damage == 'tied' else 'a'}y
$a setPlacementStatus FIRM
$z setPlacementStatus FIRM''')
    row, doc = run(case)
    assert row.status == 'FAIL', (variable, doc)
    for name in (f'edge_{side}', f'ahead_of_edge_{side}'):
        assert any(name in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('damage', ['omitted', 'duplicated'])
def test_deleted_native_pad_cannot_be_hidden_by_producer_population(case, damage):
    project, _, _ = case
    report = project / 'reports/phase3/padring.json'
    producer = json.loads(report.read_text())
    records = producer['producer']['pads']
    index = next(i for i, rec in enumerate(records) if rec['instance'] == 'edge_S')
    if damage == 'omitted':
        records.pop(index)
    else:
        records[index] = dict(next(rec for rec in records if rec['instance'] == 'edge_N'))
    report.write_text(json.dumps(producer))
    mutate(case, 'odb::dbInst_destroy $i')
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any('edge_S' in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('master', ['EDGE_CELL', 'INPUT_CELL', 'FILL_CELL'])
def test_undeclared_native_pad_cannot_be_hidden_by_producer(case, master):
    if master == 'FILL_CELL':
        project, _, _ = case
        assignment = project / pr.ASSIGNMENT_REL
        doc = json.loads(assignment.read_text())
        doc['PAD_FILLERS'] = []
        assignment.write_text(json.dumps(doc))
    mutate(case, f'''set m [[ord::get_db] findMaster {master}]
set extra [odb::dbInst_create $b $m rogue]
$extra setLocation 70000 22000
$extra setPlacementStatus FIRM''')
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any('rogue' in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('role', ['corner', 'filler', 'core'])
def test_declared_name_using_auxiliary_or_nonpad_role_fails_named(case, role):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_SOUTH'].append(role)
    assignment.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any(role in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


def test_declared_pad_master_cannot_also_be_excluded_auxiliary_master(case):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_CORNER'] = 'EDGE_CELL'
    assignment.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any('edge_S' in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('edge', [2, 2.0, '2', '2.000', '2e0'])
def test_assignment_edge_accepts_finite_numeric_strings(case, edge):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_EDGE_SPACING'] = edge
    assignment.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('edge', [None, True, -1, 'NaN', 'Infinity', 'invalid'])
def test_invalid_assignment_edge_never_passes(case, edge):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_EDGE_SPACING'] = edge
    assignment.write_text(json.dumps(doc))
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert_native_complete(case, doc)


def test_edge_rounding_remains_half_away_from_zero_without_tolerance(case):
    project, _, _ = case
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_EDGE_SPACING'] = '2.0005'
    assignment.write_text(json.dumps(doc))
    assert run(case)[0].status == 'FAIL'
    mutate(case, '''foreach {name dx dy} {edge_S 0 1 edge_N 0 -1 edge_W 1 0 edge_E -1 0} {
set inst [$b findInst $name]
lassign [$inst getLocation] x y
$inst setPlacementStatus PLACED
$inst setLocation [expr {$x + $dx}] [expr {$y + $dy}]
$inst setPlacementStatus FIRM
}''')
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert_native_complete(case, doc)


def test_pad_at_two_matching_die_edges_has_no_unique_side(case):
    mutate(case, '$i setPlacementStatus PLACED\n$i setLocation 12000 22000\n$i setPlacementStatus FIRM')
    row, doc = run(case)
    assert row.status == 'FAIL', doc
    assert any('edge_S' in f for f in doc['native_pad_evidence']['failures']), doc
    assert_native_complete(case, doc)


@pytest.mark.parametrize('damage', ['side_order', 'position_die', 'master'])
def test_producer_metadata_cannot_gate_or_replace_native_probe(case, damage):
    project, _, _ = case
    report = project / 'reports/phase3/padring.json'
    doc = json.loads(report.read_text())
    if damage == 'side_order':
        doc['producer']['pads'][0].update(side='?', order=-1)
    elif damage == 'position_die':
        doc['producer']['die'] = {'units': 0}
        for pad in doc['producer']['pads']:
            pad.update(x='invalid', y=None, orient='?')
    else:
        doc['producer']['pads'][0]['master'] = 'OTHER_EDGE_CELL'
    report.write_text(json.dumps(doc))
    row, doc = run(case)
    assert doc['native_pad_evidence']['verdict'] == 'PASS', doc
    assert row.status == ('FAIL' if damage == 'master' else 'PASS'), doc
    assert_native_complete(case, doc)


def test_moving_along_same_side_without_changing_order_is_valid(case):
    mutate(case, '$i setPlacementStatus PLACED\n$i setLocation 40000 22000\n$i setPlacementStatus FIRM')
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert_native_complete(case, doc)


def test_encoded_native_names_survive_tcl_and_log_transport(case):
    project, _, _ = case
    name = 'edge [0]; $x \\ 雪'
    assignment = project / pr.ASSIGNMENT_REL
    doc = json.loads(assignment.read_text())
    doc['PAD_SOUTH'] = [name]
    assignment.write_text(json.dumps(doc))
    encoded = name.encode().hex()
    mutate(case, f'''odb::dbInst_destroy $i
set name [encoding convertfrom utf-8 [binary decode hex {encoded}]]
set inst [odb::dbInst_create $b [[ord::get_db] findMaster EDGE_CELL] $name]
$inst setLocation 30000 22000
$inst setPlacementStatus FIRM''')
    row, doc = run(case)
    assert row.status == 'PASS', doc
    assert_native_complete(case, doc)


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
    assert doc['native_pad_evidence']['verdict'] == expected, doc
    if damage in ['duplicate', 'side_list']:
        assert any('edge_S' in f for f in doc['native_pad_evidence']['failures']), doc
    assert 'PADRING_NATIVE_COMPLETE ' in (project / 'reports/phase3/padring_final_state.log').read_text()


@pytest.mark.parametrize('damage', ['missing', 'unreadable', 'tool_rc', 'partial', 'exception', 'error'])
def test_unreadable_odb_or_incomplete_tool_is_not_measured(case, monkeypatch, damage):
    _, odb, _ = case
    if damage == 'missing':
        odb.unlink()
    elif damage == 'unreadable':
        odb.write_bytes(b'invalid OpenDB')
    elif damage == 'exception':
        def unavailable(*args, **kwargs):
            raise FileNotFoundError('native tool unavailable')
        monkeypatch.setattr(runner, '_docker_exec', unavailable)
    elif damage == 'error':
        original = runner._docker_exec
        def error(*args, **kwargs):
            _, out, err = original(*args, **kwargs)
            return 0, out + '\n[ERROR fixture] native measurement failed\n', err
        monkeypatch.setattr(runner, '_docker_exec', error)
    else:
        original = runner._docker_exec
        def incomplete(*args, **kwargs):
            _, out, err = original(*args, **kwargs)
            out = '\n'.join(line for line in out.splitlines()
                            if not line.startswith('PADRING_NATIVE_COMPLETE'))
            return 1 if damage == 'tool_rc' else 0, out, err
        monkeypatch.setattr(runner, '_docker_exec', incomplete)
    row, doc = run(case)
    assert row.status == 'NOT_MEASURED', doc
    assert doc['findings'] == []
    assert doc['not_measured']


@pytest.mark.parametrize('unavailable', ['odb', 'tool'])
def test_producer_omission_is_not_a_measurement_when_native_unavailable(case, monkeypatch, unavailable):
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
    assert row.status == 'NOT_MEASURED', doc
    assert doc['native_pad_evidence']['verdict'] == 'NOT_MEASURED', doc
    assert doc['native_pad_evidence']['failures'] == [], doc


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
    assert doc['native_pad_evidence']['verdict'] == 'PASS', doc
    assert_native_complete(case, doc)

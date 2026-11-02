"""#86: real OpenROAD, neutral ODBs, through the final-evidence consumer.

The transport runs locally inside the requested EDA image; no signoff claim
about any product or canonical carrier is made by these fixtures.
"""
import json
import shlex
import subprocess
from pathlib import Path

import pytest
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
def case(tmp_path, monkeypatch):
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
    components = '\n'.join(f'- {p["instance"]} {p["master"]} + FIXED ( {p["x"]} {p["y"]} ) {p["orient"]} ;' for p in pads)
    final_def = ('VERSION 5.8 ;\nDESIGN neutral_top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
                 'DIEAREA ( 10000 20000 ) ( 110000 120000 ) ;\nCOMPONENTS 4 ;\n'
                 + components + '\nEND COMPONENTS\nEND DESIGN\n')
    for name in ['padring.def', 'routed.def', 'neutral_top.def']:
        (pnr / name).write_text(final_def)
    (pnr / 'neutral_top.gds').write_bytes(_gds('neutral_top', ['EDGE_CELL'] * 4))
    (reports / 'padring.json').write_text(json.dumps({'producer': {
        'die': {'units': 1000}, 'config': {'PAD_EDGE_SPACING': 2},
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

"""F15: the nine step-23 gates judge STAPostPNR's per-corner output when step
23 runs `librelane` or `dual`.

The gate list is the flow's own (`flow/phase1_phase2_phase3.yaml`, step 23
`gate.all_of`), asserted below so it cannot drift.  Every gate runs through its
real `main`; only the tool's file writes are substituted: a STAPostPNR step
directory in LibreLane 3.1's layout (`config.json`, `state_out.json`, one
directory per corner) with the report grammar the step-23 extra corner Tcl
makes OpenSTA write (copied from a 0.3.79 STAPostPNR run on spm), and the
contract's `vibeic_receipt.json` hashing what the tool wrote.

Per gate: the tool arm is what is read; a missing corner artefact REFUSES
(rc 1, never N/A or PASS); a mutated worst slack (or the tool field the gate
judges) flips the verdict.  `direct` mode never touches the tool arm.
"""
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
signoff = importlib.import_module('librelane_signoff')

CORNERS = tuple(f'{rc}_{pvt}' for rc in ('nom', 'min', 'max')
                for pvt in ('tt_025C_5v00', 'ss_125C_4v50', 'ff_n40C_5v50'))
CELL_LIBS = {f'*_{c}': [f'/pdk/p/libs.ref/cells/lib/cells__{c}.lib']
             for c in ('tt_025C_5v00', 'ss_125C_4v50', 'ff_n40C_5v50')}
STA = 'phase3/librelane/23/01-openroad-stapostpnr'

GATES = ('hold_corner_coverage_check', 'post_route_signoff_corner_check', 'sta_corner_record_completeness_check')

#: Step-23 gates that BIND the tool arm like the nine above (a missing or
#: unbound corner artefact REFUSES) but whose clean-arm answer is not a PASS
#: from STAPostPNR's reports, for a stated reason pinned in
#: `test_a_gate_that_cannot_pass_on_the_tools_reports_says_why`:
#:   drv_signoff_judge      judges a fresh per-(pin, scene) OpenSTA capture
#:                          (DRV sign-off standard); STAPostPNR's reports carry
#:                          violator COUNTS only -> NOT_MEASURED without one.
#:   pad_input_drive_check  judges the SDC the tool timed against the resolved
#:                          bond-pad drive; this fixture's top is not a DIE ->
#:                          NOT_APPLICABLE.
OWN_ANSWER_GATES = ()
ALL_STEP23_GATES = GATES + OWN_ANSWER_GATES


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---------------------------------------------------- the tool's grammar ---

_SETUP_PATH = """Startpoint: u_core/_416_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: p (output port clocked by clk)
Path Group: clk
Path Type: max

        Cap        Slew       Delay        Time   Description
---------------------------------------------------------------------------------------
                           0.000000    0.000000   clock clk (rise edge)
                           6.914796    6.914796   clock network delay (propagated)
               0.168482    0.000000    6.914796 ^ u_core/_416_/CLK (cells__dffq_4)
   0.028183    0.232028    1.522065    8.436861 v u_core/_416_/Q (cells__dffq_4)
   0.069908    1.878363    1.479069    9.915931 v wire702/Z (cells__clkbuf_1)
   0.084767    0.737055    1.293833   11.209764 v wire700/Z (cells__buf_2)
   3.457845    0.560389    3.492257   {arrival:.6f} v u_pad_p/PAD (io__bi_24t)
               0.560389    0.000000   {arrival:.6f} v p (out)
                                      {arrival:.6f}   data arrival time

                          24.000000   24.000000   clock clk (rise edge)
                           0.000000   24.000000   clock network delay (propagated)
                          -4.800000   19.200000   output external delay
                                      19.200000   data required time
---------------------------------------------------------------------------------------
                                      19.200000   data required time
                                     -{arrival:.6f}   data arrival time
---------------------------------------------------------------------------------------
                                      {slack:.6f}   slack ({state})

"""

#: A setup path whose delay is logic depth, not buffering or one weak arc:
#: what `sta_architectural_residual_check` calls architectural when violated.
_DEEP_PATH = """Startpoint: u_core/_500_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_core/_501_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

        Cap        Slew       Delay        Time   Description
---------------------------------------------------------------------------------------
                           0.000000    0.000000   clock clk (rise edge)
                           1.000000    1.000000   clock network delay (propagated)
""" + ''.join(
    f"   0.010000    0.200000    4.000000   {1 + 4 * (i + 1):.6f} v u_core/_6{i}_/ZN (cells__nand2_1)\n"
    for i in range(8)) + """                                      33.000000   data arrival time

                          24.000000   24.000000   clock clk (rise edge)
                           1.000000   25.000000   clock network delay (propagated)
                                      25.000000   data required time
---------------------------------------------------------------------------------------
                                      {slack:.6f}   slack ({state})

"""

_HOLD_PATH = """Startpoint: x[1] (input port clocked by clk)
Endpoint: u_core/_450_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: min

        Cap        Slew       Delay        Time   Description
---------------------------------------------------------------------------------------
                           0.000000    0.000000   clock clk (rise edge)
                           0.000000    0.000000   clock network delay (propagated)
                           4.800000    4.800000 v input external delay
   3.028233    0.000000    0.000000    4.800000 v x[1] (in)
   0.032459    0.197919    1.396741    6.196742 v u_pad_x_1/Y (io__in_c)
               0.337285    0.000051    7.028150 v u_core/_450_/D (cells__dffq_1)
                                       7.028150   data arrival time

                           0.000000    0.000000   clock clk (rise edge)
                           6.926019    6.926019   clock network delay (propagated)
                           0.097355    7.023373   library hold time
                                       7.023373   data required time
---------------------------------------------------------------------------------------
                                       7.023373   data required time
                                      -7.028150   data arrival time
---------------------------------------------------------------------------------------
                                       {slack:.6f}   slack ({state})

"""

_DRV_VIOLATOR = """max slew

Pin                                        Limit        Slew       Slack
------------------------------------------------------------------------
u_core/_07896_/B0                        3.000000    6.120000   -3.120000 (VIOLATED)

"""


def corner_report(corner: str, setup: float, hold, *, unit='ns', drv=False,
                  deep=None) -> str:
    """`vibeic_signoff.rpt` as the step-23 extra corner Tcl has OpenSTA write it."""
    hold_line = 'INF' if hold is None else f'{hold:.6f}'
    head = ('OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV '
            'source=TIME_DERATING_CONSTRAINT=5\n'
            'STA_BASIS: POST_ROUTE_SPEF\n'
            f'STA_BASIS_CORNER: {corner}\n'
            + (f'STA_TIME_UNIT: {unit}\n' if unit else
               'STA_TIME_UNIT_NOT_STATED: this interpreter could not answer\n'))
    setup_block = (f'worst slack max {setup:.6f}\ntns max {min(setup, 0):.6f}\n'
                   f'wns max {min(setup, 0):.6f}\nSIGNOFF_WNS_REPORTED query=-max\n'
                   + _SETUP_PATH.format(arrival=19.2 - setup, slack=setup,
                                        state='MET' if setup >= 0 else 'VIOLATED')
                   + (_DEEP_PATH.format(slack=deep, state='MET' if deep >= 0 else 'VIOLATED')
                      if deep is not None else '')
                   + 'SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3\n')
    hold_block = (f'worst slack min {hold_line}\n'
                  + (f'tns min {min(hold, 0):.6f}\nwns min {min(hold, 0):.6f}\n'
                     if hold is not None else 'tns min 0.000000\nwns min 0.000000\n')
                  + 'SIGNOFF_WNS_REPORTED query=-min\n'
                  + (_HOLD_PATH.format(slack=hold, state='MET' if hold >= 0 else 'VIOLATED')
                     if hold is not None else 'No paths found.\n\n')
                  + 'SIGNOFF_WORST_PATHS_REPORTED path_delay=min group_path_count=3\n')
    checks = ('SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew '
              'min_pulse_width max_capacitance max_fanout\n'
              + (_DRV_VIOLATOR if drv else '')
              + 'SIGNOFF_DRV_CENSUS_BEGIN the tool\'s own violator count\n'
              f'SIGNOFF_DRV_CENSUS max_slew violators={1 if drv else 0}\n'
              'SIGNOFF_DRV_CENSUS max_fanout violators=0\n'
              'SIGNOFF_DRV_CENSUS max_capacitance violators=0\n')
    return head + setup_block + hold_block + checks


def clock_report(period: float) -> str:
    return (f'Clock: clk\nSources: clk \nGenerated: no\nVirtual: no\n'
            f'Propagated: yes\nPeriod: {period:.6f}\n\n'
            '===========================================================================\n'
            'report_clock_properties\n'
            '============================================================================\n'
            'Clock                   Period          Waveform\n'
            '----------------------------------------------------\n'
            f'clk                  {period:.6f}    0.000000 {period / 2:.6f}\n')


# ------------------------------------------------------------ the project ---

def tool_project(root: Path, *, mode='librelane', setup=None, hold=None,
                 period=24.0, unit='ns', drv=(), deep=None, hold_inf=()) -> Path:
    """A step-23 tool run: LibreLane's step directory plus the runner's record.
    `setup`/`hold` map a corner to its worst slack (default +1.0 / +0.4)."""
    project = root / 'proj'
    pnr = project / 'phase3/stage3/pnr'
    views = {'def': _write(pnr / 'top.def', 'DESIGN top ;\nEND DESIGN\n'),
             'nl': _write(pnr / 'top_pnr.v', 'module top(); endmodule\n'),
             'sdc': _write(pnr / 'constraint.sdc', 'create_clock -period 24 clk\n')}
    spef = {f'{rc}_*': _write(project / f'phase3/stage3/extracted/spef_corners/top.{rc}.spef',
                              f'*SPEF "IEEE 1481-1998"\n*DESIGN "top"\n*C_UNIT 1 PF\n// {rc}\n')
            for rc in ('nom', 'min', 'max')}
    pdk_root = root / 'pdk_root'
    for pattern, libs in CELL_LIBS.items():
        stem = pattern[2:]
        temp = -40 if '_n40C_' in stem else 125 if '_125C_' in stem else 25
        voltage = 4.5 if stem.endswith('4v50') else 5.5 if stem.endswith('5v50') else 5.0
        for lib in libs:
            _write(pdk_root / lib.lstrip('/').removeprefix('pdk/'),
                   f'library (cells) {{\n nom_process : 1 ;\n'
                   f' nom_voltage : {voltage} ;\n nom_temperature : {temp} ;\n}}\n')
    _write(project / 'phase3/librelane_pdk_root.provenance.json', json.dumps({
        'path': str(pdk_root), 'derivation': {'pdk': 'p'}}))
    folder = project / STA
    metrics = {}
    for corner in CORNERS:
        s = (setup or {}).get(corner, 1.0)
        h = None if corner in hold_inf else (hold or {}).get(corner, 0.4)
        _write(folder / corner / signoff.CORNER_REPORT,
               corner_report(corner, s, h, unit=unit, drv=corner in drv,
                             deep=deep if corner == 'max_ss_125C_4v50' else None))
        _write(folder / corner / 'clock.rpt', clock_report(period))
        _write(folder / corner / 'max.rpt', 'Startpoint: a\n')
        _write(folder / corner / 'min.rpt', 'Startpoint: a\n')
        _write(folder / corner / 'unpropagated.rpt', '')
        _write(folder / corner / 'sta.log', ''.join(
            f"Reading cell library for the '{corner}' corner at '{lib}'…\n"
            for p, libs in CELL_LIBS.items() if corner.endswith(p[1:]) for lib in libs)
            + f"Reading top-level design parasitics for the '{corner}' corner at "
              f"'{spef[corner.split('_', 1)[0] + '_*']}'…\n")
        metrics.update({f'timing__setup__ws__corner:{corner}': s,
                        f'timing__hold__ws__corner:{corner}': h if h is not None else 1e30})
    _write(folder / 'config.json', json.dumps({
        'meta': {'step': 'OpenROAD.STAPostPNR'}, 'DESIGN_NAME': 'top',
        'STA_CORNERS': list(CORNERS), 'CELL_LIBS': CELL_LIBS}))
    _write(folder / 'state_out.json', json.dumps({
        **{k: str(v) for k, v in views.items()},
        'spef': {k: str(v) for k, v in spef.items()}, 'metrics': metrics}))
    timed = [*views.values(), *spef.values()]
    bound = {str(p.relative_to(folder)): _sha(p) for p in folder.rglob('*')
             if p.is_file() and (p.name.endswith(('.json', '.rpt')) or p.name == 'sta.log')}
    liberty_files = {lib: _sha(pdk_root / lib.lstrip('/').removeprefix('pdk/'))
                     for libs in CELL_LIBS.values() for lib in libs}
    _write(folder / 'vibeic_receipt.json', json.dumps({
        'input': {'step': 'OpenROAD.STAPostPNR',
                  'state_files': {str(p): _sha(p) for p in timed},
                  'liberty_files': liberty_files},
        'sha256': bound}))
    _write(project / signoff.SIGNOFF_RECORD, json.dumps({
        'step': '23', 'mode': mode, 'sta_state': str(folder / 'state_out.json'),
        'sta_state_sha256': _sha(folder / 'state_out.json')}))
    _write(project / 'phase3/librelane_switch.json',
           json.dumps({'steps': {'23': mode}}))
    return project


def rebind(project: Path) -> None:
    """Re-hash the step directory, as the contract does after the tool wrote it
    (a mutation the TOOL made, not a tampered file)."""
    folder = project / STA
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    receipt['sha256'] = {str(p.relative_to(folder)): _sha(p) for p in folder.rglob('*')
                         if p.is_file() and (p.name.endswith(('.json', '.rpt')) or p.name == 'sta.log')
                         and p.name != 'vibeic_receipt.json'}
    (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))
    record = json.loads((project / signoff.SIGNOFF_RECORD).read_text())
    record['sta_state_sha256'] = _sha(folder / 'state_out.json')
    (project / signoff.SIGNOFF_RECORD).write_text(json.dumps(record))


def gate_inputs(project: Path, *, recorded_slack=1.0, assumed=False, stamp=True,
                promoted_claim=0) -> Path:
    """What the gates read besides the tool: the run's own records."""
    _write(project / 'reports/phase3/achievable_fmax.json', json.dumps({
        'spec_period_ns': 24.0, 'worst_setup_slack_ns': recorded_slack,
        'achievable_period_ns': 24.0 - recorded_slack, 'relaxation_applied': False}))
    _write(project / 'reports/phase3/clock_target_provenance.json', json.dumps({
        'pdk': 'p', 'period_ns': 24.0, 'tier': 'declared_pdk_table',
        'assumed': assumed, 'would_have_stated': ''}))
    _write(project / 'phase3/stage3/pnr/routed_base_prerepair.def', 'DESIGN top ;\n')
    _write(project / 'phase3/stage3/pnr/signoff_spef_repair.log',
           f'Found {promoted_claim} slew violations.\n'
           f'Found 0 capacitance violations.\n')
    if assumed and stamp:
        import clock_target_provenance
        clock_target_provenance.stamp_signoff_records(project)
    return project


# ------------------------------------------------------------ the runner ---

def run_gate(name: str, project: Path, tmp_path: Path):
    """The gate's real entry point, as the flow's clause calls it."""
    out = tmp_path / f'{name}.json'
    module = importlib.import_module(name)
    if name == 'sta_report_check':
        rc = module._run_and_emit([str(project), '--mode', 'sta', '--under',
                                   'phase3/stage3/sta/post_route_timing.rpt',
                                   '--json', str(out)])
    elif name == 'hold_corner_coverage_check':
        rc = module.main([str(project), '--json', str(out)])
    else:
        rc = module.main([str(project), '--json', str(out)])
    doc = json.loads(out.read_text()) if out.is_file() else {}
    return rc, doc


def verdict(doc: dict) -> str:
    if 'verdict' in doc and doc['verdict'] is not None:
        return str(doc['verdict'])
    return 'PASS' if doc.get('passed') else 'FAIL'


# ================================================================ tests ====



def test_the_reader_binds_every_file_to_what_the_tool_wrote(tmp_path):
    project = tool_project(tmp_path)
    arm = signoff.step23_tool_arm(project, (signoff.CORNER_REPORT, 'clock.rpt'))
    assert list(arm['corners']) == list(CORNERS)
    row = arm['corners']['max_ss_125C_4v50']
    assert (row['rc_corner'], row['process'], row['voltage_v'], row['temperature_c']) == \
        ('max', 'ss', 4.5, 125.0)
    report = project / STA / 'max_ss_125C_4v50' / signoff.CORNER_REPORT
    assert row['files'][signoff.CORNER_REPORT]['sha256'] == _sha(report)
    assert signoff.tool_arm_basis(arm)['state_sha256'] == _sha(project / STA / 'state_out.json')


def test_direct_mode_never_reads_the_tool_arm(tmp_path):
    project = tool_project(tmp_path, mode='direct')
    assert signoff.step23_tool_arm(project) is None


@pytest.mark.parametrize('damage, code', [
    ('missing', 'LL_STA_CORNER_ARTEFACT_MISSING'),
    ('tampered', 'LL_STA_ARTEFACT_UNBOUND'),
    ('stale_view', 'LL_STA_INPUT_STALE'),
    ('stale_mode', 'LL_STA_RECORD_STALE'),
    ('no_record', 'LL_STA_TOOL_ARM_UNREADABLE'),
    ('other_state', 'LL_STA_RECORD_STALE'),
])
def test_the_reader_refuses_what_it_cannot_bind(tmp_path, damage, code):
    project = tool_project(tmp_path)
    report = project / STA / 'min_ff_n40C_5v50' / signoff.CORNER_REPORT
    if damage == 'missing':
        report.unlink()
    elif damage == 'tampered':
        report.write_text(report.read_text().replace('worst slack max 1.0', 'worst slack max 9.0'))
    elif damage == 'stale_view':
        (project / 'phase3/stage3/pnr/top_pnr.v').write_text('module top(a); endmodule\n')
    elif damage == 'other_state':
        # the record names a STAPostPNR state other than the one on disk
        record = project / signoff.SIGNOFF_RECORD
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      'sta_state_sha256': '0' * 64}))
    elif damage == 'stale_mode':
        (project / 'phase3/librelane_switch.json').write_text(json.dumps({'steps': {'23': 'dual'}}))
    else:
        (project / signoff.SIGNOFF_RECORD).unlink()
    with pytest.raises(signoff.Refusal) as caught:
        signoff.step23_tool_arm(project)
    assert caught.value.code == code


# --------------------------------------------------- per gate: tool read ---

@pytest.mark.parametrize('name', GATES)
@pytest.mark.parametrize('mode', ['librelane', 'dual'])
def test_each_gate_passes_on_the_tools_clean_corners_and_names_them(tmp_path, name, mode):
    project = gate_inputs(tool_project(tmp_path, mode=mode))
    rc, doc = run_gate(name, project, tmp_path)
    assert rc == 0 and verdict(doc) == 'PASS', (name, doc)
    text = json.dumps(doc)
    # The basis is the tool's: its step directory, not our deck's reports.
    assert STA in text, name
    assert 'sta_mcorner_ocv' not in text and 'post_route_timing.rpt' not in text.replace(
        'phase3/stage3/sta/post_route_timing.rpt', ''), name


@pytest.mark.parametrize('name', ALL_STEP23_GATES)
def test_each_gate_refuses_a_missing_corner_artefact(tmp_path, name):
    project = gate_inputs(tool_project(tmp_path))
    (project / STA / 'max_ss_125C_4v50' / signoff.CORNER_REPORT).unlink()
    rc, doc = run_gate(name, project, tmp_path)
    assert rc == 1, (name, rc, doc)
    if name == 'sta_corner_record_completeness_check':
        missing = next(r for r in doc['corners'] if r['corner'] == 'max_ss_125C_4v50')
        assert missing['measurement_status'] == 'NOT_MEASURED', doc
        assert missing['scope_gaps']['custom_report']
        assert all(r['measurement_status'] == 'MEASURED' for r in doc['corners']
                   if r['corner'] != 'max_ss_125C_4v50')
        return
    assert verdict(doc) == 'REFUSED', (name, doc)


@pytest.mark.parametrize('name', ALL_STEP23_GATES)
def test_each_gate_refuses_a_corner_report_the_tool_did_not_write(tmp_path, name):
    project = gate_inputs(tool_project(tmp_path))
    report = project / STA / 'nom_tt_025C_5v00' / signoff.CORNER_REPORT
    report.write_text(report.read_text() + '\n')
    rc, doc = run_gate(name, project, tmp_path)
    assert (rc, verdict(doc)) == (1, 'REFUSED'), (name, doc)






# ------------------------------------ per gate: the judged field flips it ---

def _setup_violated(root):
    return tool_project(root, setup={'max_ss_125C_4v50': -0.75})


FLIPS = {
    # the tool's worst setup slack moves; the recorded reached period does not
    # the fast corner's hold analysis times no path (the INF sentinel)
    'hold_corner_coverage_check': lambda root: tool_project(
        root, hold_inf=('min_ff_n40C_5v50',)),
    'post_route_signoff_corner_check': _setup_violated,
    'sta_corner_record_completeness_check': _setup_violated,
    # a setup path of pure logic depth violated by more than buffering recovers
    # the tool timed another clock period than the run's record
    # a DRV violator the promotion's own session did not claim
}


@pytest.mark.parametrize('name', sorted(FLIPS))
def test_each_gate_flips_on_the_tools_own_number(tmp_path, name):
    project = gate_inputs(FLIPS[name](tmp_path))
    rc, doc = run_gate(name, project, tmp_path)
    assert rc == 1 and verdict(doc) == 'FAIL', (name, doc)
    # ...and it is the TOOL's number that flipped it, read from the tool's step.
    assert STA in json.dumps(doc), (name, doc)


@pytest.mark.parametrize('name', sorted(FLIPS))
def test_the_same_numbers_in_our_deck_do_not_flip_a_gate_on_the_tool(tmp_path, name):
    """Reverse: the violation sits only in the direct deck's reports; the tool
    is clean, so a gate reading the tool stays PASS."""
    project = gate_inputs(tool_project(tmp_path))
    deck = corner_report('SS', -0.75, -0.2, drv=True, deep=-8.0)
    for rel in ('phase3/stage3/sta/sta_mcorner_ocv.rpt', 'reports/phase3/sta_mcorner_ocv.rpt',
                'phase3/stage3/sta/sta_spef_multicorner.rpt', 'reports/phase3/sta_spef_based.rpt',
                'phase3/stage3/sta/post_route_timing.rpt'):
        _write(project / rel, '=== SETUP corner: process=SS liberty=x.lib ===\n' + deck)
    # the step-10 per-corner sweep is our deck too: one lone corner report is
    # a broken multi-corner claim there, and must not be read on the tool arm
    _write(project / 'phase3/stage3/sta/per_corner/sta_SS.rpt', deck)
    rc, doc = run_gate(name, project, tmp_path)
    assert rc == 0 and verdict(doc) == 'PASS', (name, doc)
    assert STA in json.dumps(doc), (name, doc)








def test_the_completeness_rows_carry_the_tools_corner_scope(tmp_path):
    project = gate_inputs(tool_project(tmp_path))
    _rc, doc = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    rows = {r['corner']: (r['rc_corner'], r['process']) for r in doc['corners']}
    assert rows == {c: (c.split('_', 1)[0], c.split('_', 2)[1]) for c in CORNERS}


def test_a_corner_whose_liberty_names_no_process_is_an_incomplete_record(tmp_path):
    """The _ppa scope rule: an unreadable process is a gap, never a guess."""
    project = tool_project(tmp_path)
    config = project / STA / 'config.json'
    doc = json.loads(config.read_text())
    doc['CELL_LIBS']['*_ss_125C_4v50'] = ['/pdk/p/libs.ref/cells/lib/cells_slowcorner.lib']
    config.write_text(json.dumps(doc))
    rebind(project)
    gate_inputs(project)
    rc, out = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert (rc, out['verdict']) == (1, 'NOT_MEASURED')
    assert 'R1_INCOMPLETE_CORNER_RECORD' in out['rules_violated']
    rc, out = run_gate('hold_corner_coverage_check', project, tmp_path)
    assert (rc, out['verdict']) == (1, 'REFUSED')


@pytest.mark.parametrize('ff_liberty, expect', [
    ('cells__ff_n40C_5v50.lib', (0, 'PASS')),
    ('cells__ff_n40C_5v50_other.lib', (1, 'NOT_MEASURED')),
])
def test_a_required_pvt_corner_is_measured_only_by_a_tool_corner_on_its_liberty(
        tmp_path, ff_liberty, expect):
    """R6 on the tool: the design requires SS/TT/FF (its own input document)
    and binds each to a liberty (its own PVT matrix); a required corner is
    measured only by a tool corner that timed THAT liberty."""
    project = gate_inputs(tool_project(tmp_path))
    _write(project / 'input/docs/L9_constraints_floorplan.md',
           '## Timing constraints (SDC)\n'
           '> Multi-corner sign-off: SS, TT, FF corners 均須 sign-off 通過。\n')
    _write(project / 'phase2/stage2/constraints/pvt_matrix.json', json.dumps({
        'primary_corner': 'TT', 'corners': [
            {'name': 'ss', 'label': 'SS', 'liberty': '/host/lib/cells__ss_125C_4v50.lib'},
            {'name': 'tt', 'label': 'TT', 'liberty': '/host/lib/cells__tt_025C_5v00.lib'},
            {'name': 'ff', 'label': 'FF', 'liberty': f'/host/lib/{ff_liberty}'}]}))
    rc, doc = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert (rc, doc['verdict']) == expect, doc
    assert doc['declaration_sources']['required_pvt_corners'] == ['FF', 'SS', 'TT']


def test_a_hold_only_violation_at_one_tool_corner_fails_the_corner_gate(tmp_path):
    project = gate_inputs(tool_project(tmp_path, hold={'nom_tt_025C_5v00': -0.05}))
    rc, doc = run_gate('post_route_signoff_corner_check', project, tmp_path)
    assert (rc, doc['verdict'], doc['hold_worst_corner']) == (1, 'FAIL', 'nom_tt_025C_5v00')
    assert any('nom_tt_025C_5v00 hold' in r for r in doc['reasons'])


def test_named_subjects_do_not_outlive_the_audit_that_named_them(tmp_path):
    """`--subject` scopes ONE audit: a later audit in the same process (a
    pytest worker, the runner's gate loop) globs as it always did."""
    import eda_report_audit
    project = tool_project(tmp_path)
    rel = f'{STA}/max_ss_125C_4v50/{signoff.CORNER_REPORT}'
    eda_report_audit.main([str(project), '--mode', 'sta', '--under', STA,
                           '--subject', rel, '--json', str(tmp_path / 'a.json')])
    assert eda_report_audit._SUBJECTS is None
    _write(project / 'reports/phase3/drc_signoff.rpt', 'x')
    assert [p.name for p in eda_report_audit._discover(project, ['*drc*.rpt'])] == ['drc_signoff.rpt']

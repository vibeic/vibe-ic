"""F22: step 30's SPICE deck simulates the cells the liberty was characterised
on, and the Xyce arm reads what the tool's Xyce deck writes.

MEASURED on the spm copy (gf180mcuD, max_ss_125C_4v50, vibeic-eda 0.3.79),
register to register, `write_path_spice` with the same STAPostPNR state:

    cell view            ngspice    Xyce       tolerance
    declared schematic   -28.98%    -29.04%    18.4%    MISMATCH (both)
    extracted layout     -11.29%    -11.31%    18.4%    CORRELATED (both)

The schematic subckts carry W/L only (`as=ad=ps=pd=0`, no wiring). One cell
per deck at liberty grid points, on the liberty's own driver waveform, the
schematic view reads -35..-50% at the smallest load; the same cells extracted
from the PDK's GDS read within 1% (nand2_1) and 5% (buf_1) at a mid point.

The programs run for real; only the tools' file writes are substituted at the
`_docker` edge. The extracted netlist below is Magic 8.3's own ext2spice
output for gf180mcu_fd_sc_mcu7t5v0__nand2_1 from the PDK's GDS; the CSV header
is Xyce's own `.print tran format=csv` output of the tool's deck.
"""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / 'tests'))
pst = importlib.import_module('path_spice_tool')
postroute = importlib.import_module('librelane_postroute')
t106 = importlib.import_module('test_t106_mig_perc_power')
write, put = t106.write, t106.put

SCHEMATIC = '''* cells
.SUBCKT cells__nand2_1 A1 A2 ZN VDD VNW VPW VSS
X_i_1 net_0 A2 VSS VPW nfet_05v0 W=8.2e-07 L=6e-07
X_i_0 ZN A1 net_0 VPW nfet_05v0 W=8.2e-07 L=6e-07
X_i_3 ZN A2 VDD VNW pfet_05v0 W=1.13e-06 L=5e-07
X_i_2 VDD A1 ZN VNW pfet_05v0 W=1.13e-06 L=5e-07
.ENDS
.SUBCKT cells__dffq_1 D CLK Q VDD VNW VPW VSS
X_i_0 Q D VSS VPW nfet_05v0 W=8.2e-07 L=6e-07
.ENDS
.SUBCKT cells__fill_1 VDD VNW VPW VSS
.ENDS
.SUBCKT cells__inv_1 I ZN VDD VNW VPW VSS
X_i_0 ZN I VSS VPW nfet_05v0 W=8.2e-07 L=6e-07
.ENDS
'''

#: Magic's ext2spice of the PDK's nand2_1 layout (ports in LAYOUT order).
EXTRACTED_NAND2 = '''* NGSPICE file created from cells__nand2_1.ext - technology: gf180mcuD

.subckt cells__nand2_1 VDD VSS ZN A1 A2 VNW VPW
X0 ZN A2 VDD VNW pfet_05v0 ad=0.2938p pd=1.65u as=0.4972p ps=3.14u w=1.13u l=0.5u
X1 ZN A1 a_245_68# VPW nfet_05v0 ad=0.3608p pd=2.52u as=0.1312p ps=1.14u w=0.82u l=0.6u
X2 VDD A1 ZN VNW pfet_05v0 ad=0.4972p pd=3.14u as=0.2938p ps=1.65u w=1.13u l=0.5u
X3 a_245_68# A2 VSS VPW nfet_05v0 ad=0.1312p pd=1.14u as=0.3608p ps=2.52u w=0.82u l=0.6u
C0 A1 A2 0.12164f
C3 ZN VSS 0.05156f
C13 ZN VDD 0.13491f
C21 ZN VPW 0.27964f
.ends
'''

NETLIST = '''module chip_top (clk, x, p);
 cells__nand2_1 _335_ (.A1(a), .A2(b), .ZN(c));
 cells__dffq_1 _417_ (.D(c), .CLK(clk), .Q(p));
 cells__fill_1 FILLER_0 ();
 cells__inv_1 _500_ (.I(c), .ZN(d));
endmodule
'''

CONFIG_TCL = ('set ::env(FP_TAPCELL_DIST) 20\n'
              'set ::env(MAGICRC) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/magic/$::env(PDK).magicrc"\n')


def _magic_edge(calls, extracted=None):
    """Magic writes one ext2spice file per cell it can load from the GDS."""
    extracted = {'cells__nand2_1': EXTRACTED_NAND2} if extracted is None else extracted

    def fake(image, project, mounts, argv, cwd, docker='docker', env=None):
        calls.append((argv, env))
        assert argv[0] == 'magic', argv
        tcl = Path(argv[-1]).read_text()
        for cell in __import__('re').findall(r'^load (\S+)$', tcl, __import__('re').M):
            if cell in extracted:
                write(Path(cwd) / f'{cell}.spice', extracted[cell])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    return fake


def _pdk(tmp_path):
    root = tmp_path / 'pdkroot'
    write(root / 'x/libs.ref/cells/spice/cells.spice', SCHEMATIC)
    write(root / 'x/libs.tech/librelane/config.tcl', CONFIG_TCL)
    return root


# ---------------------------------------------------------- the cell view ---

def test_the_layout_view_takes_the_schematic_subckts_place_in_the_schematic_port_order(
        tmp_path, monkeypatch):
    root = _pdk(tmp_path)
    netlist = write(tmp_path / 'design/nl.v', NETLIST)
    calls = []
    # dffq_1: the layout extracts to wiring alone (no device); inv_1: absent
    # from the GDS, Magic writes nothing (MEASURED: "Cell ... couldn't be read").
    monkeypatch.setattr(pst, '_docker', _magic_edge(calls, {
        'cells__nand2_1': EXTRACTED_NAND2,
        'cells__dffq_1': '.subckt cells__dffq_1 D CLK Q VDD VNW VPW VSS\nC0 Q VSS 0.1f\n.ends\n'}))
    view = pst.cell_view('img', tmp_path / 'design', [(root / 'x', '/pdk/x')],
                         config={'CELL_GDS': ['/pdk/x/libs.ref/cells/gds/cells.gds']},
                         pdk_dir=root / 'x', guest_root='/pdk', pdk='x', netlist=netlist,
                         cell_sources=[root / 'x/libs.ref/cells/spice/cells.spice'],
                         out_dir=tmp_path / 'out')
    (argv, env), = calls
    # The PDK's own rcfile, resolved in the guest, with the guest PDK_ROOT it reads.
    assert argv[:5] == ['magic', '-dnull', '-noconsole', '-rcfile', '/pdk/x/libs.tech/magic/x.magicrc']
    assert env == {'PDK_ROOT': '/pdk'}
    tcl = Path(argv[-1]).read_text()
    assert 'gds read /pdk/x/libs.ref/cells/gds/cells.gds' in tcl
    assert 'ext2spice cthresh 0' in tcl and 'ext2spice extresist on' in tcl
    # A cell with no device in its declared netlist is not extracted at all.
    assert 'load cells__fill_1' not in tcl
    assert view['extracted'] == ['cells__nand2_1']
    # A cell the layout could not stand in for keeps its schematic, by name.
    assert view['kept_schematic'] == {
        'cells__dffq_1': 'no device extracted from the declared layout',
        'cells__inv_1': 'no device extracted from the declared layout'}
    assert view['view'] == 'mixed'
    text = Path(view['path']).read_text()
    assert '.subckt cells__nand2_1 A1 A2 ZN VDD VNW VPW VSS' in text
    assert 'ad=0.3608p' in text and 'C21 ZN VPW 0.27964f' in text


def test_correlation_always_extracts_small_rc_networks(tmp_path, monkeypatch):
    root = _pdk(tmp_path)
    netlist = write(tmp_path / 'design/nl.v', NETLIST)
    monkeypatch.setattr(pst, '_docker', _magic_edge([]))
    view = pst.cell_view('img', tmp_path / 'design', [(root / 'x', '/pdk/x')],
                         config={'CELL_GDS': ['/pdk/x/cells.gds']}, pdk_dir=root / 'x',
                         guest_root='/pdk', pdk='x', netlist=netlist,
                         cell_sources=[root / 'x/libs.ref/cells/spice/cells.spice'],
                         out_dir=tmp_path / 'out')
    commands = (tmp_path / 'out/extract/extract.tcl').read_text()
    assert commands.index('extresist mindelay 0\n') < commands.index('extresist all\n')
    assert view['extresist_mindelay_ps'] == 0
    assert 'cells__nand2_1' in view['extracted']


def test_detailed_extraction_preserves_native_private_signal_splits(tmp_path, monkeypatch):
    root = _pdk(tmp_path)
    cell = 'cells__nand2_1'
    native = EXTRACTED_NAND2.replace(' VNW VPW\n', ' VNW VPW private.n0 private.t0\n')
    native = native.replace('X1 ZN A1 a_245_68#', 'X1 ZN A1 private.n0')
    native = native.replace('X3 a_245_68# A2', 'X3 private.t0 A2')
    native = native.replace('.ends', 'R0 private.n0 private.t0 100\n.ends')
    ports = ['A1', 'A2', 'ZN', 'VDD', 'VNW', 'VPW', 'VSS']
    def magic(*args, **kwargs):
        work = Path(args[4])
        write(work / f'{cell}.spice', native)
        write(work / f'{cell}.ext', '\n'.join(f'port "{p}" 0' for p in ports))
        write(work / f'{cell}.res.ext', 'rnode "private.n0" 0\nrnode "private.t0" 0\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(pst, '_docker', magic)
    view = pst.extract_cells('img', tmp_path, [], gds=['neutral.gds'], magicrc='neutral.magicrc',
        guest_root='/pdk', schematic={cell: ports}, cells=[cell], out_dir=tmp_path / 'out')
    assert cell in view['extracted']
    body = Path(view['path']).read_text()
    assert f'.subckt {cell} ' + ' '.join(ports) + '\n' in body
    assert 'R0 private.n0 private.t0 100\n' in body
    assert 'X1 ZN A1 private.n0' in body and 'X3 private.t0 A2' in body


def test_the_first_definition_of_a_cell_is_the_one_the_deck_simulates(tmp_path):
    extracted = write(tmp_path / 'x.spice', '.subckt cells__nand2_1 A1 A2 ZN VDD VNW VPW VSS\n'
                      + EXTRACTED_NAND2.split('\n', 3)[3])
    schematic = write(tmp_path / 's.spice', SCHEMATIC)
    volts = {'VDD': 5.0, 'VNW': 5.0, 'VSS': 0.0, 'VPW': 0.0}
    pst.fold_subckts([extracted, schematic], volts, 'VDD', 'VSS', tmp_path / 'f.spice')
    text = (tmp_path / 'f.spice').read_text()
    assert text.lower().count('.subckt cells__nand2_1 ') == 1
    assert 'ad=0.3608p' in text and 'X_i_1 net_0' not in text
    assert text.lower().count('.subckt cells__dffq_1 ') == 1       # the rest: unchanged


def test_a_pdk_that_declares_no_layout_or_rcfile_simulates_the_schematic_and_says_so(
        tmp_path, monkeypatch):
    root = _pdk(tmp_path)
    netlist = write(tmp_path / 'design/nl.v', NETLIST)
    monkeypatch.setattr(pst, '_docker', lambda *a, **k: pytest.fail('no extraction to run'))
    args = dict(pdk_dir=root / 'x', guest_root='/pdk', pdk='x', netlist=netlist,
                cell_sources=[root / 'x/libs.ref/cells/spice/cells.spice'],
                out_dir=tmp_path / 'out')
    view = pst.cell_view('img', tmp_path, [], config={}, **args)
    assert view == {'view': 'schematic', 'sources': [], 'reason': 'no CELL_GDS declared'}
    (root / 'x/libs.tech/librelane/config.tcl').write_text('set ::env(FP_TAPCELL_DIST) 20\n')
    view = pst.cell_view('img', tmp_path, [], config={'CELL_GDS': ['/pdk/x/g.gds']}, **args)
    assert view['view'] == 'schematic' and 'no MAGICRC declared' in view['reason']


def test_step_30_records_the_cell_view_it_simulated(tmp_path, monkeypatch):
    project = tmp_path / 'design'
    folder, _ = t106._stapostpnr(project)
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics'].update({f'timing__setup__ws__corner:{corner}':
                             -1.0 if corner == 'max_ss_125C_4v50' else 1.0
                             for corner in t106.CORNERS})
    put(folder / 'state_out.json', state)
    root = tmp_path / 'pdkroot'
    write(root / 'x/libs.ref/cells/lib/cells__ss_125C_4v50.lib', t106.LIBERTY)
    write(root / 'x/libs.ref/cells/spice/cells.spice',
          '.SUBCKT cells__dffq_1 D CLK Q VDD VNW VPW VSS\n'
          'X_i_0 Q D VSS VPW nfet_05v0 W=8.2e-07 L=6e-07\n.ENDS\n')
    write(root / 'x/libs.tech/ngspice/m.ngspice', t106.MODELS)
    write(root / 'x/libs.tech/librelane/config.tcl', CONFIG_TCL)
    config = json.loads((folder / 'config.json').read_text())
    config['CELL_SPICE_MODELS'] = ['/pdk/x/libs.ref/cells/spice/cells.spice']
    config['CELL_GDS'] = ['/pdk/x/libs.ref/cells/gds/cells.gds']
    put(folder / 'config.json', config)
    calls = []
    wps = t106._wps_edge(calls)
    dff = ('* NGSPICE file created from cells__dffq_1.ext\n'
           '.subckt cells__dffq_1 VDD VSS Q D CLK VNW VPW\n'
           'X0 Q D VSS VPW nfet_05v0 ad=0.2p pd=1.4u as=0.2p ps=1.4u w=0.82u l=0.6u\n'
           'C0 Q VSS 0.05f\n.ends\n')
    magic = _magic_edge(calls, {'cells__dffq_1': dff})

    def edge(image, project_, mounts, argv, cwd, docker='docker', env=None):
        return (magic if argv[0] == 'magic' else wps)(image, project_, mounts, argv, cwd, docker)
    monkeypatch.setattr(pst, '_docker', edge)
    doc = pst.run_step30(project, 'img', root, 'x', paths=1, simulators=('ngspice',))
    assert doc['arms']['ngspice']['cell_view'] == 'layout-extracted'
    folded = Path(doc['detail']['ngspice']['base']['cells']['path']).read_text()
    assert '.subckt cells__dffq_1 D CLK Q VDD VSS' in folded      # schematic order, folded rails
    assert 'ad=0.2p' in folded and 'W=8.2e-07' not in folded


# ------------------------------------------------ what the simulators read ---

def test_both_simulators_read_the_tool_subckts_with_device_lines_at_column_zero(tmp_path, monkeypatch):
    """`fold_subckts` indents parameterised device calls for OpenSTA's reader.
    MEASURED: Xyce reads an indented line as a continuation of the line
    before ("Unrecognized fields for device D37", a pad diode followed by an
    indented X line) and aborted every deck."""
    subckt = write(tmp_path / 'path_1.sp_1.subckt',
                   '.subckt pad PAD Y VDD VSS\nD37 VSS n0 diode_pd2nw_06v0 m=1.0 area=230.4e-15\n'
                   ' X38 n1 n0 VSS VSS nfet_06v0 m=1.0 w=3e-6 l=700e-9\n+ ad=1.32e-12\n.ends\n')
    deck = write(tmp_path / 'path_1.sp_1.sp',
                 '* Path\n.include "/g/models.sp"\n.include "path_1.sp_1.subckt"\n'
                 '.tran 1e-13 2e-08\n.print tran v(a)\nv1 a 0 4.5\n.end\n')
    seen = []
    monkeypatch.setattr(pst, '_docker', lambda image, project, mounts, argv, cwd, docker='docker',
                        env=None: seen.append(Path(argv[-1]).read_text())
                        or SimpleNamespace(returncode=0, stdout='', stderr=''))
    for simulator in ('xyce', 'ngspice'):
        pst._simulate(deck, simulator, 'img', tmp_path, [], step_s=1e-11)
        assert '.include "path_1.sp_1.run.subckt"' in seen[-1], simulator
        assert '.include "/g/models.sp"' in seen[-1]
    runnable = (tmp_path / 'path_1.sp_1.run.subckt').read_text()
    assert 'D37 VSS n0 diode_pd2nw_06v0 m=1.0 area=230.4e-15\nX38 n1 n0' in runnable
    assert '\n+ ad=1.32e-12\n' in runnable
    assert ' X38' in subckt.read_text()            # the reader's copy is untouched


XYCE_CSV = ('TIME,V(U_CORE\\/_417_/CLK),V(U_CORE\\/_417_/Q),V(U_CORE\\/_416_/D)\n'
            + ''.join(f'{i * 1e-10:.8e},{0.0 if i < 3 else 4.5},{4.5 if i < 5 else 0.0},'
                      f'{4.5 if i < 9 else 0.0}\n' for i in range(12)))


def test_the_xyce_arm_reads_the_csv_table_the_tool_deck_names(tmp_path):
    table = write(tmp_path / 'path_1.sp_1.csv', XYCE_CSV)
    deck = write(tmp_path / 'path_1.sp_1.sp',
                 f'.print tran format=csv file={table} v(u_core\\/_417_/CLK)\n'
                 'v2 u_core\\/_417_/VDD 0 4.500\n.tran 1e-13 2e-9\n')
    sta = {'startpoint': 'u_core/_417_', 'endpoint': 'u_core/_416_', 'endpoint_transition': 'fall',
           'start_row': {'inst': 'u_core/_417_', 'pin': 'u_core/_417_/Q', 'tr': 'v', 'cell': 'x'},
           'rows': [{'inst': 'u_core/_417_', 'pin': 'u_core/_417_/Q', 'tr': 'v', 'cell': 'x'},
                    {'inst': 'u_core/_416_', 'pin': 'u_core/_416_/D', 'tr': 'v', 'cell': 'x'}]}
    header = {'input_threshold_fall': 50.0, 'output_threshold_fall': 50.0}
    got = pst.measure(deck, 'xyce', sta, header)
    assert got['status'] == 'MEASURED'
    assert got['spice_ns'] == pytest.approx(0.4)
    assert pst.xyce_table(deck) == table


# ---------------------------------------------------------- the ratchets ---

def test_the_not_prose_claim_for_the_subckt_reader_is_falsifiable():
    """`subckt_devices` counts device lines by the netlist grammar's first
    letter; a comment spelling a denial is not a device and a denial token in
    a node name is not read. Zero counted devices never promotes a cell."""
    text = ('* no devices here, not extracted\n'
            '.subckt cells__a A Z VDD VSS\n'
            '* X_not a device: a comment\n'
            'X0 Z A not_denied VSS nfet_05v0 w=1u l=0.6u\n'
            'C0 Z VSS 0.1f\n'
            '.ends\n'
            '.subckt cells__b VDD VSS\n'
            '* nothing is NOT here\n'
            '.ends\n')
    assert pst.subckt_devices(text) == {'cells__a': (['A', 'Z', 'VDD', 'VSS'], 1),
                                        'cells__b': (['VDD', 'VSS'], 0)}


def test_the_pdk_magicrc_is_the_one_its_own_flow_config_declares(tmp_path):
    write(tmp_path / 'x/libs.tech/librelane/config.tcl', CONFIG_TCL)
    assert pst.pdk_magicrc(tmp_path / 'x', '/pdk', 'x') == (
        '/pdk/x/libs.tech/magic/x.magicrc', 'libs.tech/librelane/config.tcl:MAGICRC')
    assert pst.pdk_magicrc(tmp_path / 'y', '/pdk', 'y') is None


# ------------------------------------ r2: two arms are an agreement check ---

def _row(start, spice):
    return {'startpoint': start, 'endpoint': 'e', 'status': 'MEASURED', 'spice_ns': spice}


#: MEASURED on spm (layout-extracted cells, max_ss): the two paths both arms timed.
SPM_NGSPICE = [_row('u_core/_417_', 10.025510), _row('u_core/_417_b', 10.034072),
               {'startpoint': 'u_core/_417_c', 'endpoint': 'e', 'status': 'NOT_MEASURED'}]
SPM_XYCE = [_row('u_core/_417_', 10.023148), _row('u_core/_417_b', 10.035614),
            {'startpoint': 'u_core/_417_c', 'endpoint': 'e', 'status': 'NOT_MEASURED'}]
C = {'verdict': 'CORRELATED'}


def test_two_correlated_arms_within_one_percent_pass_on_agreement_and_report_ngspice():
    got = pst.step_verdict({'ngspice': C, 'xyce': C}, {'ngspice': SPM_NGSPICE, 'xyce': SPM_XYCE})
    assert (got['verdict'], got['verdict_basis'], got['reported_arm']) == ('PASS', 'AGREE', 'ngspice')
    assert got['arms_compared'] == ['ngspice', 'xyce']
    assert len(got['agreement']) == 2 and all(r['agree'] for r in got['agreement'])
    assert max(r['relative_delta'] for r in got['agreement']) == pytest.approx(0.000235, abs=1e-5)


def test_two_correlated_arms_beyond_one_percent_refuse_and_never_pick():
    # 1.2% apart: both are inside the STA tolerance, and still not one number.
    xyce = [_row('u_core/_417_', 10.025510 * 1.012), SPM_XYCE[1]]
    got = pst.step_verdict({'ngspice': C, 'xyce': C}, {'ngspice': SPM_NGSPICE, 'xyce': xyce})
    assert (got['verdict'], got['refusal'], got['verdict_basis']) == (
        'REFUSED', 'LL_SPICE_ARMS_DISAGREE', 'DISAGREE')
    assert 'reported_arm' not in got or got['verdict'] != 'PASS'
    # The boundary itself: exactly 1% agrees, a hair more does not.
    at = [_row('u_core/_417_', 10.0 * 1.01)]
    assert pst.step_verdict({'ngspice': C, 'xyce': C},
                            {'ngspice': [_row('u_core/_417_', 10.0)], 'xyce': at})['verdict'] == 'PASS'
    over = [_row('u_core/_417_', 10.0 * 1.0101)]
    assert pst.step_verdict({'ngspice': C, 'xyce': C},
                            {'ngspice': [_row('u_core/_417_', 10.0)], 'xyce': over})['verdict'] == 'REFUSED'


def test_two_correlated_arms_with_no_path_in_common_have_not_been_compared():
    got = pst.step_verdict({'ngspice': C, 'xyce': C},
                           {'ngspice': [_row('a', 10.0)], 'xyce': [_row('b', 10.0)]})
    assert (got['verdict'], got['refusal']) == ('REFUSED', 'LL_SPICE_ARMS_DISAGREE')


def test_one_correlated_arm_with_the_other_unavailable_passes_on_that_arm():
    refused = {'verdict': 'NOT_MEASURED', 'reason': 'LL_SPICE_DEVICE_UNMODELLED: xyce: ...'}
    got = pst.step_verdict({'ngspice': C, 'xyce': refused}, {'ngspice': SPM_NGSPICE, 'xyce': []})
    assert (got['verdict'], got['verdict_basis'], got['reported_arm']) == ('PASS', 'SINGLE_ARM', 'ngspice')
    assert got['not_measured'] == ['xyce']


def test_one_correlated_arm_beside_a_measured_mismatch_is_a_disagreement_not_a_pick():
    got = pst.step_verdict({'ngspice': C, 'xyce': {'verdict': 'MISMATCH'}},
                           {'ngspice': SPM_NGSPICE, 'xyce': SPM_XYCE})
    assert (got['verdict'], got['refusal']) == ('REFUSED', 'LL_SPICE_ARMS_DISAGREE')


def test_no_correlated_arm_fails_or_is_not_measured():
    assert pst.step_verdict({'ngspice': {'verdict': 'MISMATCH'}, 'xyce': {'verdict': 'MISMATCH'}},
                            {})['verdict'] == 'FAIL'
    assert pst.step_verdict({'ngspice': {'verdict': 'NOT_MEASURED'}}, {})['verdict'] == 'NOT_MEASURED'


def test_step_30_writes_the_step_verdict_not_a_selection(tmp_path, monkeypatch):
    """The landed T106 fixture: one ngspice arm, Xyce refused by its model tree."""
    project = tmp_path / 'design'
    folder, _ = t106._stapostpnr(project)
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics'].update({f'timing__setup__ws__corner:{corner}':
                             -1.0 if corner == 'max_ss_125C_4v50' else 1.0
                             for corner in t106.CORNERS})
    put(folder / 'state_out.json', state)
    root = tmp_path / 'pdkroot'
    write(root / 'x/libs.ref/cells/lib/cells__ss_125C_4v50.lib', t106.LIBERTY)
    write(root / 'x/libs.ref/cells/spice/cells.spice',
          '.SUBCKT cells__dffq_1 D CLK Q VDD VNW VPW VSS\n'
          'X_i_0 Q D VSS VPW nfet_05v0 W=8.2e-07 L=6e-07\n.ENDS\n')
    write(root / 'x/libs.tech/ngspice/m.ngspice', t106.MODELS)
    (root / 'x/libs.tech/xyce').mkdir(parents=True)
    config = json.loads((folder / 'config.json').read_text())
    config['CELL_SPICE_MODELS'] = ['/pdk/x/libs.ref/cells/spice/cells.spice']
    put(folder / 'config.json', config)
    monkeypatch.setattr(pst, '_docker', t106._wps_edge([]))
    doc = pst.run_step30(project, 'img', root, 'x', paths=1)
    written = json.loads((project / 'reports/phase3/spice_path_tool.json').read_text())
    assert 'selection' not in written
    assert 'selection' not in written
    # The fixture's liberty gives no stage tables: the arm cannot derive its
    # tolerance, so the step does not pass on it.
    assert (written['verdict'], written['verdict_basis']) == ('FAIL', 'NO_ARM_CORRELATED')
    assert written['arm_verdicts'] == {'ngspice': 'TOLERANCE_UNDERIVABLE'}
    assert written['not_measured'] == ['xyce'] and doc['verdict'] == 'FAIL'
    judge = pst.judge
    monkeypatch.setattr(pst, 'judge', lambda *a: dict(judge(*a), verdict='CORRELATED'))
    doc = pst.run_step30(project, 'img', root, 'x', paths=1)
    written = json.loads((project / 'reports/phase3/spice_path_tool.json').read_text())
    assert (written['verdict'], written['verdict_basis'], written['reported_arm']) == (
        'PASS', 'SINGLE_ARM', 'ngspice')
    assert written['not_measured'] == ['xyce']


# The Step-30 producer must publish the native full-RC cell through the same
# public interface, without shorting resistance-split well contacts.
def _full_rc_arm(tmp_path, monkeypatch, *, style='ngspice(hrhc)',
                 registered_pdk='x', registered_lib='cells__ss_125C_4v50.lib',
                 declared_styles='(),(hrhc),(lrlc)', resistor='R0 VNW well_contact 125',
                 external_port=False):
    project = tmp_path / 'design'
    folder, _ = t106._stapostpnr(project)
    root = tmp_path / 'pdkroot'
    lib = '/pdk/x/libs.ref/cells/lib/cells__ss_125C_4v50.lib'
    write(root / 'x/libs.ref/cells/lib/cells__ss_125C_4v50.lib', t106.LIBERTY)
    source = write(root / 'x/libs.ref/cells/spice/cells.spice',
                   '.subckt cells__dffq_1 D CLK Q VDD VNW VPW VSS\n'
                   'X0 Q D VSS VPW nfet_05v0 W=1u L=0.6u\n.ends\n')
    write(root / 'x/libs.tech/ngspice/m.ngspice', t106.MODELS)
    write(root / 'x/libs.tech/librelane/config.tcl', CONFIG_TCL)
    write(root / 'x/libs.tech/magic/x.tech',
          f'extract\n style ngspice variants {declared_styles}\nend\n')
    registry = put(tmp_path / 'registry.json', {'pdks': [{
        'name': registered_pdk, 'magic_extraction': {
            'tech': 'libs.tech/magic/x.tech',
            'source': {'scope': 'SOURCE_FIXTURE_ONLY explicit neutral PDK declaration'},
            'liberties': {registered_lib: style}}}]})
    monkeypatch.setattr(pst, '_EXTRACTION_CORNERS', registry, raising=False)
    config = json.loads((folder / 'config.json').read_text())
    config.update(CELL_SPICE_MODELS=['/pdk/x/libs.ref/cells/spice/cells.spice'],
                  CELL_GDS=['/pdk/x/libs.ref/cells/gds/cells.gds'])
    put(folder / 'config.json', config)
    # This is a neutral process substitution, not a native Magic result.
    # The extra port is deliberately not a guessed '.tN' name.
    native = ('.subckt cells__dffq_1 VDD VSS Q D CLK VNW VPW\n'
              '+ well_contact\n'
              'X0 Q D VSS well_contact nfet_05v0 W=1u L=0.6u\n'
              + resistor + '\nC0 Q well_contact 0.05f\n.ends\n')
    contact = 'TEST' if external_port else 'well_contact'
    native = native.replace('well_contact', contact)
    calls = []
    def tool(image, project_, mounts, argv, cwd, docker='docker', env=None):
        calls.append(argv)
        if argv[0] == 'magic':
            write(Path(cwd) / 'cells__dffq_1.spice', native)
            public = ['D', 'CLK', 'Q', 'VDD', 'VNW', 'VPW', 'VSS']
            if external_port:
                public.append(contact)
            write(Path(cwd) / 'cells__dffq_1.ext',
                  '\n'.join(f'port "{name}" {i} 0 0 0 0 m1'
                            for i, name in enumerate(public, 1)) + '\n')
            write(Path(cwd) / 'cells__dffq_1.res.ext', f'rnode "{contact}" 0 0 0 0 0\n')
        else:
            assert argv[0] == 'sta'
        return SimpleNamespace(returncode=0,
            stdout='VIBEIC_STA_DERATE set_timing_derate -late 1.0\nSOURCE_FIXTURE_ONLY\n', stderr='')
    monkeypatch.setattr(pst, '_docker', tool)
    def run():
        arm = pst.prepare_arm(project, 'img', folder / 'state_out.json',
                              'max_ss_125C_4v50', pdk_root=root, pdk='x',
                              out_dir=tmp_path / 'arm', paths=1)
        tcl = (tmp_path / 'arm/extract/extract.tcl').read_text()
        return arm, tcl, calls, lib, source
    return run


@pytest.mark.parametrize('style', ['ngspice(hrhc)', 'ngspice()', 'ngspice(lrlc)'])
def test_step30_uses_the_selected_library_declared_style_and_full_rc(tmp_path, monkeypatch, style):
    arm, tcl, calls, lib, source = _full_rc_arm(tmp_path, monkeypatch, style=style)()
    assert f'extract style {style}\n' in tcl
    order = ['extract do resistance', 'extract all', 'extresist extout on',
             'extresist threshold 0', 'extresist all', 'ext2spice scale off',
             'ext2spice lvs', 'ext2spice cthresh 0', 'ext2spice rthresh 0',
             'ext2spice extresist on']
    commands = [line.strip() for line in tcl.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    offsets = [next(i for i, line in enumerate(commands) if line.startswith(command))
               for command in order]
    assert offsets == sorted(offsets)
    view = arm['cells']['cell_view']
    assert view['extraction_corner']['status'] == 'QUALIFIED'
    assert view['extraction_corner']['liberty'] == lib
    assert view['extraction_corner']['style'] == style
    assert view['view'] == 'layout-extracted' and view['kept_schematic'] == {}
    canonical = Path(view['path']).read_text()
    assert '.subckt cells__dffq_1 D CLK Q VDD VNW VPW VSS\n' in canonical
    assert 'R0 VNW well_contact 125\n' in canonical
    assert 'X0 Q D VSS well_contact nfet_05v0 W=1u L=0.6u\n' in canonical
    folded = Path(arm['cells']['path']).read_text()
    assert '.subckt cells__dffq_1 D CLK Q VDD VSS\n' in folded
    assert 'R0 VDD well_contact 125\n' in folded
    assert 'X0 Q D VSS well_contact nfet_05v0' in folded
    assert arm['cells']['cell_view']['missing_exports'] == []
    assert [command[0] for command in calls] == ['magic', 'sta']


@pytest.mark.parametrize('missing', ['kit', 'library'])
def test_step30_does_not_borrow_another_kit_or_library_extraction_corner(tmp_path, monkeypatch, missing):
    kwargs = {'registered_pdk': 'other'} if missing == 'kit' else {'registered_lib': 'other__ss.lib'}
    arm, tcl, _, _, _ = _full_rc_arm(tmp_path, monkeypatch, **kwargs)()
    assert '\nextract style ' not in tcl
    assert arm['cells']['cell_view'].get('extraction_corner', {}).get('status') == 'UNQUALIFIED'
    assert arm['cells']['cell_view']['extraction_corner']['style'] is None
    assert 'ext2spice extresist on' in tcl


def test_step30_refuses_a_bound_style_absent_from_the_installed_technology(tmp_path, monkeypatch):
    run = _full_rc_arm(tmp_path, monkeypatch, declared_styles='()')
    with pytest.raises(pst.Refusal) as err:
        run()
    assert err.value.code == 'LL_SPICE_EXTRACTION_STYLE_UNDECLARED'


@pytest.mark.parametrize('resistor', ['', 'R0 VNW well_contact 125\nR1 well_contact Q 50'])
def test_step30_keeps_native_private_ports_without_a_public_resistor_anchor(tmp_path, monkeypatch, resistor):
    arm, _, _, _, _ = _full_rc_arm(tmp_path, monkeypatch, resistor=resistor)()
    view = arm['cells']['cell_view']
    assert view['extracted'] == ['cells__dffq_1']
    assert view['view'] == 'layout-extracted'
    assert 'well_contact' in Path(arm['cells']['path']).read_text()


def test_step30_keeps_a_real_extra_external_pin_mismatched_even_when_resistively_tied(tmp_path, monkeypatch):
    arm, _, _, _, _ = _full_rc_arm(tmp_path, monkeypatch, external_port=True)()
    view = arm['cells']['cell_view']
    assert view['extracted'] == []
    assert view['view'] == 'schematic'
    assert 'TEST' in view['kept_schematic']['cells__dffq_1']
    assert 'not the schematic ports' in view['kept_schematic']['cells__dffq_1']


def test_step30_current_consumer_rechecks_the_selected_extraction_corner(tmp_path, monkeypatch):
    import test_default_si_spice_power as ordinary
    project, folder, lib = ordinary.project(tmp_path)
    root = project / 'fixture_pdk'
    write(root / 'neutral/libs.tech/magic/neutral.tech',
          'extract\n style ngspice variants (),(hrhc)\nend\n')
    registry = {'pdks': [{'name': 'neutral', 'magic_extraction': {
        'tech': 'libs.tech/magic/neutral.tech',
        'source': {'scope': 'SOURCE_FIXTURE_ONLY neutral corner declaration'},
        'liberties': {lib.name: 'ngspice()'}}}]}
    data = put(tmp_path / 'extraction-corners.json', registry)
    monkeypatch.setattr(pst, '_EXTRACTION_CORNERS', data, raising=False)
    assert ordinary.spice_produce(project, folder, lib, monkeypatch)['status'] == 'RAN'
    assert ordinary.SC.main([str(project), '--no-spice', '--json', str(project / 'gate.json')]) == 0
    # No PDK/Liberty/tool output changes: only the actual selected owner data
    # changes. The existing consumer must reject its previous current result.
    registry['pdks'][0]['magic_extraction']['liberties'][lib.name] = 'ngspice(hrhc)'
    put(data, registry)
    assert ordinary.SC.main([str(project), '--no-spice', '--json', str(project / 'gate.json')]) == 1
    assert 'CURRENT_STEP30_INPUT_BYTES_CHANGED' in (project / 'gate.json').read_text()


def test_step30_does_not_reload_the_extraction_style_between_layout_cells(tmp_path):
    cells = ['neutral__logic', 'neutral__buffer', 'neutral__register']
    style = 'ngspice(hrhc)'
    actual = pst.extraction_tcl(['neutral.gds'], cells, tmp_path, extract_style=style)
    commands = [line.strip() for line in actual.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    # Reloading a style is a session-wide state change, even when its name
    # is unchanged. No such reload may occur after a cell starts extracting.
    assert [line for line in commands if line.startswith('extract style ')] == [
        f'extract style {style}']
    assert commands.index('gds read neutral.gds') < commands.index(f'extract style {style}')
    assert commands.index(f'extract style {style}') < commands.index(f'load {cells[0]}')
    # Each cell still receives the existing complete RC recipe, unchanged
    # except that its shared session has already selected the technology.
    for cell in cells:
        recipe = pst._mx.build_extraction_tcl(
            cell, str(tmp_path / f'{cell}.spice'),
            pst._mx.MagicResimExtractOptions(extract_style=None, extresist_mindelay_ps=0))
        assert recipe in actual
    assert commands.count('extract all') == len(cells)
    assert commands.count('extresist all') == len(cells)
    assert commands.count('ext2spice extresist on') == len(cells)


# Native processes below are SOFTWARE_FIXTURE_ONLY. The ordinary simulation,
# interpolation, judgment, publication and strict current consumer are real.
_REFERENCE_LIB = '''library(neutral_typ) {
 time_unit : "1ns";
 capacitive_load_unit(1,pf);
 nom_voltage : 1.8;
 nom_temperature : 25;
 operating_conditions(typ) { voltage : 1.8; temperature : 25; }
 normalized_driver_waveform(ndw) {
  driver_waveform_name : "fall_ndw";
  index_1("0.1,0.3");
  index_2("0,.05,.15,.25,.35,.45,.55,.65,.75,.85,.95,.99,1");
  values("1,.95,.85,.75,.65,.55,.45,.35,.25,.15,.05,.01,0",
         "1,.95,.85,.75,.65,.55,.45,.35,.25,.15,.05,.01,0");
 }
 cell(BUF) {
  pin(A) { direction : input; driver_waveform_fall : fall_ndw; }
  pin(Z) { direction : output;
   timing() { related_pin : "A"; timing_sense : positive_unate;
    cell_fall(t) { index_1("0.1,0.3"); index_2("0.01,0.03");
     values("0.9,1.0", "1.0,1.1"); }
   }
  }
 }
}
'''


def _reference_report(cell, inst, slew, cap, delay, *, external=False):
    first, last = ('I', 'Z') if external else ('launch', 'capture')
    before = (f' 0.002 {slew:.9f} 0 0 v I (in)\n' if external else
              ' 0.002 0.1 0 0 v launch/Q (DFF)\n')
    return (f'Startpoint: {first}\nEndpoint: {last}\n' + before
            + f' {slew:.9f} 0.05 0.05 v {inst}/A ({cell})\n'
            + f' {cap:.9f} 0.2 {delay:.9f} {delay + .05:.9f} v {inst}/Z ({cell})\n'
            + f' 0.2 0.05 {delay + .1:.9f} v '
            + ('Z (out)' if external else 'capture/D (DFF)') + '\n')


def _native_reference_transport(tmp_path, monkeypatch, *, damage='', companion=False):
    import re
    import test_default_si_spice_power as ordinary
    p, folder, lib = ordinary.project(tmp_path)
    lib.write_text(_REFERENCE_LIB)
    if damage == 'no_ndw':
        lib.write_text(lib.read_text().replace('driver_waveform_fall : fall_ndw;', ''))
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['liberty_files'] = {key: ordinary.LC.digest(lib) for key in fp['liberty_files']}
    fp['config_files'].update(fp['liberty_files'])
    ordinary.seal(folder, fp)
    # Reuse the existing current-subject/material setup; the next ordinary
    # producer retires this prior receipt before running the actual helpers.
    ordinary.spice_produce(p, folder, lib, monkeypatch)
    calls, points, main_delays = [], {}, {}

    def tool(image, project, mounts, argv, cwd, **_kwargs):
        calls.append((argv, Path(cwd)))
        cwd = Path(cwd)
        if argv[0] == 'sta':
            text = Path(argv[-1]).read_text()
            assert 'read_spef' not in text and 'set_load' not in text
            assert 'set_pi_model u_ref/Z' in text
            assert 'write_path_spice' in text and 'set_input_transition -fall' in Path(cwd / 'reference.sdc').read_text()
            slew = float(re.search(r'set_input_transition -fall (\S+)', (cwd / 'reference.sdc').read_text())[1])
            cap = float(re.search(r'set_pi_model u_ref/Z (\S+)', text)[1])
            delay = .8 + .5 * slew + 5 * cap
            points[cwd] = (slew, cap, delay)
            write(cwd / 'reference.rpt', _reference_report('BUF', 'u_ref', slew, cap, delay, external=True))
            write(cwd / 'reference.sp_1.sp', '* native reference fixture\n'
                  '.include "reference.sp_1.subckt"\n.tran 1e-13 8e-9\n'
                  '.print tran v(I) v(u_ref/A) v(u_ref/Z) v(Z)\n'
                  'v1 u_ref/VDD 0 1.8\nv2 u_ref/VSS 0 0\nv3 I 0 pwl(0 1.8 1e-9 0)\n.end\n')
            write(cwd / 'reference.sp_1.subckt', '.subckt ref I Z\nX0 Z I 0 0 neutral\n.ends\n')
            return SimpleNamespace(returncode=int(damage == 'partial' and cwd.name == '0'),
                                   stdout='SOFTWARE_FIXTURE_ONLY reference STA\n', stderr='')
        assert argv[0] == 'ngspice'
        text = Path(argv[-1]).read_text()
        wave = Path(re.search(r'wrdata (\S+)', text)[1])
        if 'refs' in cwd.parts:
            delay = points[cwd][2] * .7  # independent fixed model-vs-table basis
            names = ['I', 'u_ref/A', 'u_ref/Z', 'Z']
            delays = [0, 0, delay, delay]
        else:
            delay = main_delays[cwd]
            names = ['launch/Q', 'capture/D']
            delays = [0, delay]
        rows = ['time ' + ' '.join('v(' + n + ')' for n in names)]
        for t in sorted({0, 8.0, *[1 + d + off for d in delays for off in (-.001, .001)]}):
            rows.append(' '.join([str(t * 1e-9)]
                        + [str(1.8 if t <= 1 + d - .001 else 0) for d in delays]))
        write(wave, '\n'.join(rows) + '\n')
        return SimpleNamespace(returncode=int(companion and cwd.name == 'mutated'),
                               stdout='SOFTWARE_FIXTURE_ONLY ' + ('ref NG' if 'refs' in cwd.parts else 'WHOLE DESIGN NG'), stderr='')
    monkeypatch.setattr(pst, '_docker', tool)

    if damage in ('arc', 'pvt', 'view', 'execution'):
        native = pst._native_grid_reference
        def wrong(*args):
            got = native(*args)
            if damage == 'execution':
                got['executions'] = []
            else:
                got['identity'] = dict(got['identity'])
                got['identity'][{'arc': 'out_pin', 'pvt': 'temperature', 'view': 'cell_view_sha256'}[damage]] = 'foreign'
            return got
        monkeypatch.setattr(pst, '_native_grid_reference', wrong)

    def run(project, image, root, pdk, **_kwargs):
        detail = {}
        state = folder / 'state_out.json'
        inputs = ordinary.LC.post_pnr_timing_inputs(p, state, 'nom_typ')
        for variant in ('base', 'mutated'):
            directory = p / 'phase3/tool_arms/30/ngspice' / variant
            directory.mkdir(parents=True, exist_ok=True)
            cap, wire = (.02, .1) if variant == 'base' else (.025, .2)
            cell_delay = .8 + .5 * .2 + 5 * cap
            main_delays[directory] = cell_delay * .7 + wire + (.5 if damage == 'wire' else 0)
            if damage == 'removed_stage':
                main_delays[directory] = wire
            if damage == 'raw_good_partial':
                main_delays[directory] = cell_delay + wire
            cells = write(directory / 'cells_folded.spice', '.subckt BUF A Z VDD VSS\n X0 Z A VDD VSS neutral\n.ends\n')
            models = write(directory / 'models_ngspice.sp', '.model neutral nmos level=1\n')
            deck = write(directory / 'path_1.sp', '* Gate u0 A -> Z\nxu0 u0/A u0/Z u0/VDD u0/VSS BUF\n'
                         'v1 u0/VDD 0 1.8\nv2 u0/VSS 0 0\n.ends\n'
                         '.tran 1e-13 8e-9\n.print tran v(launch/Q) v(capture/D)\n.end\n')
            dcalc = write(directory / 'dcalc.rpt', 'Library: neutral_typ\nCell: BUF\nA v -> Z v\n'
                          f'------- input_net_transition = 0.200000000\n'
                          f'| total_output_net_capacitance = {cap:.9f}\n'
                          f'Delay = {cell_delay + (.75e-6 if damage == 'codec' else 0):.9f}\n')
            parsed = pst.parse_path_report(_reference_report('BUF', 'u0', .2, cap + .005, cell_delay))
            parsed['path_delay_ns'] = cell_delay + wire
            script = write(directory / 'arm.tcl', 'SOFTWARE_FIXTURE_ONLY main STA\nreport_dcalc\n')
            log = write(directory / 'sta.log', 'SOFTWARE_FIXTURE_ONLY main STA\n')
            arm = dict(corner='nom_typ', simulator='ngspice', inputs=inputs, ocv_late_derate=1.0,
                spef=str(p / inputs['spef']), spef_sha256=inputs['sha256']['spef'],
                cells={'path': str(cells)}, models={'path': str(models)},
                sta_rc=0, sta_execution={'tool': 'OpenSTA', 'rc': 0, 'argv': ['sta', str(script)],
                    'script': str(script), 'log': str(log)}, image=image, project=p, mounts=[],
                header=pst._scc.parse_liberty_header(lib.read_text()), liberty_text=lib.read_text(),
                liberty_sources=[{'path': str(lib), 'text': lib.read_text(), 'sha256': ordinary.LC.digest(lib)}],
                power='VDD', ground='VSS', clock_periods_ns=[10],
                prepared=[{'path': 1, 'parsed': parsed, 'deck': deck, 'wps_fail': [],
                           'dcalc': {('u0/A', 'u0/Z'): str(dcalc)}}])
            if damage == 'raw_good_partial':
                arm['liberty_sources'] = []
            detail[variant] = pst.simulate_arm(arm)
        judgment = pst.judge(detail['base'], detail['mutated'])
        doc = {'step': '30', 'corner': 'nom_typ', 'sta_state': str(state),
               'sta_state_sha256': ordinary.LC.digest(state), 'detail': {'ngspice': detail},
               'arms': {'ngspice': judgment}, **pst.step_verdict({'ngspice': judgment}, {'ngspice': detail['base']['paths']})}
        put(p / 'reports/phase3/spice_path_tool.json', doc)
        return doc
    monkeypatch.setattr(pst, 'run_step30', run)
    return ordinary, p, folder, lib, calls, points


@pytest.mark.parametrize('damage', ['', 'wire', 'removed_stage', 'partial', 'arc', 'pvt', 'view', 'no_ndw', 'codec'],
                         ids=['complete', 'wrong-wire', 'removed-stage', 'partial-ref', 'wrong-arc', 'wrong-pvt', 'wrong-view', 'no-ndw-binding', 'summed-print-float-codec'])
def test_step30_native_grid_separation_reaches_the_ordinary_consumer(tmp_path, monkeypatch, damage):
    ordinary, p, folder, lib, calls, points = _native_reference_transport(tmp_path, monkeypatch, damage=damage)
    result = ordinary.SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = ordinary.SC.run_audit(p)
    assert result['status'] == 'RAN', result
    doc = json.loads((p / 'reports/phase3/spice_path_tool.json').read_text())
    row = doc['detail']['ngspice']['base']['paths'][0]
    expected_good = damage in ('', 'codec')
    assert gate.passed is expected_good, gate.summary
    assert row['raw_verdict'] in ('MISMATCH', 'CRITICAL_MISMATCH')
    if damage in ('partial', 'arc', 'pvt', 'view', 'no_ndw'):
        assert not row['pdk_characterisation']['complete']
        assert row['design_reference_ns'] is None
        assert row['error_pct'] == row['raw_error_pct']
    else:
        assert row['pdk_characterisation']['complete']
        assert row['sta_wire_ns'] == pytest.approx(.1)
        assert row['design_reference_ns'] == pytest.approx(.8)
        assert len(row['pdk_characterisation']['references']) == 4
        assert {(s, c) for s, c, _ in points.values()} >= {(.1, .01), (.1, .03), (.3, .01), (.3, .03)}
        assert row['tolerance_pct'] == pytest.approx(pst._scc.derive_liberty_path_tolerance(
            _REFERENCE_LIB, pst.path_stages(pst.parse_path_report(_reference_report('BUF', 'u0', .2, .025, 1))['rows']), 1.1)['tolerance_pct'])
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    assert next(e for e in receipt['execution'] if e['tool'] == 'ngspice')['log'].endswith('/base/path_1.log')
    assert 'WHOLE DESIGN NG' in (p / 'phase3/stage3/spice/correlation.log').read_text()
    assert any('/base/refs/' in r['path'] for r in receipt['outputs']) is (damage != 'no_ndw')


def test_step30_partial_reference_keeps_the_original_raw_pass(tmp_path, monkeypatch):
    ordinary, p, _, lib, _, _ = _native_reference_transport(tmp_path, monkeypatch, damage='raw_good_partial')
    assert ordinary.SC.run_installed_pdk_path_correlation(p, str(lib))['status'] == 'RAN'
    assert ordinary.SC.run_audit(p).passed
    row = json.loads((p / 'reports/phase3/spice_path_tool.json').read_text())['detail']['ngspice']['base']['paths'][0]
    assert row['raw_verdict'] == 'CORRELATED' and not row['pdk_characterisation']['complete']
    assert row['design_reference_ns'] is None


@pytest.mark.parametrize('damage', ['wave', 'result', 'execution'])
def test_step30_current_consumer_binds_native_references(tmp_path, monkeypatch, damage):
    ordinary, p, _, lib, _, _ = _native_reference_transport(tmp_path, monkeypatch, damage='execution' if damage == 'execution' else '')
    result = ordinary.SC.run_installed_pdk_path_correlation(p, str(lib))
    if damage == 'execution':
        assert result['status'] == 'ERROR' and 'REFERENCE_EXECUTION_MISSING' in result['reason']
        return
    assert result['status'] == 'RAN' and ordinary.SC.run_audit(p).passed
    target = next((p / 'phase3/tool_arms/30/ngspice/base/refs').rglob('*.wave' if damage == 'wave' else 'result.json'))
    target.write_text(target.read_text() + '\nCHANGED\n')
    assert not ordinary.SC.run_audit(p).passed


@pytest.mark.parametrize('damage, expected', [('', False), ('wire', True)])
def test_step30_companion_uses_the_design_residual_not_the_raw_gap(tmp_path, monkeypatch, damage, expected):
    ordinary, p, _, lib, _, _ = _native_reference_transport(tmp_path, monkeypatch, damage=damage, companion=True)
    result = ordinary.SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = ordinary.SC.run_audit(p)
    assert not gate.passed
    assert (result['status'] == 'RAN') is expected, result
    if expected:
        assert gate.summary['measurement'] == 'MEASURED' and gate.summary['verdict'] == 'FAIL'
    else:
        assert gate.summary['measurement'] == 'NOT_MEASURED'

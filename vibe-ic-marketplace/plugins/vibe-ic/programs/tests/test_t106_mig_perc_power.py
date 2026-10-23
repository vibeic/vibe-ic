"""T106: steps 28, 29, 30, 33 read the post-route state the tool produced.

The programs run for real; only an EDA tool's file writes are substituted at
the subprocess edge. The report grammar below is the tool's own, copied from a
0.3.79 `OpenROAD.STAPostPNR` run and a `Vibeic.GateLevelSim` run on the spm
chip (paths shortened to `<run>`).
"""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
postroute = importlib.import_module('librelane_postroute')
sgs = importlib.import_module('sdf_gate_sim')
pst = importlib.import_module('path_spice_tool')
power = importlib.import_module('_ppa.power')

CORNERS = ('nom_tt_025C_5v00', 'max_ss_125C_4v50', 'max_ff_n40C_5v50')
LIB = {'tt': 'cells__tt_025C_5v00.lib', 'ss': 'cells__ss_125C_4v50.lib', 'ff': 'cells__ff_n40C_5v50.lib'}

POWER_RPT = '''
===========================================================================
 report_power
============================================================================
======================= {corner} Corner ===================================

Group                    Internal    Switching      Leakage        Total
                            Power        Power        Power        Power (Watts)
------------------------------------------------------------------------
Sequential           1.419380e-03 4.566406e-05 2.621685e-08 1.465070e-03   7.1%
Combinational        8.566633e-04 4.054849e-04 1.193024e-07 1.262267e-03   6.1%
Clock                1.071114e-02 3.138995e-03 1.274935e-06 1.385141e-02  66.7%
Macro                0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Pad                  3.679033e-03 5.068426e-04 1.543920e-07 4.186030e-03  20.2%
------------------------------------------------------------------------
Total                {internal} 4.096778e-03 1.584467e-06 {total} 100.0%
                            80.3%        19.7%         0.0%
'''

#: The corner totals of that run (W), nom_tt / max_ss / max_ff.
TOTALS = {'nom_tt_025C_5v00': ('1.666635e-02', '2.076471e-02'),
          'max_ss_125C_4v50': ('1.301814e-02', '1.650686e-02'),
          'max_ff_n40C_5v50': ('2.132108e-02', '2.646044e-02')}


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _lib_of(corner):
    return LIB[corner.split('_')[1]]


def _stapostpnr(project, *, metric_total=0.026460440829396248, activity=False):
    """A STAPostPNR step folder as LibreLane 3.1 leaves it, and step 23's record."""
    folder = project / 'phase3/librelane/22-23/02-openroad-stapostpnr'
    spef = {p: str(write(folder.parent / '01-openroad-rcx' / p.strip('*_') / 'chip_top.spef',
                         f'*SPEF {p}\n')) for p in ('nom_*', 'min_*', 'max_*')}
    sdf = {}
    for corner in CORNERS:
        d = folder / corner
        log = (f"Reading cell library for the '{corner}' corner at "
               f"'/pdk/x/libs.ref/cells/lib/{_lib_of(corner)}'\u2026\n")
        if activity:
            log += 'read_vcd /work/act.vcd\n'
        write(d / 'sta.log', log)
        internal, total = TOTALS[corner]
        write(d / 'power.rpt', POWER_RPT.format(corner=corner, internal=internal, total=total))
        sdf[corner] = str(write(d / f'chip_top__{corner}.sdf', '''(DELAYFILE
 (SDFVERSION "3.0") (DESIGN "chip_top") (DIVIDER .) (TIMESCALE 1ns)
 (CELL (CELLTYPE "chip_top") (INSTANCE)
  (DELAY (ABSOLUTE (INTERCONNECT clk u_core.CLK (0.001:0.001:0.001)))))
)\n'''))
    netlist = write(project / 'phase3/stage3/pnr/spm_pnr.v', CHIP_TOP)
    views = {v: str(write(project / f'phase3/stage3/pnr/chip_top.{v}', v))
             for v in ('odb', 'def', 'sdc')}
    state = put(folder / 'state_out.json', {
        **views, 'nl': str(netlist), 'sdf': sdf, 'spef': spef,
        'metrics': {'power__total': metric_total}})
    put(folder / 'config.json', {'meta': {'step': 'OpenROAD.STAPostPNR'},
                                 'DESIGN_NAME': 'chip_top', 'STA_CORNERS': list(CORNERS),
                                 'VDD_PIN': 'VDD', 'GND_PIN': 'VSS'})
    fingerprint = {'step': 'OpenROAD.STAPostPNR',
                   'state_files': {str(netlist.resolve()): contract.digest(netlist)}}
    put(folder / 'input_fingerprint.json', fingerprint)
    put(folder / 'pdk_root.json', {'path': '/fixture/pdk'})
    write(folder / 'invocation.log', 'fixture OpenROAD.STAPostPNR completed\n')
    names = ['state_out.json', 'config.json', 'input_fingerprint.json',
             'pdk_root.json', 'invocation.log']
    names += [str(Path(path).resolve().relative_to(folder.resolve()))
              for path in sdf.values()]
    put(folder / 'vibeic_receipt.json', {
        'input': fingerprint,
        'sha256': {name: contract.digest(folder / name) for name in names}})
    put(project / postroute.STEP23_RECORD, {'sta_state': str(state),
                                            'sta_state_sha256': contract.digest(state)})
    return folder, spef


CHIP_TOP = '''module chip_top (clk, x, p);
 input clk;
 input x;
 output p;
 wire n1;
 cells__in_c u_pad_x (.PAD(x), .Y(n1));
 cells__dffq_1 \\u_core/_416_  (.D(n1), .CLK(clk), .Q(p));
 cells__fill10 fill_0 ();
endmodule
'''


# ------------------------------------------------ step 23's state, consumed ---

def test_steps_29_and_33_refuse_by_name_when_step_23_did_not_run_on_the_tool(tmp_path):
    with pytest.raises(contract.Refusal) as err:
        postroute.stapostpnr_state(tmp_path)
    assert err.value.code == 'LL_STAPOSTPNR_STATE_ABSENT'


def test_a_state_other_than_the_one_step_23_recorded_is_refused(tmp_path):
    folder, _ = _stapostpnr(tmp_path)
    state = folder / 'state_out.json'
    state.write_text(state.read_text().replace('power__total', 'power__total_x'))
    with pytest.raises(contract.Refusal) as err:
        postroute.stapostpnr_state(tmp_path)
    assert err.value.code == 'LL_STAPOSTPNR_STATE_DRIFT'


# ---------------------------------------------------------------- step 33 ---

def test_per_corner_power_is_read_from_each_corner_report_never_the_unscoped_metric(tmp_path):
    folder, _ = _stapostpnr(tmp_path, metric_total=0.5)
    corners = power.stapostpnr_corner_power(folder)
    assert set(corners) == set(CORNERS)
    assert corners['nom_tt_025C_5v00']['total_w'] == pytest.approx(2.076471e-02)
    assert all(r['basis'] == power.BASIS_VECTORLESS for r in corners.values())
    assert 0.5 not in [r['total_w'] for r in corners.values()]


def test_a_corner_transcript_that_reads_activity_contradicts_the_tool_and_is_refused(tmp_path):
    folder, _ = _stapostpnr(tmp_path, activity=True)
    corners = power.stapostpnr_corner_power(folder)
    assert {r['status'] for r in corners.values()} == {power.STATUS_INVALID}


def _direct(basis, corroboration, total_raw='2.076471e-02'):
    report = {'total_row': {'total_w': float(total_raw), 'total_raw': total_raw}}
    return {'activity': {'basis': basis, 'corroboration': corroboration}}, report


def test_the_tool_is_canonical_without_a_corroborated_vector_basis_at_the_worst_corner(tmp_path):
    folder, _ = _stapostpnr(tmp_path)
    corners = power.stapostpnr_corner_power(folder)
    direct, report = _direct(power.BASIS_VECTORLESS, power.NO_CORROBORATION_NEEDED)
    out = power.signoff_power_arms(direct, report, corners, direct_liberty='/p/cells__tt_025C_5v00.lib',
                                   direct_spef_sha256=None, tool_spef_sha256={})
    assert out['canonical'] == 'librelane'
    assert out['worst_corner'] == 'max_ff_n40C_5v50'
    assert out['total_power_w'] == pytest.approx(2.646044e-02)
    assert out['agreement']['verdict'] == 'NOT_COMPARABLE'


def test_a_corroborated_vector_arm_is_canonical_whatever_the_numbers(tmp_path):
    folder, _ = _stapostpnr(tmp_path)
    corners = power.stapostpnr_corner_power(folder)
    direct, report = _direct(power.BASIS_VCD, power.CORROBORATED, total_raw='1.0e-03')
    out = power.signoff_power_arms(direct, report, corners, direct_liberty=None,
                                   direct_spef_sha256=None, tool_spef_sha256={})
    assert out['canonical'] == 'direct'
    direct, report = _direct(power.BASIS_VCD, power.UNCORROBORATED, total_raw='1.0e-03')
    assert power.signoff_power_arms(direct, report, corners, direct_liberty=None,
                                    direct_spef_sha256=None,
                                    tool_spef_sha256={})['canonical'] == 'librelane'


@pytest.mark.parametrize('direct_total,verdict', [('2.08e-02', 'AGREE'), ('2.15e-02', 'DISAGREE')])
def test_the_vectorless_arms_must_agree_on_the_same_liberty_and_spef_to_printed_resolution(
        tmp_path, direct_total, verdict):
    folder, _ = _stapostpnr(tmp_path)
    corners = power.stapostpnr_corner_power(folder)
    direct, report = _direct(power.BASIS_VECTORLESS, power.NO_CORROBORATION_NEEDED, direct_total)
    shas = {c: ('same' if c == 'nom_tt_025C_5v00' else 'other') for c in CORNERS}
    out = power.signoff_power_arms(direct, report, corners, direct_liberty='/p/cells__tt_025C_5v00.lib',
                                   direct_spef_sha256='same', tool_spef_sha256=shas)
    assert out['agreement']['verdict'] == verdict
    assert out['agreement']['corner'] == 'nom_tt_025C_5v00'


def _pdk(liberty):
    runner = importlib.import_module('phase3_one_shot_runner')
    return runner, runner.PdkConfig(name='fixture_pdk', liberty=liberty, tech_lef='/p/t.tlef',
                                    cell_lef='/p/c.lef', cell_gds=None, site='unit', drc_deck=None,
                                    metal_prefix='met', tapcell_master='cells__filltie')


def _current_power_scene(tmp_path):
    """Use the existing current-owner fixture, retaining all three power corners.

    Source fixtures only: this extends the native receipt shape rather than
    reviving the superseded State-only power adoption path.
    """
    from test_default_current_power import project, seal
    project_root, folder, library = project(tmp_path)
    config_path = project_root / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    names = ('nom_typ', 'min_typ', 'max_typ')
    config['STA_CORNERS'] = list(names)
    put(config_path, config)
    put(folder / 'config.json', config)
    for name, original in zip(names, CORNERS):
        write(folder / name / 'sta.log',
              f"SOURCE_FIXTURE_ONLY\nReading cell library for the '{name}' corner at '/pdk/neutral/neutral.lib'\n")
        internal, total = TOTALS[original]
        write(folder / name / 'power.rpt',
              POWER_RPT.format(corner=name, internal=internal, total=total))
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    fingerprint['config'] = contract.digest(config_path)
    seal(folder, fingerprint)
    return project_root, folder, library


def test_step_33_on_librelane_publishes_the_worst_corner_report_unedited(tmp_path):
    runner, _ = _pdk('/unused.lib')
    project, folder, library = _current_power_scene(tmp_path)
    rpt3 = runner._pl.reports_phase3_dir(project)
    written, notes = [], []
    runner._step33_tool_arm(project, 'neutral', _pdk(str(library))[1], 'librelane',
                            rpt3 / 'power.rpt', False, written, notes)
    record = json.loads((rpt3 / 'power.json').read_text())
    assert record['total_power_w'] == pytest.approx(2.646044e-02), notes
    assert record['power_basis'] == 'POST_ROUTE_SPEF'
    assert record['activity']['basis'] == power.BASIS_VECTORLESS
    assert (folder / 'max_typ/power.rpt').read_text() in (rpt3 / 'power.rpt').read_text()
    import _opensta_current as current
    current.power_binding(project)
    receipt = json.loads((rpt3 / 'power.current.json').read_text())
    assert receipt['tool_corner'] == 'max_typ'
    assert receipt['source_report']['sha256'] == contract.digest(folder / 'max_typ/power.rpt')
    arms = json.loads((rpt3 / 'power_arms.json').read_text())
    assert arms['canonical'] == 'current_opensta'
    assert arms['current_receipt_sha256'] == contract.digest(rpt3 / 'power.current.json')


def test_step_33_retires_an_unbound_direct_record_even_with_a_legacy_dual_flag(tmp_path):
    runner, pdk = _pdk('/p/cells__tt_025C_5v00.lib')
    _stapostpnr(tmp_path)
    rpt3 = runner._pl.reports_phase3_dir(tmp_path)
    put(rpt3 / 'power.json', {'total_power_w': 0.0215, 'activity': {'basis': 'VECTORLESS'}})
    write(rpt3 / 'power.rpt', 'Total 1.65e-02 4.94e-03 1.58e-06 2.15e-02 100.0%\n')
    notes = []
    runner._step33_tool_arm(tmp_path, 'spm', pdk, 'dual', rpt3 / 'power.rpt', True, [], notes)
    record = json.loads((rpt3 / 'power.json').read_text())
    assert record['power_measurement'] == 'NOT_MEASURED'
    assert record['verdict'] == 'NOT_MEASURED'
    assert 'total_power_w' not in record
    assert not (rpt3 / 'power_arms.json').exists()
    assert any('current power NOT_MEASURED' in note for note in notes)


# ---------------------------------------------------------------- step 29 ---

def test_native_sdf_exports_bind_the_actual_timed_netlist_and_all_corners(tmp_path):
    folder, _ = _stapostpnr(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    result = postroute.bind_stapostpnr_sdfs(folder, state,
                                          expected_netlist=Path(state['nl']))
    assert set(result['exports']) == set(CORNERS)
    assert result['netlist_sha256'] == contract.digest(Path(state['nl']))
    assert all(row['design'] == 'chip_top' and row['delay_record_count'] == 1
               for row in result['exports'].values())


@pytest.mark.parametrize('damage', ['stale_bytes', 'wrong_design', 'truncated', 'no_delays'])
def test_native_sdf_export_damage_refuses_before_simulator(tmp_path, damage):
    folder, _ = _stapostpnr(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    path = Path(state['sdf'][CORNERS[0]])
    text = path.read_text()
    if damage == 'wrong_design':
        text = text.replace('(DESIGN "chip_top")', '(DESIGN "other_top")')
    elif damage == 'truncated':
        text = text[:-3]
    elif damage == 'no_delays':
        text = text.replace('INTERCONNECT clk u_core.CLK (0.001:0.001:0.001)', 'ABSENT')
    else:
        text += '\n'
    path.write_text(text)
    if damage != 'stale_bytes':
        # A freshly hashed malformed export still cannot constitute an SDF.
        receipt_path = folder / 'vibeic_receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['sha256'][str(path.relative_to(folder))] = contract.digest(path)
        put(receipt_path, receipt)
    with pytest.raises(contract.Refusal):
        postroute.bind_stapostpnr_sdfs(folder, state)

TB = '''`timescale 1ns/1ps
module tb_case;
  reg clk; reg x; wire p;
  spm dut (.clk(clk), .x(x), .p(p));
  always #5 clk = ~clk;
  initial begin clk = 0; x = 0; #100 $display("ORACLE_TB_DONE pass=1/1"); $finish; end
endmodule
'''

#: What the chip-top producer (step 15.5ic) writes: `chip_top` wraps `spm`,
#: x through a pad, clk and p wired to the chip ports (F21).
CHIP_TOP_IO = '''module chip_top (input clk, input x, output p);
  wire x__core;
  cells__in_c u_pad_x (.PAD(x), .Y(x__core));
  spm u_core (.clk(clk), .x(x__core), .p(p));
endmodule
'''


def _declare_chip_top(project):
    write(project / 'phase3/stage3/pnr/chip_top_io.v', CHIP_TOP_IO)
    put(project / sgs.CHIP_TOP_RECORD_REL, {
        'verdict': 'WROTE', 'chip_top_module': 'chip_top', 'core_module': 'spm',
        'chip_top_verilog': 'phase3/stage3/pnr/chip_top_io.v',
        'pad_instances': {'u_pad_x': {'port': 'x', 'terminal': 'PAD', 'core_pin': 'Y'}}})

VVP_PASS = ('SDF INFO: <run>/chip_top__{c}.sdf:15: Putting delay: 0.000000 for index 0\n'
            'SDF INFO: <run>/chip_top__{c}.sdf:16: Putting delay: 0.001000 for index 0\n'
            'ORACLE_TB_DONE pass=28/28\n')
VVP_SDF_ERROR = ('SDF ERROR: <run>/chip_top__{c}.sdf:2527: Unable to match ModPath S -> Z '
                 'in tb_case.dut.spare_mux2_0\n'
                 'SDF ERROR: <run>/chip_top__{c}.sdf:1540: Could not find intermodpath!\n')


def _pdk_tree(root):
    """Declared cell model needing a sibling UDP file, and a declared black-box
    pad file whose functional model sits beside it."""
    cells = root / 'x/libs.ref/cells/verilog'
    write(cells / 'cells.v', 'module cells__dffq_1 (D, CLK, Q); input D, CLK; output Q;\n'
                             '  cells__udp_ff(Q, D, CLK);\nendmodule\n'
                             'module cells__fill10 (); endmodule\n')
    write(cells / 'primitives.v', 'primitive cells__udp_ff (q, d, c);\n output q; reg q;\n'
                                  ' input d, c;\n table\n ? r : ? : 0;\n endtable\nendprimitive\n')
    pads = root / 'x/libs.ref/pads/verilog'
    write(pads / 'pads__blackbox_pp.v', 'module cells__in_c (PAD, Y); input PAD; output Y;\nendmodule\n')
    write(pads / 'pads.v', 'module cells__in_c (PAD, Y); input PAD; output Y;\n  buf #1 (Y, PAD);\nendmodule\n')
    return ['/pdk/x/libs.ref/cells/verilog/cells.v', '/pdk/x/libs.ref/pads/verilog/pads__blackbox_pp.v']


def test_the_model_closure_takes_the_udp_sibling_and_the_modelled_pad_not_the_black_box(tmp_path):
    declared = [tmp_path / p.replace('/pdk/', '') for p in _pdk_tree(tmp_path)]
    used = sgs.netlist_used_cells(CHIP_TOP)
    assert used == {'cells__in_c', 'cells__dffq_1', 'cells__fill10'}
    closure = sgs.verilog_model_closure(declared, used)
    names = [Path(f).name for f in closure['files']]
    assert names == ['cells.v', 'primitives.v', 'pads.v']
    assert closure['unresolved'] == [] and closure['blackboxed'] == ['cells__fill10']


def test_a_case_binds_to_the_netlist_top_only_when_its_ports_are_the_same(tmp_path):
    # F21: the rebinding is the DECLARED chip top's, never a port-name match.
    _declare_chip_top(tmp_path)
    declared = sgs.declared_dut_binding(tmp_path, 'spm', CHIP_TOP)
    text, binding = sgs.bind_dut_module(TB, 'spm', 'dut', CHIP_TOP, declared)
    assert 'chip_top dut (.clk(clk)' in text and binding['rebound']
    with pytest.raises(ValueError):
        sgs.bind_dut_module(TB.replace('.p(p)', '.q(p)'), 'spm', 'dut', CHIP_TOP, declared)
    with pytest.raises(ValueError):
        sgs.bind_dut_module(TB, 'spm', 'dut', CHIP_TOP)
    same = CHIP_TOP.replace('module chip_top', 'module spm')
    assert sgs.bind_dut_module(TB, 'spm', 'dut', same)[0] == TB


def _gls_project(tmp_path):
    project = tmp_path / 'design'
    put(project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains': [{'role': 'primary', 'period_ns': 24, 'source_pin': 'clk'}]})
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {})
    put(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {})
    put(project / 'input/submission_template/tapeout_declaration.json',
        {'answers': {'top_cell': 'chip_top'}})
    _stapostpnr(project)
    _declare_chip_top(project)
    write(project / 'phase3/stage3/pnr/chip_top.sdc',
          'create_clock -name clk -period 24.0 [get_ports clk]\n')
    tb = write(project / 'phase2/stage1/sim/tb_case.v', TB)
    put(project / 'reports/phase2/sim/l10_execution.json',
        {'cases': [{'id': 'case_1', 'sim_executed': True, 'tb_file': str(tb)}]})
    root = tmp_path / 'pdkroot'
    declared = _pdk_tree(root)
    return project, root, declared


def _gls_edge(declared, transcripts):
    """A fake `docker run`: the resolver writes the step config, the custom
    step writes its runs and transcripts, as `Vibeic.GateLevelSim` does."""
    calls = []

    def fake(cmd, **_):
        calls.append(cmd)
        text = ' '.join(map(str, cmd))
        if 'librelane.steps run --help' in text or 'bash' in cmd:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if 'from librelane.flows.chip import Chip' in text:
            script_index = next(i for i, arg in enumerate(cmd)
                                if 'from librelane.flows.chip import Chip' in str(arg))
            design = json.loads(Path(cmd[script_index + 1]).read_text())
            output = Path(cmd[script_index + 3])
            for step in json.loads(Path(cmd[script_index + 2]).read_text()):
                put(output / f'{step}.json', {'meta': {'step': step},
                                              'CELL_VERILOG_MODELS': declared[:1],
                                              'PAD_VERILOG_MODELS': declared[1:],
                                              'VIBEIC_GLS_MANIFEST': design['VIBEIC_GLS_MANIFEST']})
                put(output / f'{step}.views.json', {'step': step, 'inputs': ['nl', 'sdf'],
                                                    'outputs': []})
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if '--id' in cmd:
            folder = Path(cmd[cmd.index('-o') + 1])
            state = json.loads(Path(cmd[cmd.index('-i') + 1]).read_text())
            config = json.loads(Path(cmd[cmd.index('-c') + 1]).read_text())
            manifest = json.loads(Path(config['VIBEIC_GLS_MANIFEST']).read_text())
            runs = []
            for corner, sdf in state['sdf'].items():
                for case in manifest['cases']:
                    out = write(folder / corner / f"{case['id']}.stdout.log",
                                transcripts(corner).format(c=corner))
                    runs.append({'corner': corner, 'case': case['id'], 'sdf': sdf,
                                 'compile_rc': 0, 'sim_rc': 0, 'stdout': str(out)})
            put(folder / 'gls_runs.json', {'runs': runs})
            put(folder / 'state_out.json', state)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(f'unexpected tool call: {cmd}')
    return fake, calls


def test_step_29_runs_every_corner_sdf_through_the_custom_step(tmp_path, monkeypatch):
    project, root, declared = _gls_project(tmp_path)
    fake, calls = _gls_edge(declared, lambda corner: VVP_PASS)
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    monkeypatch.setattr(contract, 'image_capability', lambda *_: {})
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    judged = postroute.gate_level_sim(project, 'spm', 'img', root, 'x',
                                      direct_sdfs=[project / 'one.sdf'])
    assert judged['verdict'] == 'PASS'
    assert judged['coverage'] == {'tool_sdf_corners': 3, 'direct_sdf_corners': 1}
    assert sorted(judged['corners']) == sorted(CORNERS)
    run = next(c for c in calls if '--id' in c)
    assert run[run.index('--id') + 1] == 'Vibeic.GateLevelSim'
    assert f'PYTHONPATH={contract.PLUGIN_ROOT.resolve()}' in run
    manifest = json.loads((project / 'phase3/librelane/29-config/gls/gls_manifest.json').read_text())
    assert manifest['models'] == ['/pdk/x/libs.ref/cells/verilog/cells.v',
                                  '/pdk/x/libs.ref/cells/verilog/primitives.v',
                                  '/pdk/x/libs.ref/pads/verilog/pads.v']
    tb = Path(manifest['cases'][0]['testbench']).read_text()
    assert 'chip_top dut' in tb and sgs.SDF_PLACEHOLDER in tb


@pytest.mark.parametrize('transcript,reason', [
    (lambda c: VVP_PASS + VVP_SDF_ERROR, 'SDF_ERRORS'),
    (lambda c: 'ORACLE_TB_DONE pass=28/28\n', 'SDF_NOT_ANNOTATED'),
    (lambda c: VVP_PASS if c != 'max_ss_125C_4v50' else VVP_PASS.replace('28/28', '11/28')
     + 'ORACLE_MISMATCH: no single serial framing\n', 'CASE_FAIL'),
])
def test_step_29_gates_on_delays_applied_sdf_errors_and_every_case(tmp_path, monkeypatch,
                                                                  transcript, reason):
    project, root, declared = _gls_project(tmp_path)
    fake, _ = _gls_edge(declared, transcript)
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    monkeypatch.setattr(contract, 'image_capability', lambda *_: {})
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    judged = postroute.gate_level_sim(project, 'spm', 'img', root, 'x')
    assert judged['verdict'] == 'FAIL'
    assert any(reason in c['reasons'] for c in judged['corners'].values())


def test_step_29_on_librelane_writes_evidence_the_step_29_gate_fails(tmp_path, monkeypatch):
    project, root, declared = _gls_project(tmp_path)
    fake, _ = _gls_edge(declared, lambda c: VVP_PASS + VVP_SDF_ERROR)
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    monkeypatch.setattr(contract, 'image_capability', lambda *_: {})
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    put(project / 'phase3/librelane_switch.json', {'steps': {'29': 'librelane'},
                                                   'image': 'img', 'pdk_root_host': str(root)})
    runner, _ = _pdk('/p/l.lib')
    sim_dir = runner._pl.sim_postlayout_dir(project)
    written, notes = [], []
    runner._step29_tool_arm(project, 'spm', SimpleNamespace(name='x'), 'librelane', sim_dir,
                            sim_dir / 'spm.sdf', written, notes)
    log = (sim_dir / 'results.log').read_text()
    assert 'ERROR: corner nom_tt_025C_5v00 FAIL: SDF_ERRORS' in log, notes
    assert not (sim_dir / 'pass.flag').exists()
    gate = importlib.import_module('post_layout_sim_check')
    findings, stats = gate.audit(project)
    assert stats['sdf_found'] and any(f.category == 'SIM_ERRORS' for f in findings)


# ---------------------------------------------------------------- step 28 ---

def _perc_project(tmp_path):
    from test_perc_tapless_pdk_latchup_false_fail import _mk_project
    return _mk_project(tmp_path)


def test_perc_screens_tap_spacing_at_the_librelane_resolved_tap_distance(tmp_path, monkeypatch):
    runner, pdk = _pdk('/p/l.lib')
    project = _perc_project(tmp_path)
    put(project / 'phase3/librelane/15-config/OpenROAD.TapEndcapInsertion.json',
        {'meta': {'step': 'OpenROAD.TapEndcapInsertion'}, 'FP_TAPCELL_DIST': 20})
    seen = {}
    geo = importlib.import_module('latchup_esd_spacing_check')
    real = geo.run_geometry_layer

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(geo, 'run_geometry_layer', spy)
    monkeypatch.setattr(runner, '_measure_tap_geometry', lambda *a, **k: {'ok': False})
    assert runner._emit_perc_equivalent(project, 'chip_top', pdk, 'x', [])
    assert seen.get('screen_um') == 20.0
    doc = json.loads((runner._pl.reports_phase3_dir(project) / 'perc_equivalent.json').read_text())
    cat = next(c for c in doc['categories'] if c['category'] == 'Latch-up tap spacing (geometry)')
    assert cat['screen_um'] == 20.0
    assert cat['screen_source'].endswith('OpenROAD.TapEndcapInsertion.json:FP_TAPCELL_DIST')


def test_perc_antenna_and_pdn_read_the_tool_metrics_when_the_run_has_them(tmp_path, monkeypatch):
    runner, pdk = _pdk('/p/l.lib')
    project = _perc_project(tmp_path)
    put(project / 'phase3/librelane/26/01-openroad-checkantennas/state_out.json',
        {'metrics': {'antenna__violating__nets': 3, 'antenna__violating__pins': 3,
                     'route__antenna_violation__count': 0,
                     'design__power_grid_violation__count': 0}})
    monkeypatch.setattr(runner, '_measure_tap_geometry', lambda *a, **k: {'ok': False})
    assert runner._emit_perc_equivalent(project, 'chip_top', pdk, 'x', [])
    doc = json.loads((runner._pl.reports_phase3_dir(project) / 'perc_equivalent.json').read_text())
    cats = {c['category']: c for c in doc['categories']}
    assert cats['Antenna']['result'] == 'FAIL' and cats['Antenna']['direct_verdict'] == 'PASS'
    assert cats['PDN connectivity']['result'] == 'PASS'
    assert cats['IR drop']['tool_seam'] == postroute.PERC_IR_TOOL_SEAM


def test_perc_without_a_librelane_state_is_unchanged(tmp_path, monkeypatch):
    runner, pdk = _pdk('/p/l.lib')
    project = _perc_project(tmp_path)
    monkeypatch.setattr(runner, '_measure_tap_geometry', lambda *a, **k: {'ok': False})
    assert runner._emit_perc_equivalent(project, 'chip_top', pdk, 'x', [])
    doc = json.loads((runner._pl.reports_phase3_dir(project) / 'perc_equivalent.json').read_text())
    cats = {c['category']: c for c in doc['categories']}
    assert 'PDN connectivity' not in cats and 'tool_seam' not in cats['IR drop']
    assert cats['Antenna']['tool'] == 'OpenROAD check_antennas'


# ---------------------------------------------------------------- step 30 ---

CELL_SPICE = '''* cells
.SUBCKT cells__inv_1 I ZN VDD VNW VPW VSS
X_i_0 ZN I VSS VPW nfet_05v0 W=8.2e-07 L=6e-07
X_i_1 ZN I VDD VNW pfet_05v0 W=1.22e-06 L=5e-07
.ENDS
.SUBCKT pads__in_c DVDD DVSS PAD PD PU VDD VSS Y
X0 DVDD DVSS cap_nmos_06v0 m=8.0 c_length=1.5e-6 c_width=5e-6
X4 n62 n70 DVSS DVSS nfet_06v0 m=1.0 w=3e-6 l=700e-9
+ ps=6.88e-6 pd=6.88e-6
d56 vss vdd diode_pd2nw_06v0 m=1.0 area=230.4e-15
d57 VSS n0 diode_pd2nw_06v0 m=1.0 area=230.4e-15
.ENDS
'''


def test_supply_ports_fold_only_at_the_declared_voltage_and_rail_only_elements_go(tmp_path):
    src = write(tmp_path / 'cells.spice', CELL_SPICE)
    volts = pst.supply_voltages(['voltage_map(VNW, 5);\nvoltage_map(VDD, 5);\n'
                                 'voltage_map(VSS, 0);\nvoltage_map(VPW, 0);',
                                 'power_rail("DVDD",5.000000);\npower_rail("DVSS",0.000000);'])
    out = pst.fold_subckts([src], volts, 'VDD', 'VSS', tmp_path / 'folded.spice')
    text = (tmp_path / 'folded.spice').read_text()
    assert '.subckt cells__inv_1 I ZN VDD VSS' in text
    assert '.subckt pads__in_c PAD PD PU VDD VSS Y' in text
    assert ' X_i_0 ZN I VSS VSS nfet_05v0 W=8.2e-07 L=6e-07' in text.splitlines()
    assert 'cap_nmos_06v0' not in text           # VDD-to-VSS decap: inert
    assert 'd57 VSS n0' in text                   # a signal node: kept
    assert out['rail_only_elements_dropped'] == 1
    assert pst.device_names(text) == {'nfet_05v0', 'pfet_05v0', 'nfet_06v0', 'diode_pd2nw_06v0'}
    kept = pst.fold_subckts([src], {**volts, 'DVDD': 3.3}, 'VDD', 'VSS', tmp_path / 'f2.spice')
    assert 'DVDD' not in kept['folded']


MODELS = '''.lib typical
.lib 'm.ngspice' fets
.endl typical
.lib ss
.lib 'm.ngspice' fets
.endl ss
.lib diode_typical
.lib 'm.ngspice' dio
.endl diode_typical
.lib diode_ss
.lib 'm.ngspice' dio
.endl diode_ss
.lib fets
.subckt nfet_05v0 d g s b
.ends
.subckt pfet_05v0 d g s b
.ends
.endl fets
.lib dio
.model diode_pd2nw_06v0 d
.endl dio
'''


def test_the_device_models_are_the_corner_sections_that_define_every_called_device(tmp_path):
    tech = tmp_path / 'ngspice'
    write(tech / 'm.ngspice', MODELS)
    write(tech / 'design.ngspice', '.param sw_stat_global=0\n')
    got = pst.model_file(tech, '/pdk/x/libs.tech/ngspice', 'ngspice', 'cells__ss_125C_4v50.lib',
                         {'nfet_05v0', 'pfet_05v0', 'diode_pd2nw_06v0'}, 125.0, tmp_path / 'm.sp')
    assert sorted(s for _, s in got['sections']) == ['diode_ss', 'ss']
    text = (tmp_path / 'm.sp').read_text()
    assert '.include /pdk/x/libs.tech/ngspice/design.ngspice' in text and '.temp 125' in text
    with pytest.raises(contract.Refusal) as err:
        pst.model_file(tech, '/g', 'ngspice', 'cells__ss_125C_4v50.lib', {'nfet_06v0'}, None,
                       tmp_path / 'x.sp')
    assert err.value.code == 'LL_SPICE_DEVICE_UNMODELLED'


def test_the_spef_mutation_scales_every_capacitance(tmp_path):
    spef = write(tmp_path / 'a.spef', '*C_UNIT 1 PF\n*D_NET n1 0.002\n*CONN\n*I u1:Z O\n*CAP\n'
                                      '1 n1:1 0.001\n2 n1:1 n2:1 0.0005\n*RES\n1 n1:1 u1:Z 2.5\n*END\n')
    out = pst.mutate_spef(spef, 10.0, tmp_path / 'b.spef')
    text = (tmp_path / 'b.spef').read_text()
    assert '*D_NET n1 0.02' in text and '1 n1:1 0.01' in text and '2 n1:1 n2:1 0.005' in text
    assert '1 n1:1 u1:Z 2.5' in text and out['cap_rows_scaled'] == 2


def _arm(delays, sta=1.0, tol=10.0):
    return {'paths': [{'path': i + 1, 'status': 'MEASURED', 'startpoint': f's{i}',
                       'endpoint': f'e{i}', 'sta_ns': sta, 'spice_ns': d,
                       'error_pct': (d - sta) / sta * 100.0, 'tolerance_pct': tol,
                       'verdict': importlib.import_module('spice_correlation_check')
                       .path_correlation_verdict((d - sta) / sta * 100.0, tol),
                       'deck': None} for i, d in enumerate(delays)]}


def test_a_correlation_that_does_not_move_with_the_spef_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pst, '_tran_step_ns', lambda deck: 1e-4)
    base = _arm([1.02])
    assert pst.judge(base, _arm([1.30], sta=1.25))['verdict'] == 'CORRELATED'
    assert pst.judge(base, _arm([1.02], sta=1.25))['verdict'] == 'SPEF_UNRESPONSIVE'
    assert pst.judge(_arm([1.5]), _arm([1.8], sta=1.25))['verdict'] == 'CRITICAL_MISMATCH'
    unmeasured = _arm([1.30], sta=1.25)
    unmeasured['paths'][0]['status'] = 'NOT_MEASURED'
    assert pst.judge(base, unmeasured)['verdict'] == 'MUTATION_NOT_MEASURED'


def test_the_spice_delay_is_measured_between_the_sta_pins_at_the_sta_edges(tmp_path):
    deck = write(tmp_path / 'path_1.sp_1.sp', 'v1 x/VDD 0 5.000\n.tran 1e-13 2e-9\n')
    rows = [(t * 1e-10, 0.0 if t < 3 else 5.0, 5.0 if t < 8 else 0.0) for t in range(12)]
    # ngspice `wrdata` with wr_vecnames + wr_singlescale, names as it keeps them.
    write(tmp_path / 'path_1.sp_1.wave', ' time v(u\\/a/clk) v(u\\/b/d)\n'
          + ''.join(f' {t} {a} {b}\n' for t, a, b in rows))
    sta = {'startpoint': 'u/a', 'endpoint': 'u/b', 'endpoint_transition': 'fall',
           'rows': [{'inst': 'u/a', 'pin': 'u/a/CLK', 'tr': '^', 'cell': 'dff'},
                    {'inst': 'u/b', 'pin': 'u/b/D', 'tr': 'v', 'cell': 'dff'}]}
    header = {'input_threshold_rise': 50.0, 'output_threshold_fall': 50.0}
    got = pst.measure(deck, 'ngspice', sta, header)
    assert got['status'] == 'MEASURED'
    assert got['spice_ns'] == pytest.approx(0.5)


# ------------------------------------------------------ the contract edge ---

def test_the_gate_level_sim_step_ships_in_the_plugin_the_contract_mounts():
    source = (contract.PLUGIN_ROOT / 'librelane_plugin_vibeic/__init__.py').read_text()
    assert 'id = "Vibeic.GateLevelSim"' in source
    assert contract._plugin_args(['Vibeic.GateLevelSim'])
    # The step records; it parses nothing it produces (the judgement is the
    # calibrated `sdf_gate_sim.judge_tool_arm` on the host).
    import ast
    tree = ast.parse(source)
    imported = ({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
    assert not imported & {'re', 'sdf_gate_sim'}


def test_post_route_power_keeps_native_clock_analysis_and_pre_pnr_keeps_ideal_clocks(tmp_path, monkeypatch):
    """Post-route power adopts the current native STAPostPNR session.

    A second standalone post-route deck would lose that session's clock-tree
    analysis. The pre-PnR estimate still has no tree to propagate.
    """
    runner, _ = _pdk('/unused.lib')
    project, folder, library = _current_power_scene(tmp_path)
    rpt = runner._pl.reports_phase3_dir(project) / 'power.rpt'
    pdk = _pdk(str(library))[1]
    monkeypatch.setattr(runner, '_docker_exec',
                        lambda *a, **k: pytest.fail('parallel post-route power session ran'))
    assert runner._emit_power_report(project, 'neutral', pdk, 'c', rpt, [], basis='post_pnr')
    assert (folder / 'max_typ/power.rpt').read_text() in rpt.read_text()
    import _opensta_current as current
    current.power_binding(project)
    assert not (rpt.parent / 'power_neutral.tcl').exists()
    write(runner._pl.synth_dir(project) / 'neutral_synth.v',
          'module neutral(input x, y, output z); assign z = x & y; endmodule\n')
    write(runner._pl.pnr_dir(project) / 'constraint.sdc',
          'create_clock -period 24 [get_ports x]\n')
    monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (1, '', ''))
    runner._emit_power_report(project, 'neutral', pdk, 'c', rpt, [], basis='pre_pnr')
    deck = (rpt.parent / 'power_neutral.tcl').read_text()
    assert 'set_propagated_clock [all_clocks]' not in deck
    assert 'read_spef' not in deck


STA_PATH = '''Startpoint: u_core/_417_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_core/_416_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

        Cap        Slew       Delay        Time   Description
---------------------------------------------------------------------------------------
                           0.000000    0.000000   clock clk (rise edge)
                           3.762521    3.762521   clock network delay (propagated)
               0.101318    0.000000    3.762521 ^ u_core/_417_/CLK (cells__dffq_1)
   0.013435    0.186434    {d1}    {t1} v u_core/_417_/Q (cells__dffq_1)
               0.186434    {d2}    {t2} v u_core/_416_/D (cells__dffq_1)
                                       {t2}   data arrival time
'''

LIBERTY = '''library (cells_tt) {
  time_unit : "1ns";
  capacitive_load_unit (1,pf);
  voltage_map(VDD, 5);
  voltage_map(VNW, 5);
  voltage_map(VSS, 0);
  voltage_map(VPW, 0);
  operating_conditions(cells_ss_125C_4v50) {
  }
  cell ("cells__dffq_1") {
    pin (Q) {
      timing () {
        related_pin : "CLK";
        cell_fall (tbl) {
          index_1 ("0.1, 0.2");
          index_2 ("0.01, 0.02");
          values ("0.70, 0.72", "0.74, 0.76");
        }
      }
    }
  }
}
'''


def _wps_edge(calls):
    """What `sta` (write_path_spice) and `ngspice` write, at the `_docker` edge.
    The deck's SPICE delay follows the SPEF the session read: x10 caps, slower."""
    def fake(image, project, mounts, argv, cwd, docker='docker'):
        calls.append(argv)
        if argv[0] == 'sta':
            tcl = Path(argv[-1]).read_text()
            spef = tcl.split('read_spef ')[1].split('\n')[0]
            slow = 'mutated' in spef
            d1, d2 = 0.710804, (0.9 if slow else 0.5)
            for rpt in __import__('re').findall(r'> (\S+\.rpt)', tcl):
                write(Path(rpt), STA_PATH.format(d1=f'{d1:.6f}', t1=f'{3.762521 + d1:.6f}',
                                                 d2=f'{d2:.6f}', t2=f'{3.762521 + d1 + d2:.6f}'))
            for deck in __import__('re').findall(r'-spice_file (\S+)', tcl):
                write(Path(deck + '_1.sp'), '* Path\n.tran 1e-13 2e-08\n'
                      '.print tran v(u_core\\/_417_/CLK) v(u_core\\/_417_/Q) v(u_core\\/_416_/D)\n'
                      'v2 u_core\\/_417_/VDD 0 4.500\n.end\n')
            return SimpleNamespace(returncode=0, stdout='VIBEIC_WPS_OK 1\n', stderr='')
        if argv[0] == 'ngspice':
            run = Path(argv[-1])
            spef_slow = 'mutated' in str(run)
            wrdata = run.read_text().split('wrdata ')[1].split('\n')[0].split()
            calls.append(('wrdata', wrdata))
            control = run.read_text().split('.control')[1].split('.endc')[0]
            assert control.split()[-1] == 'quit', control
            assert wrdata[1:] == ['v(u_core\\\\/_417_/clk)', 'v(u_core\\\\/_417_/q)',
                                  'v(u_core\\\\/_416_/d)'], wrdata
            cone = 0.95e-9 if spef_slow else 0.52e-9
            rows = [' time v(u_core\\/_417_/clk) v(u_core\\/_417_/q) v(u_core\\/_416_/d)\n']
            for i in range(400):
                t = i * 1e-11
                clk = 4.5 if t >= 0.5e-9 else 0.0
                q = 0.0 if t >= 0.5e-9 + 0.71e-9 else 4.5
                d = 0.0 if t >= 0.5e-9 + 0.71e-9 + cone else 4.5
                rows.append(f' {t} {clk} {q} {d}\n')
            write(Path(wrdata[0]), ''.join(rows))
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(argv)
    return fake


def test_step_30_runs_the_tool_deck_and_the_spef_mutation_and_records_every_arm(tmp_path, monkeypatch):
    project = tmp_path / 'design'
    folder, _ = _stapostpnr(project)
    record = json.loads((project / postroute.STEP23_RECORD).read_text())
    record['judgment'] = {'worst_setup': {'corner': 'max_ss_125C_4v50'}}
    put(project / postroute.STEP23_RECORD, record)
    root = tmp_path / 'pdkroot'
    write(root / 'x/libs.ref/cells/lib/cells__ss_125C_4v50.lib', LIBERTY)
    write(root / 'x/libs.ref/cells/spice/cells.spice',
          '.SUBCKT cells__dffq_1 D CLK Q VDD VNW VPW VSS\n'
          'X_i_0 Q D VSS VPW nfet_05v0 W=8.2e-07 L=6e-07\n.ENDS\n')
    write(root / 'x/libs.tech/ngspice/m.ngspice', MODELS)
    (root / 'x/libs.tech/xyce').mkdir(parents=True)
    config = json.loads((folder / 'config.json').read_text())
    config['CELL_SPICE_MODELS'] = ['/pdk/x/libs.ref/cells/spice/cells.spice']
    put(folder / 'config.json', config)
    calls = []
    monkeypatch.setattr(pst, '_docker', _wps_edge(calls))
    doc = pst.run_step30(project, 'img', root, 'x', paths=1)
    assert doc['corner'] == 'max_ss_125C_4v50'
    assert doc['arms']['xyce']['verdict'] == 'NOT_MEASURED'
    assert 'LL_SPICE_DEVICE_UNMODELLED' in doc['arms']['xyce']['reason']
    ngspice = doc['arms']['ngspice']
    assert ngspice['mutation'][0]['responds'] is True
    base = json.loads((project / 'reports/phase3/spice_path_tool.json').read_text())[
        'detail']['ngspice']['base']['paths'][0]
    # The launching register's combinational cone: its Q pin to the endpoint
    # pin, in STA and in SPICE.
    assert base['sta_ns'] == pytest.approx(0.5)
    assert base['start_pin'] == 'u_core/_417_/Q' and base['end_pin'] == 'u_core/_416_/D'
    assert base['spice_ns'] == pytest.approx(0.52, abs=0.011)
    sta_runs = [c for c in calls if c[0] == 'sta']
    assert '-fall_from u_core/_417_/Q -fall_to u_core/_416_/D' in Path(sta_runs[1][-1]).read_text()
    assert json.loads((project / 'reports/phase3/spice_path_tool.json').read_text())['step'] == '30'


@pytest.mark.parametrize('case', [
    'good', 'case_fail', 'missing_sdf', 'changed_state', 'missing_model', 'tool_error'])
def test_default_step29_consumes_the_complete_librelane_owner(tmp_path, monkeypatch, case):
    """Actual Default row, LL manifest/judge/publisher and both canonical clauses.

    Only the LL process edge writes neutral tool-format data. No gate JSON or
    accepted step record is seeded; the normal declared producer writes it.
    """
    import time
    import _flow_yaml
    import execution_backend_producers as backend
    import execution_backend_worker as worker
    import execution_policy
    import phase3_one_shot_runner as runner
    import step_output_collector as versions
    from _stated_eda_image import mock_docker_route

    mock_docker_route(monkeypatch)
    project, root, declared = _gls_project(tmp_path)
    put(project / 'phase3/librelane_switch.json', {
        'image': 'img', 'pdk_root_host': str(root), 'pdk': 'x'})
    put(project / 'input/step_0_5ic_answers.json', {})
    write(project / 'phase2/stage2/synth/post_dft_netlist.v', CHIP_TOP)
    cfg = SimpleNamespace(name='x')
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {
        'pdk_name': 'x', 'pdk_root': str(root), 'image_id': 'img'})
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, contract, cfg, 'SOURCE_FIXTURE_ONLY'))
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    direct_calls = []
    def unavailable_direct(*args):
        direct_calls.append(True)
        return False
    monkeypatch.setattr(runner, '_emit_sdf', unavailable_direct)
    transcript = (lambda c: VVP_PASS.replace('28/28', '11/28')
                  if case == 'case_fail' else VVP_PASS)
    edge, calls = _gls_edge(declared, transcript)
    def process_edge(argv, **kwargs):
        if any('from librelane.flows.chip import Chip' in str(arg) for arg in argv):
            # The current resolver also passes its image identity. The older
            # shared edge models the preceding five resolver arguments.
            return edge(argv[:-1], **kwargs)
        if '--id' in argv and case == 'tool_error':
            calls.append(argv)
            return SimpleNamespace(returncode=1, stdout='', stderr='SOURCE_FIXTURE_ONLY: simulation tool stopped')
        completed = edge(argv, **kwargs)
        if '--id' in argv and case == 'missing_model':
            folder = Path(argv[argv.index('-o') + 1])
            config = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
            manifest = json.loads(Path(config['VIBEIC_GLS_MANIFEST']).read_text())
            assert manifest['model_closure']['unresolved']
            runs = json.loads((folder / 'gls_runs.json').read_text())
            for row in runs['runs']:
                row['compile_rc'] = 1
                write(Path(row['stdout']), 'SOURCE_FIXTURE_ONLY: unresolved cell module\n')
            put(folder / 'gls_runs.json', runs)
        return completed
    monkeypatch.setattr(contract, 'run_container', process_edge)
    record = project / postroute.STEP23_RECORD
    state_path = Path(json.loads(record.read_text())['sta_state'])
    state = json.loads(state_path.read_text())
    original_state = state_path.read_bytes()
    if case == 'missing_sdf':
        Path(next(iter(state['sdf'].values()))).unlink()
    elif case == 'changed_state':
        state_path.write_text(state_path.read_text() + '\n ')
    elif case == 'missing_model':
        (root / 'x/libs.ref/cells/verilog/cells.v').unlink()
    gate = project / 'reports/phase2/gates/post_layout_sim.json'
    assert not gate.exists()
    began = time.time()
    result = runner._default_pnr_rows(project, 'spm', cfg, 'SOURCE_FIXTURE_ONLY', ['29'])
    assert direct_calls == [], result.detail
    assert result.status == ('PASS' if case == 'good' else 'FAIL'), result.detail
    assert gate.is_file(), result.detail
    report = json.loads(gate.read_text())
    assert report['verdict'] == ('PASS' if case == 'good' else 'FAIL'), report
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '29')
    files, missing = worker.resolve_contract(project, row['required_outputs'])
    version_folder = result.extras['canonical_steps'][0]['extras']['output_version']
    accepted = json.loads((project / 'steps' / version_folder / 'outputs.json').read_text())
    assert accepted['status'] == result.status
    assert accepted['canonical_pass'] is (case == 'good')
    sim = runner._pl.sim_postlayout_dir(project)
    if case in ('good', 'case_fail', 'missing_model'):
        assert missing == []
        assert 'reports/phase2/gates/post_layout_sim.json' in files
        assert (sim / 'results.log').is_file()
        judged = json.loads((project / 'reports/phase3/gls_corners.json').read_text())
        assert judged['coverage'] == {'tool_sdf_corners': 3, 'direct_sdf_corners': 0}
        assert judged['dut_binding']['dut_module'] == 'chip_top'
        manifest = json.loads((project / 'phase3/librelane/29-config/gls/gls_manifest.json').read_text())
        assert manifest['top'] == 'spm'
        assert sorted(judged['corners']) == sorted(CORNERS)
        for corner, sdf in state['sdf'].items():
            assert (sim / f'spm__{corner}.sdf').read_bytes() == Path(sdf).read_bytes()
        assert state_path.read_bytes() == original_state
    if case == 'good':
        complete = next(r for r in versions.current_acceptance(project, began) if r['id'] == '29')
        assert complete['canonical_pass'] is True and complete['status'] == 'PASS'
        assert (sim / 'pass.flag').is_file()
        assert versions.latest_pass(project, '29')['current_inputs'] is True
        assert {r['rel'] for r in accepted['outputs']} >= {
            'phase3/stage3/sim_postlayout/results.log',
            'reports/phase2/gates/post_layout_sim.json'}
    else:
        assert not (sim / 'pass.flag').exists()
        assert versions.latest_pass(project, '29') is None
    # Preserve a compact source-control observation alongside pytest's raw XML.
    put(project / 'source_control_observation.json', {
        'case': case, 'status': result.status, 'missing': missing,
        'captured': accepted, 'native_claim': False})


@pytest.mark.parametrize('case', ['good', 'case_fail'])
def test_default_step29_binds_a_same_line_clock_before_complete_capture(
        tmp_path, monkeypatch, case):
    """Reuse the full row control with valid single-line HDL statements."""
    original = _gls_project
    def same_line_project(path):
        project, root, declared = original(path)
        bench = project / 'phase2/stage1/sim/tb_case.v'
        text = bench.read_text().replace(
            '  always #5 clk = ~clk;',
            '  initial clk = 1\'b0; always #12 clk = ~clk;')
        assert text != bench.read_text()
        bench.write_text(text)
        return project, root, declared
    monkeypatch.setattr(sys.modules[__name__], '_gls_project', same_line_project)
    test_default_step29_consumes_the_complete_librelane_owner(tmp_path, monkeypatch, case)
    project = tmp_path / 'design'
    manifest = json.loads((project / 'phase3/librelane/29-config/gls/gls_manifest.json').read_text())
    assert manifest['not_a_subject'] == []
    assert manifest['cases'] and manifest['clock']['clocks_s']['clk'] == pytest.approx(24e-9)
    assert 'initial clk = 1\'b0; always #12 clk = ~clk;' in Path(
        manifest['cases'][0]['testbench']).read_text()


from test_librelane_contract import local_image  # noqa: E402,F401


@pytest.mark.parametrize('case', ['good', 'case_fail', 'missing_model', 'missing_include', 'docker_guest'])
def test_default_gls_manifest_uses_the_compilers_execution_namespace(
        tmp_path, monkeypatch, local_image, case):
    """Real Icarus reads the complete LOCAL neutral SC/PAD/include closure.

    Only the LibreLane configuration/step-process transport is substituted.
    The custom GLS step, compiler, simulator, judge, publishers and canonical
    consumer execute normally. The Docker branch preserves guest-path data.
    """
    import time
    import _flow_yaml
    import execution_backend_producers as backend
    import execution_backend_worker as worker
    import execution_policy
    import phase3_one_shot_runner as runner
    import step_output_collector as versions

    project, root, declared = _gls_project(tmp_path)
    local = case != 'docker_guest'
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: local)
    put(project / 'phase3/librelane_switch.json', {
        'image': local_image.image, 'pdk_root_host': str(root), 'pdk': 'x'})
    put(project / 'input/step_0_5ic_answers.json', {})
    write(project / 'phase2/stage2/synth/post_dft_netlist.v', CHIP_TOP)
    cfg = SimpleNamespace(name='x')
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {
        'pdk_name': 'x', 'pdk_root': str(root), 'image_id': local_image.image})
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, contract, cfg, 'SOURCE_FIXTURE_ONLY'))
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    header = write(root / 'x/libs.ref/cells/verilog/model_constants.vh',
                   '`define SOURCE_FIXTURE_PAD_DELAY 1\n')
    if local:
        cells = root / 'x/libs.ref/cells/verilog/cells.v'
        cells.write_text(f'`include "{header}"\n' + cells.read_text())
        pads = root / 'x/libs.ref/pads/verilog/pads.v'
        pads.write_text('module cells__in_c (PAD, Y); input PAD; output Y;\n'
                        '  buf (Y, PAD);\n'
                        '  specify (PAD => Y) = (`SOURCE_FIXTURE_PAD_DELAY, `SOURCE_FIXTURE_PAD_DELAY); endspecify\n'
                        'endmodule\n')
    state_path = Path(json.loads((project / postroute.STEP23_RECORD).read_text())['sta_state'])
    state = json.loads(state_path.read_text())
    for sdf in state['sdf'].values():
        write(Path(sdf), '(DELAYFILE\n (SDFVERSION "3.0") (DESIGN "chip_top")\n'
              ' (DIVIDER .) (TIMESCALE 1ns)\n'
              ' (CELL (CELLTYPE "chip_top") (INSTANCE)\n'
              '  (DELAY (ABSOLUTE (INTERCONNECT x u_pad_x.PAD (0.1:0.1:0.1)))))\n'
              ' (CELL (CELLTYPE "cells__in_c") (INSTANCE u_pad_x)\n'
              '  (DELAY (ABSOLUTE (IOPATH PAD Y (0.1:0.1:0.1) (0.1:0.1:0.1)))))\n)\n')
    # Fixture construction ends here; later missing-model/include controls
    # still tamper only after the valid producer has been sealed.
    from test_default_current_power import seal
    seal(state_path.parent, json.loads((state_path.parent / 'input_fingerprint.json').read_text()))
    if case == 'case_fail':
        bench = project / 'phase2/stage1/sim/tb_case.v'
        bench.write_text(bench.read_text().replace('pass=1/1', 'pass=0/1'))
    resolved_models = [str(root / path.removeprefix('/pdk/')) for path in declared] if local else declared
    edge, calls = _gls_edge(resolved_models, lambda c: VVP_PASS)
    executions = []
    def process_edge(argv, **kwargs):
        if any('from librelane.flows.chip import Chip' in str(arg) for arg in argv):
            return edge(argv[:-1], **kwargs)
        if '--id' not in argv or not local:
            return edge(argv, **kwargs)
        from librelane.state import DesignFormat
        monkeypatch.syspath_prepend(str(contract.PLUGIN_ROOT))
        from librelane_plugin_vibeic import GateLevelSim
        folder = Path(argv[argv.index('-o') + 1])
        folder.mkdir(parents=True, exist_ok=True)
        config = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
        incoming = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        manifest = json.loads(Path(config['VIBEIC_GLS_MANIFEST']).read_text())
        if case == 'missing_model':
            (root / 'x/libs.ref/pads/verilog/pads.v').unlink()
        elif case == 'missing_include':
            header.unlink()
        instance = SimpleNamespace(config={
            'VIBEIC_GLS_MANIFEST': config['VIBEIC_GLS_MANIFEST'], 'VIBEIC_GLS_TIMEOUT_S': 30},
            step_dir=str(folder), _run=GateLevelSim._run)
        GateLevelSim.run(instance, {DesignFormat.NETLIST: incoming['nl'], DesignFormat.SDF: incoming['sdf']})
        put(folder / 'state_out.json', incoming)
        executions.append(folder)
        return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY: actual Icarus GLS completed\n', stderr='')
    monkeypatch.setattr(contract, 'run_container', process_edge)
    gate = project / 'reports/phase2/gates/post_layout_sim.json'
    assert not gate.exists()
    began = time.time()
    row = runner._default_pnr_rows(project, 'spm', cfg, 'SOURCE_FIXTURE_ONLY', ['29'])
    manifest = json.loads((project / 'phase3/librelane/29-config/gls/gls_manifest.json').read_text())
    expected = [str(root / 'x/libs.ref/cells/verilog/cells.v'),
                str(root / 'x/libs.ref/cells/verilog/primitives.v'),
                str(root / 'x/libs.ref/pads/verilog/pads.v')]
    assert manifest['models'] == (expected if local else [
        '/pdk/x/libs.ref/cells/verilog/cells.v', '/pdk/x/libs.ref/cells/verilog/primitives.v',
        '/pdk/x/libs.ref/pads/verilog/pads.v'])
    assert Path(manifest['netlist']).is_file() and Path(manifest['stubs']).is_file()
    assert all(Path(c['testbench']).is_file() for c in manifest['cases'])
    judged = json.loads((project / 'reports/phase3/gls_corners.json').read_text())
    good = case in ('good', 'docker_guest')
    assert row.status == ('PASS' if good else 'FAIL'), row.detail
    assert judged['verdict'] == ('PASS' if good else 'FAIL')
    if local:
        assert len(executions) == 1
        runs = json.loads((executions[0] / 'gls_runs.json').read_text())['runs']
        assert len(runs) == 3
        for run in runs:
            log = Path(run['compile_log']).read_text()
            if case in ('missing_model', 'missing_include'):
                assert run['compile_rc'] != 0 and run['sim_rc'] is None
                assert ('pads.v' if case == 'missing_model' else 'model_constants.vh') in log
            else:
                assert run['compile_rc'] == run['sim_rc'] == 0, log
                assert Path(run['stdout']).is_file()
                assert judged['corners'][run['corner']]['delays_applied'] > 0
    definition = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '29')
    _, missing = worker.resolve_contract(project, definition['required_outputs'])
    assert missing == [] and gate.is_file()
    assert json.loads(gate.read_text())['verdict'] == ('PASS' if good else 'FAIL')
    if good:
        accepted = next(r for r in versions.current_acceptance(project, began) if r['id'] == '29')
        assert accepted['canonical_pass'] is True
    else:
        assert versions.latest_pass(project, '29') is None
    put(project / 'local_namespace_observation.json', {
        'case': case, 'local': local, 'models': manifest['models'],
        'actual_iverilog_vvp': local, 'verdict': row.status, 'ic_native_claim': False})


def _declared_observation_gls_project(tmp_path, mode):
    """Public INPUT-defined 24 ns multiplier, delayed pads and renamed pins.

    The schedule is chosen before execution: 1.2 ns clock-pad plus 1.8 ns
    output-pad delay, observed at the declared 4 ns point. No field design,
    waveform search or expected-result file is used.
    """
    import arith_oracle_tb_gen as arith
    from test_fullstacktb_functional_population import _timed_input

    project = tmp_path / 'design'
    cases = _timed_input(project, 'wrapped8_delayed',
                         mode='wrong_product' if mode == 'case_fail' else 'good')
    case = next(c for c in cases if c['name'] == 'transaction_sequence')
    if mode == 'random':
        case = {'name': 'transaction_sequence', 'kind': 'functional_vector',
                'stimulus': 'Random at least 10000 operand pairs using the stated serial framing.',
                'expected': '100% PASS'}
    elif mode == 'combined':
        case = {'name': 'transaction_sequence', 'kind': 'functional_vector',
                'coverage_scope': 'Operand boundaries: zero, one, MAX; all Cartesian combinations. Consecutive transactions: at least 16 operand pairs using declared rearm, no extra idle cycles. Synchronous reset held, released, and asserted during computation; between-edge reset pulses must not reset.',
                'expected': '100% PASS'}
    put(project / 'phase1/generated_docs/L10_TEST_CASES.json', {'test_cases': [case]})
    l9 = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    doc = json.loads(l9.read_text())
    doc['clocks'][0]['period_ns'] = 24
    put(l9, doc)
    put(project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains': [{'role': 'primary', 'period_ns': 24, 'source_pin': 'i_clk'}]})
    put(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {})
    put(project / 'input/submission_template/tapeout_declaration.json',
        {'answers': {'top_cell': 'public_surface'}})
    put(project / 'input/step_0_5ic_answers.json', {})
    root = tmp_path / 'pdkroot'
    models = write(root / 'x/libs.ref/cells/verilog/public_pads.v', '''`timescale 1ns/1ps
module PUBLIC_CLK(input A, output Y);
 buf (Y,A); specify (A => Y) = (1.2,1.2); endspecify
endmodule
module PUBLIC_OUT(input A, output Y);
 buf (Y,A); specify (A => Y) = (1.8,1.8); endspecify
endmodule
''')
    wrapper = project / 'phase3/stage3/pnr/public_surface.v'
    wrapper.write_text('''module public_surface (chip_clock, chip_reset, chip_word, chip_serial, chip_result);
 input chip_clock, chip_reset, chip_serial;
 input [7:0] chip_word;
 output chip_result;
 wire selected_clock, core_result;
 PUBLIC_CLK clock_pad (.A(chip_clock), .Y(selected_clock));
 public_serial_product core (.i_clk(selected_clock), .i_rst(chip_reset), .operand_word(chip_word), .serial_bit(chip_serial), .result_bit(core_result));
 PUBLIC_OUT output_pad (.A(core_result), .Y(chip_result));
endmodule
''')
    put(project / sgs.CHIP_TOP_RECORD_REL, {
        'verdict': 'WROTE', 'core_module': 'public_serial_product',
        'chip_top_module': 'public_surface', 'chip_top_verilog': str(wrapper.relative_to(project)),
        'pad_instances': {
            'clock_pad': {'core_pin': 'Y', 'terminal': 'A'},
            'output_pad': {'core_pin': 'A', 'terminal': 'Y'}}})
    declaration = json.loads((project / 'plugin_output/declaration.json').read_text())
    declaration['verification_stimuli']['arithmetic_observation']['public_surface'] = {
        'clock': 'i_clk', 'output': 'result_bit', 'settle_ns': 3,
        'sample_offset_ns': 4, 'binding': {
            str(f.resolve()): contract.digest(f) for f in (wrapper, models)}}
    if mode == 'missing_contract':
        declaration['verification_stimuli']['arithmetic_observation'] = {}
    elif mode == 'changed_binding':
        declaration['verification_stimuli']['arithmetic_observation']['public_surface']['binding'][str(models.resolve())] = '0' * 64
    put(project / 'plugin_output/declaration.json', declaration)
    # The original L10/core plan is produced normally and remains immutable.
    original_plan = arith.arithmetic_scenario_plan(project, 'digital_arithmetic_primitive', case)
    assert original_plan is not None
    bench = write(project / 'phase2/stage1/sim/tb/transaction_sequence.v',
                  arith.emit_arithmetic_scenario_module(case['name'], original_plan))
    put(project / 'reports/phase2/sim/l10_execution.json', {'cases': [{
        'id': case['name'], 'sim_executed': True, 'tb_file': str(bench),
        'tb_provenance': 'generated', 'tb_sha256': contract.digest(bench)}]})
    folder, _ = _stapostpnr(project)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    # A neutral flattened physical implementation of the same public core.
    core = (project / 'phase2/stage1/rtl/public_serial_product.v').read_text()
    body = core.split(';', 1)[1].rsplit('endmodule', 1)[0]
    physical = '''`timescale 1ns/1ps
module public_surface (chip_clock, chip_reset, chip_word, chip_serial, chip_result);
 input chip_clock, chip_reset, chip_serial;
 input [7:0] chip_word;
 output chip_result;
 wire i_clk, i_rst=chip_reset, serial_bit=chip_serial;
 wire [7:0] operand_word=chip_word;
 reg result_bit=0;
 PUBLIC_CLK clock_pad (.A(chip_clock), .Y(i_clk));
 PUBLIC_OUT output_pad (.A(result_bit), .Y(chip_result));
''' + body + '\nendmodule\n'
    write(Path(state['nl']), physical)
    write(project / 'phase2/stage2/synth/post_dft_netlist.v', physical)
    write(Path(state['sdc']), 'create_clock -name clk -period 24 [get_ports chip_clock]\n')
    for sdf in state['sdf'].values():
        write(Path(sdf), '''(DELAYFILE
 (SDFVERSION "3.0") (DESIGN "public_surface") (DIVIDER .) (TIMESCALE 1ns)
 (CELL (CELLTYPE "public_surface") (INSTANCE)
  (DELAY (ABSOLUTE (INTERCONNECT chip_clock clock_pad.A (0:0:0)))))
 (CELL (CELLTYPE "PUBLIC_CLK") (INSTANCE clock_pad)
  (DELAY (ABSOLUTE (IOPATH A Y (1.2:1.2:1.2) (1.2:1.2:1.2)))))
 (CELL (CELLTYPE "PUBLIC_OUT") (INSTANCE output_pad)
  (DELAY (ABSOLUTE (IOPATH A Y (1.8:1.8:1.8) (1.8:1.8:1.8)))))
)
''')
    _current_output_deadline_fixture(project, root, 4)
    return project, root, models, bench, original_plan


@pytest.mark.parametrize('case', ['good', 'case_fail', 'missing_contract', 'changed_binding'])
def test_default_gls_uses_the_declared_physical_observation(
        tmp_path, monkeypatch, local_image, case):
    """Actual Default capture, typed INPUT schedule and real Icarus verdicts."""
    import execution_backend_producers as backend
    import execution_policy
    import phase3_one_shot_runner as runner
    import step_output_collector as versions
    import arith_oracle_tb_gen as arith

    project, root, model, bench, original_plan = _declared_observation_gls_project(tmp_path, case)
    original_bytes = bench.read_bytes()
    put(project / 'phase3/librelane_switch.json', {
        'image': local_image.image, 'pdk_root_host': str(root), 'pdk': 'x'})
    cfg = SimpleNamespace(name='x')
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {
        'pdk_name': 'x', 'pdk_root': str(root), 'image_id': local_image.image})
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, contract, cfg, 'SOURCE_FIXTURE_ONLY'))
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    edge, _ = _gls_edge([str(model)], lambda c: VVP_PASS)
    native = []
    def process_edge(argv, **kwargs):
        if any('from librelane.flows.chip import Chip' in str(arg) for arg in argv):
            return edge(argv[:-1], **kwargs)
        if '--id' not in argv:
            return edge(argv, **kwargs)
        from librelane.state import DesignFormat
        monkeypatch.syspath_prepend(str(contract.PLUGIN_ROOT))
        from librelane_plugin_vibeic import GateLevelSim
        folder = Path(argv[argv.index('-o') + 1])
        folder.mkdir(parents=True, exist_ok=True)
        config = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
        incoming = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        instance = SimpleNamespace(config={
            'VIBEIC_GLS_MANIFEST': config['VIBEIC_GLS_MANIFEST'], 'VIBEIC_GLS_TIMEOUT_S': 30},
            step_dir=str(folder), _run=GateLevelSim._run)
        GateLevelSim.run(instance, {DesignFormat.NETLIST: incoming['nl'], DesignFormat.SDF: incoming['sdf']})
        put(folder / 'state_out.json', incoming)
        native.append(folder)
        return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY: actual Icarus completed\n', stderr='')
    monkeypatch.setattr(contract, 'run_container', process_edge)
    result = runner._default_pnr_rows(project, 'public_serial_product', cfg, 'SOURCE_FIXTURE_ONLY', ['29'])
    manifest = json.loads((project / 'phase3/librelane/29-config/gls/gls_manifest.json').read_text())
    assert bench.read_bytes() == original_bytes
    assert original_plan['observation']['sample_offset_ns'] == 1
    assert original_plan['framing']['settled_latency'] == 1
    good = case == 'good'
    assert result.status == ('PASS' if good else 'FAIL'), result.detail
    if case in ('missing_contract', 'changed_binding'):
        assert manifest['cases'] == []
        assert 'MISSING_OBSERVATION_CONTRACT' in manifest['not_a_subject'][0]['detail']
    else:
        prepared = Path(manifest['cases'][0]['testbench'])
        plan = arith._scenario_header(prepared)
        if case == 'good' or manifest['cases'][0].get('observation') is not None:
            assert plan['observation']['top'] == 'public_surface'
            assert plan['observation']['sample_offset_ns'] == 4
            assert plan['framing'] == original_plan['framing']
            assert plan['pairs'] == json.loads(json.dumps(original_plan['pairs']))
            assert plan['transactions'] == original_plan['transactions'] == 16
            assert plan['comparisons'] == original_plan['comparisons'] == 128
            assert '.chip_clock(i_clk)' in prepared.read_text()
            assert '.chip_result(result_bit)' in prepared.read_text()
            assert manifest['cases'][0]['observation'] == plan['observation']
        runs = json.loads((native[0] / 'gls_runs.json').read_text())['runs']
        assert len(runs) == len(CORNERS)
        for run in runs:
            assert run['compile_rc'] == 0, Path(run['compile_log']).read_text()
            assert run['sim_rc'] == (0 if good else 1)
            transcript = Path(run['stdout']).read_text()
            assert 'transactions=16 comparisons=128' in transcript
    gate = json.loads((project / 'reports/phase2/gates/post_layout_sim.json').read_text())
    assert gate['verdict'] == ('PASS' if good else 'FAIL')
    latest = versions.latest_pass(project, '29')
    assert (latest is not None) is good
    assert (runner._pl.sim_postlayout_dir(project) / 'pass.flag').exists() is good
    put(project / 'observation_adapter_readback.json', {
        'case': case, 'status': result.status, 'physical_contract':
        manifest['cases'][0].get('observation') if manifest['cases'] else None,
        'original_tb_unchanged': True, 'native_claim': False})


def _current_output_deadline_fixture(project, root, deadline):
    """Neutral native grammar; real current-scene reader, never a timing result."""
    folder = next((project / 'phase3/librelane').glob('22-23/*stapostpnr'))
    state = json.loads((folder / 'state_out.json').read_text())
    state['spef'] = {p: str(write(folder / f'public_surface.{p[:-2]}.spef', '*SPEF fixture'))
                     for p in ('nom_*', 'min_*', 'max_*')}
    libs = {}
    for corner in CORNERS:
        process, temp, voltage = corner.split('_')[1:]
        lib = write(root / 'x/libs.ref/cells/lib' / _lib_of(corner),
                    f'library(fixture) {{\n nom_process : 1;\n nom_voltage : {float(voltage.replace("v", "."))};\n'
                    f' nom_temperature : {(-float(temp[1:-1]) if temp.startswith("n") else float(temp[:-1]))};\n}}\n')
        libs[corner] = [str(lib)]
        spef = state['spef'][corner.split('_')[0] + '_*']
        write(folder / corner / 'sta.log',
              f"Reading cell library for the '{corner}' corner at '{lib}'\n"
              f"Reading top-level design parasitics for the '{corner}' corner at '{spef}'\n")
        write(folder / corner / 'max.rpt',
              'Startpoint: result_ff (rising edge-triggered flip-flop clocked by clk)\n'
              'Endpoint: chip_result (output port clocked by clk)\nPath Group: clk\nPath Type: max\n'
              f' {deadline:.6f} data required time\n 1.000000 data arrival time\n 1.000000 slack (MET)\n')
    put(folder / 'state_out.json', state)
    put(folder / 'config.json', {'meta': {'step': 'OpenROAD.STAPostPNR'},
         'DESIGN_NAME': 'public_surface', 'STA_CORNERS': list(CORNERS), 'CELL_LIBS': libs})
    fingerprint = {
        'step': 'OpenROAD.STAPostPNR',
        'state_files': {str(Path(f)): contract.digest(Path(f))
                        for f in [*(state[v] for v in ('nl', 'sdc', 'odb', 'def')), *state['spef'].values()]},
        'liberty_files': {f: contract.digest(Path(f)) for group in libs.values() for f in group}}
    from test_default_current_power import seal
    seal(folder, fingerprint)
    put(project / postroute.STEP23_RECORD, {'mode': 'librelane',
         'sta_state': str(folder / 'state_out.json'),
         'sta_state_sha256': contract.digest(folder / 'state_out.json')})
    return folder


@pytest.mark.parametrize('case', ['good', 'random', 'combined', 'case_fail', 'wrong_cycle', 'late', 'missing_corner', 'changed_corner', 'wrong_output', 'wrong_clock'])
def test_default_gls_observes_the_current_output_deadline(
        tmp_path, monkeypatch, local_image, case):
    """Actual Default capture, typed INPUT schedule and real Icarus verdicts."""
    import execution_backend_producers as backend
    import execution_policy
    import phase3_one_shot_runner as runner
    import step_output_collector as versions
    import arith_oracle_tb_gen as arith

    project, root, model, bench, original_plan = _declared_observation_gls_project(tmp_path, case)
    # Keep the same input timing, arithmetic population, comparator and latency.
    # A slow-but-on-time output crosses the half period; a later one must fail.
    text = model.read_text().replace('(1.8,1.8)', '(19.5,19.5)' if case == 'late' else '(14.0,14.0)')
    model.write_text(text)
    decl_path = project / 'plugin_output/declaration.json'
    decl = json.loads(decl_path.read_text())
    decl['verification_stimuli']['arithmetic_observation']['public_surface']['binding'][str(model.resolve())] = contract.digest(model)
    put(decl_path, decl)
    folder = _current_output_deadline_fixture(project, root, 18.949999)
    for sdf in folder.rglob('*.sdf'):
        sdf.write_text(sdf.read_text().replace('(1.8:1.8:1.8)', '(19.5:19.5:19.5)' if case == 'late' else '(14.0:14.0:14.0)'))
    if case == 'wrong_cycle':
        nl = Path(json.loads((folder / 'state_out.json').read_text())['nl'])
        body = nl.read_text().replace('PUBLIC_OUT output_pad (.A(result_bit)',
                  'reg extra_bit=0; always @(posedge i_clk) extra_bit<=result_bit;\n PUBLIC_OUT output_pad (.A(extra_bit)')
        nl.write_text(body)
    # Bind neutral producer bytes before testing absence / tampering.
    _current_output_deadline_fixture(project, root, 18.949999)
    report = folder / CORNERS[-1] / 'max.rpt'
    if case == 'missing_corner':
        report.unlink()
    elif case in ('changed_corner', 'wrong_output', 'wrong_clock'):
        report.write_text(report.read_text().replace('chip_result', 'another_output') if case == 'wrong_output'
                          else report.read_text().replace('clocked by clk', 'clocked by other') if case == 'wrong_clock'
                          else report.read_text() + '\nchanged bytes\n')
        if case in ('wrong_output', 'wrong_clock'):
            receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
            receipt['sha256'][str(report.relative_to(folder))] = contract.digest(report)
            put(folder / 'vibeic_receipt.json', receipt)
    original_bytes = bench.read_bytes()
    put(project / 'phase3/librelane_switch.json', {
        'image': local_image.image, 'pdk_root_host': str(root), 'pdk': 'x'})
    cfg = SimpleNamespace(name='x')
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {
        'pdk_name': 'x', 'pdk_root': str(root), 'image_id': local_image.image})
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, contract, cfg, 'SOURCE_FIXTURE_ONLY'))
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    edge, _ = _gls_edge([str(model)], lambda c: VVP_PASS)
    native = []
    def process_edge(argv, **kwargs):
        if any('from librelane.flows.chip import Chip' in str(arg) for arg in argv):
            return edge(argv[:-1], **kwargs)
        if '--id' not in argv:
            return edge(argv, **kwargs)
        from librelane.state import DesignFormat
        monkeypatch.syspath_prepend(str(contract.PLUGIN_ROOT))
        from librelane_plugin_vibeic import GateLevelSim
        folder = Path(argv[argv.index('-o') + 1])
        folder.mkdir(parents=True, exist_ok=True)
        config = json.loads(Path(argv[argv.index('-c') + 1]).read_text())
        incoming = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        instance = SimpleNamespace(config={
            'VIBEIC_GLS_MANIFEST': config['VIBEIC_GLS_MANIFEST'], 'VIBEIC_GLS_TIMEOUT_S': 30},
            step_dir=str(folder), _run=GateLevelSim._run)
        GateLevelSim.run(instance, {DesignFormat.NETLIST: incoming['nl'], DesignFormat.SDF: incoming['sdf']})
        put(folder / 'state_out.json', incoming)
        native.append(folder)
        return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY: actual Icarus completed\n', stderr='')
    monkeypatch.setattr(contract, 'run_container', process_edge)
    result = runner._default_pnr_rows(project, 'public_serial_product', cfg, 'SOURCE_FIXTURE_ONLY', ['29'])
    manifest_path = project / 'phase3/librelane/29-config/gls/gls_manifest.json'
    if case in ('missing_corner', 'changed_corner'):
        # The bound native producer is checked before compiling a GLS manifest.
        # Tampering still refuses, at the earlier owning boundary.
        assert result.status == 'FAIL', result.detail
        assert 'LL_STEP_OUTPUT_UNBOUND' in result.detail
        assert 'max.rpt' in result.detail
        assert native == [] and not manifest_path.exists()
        assert bench.read_bytes() == original_bytes
        gate = json.loads((project / 'reports/phase2/gates/post_layout_sim.json').read_text())
        assert gate['verdict'] in ('FAIL', 'ERROR')
        assert versions.latest_pass(project, '29') is None
        return
    manifest = json.loads(manifest_path.read_text())
    assert bench.read_bytes() == original_bytes
    assert original_plan['observation']['sample_offset_ns'] == 1
    assert original_plan['framing']['settled_latency'] == 1
    good = case in ('good', 'random', 'combined')
    assert result.status == ('PASS' if good else 'FAIL'), result.detail
    if case in ('missing_corner', 'changed_corner', 'wrong_output', 'wrong_clock'):
        assert manifest['cases'] == []
        assert 'POSTLAYOUT_OBSERVATION_UNMEASURED' in manifest['not_a_subject'][0]['detail']
    else:
        prepared = Path(manifest['cases'][0]['testbench'])
        plan = arith._scenario_header(prepared)
        if case == 'good' or manifest['cases'][0].get('observation') is not None:
            assert plan['observation']['top'] == 'public_surface'
            assert plan['observation']['sample_offset_ns'] == 18.949
            assert set(plan['observation']['postlayout_deadline']['required_time_ns']) == set(CORNERS)
            assert plan['framing'] == original_plan['framing']
            assert plan['pairs'] == json.loads(json.dumps(original_plan['pairs']))
            assert plan['transactions'] == original_plan['transactions']
            assert plan['comparisons'] == original_plan['comparisons']
            assert '.chip_clock(i_clk)' in prepared.read_text()
            assert '.chip_result(result_bit)' in prepared.read_text()
            assert manifest['cases'][0]['observation'] == plan['observation']
        import subprocess
        source = prepared.read_text()
        monitor = ('\nmodule drive_monitor; always @(negedge transaction_sequence.i_clk) #0 '
                   '$strobe("DRIVE %0t %b %b %b",$time,transaction_sequence.i_rst,'
                   'transaction_sequence.operand_word,transaction_sequence.serial_bit); endmodule\n')
        old_plan = json.loads(json.dumps(plan))
        old_plan['observation'].pop('postlayout_deadline')
        old_plan['observation']['sample_offset_ns'] = 4
        old = arith.emit_arithmetic_scenario_module('transaction_sequence', old_plan, dut_module='public_serial_product')
        old, _ = sgs.bind_dut_module(old, 'public_serial_product', 'dut',
                                   Path(manifest['netlist']).read_text(), manifest['dut_binding'])
        drives = []
        for label, tb in [('model_only', old), ('deadline', source)]:
            path = write(tmp_path / f'{label}.v', __import__('re').sub(r'(?m)^\s*initial\s+\$sdf_annotate[^;]+;[^\n]*\n', '', tb) + monitor)
            # Separate cadence observation: no change to the real GLS run above.
            binary = tmp_path / f'{label}.vvp'
            c = subprocess.run(['iverilog', '-g2012', '-gspecify', '-s', 'transaction_sequence', '-s', 'drive_monitor',
                                '-o', str(binary), str(path), manifest['netlist'], str(model)], capture_output=True, text=True)
            assert c.returncode == 0, c.stderr
            run = subprocess.run(['vvp', str(binary)], capture_output=True, text=True)
            drives.append([line for line in run.stdout.splitlines() if line.startswith('DRIVE ')])
        # The last observer may finish after the driver's last negedge. Compare
        # all original drive instants and require no inserted/missed update.
        assert drives[1][:len(drives[0])] == drives[0]
        assert len(drives[1]) == len(drives[0])
        runs = json.loads((native[0] / 'gls_runs.json').read_text())['runs']
        assert len(runs) == len(CORNERS)
        for run in runs:
            assert run['compile_rc'] == 0, Path(run['compile_log']).read_text()
            assert run['sim_rc'] == (0 if good else 1)
            transcript = Path(run['stdout']).read_text()
            assert f"transactions={original_plan['transactions']} comparisons={original_plan['comparisons']}" in transcript
            if case == 'random':
                assert 'ORACLE_TB_DONE pass=10000/10000' in transcript
            if case == 'combined':
                measured, detail = arith.capture_arithmetic_scenario_execution(project, prepared, Path(run['stdout']), {})
                assert measured is not None and measured['complete'] is True and measured['errors'] == 0, detail
    gate = json.loads((project / 'reports/phase2/gates/post_layout_sim.json').read_text())
    assert gate['verdict'] == ('PASS' if good else 'FAIL')
    latest = versions.latest_pass(project, '29')
    assert (latest is not None) is good
    assert (runner._pl.sim_postlayout_dir(project) / 'pass.flag').exists() is good
    put(project / 'observation_adapter_readback.json', {
        'case': case, 'status': result.status, 'physical_contract':
        manifest['cases'][0].get('observation') if manifest['cases'] else None,
        'original_tb_unchanged': True, 'native_claim': False})


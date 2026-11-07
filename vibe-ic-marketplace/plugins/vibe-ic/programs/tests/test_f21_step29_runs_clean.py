"""F21 — step 29's post-layout gate-level simulation actually runs, and runs clean.

MEASURED on spm x gf180mcuD (run23 copy, vibeic-eda 0.3.79), before this lane:

* direct arm: NOT_EXECUTED, 0 delays -- every L10 case instantiates the core
  `spm`, the routed netlist defines only the padded `chip_top`;
* tool arm: 315 `SDF ERROR` per corner, unclassified, failing every corner;
* ss corners: 0/5 cases -- the bench clocked at its own 10 ns default against a
  declared `create_clock -period 24.0`.

After: both arms 5/5 at every corner, the DUT bound through the chip-top
producer's record, the bench clocked from the declared SDC, and every refused
SDF record classified from the run's own artefacts (an unexplained one fails).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import sdf_gate_sim as sgs  # noqa: E402

CAL = PROGRAMS / 'calibration'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def put(path, obj):
    return write(path, json.dumps(obj))


#: The routed netlist step 15 leaves: flattened, top `chip_top`, a bus through
#: per-bit pads, a bidirectional pad on the output.
ROUTED = '''module chip_top (clk, x, p);
 input clk;
 input [1:0] x;
 output p;
 cells__in_c u_pad_clk (.PAD(clk), .Y(n0));
 cells__in_c u_pad_x_0 (.PAD(x[0]), .Y(n1));
 cells__in_c u_pad_x_1 (.PAD(x[1]), .Y(n2));
 cells__dffq_1 \\u_core/_416_  (.D(n1), .CLK(n0), .Q(n3));
 cells__bi_24t u_pad_p (.A(n3), .OE(n2), .PAD(p));
endmodule
'''

#: What the chip-top producer (step 15.5ic) wrote and records.
CHIP_TOP_IO = '''module chip_top (input clk, input [1:0] x, output p);
  wire clk__core; wire [1:0] x__core; wire p__core;
  cells__in_c u_pad_clk (.PAD(clk), .Y(clk__core));
  cells__in_c u_pad_x_0 (.PAD(x[0]), .Y(x__core[0]));
  cells__in_c u_pad_x_1 (.PAD(x[1]), .Y(x__core[1]));
  cells__bi_24t u_pad_p (.A(p__core), .OE(1'b1), .PAD(p));
  core u_core (.clk_i(clk__core), .x_i(x__core), .p_o(p__core));
endmodule
'''

RECORD = {
    'verdict': 'WROTE', 'chip_top_module': 'chip_top', 'core_module': 'core',
    'chip_top_verilog': 'phase3/stage3/pnr/chip_top_io.v',
    'io_library_liberty': ['/pdk/x/libs.ref/pads/lib/pads__tt.lib'],
    'pad_instances': {
        'u_pad_clk': {'port': 'clk', 'terminal': 'PAD', 'core_pin': 'Y'},
        'u_pad_x_0': {'port': 'x[0]', 'terminal': 'PAD', 'core_pin': 'Y'},
        'u_pad_x_1': {'port': 'x[1]', 'terminal': 'PAD', 'core_pin': 'Y'},
        'u_pad_p': {'port': 'p', 'terminal': 'PAD', 'core_pin': 'A'},
        'u_pad_vdd': {'port': 'VDD', 'terminal': 'DVDD', 'core_pin': None}}}

#: An L10 bench as phase 2 writes it: the CORE's ports (named differently from
#: the chip's, so no name match can bind it), and a 10 ns bench default clock.
TB = '''`timescale 1ns/1ps
module case_1;
  reg clk; reg [1:0] x; wire p;
  core dut (.clk_i(clk), .x_i(x), .p_o(p));
  initial clk = 1'b0;
  always #5 clk = ~clk;
  initial begin x = 0; @(posedge clk); $display("ORACLE_TB_DONE pass=1/1"); $finish; end
endmodule
'''

SDC = 'set period 24.0\ncreate_clock -name core_clk -period $period [get_ports clk]\n'
SDF_HEAD = '(DELAYFILE\n (SDFVERSION "3.0")\n (DIVIDER .)\n (TIMESCALE 1ns)\n)\n'


def _project(tmp_path, *, record=True):
    project = tmp_path / 'design'
    write(project / 'phase3/stage3/pnr/spm_pnr.v', ROUTED)
    write(project / 'phase3/stage3/pnr/constraint.sdc', SDC)
    if record:
        write(project / 'phase3/stage3/pnr/chip_top_io.v', CHIP_TOP_IO)
        put(project / sgs.CHIP_TOP_RECORD_REL, RECORD)
    tb = write(project / 'phase2/stage1/sim/case_1.v', TB)
    put(project / 'reports/phase2/sim/l10_execution.json',
        {'cases': [{'id': 'case_1', 'sim_executed': True, 'tb_file': str(tb)}]})
    return project


# ------------------------------------------------ 3. the DUT, as declared ---

def test_the_dut_binds_through_the_declared_chip_top_pad_by_pad(tmp_path):
    project = _project(tmp_path)
    declared = sgs.declared_dut_binding(project, 'core', ROUTED)
    assert declared['dut_module'] == 'chip_top' and declared['rebound']
    # core port -> its net in the declared Verilog -> the pad -> the chip port
    assert declared['port_map'] == {'clk_i': 'clk', 'x_i': 'x', 'p_o': 'p'}
    text, binding = sgs.bind_dut_module(TB, 'core', 'dut', ROUTED, declared)
    assert 'chip_top dut (.clk(clk), .x(x), .p(p));' in text
    assert binding['ports'] == {'clk_i': 'clk', 'p_o': 'p', 'x_i': 'x'}


def test_without_the_chip_top_record_nothing_is_bound_by_name(tmp_path):
    """The netlist top has a clk/x/p and the bench a clk/x/p signal: a name
    match would bind it. The record is absent, so it refuses."""
    project = _project(tmp_path, record=False)
    with pytest.raises(ValueError, match='NO_DECLARED_CHIP_TOP'):
        sgs.declared_dut_binding(project, 'core', ROUTED)
    same_names = TB.replace('.clk_i(clk), .x_i(x), .p_o(p)', '.clk(clk), .x(x), .p(p)')
    with pytest.raises(ValueError):
        sgs.bind_dut_module(same_names, 'core', 'dut', ROUTED)


@pytest.mark.parametrize('change', ['none', 'other_core', 'wrong_chip', 'missing_pad'])
def test_native_preparation_traces_existing_core_bench(tmp_path, change):
    project = _project(tmp_path, record=False)
    write(project / 'phase2/stage1/rtl/core.v',
          'module core(input clk_i,input [1:0] x_i,output p_o); assign p_o=x_i[0]; endmodule\n')
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'core'})
    write(project / 'work/flow/chip/wrapper.v', CHIP_TOP_IO)
    put(project / 'work/flow/chip/config.json',
        {'DESIGN_NAME': 'other_chip' if change == 'wrong_chip' else 'chip_top'})
    pads = dict(RECORD['pad_instances'])
    if change == 'missing_pad':
        pads.pop('u_pad_clk')
    put(project / 'work/flow/chip/preparation.json', {'pads': pads})
    if change != 'none':
        with pytest.raises(ValueError):
            sgs.declared_dut_binding(project, 'another_core' if change == 'other_core' else 'core', ROUTED)
    else:
        declared = sgs.declared_dut_binding(project, 'core', ROUTED)
        bound, _ = sgs.bind_dut_module(TB, 'core', 'dut', ROUTED, declared)
        assert 'chip_top dut (.clk(clk), .x(x), .p(p));' in bound
        assert declared['port_map'] == {'clk_i': 'clk', 'x_i': 'x', 'p_o': 'p'}
    assert not (project / sgs.CHIP_TOP_RECORD_REL).exists()


@pytest.mark.parametrize('edit,code', [
    (lambda r: {**r, 'core_module': 'other'}, 'CHIP_TOP_WRAPS_ANOTHER_CORE'),
    (lambda r: {**r, 'chip_top_module': 'pad_ring'}, 'ROUTED_TOP_IS_NOT_THE_DECLARED_CHIP_TOP'),
    (lambda r: {**r, 'pad_instances': {k: v for k, v in r['pad_instances'].items()
                                       if k != 'u_pad_clk'}}, 'CORE_PORT_NOT_TRACEABLE'),
])
def test_a_declaration_that_does_not_trace_refuses(tmp_path, edit, code):
    project = _project(tmp_path)
    put(project / sgs.CHIP_TOP_RECORD_REL, edit(RECORD))
    with pytest.raises(ValueError, match=code):
        sgs.declared_dut_binding(project, 'core', ROUTED)


def test_a_netlist_that_defines_the_dut_binds_unchanged(tmp_path):
    netlist = 'module core (clk_i, x_i, p_o);\nendmodule\n'
    assert sgs.declared_dut_binding(tmp_path, 'core', netlist)['rebound'] is False
    assert sgs.bind_dut_module(TB, 'core', 'dut', netlist)[0] == TB


# ------------------------------------------ 1. the clock, from the SDC ---

def test_the_bench_clock_is_the_declared_sdc_period(tmp_path):
    project = _project(tmp_path)
    clocks = sgs.declared_sdc_clocks(project / 'phase3/stage3/pnr/constraint.sdc', [SDF_HEAD])
    assert clocks['clocks_s'] == {'clk': pytest.approx(24e-9)}
    bound, _ = sgs.bind_dut_module(TB, 'core', 'dut', ROUTED,
                                   sgs.declared_dut_binding(project, 'core', ROUTED))
    text, info = sgs.bind_bench_clock(bound, 'dut', clocks)
    assert 'always #12 clk = ~clk;' in text and 'always #5 ' not in text
    assert info['clocks'][0]['bench_default'] == '5'


def test_the_sdc_units_statement_outranks_the_sdf_timescale(tmp_path):
    sdc = write(tmp_path / 'c.sdc', 'set_units -time ps\ncreate_clock -period 2000 [get_ports clk]\n')
    clocks = sgs.declared_sdc_clocks(sdc, [SDF_HEAD])
    assert clocks['clocks_s'] == {'clk': pytest.approx(2e-9)}
    assert 'set_units' in clocks['unit_source']


@pytest.mark.parametrize('sdc,sdfs,code', [
    (None, [SDF_HEAD], 'SDC_UNREADABLE'),
    ('create_clock -period [expr 2*$p] [get_ports clk]\n', [SDF_HEAD], 'SDC_CLOCK_UNREADABLE'),
    ('create_clock -period 10 [get_ports clk]\ncreate_clock -period 12 [get_ports clk]\n',
     [SDF_HEAD], 'SDC_CLOCK_AMBIGUOUS'),
    ('create_clock -period 10 [get_ports clk]\n', ['(DELAYFILE)\n'], 'SDC_TIME_UNIT_UNSTATED'),
    ('create_clock -period 10 [get_ports clk]\n',
     [SDF_HEAD, SDF_HEAD.replace('1ns', '1ps')], 'SDC_TIME_UNIT_UNSTATED'),
])
def test_an_sdc_clock_this_cannot_read_refuses_and_is_never_guessed(tmp_path, sdc, sdfs, code):
    path = tmp_path / 'c.sdc'
    if sdc is not None:
        write(path, sdc)
    with pytest.raises(ValueError, match=code):
        sgs.declared_sdc_clocks(path, sdfs)


def test_an_sdc_with_no_port_clock_clocks_no_port_and_refuses_a_free_running_bench(tmp_path):
    """A combinational design (only a virtual clock) is not refused for having
    no clock; a bench that free-runs a DUT port against it is."""
    sdc = write(tmp_path / 'c.sdc', 'create_clock -name v -period 10\n')
    declared = sgs.declared_sdc_clocks(sdc, ['(DELAYFILE)\n'])
    assert declared['clocks_s'] == {}
    comb = TB.replace('  always #5 clk = ~clk;\n', '')
    assert sgs.bind_bench_clock(comb, 'dut', declared)[0] == comb
    with pytest.raises(ValueError, match='BENCH_CLOCK_UNDECLARED'):
        sgs.bind_bench_clock(TB, 'dut', declared)


@pytest.mark.parametrize('tb,clocks,code', [
    (TB.replace('`timescale 1ns/1ps\n', ''), {'clk': 24e-9}, 'BENCH_TIMESCALE_UNSTATED'),
    (TB.replace('always #5 clk = ~clk;', 'initial #5 clk = 1;'), {'clk': 24e-9},
     'BENCH_CLOCK_NOT_BOUND'),
    (TB, {'x': 24e-9}, 'BENCH_CLOCK_UNDECLARED'),
    (TB, {'clk': 24.0005e-9}, 'BENCH_PRECISION'),
])
def test_a_bench_clock_the_sdc_does_not_declare_refuses(tb, clocks, code):
    bound = tb.replace('core dut (.clk_i(clk), .x_i(x), .p_o(p))',
                       'chip_top dut (.clk(clk), .x(x), .p(p))')
    with pytest.raises(ValueError, match=code):
        sgs.bind_bench_clock(bound, 'dut', {'sdc': 's.sdc', 'unit_source': 'u',
                                            'clocks_s': clocks})


# ------------------------------------------ 2. SDF errors, by class ---

def _cal(side):
    return {'transcript': (CAL / f'cal_sdf_class_{side}.log').read_text(),
            'compile_log': (CAL / f'cal_sdf_class_{side}.compile.log').read_text(),
            'sdf_text': (CAL / 'cal_sdf_class.sdf').read_text(),
            'explainer': sgs.SdfErrorExplainer(
                (CAL / 'cal_sdf_class.v').read_text(),
                {n: (CAL / n).read_text() for n in ('cal_sdf_class_cells.v',
                                                    'cal_sdf_class_pad.v')})}


def _classify(bundle, **over):
    b = {**bundle, **over}
    return sgs.classify_sdf_errors(b['transcript'], compile_log=b['compile_log'],
                                   sdf_text=b['sdf_text'], explainer=b['explainer'])


def test_the_two_measured_classes_are_explained_from_the_runs_own_artefacts():
    """REAL Icarus output on the PDK's own mux2 + bidirectional pad."""
    got = _classify(_cal('negative'))
    assert got['by_class'] == {'IFNONE_EDGE_PATH_DROPPED': 2, 'INOUT_PORT_INTERCONNECT': 1}
    assert got['unexplained'] == 0 and got['total'] == 3


def test_a_record_no_class_explains_is_counted_unexplained():
    got = _classify(_cal('positive'))
    assert got['total'] == 19 and got['unexplained'] == 16
    assert got['total'] == sgs.sdf_error_count(_cal('positive')['transcript'])


def test_an_ifnone_record_without_the_compilers_sorry_is_not_explained():
    """The class is granted on the run's proof, not on the message's shape."""
    got = _classify(_cal('negative'), compile_log='')
    assert got['by_class'] == {'INOUT_PORT_INTERCONNECT': 1} and got['unexplained'] == 2


def test_an_interconnect_record_on_a_non_inout_endpoint_is_not_explained():
    # FX_SPM_GATES_2: the record here is `(INTERCONNECT u_pad.PAD p
    # (0.000:0.000:0.000))` -- zero delay to the top port `p`, which the
    # ZERO_DELAY_TOP_PORT_INTERCONNECT class now explains ON ITS OWN MERITS.
    # This test pins a different fact: the INOUT class is never granted to a
    # non-inout endpoint. So the record is given a NON-zero delay, which no
    # class may explain, and every assertion below is unchanged.
    bundle = _cal('negative')
    bundle['sdf_text'] = bundle['sdf_text'].replace(
        '(INTERCONNECT u_pad.PAD p (0.000:0.000:0.000))',
        '(INTERCONNECT u_pad.PAD p (0.004:0.004:0.004))')
    assert '(INTERCONNECT u_pad.PAD p (0.004:0.004:0.004))' in bundle['sdf_text']
    pad = (CAL / 'cal_sdf_class_pad.v').read_text().replace('inout\tPAD;', 'output\tPAD;')
    explainer = sgs.SdfErrorExplainer((CAL / 'cal_sdf_class.v').read_text(),
                                      {'cal_sdf_class_cells.v': (CAL / 'cal_sdf_class_cells.v').read_text(),
                                       'cal_sdf_class_pad.v': pad})
    got = _classify(bundle, explainer=explainer)
    assert got['by_class'] == {'IFNONE_EDGE_PATH_DROPPED': 2} and got['unexplained'] == 1


def test_two_interconnect_records_on_one_line_cannot_borrow_inout_explanation():
    bundle = _cal('negative')
    records = ('(INTERCONNECT u_pad.PAD p (0.000:0.000:0.000)) '
               '(INTERCONNECT u0.Z u_pad.A (0.004:0.004:0.004))')
    bundle['sdf_text'] = bundle['sdf_text'].replace(
        '(INTERCONNECT u_pad.PAD p (0.000:0.000:0.000))', records)
    assert records in bundle['sdf_text'].splitlines()[24]
    got = _classify(
        bundle,
        transcript='SDF ERROR: cal_sdf_class.sdf:25: Could not find intermodpath!\n',
        compile_log='')
    assert got['total'] == 1
    assert got['by_class'] == {}
    assert got['unexplained'] == 1


def _tool_step(tmp_path, transcript, compile_log):
    """What `Vibeic.GateLevelSim` leaves: gls_runs.json and per-run logs."""
    step = tmp_path / 'step'
    sdf = write(tmp_path / 'corner.sdf', (CAL / 'cal_sdf_class.sdf').read_text())
    rows = []
    for corner in ('nom_tt', 'max_ss'):
        out = write(step / corner / 'c.stdout.log', transcript + 'ORACLE_TB_DONE pass=1/1\n')
        log = write(step / corner / 'c.compile.log', compile_log)
        rows.append({'corner': corner, 'case': 'c', 'sdf': str(sdf), 'compile_rc': 0,
                     'sim_rc': 0, 'stdout': str(out), 'compile_log': str(log)})
    put(step / 'gls_runs.json', {'runs': rows})
    manifest = {'netlist': str(CAL / 'cal_sdf_class.v'), 'cases': [{'id': 'c'}],
                'model_closure': {'files': [str(CAL / 'cal_sdf_class_cells.v'),
                                            str(CAL / 'cal_sdf_class_pad.v')]}}
    return step, manifest


def test_a_corner_whose_every_refused_record_is_explained_passes():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        step, manifest = _tool_step(Path(d), (CAL / 'cal_sdf_class_negative.log').read_text(),
                                    (CAL / 'cal_sdf_class_negative.compile.log').read_text())
        judged = sgs.judge_tool_arm(step, manifest)
    assert judged['verdict'] == 'PASS', judged['corners']
    row = judged['corners']['nom_tt']
    assert row['sdf_errors'] == 3 and row['sdf_errors_unexplained'] == 0
    assert row['sdf_errors_by_class'] == {'IFNONE_EDGE_PATH_DROPPED': 2,
                                          'INOUT_PORT_INTERCONNECT': 1}


def test_a_corner_with_an_unexplained_record_fails(tmp_path):
    step, manifest = _tool_step(tmp_path, (CAL / 'cal_sdf_class_positive.log').read_text(),
                                (CAL / 'cal_sdf_class_positive.compile.log').read_text())
    judged = sgs.judge_tool_arm(step, manifest)
    assert judged['verdict'] == 'FAIL'
    assert all('SDF_ERRORS' in c['reasons'] for c in judged['corners'].values())
    assert judged['corners']['max_ss']['sdf_errors_unexplained'] == 16


def test_the_evidence_names_every_class_its_owner_and_its_fork(tmp_path):
    step, manifest = _tool_step(tmp_path, (CAL / 'cal_sdf_class_negative.log').read_text(),
                                (CAL / 'cal_sdf_class_negative.compile.log').read_text())
    sim = tmp_path / 'sim'
    sgs.write_tool_arm_results(sim, sgs.judge_tool_arm(step, manifest), 'chip_top')
    log = (sim / 'results.log').read_text()
    assert 'IFNONE_EDGE_PATH_DROPPED 2 (owner tool:iverilog, ' + sgs.IFNONE_FORK in log
    assert 'INOUT_PORT_INTERCONNECT 1 (owner tool:iverilog, ' + sgs.INOUT_FORK in log
    assert 'unexplained 0' in log and (sim / 'pass.flag').is_file()


# ------------------------------------------ the tool arm's manifest ---

def test_the_tool_arm_prepares_benches_bound_and_clocked_as_declared(tmp_path):
    project = _project(tmp_path)
    sdf = write(tmp_path / 'c.sdf', SDF_HEAD)
    models = write(tmp_path / 'pdk/cells.v', 'module cells__in_c (PAD, Y); input PAD; '
                   'output Y; buf (Y, PAD); endmodule\n')
    manifest = sgs.tool_arm_manifest(project, 'core', project / 'phase3/stage3/pnr/spm_pnr.v',
                                     [models], tmp_path / 'gls',
                                     sdc=project / 'phase3/stage3/pnr/constraint.sdc',
                                     sdfs=[sdf])
    assert [c['id'] for c in manifest['cases']] == ['case_1']
    tb = Path(manifest['cases'][0]['testbench']).read_text()
    assert 'chip_top dut (.clk(clk), .x(x), .p(p))' in tb
    assert 'always #12 clk = ~clk;' in tb
    assert manifest['clock']['clocks_s'] == {'clk': pytest.approx(24e-9)}


def test_the_tool_arm_refuses_a_run_whose_sdc_it_cannot_read(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match='SDC_UNREADABLE'):
        sgs.tool_arm_manifest(project, 'core', project / 'phase3/stage3/pnr/spm_pnr.v',
                              [], tmp_path / 'gls', sdc=tmp_path / 'absent.sdc',
                              sdfs=[write(tmp_path / 'c.sdf', SDF_HEAD)])


# ------------------------------------------ the direct arm, end to end ---

def _direct(tmp_path, monkeypatch, transcript, compile_log):
    """Drive `_run_l10_suite` with the simulator's file writes faked. The pad
    on `p` is the calibration's real gf180 bi_24t, under the routed name."""
    project = _project(tmp_path)
    write(project / 'phase3/stage3/pnr/spm_pnr.v',
          ROUTED.replace('cells__bi_24t u_pad_p', 'gf180mcu_fd_io__bi_24t u_pad_p'))
    sim = tmp_path / 'design/phase3/stage3/sim_postlayout'
    sim.mkdir(parents=True)
    sdf = write(sim / 'spm.sdf', (CAL / 'cal_sdf_class.sdf').read_text()
                .replace('u_pad.', 'u_pad_p.'))
    seen = []

    def fake(container, cmd, budget_s=600):
        seen.append(cmd)
        if 'iverilog' in cmd:
            write(sim / 'case_1.compile.log', compile_log)
        else:
            write(sim / 'case_1.stdout.log', transcript + 'ORACLE_TB_DONE pass=1/1\n')
        return SimpleNamespace(stdout='RC=0\n', returncode=0)
    monkeypatch.setattr(sgs, '_docker', fake)
    models = sgs.CellModels(['/m/cal_sdf_class_cells.v', '/m/cal_sdf_class_pad.v'],
                            '', 'test', files={
                                '/m/cal_sdf_class_cells.v': (CAL / 'cal_sdf_class_cells.v').read_text(),
                                '/m/cal_sdf_class_pad.v': (CAL / 'cal_sdf_class_pad.v').read_text()})
    suite = sgs.find_l10_executed_cases(project, 'core')
    netlist = project / 'phase3/stage3/pnr/spm_pnr.v'
    res = sgs._run_l10_suite(project, 'core', 'c', sim, netlist, sdf, models,
                             sgs.netlist_used_cells(ROUTED), suite, [])
    return res, sim, seen


def test_the_direct_arm_runs_the_core_suite_on_the_chip_top_at_the_sdc_clock(
        tmp_path, monkeypatch):
    res, sim, _ = _direct(tmp_path, monkeypatch,
                          (CAL / 'cal_sdf_class_negative.log').read_text(),
                          (CAL / 'cal_sdf_class_negative.compile.log').read_text())
    assert res['verdict'] == 'PASS' and res['executed'] == 1
    tb = (sim / 'case_1_sdf_gate.v').read_text()
    assert 'chip_top dut (.clk(clk), .x(x), .p(p))' in tb and 'always #12 clk' in tb
    doc = json.loads((sim / 'results.json').read_text())
    assert doc['sdf_errors_unexplained'] == 0
    assert doc['sdf_errors_by_class'] == {'IFNONE_EDGE_PATH_DROPPED': 2,
                                          'INOUT_PORT_INTERCONNECT': 1}
    assert (sim / 'pass.flag').is_file()


def test_the_direct_arm_fails_on_an_unexplained_record(tmp_path, monkeypatch):
    res, sim, _ = _direct(tmp_path, monkeypatch,
                          (CAL / 'cal_sdf_class_positive.log').read_text(),
                          (CAL / 'cal_sdf_class_positive.compile.log').read_text())
    assert res['verdict'] == 'FAIL'
    assert 'ERROR: 16 SDF ERROR record(s) no class explains' in (sim / 'results.log').read_text()
    assert not (sim / 'pass.flag').exists()


def test_the_direct_arm_refuses_every_case_when_the_dut_is_not_declared(tmp_path, monkeypatch):
    project = _project(tmp_path, record=False)
    sim = project / 'phase3/stage3/sim_postlayout'
    sim.mkdir(parents=True)
    sdf = write(sim / 'spm.sdf', SDF_HEAD)
    monkeypatch.setattr(sgs, '_docker', lambda *a, **k: pytest.fail('nothing may run'))
    res = sgs._run_l10_suite(project, 'core', 'c', sim, project / 'phase3/stage3/pnr/spm_pnr.v',
                             sdf, sgs.CellModels([], '', 't'), set(),
                             sgs.find_l10_executed_cases(project, 'core'), [])
    assert res['verdict'] == 'NOT_EXECUTED'
    assert 'NO_GATE_BINDING: NO_DECLARED_CHIP_TOP' in json.dumps(
        json.loads((sim / 'results.json').read_text())['cases'])


def test_the_direct_arm_takes_the_pads_models_from_the_declared_io_library(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    cells = 'module cells__dffq_1 (D, CLK, Q); input D, CLK; output Q;\n  buf (Q, D);\nendmodule\n'
    pads = {'/pdk/x/libs.ref/pads/verilog/pads__blackbox.v':
            'module cells__in_c (PAD, Y); input PAD; output Y;\nendmodule\n',
            '/pdk/x/libs.ref/pads/verilog/pads.v':
            'module cells__in_c (PAD, Y); input PAD; output Y;\n  buf (Y, PAD);\nendmodule\n'
            'module cells__bi_24t (A, OE, PAD); input A, OE; inout PAD;\n'
            '  bufif1 (PAD, A, OE);\nendmodule\n'}

    def fake(container, cmd, budget_s=600):
        if cmd.startswith('ls -1 /pdk/x/libs.ref/pads/verilog'):
            return SimpleNamespace(stdout='[INFO] banner\npads__blackbox.v\npads.v\n', returncode=0)
        path = cmd.split(' ', 1)[1]
        return SimpleNamespace(stdout=pads[path], returncode=0)
    monkeypatch.setattr(sgs, '_docker', fake)
    models = sgs.CellModels(['/c/cells.v'], cells, 'container_pdk', files={'/c/cells.v': cells})
    got = sgs.declared_io_models(project, 'c', sgs.netlist_used_cells(ROUTED), models)
    assert got.paths == ['/c/cells.v', '/pdk/x/libs.ref/pads/verilog/pads.v']
    assert 'bufif1' in got.files['/pdk/x/libs.ref/pads/verilog/pads.v']


# ------------------------------------------ the container read ---

def test_a_model_read_from_the_container_is_the_file_not_the_entrypoint_banner(monkeypatch):
    """MEASURED on 0.3.79: two `[INFO] Final PATH variable` lines precede the
    `cat`, and every model line number read this way was off by two."""
    body = 'module a (); endmodule\n'
    monkeypatch.setattr(sgs, '_docker', lambda c, cmd, budget_s=0: SimpleNamespace(
        stdout='[INFO] Final PATH variable: /x\n[INFO] Final PATH variable: /y\n' + body,
        returncode=0))
    assert sgs._read_container_files('c', ['/m.v']) == body


# ------------------------------------------ issue #1410: no fixed window ---

#: SDF allows `//` comments; a writer's banner can push the header statements
#: past any fixed prefix. They are still the file's statements.
_LONG_BANNER = ''.join(f'// banner line {i:04d} ' + 'x' * 40 + '\n' for i in range(120))


def test_a_timescale_past_the_first_4096_bytes_is_still_the_sdfs_unit(tmp_path):
    sdc = write(tmp_path / 'c.sdc', 'create_clock -period 24 [get_ports clk]\n')
    sdf = '(DELAYFILE\n' + _LONG_BANNER + ' (TIMESCALE 1ps)\n)\n'
    assert sdf.index('TIMESCALE') > 4096
    clocks = sgs.declared_sdc_clocks(sdc, [sdf])
    assert clocks['clocks_s'] == {'clk': pytest.approx(24e-12)}


def test_a_divider_past_the_first_4096_bytes_is_still_the_sdfs_divider():
    bundle = _cal('negative')
    sdf = bundle['sdf_text']
    head, rest = sdf.split('\n', 1)
    # the same SDF, `/` divider stated after a long banner; line numbers kept
    # by folding the banner into the first line's trailing comment block
    moved = (head + ' ' + _LONG_BANNER.replace('\n', ' ') + '\n'
             + rest.replace('(DIVIDER .)', '(DIVIDER /)').replace('u_pad.PAD', 'u_pad/PAD'))
    assert moved.index('DIVIDER') > 4096
    got = _classify(bundle, sdf_text=moved)
    assert got['by_class'].get('INOUT_PORT_INTERCONNECT') == 1, got


@pytest.mark.parametrize('prefix,half,period_ns,expected', [
    ('initial clk=0;', '12', 24, '12'),
    ('initial clk=0;', '5', 12, '6'),
    ('initial clk=0; /* preserve offsets */', '(5)', 24, '12')])
def test_clock_binding_uses_statement_boundaries_with_the_same_sdc_policy(
        tmp_path, prefix, half, period_ns, expected):
    original = TB.replace('  always #5 clk = ~clk;',
                          f'  {prefix} always #{half} clk = ~clk;')
    bound = original.replace('core dut (.clk_i(clk), .x_i(x), .p_o(p))',
                            'chip_top dut (.clk(clk), .x(x), .p(p))')
    sdc = write(tmp_path / 'clock.sdc',
                f'create_clock -period {period_ns} [get_ports clk]\n')
    clocks = sgs.declared_sdc_clocks(sdc, [SDF_HEAD])
    text, info = sgs.bind_bench_clock(bound, 'dut', clocks)
    assert text == bound.replace(f'#{half} clk', f'#{expected} clk')
    assert info['clocks'][0]['bench_default'] == half.strip('()')
    assert info['clocks'][0]['period_s'] == pytest.approx(period_ns * 1e-9)
    assert prefix in text


@pytest.mark.parametrize('generator,clocks,code', [
    ('initial clk=0; always #12 clk = ~clk;', {'clk': 24.0005e-9}, 'BENCH_PRECISION'),
    ('initial clk=0; always #12 clk = ~clk;', {'x': 24e-9}, 'BENCH_CLOCK_UNDECLARED'),
    ('initial clk=0; /* always #12 clk = ~clk; */', {'clk': 24e-9}, 'BENCH_CLOCK_NOT_BOUND'),
    ('initial $display("; always #12 clk = ~clk;");', {'clk': 24e-9}, 'BENCH_CLOCK_NOT_BOUND')])
def test_statement_clock_binding_keeps_unmeasured_or_unrepresentable_clocks_refused(
        generator, clocks, code):
    text = TB.replace('  always #5 clk = ~clk;', '  ' + generator)
    text = text.replace('core dut (.clk_i(clk), .x_i(x), .p_o(p))',
                        'chip_top dut (.clk(clk), .x(x), .p(p))')
    with pytest.raises(ValueError, match=code):
        sgs.bind_bench_clock(text, 'dut', {
            'sdc': 'source-control.sdc', 'unit_source': 'declared SDC', 'clocks_s': clocks})


def test_fragmented_sdf_error_remains_unexplained_and_blocks_the_tool_arm(tmp_path):
    folder = tmp_path / 'native'
    folder.mkdir()
    stdout = write(folder / 'stdout.log',
        'SDF INFO: x.sdf:1: Putting delay on a native path\n'
        'SDF ERROR: /run/openroad-VPI error: interleaved native stderr\n'
        '[TB functional] PASS\n')
    compile_log = write(folder / 'compile.log', '')
    put(folder / 'gls_runs.json', {'runs': [{'corner': 'tt', 'case': 'functional',
        'sdf': str(write(folder / 'x.sdf', SDF_HEAD)), 'compile_rc': 0, 'sim_rc': 0,
        'compile_log': str(compile_log), 'stdout': str(stdout)}]})
    result = sgs.judge_tool_arm(folder, {'cases': [{'id': 'functional'}]})
    assert result['corners']['tt']['sdf_errors'] == 1
    assert result['corners']['tt']['sdf_errors_unexplained'] == 1
    assert result['verdict'] == 'FAIL'


def test_fragmented_and_well_formed_sdf_errors_are_each_counted_once():
    text = ('SDF ERROR: truncated native header\n'
            'SDF ERROR: x.sdf:3: unrecognized native record\n')
    result = sgs.classify_sdf_errors(text, compile_log='', sdf_text=SDF_HEAD,
                                    explainer=sgs.SdfErrorExplainer('', {}))
    assert result['total'] == sgs.sdf_error_count(text) == 2
    assert result['unparsed'] == 1
    assert result['unexplained'] == 2


def test_native_gls_collector_preserves_complete_stdout_and_stderr_lines(tmp_path):
    from librelane_plugin_vibeic import GateLevelSim
    log = tmp_path / 'native.log'
    program = ('import sys;sys.stdout.write("SDF ERROR: x.sdf");sys.stdout.flush();'
               'sys.stderr.write("native VPI stderr\\n");sys.stderr.flush();'
               'sys.stdout.write(":3: complete error\\n");sys.stdout.flush()')
    rc = GateLevelSim._run([sys.executable, '-c', program], str(log), 30)
    assert rc == 0
    assert log.read_text().splitlines() == [
        'SDF ERROR: x.sdf:3: complete error', '', 'native VPI stderr']
    assert (tmp_path / 'native.log.stderr').read_text() == 'native VPI stderr\n'

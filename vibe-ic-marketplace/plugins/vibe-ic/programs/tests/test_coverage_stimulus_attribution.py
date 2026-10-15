#!/usr/bin/env python3
"""Coverage must be attributed to a testbench with functional stimulus.

These generic fixtures reproduce the observed failure shapes without embedding
a design, PDK or vendor identity.  A checked-in activity testbench supplies the
real-artefact reverse control.
"""
import sys
import os
import json
import subprocess
import importlib.util
import pytest
from pathlib import Path

PROGRAMS = Path(os.environ.get("VIBEIC_COVERAGE_SUBJECT", Path(__file__).resolve().parents[1]))
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

SPEC = importlib.util.spec_from_file_location("coverage_stimulus_subject", PROGRAMS / "verilator_coverage_measure.py")
V = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V
SPEC.loader.exec_module(V)
from _hostpaths import require_repo  # noqa: E402

_INERT_TB = """\
// A connectivity-only harness.
module tb_top_full;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [31:0] wdata_i = 32'h0;
  wire [31:0] rdata_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .wdata_i(wdata_i),
             .rdata_o(rdata_o));
  initial begin rst_ni <= 1'b1; #100 $finish; end
endmodule
"""

_DRIVING_TB = """\
module tb_vec;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  bus_pkg::req_t bus_raw;
  bus_pkg::req_t bus_i;
  intg_gen u_intg (.bus_i(bus_raw), .bus_o(bus_i));
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .bus_i(bus_i));
  initial begin
    rst_ni <= 1'b1;
    bus_raw.valid <= 1'b1;
    bus_raw.addr  <= 32'h10;
    #100 $finish;
  end
endmodule
"""

_OUTPUT_TO_MONITOR_TB = """\
module tb_monitor;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [7:0] cmd_i = 8'h00;
  wire [7:0] status_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .cmd_i(cmd_i),
             .status_o(status_o));
  monitor u_monitor (.sample_i(status_o));
  initial begin rst_ni <= 1'b1; #100 $finish; end
endmodule
"""


def test_a_direction_suffixed_clock_and_reset_are_infrastructure():
    for name in ("clk_i", "rst_ni", "clk", "rst_n", "sclk_i"):
        assert V._cov_is_clock_or_reset(name), name
    for name in ("wdata_i", "data_o", "addr_i", "bus_i",
                 "clk_enable_i", "reset_value_i"):
        assert not V._cov_is_clock_or_reset(name), name


def test_a_connectivity_only_testbench_drives_nothing(tmp_path):
    tb = tmp_path / "tb_top_full.v"
    tb.write_text(_INERT_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert a["driven"] == [], a
    assert set(a["clock_reset"]) >= {"clk_i", "rst_ni"}
    assert "wdata_i" in a["inert"]


def test_a_struct_field_assignment_is_functional_stimulus(tmp_path):
    tb = tmp_path / "tb_vec.v"
    tb.write_text(_DRIVING_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    # Only an observed assignment produces the vocabulary. Merely sharing a
    # signal between instances does not establish which instance drives it.
    assert "bus_raw" in a["driven"], a
    assert "bus_i" not in a["driven"], a


def test_a_dut_output_shared_with_a_monitor_is_not_invented_as_stimulus(
        tmp_path):
    tb = tmp_path / "tb_monitor.v"
    tb.write_text(_OUTPUT_TO_MONITOR_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert a["driven"] == [], a
    assert "cmd_i" in a["inert"], a
    assert "status_o" not in a["driven"], a


def test_discovery_prefers_the_testbench_that_drives(tmp_path):
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    (tmp_path / "phase2/stage1/rtl/dut.sv").write_text(
        "module dut(input clk_i); endmodule\n")
    fs = tmp_path / "phase2/stage1/sim_full_stack"
    fs.mkdir(parents=True)
    (fs / "tb_top_full.v").write_text(_INERT_TB)
    unit = tmp_path / "phase2/stage1/sim/tb"
    unit.mkdir(parents=True)
    (unit / "tb_vec.v").write_text(_DRIVING_TB)
    _rtl, tb = V.discover_measure_inputs(tmp_path)
    assert tb and Path(tb).name == "tb_vec.v", tb


def test_discovery_keeps_the_old_first_hit_when_nothing_drives(tmp_path):
    fs = tmp_path / "phase2/stage1/sim_full_stack"
    fs.mkdir(parents=True)
    (fs / "tb_top_full.v").write_text(_INERT_TB)
    _rtl, tb = V.discover_measure_inputs(tmp_path)
    assert tb and Path(tb).name == "tb_top_full.v"


def test_a_helper_module_is_resolved_from_the_design_input_only(tmp_path):
    (tmp_path / "input/vendor_rtl").mkdir(parents=True)
    (tmp_path / "input/vendor_rtl/intg_gen.sv").write_text(
        "module intg_gen(input a); endmodule\n")
    (tmp_path / "input/golden").mkdir(parents=True)
    (tmp_path / "input/golden/dut.sv").write_text(
        "module dut(input a); endmodule\n")
    tb = tmp_path / "tb_vec.v"
    tb.write_text(_DRIVING_TB)
    got = V._cov_sources_for_tb(tmp_path, tb, [])
    assert [Path(g).name for g in got] == ["intg_gen.sv"], got


def test_checked_in_activity_testbench_remains_functional():
    tb = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "ppa", "power", "activity_basis_pair", "tb.v")
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert set(a["clock_reset"]) == {"clk", "rst"}, a
    assert set(a["driven"]) == {"x", "y"}, a


@pytest.mark.parametrize("variation,expected", [
    ("native", {"cmd_i": 7}), ("denied", {}), ("prose", {}),
    ("zero", {}), ("negative", {}), ("foreign_page", {}),
    ("foreign_hierarchy", {}),
])
def test_professional_activity_requires_native_record_grammar(
        tmp_path, variation, expected):
    fields = "\x01page\x02v_toggle/dut\x01h\x02TOP.dut\x01o\x02cmd_i[0]"
    raw = f"C '{fields}' 7"
    if variation == "denied":
        raw = "not " + raw
    elif variation == "prose":
        raw = "The cmd_i input does not toggle; observed transitions: 7."
    elif variation == "zero":
        raw = raw[:-1] + "0"
    elif variation == "negative":
        raw = raw[:-1] + "-7"
    elif variation == "foreign_page":
        raw = raw.replace("v_toggle/dut", "v_toggle/other")
    elif variation == "foreign_hierarchy":
        raw = raw.replace("TOP.dut", "TOP.other")
    dat = tmp_path / "coverage.dat"
    dat.write_text(raw + "\n")
    assert V._professional_input_activity(dat, "dut", ["cmd_i"]) == expected


def test_check_refuses_to_grade_a_connectivity_only_measurement(tmp_path,
                                                                capsys):
    import argparse
    import json
    tb = tmp_path / "tb_top_full.v"
    tb.write_text(_INERT_TB)
    cov = tmp_path / "coverage_verilator.json"
    cov.write_text(json.dumps({
        "tool": "verilator", "measurement_mode": "measure-tb",
        "testbench": str(tb), "rtl_sources": [], "scope_files": [],
        "per_file": {}, "format_detected": "v5",
        "totals": {"line": {"covered": 340, "total": 547, "pct": 62.16},
                   "toggle": {"covered": 10835, "total": 64382, "pct": 16.83},
                   "branch": {"covered": 325, "total": 940, "pct": 34.57}}}))
    args = argparse.Namespace(coverage_json=str(cov), min_line=70.0,
                              min_toggle=60.0, min_branch=70.0,
                              verilator_bin="verilator")
    rc = V.cmd_check(args)
    out = capsys.readouterr().out
    assert rc == 1
    assert "NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD" in out
    assert "62.16" in out and "NOT graded here" in out


_COCOTB_SCOREBOARD = '''import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def reference_model(dut):
    for value in (0, 1, 0, 1):
        dut.ck4.value = 0
        dut.sample.value = value
        await Timer(5, unit='ns')
        dut.ck4.value = 1
        await Timer(5, unit='ns')
        assert int(dut.result.value) == value
    dut._log.info('PROFESSIONAL_TB PASS scalar scoreboard')
'''


def _professional_project(root):
    import professional_tb_gen as gen
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'converter', 'top_ports': [
            {'name': 'sample', 'dir': 'input', 'width': 1},
            {'name': 'result', 'dir': 'output', 'width': 1},
            {'name': 'ck4', 'dir': 'input', 'width': 1}],
        'clock_domains': [{'name': 'ck4', 'source_pin': 'ck4'}]}))
    (docs / 'L8_TIMING_WAVEFORM.json').write_text(json.dumps({
        'clocks': [{'name': 'ck4', 'source_pin': 'ck4', 'period_ns': 10}]}))
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'converter.v').write_text(
        'module converter(input sample, input ck4, output reg result);\n'
        'always @(posedge ck4) begin\n'
        "if (sample) result <= 1'b1; else result <= 1'b0;\n"
        'end\nendmodule\n')
    bundle = root / 'phase2/stage1/sim_professional/converter'
    bundle.mkdir(parents=True)
    (bundle / 'expert_reference_tb.py').write_text(_COCOTB_SCOREBOARD)
    gen.generate(root)
    inert = root / 'phase2/stage1/sim_full_stack'
    inert.mkdir(parents=True)
    (inert / 'tb_converter_full.v').write_text(_INERT_TB)
    return root, bundle


def test_discovery_instruments_the_professional_scoreboard_before_an_inert_harness(tmp_path):
    project, bundle = _professional_project(tmp_path)
    sources, tbs = V.discover_measure_testbenches(project)
    # VALUE control: pre-fix returns the .v connectivity harness; there are
    # real sources and a real selection on both sides, never an absence test.
    assert [Path(p).name for p in tbs] == ['tb_converter.py'], tbs
    assert [Path(p).name for p in sources] == ['converter.v']
    audit = V.functional_stimulus_audit(bundle / 'tb_converter.py')
    assert audit['decidable'] and audit['driven'] == ['sample'], audit
    assert audit['clock_reset'] == ['ck4'], audit


def test_python_only_initialization_is_still_inert(tmp_path):
    import professional_tb_gen as gen
    project, bundle = _professional_project(tmp_path)
    source = _COCOTB_SCOREBOARD.replace('dut.sample.value = value', 'dut.sample.value = 0')
    (bundle / 'expert_reference_tb.py').write_text(source)
    gen.generate(project)
    audit = V.functional_stimulus_audit(bundle / 'tb_converter.py')
    assert audit['decidable'] and audit['driven'] == [], audit
    assert audit['inert'] == ['sample'], audit


def test_missing_professional_plan_does_not_fall_back_to_connectivity(tmp_path):
    import pytest
    project, bundle = _professional_project(tmp_path)
    (bundle / 'verification_plan.json').unlink()
    sources, tbs = V.discover_measure_testbenches(project)
    with pytest.raises(SystemExit, match='PROFESSIONAL_COVERAGE_PLAN_INVALID'):
        V.measure_suite(sources, tbs, str(project / 'coverage'), build_jobs=1)


@pytest.mark.parametrize('plan_state', ['missing', 'unfilled'])
def test_an_incomplete_professional_hook_does_not_displace_functional_verilog(tmp_path, plan_state):
    project, bundle = _professional_project(tmp_path)
    plan = bundle / 'verification_plan.json'
    if plan_state == 'missing':
        plan.unlink()
    else:
        plan.write_text(json.dumps({'top': 'converter', 'dut_kind': 'generic',
                                    'reference_model_tier': 'hook_unfilled'}))
    functional = project / 'phase2/stage1/sim_full_stack/tb_converter_full.v'
    functional.write_text(_DRIVING_TB)
    _sources, selected = V.discover_measure_testbenches(project)
    assert selected == [str(functional)], selected


def test_zero_and_skipped_instrumented_junit_cannot_reuse_prior_icarus_pass(tmp_path):
    import pytest
    project, bundle = _professional_project(tmp_path)
    (bundle / 'results.xml').write_text('<testsuite tests="1" failures="0" errors="0"/>')
    for label, xml in [
        ('zero', '<testsuite tests="0"/>'),
        ('skipped', '<testsuite tests="1" skipped="1"/>'),
        ('failed', '<testsuite tests="1" failures="1"/>'),
    ]:
        build = project / label
        build.mkdir()
        (build / 'coverage.dat').write_text('stale')
        (build / 'coverage_results.xml').write_text('<testsuite tests="1"/>')
        def simulate(argv, cwd):
            cwd = Path(cwd)
            assert not (cwd / 'coverage.dat').exists()
            assert not (cwd / 'coverage_results.xml').exists()
            (cwd / 'coverage_results.xml').write_text(xml)
            (cwd / 'coverage.dat').write_text('fresh data from shutdown')
            return 0, '', ''
        sources, tbs = V.discover_measure_testbenches(project)
        with pytest.raises(SystemExit, match='PROFESSIONAL_COVERAGE_SIMULATION_REFUSED'):
            V.measure_suite(sources, tbs, str(build), exec_fn=simulate, build_jobs=1)
        assert (build / 'coverage.dat').read_text() == 'stale'
        assert (build / 'coverage_results.xml').read_text() == '<testsuite tests="1"/>'
        attempts = list(build.glob('attempt_*'))
        assert len(attempts) == 1
        record = json.loads((attempts[0] / 'coverage_cocotb_execution.json').read_text())
        assert record['measurement_status'] == 'NOT_MEASURED'
        assert Path(record['coverage_dat']).read_text() == 'fresh data from shutdown'


def test_real_cocotb_coverage_uses_this_runs_passing_junit_and_raw_points(tmp_path):
    import shutil
    import pytest
    if shutil.which('verilator') is None or shutil.which('cocotb-config') is None:
        pytest.skip('native Verilator/cocotb toolchain required')
    project, bundle = _professional_project(tmp_path)
    # Only the real cocotb bundle is part of this measurement. The preceding
    # selector test pins that an inert harness cannot replace it.
    (project / 'phase2/stage1/sim_full_stack/tb_converter_full.v').unlink()
    out = project / 'coverage.json'
    proc = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'measure-tb',
        '--project', str(project), '--out', str(out), '--build-jobs', '1'],
        text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    dat = payload['coverage_dat']
    raw = V.scope_totals(V.parse_coverage_dat(dat), payload['rtl_sources'])
    assert raw['totals'] == payload['totals']
    assert payload['line_union_cross_check']['agree'] is True
    assert payload['scope_files'] == payload['rtl_sources']
    record = json.loads((Path(dat).parent / 'coverage_cocotb_execution.json').read_text())
    assert record['test_denominator']['tests'] == record['test_denominator']['passed'] == 1
    assert record['test_denominator']['skipped'] == 0
    checked = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'check',
        '--coverage-json', str(out)], text=True, capture_output=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    # A subsequently changed Python source cannot borrow this run's JUnit/dat.
    (bundle / 'tb_converter.py').write_text(_COCOTB_SCOREBOARD + '\n# changed source\n')
    changed = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'check',
        '--coverage-json', str(out)], text=True, capture_output=True)
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert 'PROFESSIONAL_COVERAGE_EVIDENCE_REFUSED' in changed.stdout
    # A real successful native run survives a later native failed rerun.
    import professional_tb_gen as gen
    before_report = out.read_bytes()
    before_dat = Path(dat).read_bytes()
    before_junit = Path(record['instrumented_junit']).read_bytes()
    (bundle / 'expert_reference_tb.py').write_text(
        _COCOTB_SCOREBOARD.replace('== value', '== (value ^ 1)'))
    gen.generate(project)
    failed = subprocess.run(proc.args, text=True, capture_output=True)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    current = json.loads(out.read_text())
    assert current['measurement_status'] == 'NOT_MEASURED'
    assert 'PROFESSIONAL_COVERAGE_SIMULATION_REFUSED' in current['reason']
    assert Path(current['previous_report']).read_bytes() == before_report
    assert Path(dat).read_bytes() == before_dat
    assert Path(record['instrumented_junit']).read_bytes() == before_junit
    refused = subprocess.run(checked.args, text=True, capture_output=True)
    assert refused.returncode == 1, refused.stdout + refused.stderr


@pytest.mark.parametrize('control', ['failure', 'skip', 'zero', 'inert'])
def test_native_professional_rerun_refuses_failed_skipped_and_zero_test_controls(tmp_path, control):
    import shutil
    import professional_tb_gen as gen
    if shutil.which('verilator') is None or shutil.which('cocotb-config') is None:
        pytest.skip('native Verilator/cocotb toolchain required')
    project, bundle = _professional_project(tmp_path)
    (project / 'phase2/stage1/sim_full_stack/tb_converter_full.v').unlink()
    source = _COCOTB_SCOREBOARD
    if control == 'failure':
        source = source.replace('== value', '== (value ^ 1)')
    if control == 'skip':
        source = source.replace('@cocotb.test()', '@cocotb.test(skip=True)')
    if control == 'inert':
        source = source.replace('(0, 1, 0, 1)', '(0, 0, 0, 0)')
    (bundle / 'expert_reference_tb.py').write_text(source)
    gen.generate(project)
    out = project / 'coverage.json'
    out.write_text('previous passing measurement must not survive')
    env = dict(os.environ)
    if control == 'zero':
        env['COCOTB_TEST_FILTER'] = '^no_matching_test$'
    measured = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'measure-tb',
        '--project', str(project), '--out', str(out), '--build-jobs', '1'],
        text=True, capture_output=True, env=env)
    assert measured.returncode == 1, measured.stdout + measured.stderr
    refusal = ('PROFESSIONAL_COVERAGE_INPUT_ACTIVITY_UNOBSERVED'
               if control == 'inert' else 'PROFESSIONAL_COVERAGE_SIMULATION_REFUSED')
    assert refusal in measured.stderr
    current = json.loads(out.read_text())
    assert current['measurement_status'] == 'NOT_MEASURED'
    assert Path(current['previous_report']).read_text() == 'previous passing measurement must not survive'
    checked = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'check',
        '--coverage-json', str(out)], text=True, capture_output=True)
    assert checked.returncode == 1, checked.stdout + checked.stderr
    (project / 'native_control_receipt.json').write_text(json.dumps({
        'control': control, 'producer_command': measured.args,
        'producer_rc': measured.returncode,
        'producer_stdout': measured.stdout, 'producer_stderr': measured.stderr,
        'consumer_command': checked.args, 'consumer_rc': checked.returncode,
        'consumer_stdout': checked.stdout, 'consumer_stderr': checked.stderr,
    }, indent=2) + '\n')


def _selection_project(root, state):
    """Authored SOURCE_CONTROL inputs, using the real professional generator.

    The unit adapter's prior JUnit is discovery input only, never measurement
    evidence. Its role is independent of the generator's Python bundle.
    """
    import professional_tb_gen as gen
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'sensor_core', 'top_ports': [
            {'name': 'sample', 'dir': 'input', 'width': 1},
            {'name': 'result', 'dir': 'output', 'width': 1},
            {'name': 'ck4', 'dir': 'input', 'width': 1}],
        'clock_domains': [{'name': 'ck4', 'source_pin': 'ck4'}]}))
    (docs / 'L8_TIMING_WAVEFORM.json').write_text(json.dumps({
        'clocks': [{'name': 'ck4', 'source_pin': 'ck4', 'period_ns': 10}]}))
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'sensor_core.v').write_text(
        'module sensor_core(input sample, input ck4, output reg result);\n'
        'always @(posedge ck4) begin\n'
        "if (sample) result <= 1'b1; else result <= 1'b0;\n"
        'end\nendmodule\n')
    bundle = root / 'phase2/stage1/sim_professional/sensor_core'
    bundle.mkdir(parents=True)
    if state != 'unfilled':
        (bundle / 'expert_reference_tb.py').write_text(_COCOTB_SCOREBOARD)
    generated = gen.generate(root)
    assert generated['status'] == 'PASS'  # Generation, not native execution.
    if state == 'missing':
        (bundle / 'verification_plan.json').unlink()
    elif state == 'invalid':
        (bundle / 'verification_plan.json').write_text('{invalid JSON')
    elif state == 'declared_missing':
        report = root / 'reports/phase2/gates/professional_tb.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps(generated))
        for name in generated['files']:
            (bundle / name).unlink()
        (bundle / 'expert_reference_tb.py').unlink()
    for name in ('l10_unit_tb', 'support_cache'):
        work = bundle.parent / name
        work.mkdir()
        (work / 'Makefile').write_text('# Unit/helper execution workdir\n')
        (work / 'results.xml').write_text('<testsuite tests="1" failures="0" errors="0"/>')
    return root, bundle


@pytest.mark.parametrize('state,refusal', [
    ('unfilled', 'PROFESSIONAL_COVERAGE_PLAN_INCOMPLETE'),
    ('missing', 'PROFESSIONAL_COVERAGE_PLAN_INVALID'),
    ('invalid', 'PROFESSIONAL_COVERAGE_PLAN_INVALID'),
    ('declared_missing', 'PROFESSIONAL_COVERAGE_PLAN_INVALID'),
    ('filled', None),
])
def test_only_generator_bundles_reach_the_strict_coverage_consumer(tmp_path, state, refusal):
    """Public directory shape -> actual selector -> instrumenter -> checker."""
    import hashlib
    project, bundle = _selection_project(tmp_path, state)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for name in ('l10_unit_tb', 'support_cache')
              for p in (bundle.parent / name).iterdir()}
    input_hashes = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(project.rglob('*')) if p.is_file()}
    candidates = V._professional_measure_testbenches(project)
    sources, selected = V.discover_measure_testbenches(project)
    out = project / 'coverage.json'
    measured = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'measure-tb',
        '--project', str(project), '--out', str(out), '--build-jobs', '1'],
        text=True, capture_output=True)
    checked = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'), 'check',
        '--coverage-json', str(out)], text=True, capture_output=True)
    payload = json.loads(out.read_text())
    receipt = {'state': state, 'input_role': 'SOURCE_CONTROL',
               'input_hashes': input_hashes,
               'candidates': candidates, 'selected': selected, 'sources': sources,
               'producer_rc': measured.returncode, 'producer_stdout': measured.stdout,
               'producer_stderr': measured.stderr, 'consumer_rc': checked.returncode,
               'consumer_stdout': checked.stdout, 'consumer_stderr': checked.stderr,
               'payload': payload}
    (project / 'selection_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    tb = str(bundle / 'tb_sensor_core.py')
    assert candidates == selected == [tb], receipt
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ('l10_unit_tb', 'support_cache')
            for p in (bundle.parent / name).iterdir()} == before
    if refusal:
        assert measured.returncode == checked.returncode == 1, receipt
        assert payload['measurement_status'] == 'NOT_MEASURED', receipt
        assert refusal in payload['reason'], receipt
        assert 'l10_unit_tb' not in payload['reason'], receipt
        assert not list(project.glob('**/coverage_cocotb_execution.json'))
    else:
        assert measured.returncode == checked.returncode == 0, receipt
        dat = Path(payload['coverage_dat'])
        execution = json.loads((dat.parent / 'coverage_cocotb_execution.json').read_text())
        assert execution['measurement_status'] == 'MEASURED', execution
        assert execution['test_denominator']['tests'] == execution['test_denominator']['passed'] == 1
        assert execution['test_denominator']['skipped'] == 0
        assert execution['observed_functional_input_toggles']['sample'] > 0
        assert payload['line_union_cross_check']['agree'] is True
        assert V.scope_totals(V.parse_coverage_dat(str(dat)), sources)['totals'] == payload['totals']


def _public_selector_project(root, top):
    """Real producer CLI, source/admission evidence only; never run the TB."""
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': top, 'top_ports': [
            {'name': 'sample', 'dir': 'input', 'width': 1},
            {'name': 'result', 'dir': 'output', 'width': 1},
            {'name': 'ck4', 'dir': 'input', 'width': 1}]}))
    (docs / 'L8_TIMING_WAVEFORM.json').write_text(json.dumps({
        'clocks': [{'name': 'ck4', 'source_pin': 'ck4', 'period_ns': 10}]}))
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    # A legitimate top may end in _tb; its RTL filename is not a testbench.
    (rtl / 'native_logic.v').write_text(
        f'module {top}(input sample, input ck4, output reg result);\n'
        'always @(posedge ck4) result <= sample;\nendmodule\n')
    bundle = root / 'phase2/stage1/sim_professional' / top
    bundle.mkdir(parents=True)
    (bundle / 'expert_reference_tb.py').write_text(_COCOTB_SCOREBOARD)
    report = root / 'reports/phase2/gates/professional_tb.json'
    report.parent.mkdir(parents=True)
    produced = subprocess.run([
        sys.executable, str(PROGRAMS / 'professional_tb_gen.py'), str(root),
        '--json', str(report)], capture_output=True, text=True)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    declaration = json.loads(report.read_text())
    assert declaration['reference_model_tier'] == 'expert_filled', declaration
    return bundle, report


@pytest.mark.parametrize('control', [
    'foreign_absolute', 'foreign_parent_relative', 'foreign_wrong_slot',
    'broken_professional_artifact',
])
def test_selector_declaration_cannot_borrow_a_foreign_basename(tmp_path, control):
    """Predeclared independent failures: exact source scope and broken link."""
    from testbench_gen import UNIT_TB_RESULT_DIR
    bundle, report = _public_selector_project(tmp_path, UNIT_TB_RESULT_DIR)
    original = json.loads(report.read_text())
    for path in bundle.iterdir():
        path.unlink()
    (bundle / 'results.xml').write_text('<testsuite tests="1"/>')
    expected = []
    if control == 'broken_professional_artifact':
        report.rename(report.with_name('professional_tb.retained.json'))
        tb = bundle / f'tb_{UNIT_TB_RESULT_DIR}.py'
        tb.symlink_to('missing-native-tb.py')
        expected = [str(tb)]
    else:
        foreign = tmp_path.parent / 'foreign-project' / control / UNIT_TB_RESULT_DIR
        foreign.mkdir(parents=True)
        raw = str(foreign)
        if control == 'foreign_parent_relative':
            raw = os.path.relpath(foreign, tmp_path)
        elif control == 'foreign_wrong_slot':
            foreign = tmp_path / 'different-subtree' / UNIT_TB_RESULT_DIR
            foreign.mkdir(parents=True)
            raw = str(foreign)
        report.write_text(json.dumps({**original, 'out_dir': raw}))
    observed = {
        'professional': V._professional_measure_testbenches(tmp_path),
        'single': V.discover_measure_inputs(tmp_path)[1],
        'suite': V.discover_measure_testbenches(tmp_path)[1],
    }
    expected_selection = {'professional': expected,
                          'single': expected[0] if expected else None,
                          'suite': expected}
    selection_matches = observed == expected_selection
    assert selection_matches is True, observed
    # A real refused invocation must stop before any simulator or coverage.dat.
    out = tmp_path / 'refused-coverage.json'
    consumed = subprocess.run([
        sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'),
        'measure-tb', '--project', str(tmp_path), '--out', str(out)],
        text=True, capture_output=True)
    assert consumed.returncode == 1, consumed.stdout + consumed.stderr
    if expected:
        payload = json.loads(out.read_text())
        assert payload['measurement_status'] == 'NOT_MEASURED', payload
        assert 'PROFESSIONAL_COVERAGE_PLAN_INVALID' in payload['reason'], payload
    else:
        assert 'no testbench found to instrument' in consumed.stderr
        assert out.exists() is False
    assert list(tmp_path.glob('**/coverage.dat')) == []
    assert list(tmp_path.glob('**/coverage_cocotb_execution.json')) == []


def test_public_professional_producer_keeps_healthy_bundle_admission(tmp_path):
    bundle, report = _public_selector_project(tmp_path, 'selector_scope')
    helper = bundle.parent / 'execution_helper'
    helper.mkdir()
    (helper / 'Makefile').write_text('# Execution-only helper\n')
    (helper / 'results.xml').write_text('<testsuite tests="1"/>')
    tb = bundle / 'tb_selector_scope.py'
    assert V._professional_measure_testbenches(tmp_path) == [str(tb)]
    assert V.discover_measure_inputs(tmp_path)[1] == str(tb)
    assert V.discover_measure_testbenches(tmp_path)[1] == [str(tb)]
    assert V._professional_bundle(tb)['reference_model_tier'] == 'expert_filled'
    assert json.loads(report.read_text())['out_dir'] == str(bundle)
    assert list(tmp_path.glob('**/coverage.dat')) == []


@pytest.mark.parametrize('state', ['declared_missing', 'filled'])
def test_copied_canonical_declaration_keeps_its_bundle_population(tmp_path, state):
    """Actual producer -> copied INPUT -> selector/admission, without simulation.

    A former absolute canonical slot still declares a damaged bundle. The
    refusal must name that plan rather than silently losing its population.
    """
    import hashlib
    import shutil
    import professional_tb_gen as gen
    seed, _bundle = _selection_project(tmp_path / 'original', state)
    report = seed / 'reports/phase2/gates/professional_tb.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    declaration = json.loads(report.read_text()) if report.exists() else gen.generate(seed)
    declaration['out_dir'] = (
        '/previous_location/neutral_project/phase2/stage1/sim_professional/sensor_core')
    report.write_text(json.dumps(declaration))
    seal = {str(p.relative_to(seed)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(seed.rglob('*')) if p.is_file()}
    project = tmp_path / 'current'
    shutil.copytree(seed, project)
    assert {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(project.rglob('*')) if p.is_file()} == seal
    tb = project / 'phase2/stage1/sim_professional/sensor_core/tb_sensor_core.py'
    observed = {
        'state': state, 'input_role': 'SOURCE_CONTROL', 'input_seal': seal,
        'selectors': {'professional': V._professional_measure_testbenches(project),
                      'single': V.discover_measure_inputs(project)[1],
                      'suite': V.discover_measure_testbenches(project)[1]},
    }
    if state == 'declared_missing':
        out = tmp_path / 'copied-coverage.json'
        measured = subprocess.run([
            sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'),
            'measure-tb', '--project', str(project), '--out', str(out)],
            text=True, capture_output=True)
        checked = subprocess.run([
            sys.executable, str(PROGRAMS / 'verilator_coverage_measure.py'),
            'check', '--coverage-json', str(out)], text=True, capture_output=True)
        observed['CLI'] = {
            'producer_rc': measured.returncode, 'producer_stdout': measured.stdout,
            'producer_stderr': measured.stderr, 'consumer_rc': checked.returncode,
            'consumer_stdout': checked.stdout, 'consumer_stderr': checked.stderr,
            'report_present': out.exists(),
            'report': json.loads(out.read_text()) if out.exists() else None,
        }
    else:
        observed['admission'] = V._professional_bundle(tb)['reference_model_tier']
    observed['native_artifacts'] = [str(p.relative_to(project))
                                  for pattern in ('**/coverage.dat',
                                                  '**/coverage_cocotb_execution.json')
                                  for p in project.glob(pattern)]
    (tmp_path / 'copied_selection_observed.json').write_text(
        json.dumps(observed, indent=2) + '\n')
    assert observed['selectors'] == {
        'professional': [str(tb)], 'single': str(tb), 'suite': [str(tb)]}, observed
    assert observed['native_artifacts'] == [], observed
    if state == 'declared_missing':
        actual = observed['CLI']
        assert actual['producer_rc'] == actual['consumer_rc'] == 1, observed
        assert actual['report_present'] is True, observed
        assert actual['report']['measurement_status'] == 'NOT_MEASURED', observed
        assert 'PROFESSIONAL_COVERAGE_PLAN_INVALID' in actual['report']['reason'], observed
    else:
        assert observed['admission'] == 'expert_filled', observed


_HELPER_READER = 'def sample_handle(handle):\n    return int(handle.value)\n'


def _helper_scoreboard_project(root, helper, expression, *, before='', after='',
                               module_after='', drive=True, test_arguments='dut'):
    """Normal professional producer, with a competing functional Verilog suite."""
    import professional_tb_gen as gen
    project, bundle = _professional_project(root)
    source = _COCOTB_SCOREBOARD.replace('int(dut.result.value)', expression)
    source = source.replace('async def reference_model(dut):',
                            f'async def reference_model({test_arguments}):')
    source = source.replace('    for value in', before + '    for value in')
    source += after
    if not drive:
        source = source.replace('dut.sample.value = value', 'dut.sample.value = 0')
    source = source.replace('@cocotb.test()', helper + '\n@cocotb.test()') + module_after
    (bundle / 'expert_reference_tb.py').write_text(source)
    (bundle / 'replacement.py').write_text('def sample_handle(handle):\n    return 0\n')
    gen.generate(project)
    competing = project / 'phase2/stage1/sim/tb'
    competing.mkdir(parents=True)
    (competing / 'tb_vector.v').write_text(
        'module tb_vector; reg sample=0; reg ck4=0; wire result;\n'
        'converter dut(.sample(sample),.ck4(ck4),.result(result));\n'
        'initial begin sample=1; #5 sample=0; #5 $finish; end\nendmodule\n')
    return project, bundle / 'tb_converter.py'


@pytest.mark.parametrize('helper,expression', [
    (_HELPER_READER, 'sample_handle(dut.result)'),
    (_HELPER_READER, 'sample_handle(handle=dut.result)'),
    ('def sample_handle(unused, handle):\n    return int(handle.value)\n',
     'sample_handle(0, handle=dut.result)'),
    ('def sample_handle(*, handle):\n    return int(handle.value)\n',
     'sample_handle(handle=dut.result)'),
    ('def sample_handle(handle, label="result"):\n'
     '    if not handle.value.is_resolvable:\n'
     '        raise AssertionError(label)\n'
     '    return int(handle.value)\n', 'sample_handle(dut.result)'),
], ids=['positional', 'keyword', 'keyword-mapping', 'keyword-only', 'validated-read'])
def test_local_handle_reader_joins_the_functional_suite(tmp_path, helper, expression):
    project, tb = _helper_scoreboard_project(tmp_path, helper, expression)
    audit = V.functional_stimulus_audit(tb)
    assert audit['decidable'] and audit['driven'] == ['sample'], audit
    _, selected = V.discover_measure_testbenches(project)
    assert set(map(lambda p: Path(p).name, selected)) == {'tb_vector.v', 'tb_converter.py'}, selected


@pytest.mark.parametrize('helper,expression,options', [
    (_HELPER_READER, 'int(dut.result.value)', {}),
    (_HELPER_READER, 'sample_handle(dut.result)', {'drive': False}),
], ids=['direct-read-with-unused-helper', 'read-without-functional-drive'])
def test_local_reader_preserves_direct_and_inert_controls(tmp_path, helper, expression, options):
    project, tb = _helper_scoreboard_project(tmp_path, helper, expression, **options)
    audit = V.functional_stimulus_audit(tb)
    assert audit['decidable'], audit
    assert audit['driven'] == ([] if options else ['sample']), audit
    _, selected = V.discover_measure_testbenches(project)
    assert (str(tb) in selected) is (not options), selected
    assert any(Path(p).name == 'tb_vector.v' for p in selected), selected


@pytest.mark.parametrize('helper,expression,options', [
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\ndef unused(x=(sample_handle := lambda handle: 0)):\n    pass\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    def unused(x=(dut := None)):\n        pass\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\nunused = lambda x=(sample_handle := lambda handle: 0): 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    unused = lambda x=(dut := None): 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\n@(sample_handle := lambda handle: 0)\ndef unused():\n    pass\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    class Unused((dut := object)):\n        pass\n'}),
    ('def sample_handle(handle):\n    match {}:\n        case {**handle}:\n            pass\n'
     '    return int(handle.value)\n', 'sample_handle(dut.result)', {}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    match {}:\n        case {**sample_handle}:\n            pass\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    match {}:\n        case {**dut}:\n            pass\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\nmatch {}:\n    case {**sample_handle}:\n        pass\n'}),
    ('def sample_handle(handle):\n    def mutate():\n        nonlocal handle\n'
     '        handle = None\n    mutate()\n    return int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    def mutate():\n        nonlocal dut\n        dut = None\n    mutate()\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\nfrom replacement import *\n'}),
    ('def sample_handle(handle):\n    unused = (handle.value for _ in ())\n    return 0\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    if True:\n        return 0\n    return int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    (_HELPER_READER, '0', {'before': '    unused = (sample_handle(dut.result) for _ in ())\n'}),
    ('def sample_handle(handle):\n    return False and int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    return 0 if True else int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    (_HELPER_READER, 'False and sample_handle(dut.result)', {}),
    (_HELPER_READER, '0 if True else sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    unused = [handle.value for _ in ()]\n    return 0\n',
     'sample_handle(dut.result)', {}),
    (_HELPER_READER, '0', {}),
    ('def sample_handle(handle):\n    handle.value = 0\n    return 0\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    return 0\n', 'sample_handle(dut.result)', {}),
    (_HELPER_READER, '0', {'before': '    if False:\n        sample_handle(dut.result)\n'}),
    ('def sample_handle(handle):\n    if False:\n        return int(handle.value)\n    return 0\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    return 0\n    return int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    def unused():\n        return int(handle.value)\n    return 0\n',
     'sample_handle(dut.result)', {}),
    ('def replace(fn):\n    return lambda handle: 0\n@replace\n' + _HELPER_READER,
     'sample_handle(dut.result)', {}),
    (_HELPER_READER.replace('def sample_handle', 'async def sample_handle'),
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle):\n    yield int(handle.value)\n', 'sample_handle(dut.result)', {}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\nsample_handle = lambda handle: 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'module_after': '\ndef sample_handle(handle):\n    return 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'test_arguments': 'dut, sample_handle=None'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'after': '    sample_handle = lambda handle: 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    if False:\n        sample_handle = lambda handle: 0\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    from math import floor as sample_handle\n'}),
    (_HELPER_READER, 'sample_handle(dut.result)',
     {'before': '    def sample_handle(handle):\n        return 0\n'}),
    ('def sample_handle(unused, handle):\n    return int(handle.value)\n',
     'sample_handle(dut.result, handle=0)', {}),
    (_HELPER_READER, 'sample_handle(dut.result, handle=dut.result)', {}),
    (_HELPER_READER, 'sample_handle()', {}),
    (_HELPER_READER, 'sample_handle(dut.result, 0)', {}),
    (_HELPER_READER, 'sample_handle(*[dut.result])', {}),
    (_HELPER_READER, 'sample_handle(**{"handle": dut.result})', {}),
    (_HELPER_READER, 'sample_handle(other=dut.result)', {}),
    ('def sample_handle(handle, /):\n    return int(handle.value)\n',
     'sample_handle(handle=dut.result)', {}),
    ('def sample_handle(handle, *args):\n    return int(handle.value)\n',
     'sample_handle(dut.result)', {}),
    ('def sample_handle(handle, **kwargs):\n    return int(handle.value)\n',
     'sample_handle(dut.result)', {}),
], ids=['header-module-function-default', 'header-caller-function-default',
        'header-module-lambda-default', 'header-caller-lambda-default',
        'header-module-decorator', 'header-caller-class-base', 'mapping-formal', 'mapping-caller-callable', 'mapping-caller-dut',
        'mapping-module-callable', 'nested-nonlocal-formal', 'nested-nonlocal-dut', 'module-star-import', 'lazy-generator-read', 'constant-return', 'lazy-generator-call',
        'short-circuit-read', 'conditional-expression-read', 'short-circuit-call',
        'conditional-expression-call', 'empty-comprehension-read', 'unused', 'write-only', 'ignore-handle', 'dead-call', 'dead-read',
        'read-after-return', 'nested-unused', 'decorated', 'async', 'generator',
        'module-rebind', 'module-redefinition', 'caller-parameter', 'caller-late-bind',
        'caller-dead-bind', 'caller-import', 'caller-definition', 'wrong-keyword-map',
        'duplicate-binding', 'missing', 'excess', 'starargs', 'kwargs', 'unknown-keyword',
        'posonly-keyword', 'helper-varargs', 'helper-kwargs'])
def test_ambiguous_or_unexecuted_helpers_do_not_displace_functional_verilog(
        tmp_path, helper, expression, options):
    project, tb = _helper_scoreboard_project(tmp_path, helper, expression, **options)
    audit = V.functional_stimulus_audit(tb)
    assert not audit['decidable'] and audit['driven'] == [], audit
    _, selected = V.discover_measure_testbenches(project)
    assert [Path(p).name for p in selected] == ['tb_vector.v'], selected


@pytest.mark.parametrize('binding', [
    'handle = None', 'handle: object = None', 'handle += 0', '(handle := None)',
    'del handle', 'for handle in []:\n        pass',
    'with context() as handle:\n        pass',
    'try:\n        pass\n    except Exception as handle:\n        pass',
    'def handle():\n        return 0',
    'if False:\n        handle = None',
], ids=['assign', 'annotated', 'augmented', 'named-expression', 'delete',
        'loop', 'with', 'except', 'nested-definition', 'dead-binding'])
def test_rebound_helper_formals_receive_no_handle_credit(tmp_path, binding):
    helper = 'def sample_handle(handle):\n    ' + binding + '\n    return int(handle.value)\n'
    project, tb = _helper_scoreboard_project(tmp_path, helper, 'sample_handle(dut.result)')
    audit = V.functional_stimulus_audit(tb)
    assert not audit['decidable'] and audit['driven'] == [], audit
    _, selected = V.discover_measure_testbenches(project)
    assert [Path(p).name for p in selected] == ['tb_vector.v'], selected

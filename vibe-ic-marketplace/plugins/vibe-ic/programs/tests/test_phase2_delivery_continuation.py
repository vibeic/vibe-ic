"""Phase-2 delivery ownership: real logical pad/iverilog, controlled board metadata.

The core and neutral PDK reuse existing public fixtures. No upstream synthesis,
physical pad ring, FPGA hardware or full IC qualification is claimed.
"""
import ast
import hashlib
import inspect
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).parent))
import design_one_shot_runner as D
import phase3_one_shot_runner as P3
import execution_policy as E
import full_stack_functional_tb as F
import bit_level_full_stack_tb_check as G
import flow_compliance_check as C
import step_output_collector as V
import test_fullstacktb_functional_population as B
import test_io_pad_chip_top_gen as PAD
import test_professional_tb_gen as NATIVE
import testbench_gen as TBG
import test_issue2064_analog_acceptance_producer as ANALOG


def write(root, rel, obj):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return path


def values(root, **data):
    write(root, 'actual-values.json', data)


def aggregate(plan, project, began):
    # The old real aggregate is measured too; absence of a new API is not a
    # controller exception and cannot be mistaken for a source VALUE failure.
    kwargs = {'project': project, 'started_at': began} if 'project' in inspect.signature(D._aggregate_verdict).parameters else {}
    return D._aggregate_verdict(plan, **kwargs)


def actual_main_full_stack_sites(project, monkeypatch, pdk, *, synth_status='PASS'):
    """Execute the shipped main's early and post-synth call sites in order.

    Only the surrounding unrelated pipeline is omitted. The producer calls,
    Default/DIE decision and post-synth dispatcher are actual source AST.
    """
    monkeypatch.setattr(E, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(D, '_phase2_pdk_config', lambda *_a: pdk)
    tree = ast.parse(Path(D.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    env = dict(vars(D), project=project, args=SimpleNamespace(container=None, pdk='testpdk'),
               plan=[], _full_stack_after_synth=False)
    span = next(n for n in main.body if isinstance(n, ast.If) and
                isinstance(n.test, ast.Call) and getattr(n.test.func, 'id', '') == '_before_entry' and
                n.test.args and isinstance(n.test.args[0], ast.Constant) and n.test.args[0].value == 'sim')
    body = span.orelse[0].orelse
    for node in body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                t.id == '_full_stack_after_synth' for t in node.targets)) or any(
                    isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'step_full_stack_functional_tb'
                    for n in ast.walk(node)):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), D.__file__, 'exec'), env)
    net = write(project, f'phase2/stage2/synth/{B.CORE}_synth.v',
                (project / f'phase2/stage1/rtl/{B.CORE}.v').read_text())
    env['_synth_row'] = D.StepResult('yosys_synth', synth_status, output_files=[str(net)],
                                   extras={'synth_top': B.CORE})
    for node in main.body:
        if isinstance(node, ast.If) and any(isinstance(n, ast.Call) and
                getattr(n.func, 'id', '') == '_phase2_logical_pad_top' for n in ast.walk(node)):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), D.__file__, 'exec'), env)
    return env['plan']


def native_pad_project(tmp_path, monkeypatch):
    project = B._mk_project(tmp_path, die=True, chip_top=False)
    # Existing native serial implementation, not B's simulator stand-in core.
    source = tmp_path / 'existing_native_core'
    NATIVE._random_goal_project(source, 64, '*', 8, True)
    rtl = (source / 'phase2/stage1/rtl/neutral_arithmetic.v').read_text().replace('neutral_arithmetic', B.CORE)
    write(project, f'phase2/stage1/rtl/{B.CORE}.v', rtl)
    write(project, 'plugin_output/declaration.json', json.loads((source / 'plugin_output/declaration.json').read_text()))
    # Both pad generator and oracle see the same actual public fixture ports.
    l9 = json.loads((project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').read_text())
    l9['clocks'] = [{'name': 'clk', 'period_ns': 10}]
    l9['reset_domains'] = [{'name': 'rst', 'polarity': 'active_high', 'sync': 'sync'}]
    write(project, 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', l9)
    write(project, 'phase1/generated_docs/L2_FRS.json', {'frs_sections': [{'content': 'p = x * y mod 2^8; serial-parallel multiplier; synchronous active-high reset'}]})
    write(project, 'phase3/librelane_switch.json', {'steps': {'9': 'direct'}})
    write(project, 'input/docs/L3_external_interface.md', '''---
layer: L3
---
# External interface
The I/O cell library is delegated to the PDK i/o pad defaults.
## Physical Pad Placement
| Pad side | signals |
|---|---|
| South (S) | `rst` |
| East (E) | `clk` |
| North (N) | `x[7:0]` |
| West (W) | `y` / `p` |
''')
    root = PAD._pdk(tmp_path / 'neutral_pdk')
    lib = write(root, 'testpdk/libs.ref/testlib_io/lib/io.lib', '''library(neutral) {
cell(testlib_io__in) {
pin(PAD) {
direction: input;
is_pad: true;
}
pin(Y) {
direction: output;
function: "PAD";
}
}
cell(testlib_io__bi) {
pin(PAD) {
direction: inout;
is_pad: true;
function: "A";
three_state: "OE";
}
pin(A) {
direction: input;
}
pin(OE) {
direction: input;
related_power_pin: "VDDIO";
}
pin(TIELO) {
direction: output;
function: "0";
related_power_pin: "VDDIO";
}
}
}
''')
    lef = root / 'testpdk/libs.ref/testlib_io/lef/testlib_io.lef'
    pdk = P3.PdkConfig('testpdk', str(lib), str(lef), str(lef), None, 'IO_Site', None)
    model = write(root, 'testpdk/libs.ref/testlib_io/verilog/io.v', '''module testlib_io__in(input PAD, output Y); assign Y=PAD; endmodule
module testlib_io__bi(inout PAD, input A,OE, output TIELO); assign TIELO=1'b0; assign PAD=OE?1'bz:A; endmodule
''')
    # Model-file transport only; the actual CLI producer, build, simulation,
    # scoring and digest-checking consumer all execute without a stand-in.
    monkeypatch.setattr(F, 'default_model_resolver', lambda *_a: ({str(model): model.read_text()}, 'neutral PDK behavioral models'))
    monkeypatch.setattr(TBG, '_detect_ic_class', lambda *_a: 'digital_arithmetic_primitive')
    return project, pdk


def test_existing_row5_retention_owns_functional_producer_not_route_predicate(tmp_path, monkeypatch):
    """The existing retention callback keeps its actual producer identity."""
    project = B._mk_project(tmp_path, die=False)
    monkeypatch.setattr(E, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(TBG, '_detect_ic_class', lambda *_a: 'digital_arithmetic_primitive')
    monkeypatch.setattr(F, 'default_dispatch', B._FakeSim())
    observed = []
    def retained(project, decision, flow, fn, args, kwargs, **options):
        result = fn(*args, **kwargs)
        observed.append({'site': decision.site, 'ids': decision.flow_steps,
                         'result_type': type(result).__name__})
        return result
    monkeypatch.setattr(D._spf, '_retained_dispatch', retained)
    predicate = getattr(D, '_phase2_needs_logical_pad_top', None)
    selected = predicate(project) if predicate else P3._chip_path_requests_pad_ring(project)
    result = D.step_full_stack_functional_tb(project, None)
    values(project, control='retained producer ownership', actual=observed,
           expected=[{'site': 'step_full_stack_functional_tb', 'ids': ['5'], 'result_type': 'StepResult'}])
    assert selected is False
    assert result.status == 'PASS'
    assert observed == [{'site': 'step_full_stack_functional_tb', 'ids': ['5'], 'result_type': 'StepResult'}]


@pytest.mark.parametrize('control', ['pass', 'disconnected', 'behavior_fail', 'stale', 'pad_absent', 'synth_fail'])
def test_default_phase2_native_pad_population_before_complete_consumer(tmp_path, monkeypatch, control):
    project, pdk = native_pad_project(tmp_path, monkeypatch)
    if control == 'pad_absent':
        (project / 'input/docs/L3_external_interface.md').unlink()
    if control == 'behavior_fail':
        rtl = project / f'phase2/stage1/rtl/{B.CORE}.v'
        rtl.write_text(rtl.read_text().replace('p <= next_accum[0]', "p <= 1'b0"))
    if control == 'disconnected':
        # Mutation at the real producer boundary; never hand-write a WROTE record.
        native = P3.step_io_pad_chip_top_gen
        def disconnected(*args, **kwargs):
            result = native(*args, **kwargs)
            top = project / 'phase3/stage3/pnr/chip_top_io.v'
            if top.is_file():
                text = top.read_text()
                text = text.replace('.p(p__core)', ".p()")
                assert text != top.read_text(), 'disconnection must alter actual generated wiring'
                top.write_text(text)
            return result
        monkeypatch.setattr(P3, 'step_io_pad_chip_top_gen', disconnected)
    began = time.time()
    plan = actual_main_full_stack_sites(project, monkeypatch, pdk,
                                       synth_status='FAIL' if control == 'synth_fail' else 'PASS')
    if control == 'stale' and (project / f'phase2/stage1/rtl/{B.CORE}.v').is_file():
        with (project / f'phase2/stage1/rtl/{B.CORE}.v').open('a') as handle:
            handle.write('// bytes changed after measurement\n')
    rc, result, _ = G.functional_full_stack_verdict(project)
    expected = 'PASS' if control == 'pass' else 'FAIL' if control in ('disconnected', 'behavior_fail') else 'NOT_MEASURED'
    values(project, issue=3060, control=control, expected=expected, actual=result['verdict'],
           rc=rc, producer_rows=[asdict(s) for s in plan], consumer=result,
           scope='actual logical pad CLI + iverilog/vvp + functional population consumer; synthesis/model sources controlled')
    assert result['verdict'] == expected, result
    if control == 'pass':
        record = json.loads(F.record_path(project).read_text())
        assert record['counts']['executed'] == record['counts']['passed'] == 3
        assert record['full_stack_top']['pad_ring'] is True
        assert record['full_stack_top']['module'] == 'chip_top'
        pads = json.loads((project / F.CHIP_TOP_RECORD_REL).read_text())['pad_instances']
        assert len(pads) == 12 and all(r['core_pin'] for r in pads.values())
        assert '.p(p__core)' in (project / 'phase3/stage3/pnr/chip_top_io.v').read_text()
        assert [s.name for s in plan] == ['io_pad_chip_top_gen', 'full_stack_functional_tb']
        assert all(s.status == 'PASS' for s in plan)
        assert aggregate(plan, project, began) == 'PASS'


@pytest.mark.parametrize('facts', ['empty_master', 'l5_no_analog', 'l5_empty', 'missing', 'broken', 'unknown', 'populated', 'contradictory_l22', 'intent'])
def test_positive_noanalog_only_is_inapplicable(tmp_path, facts):
    expected = 'NOT_APPLICABLE' if facts in ('empty_master', 'l5_no_analog', 'l5_empty') else 'NOT_MEASURED'
    if facts == 'empty_master':
        write(tmp_path, 'phase1/analog/analog_block_list.json', {'blocks': [], 'block_count': 0})
    elif facts == 'broken':
        write(tmp_path, 'phase1/analog/analog_block_list.json', '{broken')
    elif facts != 'missing':
        doc = {'no_analog': True} if facts in ('l5_no_analog', 'contradictory_l22', 'intent') else {'analog_blocks': []} if facts == 'l5_empty' else {'analog_blocks': [{'name': 'gain_stage'}]} if facts == 'populated' else {'notes': 'unknown applicability'}
        write(tmp_path, 'phase1/generated_docs/L5_ADI_SPEC.json', doc)
    if facts == 'contradictory_l22':
        write(tmp_path, 'phase1/generated_docs/L22_VERIFICATION_PLAN.json', {'fields': {'verification_plan': {'analog': [{'block': 'gain_stage'}]}}})
    if facts == 'intent':
        write(tmp_path, 'phase1/generated_docs/L10_TEST_CASES.json', {'test_cases': [{'name': 'analog_measurement', 'kind': 'verification_intent', 'expected': 'measured regulation'}]})
    rows = [D.step_analog_acceptance_tb_gen(tmp_path), D.step_analog_acceptance_tb_run(tmp_path)]
    values(tmp_path, issue=3099, facts=facts, expected=expected, rows=[asdict(s) for s in rows])
    assert [s.status for s in rows] == [expected, expected]
    assert rows[1].extras['sim_executed'] is False
    if expected == 'NOT_APPLICABLE':
        assert all(s.declared_by for s in rows)
        assert D._aggregate_verdict([D.StepResult('core_functional_evidence', 'PASS'), *rows]) == 'PASS'


@pytest.mark.parametrize('evidence,expected', [('within_bound', 'PASS'), ('out_of_bound', 'FAIL'), ('absent', 'NOT_MEASURED')])
def test_applicable_analog_acceptance_retains_actual_executor_outcome(tmp_path, monkeypatch, evidence, expected):
    """Existing A4 JSON transport corpus; actual producer and check executor."""
    monkeypatch.setenv('PYTHONPATH', str(PROGRAMS))
    project = ANALOG._value_project(tmp_path, record=evidence != 'absent')
    if evidence == 'out_of_bound':
        ANALOG._a4(project, 'block_a', values=[('mos_tt', 27, 1.5)])
    gen = D.step_analog_acceptance_tb_gen(project)
    run = D.step_analog_acceptance_tb_run(project)
    actual = D._aggregate_verdict([D.StepResult('core_functional_evidence', 'PASS'), gen, run])
    values(project, issue=3099, evidence=evidence, expected=expected, actual=actual,
           rows=[asdict(gen), asdict(run)], scope='A4 fixture transport + actual acceptance check executor, no native analog measurement')
    assert gen.status == 'PASS'
    assert run.status == actual == expected


def excluded_board(project, monkeypatch, plan, began):
    """Existing canonical Step6 exclusion, not a forged board measurement."""
    write(project, 'reports/orchestrator/phase2_one_shot.json', {'steps': [asdict(s) for s in plan]})
    audit = write(project, 'reports/phase2/fpga/quartus_map_audit.json', {'verdict': 'SKIP', 'sof_present': False, 'evidence': 'fpga_compile not run'})
    waivers = {}
    C._synthesise_fpga_skip_waivers(project, waivers)
    row = C.check_step(project, {'id': 6, 'name': 'FPGA verification', 'stage': 'stage1',
                               'required_outputs': ['phase2/stage1/fpga/output_files/*.sof'],
                               'gate': {'files_exist': ['phase2/stage1/fpga/output_files/*.sof']}}, waivers)
    assert row.status == 'NOT_MEASURED' and row.excluded_from_verdict and row.reason_class == 'input_absent', asdict(row)
    report = project / 'reports/orchestrator/phase2_one_shot.json'
    monkeypatch.setattr(V, '_iter_step_records', lambda *_a: iter([('6', 'FPGA verification', 'partial', 'phase2', 'stage1',
        [{'rel': str(audit.relative_to(project)), 'abs': str(audit), 'exists': True}])]))
    attempt = V.begin_step(project, '6', {str(report.relative_to(project)): {'sha256': hashlib.sha256(report.read_bytes()).hexdigest()}})
    V.finish_step(project, attempt, verdict=row.status, result={'canonical_consumer': {'step': asdict(row)}})
    return audit


@pytest.mark.parametrize('control', ['excluded', 'missing', 'previous', 'stale', 'board_contract', 'compile_fail', 'burn_fail', 'tool_absent', 'other_unmeasured'])
def test_current_board_exclusion_changes_only_aggregate_contribution(tmp_path, monkeypatch, control):
    plan = [D.step_qsf_gen(tmp_path, 'neutral_arithmetic', 'digital_arithmetic_primitive'),
            D.step_fpga_compile(tmp_path, 'neutral_arithmetic', None),
            D.step_fpga_burn(tmp_path, 'neutral_arithmetic')]
    assert plan[0].status == 'NOT_APPLICABLE'
    plan.append(D.StepResult('core_functional_evidence', 'PASS'))
    before = [asdict(s) for s in plan]
    began = time.time()
    audit = excluded_board(tmp_path, monkeypatch, plan, began) if control != 'missing' else None
    if control == 'previous':
        began = time.time()
    if control == 'stale':
        audit.write_text('{}')
    if control == 'board_contract':
        plan[0] = D.StepResult('qsf_gen', 'PASS')
    if control in ('compile_fail', 'burn_fail'):
        plan[1 if control == 'compile_fail' else 2].status = 'FAIL'
    if control == 'tool_absent':
        plan[1].reason_class = D._V.ReasonClass.TOOL_ABSENT
    if control == 'other_unmeasured':
        plan.append(D.StepResult('other_required_measurement', 'NOT_MEASURED', reason_class='input_absent'))
    expected = 'PASS' if control == 'excluded' else 'FAIL' if control in ('compile_fail', 'burn_fail') else 'NOT_MEASURED'
    actual = aggregate(plan, tmp_path, began)
    values(tmp_path, issue=3099, control=control, expected=expected, actual=actual,
           raw_rows=[asdict(s) for s in plan], scope='actual producer missing-input paths and canonical exclusion consumer; no FPGA execution')
    assert actual == expected
    if control == 'excluded':
        assert [asdict(s) for s in plan] == before
        assert all(s.status == 'NOT_MEASURED' for s in plan[1:3])
        import vibe_ic_one_shot_runner as outer
        write(tmp_path, 'reports/orchestrator/phase2_one_shot.json', {'verdict': actual})
        assert outer._row_verdict(tmp_path, 'phase2_one_shot.json', 0, began, 'phase2')[0] == 'PASS'


def test_actual_main_publishes_current_rows_before_complete_board_consumer(tmp_path, monkeypatch):
    """Real main call-site ordering and real existing board exclusion reader.

    Other frontend consumers are outside this controlled transport fixture.
    The report publisher is actual production code and must remain pending.
    """
    write(tmp_path, 'reports/orchestrator/phase2_one_shot.json', {'steps': []})
    plan = [D.step_qsf_gen(tmp_path, 'neutral_arithmetic', 'digital_arithmetic_primitive'),
            D.step_fpga_compile(tmp_path, 'neutral_arithmetic', None),
            D.step_fpga_burn(tmp_path, 'neutral_arithmetic')]
    write(tmp_path, 'reports/phase2/fpga/quartus_map_audit.json', {'verdict': 'SKIP', 'sof_present': False})
    observed = []
    def board_consumer(project, plan, *_a):
        waivers = {}
        C._synthesise_fpga_skip_waivers(project, waivers)
        row = C.check_step(project, {'id': 6, 'name': 'FPGA verification', 'stage': 'stage1',
                              'required_outputs': ['phase2/stage1/fpga/output_files/*.sof'],
                              'gate': {'files_exist': ['phase2/stage1/fpga/output_files/*.sof']}}, waivers)
        observed.append(asdict(row))
        return D.StepResult('phase2_manifests', 'PASS')
    monkeypatch.setattr(D, '_complete_phase2_frontend', board_consumer)
    tree = ast.parse(Path(D.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    env = dict(vars(D), project=tmp_path, plan=plan, ic_class='digital_arithmetic_primitive',
               evidence='neutral inline INPUT', _dispatch_invocation_context=None,
               args=SimpleNamespace(top_name='neutral_arithmetic', container=None), _bounded=False)
    for node in main.body:
        if any(isinstance(n, ast.Call) and getattr(n.func, 'id', '') == '_complete_phase2_frontend' for n in ast.walk(node)):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), D.__file__, 'exec'), env)
            break
        if (isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.operand, ast.Name) and node.test.operand.id == '_bounded'
                and any(isinstance(n, ast.Call) and getattr(n.func, 'id', '') == '_publish_record_before_audit'
                        for n in ast.walk(node))):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), D.__file__, 'exec'), env)
    values(tmp_path, issue=3099, actual=observed[0]['reason_class'], expected='input_absent', consumer=observed[0])
    assert observed[0]['reason_class'] == 'input_absent'
    assert observed[0]['status'] == 'NOT_MEASURED' and observed[0]['excluded_from_verdict']
    report = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_text())
    assert report['verdict'] == 'FAIL' and report['final_audit_pending'] is True

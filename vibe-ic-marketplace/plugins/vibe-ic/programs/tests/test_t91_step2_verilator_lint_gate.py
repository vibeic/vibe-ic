"""Step 2 lint through LibreLane Verilator.Lint (T91, lane mig-rtlver).

The transcripts are real LibreLane Verilator.Lint output from the released
image (programs/calibration/librelane_verilator_lint_*.log). Only the tool's
file writes are substituted, at the subprocess edge of librelane_contract.
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
hub = importlib.import_module('_rtl_include_hub')

CAL = PROGRAMS / 'calibration'
POS = (CAL / 'librelane_verilator_lint_pos.log').read_text()
NEG = (CAL / 'librelane_verilator_lint_neg.log').read_text()
POS_SRC = '/tmp/vlcal/phase2/stage1/rtl/cal_pos.v'
NEG_SRC = '/tmp/vlcal/phase2/stage1/rtl/cal_neg.v'
# The MULTIDRIVEN diagnostic alone, cut from the real positive transcript.
MULTI = POS[POS.index('%Warning-MULTIDRIVEN'):POS.index('%Error: Exiting')]


def gate():
    return importlib.import_module('verilator_lint_gate')


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def step_dir(root, log, linted, errors, warnings, latch=0):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'verilator-lint.log').write_text(log)
    put(root / 'config.json', {'VERILOG_FILES': [str(p) for p in linted]})
    put(root / 'state_out.json', {'metrics': {
        'design__lint_error__count': errors, 'design__lint_warning__count': warnings,
        'design__inferred_latch__count': latch,
        'design__lint_timing_construct__count': 0}})
    return root


def rtl(tmp_path, name='cal_pos.v', body='module cal_pos; endmodule\n'):
    path = tmp_path / 'design/phase2/stage1/rtl' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_error_and_curated_warning_in_the_design_block(tmp_path):
    src = rtl(tmp_path)
    folder = step_dir(tmp_path / 'lint', POS.replace(POS_SRC, str(src)), [src], 1, 1, 1)
    report = gate().judge(folder, [src])
    assert report['verdict'] == 'FAIL'
    assert sorted(row['code'] for row in report['blocking']) == ['LATCH', 'MULTIDRIVEN']


def test_curated_warning_alone_blocks_in_the_design(tmp_path):
    src = rtl(tmp_path)
    folder = step_dir(tmp_path / 'lint', MULTI.replace(POS_SRC, str(src)), [src], 0, 1)
    report = gate().judge(folder, [src])
    assert (report['verdict'], [r['code'] for r in report['blocking']]) == \
        ('FAIL', ['MULTIDRIVEN'])


def test_curated_warning_outside_the_design_sources_does_not_block(tmp_path):
    src = rtl(tmp_path)
    model = str(tmp_path / 'toolbox_tmp/cells.bb.v')
    folder = step_dir(tmp_path / 'lint', MULTI.replace(POS_SRC, model), [src], 0, 1)
    report = gate().judge(folder, [src])
    assert (report['verdict'], report['blocking']) == ('PASS', [])
    assert [r['code'] for r in report['diagnostics']] == ['MULTIDRIVEN']


def test_uncurated_warning_is_reported_and_passes(tmp_path):
    src = rtl(tmp_path, 'cal_neg.v')
    folder = step_dir(tmp_path / 'lint', NEG.replace(NEG_SRC, str(src)), [src], 0, 1)
    report = gate().judge(folder, [src])
    assert report['verdict'] == 'PASS'
    assert [r['code'] for r in report['diagnostics']] == ['UNUSEDSIGNAL']


def test_empty_file_set_is_not_measured_never_pass(tmp_path):
    folder = step_dir(tmp_path / 'lint', NEG, [], 0, 1)
    report = gate().judge(folder, [])
    assert (report['verdict'], report['reason_class']) == ('NOT_MEASURED', 'INPUT_ABSENT')
    assert gate().main(['--step-dir', str(folder), '--json', str(tmp_path / 'g.json')]) == 2


def test_a_v_file_the_linter_skipped_is_a_file_set_mismatch(tmp_path):
    """The step-2 lint once globbed *.sv only and linted none of a .v design."""
    sv = rtl(tmp_path, 'top.sv')
    v = rtl(tmp_path, 'leaf.v')
    folder = step_dir(tmp_path / 'lint', NEG.replace(NEG_SRC, str(sv)), [sv], 0, 1)
    report = gate().judge(folder, [sv, v])
    assert (report['verdict'], report['reason_class']) == ('FAIL', 'LINT_FILE_SET_MISMATCH')
    assert report['file_set']['missing'] == [str(v.resolve())]


def test_reader_disagreeing_with_the_tool_counters_is_not_measured(tmp_path):
    src = rtl(tmp_path)
    folder = step_dir(tmp_path / 'lint', POS.replace(POS_SRC, str(src)), [src], 0, 1)
    report = gate().judge(folder, [src])
    assert (report['verdict'], report['reason_class']) == ('NOT_MEASURED', 'INSTRUMENT_DISAGREES')


def test_missing_step_output_is_not_measured(tmp_path):
    report = gate().judge(tmp_path / 'absent', [rtl(tmp_path)])
    assert (report['verdict'], report['reason_class']) == ('NOT_MEASURED', 'TOOL_OUTPUT_ABSENT')


def test_silicon_selection_takes_v_and_sv_and_skips_testbenches(tmp_path):
    for name in ('core.v', 'bus_pkg.sv', 'core_tb.sv', 'top.sv'):
        rtl(tmp_path, name)
    select = getattr(hub, 'silicon_rtl_selection', None)
    names = [p.name for p in select(tmp_path / 'design/phase2/stage1/rtl')] if select else []
    assert names == ['bus_pkg.sv', 'top.sv', 'core.v']


def test_lint_config_carries_declared_inputs_and_refuses_foreign_rtl(tmp_path):
    src = rtl(tmp_path)
    out = tmp_path / 'design/cfg.json'
    config = contract.emit_lint_config(tmp_path / 'design', 'pdkA', out, 'cal_pos',
                                       [src], 'L9_INTEGRATION_SPEC.top_module')
    assert config['meta'] == {'step': 'Verilator.Lint'}
    assert config['VERILOG_FILES'] == [str(src.resolve())]
    assert set(json.loads(out.with_suffix('.provenance.json').read_text())) == \
        {'DESIGN_NAME', 'PDK', 'VERILOG_FILES', 'USE_SLANG'}
    assert config['USE_SLANG'] is False
    with pytest.raises(contract.Refusal, match='LL_LINT_INPUT_MISSING'):
        contract.emit_lint_config(tmp_path / 'design', 'pdkA', out, 'cal_pos',
                                  [tmp_path / 'elsewhere.v'], 'x')
    with pytest.raises(contract.Refusal, match='LL_TOP_UNDECLARED'):
        contract.emit_lint_config(tmp_path / 'design', 'pdkA', out, '', [src], 'x')


# ---- the runner call site -------------------------------------------------

def _design(tmp_path, mode, log, errors, warnings):
    project = tmp_path / 'design'
    src = rtl(tmp_path, 'cal_pos.v', (
        'module cal_pos(input wire clk, input wire a, output reg q);\n'
        '    always @(posedge clk) q <= a;\n'
        '    always @(negedge clk) q <= ~a;\nendmodule\n'))
    rtl(tmp_path, 'cal_pos_tb.v', 'module cal_pos_tb; endmodule\n')
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'cal_pos'})
    put(project / 'input/project.json', {'pdk': 'pdkA'})
    if mode:
        # The stated environment: image AND PDK root declared, so the
        # contract's resolvers answer without asking this host's docker.
        (tmp_path / 'pdkroot').mkdir(exist_ok=True)
        put(project / 'phase3/librelane_switch.json',
            {'steps': {'2': mode}, 'image': 'img', 'pdk': 'pdkA',
             'pdk_root_host': str(tmp_path / 'pdkroot')})
    calls = []

    def tool(cmd, **_):
        calls.append(cmd)
        if '-c' in cmd and 'Config.load' in cmd[cmd.index('-c') + 1]:
            script = cmd[cmd.index('-c') + 1]
            source = script.split("p='", 1)[1].split("'", 1)[0]
            output = script.split("out='", 1)[1].split("'", 1)[0]
            Path(output).write_text(Path(source).read_text())
        elif 'librelane.steps' in cmd and cmd[cmd.index('--id') + 1] == 'Yosys.JsonHeader':
            folder = Path(cmd[cmd.index('-o') + 1])
            folder.mkdir(parents=True, exist_ok=True)
            header = folder / 'cal_pos.h.json'
            header.write_text(json.dumps({'modules': {'cal_pos': {'ports': {
                'clk': {'direction': 'input', 'bits': [2]},
                'a': {'direction': 'input', 'bits': [3]},
                'q': {'direction': 'output', 'bits': [4]}}}}}))
            put(folder / 'state_out.json', {'json_h': str(header), 'metrics': {}})
        elif 'librelane.steps' in cmd and 'run' in cmd:
            folder = Path(cmd[cmd.index('-o') + 1])
            config = json.loads(Path(cmd[cmd.index('-c') + 1]).read_text())
            step_dir(folder, log.replace(POS_SRC, config['VERILOG_FILES'][0]),
                     config['VERILOG_FILES'], errors, warnings)
            put(folder / 'config.json', config)  # retain native step identity
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return project, src, calls, tool


def _runner(monkeypatch, tool):
    runner = importlib.import_module('design_one_shot_runner')
    # The supplied tool records Docker argv and writes fixture outputs. Its
    # fake image is not the identity of pytest's enclosing EDA container.
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    monkeypatch.setattr(contract.subprocess, 'run', tool)
    return runner, getattr(runner, 'step_rtl_lint_tool', None)


def test_librelane_mode_lints_the_synthesis_file_set_and_blocks(tmp_path, monkeypatch):
    project, src, calls, tool = _design(tmp_path, 'librelane', POS, 1, 1)
    _, step = _runner(monkeypatch, tool)
    row = step(project) if step else None
    report_path = project / 'reports/phase2/lint/verilator_lint_gate.json'
    report = json.loads(report_path.read_text()) if report_path.is_file() else {}
    assert report.get('file_set', {}).get('linted') == [str(src.resolve())]
    assert (row.status if row else None, report.get('verdict')) == ('FAIL', 'FAIL')
    assert any('librelane.steps' in c for c in calls)
    assert row.extras['spec_conformance_tool_ports_rc'] is not None
    assert (project / 'reports/phase2/gates/spec_conformance_tool_ports.json').is_file()


def test_tool_port_conformance_receives_the_native_declared_top(tmp_path, monkeypatch):
    project, _, _, tool = _design(tmp_path, 'librelane', MULTI, 0, 1)
    runner, step = _runner(monkeypatch, tool)
    original = runner._pr.run
    captured = []
    def record(argv, **kwargs):
        captured.append(argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(runner._pr, 'run', record)
    row = step(project)
    command = next(argv for argv in captured
                   if any(str(part).endswith('spec_conformance_check.py') for part in argv))
    assert command[command.index('--top') + 1] == 'cal_pos'
    assert '--tool-ports' in command
    assert row.extras['spec_conformance_tool_ports_rc'] is not None


@pytest.mark.parametrize('code,status,reason', [
    ('LL_TOOL_STALLED', 'NOT_MEASURED', 'stalled'),
    ('LL_TOOL_DEADLINE', 'NOT_MEASURED', 'budget_exhausted'),
    ('LL_STEP_FAILED', 'FAIL', ''),
])
def test_step2_books_the_shared_supervisor_refusal(tmp_path, monkeypatch,
                                                    code, status, reason):
    project, _, _, tool = _design(tmp_path, 'librelane', POS, 0, 0)
    _, step = _runner(monkeypatch, tool)

    def stopped(*_args, **_kwargs):
        raise contract.Refusal(code, 'tool did not complete')

    monkeypatch.setattr(contract, 'run_chain', stopped)
    row = step(project)
    assert row.status == status
    assert row.reason_class == reason
    assert code in row.detail
    assert row.extras['step_id'] == '2'
    assert row.extras['default_row_status'] == status
    assert row.extras['completed'] is False


def test_direct_mode_is_unchanged_and_adds_no_row(tmp_path, monkeypatch):
    project, _, calls, tool = _design(tmp_path, 'direct', NEG, 0, 1)
    runner, step = _runner(monkeypatch, tool)
    assert step is not None and step(project) is None and calls == []


def _standalone_rtl(tmp_path):
    src = rtl(tmp_path, 'plain.v',
              'module plain(input [7:0] value_i, output [7:0] value_o); '
              'assign value_o = ~value_i; endmodule\n')
    project = tmp_path / 'design'
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'plain'})
    return project, src


@pytest.mark.parametrize('valid', [True, False])
@pytest.mark.parametrize('declared_top', ['plain', None, 'original'])
def test_bounded_no_pdk_consumes_native_project_lint(tmp_path, monkeypatch, valid, declared_top):
    project, src = _standalone_rtl(tmp_path)
    spec_path = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    put(spec_path, {'top_module': declared_top})
    if declared_top == 'original':
        layout = importlib.import_module('_path_layout')
        monkeypatch.setattr(layout, '_RTL_INPUT', layout._RTL_INPUT)
        spec_path.unlink()  # This fixture deliberately has only an original prompt.
        prompt = project / 'input/phase1_prompt.md'
        prompt.parent.mkdir(parents=True)
        prompt.write_text('Module name: plain\nInvert the eight-bit input value_i into value_o.\n')
        layout.select_rtl_input(project, 'original', '2', '2')
    before = spec_path.read_bytes() if spec_path.exists() else None
    if not valid:
        src.write_text('module plain(input [7:0] value_i, output [7:0] value_o); '
                       'assign value_o = ; endmodule\n')
    runner = importlib.import_module('design_one_shot_runner')
    row = runner.step_rtl_lint_tool(project, bounded_rtl=True)
    assert row.status == ('PASS' if valid else 'FAIL'), row.detail
    context = row.extras['native_context']
    assert context['top'] == 'plain' and context['files'] == [str(src.resolve())]
    assert context['defines'] == []
    assert context['native_returncode'] == context['transport_returncode']
    assert context['native_returncode'] == (0 if valid else 1)
    assert (spec_path.read_bytes() if spec_path.exists() else None) == before
    assert row.name == ('rtl_validate' if declared_top == 'original' else 'rtl_lint_tool')
    assert isinstance(json.loads((project / 'reports/phase2/lint/rtl_hygiene.json').read_text()), list)
    assert not (project / 'phase3/librelane/step2/lint_config.json').exists()


def test_unnamed_native_lint_refuses_ambiguous_roots(tmp_path):
    project, src = _standalone_rtl(tmp_path)
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': None})
    src.write_text(src.read_text() + 'module other(input a, output b); assign b = a; endmodule\n')
    runner = importlib.import_module('design_one_shot_runner')
    row = runner.step_rtl_lint_tool(project, bounded_rtl=True)
    assert row.status == 'NOT_MEASURED' and 'unique selected top' in row.detail
    assert row.extras['completed'] is False


@pytest.mark.parametrize('choice', ['unbounded', 'step_switch', 'selected_pdk', 'malformed_pdk'])
def test_no_pdk_native_lint_does_not_replace_explicit_or_physical_contract(tmp_path, choice):
    project, _ = _standalone_rtl(tmp_path)
    if choice == 'step_switch':
        put(project / 'phase3/librelane_switch.json', {'steps': {'2': 'librelane'}})
    if choice == 'malformed_pdk':
        path = project / 'input/project.json'
        path.parent.mkdir(parents=True)
        path.write_text('{')
    runner = importlib.import_module('design_one_shot_runner')
    row = runner.step_rtl_lint_tool(project, bounded_rtl=choice != 'unbounded',
                                    pdk_name='declared-tech' if choice == 'selected_pdk' else None)
    assert row.status == 'FAIL', row.detail
    assert 'LL_PHASE2_PDK_' in row.detail
    assert not (project / 'reports/phase2/lint/rtl_hygiene.json').exists()


@pytest.mark.parametrize('native_rc,transport_rc', [(None, 127), (0, 125)])
def test_native_lint_failed_transport_is_not_a_design_pass(tmp_path, monkeypatch,
                                                          native_rc, transport_rc):
    project, src = _standalone_rtl(tmp_path)
    runner = importlib.import_module('design_one_shot_runner')

    def failed_transport(*args, **kwargs):
        out = project / 'reports/phase2/lint'
        put(out / 'rtl_hygiene.json', [])
        put(out / 'native-elaboration-failed/context.json', {
            'top': 'plain', 'files': [str(src.resolve())],
            'native_returncode': native_rc, 'transport_returncode': transport_rc,
            'status': 'NOT_MEASURED'})
        return SimpleNamespace(returncode=1, stdout='', stderr='native transport failed')

    monkeypatch.setattr(runner._pr, 'run', failed_transport)
    row = runner.step_rtl_lint_tool(project, bounded_rtl=True)
    assert row.status == 'NOT_MEASURED', row.detail
    assert row.extras['completed'] is False


def test_dual_mode_blocks_on_the_union_and_names_the_arm(tmp_path, monkeypatch):
    project, src, _, tool = _design(tmp_path, 'dual', MULTI, 0, 1)
    _, step = _runner(monkeypatch, tool)
    row = step(project) if step else None
    dual_path = project / 'reports/phase2/lint/lint_dual.json'
    dual = json.loads(dual_path.read_text()) if dual_path.is_file() else {}
    assert (row.status if row else None, dual.get('verdict')) == ('FAIL', 'FAIL')
    assert dual['arms']['librelane']['verdict'] == 'FAIL'
    assert dual['only_librelane'] == [[src.name, 5]]
    assert (project / 'reports/phase2/lint/rtl_hygiene_direct_arm.json').is_file()


# ---- spec conformance against the tool's elaborated ports ------------------

FIXTURE = PROGRAMS / 'tests/fixtures/t91_yosys_jsonheader_define_width.h.json'
DEFINE_RTL = ('`define WA 4\nmodule blk (\n    input  wire           clk,\n'
              '    input  wire [`WA-1:0] a,\n    output reg  [1:0]     q\n);\n'
              '    always @(posedge clk) q <= a[1:0] ^ a[3:2];\nendmodule\n')


def _conformance(tmp_path, *extra):
    import subprocess
    src = rtl(tmp_path, 'blk.v', DEFINE_RTL)
    spec = put(tmp_path / 'L9.json', {'top_module': 'blk', 'ports': [
        {'name': 'clk', 'direction': 'input', 'width': 1},
        {'name': 'a', 'direction': 'input', 'width': 8},
        {'name': 'q', 'direction': 'output', 'width': 2}]})
    return subprocess.run([sys.executable, str(PROGRAMS / 'spec_conformance_check.py'),
                           '--spec', str(spec), '--rtl-dir', str(src.parent), *extra],
                          capture_output=True, text=True)


def test_a_width_behind_a_define_is_compared_from_the_tool_ports(tmp_path):
    """Regex reads `[`WA-1:0]` as width 0 (unknown) and passes an 8-vs-4 port;
    the Yosys.JsonHeader interface (real tool output) measures 4."""
    assert _conformance(tmp_path).returncode == 0          # the text reader's blind spot
    tool = _conformance(tmp_path, '--tool-ports', str(FIXTURE))
    assert tool.returncode == 1
    assert "port 'a' width RTL=4 vs spec=8" in tool.stdout


def test_a_top_missing_from_the_tool_ports_is_not_measured(tmp_path):
    other = put(tmp_path / 'other.json', {'modules': {'else': {'ports': {}}}})
    assert _conformance(tmp_path, '--tool-ports', str(other)).returncode == 2


def _native_checks(root, metrics):
    result={}
    for sid,flag in [('Checker.LintErrors','ERROR_ON_LINTER_ERRORS'),
                     ('Checker.LintTimingConstructs','ERROR_ON_LINTER_TIMING_CONSTRUCTS'),
                     ('Checker.LintWarnings','ERROR_ON_LINTER_WARNINGS')]:
        folder=root/sid;put(folder/'config.json',{'meta':{'step':sid},
            flag:sid!='Checker.LintWarnings'})
        put(folder/'state_out.json',{'metrics':metrics});result[sid]=folder
    return result


def test_default_lint_uses_native_checker_authority(tmp_path,monkeypatch):
    project,src,_,tool=_design(tmp_path,'librelane',MULTI,0,1)
    _,step=_runner(monkeypatch,tool)
    result=step(project)
    assert result.status=='PASS',result.detail
    report=json.loads((project/'reports/phase2/lint/verilator_lint_gate.json').read_text())
    assert report['counts']=={'errors':0,'warnings':1}
    assert report['authority']=='LibreLane native lint checkers'
    assert result.extras['completed'] is True


@pytest.mark.parametrize('mutation,expected', [
    ('missing','NOT_MEASURED'),('foreign','NOT_MEASURED'),
    ('counter','NOT_MEASURED'),('disabled','NOT_MEASURED'),
    ('latch','FAIL'),('error','FAIL'),('timing','FAIL'),
    ('strict_warning','FAIL'),('missing_metric','NOT_MEASURED')])
def test_native_lint_checks_preserve_failure_and_missing_work(tmp_path,mutation,expected):
    src=rtl(tmp_path)
    folder=step_dir(tmp_path/'lint','native diagnostics need no second parser\n',[src],0,307)
    metrics=json.loads((folder/'state_out.json').read_text())['metrics']
    if mutation in ('latch','error','timing'):
        metric={'latch':'design__inferred_latch__count','error':'design__lint_error__count',
                'timing':'design__lint_timing_construct__count'}[mutation];metrics[metric]=1
    if mutation=='missing_metric':metrics.pop('design__inferred_latch__count')
    put(folder/'state_out.json',{'metrics':metrics});checks=_native_checks(tmp_path/'checks',metrics)
    errors=checks['Checker.LintErrors']
    if mutation=='missing':(errors/'state_out.json').unlink()
    if mutation=='foreign':put(errors/'config.json',{'meta':{'step':'Checker.TrDRC'}})
    if mutation=='counter':put(errors/'state_out.json',{'metrics':{**metrics,'design__lint_error__count':9}})
    if mutation=='disabled':put(errors/'config.json',{'meta':{'step':'Checker.LintErrors'},'ERROR_ON_LINTER_ERRORS':False})
    if mutation=='strict_warning':put(checks['Checker.LintWarnings']/'config.json',{'meta':{'step':'Checker.LintWarnings'},'ERROR_ON_LINTER_WARNINGS':True})
    answer=gate().judge(folder,[src],checker_dirs=checks)
    assert answer['verdict']==expected,answer


def test_native_metric_only_inputs_do_not_relax_physical_step_views():
    contract._check_state({'metrics':{}},step_id='Checker.LintErrors')
    with pytest.raises(contract.Refusal,match='LL_STATE_MISSING'):
        contract._check_state({'metrics':{}},step_id='OpenROAD.DetailedRouting')

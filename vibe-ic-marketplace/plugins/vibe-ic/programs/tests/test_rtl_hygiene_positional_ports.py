"""Conservative positional-port driver resolution for ``rtl_hygiene_lint``.

The parser is shared with ``module_port_audit``.  These fixtures are neutral,
compile-shaped RTL and exercise the actual linter consumer: only a resolved
same-file child output/inout formal may credit a parent actual as driven.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import json
import os

import pytest
import json

PROGRAMS = Path(os.environ.get(
    "VIBEIC_HYGIENE_PROGRAMS_DIR", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as lint  # noqa: E402


NATIVE_TOP = """module top #(parameter ENABLE=0)(input source, output result);
wire routed;
generate if (ENABLE) begin: selected
leaf u_leaf(.a(source), .y(routed));
assign result=routed;
end else begin: inactive
assign result=source;
end endgenerate
endmodule
"""
NATIVE_LEAF = 'module leaf(input a, output y); assign y=a; endmodule\n'


@pytest.mark.parametrize('relative_report', [True, False], ids=['relative', 'absolute'])
def test_native_project_report_paths_obey_docker_mount_protocol(
        tmp_path, monkeypatch, relative_report):
    """CPU transport-contract control; actual Docker/Yosys is separate evidence."""
    import _eda_image
    import librelane_contract
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    source = rtl / 'top.v'
    source.write_text('module top(input source, output result); '
                      'assign result=source; endmodule\n')
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.chdir(project)
    target = 'registry.invalid/neutral-tools@sha256:' + 'ac' * 32
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', target)
    monkeypatch.delenv('IIC_EDA_IMAGE', raising=False)
    monkeypatch.delenv(librelane_contract.LOCAL_ATTESTATION_ENV, raising=False)
    monkeypatch.setattr(_eda_image, 'local_digest',
                        lambda selected: ('sha256:' + 'ac' * 32, 'repo-digest', ''))
    calls = []

    def transport(argv, **kwargs):
        calls.append(argv)
        for index, arg in enumerate(argv):
            if arg == '-v':
                host, container, *_ = argv[index + 1].split(':')
                if not Path(host).is_absolute() or not Path(container).is_absolute():
                    raise ValueError('Docker mount paths must be absolute')
        at = argv.index('--skip')
        receipt = Path(argv[at + 4])
        command = argv[at + 5:]
        script = Path(command[-1])
        assert receipt.is_absolute() and script.is_absolute()
        work = script.parent
        assert work.parent == (project / 'reports/lint').resolve()
        assert 'write_json "' + str(work / 'design.json') + '"' in script.read_text()
        (work / 'design.json').write_text(json.dumps({'modules': {'top': {}}}))
        receipt.write_text(json.dumps({'command': command, 'native_returncode': 0}))
        return subprocess.CompletedProcess(argv, 0, 'controlled transport reply\n', '')

    monkeypatch.setattr(librelane_contract, 'run_container', transport)
    report = Path('reports/lint/findings.json')
    if not relative_report:
        report = project / report
    monkeypatch.setattr(sys, 'argv', [str(PROGRAMS / 'rtl_hygiene_lint.py'),
        '--project', '.', '--json', str(report), '--severity', 'ERROR'])
    assert lint.main() == 0
    assert json.loads(report.read_text()) == [] and len(calls) == 1
    context_path, = (project / 'reports/lint').glob('native-elaboration-*/context.json')
    context = json.loads(context_path.read_text())
    assert context['status'] == 'MEASURED'
    assert context['native_returncode'] == context['transport_returncode'] == 0
    assert source.read_text().startswith('module top(input source, output result);')


@pytest.mark.parametrize('defines,parameters', [(['FEATURE;bad'], []), ([], ['ENABLE=bad'])])
def test_native_relative_report_keeps_invalid_configuration_refusal(
        tmp_path, monkeypatch, defines, parameters):
    source = tmp_path / 'top.v'
    source.write_text('module top(input a, output y); assign y=a; endmodule\n')
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(lint, '_native_driver_run', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='invalid native compile define|NAME=integer'):
        lint._native_driver_view([source], 'top', defines, parameters, [], Path('reports'))
    assert calls == []


def _native_lint_cli(tmp_path, source=NATIVE_TOP, extra=()):
    assert shutil.which('yosys'), 'native driver qualification requires Yosys'
    leaf = tmp_path / 'leaf.v'
    top = tmp_path / 'top.v'
    leaf.write_text(NATIVE_LEAF)
    top.write_text(source)
    report = tmp_path / 'findings.json'
    result = subprocess.run([sys.executable, str(PROGRAMS / 'rtl_hygiene_lint.py'),
        str(leaf), str(top), '--top', 'top', '--severity', 'ERROR', '--json', str(report),
        *extra], capture_output=True, text=True)
    assert report.is_file(), result.stdout + result.stderr
    assert top.read_text() == source and leaf.read_text() == NATIVE_LEAF
    return result, json.loads(report.read_text())


@pytest.mark.parametrize('enabled', [0, 1])
def test_native_selected_parameter_branch_resolves_driver_cli(tmp_path, enabled):
    result, findings = _native_lint_cli(tmp_path, extra=['--parameter', f'ENABLE={enabled}'])
    assert result.returncode == 0, result.stdout + result.stderr
    assert sum(f['symbol'] == 'routed' and f['severity'] == 'ERROR' for f in findings) == 0
    context = json.loads(next(tmp_path.glob('native-elaboration-*/context.json')).read_text())
    assert context['status'] == 'MEASURED' and context['parameters'] == [f'ENABLE={enabled}']


@pytest.mark.parametrize('enabled', [False, True])
def test_native_selected_preprocessor_branch_resolves_driver_cli(tmp_path, enabled):
    source = """module top(input source, output result);
wire routed;
`ifdef FEATURE
leaf u_leaf(.a(source), .y(routed));
assign result=routed;
`else
assign result=source;
`endif
endmodule
"""
    result, findings = _native_lint_cli(tmp_path, source, ['--define', 'FEATURE'] if enabled else [])
    assert result.returncode == 0, result.stdout + result.stderr
    assert sum(f['symbol'] == 'routed' and f['severity'] == 'ERROR' for f in findings) == 0


def test_native_disabled_driver_still_blocks_when_output_reads_it(tmp_path):
    source = NATIVE_TOP.replace('assign result=routed;', '').replace('assign result=source;', '')
    source = source.replace('end endgenerate', 'end endgenerate\nassign result=routed;')
    result, findings = _native_lint_cli(tmp_path, source)
    assert result.returncode == 1
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    assert any(f['symbol'] == 'routed' and f['block_eligible'] for f in findings)


@pytest.mark.parametrize('connection', ['.a(source), .y(routed), .y(routed)',
                                       '.a(source), .y(routed), broken'])
def test_native_does_not_erase_bad_connections(tmp_path, connection):
    source = NATIVE_TOP.replace('.a(source), .y(routed)', connection)
    result, findings = _native_lint_cli(tmp_path, source, ['--parameter', 'ENABLE=1'])
    assert result.returncode == 1
    assert any(f['symbol'] == 'routed' and f['severity'] == 'ERROR' for f in findings)


def test_native_fresh_invocations_reject_previous_good_configuration(tmp_path):
    first, _ = _native_lint_cli(tmp_path, extra=['--parameter', 'ENABLE=1'])
    assert first.returncode == 0
    old = {p: p.read_bytes() for p in tmp_path.glob('native-elaboration-*/*')}
    bad = NATIVE_TOP.replace('assign result=source;', 'assign result=routed;')
    second, findings = _native_lint_cli(tmp_path, bad)
    assert second.returncode == 1
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    assert len(list(tmp_path.glob('native-elaboration-*/context.json'))) == 2
    assert all(p.read_bytes() == value for p, value in old.items())


def test_native_aggregate_keeps_other_findings_and_missing_auditor(tmp_path):
    (tmp_path / 'leaf.v').write_text(NATIVE_LEAF)
    (tmp_path / 'top.v').write_text(NATIVE_TOP + '\nmodule unused(input a, output reg q); always @(a) q <= a; endmodule\n')
    output = tmp_path / 'review.json'
    result = subprocess.run([sys.executable, str(PROGRAMS / 'rtl_review_aggregate.py'),
        '--rtl-dir', str(tmp_path), '--top', 'top', '--parameter', 'ENABLE=1',
        '--out-json', str(output), '--strict'], capture_output=True, text=True)
    assert output.is_file(), result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert sum(f['rule_id'] == 'instance-driver-analysis-unresolved'
               for category in report['per_category'].values() for f in category['findings']) == 0
    assert report['total_warns'] > 0 and report['auditors_not_run']
    assert result.returncode == 1


def test_default_declared_gate_uses_real_selected_inputs(tmp_path):
    import yaml
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'leaf.v').write_text(NATIVE_LEAF)
    (rtl / 'top.v').write_text(NATIVE_TOP.replace('parameter ENABLE=0', 'parameter ENABLE=1'))
    (rtl / 'top_tb.v').write_text('this excluded testbench is not RTL;\n')
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'top'}))
    flow = yaml.safe_load((PROGRAMS.parent / 'flow/phase1_phase2_phase3.yaml').read_text())
    step2 = next(step for step in flow['steps'] if str(step['id']) == '2')
    assert {'from': 'D1', 'path': 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'} in step2['required_inputs']
    def commands(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'program_exit_zero' and isinstance(item, str) and item.startswith('rtl_hygiene_lint '):
                    yield item
                else: yield from commands(item)
        elif isinstance(value, list):
            for item in value: yield from commands(item)
    command, = list(commands(flow))
    import flow_compliance_check as compliance
    passed, detail = compliance._check_program_exit_zero(project, command)
    assert passed, detail
    native = next(project.glob('reports/phase2/lint/native-elaboration-*/context.json'))
    context = json.loads(native.read_text())
    assert context['top'] == 'top' and context['defines'] == ['SYNTHESIS']
    assert context['files'] == [str(rtl / 'leaf.v'), str(rtl / 'top.v')]
    old = {p: p.read_bytes() for p in native.parent.iterdir()}
    (rtl / 'top.v').write_text(NATIVE_TOP.replace('assign result=source;', 'assign result=routed;'))
    passed, detail = compliance._check_program_exit_zero(project, command)
    assert not passed, detail
    # The consumer refuses overwriting the previous report. A retry has its
    # own destination, preserving both the earlier verdict and native proof.
    assert len(list(project.glob('reports/phase2/lint/native-elaboration-*/context.json'))) == 1
    retry = command.replace('rtl_hygiene.json', 'rtl_hygiene_retry.json')
    passed, detail = compliance._check_program_exit_zero(project, retry)
    assert not passed, detail
    assert len(list(project.glob('reports/phase2/lint/native-elaboration-*/context.json'))) == 2
    assert all(p.read_bytes() == value for p, value in old.items())


def test_native_rejects_rtl_changed_before_consumer(tmp_path):
    assert shutil.which('yosys'), 'native driver qualification requires Yosys'
    leaf = tmp_path / 'leaf.v'
    top = tmp_path / 'top.v'
    leaf.write_text(NATIVE_LEAF)
    top.write_text(NATIVE_TOP)
    design = lint._native_driver_view([leaf, top], 'top', [], ['ENABLE=1'], [], tmp_path)
    top.write_text(NATIVE_TOP.replace('leaf u_leaf', 'unknown u_leaf'))
    findings = lint.lint_file(top, design)
    assert any(f.rule == 'native-elaboration-unresolved' and f.block_eligible for f in findings)
    assert any(f.rule == 'instance-driver-analysis-unresolved' for f in findings)


@pytest.fixture
def selected_native_target(tmp_path, monkeypatch):
    """PROGRAM_FIXTURE transport edge; its Yosys subprocess is real.

    Actual host-to-image CLI controls are separate evidence. This fixture does
    not claim that its substituted Docker boundary executed an image.
    """
    import _eda_image
    import librelane_contract
    for key in ('VIBEIC_EDA_IMAGE', 'IIC_EDA_IMAGE',
                librelane_contract.LOCAL_ATTESTATION_ENV):
        monkeypatch.delenv(key, raising=False)
    target = 'registry.invalid/neutral-tools@sha256:' + 'ac' * 32
    monkeypatch.setattr(_eda_image, 'local_digest',
                        lambda selected: ('sha256:' + 'ac' * 32, 'repo-digest', ''))
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        assert kw['supervised'] is True
        assert argv[argv.index(target) + 1] == '--skip'
        assert '-v' in argv and any(v.endswith(':ro') for v in argv)
        # Execute the producer's own image command in this test's EDA image.
        child = subprocess.run(argv[argv.index('--skip') + 1:],
                               capture_output=True, text=True, timeout=20)
        return subprocess.CompletedProcess(argv, child.returncode, child.stdout, child.stderr)
    monkeypatch.setattr(librelane_contract, 'run_container', run)
    return target, calls


def _selected_native_main(tmp_path, monkeypatch, source=NATIVE_TOP):
    leaf, top = tmp_path / 'leaf.v', tmp_path / 'top.v'
    leaf.write_text(NATIVE_LEAF)
    top.write_text(source)
    report = tmp_path / 'findings.json'
    monkeypatch.setattr(sys, 'argv', [str(PROGRAMS / 'rtl_hygiene_lint.py'),
        str(leaf), str(top), '--top', 'top', '--parameter', 'ENABLE=1',
        '--severity', 'ERROR', '--json', str(report)])
    rc = lint.main()
    context = json.loads(sorted(tmp_path.glob('native-elaboration-*/context.json'))[-1].read_text())
    return rc, json.loads(report.read_text()), context


@pytest.mark.parametrize('image_env', ['VIBEIC_EDA_IMAGE', 'IIC_EDA_IMAGE'])
def test_native_selected_image_runs_without_host_yosys(tmp_path, monkeypatch,
                                                      selected_native_target, image_env):
    target, calls = selected_native_target
    monkeypatch.setenv(image_env, target)
    def absent_host(*args, **kw):
        raise FileNotFoundError('neutral host has no Yosys')
    monkeypatch.setattr(lint._pr, 'run', absent_host)
    rc, findings, context = _selected_native_main(tmp_path, monkeypatch)
    assert rc == 0, context
    assert findings == [] and len(calls) == 1
    assert context['backend'] == 'docker' and context['image'] == target
    assert context['native_returncode'] == context['transport_returncode'] == 0
    assert context['native_process']['tool_path'] == shutil.which('yosys')
    assert context['native_process']['command'][:3] == ['yosys', '-Q', '-s']
    assert context['parameters'] == ['ENABLE=1'] and context['status'] == 'MEASURED'


@pytest.mark.parametrize('rejection', ['unavailable', 'missing_receipt', 'missing_tool', 'wrong_rc'])
def test_native_selected_target_failure_never_uses_available_host(tmp_path, monkeypatch,
                                                                selected_native_target, rejection):
    import _eda_image
    import librelane_contract
    target, calls = selected_native_target
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', target)
    if rejection == 'unavailable':
        monkeypatch.setattr(_eda_image, 'local_digest',
                            lambda selected: (None, '', 'neutral target missing'))
    else:
        def broken(argv, **kw):
            calls.append((argv, kw))
            if rejection in ('wrong_rc', 'missing_tool'):
                at = argv.index('--skip')
                receipt, command = Path(argv[at + 4]), argv[at + 5:]
                record = {'command': command, 'native_returncode': 1}
                if rejection == 'missing_tool':
                    record.update(native_returncode=None, launch_error='neutral image has no Yosys')
                receipt.write_text(json.dumps(record))
            return subprocess.CompletedProcess(argv, 127 if rejection == 'missing_tool' else 0, '', '')
        monkeypatch.setattr(librelane_contract, 'run_container', broken)
    rc, findings, context = _selected_native_main(tmp_path, monkeypatch)
    assert rc == 1, context
    assert context['status'] == 'NOT_MEASURED'
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    assert len(calls) == (0 if rejection == 'unavailable' else 1)
    if rejection == 'missing_tool':
        assert context['native_returncode'] is None and context['transport_returncode'] == 127


@pytest.mark.parametrize('source', [
    NATIVE_TOP.replace('leaf u_leaf', 'unknown u_leaf'),
    NATIVE_TOP.replace('.y(routed)', '.y()'),
    NATIVE_TOP.replace('leaf u_leaf(.a(source), .y(routed));', 'wire unused;'),
], ids=['unknown-child', 'missing-connection', 'undriven-wire'])
def test_native_selected_image_keeps_driver_negatives(tmp_path, monkeypatch,
                                                     selected_native_target, source):
    target, calls = selected_native_target
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', target)
    rc, findings, context = _selected_native_main(tmp_path, monkeypatch, source)
    assert rc == 1 and len(calls) == 1
    assert context['native_returncode'] == context['transport_returncode'] == 1
    assert context['status'] == 'NOT_MEASURED'
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    assert any(f['symbol'] == 'routed' and f['block_eligible'] for f in findings)


@pytest.mark.parametrize('matches', [True, False])
def test_native_selected_in_image_uses_existing_attestation(tmp_path, monkeypatch,
                                                          selected_native_target, matches):
    import librelane_contract
    target, calls = selected_native_target
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', target)
    monkeypatch.setenv(librelane_contract.LOCAL_ATTESTATION_ENV, '/neutral/launch_identity.json')
    def attest(selected):
        assert selected == target
        if not matches:
            raise librelane_contract.Refusal('LL_LOCAL_IMAGE_UNATTESTED', 'neutral image mismatch')
        return {'image': selected, 'image_id': 'sha256:' + 'ad' * 32}
    monkeypatch.setattr(librelane_contract, 'local_image_attestation', attest)
    rc, findings, context = _selected_native_main(tmp_path, monkeypatch)
    assert rc == (0 if matches else 1), context
    assert calls == []
    assert context.get('backend') == 'in-image'
    assert context['status'] == ('MEASURED' if matches else 'NOT_MEASURED')
    if matches:
        assert context['native_returncode'] == context['transport_returncode'] == 0
        assert findings == []
    else:
        assert context['native_returncode'] is None
        assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)


def test_native_relative_include_is_read_and_bound_to_current_source(tmp_path):
    include_dir = tmp_path / 'includes'
    include_dir.mkdir()
    header = include_dir / 'neutral.svh'
    header.write_text('`define INCLUDED_DRIVER leaf u_leaf(.a(source), .y(routed));\n')
    source = NATIVE_TOP.replace('wire routed;', '`include "neutral.svh"\nwire routed;')
    source = source.replace('leaf u_leaf(.a(source), .y(routed));', '`INCLUDED_DRIVER')
    args = ['--parameter', 'ENABLE=1', '--include-dir', str(include_dir)]
    good, findings = _native_lint_cli(tmp_path, source, args)
    assert good.returncode == 0, good.stdout + good.stderr
    assert findings == []
    context_path, = tmp_path.glob('native-elaboration-*/context.json')
    context = json.loads(context_path.read_text())
    import hashlib
    assert context['input_sha256'][str(header)] == hashlib.sha256(header.read_bytes()).hexdigest()
    old = {p: p.read_bytes() for p in context_path.parent.iterdir()}
    header.write_text('`define INCLUDED_DRIVER leaf u_leaf(.a(source), .y());\n')
    bad, findings = _native_lint_cli(tmp_path, source, args)
    assert bad.returncode == 1
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    current, = [p for p in tmp_path.glob('native-elaboration-*/context.json') if p != context_path]
    record = json.loads(current.read_text())
    assert record['input_sha256'][str(header)] == hashlib.sha256(header.read_bytes()).hexdigest()
    assert record['status'] == 'NOT_MEASURED'
    assert all(p.read_bytes() == value for p, value in old.items())


def test_native_missing_relative_include_is_not_a_clean_driver_result(tmp_path):
    include_dir = tmp_path / 'includes'
    include_dir.mkdir()
    source = NATIVE_TOP.replace('wire routed;', '`include "neutral.svh"\nwire routed;')
    result, findings = _native_lint_cli(tmp_path, source,
                                      ['--parameter', 'ENABLE=1', '--include-dir', str(include_dir)])
    assert result.returncode == 1
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    context = json.loads(next(tmp_path.glob('native-elaboration-*/context.json')).read_text())
    assert context['status'] == 'NOT_MEASURED'


def test_native_include_directory_with_whitespace_is_explicitly_unmeasured(tmp_path):
    include_dir = tmp_path / 'with space'
    include_dir.mkdir()
    (include_dir / 'neutral.svh').write_text('`define NEUTRAL_INCLUDE 1\n')
    result, findings = _native_lint_cli(tmp_path,
        extra=['--parameter', 'ENABLE=1', '--include-dir', str(include_dir)])
    assert result.returncode == 1
    assert any(f['rule'] == 'native-elaboration-unresolved' for f in findings)
    context = json.loads(next(tmp_path.glob('native-elaboration-*/context.json')).read_text())
    assert context['status'] == 'NOT_MEASURED' and 'whitespace' in context['reason']
    assert context['native_returncode'] is None and context['transport_returncode'] is None


def _undriven(source: str):
    findings = lint.rule_undriven_and_unread(
        lint.strip_comments(source), "fixture.sv")
    return sorted(f.symbol for f in findings if f.rule == "undriven-wire")


ANSI = """
module leaf #(parameter W = 8) (
    input logic [W-1:0] data_i,
    output logic [W-1:0] data_o
);
    assign data_o = data_i;
endmodule
"""


def test_parameterized_ansi_output_actual_is_a_driver():
    source = ANSI + """
module top(input logic [7:0] source, output logic [7:0] result);
    logic [7:0] routed;
    leaf #(.W(8)) u_leaf(source, routed);
    assign result = routed;
endmodule
"""
    assert _undriven(source) == []


def test_non_ansi_header_order_beats_declaration_order():
    source = """
module leaf(data_i, data_o);
    output data_o;
    input data_i;
    assign data_o = data_i;
endmodule
module top(input source, output result);
    wire routed;
    leaf u_leaf(source, routed);
    assign result = routed;
endmodule
"""
    assert _undriven(source) == []


def test_empty_positional_actual_keeps_later_output_position():
    source = ANSI + """
module top(input logic [7:0] source, output logic [7:0] result);
    logic [7:0] routed;
    leaf u_leaf(, routed);
    assign result = routed;
endmodule
"""
    assert _undriven(source) == []


def test_concatenated_output_actuals_are_each_driven():
    source = """
module leaf(input data_i, output [1:0] data_o);
    assign data_o = {data_i, data_i};
endmodule
module top(input source, output [1:0] result);
    wire hi, lo;
    leaf u_leaf(source, {hi, lo});
    assign result = {hi, lo};
endmodule
"""
    assert _undriven(source) == []


def test_positional_input_actual_does_not_count_as_a_driver():
    source = """
module leaf(input data_i, output data_o);
    assign data_o = data_i;
endmodule
module top(input source, output result);
    wire routed;
    leaf u_leaf(routed, result);
    assign result = routed;
endmodule
"""
    assert _undriven(source) == ["routed"]


def test_true_floating_wire_remains_an_error():
    source = """
module top(input source, output result);
    wire floating;
    assign result = source;
endmodule
"""
    assert _undriven(source) == ["floating"]


@pytest.mark.parametrize("connection", [
    "missing u(source, routed);",
    "leaf u(source, routed, extra);",
    "leaf u(source, routed[);",
    "leaf u(source, routed, .unexpected(extra));",
])
def test_unresolved_unsupported_and_out_of_range_forms_stay_conservative(connection):
    source = """
module leaf(input data_i, output data_o);
    assign data_o = data_i;
endmodule
module top(input source, output result);
    wire routed;
    wire extra;
    %s
    assign result = routed;
endmodule
""" % connection
    symbols = _undriven(source)
    assert "extra" in symbols or "routed" in symbols


def test_named_port_baseline_remains_clean():
    source = """
module leaf(input data_i, output data_o);
    assign data_o = data_i;
endmodule
module top(input source, output result);
    wire routed;
    leaf u_leaf(.data_i(source), .data_o(routed));
    assign result = routed;
endmodule
"""
    assert _undriven(source) == []


@pytest.mark.skipif(shutil.which("iverilog") is None or shutil.which("vvp") is None,
                    reason="native Icarus is supplied by the EDA image")
@pytest.mark.parametrize("style", ["positional", "named"])
def test_positional_and_named_wiring_simulate(style, tmp_path):
    connection = ("leaf u_leaf(source, routed);" if style == "positional"
                  else "leaf u_leaf(.data_i(source), .data_o(routed));")
    design = f"""
module leaf(input wire data_i, output wire data_o);
    assign data_o = data_i;
endmodule
module top(input wire source, output wire result);
    wire routed;
    {connection}
    assign result = routed;
endmodule
"""
    tb = """
module tb;
    reg source;
    wire result;
    top dut(source, result);
    initial begin
        source = 1'b0;
        #1 if (result !== 1'b0) $fatal(1, "zero did not propagate");
        source = 1'b1;
        #1 if (result !== 1'b1) $fatal(1, "one did not propagate");
        $finish;
    end
endmodule
"""
    design_path = tmp_path / f"{style}.sv"
    tb_path = tmp_path / f"{style}_tb.sv"
    out_path = tmp_path / f"{style}.vvp"
    design_path.write_text(design)
    tb_path.write_text(tb)
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(out_path),
         str(design_path), str(tb_path)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(["vvp", str(out_path)],
                                capture_output=True, text=True)
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr


@pytest.mark.parametrize("boundary", ["generate", "always", "case", "preprocessor"])
@pytest.mark.parametrize("control", ["current", "absent", "duplicate", "malformed"])
def test_instance_after_closed_scope_keeps_real_output_driver(tmp_path, boundary, control):
    """A native elaboration control and the actual lexical/CLI consumer agree."""
    import json
    prefix = {
        "generate": "generate if (1) begin: selected assign anchor=source; end: selected endgenerate",
        "always": "always @(*) begin anchor=source; end",
        "case": "always @(*) begin case (source) 1'b0: anchor=1'b0; default: anchor=1'b1; endcase end",
        "preprocessor": "`ifdef FEATURE\ngenerate if (1) begin: selected assign anchor=source; end endgenerate\n`else\nassign anchor=source;\n`endif",
    }[boundary]
    connection = ".data_i(anchor), .data_o(routed)"
    if control == "duplicate":
        connection += ", .data_o(other)"
    elif control == "malformed":
        connection += ", .broken(routed) trailing"
    instance = f"leaf #(.W(8)) u_leaf({connection});" if control != "absent" else ""
    source = ANSI + f"""
module top(input wire source, output wire [7:0] result);
    {'wire' if boundary in ('generate', 'preprocessor') else 'reg'} anchor;
    wire [7:0] routed;
    wire [7:0] other;
    {prefix}
    {instance}
    assign result=routed;
endmodule
"""
    fp=tmp_path/'input.sv';fp.write_text(source)
    # Every configured preprocessor arm is independently checked by the tool.
    if control == "current":
        assert shutil.which("yosys"), "EDA image must supply the native control"
        script = f"read_verilog -sv {'-DFEATURE' if boundary == 'preprocessor' else ''} {fp}; hierarchy -check -top top; proc; check -assert; write_json {tmp_path}/native.json"
        native = subprocess.run(['yosys','-Q','-p',script],capture_output=True,text=True)
        (tmp_path/'native.log').write_text(native.stdout+native.stderr)
        assert native.returncode == 0, native.stdout+native.stderr
        elaborated=json.loads((tmp_path/'native.json').read_text())['modules']['top']
        assert elaborated['cells']['u_leaf']['port_directions']['data_o']=='output'
        assert elaborated['cells']['u_leaf']['connections']['data_o']==elaborated['netnames']['routed']['bits']
        assert lint.collect_instance_connections(source).get('routed') == 'data_o'
        assert 'routed' not in _undriven(source)
        parsed=lint._module_ports.parse_modules(lint._module_ports.strip_preproc_directives(source),str(fp))
        child=next(i for m in parsed if m.name=='top' for i in m.instances if i.instance_name=='u_leaf')
        assert child.line==source[:source.index(instance)].count('\n')+1
    else:
        assert 'routed' in _undriven(source)
    # Assert the actual public CLI report, preserving unrelated unused-wire findings.
    report=tmp_path/'hygiene.json'
    run=subprocess.run([sys.executable,str(PROGRAMS/'rtl_hygiene_lint.py'),str(fp),
                        '--severity','ERROR','--json',str(report)],capture_output=True,text=True)
    findings=json.loads(report.read_text())
    assert any(f['rule']=='undriven-wire' and f['symbol']=='routed' for f in findings)==(control!='current')
    assert fp.read_text()==source


@pytest.mark.parametrize("event", ["@(*)", "@ (*)", "@ ( * )"])
def test_event_wildcard_keeps_discovery_and_real_attributes(event):
    source = ANSI + f"""
module top(input [7:0] source, output [7:0] result);
    reg [7:0] sampled;
    wire [7:0] routed;
    always {event} begin sampled=source; end
    (* keep = 1, description = "endgenerate" *) leaf u_leaf(sampled, routed);
    assign result=routed;
endmodule
"""
    masked=lint._module_ports.lexical_mask(source, attributes=True)
    assert event in masked
    assert 'description' not in masked
    assert len(masked)==len(source)
    assert masked.count('\n')==source.count('\n')
    assert 'routed' not in _undriven(source)


@pytest.mark.parametrize("branch", ["generate", "preprocessor"])
def test_unselected_conditional_child_is_not_credited_as_an_active_driver(tmp_path, branch):
    import json
    import rtl_review_aggregate as A
    inside="leaf u_leaf(.data_i(source), .data_o(routed));"
    region=(f"generate if (ENABLE) begin: maybe wire [7:0] unused; {inside} end endgenerate"
            if branch=='generate' else f"`ifdef FEATURE\n{inside}\n`endif")
    source=ANSI+f"""
module top #(parameter ENABLE=0)(input [7:0] source, output [7:0] result);
    wire [7:0] routed;
    {region}
    assign result=routed;
endmodule
"""
    fp=tmp_path/'conditional.sv';fp.write_text(source)
    findings=lint.rule_undriven_and_unread(source,str(fp))
    f=next(f for f in findings if f.symbol=='routed')
    assert f.rule=='instance-driver-analysis-unresolved'
    assert f.severity=='ERROR' and f.block_eligible
    assert 'NOT_MEASURED' in f.message
    assert 'routed' not in lint.collect_instance_connections(source)
    assert A.HYGIENE_RULE_CATEGORY[f.rule]=='correctness_smells'
    native=subprocess.run(['yosys','-Q','-p',f'read_verilog -sv {fp}; hierarchy -check -top top; proc; check -assert'],capture_output=True,text=True)
    assert native.returncode!=0, native.stdout+native.stderr
    report=tmp_path/'hygiene.json'
    cli=subprocess.run([sys.executable,str(PROGRAMS/'rtl_hygiene_lint.py'),str(fp),'--severity','ERROR','--json',str(report)],capture_output=True,text=True)
    assert cli.returncode==1
    actual=json.loads(report.read_text())
    assert [(f['rule'],f['symbol'],f['severity']) for f in actual] == [
        ('undriven-wire','routed','ERROR')]
    assert actual[0]['block_eligible']
    from rtl_hierarchy_drivers import DriverContext
    context=DriverContext([fp],lint._procedural_statement_end,lint.collect_lhs_set)
    body,drivers,connections,problems=context.drivers('top')
    assert problems==[]
    assert 'routed' not in drivers and 'routed' not in connections
    assert not lint._module_ports.parse_instantiations(body,'top',1)
    assert '.data_o(routed)' in source
    consumed=A._load_hygiene_findings(report,cli.returncode,cli.stderr)
    assert any(f.rule_id=='undriven-wire' and "'routed'" in f.message
               and f.severity=='ERROR' and f.category=='correctness_smells' for f in consumed)


@pytest.mark.parametrize("enabled", [0, 1])
def test_first_generate_child_is_discovered_without_guessing_activation(tmp_path, enabled):
    import json
    source=ANSI+f"""
module top #(parameter ENABLE={enabled})(input [7:0] source, output [7:0] result);
    wire [7:0] routed;
    generate if (ENABLE) begin: optional
        leaf u_leaf(.data_i(source), .data_o(routed));
    end endgenerate
    assign result=routed;
endmodule
"""
    fp=tmp_path/'first.sv';fp.write_text(source)
    native=subprocess.run(['yosys','-Q','-p',f'read_verilog -sv {fp}; hierarchy -check -top top; proc; check -assert; write_json {tmp_path}/native.json'],capture_output=True,text=True)
    (tmp_path/'native.log').write_text(native.stdout+native.stderr)
    assert (native.returncode==0)==bool(enabled), native.stdout+native.stderr
    mods=lint._module_ports.parse_modules(source,str(fp))
    parent=next(m for m in mods if m.name=='top')
    child=next(i for i in parent.instances if i.instance_name=='u_leaf')
    assert child.module_name=='leaf'
    assert child.line==source[:source.index('leaf u_leaf')].count('\n')+1
    findings=lint.rule_undriven_and_unread(source,str(fp))
    f=next(f for f in findings if f.symbol=='routed')
    assert f.rule=='instance-driver-analysis-unresolved'
    assert f.severity=='ERROR' and f.block_eligible
    assert 'routed' not in lint.collect_instance_connections(source)
    assert fp.read_text()==source


def _native_hierarchy(tmp_path, sources):
    paths = []
    for number, source in enumerate(sources):
        path = tmp_path / f"unit_{number}.sv"
        path.write_text(source)
        paths.append(path)
    report = tmp_path / "findings.json"
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
         *map(str, paths), "--strict", "--severity", "ERROR", "--json", str(report)],
        capture_output=True, text=True)
    findings = json.loads(report.read_text()) if report.exists() else []
    return result, findings


LEAF = """
module leaf(input data_i, output data_o);
    assign data_o = data_i;
endmodule
"""


@pytest.mark.parametrize("style", ["named", "positional", "implicit", "wildcard"])
def test_native_cross_file_child_after_generate_is_a_driver(tmp_path, style):
    connection = {
        "named": ".data_i(source), .data_o(routed)",
        "positional": "source, routed",
        "implicit": ".data_i, .data_o",
        "wildcard": ".*",
    }[style]
    signal = "data_o" if style in {"implicit", "wildcard"} else "routed"
    source = f"""
module top(input source, input data_i, output result);
    wire {signal};
    generate if (0) begin : unused
        assign result = source;
    end endgenerate
    leaf u_leaf({connection});
    assign result = {signal};
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


@pytest.mark.parametrize("connection,expected", [
    ("leaf u_leaf(.data_i(routed), .data_o(result));", [("undriven-wire", "routed")]),
    ("leaf u_leaf(routed, result);", [("undriven-wire", "routed")]),
    ("absent u_leaf(.data_i(source), .data_o(routed));",
     [("undriven-wire", "routed"), ("hierarchy-port-resolution", "u_leaf")]),
    ("leaf u_leaf(.data_i(source), .wrong(routed));",
     [("undriven-wire", "routed"), ("hierarchy-port-resolution", "u_leaf")]),
    ("leaf u_leaf(.data_i(source), .data_o(routed), .wrong(result));",
     [("hierarchy-port-resolution", "u_leaf")]),
    ("leaf u_leaf(.data_o(routed), .data_o(result));",
     [("undriven-wire", "routed"), ("hierarchy-port-resolution", "u_leaf")]),
    ("leaf u_leaf(source, routed, result);",
     [("undriven-wire", "routed"), ("hierarchy-port-resolution", "u_leaf")]),
    ("leaf u_leaf(.data_i(source), .data_o(source & routed));",
     [("undriven-wire", "routed"), ("hierarchy-port-resolution", "u_leaf")]),
])
def test_native_invalid_bindings_and_input_actuals_still_block(tmp_path, connection, expected):
    source = """
module top(input source, output result);
    wire routed;
    %s
    assign result = routed;
endmodule
""" % connection
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [(f["rule"], f["symbol"]) for f in findings] == expected
    assert all(f["severity"] == "ERROR" and f["block_eligible"] for f in findings)
    import rtl_review_aggregate as A
    consumed = A._load_hygiene_findings(tmp_path / "findings.json", result.returncode, result.stderr)
    assert [(f.rule_id, f.severity, f.category) for f in consumed] == [
        (rule, "ERROR", "correctness_smells") for rule, symbol in expected]


def test_native_width_mismatch_does_not_credit_an_output(tmp_path):
    source = """
module top(input source, output [3:0] result);
    wire [3:0] routed;
    leaf u_leaf(.data_i(source), .data_o(routed));
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == 1, result.stdout + result.stderr
    assert any("output width mismatch" in f["message"] for f in findings), findings


@pytest.mark.parametrize("enabled", [0, 1])
def test_native_conditional_driver_tracks_selected_parameter(tmp_path, enabled):
    source = f"""
module top #(parameter ENABLE = {enabled}) (input source, output result);
    wire routed;
    generate if (ENABLE) begin : enabled
        leaf u_leaf(.data_i(source), .data_o(routed));
    end endgenerate
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == (0 if enabled else 1), result.stdout + result.stderr
    assert [f["symbol"] for f in findings if f["rule"] == "undriven-wire"] == (
        [] if enabled else ["routed"])


def test_native_child_override_cannot_credit_an_inactive_driver(tmp_path):
    child = """
module leaf #(parameter ENABLE = 1) (input data_i, output data_o);
    generate if (ENABLE) begin : enabled
        assign data_o = data_i;
    end endgenerate
endmodule
"""
    source = """
module top(input source, output result);
    wire routed;
    leaf #(.ENABLE(0)) u_leaf(.data_i(source), .data_o(routed));
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, child])
    assert result.returncode == 1, result.stdout + result.stderr
    assert any("not driven in selected configuration" in f["message"] for f in findings), findings


def test_native_inactive_unknown_child_is_absent(tmp_path):
    source = """
module top #(parameter ENABLE = 0) (input source, output result);
    generate if (ENABLE) begin : enabled
        absent u_leaf(.data_o(result));
    end else begin : disabled
        assign result = source;
    end endgenerate
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


def test_native_unresolved_generate_condition_is_rejected(tmp_path):
    source = """
module top #(parameter ENABLE = unknown_fn(1)) (input source, output result);
    generate if (ENABLE) begin : enabled
        assign result = source;
    end endgenerate
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [(f["rule"], f["symbol"], f["severity"]) for f in findings] == [
        ("hierarchy-port-resolution", "top", "ERROR")]
    assert "unresolved generate condition" in findings[0]["message"]


def test_native_same_named_sibling_wire_still_has_no_driver(tmp_path):
    source = """
module first(input source, output result);
    wire routed;
    assign routed = source;
    assign result = routed;
endmodule
module second(input source, output result);
    wire routed;
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [f["symbol"] for f in findings if f["rule"] == "undriven-wire"] == ["routed"]


def test_native_sensitivity_wildcard_is_not_an_attribute(tmp_path):
    source = """
module leaf(input data_i, output reg data_o);
    always @ (*) data_o = data_i;
endmodule
module top(input source, output result);
    leaf u_leaf(.data_i(source), .data_o(result));
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


def test_native_initialized_output_is_in_the_formal_port_census(tmp_path):
    source = """
module leaf(output reg data_o = 1'b0);
    initial data_o = 1'b0;
endmodule
module top(output result);
    leaf u_leaf(.data_o(result));
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


def test_native_default_preprocessor_selection_removes_inactive_ports(tmp_path):
    source = """
module top(input source, output result
`ifdef EXTRA
    , output optional_result
`endif
);
    assign result = source;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


@pytest.mark.parametrize("declaration,override", [
    ("parameter [0:0] ENABLE = 2", ""),
    ("parameter [0:0] ENABLE = 1", "#(.ENABLE(2))"),
])
def test_native_parameter_width_truncation_selects_the_inactive_driver(tmp_path, declaration, override):
    child = f"""
module leaf #({declaration}) (input data_i, output data_o);
    generate if (ENABLE) begin : enabled
        assign data_o = data_i;
    end endgenerate
endmodule
"""
    source = f"""
module top(input source, output result);
    wire routed;
    leaf {override} u_leaf(.data_i(source), .data_o(routed));
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, child])
    assert result.returncode == 1, result.stdout + result.stderr
    assert any("not driven in selected configuration" in f["message"] for f in findings), findings


@pytest.mark.parametrize("complete", [False, True])
def test_native_partial_child_output_only_credits_covered_bits(tmp_path, complete):
    source = """
module top(input source, output [1:0] result);
    wire [1:0] routed;
    leaf u_low(.data_i(source), .data_o(routed[0]));
    %s
    assign result = routed;
endmodule
""" % ("leaf u_high(.data_i(source), .data_o(routed[1]));" if complete else "")
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == (0 if complete else 1), result.stdout + result.stderr
    assert [f["symbol"] for f in findings if f["rule"] == "undriven-wire"] == (
        [] if complete else ["routed"])


@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("statement", [
    "assign routed = source;",
    "leaf u_leaf(.data_i(source), .data_o(routed));",
])
def test_native_implicit_generate_tracks_selected_driver(tmp_path, enabled, statement):
    source = f"""
module top #(parameter ENABLE = {enabled})(input source, output result);
    wire routed;
    if (ENABLE) {statement}
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == (0 if enabled else 1), result.stdout + result.stderr
    assert [(f["rule"], f["symbol"], f["severity"]) for f in findings] == (
        [] if enabled else [("undriven-wire", "routed", "ERROR")])


def test_native_unknown_output_width_is_rejected(tmp_path):
    source = """
module top(input source, output [1:0] result);
    wire [1:0] routed;
    leaf u_leaf(.data_i(source), .data_o(routed));
    assign result = routed;
endmodule
"""
    child = """
module leaf(input data_i, output [opaque(1):0] data_o);
    assign data_o = {data_i, data_i};
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, child])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [(f["rule"], f["symbol"], f["severity"]) for f in findings] == [
        ("undriven-wire", "routed", "ERROR"),
        ("hierarchy-port-resolution", "u_leaf", "ERROR")]
    assert "unresolved output width: data_o" in findings[1]["message"]


def test_native_unsupported_instance_array_discovery_is_rejected(tmp_path):
    source = """
module top(input source, output result);
    leaf u_leaf[1:0](.data_i(source), .data_o());
    assign result = source;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [(f["rule"], f["symbol"], f["severity"]) for f in findings] == [
        ("hierarchy-port-resolution", "u_leaf", "ERROR")]
    assert "unsupported instance array" in findings[0]["message"]


@pytest.mark.parametrize("declarations,condition", [
    ("parameter ENABLE=8'hff+8'h1", "ENABLE"),
    ("parameter A=2, B=1", "!A == B"),
    ("parameter A=1'sb1, B=1'b0", "A < B"),
    ("parameter [7:0] A=8'hff", "A+1'b1"),
    ("parameter A=8'hff", "A+1'b1"),
    ("parameter [7:0] A=0, B=255", "B+1'b1"),
    ('parameter A="AA"', 'A < "B"'),
    ("parameter A=1", "A[64] == 0"),
    ("parameter A=8'hff", "A[0] > -1"),
    ("parameter A=1", "(A == A) > -1"),
    ("parameter A=0, B=!A", "B > -1"),
    ("parameter A=1, B=|A", "B > -1"),
    ("parameter A=1, B=(A && A)", "B > -1"),
    ("parameter A=1", "'0 > -1"),
])
def test_native_unsafe_constant_semantics_never_credit_a_driver(tmp_path, declarations, condition):
    source = f"""
module top #({declarations})(input source, output result);
    wire routed;
    generate if ({condition}) begin: selected
        leaf u_leaf(.data_i(source), .data_o(routed));
    end endgenerate
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert result.returncode == 1, result.stdout + result.stderr
    assert [(f["rule"], f["symbol"], f["severity"]) for f in findings] == [
        ("hierarchy-port-resolution", "top", "ERROR")]
    assert findings[0]["block_eligible"]
    assert "unresolved generate condition" in findings[0]["message"]


@pytest.mark.parametrize("declarations,condition", [
    ("parameter integer A=2, B=1", "A > B"),
    ("parameter [0:0] A=1'b0", "A*4 == 0"),
])
def test_native_bounded_integer_and_vector_arithmetic_remains_resolved(tmp_path, declarations, condition):
    source = f"""
module top #({declarations})(input source, output result);
    wire routed;
    generate if ({condition}) begin: selected
        leaf u_leaf(.data_i(source), .data_o(routed));
    end endgenerate
    assign result = routed;
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source, LEAF])
    assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


@pytest.mark.parametrize("datatype,value,condition,expected_rc", [
    ("bit", "1", "ENABLE", 0),
    ("bit", "0", "ENABLE", 1),
    ("bit", "2", "ENABLE", 1),
    ("logic", "2", "ENABLE", 1),
    ("byte", "256", "ENABLE", 1),
    ("byte", "255", "ENABLE >= 0", 1),
    ("logic", "1", "ENABLE", 0),
    ("reg", "1", "ENABLE", 0),
    ("reg", "2", "ENABLE", 1),
    ("bit signed", "1", "ENABLE", 0),
    ("byte", "255", "ENABLE", 0),
    ("byte unsigned", "255", "ENABLE", 0),
    ("shortint", "1", "ENABLE", 0),
    ("shortint", "65536", "ENABLE", 1),
    ("longint", "1", "ENABLE", 0),
    ("longint", "18446744073709551616", "ENABLE", 1),
    ("time", "1", "ENABLE", 0),
    ("time", "18446744073709551616", "ENABLE", 1),
    ("logic [3:0]", "16", "ENABLE", 1),
    ("logic [1:0][1:0]", "16", "ENABLE", 1),
], ids=["bit1", "bit0", "bit2", "logic2", "byte256", "signedbyte255",
        "logic1", "reg1", "reg2", "signedbit1", "signedbyte255_truth",
        "unsignedbyte255", "shortint1", "shortint65536", "longint1",
        "longint_overflow", "time1", "time_overflow", "logic_vector16",
        "logic_multidimension16"])
def test_native_typed_parameter_child_driver_matches_yosys(
        tmp_path, datatype, value, condition, expected_rc):
    """The same child source must not gain credit from untruncated Python ints."""
    source = f"""
module leaf #(parameter {datatype} ENABLE={value})(input source, output result);
    generate if ({condition}) begin: selected
        assign result = source;
    end endgenerate
endmodule
module top(input source, output result);
    leaf u_leaf(.source(source), .result(result));
endmodule
"""
    _check_typed_driver_source(tmp_path, source, expected_rc)


def _check_typed_driver_source(tmp_path, source, expected_rc):
    assert shutil.which("yosys"), "typed-driver qualification requires native Yosys"
    result, findings = _native_hierarchy(tmp_path, [source])
    path = tmp_path / "unit_0.sv"
    native = subprocess.run(
        ["yosys", "-Q", "-T", "-p",
         # The built-in SystemVerilog frontend also parses time and packed
         # multidimensional parameters; read_verilog rejects those declarations.
         f"read_slang {path} --top top; hierarchy -check -top top; proc; flatten; check -assert"],
        capture_output=True, text=True)
    (tmp_path / "native-yosys.stdout").write_text(native.stdout)
    (tmp_path / "native-yosys.stderr").write_text(native.stderr)
    (tmp_path / "process-results.json").write_text(json.dumps({
        "native_yosys_process_rc": native.returncode,
        "hygiene_process_rc": result.returncode,
        "findings": findings,
    }, indent=2))
    assert native.returncode == expected_rc, native.stdout + native.stderr
    if expected_rc:
        assert "used but has no driver" in native.stdout
        assert result.returncode == 1, result.stdout + result.stderr
        assert any(f["severity"] == "ERROR" and f["block_eligible"] for f in findings)
    else:
        assert (result.returncode, findings) == (0, []), result.stdout + result.stderr


@pytest.mark.parametrize("declaration,body,condition", [
    ("parameter bit FIRST=1, ENABLE=2", "", "ENABLE"),
    ("parameter byte FIRST=1, ENABLE=256", "", "ENABLE"),
    ("parameter FIRST=1", "localparam logic ENABLE=2;", "ENABLE"),
    ("parameter unsigned ENABLE=-1", "", "ENABLE < 0"),
], ids=["inherited_bit", "inherited_byte", "body_localparam", "implicit_unsigned"])
def test_native_typed_parameter_declaration_context_stays_blocking(
        tmp_path, declaration, body, condition):
    source = f"""
module leaf #({declaration})(input source, output result);
    {body}
    generate if ({condition}) begin: selected
        assign result = source;
    end endgenerate
endmodule
module top(input source, output result);
    leaf u_leaf(.source(source), .result(result));
endmodule
"""
    _check_typed_driver_source(tmp_path, source, 1)


@pytest.mark.parametrize("datatype,value,condition", [
    ("bit", "2", "ENABLE"),
    ("logic", "2", "ENABLE"),
    ("byte", "256", "ENABLE"),
    ("byte", "255", "ENABLE >= 0"),
], ids=["bit2", "logic2", "byte256", "signedbyte255"])
def test_native_typed_child_override_is_converted_before_driver_credit(
        tmp_path, datatype, value, condition):
    source = f"""
module leaf #(parameter {datatype} ENABLE=1)(input source, output result);
    generate if ({condition}) begin: selected
        assign result = source;
    end endgenerate
endmodule
module top(input source, output result);
    leaf #(.ENABLE({value})) u_leaf(.source(source), .result(result));
endmodule
"""
    _check_typed_driver_source(tmp_path, source, 1)


@pytest.mark.parametrize("declaration", [
    "parameter unresolved_t ENABLE=2",
    "parameter real ENABLE=2",
    "parameter bit signed unsigned ENABLE=2",
    "parameter byte [1:0] ENABLE=2",
])
def test_native_unsupported_parameter_type_never_uses_python_integer_credit(
        tmp_path, declaration):
    source = f"""
module top #({declaration})(input source, output result);
    generate if (ENABLE) begin: selected
        assign result = source;
    end endgenerate
endmodule
"""
    result, findings = _native_hierarchy(tmp_path, [source])
    assert result.returncode == 1, result.stdout + result.stderr
    assert any(f["rule"] == "hierarchy-port-resolution" and
               f["severity"] == "ERROR" and f["block_eligible"] for f in findings)


def _machine_grammar_context(tmp_path, source):
    from rtl_hierarchy_drivers import DriverContext
    path = tmp_path / 'grammar.sv'
    path.write_text(source)
    return DriverContext([path], lint._procedural_statement_end, lint.collect_lhs_set)


@pytest.mark.parametrize('body,expected', [
    ('leaf u_leaf(.a(source), .y(routed));', True),
    ('generate if (!ENABLE) begin: disabled '
     'leaf u_leaf(.a(source), .y(routed)); end endgenerate', False),
    ('// Do not credit leaf u_leaf(.a(source), .y(routed));\n'
     '/* assign routed = source; is denied commentary, not RTL. */', False),
])
def test_hierarchy_machine_grammar_driver_credit(tmp_path, body, expected):
    source = ('module leaf(input a, output y); assign y=a; endmodule\n'
              'module top #(parameter ENABLE=1)(input source, output result);\n'
              'wire routed;\n' + body + '\nassign result=routed; endmodule\n')
    context = _machine_grammar_context(tmp_path, source)
    _body, driven, connections, problems = context.drivers('top')
    assert problems == []
    assert ('routed' in driven) == expected
    assert connections == ({'routed': 'y'} if expected else {})
    assert ('u_leaf' in _body) == expected


@pytest.mark.parametrize('source,stage,reason', [
    ('The output is driven by leaf u_leaf(.a(source), .y(routed));\n'
     'parameter ENABLE=1; assign routed=source;\n', 'discovery', 'no safely parsed module'),
    ('Do not drive routed: leaf u_leaf(.a(source), .y(routed));\n'
     'Do not use parameter ENABLE=1 or assign routed=source;\n',
     'discovery', 'no safely parsed module'),
    ('module top #(parameter ENABLE=unknown_fn(1))(input source, output result);\n'
     'generate if (ENABLE) begin: unresolved assign result=source; '
     'end endgenerate endmodule\n', 'selection', 'unresolved generate condition'),
])
def test_hierarchy_machine_grammar_refuses_prose_and_unknown(tmp_path, source, stage, reason):
    with pytest.raises(ValueError, match=reason):
        context = _machine_grammar_context(tmp_path, source)
        assert stage == 'selection'
        context.drivers('top')


@pytest.mark.parametrize('value', [0, 1])
def test_hierarchy_machine_grammar_parameter_declarations(tmp_path, value):
    from rtl_hierarchy_drivers import resolve_parameters
    source = f'''module leaf(input a, output y); assign y=a; endmodule
module top #(parameter ENABLE={value})(input source, output result);
wire routed;
// Do not infer localparam SELECT=1; or parameter GHOST=1;
/* parameter ENABLE=1; localparam GHOST=1; are prose examples. */
localparam SELECT=ENABLE;
generate if (SELECT) begin: selected
leaf u_leaf(.a(source), .y(routed));
end endgenerate
assign result=routed;
endmodule
'''
    context = _machine_grammar_context(tmp_path, source)
    expressions = context.regions['top'].expressions
    assert expressions == {'ENABLE': (str(value), '', False),
                           'SELECT': ('ENABLE', '', False)}
    assert resolve_parameters(expressions) == {'ENABLE': value, 'SELECT': value}
    _body, driven, connections, problems = context.drivers('top')
    assert problems == []
    assert ('routed' in driven) == bool(value)
    assert connections == ({'routed': 'y'} if value else {})

"""Conservative positional-port driver resolution for ``rtl_hygiene_lint``.

The parser is shared with ``module_port_audit``.  These fixtures are neutral,
compile-shaped RTL and exercise the actual linter consumer: only a resolved
same-file child output/inout formal may credit a parent actual as driven.
"""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import json

PROGRAMS = Path(__file__).resolve().parents[1]
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
    assert any(f['rule']=='instance-driver-analysis-unresolved' and f['symbol']=='routed'
               for f in json.loads(report.read_text()))
    consumed=A._load_hygiene_findings(report,cli.returncode,cli.stderr)
    assert any(f.rule_id=='instance-driver-analysis-unresolved' and "'routed'" in f.message
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

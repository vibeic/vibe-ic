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

PROGRAMS = Path(os.environ.get(
    "VIBEIC_HYGIENE_PROGRAMS_DIR", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as lint  # noqa: E402


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

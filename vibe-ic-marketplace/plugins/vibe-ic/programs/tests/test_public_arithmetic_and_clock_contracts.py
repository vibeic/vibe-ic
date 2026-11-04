"""Public parameter, branch-sign and edge-phase contracts on neutral designs."""
import re
import subprocess

import pytest

import arithmetic_synth as arithmetic
import canonical_primitive_synth as clocks
import deterministic_emit_chain as chain
from _prose_handoff_assertions import assert_program_chain_candidate


def native(tmp_path, rtl, tb):
    src = tmp_path / "design.sv"
    bench = tmp_path / "check.sv"
    src.write_text(rtl)
    bench.write_text(tb)
    result = subprocess.run(
        ["iverilog", "-g2012", "-s", "check", "-o", str(tmp_path / "sim"),
         str(src), str(bench)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(["vvp", str(tmp_path / "sim")],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "CHECK_PASS" in result.stdout, result.stdout + result.stderr


def alu_prompt(lower=False):
    names = ["ADD", "XOR", "AND", "OR"]
    if lower:
        names = [x.title() for x in names]
    return ("Design an ALU.\nModule name:\n operator_unit\n"
            "Input ports:\n a[31:0]: Operand.\n b[31:0]: Operand.\n"
            " control[3:0]: Operation selection.\nOutput ports:\n result[31:0]: Result.\n"
            + "\n".join(f"parameter {n} = 4'd{i};" for i, n in enumerate(names))
            + "\nThe operation parameters are configurable. ADD adds, XOR is bitwise xor, "
              "AND is bitwise and, OR is bitwise or.\n")


@pytest.mark.parametrize("lower", [False, True])
def test_public_opcode_override_reaches_normal_emit_chain_and_native_tool(tmp_path, lower):
    prompt = alu_prompt(lower)
    result = chain.try_emit_ex(prompt, top="operator_unit")
    assert_program_chain_candidate(result, prompt)
    parameter = "Add" if lower else "ADD"
    rtl = result[1]
    assert rtl == arithmetic.synth(prompt, top="operator_unit")
    native(tmp_path, rtl, f'''module check;
reg [31:0] a=7,b=9; reg [3:0] control=12; wire [31:0] result;
operator_unit #(.{parameter}(4'd12)) d(a,b,control,result);
initial begin #1; if(result!==16) begin $display("CHECK_FAIL override %h",result); $fatal; end
control=1; #1; if(result!==(7^9)) $fatal;
$display("CHECK_PASS"); $finish; end endmodule''')


def test_combinational_alu_evaluates_declaration_initialized_inputs(tmp_path):
    rtl = arithmetic.synth(alu_prompt(), top="operator_unit")
    assert rtl
    native(tmp_path, rtl, '''module check;
reg [31:0] a=7,b=9; reg [3:0] control=0; wire [31:0] result;
operator_unit d(a,b,control,result);
initial begin #1; if(result!==16) begin $display("CHECK_FAIL initial %h",result); $fatal; end
$display("CHECK_PASS"); $finish; end endmodule''')


def sequential_multiplier_prompt(width, gated=False):
    condition = "start is active and " if gated else ""
    return ("Implement an unsigned shift and accumulate multiplier.\nModule name:\n accumulate_unit\n"
            "Input ports:\n clk: Clock.\n rst_n: Active-low reset.\n start: Enable.\n"
            f" a[{width-1}:0]: Multiplicand.\n b[{width-1}:0]: Multiplier.\n"
            f"Output ports:\n product[{2*width-1}:0]: Product.\n done: Completion flag.\n"
            f"The shift count register (i) is less than {width+1} and increments while start is active.\n"
            "When start is inactive the counter is reset to 0. Reset clears all registers.\n"
            f"If {condition}the shift count register (i) is equal to {width}, done_r is set to 1.\n"
            f"If {condition}the shift count register (i) is equal to {width+1}, done_r is reset to 0.\n"
            + ("When start is inactive done_r is reset to 0.\n" if gated else "")
            + "While start is active, count 0 loads operands and clears the product; subsequent counts shift and accumulate.\n")


@pytest.mark.parametrize("width", [3, 5])
@pytest.mark.parametrize("gated", [False, True])
def test_completion_obeys_its_own_enable_condition(tmp_path, width, gated):
    prompt = sequential_multiplier_prompt(width, gated)
    result = chain.try_emit_ex(prompt, top="accumulate_unit")
    assert_program_chain_candidate(result, prompt)
    assert result[1] == arithmetic.synth(prompt, top="accumulate_unit")
    native(tmp_path, result[1], f'''module check;
reg clk=0,rst_n=1,start=0; reg [{width-1}:0] a=3,b=7;
wire [{2*width-1}:0] product; wire done; always #5 clk=~clk;
accumulate_unit d(.*);
task reset; begin @(negedge clk);rst_n=0;start=0;#1;if(done!==0 || product!==0)$fatal;
@(negedge clk);rst_n=1;end endtask
initial begin reset(); @(negedge clk);start=1;repeat({width})@(negedge clk);
start=0;@(negedge clk);if(done!==1'b{int(not gated)})$fatal(1,"completion suppressed on disable: %b",done);
@(negedge clk);if(done!==1'b{int(not gated)})$fatal;
reset();@(negedge clk);start=1;repeat({width+1})@(negedge clk);
if(done!==1 || product!==21)$fatal;@(negedge clk);if(done!==0)$fatal;
reset();$display("CHECK_PASS");$finish;end endmodule''')


@pytest.mark.parametrize("width", [3, 5])
@pytest.mark.parametrize("rule", ["equality", "literal_equality", "inactive_clear_only",
                                  "qualified_hold", "unqualified_raise"])
def test_explicit_completion_control_clauses(tmp_path, width, rule):
    prompt = sequential_multiplier_prompt(width, rule != "inactive_clear_only")
    inactive_clear = "When start is inactive done_r is reset to 0.\n"
    if rule in ("equality", "literal_equality"):
        qualifier = "start == 1" if rule == "equality" else "start === 1'b1"
        prompt = prompt.replace("start is active and", qualifier + " and")
    elif rule == "inactive_clear_only":
        prompt = prompt.replace(f"If the shift count register (i) is equal to {width+1}, done_r is reset to 0.\n", "") + inactive_clear
    else:
        prompt = prompt.replace(inactive_clear, "")
        if rule == "unqualified_raise":
            prompt = prompt.replace(f"If start is active and the shift count register (i) is equal to {width},",
                                    f"If the shift count register (i) is equal to {width},")
    completed = rule in ("inactive_clear_only", "qualified_hold")
    expected = int(rule in ("qualified_hold", "unqualified_raise"))
    result = chain.try_emit_ex(prompt, top="accumulate_unit")
    assert_program_chain_candidate(result, prompt)
    assert result[1] == arithmetic.synth(prompt, top="accumulate_unit")
    native(tmp_path, result[1], f'''module check;
reg clk=0,rst_n=1,start=0; reg [{width-1}:0] a=3,b=7;
wire [{2*width-1}:0] product; wire done; always #5 clk=~clk;
accumulate_unit d(.*);
initial begin @(negedge clk);rst_n=0;@(negedge clk);rst_n=1;
@(negedge clk);start=1;repeat({width+1 if completed else width})@(negedge clk);
if({int(completed)} && (done!==1 || product!==21))$fatal(1,"completion was not reached");
start=0;@(negedge clk);if(done!==1'b{expected})$fatal(1,"explicit completion control: got %b expected {expected}",done);
$display("CHECK_PASS");$finish;end endmodule''')


def test_multiplier_without_stated_completion_or_matching_datapath_declines():
    prompt = sequential_multiplier_prompt(5)
    assert arithmetic.synth(prompt.replace("is set to 1", "indicates completion")) is None
    assert arithmetic.synth(prompt.replace(" a[4:0]", " data[4:0]")) is None


def test_reserved_or_case_colliding_opcode_parameters_decline():
    reserved = alu_prompt(True).replace("parameter And", "parameter and")
    assert arithmetic.synth(reserved, top="operator_unit") is None
    collision = alu_prompt() + "parameter Add = 4'd8;\n"
    assert arithmetic.synth(collision, top="operator_unit") is None


def fixed_prompt(sign=None):
    custom = (f"If `a` is greater than `b`, the result is `a - b` and the MSB "
              f"of the result is set to {sign}.\n") if sign is not None else ""
    return ("Implement a parameterized fixed-point adder.\nModule name:\n signed_unit\n"
            "Input parameters: Q fractional bits; N total bits including sign.\n"
            "Input ports:\n a[N-1:0]: First operand.\n b[N-1:0]: Second operand.\n"
            "Output ports:\n c[N-1:0]: Result.\n"
            "Use N-bit result storage. With equal signs add magnitudes and retain "
            "the common sign. With different signs subtract the smaller magnitude "
            "from the larger and use the dominant operand sign unless explicitly "
            "overridden below. Equal opposite magnitudes produce zero.\n" + custom)


@pytest.mark.parametrize("sign", [0, 1, None])
def test_branch_sign_is_from_public_source_not_an_arithmetic_convention(tmp_path, sign):
    prompt = fixed_prompt(sign)
    result = chain.try_emit_ex(prompt, top="signed_unit")
    assert_program_chain_candidate(result, prompt)
    rtl = result[1]
    assert rtl == arithmetic.synth(prompt, top="signed_unit")
    a_sign = str(sign) if sign is not None else "a[4]"
    native(tmp_path, rtl, '''module check;
reg [4:0] a,b; wire [4:0] c; reg [4:0] expected; integer x,y,mag;
signed_unit #(.N(5),.Q(2)) d(a,b,c);
initial begin
for(x=0;x<32;x=x+1) for(y=0;y<32;y=y+1) begin
 a=x; b=y;
 if(a[4]==b[4]) begin mag=(x%16+y%16)%16; expected={a[4],4'b0}|mag; end
 else if(x%16>y%16) begin mag=x%16-y%16; expected=(''' + a_sign + '''<<4)|mag; end
 else if(y%16>x%16) begin mag=y%16-x%16; expected={b[4],4'b0}|mag; end
 else expected=0;
 #1; if(c!==expected) begin $display("CHECK_FAIL %h %h actual=%h expected=%h",a,b,c,expected); $fatal; end
end
$display("CHECK_PASS"); $finish; end endmodule''')


def test_conflicting_branch_sign_declarations_decline():
    prompt = fixed_prompt(0) + "If a is greater than b, the result sign bit is set to 1.\n"
    assert arithmetic.synth(prompt, top="signed_unit") is None


def odd_prompt(phase="post", default=5, module="phase_unit"):
    phase_line = ("After each counter wraps to 0, its corresponding divider output "
                  "starts a new high interval on that clock edge.\n" if phase == "post" else
                  "Decode the current counter value before incrementing; the divider "
                  "output is low on the counter wrap edge.\n")
    return (f"Module name:\n {module}\nA frequency divider by odd numbers.\n"
            "Input ports:\n clk: Input clock.\n rst_n: Active low reset.\n"
            "Output ports:\n clk_div: Divided clock.\n"
            f"The parameter NUM_DIV defaults to {default}.\n"
            "Two counters track rising and falling edges, count from 0 to NUM_DIV-1 "
            "and wrap to 0. Each divider output is high during the first half and "
            "low during the remaining values, using integer truncation.\n"
            + phase_line +
            "Logically OR the two divided outputs. The active low reset "
            "asynchronously initializes counters to 0 and divider outputs to 1.\n")


@pytest.mark.parametrize("phase", ["post", "pre"])
def test_declared_clock_phase_has_an_independent_edge_model(tmp_path, phase):
    desc = odd_prompt(phase)
    rtl = clocks.emit_rtl("odd_clock_divider", desc)
    # Resolve the emitted name so the baseline native control observes phase,
    # separately from the ordinary-caller identity test below.
    module = re.search(r"(?m)^module\s+(\w+)", rtl).group(1)
    new_phase = 1 if phase == "post" else 0
    native(tmp_path, rtl, f'''`timescale 1ns/1ps
module check;
reg clk=0,rst_n=1; wire divided; integer p=0,n=0,k; reg hp=1,hn=1;
{module} #(.NUM_DIV(5)) d(clk,rst_n,divided);
initial begin #1; rst_n=0; #1; rst_n=1;
for(k=0;k<100;k=k+1) begin
 #4; clk=~clk;
 if(clk) begin
  if({new_phase}) begin p=(p+1)%5; hp=(p<2); end
  else begin hp=(p==4)?0:(p<2); p=(p+1)%5; end
 end else begin
  if({new_phase}) begin n=(n+1)%5; hn=(n<2); end
  else begin hn=(n==4)?0:(n<2); n=(n+1)%5; end
 end
 #1; if(divided!==(hp|hn)) begin $display("CHECK_FAIL phase edge=%0d",k); $fatal; end
end
$display("CHECK_PASS"); $finish; end endmodule''')


def test_ordinary_runner_publishes_neutral_module_and_source_default(tmp_path):
    import design_one_shot_runner as runner
    project = tmp_path / "project"
    doc = project / "phase1/input_doc/design_description.txt"
    doc.parent.mkdir(parents=True)
    doc.write_text(odd_prompt(default=7))
    result = runner._try_canonical_primitive_rtl(project, 0.0)
    assert result is not None and result.status == "PASS"
    rtl = project / "phase2/stage1/rtl/phase_unit.v"
    assert rtl.is_file()
    text = rtl.read_text()
    assert "module phase_unit" in text
    assert re.search(r"parameter\s+NUM_DIV\s*=\s*7\b", text)
    assert clocks.module_of_shape("odd_clock_divider", doc.read_text()) == "phase_unit"
    # The ordinary publisher must keep a pre-existing author's file.
    assert runner._try_canonical_primitive_rtl(project, 0.0) is None
    assert rtl.read_text() == text


def test_conflicting_clock_phase_is_not_silently_selected():
    desc = odd_prompt("post") + "Decode the current counter value before incrementing; output is low on the counter wrap edge.\n"
    assert clocks.detect_shape(desc) is None


@pytest.mark.parametrize("default", [0, 2, 4])
def test_unsupported_even_or_empty_odd_period_does_not_emit(default):
    assert clocks.detect_shape(odd_prompt(default=default)) is None


def test_unrelated_clock_ports_do_not_select_the_family():
    desc = odd_prompt().replace("divider by odd numbers", "event counter")
    assert clocks.detect_shape(desc) is None


@pytest.mark.parametrize("change", [
    lambda s: s.replace("starts a new high interval", "does not start a new high interval"),
    lambda s: s.replace("clk_div: Divided clock", "clk_div[3:0]: Divided clock"),
    lambda s: s.replace("rst_n: Active low reset.", "rst_n: Active low reset.\n enable: Enable."),
])
def test_negated_phase_or_unsupported_interface_does_not_emit(change):
    assert clocks.detect_shape(change(odd_prompt())) is None


def test_renamed_clock_roles_and_private_name_collision(tmp_path):
    desc = odd_prompt(default=7)
    for before, after in (("clk_div", "cnt1"), ("rst_n", "clear_n"), ("clk", "tick"), ("NUM_DIV", "PERIOD")):
        desc = re.sub(r"\b" + before + r"\b", after, desc)
    assert clocks.detect_shape(desc) == "odd_clock_divider"
    rtl = clocks.emit_rtl("odd_clock_divider", desc)
    native(tmp_path, rtl, """`timescale 1ns/1ps
module check;
reg tick=0,clear_n=1; wire q; integer p=0,n=0,k; reg hp=1,hn=1;
phase_unit d(.tick(tick),.clear_n(clear_n),.cnt1(q));
initial begin #1; clear_n=0; #1; clear_n=1;
for(k=0;k<100;k=k+1) begin
 #4; tick=~tick;
 if(tick) begin p=(p+1)%7; hp=(p<3); end
 else begin n=(n+1)%7; hn=(n<3); end
 #1; if(q!==(hp|hn)) $fatal;
end
$display("CHECK_PASS"); $finish; end endmodule""")


def test_contradictory_wrap_levels_decline():
    assert clocks.detect_shape(odd_prompt() + "The output is low on the counter wrap edge.") is None


def test_module_identity_does_not_alias_private_register(tmp_path):
    desc = odd_prompt(module="cnt1")
    rtl = clocks.emit_rtl("odd_clock_divider", desc)
    assert clocks.module_of_shape("odd_clock_divider", desc) == "cnt1"
    native(tmp_path, rtl, """module check;
reg clk=0,rst_n=1; wire q; cnt1 d(clk,rst_n,q);
initial begin #1; rst_n=0; #1; if(q!==1) $fatal;
$display("CHECK_PASS"); $finish; end endmodule""")


@pytest.mark.parametrize("change", [
    lambda s: s.replace("Logically OR", "Do not logically OR"),
    lambda s: s.replace("asynchronously initializes", "does not asynchronously initialize"),
    lambda s: s + "The reset is active high and synchronous.",
])
def test_negated_or_conflicting_architecture_declines(change):
    assert clocks.detect_shape(change(odd_prompt())) is None


def test_negated_literal_sign_assignment_declines():
    assert arithmetic.synth(fixed_prompt(0).replace("is set to", "must not be set to"), top="signed_unit") is None

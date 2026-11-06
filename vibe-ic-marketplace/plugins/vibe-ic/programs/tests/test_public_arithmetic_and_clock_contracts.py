"""Public parameter, branch-sign and edge-phase contracts on neutral designs."""
import re
import subprocess

import pytest

import arithmetic_synth as arithmetic
import general_synth as general
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
    project = tmp_path / "project"
    doc = project / "phase1/input_doc/design_description.txt"
    doc.parent.mkdir(parents=True)
    doc.write_text(odd_prompt(default=7))
    assert clocks.module_of_shape("odd_clock_divider", doc.read_text()) == "phase_unit"


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


def sequential_product_prompt(width, completion, qualified):
    guard = 'If start is high and the' if qualified is True else 'The'
    inactive = ('When start is low, done_r is reset to 0.' if qualified else
                'The completion register follows its separate counter predicates, independent of start.')
    return (f'Implement a {width}-bit unsigned sequential shift-and-accumulate multiplier.\n'
            'Module name:\n product_unit\nInput ports:\n clk: Clock.\n rst: Active-high asynchronous reset.\n'
            f' start: Datapath enable.\n a[{width - 1}:0]: Operand.\n b[{width - 1}:0]: Operand.\n'
            f'Output ports:\n p[{2 * width - 1}:0]: Product.\n done: Completion flag.\n'
            f'When start is high and the counter register (i) is less than {completion + 2}, '
            'increment i on each rising clock edge; when start is low, reset i to zero.\n'
            'While start is high, capture a and b and clear the product at i=0, then '
            f'conditionally add the shifted operand for each of the next {width} counts. '
            'When start is low, retain the product. Reset clears the counter, datapath and done_r.\n'
            f'{guard} counter register (i) is equal to {completion}, done_r is set to 1.\n'
            f'{guard} counter register (i) is equal to {completion + 1}, done_r is reset to 0.\n'
            f'{inactive} At other enabled counts, done_r holds its value.\n'
            + ('The done_r register updates only when start is high.\n' if qualified == 'global' else ''))


@pytest.mark.parametrize('width,completion', [(3, 5), (5, 8)])
@pytest.mark.parametrize('qualified', [False, True, 'global'],
                         ids=['independent', 'enable-qualified', 'global-enable-qualified'])
def test_sequential_completion_uses_its_own_stated_enable(tmp_path, width, completion, qualified):
    prompt = sequential_product_prompt(width, completion, qualified)
    (tmp_path / 'prompt.txt').write_text(prompt)
    result = chain.try_emit_ex(prompt, top='product_unit')
    rtl = assert_program_chain_candidate(result, prompt)
    assert result[0] == 'arithmetic'
    native(tmp_path, rtl, f'''module check;
reg clk=0,rst=0,start=0;
reg [{width - 1}:0] a={width}'d{(1 << width) - 1},b={width}'d{(1 << (width - 1)) + 1};
wire [{2 * width - 1}:0] p; wire done;
integer count=0,k; reg expected_done=0;
product_unit d(.clk(clk),.rst(rst),.start(start),.a(a),.b(b),.p(p),.done(done));
task reset_unit; begin
 rst=1; #1; count=0; expected_done=0;
 if(done!==0 || p!==0) $fatal(1,"asynchronous reset");
 rst=0; #1;
end endtask
task tick(input en); begin
 start=en;
 if({int(bool(qualified))} && !en) expected_done=0;
 else if(count=={completion}) expected_done=1;
 else if(count=={completion + 1}) expected_done=0;
 #2; clk=1; #1;
 if(done!==expected_done) $fatal(1,"completion count=%0d enable=%0d got=%0d expected=%0d",count,en,done,expected_done);
 if(en && count==0 && p!==0) $fatal(1,"new product must start at zero");
 if(count>={width} && p!==a*b) $fatal(1,"completed product");
 if(!en) count=0; else if(count<{completion + 2}) count=count+1;
 #2; clk=0;
end endtask
initial begin
 reset_unit;
 for(k=0;k<{completion};k=k+1) tick(1);
 tick(0); tick(0);
 for(k=0;k<={completion};k=k+1) tick(1);
 tick(0); tick(0);
 reset_unit;
 for(k=0;k<{completion - 1};k=k+1) tick(1);
 tick(0);
 for(k=0;k<={completion};k=k+1) tick(1);
 reset_unit;
 $display("CHECK_PASS"); $finish;
end endmodule''')


@pytest.mark.parametrize('mutation', [
    lambda text: text.replace('If start is high and the counter', 'If start is low and the counter'),
    lambda text: text.replace('If start is high and the counter register (i) is equal to 6',
                              'The counter register (i) is equal to 6').replace('When start is low, done_r is reset to 0.', ''),
], ids=['unsupported-low-enable', 'mixed-qualifiers'])
def test_sequential_completion_declines_unsupported_enable_rules(tmp_path, mutation):
    prompt = mutation(sequential_product_prompt(3, 5, True))
    assert_completion_declines_to_author(tmp_path, prompt)



@pytest.mark.parametrize('width,completion', [(3, 5), (5, 8)])
@pytest.mark.parametrize('qualified', [False, True, 'global'])
def test_general_multiplier_retains_the_shared_completion_predicate(tmp_path, width, completion, qualified):
    prompt = sequential_product_prompt(width, completion, qualified)
    rtl = general.synth(prompt, *arithmetic._dia_parse_ports(prompt), top='product_unit')
    assert rtl is not None
    native(tmp_path, rtl, f'''module check;
reg clk=0,rst=0,start=0; reg [{width-1}:0] a=3,b=2;
wire [{2*width-1}:0] p; wire done; integer k; always #5 clk=~clk;
product_unit d(.*);
initial begin #1;rst=1;#1;if(done!==0 || p!==0)$fatal;rst=0;
for(k=0;k<{completion};k=k+1) begin
 @(negedge clk);start=1;@(posedge clk);#1;
 if(done!==0)$fatal(1,"early completion at count %0d, declared completion {completion}",k);
end
@(negedge clk);start=0;@(posedge clk);#1;
if(done!==1'b{int(not bool(qualified))} || p!==6)$fatal(1,"completion enable/product mismatch");
$display("CHECK_PASS");$finish;end endmodule''')


def assert_completion_declines_to_author(tmp_path, prompt):
    assert arithmetic.synth(prompt, top='product_unit') is None
    assert general.synth(prompt, *arithmetic._dia_parse_ports(prompt), top='product_unit') is None
    kind, rtl, rejected = chain.try_emit_ex(prompt, top='product_unit')
    assert (kind, rtl) == (None, None), (kind, rtl, rejected)
    import _path_layout as layout
    import design_one_shot_runner as runner
    source = tmp_path / 'input/phase1_prompt.md'
    source.parent.mkdir()
    source.write_text(prompt)
    previous = layout._RTL_INPUT
    try:
        layout.select_rtl_input(tmp_path, 'original', '1', '1')
        result = runner.step_rtl_gen(tmp_path, 'digital_arithmetic_primitive')
    finally:
        layout._RTL_INPUT = previous
    assert result.status == 'PASS_WITH_WAIVERS', result
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert not result.output_files and not list((tmp_path / 'phase2/stage1/rtl').glob('*.sv'))


@pytest.mark.parametrize('width,completion', [(3, 5), (5, 8)])
def test_continued_unknown_completion_condition_reaches_author(tmp_path, width, completion):
    prompt = sequential_product_prompt(width, completion, True)
    prompt = prompt.replace('If start is high and the', 'If start != 0\n and the')
    prompt = prompt.replace('When start is low, done_r is reset to 0.', '')
    assert_completion_declines_to_author(tmp_path, prompt)

"""A fixed multiplier template must defer state it cannot represent."""
import subprocess

import pytest

import arithmetic_synth as arithmetic
import deterministic_emit_chain as chain
import design_one_shot_runner as owner
import _path_layout as layout


def prompt(width=6, extra="", radix=False):
    return (f"Implement a {width}-bit signed {'Radix-4 Booth ' if radix else ''}multiplier.\n"
            "Module name:\n ready_unit\nInput ports:\n clk: Clock.\n"
            " reset: Active-high asynchronous reset.\n"
            f" a[{width-1}:0]: First operand.\n b[{width-1}:0]: Second operand.\n"
            f"Output ports:\n p[{2*width-1}:0]: Product.\n rdy: Ready flag.\n"
            "Implementation:\n"
            f"The counter (ctr) is less than {width+3} while computing.\n"
            f"Once the counter reaches {width+3}, rdy is set to 1.\n" + extra)


STATE_CASES = [
    (3, "reg [5:0] saved_word;", False),
    (5, "logic signed [9:0] shadow_bits;\nOn reset: shadow_bits <= {a,b};", True),
    (6, "Reset loads operand_cache <= {{6{b[5]}}, b}.", True),
    (10, "During reset: held_factor <= a;", False),
    (4, "reg pending;", False),
    (12, "logic [23:0] lane_x, lane_y;\nif (reset) lane_x <= 24'h345;", True),
    (7, "On reset: p <= 1;", True),
    (9, "if (reset) rdy <= 0;", False),
]
STATE_IDS = ["reg-vector-3", "logic-reset-5", "concat-load-6",
             "operand-load-10", "reg-scalar-4", "logic-lanes-12",
             "numeric-product-reset-7", "numeric-ready-reset-9"]


@pytest.mark.parametrize("width,extra,radix", STATE_CASES, ids=STATE_IDS)
def test_unrepresented_state_declines(width, extra, radix):
    assert arithmetic.synth(prompt(width, extra, radix), "ready_unit") is None


@pytest.mark.parametrize("width,extra,radix", STATE_CASES, ids=STATE_IDS)
def test_decline_reaches_ordinary_owner(tmp_path, width, extra, radix):
    text = prompt(width, extra, radix)
    kind, rtl, rejected = chain.try_emit_ex(text, top="ready_unit")
    assert (kind, rtl) == (None, None), (kind, rtl, rejected)
    source = tmp_path / "input/phase1_prompt.md"
    source.parent.mkdir()
    source.write_text(text)
    previous = layout._RTL_INPUT
    try:
        layout.select_rtl_input(tmp_path, "original", "1", "1")
        result = owner.step_rtl_gen(tmp_path, "digital_arithmetic_primitive")
    finally:
        layout._RTL_INPUT = previous
    assert result.status == "PASS_WITH_WAIVERS", result
    assert result.extras["fallback_skill"] == "spec-to-rtl"
    assert not result.output_files
    assert not list((tmp_path / "phase2/stage1/rtl").glob("*.[sv]*"))


@pytest.mark.parametrize("extra", ["", "Bounds: 0 <= a; b <= 7;",
                                    "0 <= a;\nb <= 7;\na <= 6'd9;"],
                         ids=["unconstrained", "semicolon-bounds", "line-bounds"])
@pytest.mark.parametrize("radix", [False, True], ids=["plain", "radix4"])
def test_ordinary_product_runs_in_native_tools(tmp_path, extra, radix):
    width = 6
    text = prompt(width, extra, radix)
    kind, rtl, rejected = chain.try_emit_ex(text, top="ready_unit")
    assert kind == "arithmetic" and rtl, rejected
    assert rtl == arithmetic.synth(text, "ready_unit")
    dut = tmp_path / "dut.sv"
    tb = tmp_path / "check.sv"
    exe = tmp_path / "sim"
    dut.write_text(rtl)
    tb.write_text(f'''module check;
reg clk=0,reset=0; reg signed [5:0] a=0,b=0;
wire signed [11:0] p; wire rdy; integer i,j,k;
reg signed [11:0] expected;
ready_unit d(.*);
task tick; begin #2;clk=1;#1;clk=0;#1;end endtask
initial begin
 for(i=-32;i<32;i=i+1) for(j=-32;j<32;j=j+1) begin
  a=i;b=j;expected=i*j;#1;reset=1;#1;
  if(rdy!==0) $fatal(1,"reset ready");
  if(p!=={'0' if radix else 'expected'}) $fatal(1,"reset product default");
  reset=0;
  for(k=0;k<9;k=k+1) begin
   tick;
   if(rdy!==0) $fatal(1,"early ready");
  end
  tick;
  if(rdy!==1 || p!==expected) $fatal(1,"product %d * %d = %d",i,j,p);
  a=0;b=0;tick;
  if(rdy!==1 || p!==expected) $fatal(1,"completed value must hold");
 end
 $display("CHECK_PASS 4096 signed products");$finish;
end endmodule
''')
    for argv in (["iverilog", "-g2012", "-s", "check", "-o", str(exe), str(dut), str(tb)],
                 ["vvp", str(exe)]):
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
        (tmp_path / (argv[0] + ".log")).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECK_PASS 4096 signed products" in result.stdout


@pytest.mark.parametrize("change", [
    lambda text: text.replace("Once the counter reaches 9, rdy is set to 1.", "")
                     .replace("The counter (ctr) is less than 9 while computing.", ""),
    lambda text: text.replace(" a[5:0]: First operand.\n", ""),
], ids=["unstated-latency", "missing-operand"])
def test_existing_refusals_remain(change):
    assert arithmetic.synth(change(prompt()), "ready_unit") is None

"""Clocked decodes follow the source register and the scope of edge clauses."""
import re
import subprocess

import pytest

import canonical_primitive_synth as synth
import counter_advanced_synth
import deterministic_emit_chain


def _odd_description(relation=""):
    return """Module name:
 phase_reader_unit
A frequency divider by odd numbers.
Input ports:
 clk: Input clock.
 rst_n: Active low reset.
Output ports:
 clk_div: Divided clock.
The parameter NUM_DIV defaults to 7.
Two counters track rising and falling edges, count from 0 to NUM_DIV-1
and wrap to 0. Each divider output is high during the first half and low
during the remaining values, using integer truncation.
Logically OR the two divided outputs. The active low reset asynchronously
initializes counters to 0 and divider outputs to 1.
""" + relation


def _simulate(tmp_path, rtl, body):
    design, monitor, executable = (tmp_path / name for name in
                                    ("design.sv", "monitor.sv", "simulation.vvp"))
    design.write_text(rtl)
    monitor.write_text(body)
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-s", "monitor", "-o", str(executable),
         str(design), str(monitor)], cwd=tmp_path, capture_output=True, text=True,
        timeout=30)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    result = subprocess.run(["vvp", str(executable)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECK_PASS" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("relation,phase", [
    ("", "current"),
    ("Decode the current counter value before incrementing; output is low on the counter wrap edge.", "current"),
    ("After each counter wraps to 0, its output starts a high interval on that clock edge.", "wrap"),
    ("On each edge decode the next counter value after incrementing. After each counter wraps to 0, its output starts a high interval on that clock edge.", "next"),
    ("Each counter uses post-increment syntax for its own update.", "current"),
    ("Each counter uses post-increment syntax for its own update on each edge.", "current"),
    ("Each counter uses post-increment counter syntax for its own update on each edge, and the divider output keeps its defined phase.", "current"),
    ("Each registered divider output decodes the next counter value on the same edge as its counter update.", "next"),
    ("Each registered divider output decodes the post-increment counter value on the same edge as its counter update.", "next"),
])
def test_registered_divider_reads_current_value_except_explicit_edge(tmp_path, relation, phase):
    rtl = synth.emit_rtl("odd_clock_divider", _odd_description(relation))
    # Normalize the public identity so the old arm reaches the value assertion.
    rtl = re.sub(r"(?m)^module\s+\w+", "module phase_reader_unit", rtl, count=1)
    _simulate(tmp_path, rtl, """module monitor;
reg clk=0, rst_n=1;
wire q;
phase_reader_unit #(.NUM_DIV(7)) d(.clk(clk),.rst_n(rst_n),.clk_div(q));
integer p=0, n=0, k;
reg hp=1, hn=1;
initial begin
 #1; rst_n=0; #1; rst_n=1;
 for(k=0;k<56;k=k+1) begin
  #2;
  if(!clk) begin
   hp=(PHASE_NEXT ? ((p+1)%7)<3 : (PHASE_WRAP && p==6 ? 1 : p<3));
   p=(p+1)%7;
  end else begin
   hn=(PHASE_NEXT ? ((n+1)%7)<3 : (PHASE_WRAP && n==6 ? 1 : n<3));
   n=(n+1)%7;
  end
  clk=~clk; #1;
  if(q !== (hp|hn)) $fatal(1,"CHECK_FAIL current-decode edge=%0d actual=%b expected=%b",k,q,hp|hn);
 end
 $display("CHECK_PASS"); $finish;
end
endmodule
""".replace("PHASE_NEXT", str(int(phase == "next")))
       .replace("PHASE_WRAP", str(int(phase == "wrap"))))


@pytest.mark.parametrize("route", ["counter", "ordinary"])
def test_ordinary_emitter_keeps_current_counter_decode(tmp_path, route):
    description = _odd_description()
    if route == "counter":
        rtl = counter_advanced_synth.synth(description, top="phase_reader_unit")
    else:
        _, rtl, rejected = deterministic_emit_chain.try_emit_ex(
            description, top="phase_reader_unit", check=True)
        assert not rejected, rejected
    assert rtl is not None
    _simulate(tmp_path, rtl, """module monitor;
reg clk=0,rst_n=1; wire q;
phase_reader_unit d(.clk(clk),.rst_n(rst_n),.clk_div(q));
integer p=0,n=0,k; reg hp=1,hn=1;
initial begin
 #1;rst_n=0;#1;rst_n=1;
 for(k=0;k<56;k=k+1) begin
  #2;if(!clk) begin hp=(p<3);p=(p+1)%7;end
  else begin hn=(n<3);n=(n+1)%7;end
  clk=~clk;#1;if(q !== (hp|hn)) $fatal(1,"CHECK_FAIL ordinary-decode edge=%0d",k);
 end
 $display("CHECK_PASS");$finish;
end
endmodule
""")


@pytest.mark.parametrize("same_edge", [False, True])
@pytest.mark.parametrize("depth", [2, 4, 16])
def test_registered_gray_reads_named_binary_register(tmp_path, same_edge, depth):
    description = ("Gray registers encode the next binary position on the same edge as each binary update."
                   if same_edge else "Gray registers store the conversion of the current binary register.")
    rtl = synth.emit_rtl("async_gray_fifo", description)
    # Public identities do not select the register relation under test.
    modules = re.findall(r"(?m)^module\s+(\w+)", rtl)
    rtl = re.sub(r"(?m)^module\s+" + modules[-1] + r"\b", "module queue_unit", rtl)
    _simulate(tmp_path, rtl, """module monitor;
reg wc=0,rc=0,wn=1,rn=1,wi=0,ri=0;
wire full,empty; wire [7:0] data;
queue_unit #(.DEPTH(DEPTH_VALUE)) d(.wclk(wc),.rclk(rc),.wrstn(wn),.rrstn(rn),
 .winc(wi),.rinc(ri),.wdata(8'd19),.wfull(full),.rempty(empty),.rdata(data));
integer k, wb, rb, accepted_w, accepted_r, expected_w, expected_r;
initial begin
 #1;wn=0;rn=0;#1;wn=1;rn=1;
 for(k=0;k<28;k=k+1) begin
  wi=(k<2);ri=(k>8 && k<11);
  wb=d.waddr_bin;accepted_w=wi&&!full;
  expected_w=SAME_EDGE ? wb+accepted_w : wb;
  wc=1;#1;
  expected_w=expected_w & ((2*DEPTH_VALUE)-1);
  if(d.wptr !== (expected_w^(expected_w>>1))) $fatal(1,"CHECK_FAIL write-current k=%0d",k);
  if(full !== (d.wptr == (d.rptr_syn ^ (DEPTH_VALUE | (DEPTH_VALUE/2))))) $fatal(1,"CHECK_FAIL full-comparison");
  wc=0;#1;
  rb=d.raddr_bin;accepted_r=ri&&!empty;
  expected_r=SAME_EDGE ? rb+accepted_r : rb;
  rc=1;#1;
  expected_r=expected_r & ((2*DEPTH_VALUE)-1);
  if(d.rptr !== (expected_r^(expected_r>>1))) $fatal(1,"CHECK_FAIL read-current k=%0d",k);
  if(empty !== (d.rptr==d.wptr_syn)) $fatal(1,"CHECK_FAIL empty-comparison");
  rc=0;#1;
 end
 $display("CHECK_PASS");$finish;
end
endmodule
""".replace("DEPTH_VALUE", str(depth)).replace("SAME_EDGE", str(int(same_edge))))

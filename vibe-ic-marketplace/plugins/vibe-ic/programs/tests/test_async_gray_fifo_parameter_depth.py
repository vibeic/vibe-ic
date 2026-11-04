"""Exercise legal Gray FIFO depths through its producer and public RTL step."""
from pathlib import Path
import shutil
import subprocess

import pytest

import canonical_primitive_synth as producer
import design_one_shot_runner as runner


_DESCRIPTION = """Module name:
    asyn_fifo
Implement an asynchronous FIFO with gray code pointers and dual-port RAM.
Parameters WIDTH and DEPTH default to 8 and 16. DEPTH is a power of two >= 2.
Input ports:
 wclk: write clock.
 rclk: read clock.
 wrstn: active-low write reset.
 rrstn: active-low read reset.
 winc: write request.
 rinc: read request.
 wdata[WIDTH-1:0]: write data.
Output ports:
 wfull: full flag.
 rempty: empty flag.
 rdata[WIDTH-1:0]: registered read data.
"""

_WRAPPER = """module queue_shell #(parameter DEPTH=16)(
 input wclk, rclk, wrstn, rrstn, winc, rinc,
 input [7:0] wdata, output wfull, rempty, output [7:0] rdata);
 asyn_fifo #(.DEPTH(DEPTH), .WIDTH(8)) core (.*);
endmodule
"""

_TESTBENCH = r"""`timescale 1ns/1ps
module queue_probe;
 parameter DEPTH=16;
 localparam PW=$clog2(DEPTH)+1;
 reg wclk=0, rclk=0, wrstn=1, rrstn=1, winc=0, rinc=0;
 reg [7:0] wdata=0;
 wire wfull, rempty;
 wire [7:0] rdata;
 queue_shell #(.DEPTH(DEPTH)) dut (.*);
 always #5 wclk=~wclk;
 always #7 rclk=~rclk;
 integer i, round_id;
 reg [PW-1:0] previous_bin, previous_gray, sample_gray;
 reg [7:0] held_data;

 task reset_queue;
 begin
   @(negedge wclk); winc=0; rinc=0; wrstn=0; rrstn=0;
   #1;
   if (dut.core.waddr_bin !== 0 || dut.core.raddr_bin !== 0 ||
       dut.core.wptr !== 0 || dut.core.rptr !== 0 ||
       wfull !== 0 || rempty !== 1) $fatal(1, "reset boundary");
   repeat (3) @(negedge wclk);
   wrstn=1; rrstn=1;
 end
 endtask

 task write_word(input [7:0] value, input accepted);
 begin
   @(negedge wclk);
   previous_bin=dut.core.waddr_bin; previous_gray=dut.core.wptr;
   wdata=value; winc=1;
   @(posedge wclk); #1;
   if (dut.core.waddr_bin !== (previous_bin + accepted) % (2*DEPTH))
     $fatal(1, "write acceptance");
   sample_gray=dut.core.wptr;
   if (sample_gray !== (dut.core.waddr_bin ^ (dut.core.waddr_bin >> 1)))
     $fatal(1, "write Gray position");
   if (accepted && !$onehot(sample_gray ^ previous_gray))
     $fatal(1, "write Gray transition");
   $display("TRACE W %0d %0d %0d %0d", value, accepted, sample_gray, wfull);
   @(negedge wclk); winc=0;
 end
 endtask

 task read_word(input [7:0] value, input accepted);
 begin
   @(negedge rclk);
   previous_bin=dut.core.raddr_bin; previous_gray=dut.core.rptr;
   held_data=rdata; rinc=1;
   #1;
   if (rdata !== held_data) $fatal(1, "read changed before clock");
   @(posedge rclk); #1;
   if (dut.core.raddr_bin !== (previous_bin + accepted) % (2*DEPTH))
     $fatal(1, "read acceptance");
   if (accepted && rdata !== value) $fatal(1, "read order");
   if (!accepted && rdata !== held_data) $fatal(1, "empty read changed data");
   sample_gray=dut.core.rptr;
   if (sample_gray !== (dut.core.raddr_bin ^ (dut.core.raddr_bin >> 1)))
     $fatal(1, "read Gray position");
   if (accepted && !$onehot(sample_gray ^ previous_gray))
     $fatal(1, "read Gray transition");
   $display("TRACE R %0d %0d %0d %0d", rdata, accepted, sample_gray, rempty);
   @(negedge rclk); rinc=0;
 end
 endtask

 // Check both synchronizer stages, including their edge latency.
 reg [PW-1:0] read_gray_at_edge, read_stage_at_edge;
 reg [PW-1:0] write_gray_at_edge, write_stage_at_edge;
 reg [PW-1:0] full_target;
 always @(posedge wclk) begin
   read_gray_at_edge=dut.core.rptr; read_stage_at_edge=dut.core.rptr_b0;
   #1;
   if (wrstn && (dut.core.rptr_b0 !== read_gray_at_edge ||
                 dut.core.rptr_b1 !== read_stage_at_edge))
     $fatal(1, "read-pointer two-stage CDC");
   full_target=dut.core.rptr_syn;
   full_target[PW-1]=~full_target[PW-1];
   full_target[PW-2]=~full_target[PW-2];
   if (wfull !== (dut.core.wptr == full_target))
     $fatal(1, "full Gray comparison");
 end
 always @(posedge rclk) begin
   write_gray_at_edge=dut.core.wptr; write_stage_at_edge=dut.core.wptr_b0;
   #1;
   if (rrstn && (dut.core.wptr_b0 !== write_gray_at_edge ||
                 dut.core.wptr_b1 !== write_stage_at_edge))
     $fatal(1, "write-pointer two-stage CDC");
   if (rempty !== (dut.core.rptr == dut.core.wptr_syn))
     $fatal(1, "empty Gray comparison");
 end

 initial begin
   reset_queue;
   read_word(0, 0);
   for (round_id=0; round_id<3; round_id=round_id+1) begin
     for (i=0; i<DEPTH; i=i+1) begin
       if (wfull !== 0) $fatal(1, "early full");
       write_word(round_id*DEPTH+i+1, 1);
     end
     if (wfull !== 1) $fatal(1, "missing full at capacity");
     write_word(8'he7, 0);
     write_word(8'hb2, 0);
     repeat (3) @(negedge rclk);
     if (rempty !== 0) $fatal(1, "write CDC never visible");
     for (i=0; i<DEPTH; i=i+1) begin
       if (rempty !== 0) $fatal(1, "early empty");
       read_word(round_id*DEPTH+i+1, 1);
     end
     if (rempty !== 1) $fatal(1, "missing empty after drain");
     read_word(0, 0);
     repeat (3) @(negedge wclk);
     if (wfull !== 0) $fatal(1, "read CDC did not clear full");
   end
   write_word(8'h36, 1);
   reset_queue;
   read_word(0, 0);
   write_word(8'h95, 1);
   repeat (3) @(negedge rclk);
   read_word(8'h95, 1);
   if (rempty !== 1) $fatal(1, "post-reset empty");
   $display("PASS queue depth=%0d", DEPTH);
   $finish;
 end
 initial begin #100000; $fatal(1, "watchdog"); end
endmodule
"""


def _rtl_from(route: str, root: Path) -> Path:
    if route == "producer":
        rtl = root / "queue_primitive.v"
        rtl.write_text(producer.emit_rtl("async_gray_fifo"))
        return rtl
    project = root / "queue_project"
    prompt = project / "phase1" / "input_prompt" / "request.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(_DESCRIPTION)
    result = runner.step_rtl_gen(project, "digital_memory")
    (root / "step-result.txt").write_text(repr(result))
    assert result.status == "PASS", result
    assert result.extras["deterministic_generator"] == "canonical_primitive_synth"
    assert result.extras["shape"] == "async_gray_fifo"
    rtl = Path(next(path for path in result.output_files if path.endswith(".v")))
    assert rtl.is_file(), result
    assert producer.emit_rtl("async_gray_fifo") in rtl.read_text()
    return rtl


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="native Icarus compiler and simulator required")
@pytest.mark.parametrize("route", ["producer", "rtl_step"])
@pytest.mark.parametrize("depth", [2, 4, 8, 16, 32])
def test_legal_depth_compiles_and_preserves_queue_behavior(tmp_path, route, depth):
    rtl = _rtl_from(route, tmp_path)
    wrapper = tmp_path / "queue_shell.v"
    wrapper.write_text(_WRAPPER)
    tb = tmp_path / "queue_probe.sv"
    tb.write_text(_TESTBENCH)
    image = tmp_path / "queue.vvp"
    commands = [
        ["iverilog", "-g2012", "-s", "queue_probe", f"-Pqueue_probe.DEPTH={depth}",
         "-o", str(image), str(rtl), str(wrapper), str(tb)],
        ["vvp", str(image)],
    ]
    for phase, command in zip(("compile", "simulate"), commands):
        result = subprocess.run(command, cwd=tmp_path, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=60)
        (tmp_path / f"{phase}.log").write_text(result.stdout)
        assert result.returncode == 0, f"{phase} rc={result.returncode}\n{result.stdout}"
    assert f"PASS queue depth={depth}" in result.stdout

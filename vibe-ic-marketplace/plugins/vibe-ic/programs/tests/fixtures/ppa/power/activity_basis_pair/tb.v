// Testbench for the GATE netlist of chip_top (serial-parallel multiplier).
// Purpose: produce a VCD with REAL switching activity so `read_vcd` in OpenSTA
// has something to annotate. Deterministic: fixed seed, fixed stimulus.
`timescale 1ns/1ps
module tb;
  reg clk = 1'b0, rst = 1'b1, y = 1'b0;
  reg [31:0] x = 32'h0000_0000;
  wire p;
  chip_top dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));
  always #12 clk = ~clk;              // 24 ns period — the SDC period
  integer i;
  reg [31:0] lfsr = 32'hACE1_2345;    // fixed seed, no $random
  initial begin
    $dumpfile("chip_top.vcd");
    $dumpvars(0, tb);
    x = 32'h5A5A_1234;
    repeat (2) @(posedge clk);
    rst = 1'b0;
    for (i = 0; i < 256; i = i + 1) begin
      @(posedge clk);
      lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
      y = lfsr[0];
      if (i % 64 == 0) x = lfsr;
    end
    $finish;
  end
endmodule

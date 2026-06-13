// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: swd

`timescale 1ns/1ps

module swd_tb;

    reg  clk;
    reg  rst_n;

    // DUT instance
    swd u_dut (
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("swd_tb.vcd");
        $dumpvars(0, swd_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

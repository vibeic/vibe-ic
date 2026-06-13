// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: i2s

`timescale 1ns/1ps

module i2s_tb;

    wire SCK; // inout
    wire WS; // inout
    wire SD; // inout
    reg  clk;
    reg  rst_n;

    // DUT instance
    i2s u_dut (
        .SCK(SCK),
        .WS(WS),
        .SD(SD),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("i2s_tb.vcd");
        $dumpvars(0, i2s_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

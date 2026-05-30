// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: swd

`timescale 1ns/1ps

module swd_tb;

    wire SWCLK; // inout
    wire SWDIO; // inout
    wire nTRST; // inout
    wire SWO; // inout
    reg  VDD_IO_per_target;
    reg  GND;
    reg  clk;

    // DUT instance
    swd u_dut (
        .SWCLK(SWCLK),
        .SWDIO(SWDIO),
        .nTRST(nTRST),
        .SWO(SWO),
        .VDD_IO_per_target(VDD_IO_per_target),
        .GND(GND),
        .clk(clk)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("swd_tb.vcd");
        $dumpvars(0, swd_tb);
        VDD_IO_per_target = 1'b0;
        GND = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

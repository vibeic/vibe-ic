// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: PC16550D

`timescale 1ns/1ps

module PC16550D_tb;

    wire ANT; // inout
    reg  RF_GND;
    reg  VDD;
    reg  VSS;
    reg  Active_Clock;
    reg  Sleep_Clock;
    reg  clk;
    reg  rst_n;

    // DUT instance
    PC16550D u_dut (
        .ANT(ANT),
        .RF_GND(RF_GND),
        .VDD(VDD),
        .VSS(VSS),
        .Active_Clock(Active_Clock),
        .Sleep_Clock(Sleep_Clock),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial Active_Clock = 1'b0;
    always #5 Active_Clock = ~Active_Clock;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("PC16550D_tb.vcd");
        $dumpvars(0, PC16550D_tb);
        RF_GND = 1'b0;
        VDD = 1'b0;
        VSS = 1'b0;
        Sleep_Clock = 1'b0;
        clk = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

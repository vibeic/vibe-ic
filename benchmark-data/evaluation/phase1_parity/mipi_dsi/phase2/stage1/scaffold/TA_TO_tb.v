// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: TA_TO

`timescale 1ns/1ps

module TA_TO_tb;

    wire Clock; // inout
    wire Data0; // inout
    wire Data1_Data1_optional; // inout
    wire Data2_Data2_optional; // inout
    wire Data3_Data3_optional; // inout
    reg  rst_n;

    // DUT instance
    TA_TO u_dut (
        .Clock(Clock),
        .Data0(Data0),
        .Data1_Data1_optional(Data1_Data1_optional),
        .Data2_Data2_optional(Data2_Data2_optional),
        .Data3_Data3_optional(Data3_Data3_optional),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("TA_TO_tb.vcd");
        $dumpvars(0, TA_TO_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

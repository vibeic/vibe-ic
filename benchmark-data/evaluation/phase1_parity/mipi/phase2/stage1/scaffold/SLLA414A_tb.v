// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: SLLA414A

`timescale 1ns/1ps

module SLLA414A_tb;

    wire CLK_P; // inout
    wire CLK_N; // inout
    wire DAT0_P; // inout
    wire DAT0_N; // inout
    wire DAT1_P_DAT1_N_optional; // inout
    wire DAT2_P_DAT2_N_optional; // inout
    wire DAT3_P_DAT3_N_optional; // inout
    reg  rst_n;

    // DUT instance
    SLLA414A u_dut (
        .CLK_P(CLK_P),
        .CLK_N(CLK_N),
        .DAT0_P(DAT0_P),
        .DAT0_N(DAT0_N),
        .DAT1_P_DAT1_N_optional(DAT1_P_DAT1_N_optional),
        .DAT2_P_DAT2_N_optional(DAT2_P_DAT2_N_optional),
        .DAT3_P_DAT3_N_optional(DAT3_P_DAT3_N_optional),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("SLLA414A_tb.vcd");
        $dumpvars(0, SLLA414A_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

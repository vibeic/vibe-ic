// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: tilelink

`timescale 1ns/1ps

module tilelink_tb;

    reg  A;
    reg  B;
    reg  C;
    reg  D;
    reg  E;
    reg  clock;
    reg  reset;

    // DUT instance
    tilelink u_dut (
        .A(A),
        .B(B),
        .C(C),
        .D(D),
        .E(E),
        .clock(clock),
        .reset(reset)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clock = 1'b0;
    always #5 clock = ~clock;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("tilelink_tb.vcd");
        $dumpvars(0, tilelink_tb);
        A = 1'b0;
        B = 1'b0;
        C = 1'b0;
        D = 1'b0;
        E = 1'b0;
        reset = 1'b0;
        reset = 1'b1;
        #30;
        reset = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

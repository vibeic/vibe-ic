// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: QoS

`timescale 1ns/1ps

module QoS_tb;

    wire AW; // inout
    wire W; // inout
    wire B; // inout
    wire AR; // inout
    wire R; // inout
    reg  ACLK;
    reg  ARESETn;
    reg  clk;

    // DUT instance
    QoS u_dut (
        .AW(AW),
        .W(W),
        .B(B),
        .AR(AR),
        .R(R),
        .ACLK(ACLK),
        .ARESETn(ARESETn),
        .clk(clk)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial ACLK = 1'b0;
    always #5 ACLK = ~ACLK;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("QoS_tb.vcd");
        $dumpvars(0, QoS_tb);
        ARESETn = 1'b0;
        clk = 1'b0;
        ARESETn = 1'b0;
        #30;
        ARESETn = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

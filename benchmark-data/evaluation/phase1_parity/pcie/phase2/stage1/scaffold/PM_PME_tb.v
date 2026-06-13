// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: PM_PME

`timescale 1ns/1ps

module PM_PME_tb;

    wire TXp;
    wire TXn;
    reg  RXp;
    reg  RXn;
    reg  REFCLK;
    reg  PERST;
    reg  WAKE;

    // DUT instance
    PM_PME u_dut (
        .TXp(TXp),
        .TXn(TXn),
        .RXp(RXp),
        .RXn(RXn),
        .REFCLK(REFCLK),
        .PERST(PERST),
        .WAKE(WAKE)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial REFCLK = 1'b0;
    always #5 REFCLK = ~REFCLK;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("PM_PME_tb.vcd");
        $dumpvars(0, PM_PME_tb);
        RXp = 1'b0;
        RXn = 1'b0;
        PERST = 1'b0;
        WAKE = 1'b0;
        PERST = 1'b1;
        #30;
        PERST = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

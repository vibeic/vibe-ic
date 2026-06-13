// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: chip_top

`timescale 1ns/1ps

module chip_top_tb;

    wire TXp;
    wire TXn;
    reg  RXp;
    reg  RXn;
    reg  REFCLK;
    reg  PERST;
    reg  WAKE;
    reg  VBUS;
    reg  GND;
    reg  clk;
    reg  reset_n;
    reg  id_bus;

    // DUT instance
    chip_top u_dut (
        .TXp(TXp),
        .TXn(TXn),
        .RXp(RXp),
        .RXn(RXn),
        .REFCLK(REFCLK),
        .PERST(PERST),
        .WAKE(WAKE),
        .VBUS(VBUS),
        .GND(GND),
        .clk(clk),
        .reset_n(reset_n),
        .id_bus(id_bus)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial REFCLK = 1'b0;
    always #5 REFCLK = ~REFCLK;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("chip_top_tb.vcd");
        $dumpvars(0, chip_top_tb);
        RXp = 1'b0;
        RXn = 1'b0;
        PERST = 1'b0;
        WAKE = 1'b0;
        VBUS = 1'b0;
        GND = 1'b0;
        clk = 1'b0;
        reset_n = 1'b0;
        id_bus = 1'b0;
        PERST = 1'b1;
        #30;
        PERST = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

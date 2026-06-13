// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: SPI

`timescale 1ns/1ps

module SPI_tb;

    wire MOSI;
    reg  MISO;
    wire SCK;
    reg  SS;
    reg  BusClock;
    reg  Reset;

    // DUT instance
    SPI u_dut (
        .MOSI(MOSI),
        .MISO(MISO),
        .SCK(SCK),
        .SS(SS),
        .BusClock(BusClock),
        .Reset(Reset)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial BusClock = 1'b0;
    always #5 BusClock = ~BusClock;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("SPI_tb.vcd");
        $dumpvars(0, SPI_tb);
        MISO = 1'b0;
        SS = 1'b0;
        Reset = 1'b0;
        Reset = 1'b1;
        #30;
        Reset = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

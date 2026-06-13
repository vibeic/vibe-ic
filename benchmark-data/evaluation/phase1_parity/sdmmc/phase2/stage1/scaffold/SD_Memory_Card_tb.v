// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: SD_Memory_Card

`timescale 1ns/1ps

module SD_Memory_Card_tb;

    wire CLK; // inout
    wire CMD; // inout
    wire DAT0; // inout
    wire DAT1; // inout
    wire DAT2; // inout
    wire DAT3_CD_CS; // inout
    reg  rst_n;

    // DUT instance
    SD_Memory_Card u_dut (
        .CLK(CLK),
        .CMD(CMD),
        .DAT0(DAT0),
        .DAT1(DAT1),
        .DAT2(DAT2),
        .DAT3_CD_CS(DAT3_CD_CS),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("SD_Memory_Card_tb.vcd");
        $dumpvars(0, SD_Memory_Card_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: spdif

`timescale 1ns/1ps

module spdif_tb;

    wire SPDIF_TX_coax; // inout
    wire SPDIF_RX_coax; // inout
    wire SPDIF_Toslink_Tx; // inout
    wire SPDIF_Toslink_Rx; // inout
    reg  clk;
    reg  rst_n;

    // DUT instance
    spdif u_dut (
        .SPDIF_TX_coax(SPDIF_TX_coax),
        .SPDIF_RX_coax(SPDIF_RX_coax),
        .SPDIF_Toslink_Tx(SPDIF_Toslink_Tx),
        .SPDIF_Toslink_Rx(SPDIF_Toslink_Rx),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("spdif_tb.vcd");
        $dumpvars(0, spdif_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

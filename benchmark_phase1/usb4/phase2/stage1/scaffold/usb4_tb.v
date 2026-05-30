// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: usb4

`timescale 1ns/1ps

module usb4_tb;

    reg  TX1_TX1;
    reg  RX1_RX1;
    reg  TX2_TX2;
    reg  RX2_RX2;
    wire SBU1_SBU2; // inout
    wire CC1_CC2; // inout
    reg  VBUS;
    reg  D_D;
    reg  GND;
    reg  clk;
    reg  rst_n;

    // DUT instance
    usb4 u_dut (
        .TX1_TX1(TX1_TX1),
        .RX1_RX1(RX1_RX1),
        .TX2_TX2(TX2_TX2),
        .RX2_RX2(RX2_RX2),
        .SBU1_SBU2(SBU1_SBU2),
        .CC1_CC2(CC1_CC2),
        .VBUS(VBUS),
        .D_D(D_D),
        .GND(GND),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("usb4_tb.vcd");
        $dumpvars(0, usb4_tb);
        TX1_TX1 = 1'b0;
        RX1_RX1 = 1'b0;
        TX2_TX2 = 1'b0;
        RX2_RX2 = 1'b0;
        VBUS = 1'b0;
        D_D = 1'b0;
        GND = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

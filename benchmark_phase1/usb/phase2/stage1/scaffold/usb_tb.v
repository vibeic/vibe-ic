// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: usb

`timescale 1ns/1ps

module usb_tb;

    wire D; // inout
    reg  VBUS;
    reg  GND;
    reg  VBUS_5V;
    reg  clk;
    reg  rst_n;

    // DUT instance
    usb u_dut (
        .D(D),
        .VBUS(VBUS),
        .GND(GND),
        .VBUS_5V(VBUS_5V),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("usb_tb.vcd");
        $dumpvars(0, usb_tb);
        VBUS = 1'b0;
        GND = 1'b0;
        VBUS_5V = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

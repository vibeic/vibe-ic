// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: hdmi

`timescale 1ns/1ps

module hdmi_tb;

    wire SDA; // inout
    reg  SCL;
    reg  VDD;
    reg  Rp;
    reg  GND;
    reg  hsync;
    reg  vsync;
    reg  dken;
    reg  de;
    wire dvi;
    reg  clk;
    reg  rst_n;

    // DUT instance
    hdmi u_dut (
        .SDA(SDA),
        .SCL(SCL),
        .VDD(VDD),
        .Rp(Rp),
        .GND(GND),
        .hsync(hsync),
        .vsync(vsync),
        .dken(dken),
        .de(de),
        .dvi(dvi),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("hdmi_tb.vcd");
        $dumpvars(0, hdmi_tb);
        SCL = 1'b0;
        VDD = 1'b0;
        Rp = 1'b0;
        GND = 1'b0;
        hsync = 1'b0;
        vsync = 1'b0;
        dken = 1'b0;
        de = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

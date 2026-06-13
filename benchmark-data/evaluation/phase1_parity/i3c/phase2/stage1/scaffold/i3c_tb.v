// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: i3c

`timescale 1ns/1ps

module i3c_tb;

    reg  SDA;
    reg  SCL;
    reg  VDD;
    reg  Rp_Pull_Up;
    reg  High_Keeper;
    reg  GND;
    reg  clk;
    reg  rst_n;

    // DUT instance
    i3c u_dut (
        .SDA(SDA),
        .SCL(SCL),
        .VDD(VDD),
        .Rp_Pull_Up(Rp_Pull_Up),
        .High_Keeper(High_Keeper),
        .GND(GND),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("i3c_tb.vcd");
        $dumpvars(0, i3c_tb);
        SDA = 1'b0;
        SCL = 1'b0;
        VDD = 1'b0;
        Rp_Pull_Up = 1'b0;
        High_Keeper = 1'b0;
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

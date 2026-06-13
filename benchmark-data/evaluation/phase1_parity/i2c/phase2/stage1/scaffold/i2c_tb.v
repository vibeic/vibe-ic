// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: i2c

`timescale 1ns/1ps

module i2c_tb;

    wire SDA; // inout
    reg  SCL;
    reg  VDD;
    reg  Rp;
    reg  GND;
    reg  clk;
    reg  rst_n;

    // DUT instance
    i2c u_dut (
        .SDA(SDA),
        .SCL(SCL),
        .VDD(VDD),
        .Rp(Rp),
        .GND(GND),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("i2c_tb.vcd");
        $dumpvars(0, i2c_tb);
        SCL = 1'b0;
        VDD = 1'b0;
        Rp = 1'b0;
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

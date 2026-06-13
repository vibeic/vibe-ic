// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: DS2480B

`timescale 1ns/1ps

module DS2480B_tb;

    reg  DQ;
    reg  GND;
    reg  clk;
    reg  rst_n;

    // DUT instance
    DS2480B u_dut (
        .DQ(DQ),
        .GND(GND),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("DS2480B_tb.vcd");
        $dumpvars(0, DS2480B_tb);
        DQ = 1'b0;
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

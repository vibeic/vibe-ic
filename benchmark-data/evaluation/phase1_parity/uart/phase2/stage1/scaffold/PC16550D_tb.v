// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: PC16550D

`timescale 1ns/1ps

module PC16550D_tb;

    reg  VDD;
    reg  VSS;
    reg  clk;
    reg  rst_n;

    // DUT instance
    PC16550D u_dut (
        .VDD(VDD),
        .VSS(VSS),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("PC16550D_tb.vcd");
        $dumpvars(0, PC16550D_tb);
        VDD = 1'b0;
        VSS = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

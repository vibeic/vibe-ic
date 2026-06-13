// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: arinc429

`timescale 1ns/1ps

module arinc429_tb;

    reg  ARINC_429_bus_single_twisted_pair_simplex;
    reg  clk;
    reg  rst_n;

    // DUT instance
    arinc429 u_dut (
        .ARINC_429_bus_single_twisted_pair_simplex(ARINC_429_bus_single_twisted_pair_simplex),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("arinc429_tb.vcd");
        $dumpvars(0, arinc429_tb);
        ARINC_429_bus_single_twisted_pair_simplex = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

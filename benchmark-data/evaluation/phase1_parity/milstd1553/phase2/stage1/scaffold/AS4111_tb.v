// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: AS4111

`timescale 1ns/1ps

module AS4111_tb;

    reg  Bus_A_primary;
    reg  Bus_B_redundant;
    reg  clk;
    reg  rst_n;

    // DUT instance
    AS4111 u_dut (
        .Bus_A_primary(Bus_A_primary),
        .Bus_B_redundant(Bus_B_redundant),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("AS4111_tb.vcd");
        $dumpvars(0, AS4111_tb);
        Bus_A_primary = 1'b0;
        Bus_B_redundant = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

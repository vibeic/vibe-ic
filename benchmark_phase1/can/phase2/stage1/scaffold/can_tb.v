// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: can

`timescale 1ns/1ps

module can_tb;

    wire CAN_bus_single_channel; // inout
    reg  clk;
    reg  rst_n;

    // DUT instance
    can u_dut (
        .CAN_bus_single_channel(CAN_bus_single_channel),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("can_tb.vcd");
        $dumpvars(0, can_tb);
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: jtag

`timescale 1ns/1ps

module jtag_tb;

    wire TCK; // inout
    wire TMS; // inout
    wire TDI; // inout
    wire TDO; // inout
    wire TRST; // inout
    reg  VDD_IO_per_device;
    reg  GND;
    reg  clk;

    // DUT instance
    jtag u_dut (
        .TCK(TCK),
        .TMS(TMS),
        .TDI(TDI),
        .TDO(TDO),
        .TRST(TRST),
        .VDD_IO_per_device(VDD_IO_per_device),
        .GND(GND),
        .clk(clk)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("jtag_tb.vcd");
        $dumpvars(0, jtag_tb);
        VDD_IO_per_device = 1'b0;
        GND = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

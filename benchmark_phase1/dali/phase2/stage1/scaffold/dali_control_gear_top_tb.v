// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: dali_control_gear_top

`timescale 1ns/1ps

module dali_control_gear_top_tb;

    reg  VBUS;
    reg  IBUS;
    reg  BUS_IDLE_STATE;
    reg  TE;
    reg  BIT_TIME;
    reg  BYTE_ORDER;
    reg  clk;
    reg  rst_n;

    // DUT instance
    dali_control_gear_top u_dut (
        .VBUS(VBUS),
        .IBUS(IBUS),
        .BUS_IDLE_STATE(BUS_IDLE_STATE),
        .TE(TE),
        .BIT_TIME(BIT_TIME),
        .BYTE_ORDER(BYTE_ORDER),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("dali_control_gear_top_tb.vcd");
        $dumpvars(0, dali_control_gear_top_tb);
        VBUS = 1'b0;
        IBUS = 1'b0;
        BUS_IDLE_STATE = 1'b0;
        TE = 1'b0;
        BIT_TIME = 1'b0;
        BYTE_ORDER = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: modbus_server_top

`timescale 1ns/1ps

module modbus_server_top_tb;

    reg  BUS_IDLE_STATE;
    reg  TCP_PORT_502;
    reg  BIG_ENDIAN_ORDER;
    reg  clk;
    reg  rst_n;

    // DUT instance
    modbus_server_top u_dut (
        .BUS_IDLE_STATE(BUS_IDLE_STATE),
        .TCP_PORT_502(TCP_PORT_502),
        .BIG_ENDIAN_ORDER(BIG_ENDIAN_ORDER),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("modbus_server_top_tb.vcd");
        $dumpvars(0, modbus_server_top_tb);
        BUS_IDLE_STATE = 1'b0;
        TCP_PORT_502 = 1'b0;
        BIG_ENDIAN_ORDER = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: hdlc

`timescale 1ns/1ps

module hdlc_tb;

    reg  Synchronous_serial_link_NRZI;
    reg  Asynchronous_serial_link_RS_232_style;
    reg  Multidrop_bus_SDLC;
    reg  clk;
    reg  rst_n;

    // DUT instance
    hdlc u_dut (
        .Synchronous_serial_link_NRZI(Synchronous_serial_link_NRZI),
        .Asynchronous_serial_link_RS_232_style(Asynchronous_serial_link_RS_232_style),
        .Multidrop_bus_SDLC(Multidrop_bus_SDLC),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("hdlc_tb.vcd");
        $dumpvars(0, hdlc_tb);
        Synchronous_serial_link_NRZI = 1'b0;
        Asynchronous_serial_link_RS_232_style = 1'b0;
        Multidrop_bus_SDLC = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

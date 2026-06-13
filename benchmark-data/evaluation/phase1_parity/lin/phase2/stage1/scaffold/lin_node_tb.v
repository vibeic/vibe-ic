// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: lin_node

`timescale 1ns/1ps

module lin_node_tb;

    wire CAN_bus_single_channel; // inout
    reg  response_error;
    reg  NAD;
    reg  Supplier_ID_Function_ID_Variant;
    reg  clk;
    reg  rst_n;

    // DUT instance
    lin_node u_dut (
        .CAN_bus_single_channel(CAN_bus_single_channel),
        .response_error(response_error),
        .NAD(NAD),
        .Supplier_ID_Function_ID_Variant(Supplier_ID_Function_ID_Variant),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("lin_node_tb.vcd");
        $dumpvars(0, lin_node_tb);
        response_error = 1'b0;
        NAD = 1'b0;
        Supplier_ID_Function_ID_Variant = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

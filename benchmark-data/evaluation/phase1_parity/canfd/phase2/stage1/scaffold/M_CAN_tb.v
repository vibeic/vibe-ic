// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: M_CAN

`timescale 1ns/1ps

module M_CAN_tb;

    wire CAN_bus_single_channel; // inout
    reg  Generic_Slave_Interface_Host_CPU;
    reg  Generic_Master_Interface_Message_RAM;
    reg  Interrupt_lines;
    reg  Extension_Interface;
    reg  TSU_Interface;
    reg  DMU_Interface;
    reg  Power_down_Interface;
    reg  clk;
    reg  rst_n;

    // DUT instance
    M_CAN u_dut (
        .CAN_bus_single_channel(CAN_bus_single_channel),
        .Generic_Slave_Interface_Host_CPU(Generic_Slave_Interface_Host_CPU),
        .Generic_Master_Interface_Message_RAM(Generic_Master_Interface_Message_RAM),
        .Interrupt_lines(Interrupt_lines),
        .Extension_Interface(Extension_Interface),
        .TSU_Interface(TSU_Interface),
        .DMU_Interface(DMU_Interface),
        .Power_down_Interface(Power_down_Interface),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("M_CAN_tb.vcd");
        $dumpvars(0, M_CAN_tb);
        Generic_Slave_Interface_Host_CPU = 1'b0;
        Generic_Master_Interface_Message_RAM = 1'b0;
        Interrupt_lines = 1'b0;
        Extension_Interface = 1'b0;
        TSU_Interface = 1'b0;
        DMU_Interface = 1'b0;
        Power_down_Interface = 1'b0;
        rst_n = 1'b0;
        rst_n = 1'b0;
        #30;
        rst_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

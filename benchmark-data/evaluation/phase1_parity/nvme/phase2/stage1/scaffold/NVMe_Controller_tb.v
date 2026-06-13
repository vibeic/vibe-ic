// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: NVMe_Controller

`timescale 1ns/1ps

module NVMe_Controller_tb;

    wire PCIe_Link; // inout
    reg  REFCLK;
    reg  PERST;
    reg  CLKREQ;
    reg  BAR0_BAR1_MMIO;
    reg  Host_SQ_memory;
    reg  Host_CQ_memory;
    wire Host_PRP_SGL_buffers; // inout
    reg  MSI_X_Table;

    // DUT instance
    NVMe_Controller u_dut (
        .PCIe_Link(PCIe_Link),
        .REFCLK(REFCLK),
        .PERST(PERST),
        .CLKREQ(CLKREQ),
        .BAR0_BAR1_MMIO(BAR0_BAR1_MMIO),
        .Host_SQ_memory(Host_SQ_memory),
        .Host_CQ_memory(Host_CQ_memory),
        .Host_PRP_SGL_buffers(Host_PRP_SGL_buffers),
        .MSI_X_Table(MSI_X_Table)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial REFCLK = 1'b0;
    always #5 REFCLK = ~REFCLK;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("NVMe_Controller_tb.vcd");
        $dumpvars(0, NVMe_Controller_tb);
        PERST = 1'b0;
        CLKREQ = 1'b0;
        BAR0_BAR1_MMIO = 1'b0;
        Host_SQ_memory = 1'b0;
        Host_CQ_memory = 1'b0;
        MSI_X_Table = 1'b0;
        PERST = 1'b1;
        #30;
        PERST = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

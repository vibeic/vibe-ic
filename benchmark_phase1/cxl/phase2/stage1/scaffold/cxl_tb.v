// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: cxl

`timescale 1ns/1ps

module cxl_tb;

    wire CXL_io; // inout
    reg  CXL_cache_D2H_Req;
    reg  CXL_cache_D2H_Rsp;
    reg  CXL_cache_D2H_Data;
    reg  CXL_cache_H2D_Req;
    reg  CXL_cache_H2D_Rsp;
    reg  CXL_cache_H2D_Data;
    reg  CXL_mem_M2S_Req;
    reg  CXL_mem_M2S_RwD;
    reg  CXL_mem_S2M_NDR;
    reg  CXL_mem_S2M_DRS;
    reg  Flex_Bus_TXp_TXn_RXp_RXn;
    reg  REFCLK;
    reg  PERST;

    // DUT instance
    cxl u_dut (
        .CXL_io(CXL_io),
        .CXL_cache_D2H_Req(CXL_cache_D2H_Req),
        .CXL_cache_D2H_Rsp(CXL_cache_D2H_Rsp),
        .CXL_cache_D2H_Data(CXL_cache_D2H_Data),
        .CXL_cache_H2D_Req(CXL_cache_H2D_Req),
        .CXL_cache_H2D_Rsp(CXL_cache_H2D_Rsp),
        .CXL_cache_H2D_Data(CXL_cache_H2D_Data),
        .CXL_mem_M2S_Req(CXL_mem_M2S_Req),
        .CXL_mem_M2S_RwD(CXL_mem_M2S_RwD),
        .CXL_mem_S2M_NDR(CXL_mem_S2M_NDR),
        .CXL_mem_S2M_DRS(CXL_mem_S2M_DRS),
        .Flex_Bus_TXp_TXn_RXp_RXn(Flex_Bus_TXp_TXn_RXp_RXn),
        .REFCLK(REFCLK),
        .PERST(PERST)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial REFCLK = 1'b0;
    always #5 REFCLK = ~REFCLK;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("cxl_tb.vcd");
        $dumpvars(0, cxl_tb);
        CXL_cache_D2H_Req = 1'b0;
        CXL_cache_D2H_Rsp = 1'b0;
        CXL_cache_D2H_Data = 1'b0;
        CXL_cache_H2D_Req = 1'b0;
        CXL_cache_H2D_Rsp = 1'b0;
        CXL_cache_H2D_Data = 1'b0;
        CXL_mem_M2S_Req = 1'b0;
        CXL_mem_M2S_RwD = 1'b0;
        CXL_mem_S2M_NDR = 1'b0;
        CXL_mem_S2M_DRS = 1'b0;
        Flex_Bus_TXp_TXn_RXp_RXn = 1'b0;
        PERST = 1'b0;
        PERST = 1'b1;
        #30;
        PERST = 1'b0;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

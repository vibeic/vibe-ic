// Auto-generated SoC integration wrapper (APB-lite).
// Wraps cxl and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: cxl
// Register file present (L4): no

`timescale 1ns/1ps

module cxl_soc_wrap (
    // ---- APB-lite register-access bus ----
    input         PCLK,
    input         PRESETn,
    input  [11:0] PADDR,
    input         PSEL,
    input         PENABLE,
    input         PWRITE,
    input  [31:0] PWDATA,
    output reg [31:0] PRDATA,
    output        PREADY
    ,
    // ---- native protocol ports (passthrough to pads) ----
    inout  CXL_io,  // Non-coherent I/O / config / enumeration / DMA / register I/O.
    input  CXL_cache_D2H_Req,  // Device requests host memory line (Rd/Own/etc.).
    input  CXL_cache_D2H_Rsp,  // Device response to host snoop.
    input  CXL_cache_D2H_Data,  // Device-to-host data transfer.
    input  CXL_cache_H2D_Req,  // Host snoop (SnpData/SnpInv/SnpCur) to device cache.
    input  CXL_cache_H2D_Rsp,  // Host response (GO / WritePull / ...).
    input  CXL_cache_H2D_Data,  // Host-to-device data transfer.
    input  CXL_mem_M2S_Req,  // Host read/inval request to device memory.
    input  CXL_mem_M2S_RwD,  // Host write-with-data to device memory.
    input  CXL_mem_S2M_NDR,  // No-Data Response (Cmp / Cmp-S / Cmp-E).
    input  CXL_mem_S2M_DRS,  // Data Response (MemData).
    input  Flex_Bus_TXp_TXn_RXp_RXn  // Shared PCIe PHY carrying all multiplexed sub-protocols.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // No register file (L4 empty). Expose a read-only ID register
    // so the SoC can still probe the wrapper, and pass the block's
    // native ports through to the wrapper boundary.
    // -----------------------------------------------------------
    localparam [31:0] WRAP_ID = 32'h5343_5750; // "SCWP"

    always @(*) begin
        PRDATA = 32'h0;
        if (apb_read) begin
            case (PADDR)
                12'h000: PRDATA = WRAP_ID; // read-only ID register
                default: PRDATA = 32'h0;
            endcase
        end
    end

    // Wrapped protocol-block instance.
    cxl u_cxl (
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
        .REFCLK(PCLK),
        .PERST(PRESETn)
    );

endmodule

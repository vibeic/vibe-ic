// Auto-generated SoC integration wrapper (APB-lite).
// Wraps SUCH_ARM_TECHNOLOGY and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: SUCH_ARM_TECHNOLOGY
// Register file present (L4): no

`timescale 1ns/1ps

module SUCH_ARM_TECHNOLOGY_soc_wrap (
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
    inout  AW,
    inout  W,
    inout  B,
    inout  AR,
    inout  R,
    input  aclk,
    output awid,
    output awaddr,
    output awregion,
    output awlen,
    output awsize,
    output awburst,
    output incr,
    output awlock,
    output awcache,
    output awprot,
    output awqos,
    output awvalid,
    input  awready,
    output wdata,
    output wstrb,
    output wlast,
    output wvalid,
    input  wready,
    input  bid,
    input  bresp,
    input  bvalid,
    output bready,
    output okay,
    output arid,
    output araddr,
    output arregion,
    output arlen,
    output arsize,
    output arburst,
    output arlock,
    output arcache,
    output arprot,
    output arqos,
    output arvalid,
    input  arready,
    input  rid,
    input  rdata,
    input  rresp,
    input  rlast,
    input  rvalid,
    output rready
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
    SUCH_ARM_TECHNOLOGY u_SUCH_ARM_TECHNOLOGY (
        .AW(AW),
        .W(W),
        .B(B),
        .AR(AR),
        .R(R),
        .ACLK(PCLK),
        .ARESETn(PRESETn),
        .aclk(aclk),
        .awid(awid),
        .awaddr(awaddr),
        .awregion(awregion),
        .awlen(awlen),
        .awsize(awsize),
        .awburst(awburst),
        .incr(incr),
        .awlock(awlock),
        .awcache(awcache),
        .awprot(awprot),
        .awqos(awqos),
        .awvalid(awvalid),
        .awready(awready),
        .wdata(wdata),
        .wstrb(wstrb),
        .wlast(wlast),
        .wvalid(wvalid),
        .wready(wready),
        .bid(bid),
        .bresp(bresp),
        .bvalid(bvalid),
        .bready(bready),
        .okay(okay),
        .arid(arid),
        .araddr(araddr),
        .arregion(arregion),
        .arlen(arlen),
        .arsize(arsize),
        .arburst(arburst),
        .arlock(arlock),
        .arcache(arcache),
        .arprot(arprot),
        .arqos(arqos),
        .arvalid(arvalid),
        .arready(arready),
        .rid(rid),
        .rdata(rdata),
        .rresp(rresp),
        .rlast(rlast),
        .rvalid(rvalid),
        .rready(rready)
    );

endmodule

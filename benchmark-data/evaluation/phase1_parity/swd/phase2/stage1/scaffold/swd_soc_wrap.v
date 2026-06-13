// Auto-generated SoC integration wrapper (APB-lite).
// Wraps swd and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: swd
// Register file present (L4): yes

`timescale 1ns/1ps

module swd_soc_wrap (
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
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 6 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x24     MEMMAP_LOW_00000024 [8b, ro]
    // offset 0xEC     MEMMAP_HIGH_000000EC [8b, ro]
    // offset 0x20     MEMMAP_LOW_00000020 [8b, ro]
    // offset 0xF8     MEMMAP_HIGH_000000F8 [8b, ro]
    // offset 0x2      MEMMAP_LOW_00000002 [8b, ro]
    // offset 0x8      MEMMAP_HIGH_00000008 [8b, ro]

    always @(*) begin
        PRDATA = 32'h0;
        if (apb_read) begin
            case (PADDR)
                // TODO: 12'hXXX: PRDATA = <reg>;  per offsets above
                default: PRDATA = 32'h0;
            endcase
        end
    end

    // TODO: on apb_write, decode PADDR and update the block's
    //       register file (writes are stubbed out for now).

    // Wrapped protocol-block instance.
    swd u_swd (
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

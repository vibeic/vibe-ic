// Auto-generated SoC integration wrapper (APB-lite).
// Wraps wishbone and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: wishbone
// Register file present (L4): yes

`timescale 1ns/1ps

module wishbone_soc_wrap (
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
    // The protocol exposes 8 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x00     MEMMAP_LOW_00000000 [8b, ro]
    // offset 0x07     MEMMAP_HIGH_00000007 [8b, ro]
    // offset 0x08     MEMMAP_LOW_00000008 [8b, ro]
    // offset 0x0F     MEMMAP_HIGH_0000000F [8b, ro]
    // offset 0x10     MEMMAP_LOW_00000010 [8b, ro]
    // offset 0x17     MEMMAP_HIGH_00000017 [8b, ro]
    // offset 0x18     MEMMAP_LOW_00000018 [8b, ro]
    // offset 0x1F     MEMMAP_HIGH_0000001F [8b, ro]

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
    wishbone u_wishbone (
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

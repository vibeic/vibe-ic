// Auto-generated SoC integration wrapper (APB-lite).
// Wraps SPI and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: SPI
// Register file present (L4): yes

`timescale 1ns/1ps

module SPI_soc_wrap (
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
    output MOSI,  // Master-Output Slave-Input serial data; in bidirectional master mode acts as MOMI (Master I/O); in bidirectional slave mode is not used by SPI.
    input  MISO,  // Master-Input Slave-Output serial data; in bidirectional master mode is not used; in bidirectional slave mode acts as SISO (Slave I/O).
    output SCK,  // Serial clock; 16 edges per 8-bit transfer; idle polarity per CPOL.
    input  SS  // Slave-Select; LOW = selected; HIGH = deselected (slave output tri-stated and SCK input ignored).
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
    // offset $___0    SPICR1 [8b, read / write (anytime)]
    // offset $___1    SPICR2 [8b, read / write (anytime; reserved bits writes ignored)]
    // offset $___2    SPIBR [8b, read / write (anytime; reserved bits writes ignored)]
    // offset $___3    SPISR [8b, read; writes have no effect]
    // offset $___4    Reserved_4 [8b, writes ignored; reads return all zeros.]
    // offset $___5    SPIDR [8b, read (normally only when spif set) / write (anytime)]
    // offset $___6    Reserved_6 [8b, writes ignored; reads return all zeros.]
    // offset $___7    Reserved_7 [8b, writes ignored; reads return all zeros.]

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
    SPI u_SPI (
        .MOSI(MOSI),
        .MISO(MISO),
        .SCK(SCK),
        .SS(SS),
        .BusClock(PCLK),
        .Reset(PRESETn)
    );

endmodule

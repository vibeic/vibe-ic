// Auto-generated SoC integration wrapper (APB-lite).
// Wraps SD_Memory_Card and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: SD_Memory_Card
// Register file present (L4): yes

`timescale 1ns/1ps

module SD_Memory_Card_soc_wrap (
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
    inout  CLK,  // Synchronous bus clock; up to 208 MHz UHS-I SDR104.
    inout  CMD,  // Command/response; 48-bit frames; open-drain in ident, push-pull after.
    inout  DAT0,  // Data line 0; SPI DO; BUSY when LOW during Programming.
    inout  DAT1,  // Data line 1; SDIO IRQ.
    inout  DAT2,  // Data line 2; SDIO Read Wait.
    inout  DAT3_CD_CS  // Data line 3 (SD); CS (SPI); CD/DAT3 with internal 50 kΩ pull-up.
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
    // offset          OCR [32b, read (via acmd41 r3 / cmd58 in spi)]
    // offset          CID [128b, read (cmd2 in sd, cmd10 later)]
    // offset          CSD [128b, read (cmd9), partial write (cmd27 program_csd)]
    // offset          RCA [16b, read/published (cmd3 r6)]
    // offset          DSR [16b, write (cmd4; optional)]
    // offset          SCR [64b, read (acmd51)]
    // offset          SSR [512b, read (acmd13)]
    // offset          CSR [32b, read (every r1 response)]

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
    SD_Memory_Card u_SD_Memory_Card (
        .CLK(CLK),
        .CMD(CMD),
        .DAT0(DAT0),
        .DAT1(DAT1),
        .DAT2(DAT2),
        .DAT3_CD_CS(DAT3_CD_CS),
        .rst_n(PRESETn)
    );

endmodule

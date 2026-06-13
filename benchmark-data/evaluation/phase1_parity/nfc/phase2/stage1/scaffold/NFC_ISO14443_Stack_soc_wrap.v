// Auto-generated SoC integration wrapper (APB-lite).
// Wraps NFC_ISO14443_Stack and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: NFC_ISO14443_Stack
// Register file present (L4): yes

`timescale 1ns/1ps

module NFC_ISO14443_Stack_soc_wrap (
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
    input  RF_Carrier_13_56_MHz,  // Continuous unmodulated 13.56 MHz carrier that powers the PICC and serves as the synchronous clock reference.
    input  PCD_PICC_modulation,  // Carries 7-bit short frames, standard frames, and anti-collision bit-frames as envelope changes.
    input  PICC_PCD_load_modulation,  // Carries ATQA, UID-CLn+BCC, SAK, ATS, T=CL replies as 847.5 kHz subcarrier sidebands.
    input  PCD_Host_Bus_SPI_I2C_UART,  // Application path between host MCU and PCD chip.
    input  PCD_IRQ,  // Asynchronous interrupt indicating frame received / TX complete / error.
    input  sig_13_56_MHz_RF_carrier  // Shared synchronous time base for PCD-PICC system.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 9 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          ATQA [16b, read (picc reply to reqa / wupa)]
    // offset          UID [32b, read (across cascade levels 1..3)]
    // offset          BCC_per_CL [8b, computed by both pcd and picc]
    // offset          SAK [8b, read (picc reply to final select)]
    // offset          ATS [8b, read (picc reply to rats 0xe0)]
    // offset          GetVersion_Response [7b, read (host apdu 0x60)]
    // offset          ATQB [12b, read (picc reply to reqb / wupb)]
    // offset          PCB [8b, read/write (per t=cl block)]
    // offset          CID [8b, read/write (assigned by pcd at rats param)]

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
    NFC_ISO14443_Stack u_NFC_ISO14443_Stack (
        .RF_Carrier_13_56_MHz(RF_Carrier_13_56_MHz),
        .PCD_PICC_modulation(PCD_PICC_modulation),
        .PICC_PCD_load_modulation(PICC_PCD_load_modulation),
        .PCD_Host_Bus_SPI_I2C_UART(PCD_Host_Bus_SPI_I2C_UART),
        .PCD_IRQ(PCD_IRQ),
        .PCD_NRSTPD(PRESETn),
        .sig_13_56_MHz_RF_carrier(sig_13_56_MHz_RF_carrier),
        .clk(PCLK)
    );

endmodule

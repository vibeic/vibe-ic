// Auto-generated SoC integration wrapper (APB-lite).
// Wraps AHCI_HBA and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: AHCI_HBA
// Register file present (L4): no

`timescale 1ns/1ps

module AHCI_HBA_soc_wrap (
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
    input  A_TX_positive,  // Positive line of SATA differential TX pair; 8b/10b at 1.5/3/6 Gbps.
    input  A_TX_negative,  // Negative line of TX pair.
    input  B_RX_positive,  // Positive line of RX pair.
    input  B_RX_negative,  // Negative line of RX pair.
    input  DEVSLP,  // Sideband; AHCI 1.3.1 DevSleep assertion.
    input  Activity_LED,  // Per-port activity LED; CAP.SAL=1.
    input  GHC_IE_software,  // Global Interrupt Enable.
    input  GHC_HR_software  // HBA Reset.
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
    AHCI_HBA u_AHCI_HBA (
        .A_TX_positive(A_TX_positive),
        .A_TX_negative(A_TX_negative),
        .B_RX_positive(B_RX_positive),
        .B_RX_negative(B_RX_negative),
        .DEVSLP(DEVSLP),
        .Activity_LED(Activity_LED),
        .PERST_PCIe_Fundamental_Reset(PRESETn),
        .REFCLK_PHY(PCLK),
        .GHC_IE_software(GHC_IE_software),
        .GHC_HR_software(GHC_HR_software)
    );

endmodule

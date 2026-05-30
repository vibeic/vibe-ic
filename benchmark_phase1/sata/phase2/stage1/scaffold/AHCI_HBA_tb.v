// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: AHCI_HBA

`timescale 1ns/1ps

module AHCI_HBA_tb;

    reg  A_TX_positive;
    reg  A_TX_negative;
    reg  B_RX_positive;
    reg  B_RX_negative;
    reg  DEVSLP;
    reg  Activity_LED;
    reg  PERST_PCIe_Fundamental_Reset;
    reg  REFCLK_PHY;
    reg  GHC_IE_software;
    reg  GHC_HR_software;

    // DUT instance
    AHCI_HBA u_dut (
        .A_TX_positive(A_TX_positive),
        .A_TX_negative(A_TX_negative),
        .B_RX_positive(B_RX_positive),
        .B_RX_negative(B_RX_negative),
        .DEVSLP(DEVSLP),
        .Activity_LED(Activity_LED),
        .PERST_PCIe_Fundamental_Reset(PERST_PCIe_Fundamental_Reset),
        .REFCLK_PHY(REFCLK_PHY),
        .GHC_IE_software(GHC_IE_software),
        .GHC_HR_software(GHC_HR_software)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial REFCLK_PHY = 1'b0;
    always #5 REFCLK_PHY = ~REFCLK_PHY;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("AHCI_HBA_tb.vcd");
        $dumpvars(0, AHCI_HBA_tb);
        A_TX_positive = 1'b0;
        A_TX_negative = 1'b0;
        B_RX_positive = 1'b0;
        B_RX_negative = 1'b0;
        DEVSLP = 1'b0;
        Activity_LED = 1'b0;
        PERST_PCIe_Fundamental_Reset = 1'b0;
        GHC_IE_software = 1'b0;
        GHC_HR_software = 1'b0;
        PERST_PCIe_Fundamental_Reset = 1'b0;
        #30;
        PERST_PCIe_Fundamental_Reset = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

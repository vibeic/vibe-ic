// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: NFC_ISO14443_Stack

`timescale 1ns/1ps

module NFC_ISO14443_Stack_tb;

    reg  RF_Carrier_13_56_MHz;
    reg  PCD_PICC_modulation;
    reg  PICC_PCD_load_modulation;
    reg  PCD_Host_Bus_SPI_I2C_UART;
    reg  PCD_IRQ;
    reg  PCD_NRSTPD;
    reg  sig_13_56_MHz_RF_carrier;
    reg  clk;

    // DUT instance
    NFC_ISO14443_Stack u_dut (
        .RF_Carrier_13_56_MHz(RF_Carrier_13_56_MHz),
        .PCD_PICC_modulation(PCD_PICC_modulation),
        .PICC_PCD_load_modulation(PICC_PCD_load_modulation),
        .PCD_Host_Bus_SPI_I2C_UART(PCD_Host_Bus_SPI_I2C_UART),
        .PCD_IRQ(PCD_IRQ),
        .PCD_NRSTPD(PCD_NRSTPD),
        .sig_13_56_MHz_RF_carrier(sig_13_56_MHz_RF_carrier),
        .clk(clk)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("NFC_ISO14443_Stack_tb.vcd");
        $dumpvars(0, NFC_ISO14443_Stack_tb);
        RF_Carrier_13_56_MHz = 1'b0;
        PCD_PICC_modulation = 1'b0;
        PICC_PCD_load_modulation = 1'b0;
        PCD_Host_Bus_SPI_I2C_UART = 1'b0;
        PCD_IRQ = 1'b0;
        PCD_NRSTPD = 1'b0;
        sig_13_56_MHz_RF_carrier = 1'b0;
        PCD_NRSTPD = 1'b0;
        #30;
        PCD_NRSTPD = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

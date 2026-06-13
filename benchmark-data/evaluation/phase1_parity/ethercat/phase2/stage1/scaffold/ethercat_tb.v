// Auto-generated testbench scaffold.
// Stimulus + checks are TODO; the scaffold provides clock, reset,
// DUT instantiation, and waveform dump.
// Top module: ethercat

`timescale 1ns/1ps

module ethercat_tb;

    reg  ECAT_P0_TXP_TXN;
    reg  ECAT_P0_RXP_RXN;
    reg  ECAT_P1_TXP_TXN;
    reg  ECAT_P1_RXP_RXN;
    wire ECAT_P2_P3_opt; // inout
    reg  MDC;
    wire MDIO; // inout
    reg  EEPROM_SCL;
    wire EEPROM_SDA; // inout
    reg  SYNC0;
    reg  SYNC1;
    reg  LATCH0;
    reg  LATCH1;
    reg  PDI_CS_n;
    reg  [15:0] PDI_ADDR;
    wire PDI_DATA_7_0_15_0; // inout
    reg  PDI_WR_n_RD_n;
    reg  PDI_READY;
    reg  PDI_IRQ;
    reg  SPI_SCK_MOSI_MISO;
    reg  [31:0] PDI_DIO_OUT;
    reg  [31:0] PDI_DIO_IN;
    reg  LED_RUN;
    reg  LED_ERR;
    reg  LED_LINK_P0_P1;
    reg  LED_ACT_P0_P1;
    reg  RESET_n;
    reg  CLK25;
    reg  RESET;
    reg  INT;
    reg  VDD_GND;

    // DUT instance
    ethercat u_dut (
        .ECAT_P0_TXP_TXN(ECAT_P0_TXP_TXN),
        .ECAT_P0_RXP_RXN(ECAT_P0_RXP_RXN),
        .ECAT_P1_TXP_TXN(ECAT_P1_TXP_TXN),
        .ECAT_P1_RXP_RXN(ECAT_P1_RXP_RXN),
        .ECAT_P2_P3_opt(ECAT_P2_P3_opt),
        .MDC(MDC),
        .MDIO(MDIO),
        .EEPROM_SCL(EEPROM_SCL),
        .EEPROM_SDA(EEPROM_SDA),
        .SYNC0(SYNC0),
        .SYNC1(SYNC1),
        .LATCH0(LATCH0),
        .LATCH1(LATCH1),
        .PDI_CS_n(PDI_CS_n),
        .PDI_ADDR(PDI_ADDR),
        .PDI_DATA_7_0_15_0(PDI_DATA_7_0_15_0),
        .PDI_WR_n_RD_n(PDI_WR_n_RD_n),
        .PDI_READY(PDI_READY),
        .PDI_IRQ(PDI_IRQ),
        .SPI_SCK_MOSI_MISO(SPI_SCK_MOSI_MISO),
        .PDI_DIO_OUT(PDI_DIO_OUT),
        .PDI_DIO_IN(PDI_DIO_IN),
        .LED_RUN(LED_RUN),
        .LED_ERR(LED_ERR),
        .LED_LINK_P0_P1(LED_LINK_P0_P1),
        .LED_ACT_P0_P1(LED_ACT_P0_P1),
        .RESET_n(RESET_n),
        .CLK25(CLK25),
        .RESET(RESET),
        .INT(INT),
        .VDD_GND(VDD_GND)
    );

    // Clock generation — defaults to 100 MHz; override per protocol.
    initial CLK25 = 1'b0;
    always #5 CLK25 = ~CLK25;

    // Reset + waveform + minimal scenario
    initial begin
        $dumpfile("ethercat_tb.vcd");
        $dumpvars(0, ethercat_tb);
        ECAT_P0_TXP_TXN = 1'b0;
        ECAT_P0_RXP_RXN = 1'b0;
        ECAT_P1_TXP_TXN = 1'b0;
        ECAT_P1_RXP_RXN = 1'b0;
        MDC = 1'b0;
        EEPROM_SCL = 1'b0;
        SYNC0 = 1'b0;
        SYNC1 = 1'b0;
        LATCH0 = 1'b0;
        LATCH1 = 1'b0;
        PDI_CS_n = 1'b0;
        PDI_ADDR = 16'b0;
        PDI_WR_n_RD_n = 1'b0;
        PDI_READY = 1'b0;
        PDI_IRQ = 1'b0;
        SPI_SCK_MOSI_MISO = 1'b0;
        PDI_DIO_OUT = 32'b0;
        PDI_DIO_IN = 32'b0;
        LED_RUN = 1'b0;
        LED_ERR = 1'b0;
        LED_LINK_P0_P1 = 1'b0;
        LED_ACT_P0_P1 = 1'b0;
        RESET_n = 1'b0;
        RESET = 1'b0;
        INT = 1'b0;
        VDD_GND = 1'b0;
        RESET_n = 1'b0;
        #30;
        RESET_n = 1'b1;
        // TODO — protocol stimulus + assertions per L10 test cases.
        #1000;
        $finish;
    end

endmodule

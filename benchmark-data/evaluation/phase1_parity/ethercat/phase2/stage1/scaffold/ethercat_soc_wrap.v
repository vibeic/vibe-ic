// Auto-generated SoC integration wrapper (APB-lite).
// Wraps ethercat and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: ethercat
// Register file present (L4): no

`timescale 1ns/1ps

module ethercat_soc_wrap (
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
    input  ECAT_P0_TXP_TXN,  // 100BASE-TX / 1000BASE-T differential TX to upstream.
    input  ECAT_P0_RXP_RXN,  // 100BASE-TX / 1000BASE-T differential RX from upstream.
    input  ECAT_P1_TXP_TXN,  // Forward to downstream SubDevice; loop back on link-down.
    input  ECAT_P1_RXP_RXN,  // Receive returning frame.
    inout  ECAT_P2_P3_opt,  // Optional 3rd/4th ports for tree/star topologies.
    input  MDC,  // MII Management clock, ≤ 2.5 MHz.
    inout  MDIO,  // MII Management data (three-state, 1.5 kΩ pull-up).
    input  EEPROM_SCL,  // I²C-compatible clock to SII EEPROM.
    inout  EEPROM_SDA,  // I²C-compatible data.
    input  SYNC0,  // First DC pulse output; period in 0x0990.
    input  SYNC1,  // Second DC pulse output; period in 0x0994.
    input  LATCH0,  // External event input — capture System Time.
    input  LATCH1,  // Second latch input.
    input  PDI_CS_n,  // Chip select for PDI bus / SPI slave.
    input  [15:0] PDI_ADDR,  // PDI address bus.
    inout  PDI_DATA_7_0_15_0,  // PDI data bus 8/16-bit.
    input  PDI_WR_n_RD_n,  // Write / Read strobe.
    input  PDI_READY,  // Wait-state signal.
    input  PDI_IRQ,  // Interrupt output; mask in 0x0200.
    input  SPI_SCK_MOSI_MISO,  // SPI clock + MOSI + MISO.
    input  [31:0] PDI_DIO_OUT,  // Up to 32 output pins; no µC required.
    input  [31:0] PDI_DIO_IN,  // Up to 32 input pins sampled into DPRAM.
    input  LED_RUN,  // ESM state per IEC 61784-2.
    input  LED_ERR,  // AL Status error.
    input  LED_LINK_P0_P1,  // Per-port link state.
    input  LED_ACT_P0_P1,  // Per-port TX/RX activity.
    input  RESET,  // PHY hardware reset (active LOW); equivalent to BMCR bit 0.15.
    input  INT,  // Optional open-drain interrupt — Link Status change, AutoNeg Complete, Remote Fault, etc.
    input  VDD_GND  // Power. Clause 22.5: 5 V ±5 % @ ≤ 750 mA; modern silicon uses 3.3 / 2.5 / 1.8 V I/O.
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
    ethercat u_ethercat (
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
        .RESET_n(PRESETn),
        .CLK25(PCLK),
        .RESET(RESET),
        .INT(INT),
        .VDD_GND(VDD_GND)
    );

endmodule

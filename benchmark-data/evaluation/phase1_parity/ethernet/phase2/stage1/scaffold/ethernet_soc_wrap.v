// Auto-generated SoC integration wrapper (APB-lite).
// Wraps ethernet and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: ethernet
// Register file present (L4): no

`timescale 1ns/1ps

module ethernet_soc_wrap (
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
    input  [3:0] TXD,  // Nibble-wide transmit data. TXD[0] is LSB. Synchronous to TX_CLK.
    input  TX_EN,  // Transmit Enable. Asserted with first preamble nibble; de-asserted after final FCS nibble.
    input  TX_ER,  // Transmit coding-error indication; PHY emits at least one invalid symbol when asserted with TX_EN.
    input  RX_CLK,  // Receive-side clock recovered from RX data (or nominal when no signal). 25 MHz at 100 Mb/s, 2.5 MHz at 10 Mb/s; 35-65 % duty.
    input  [3:0] RXD,  // Nibble-wide receive data. RXD[0] is LSB. Synchronous to RX_CLK.
    input  RX_DV,  // Receive Data Valid. Encompasses the frame from first preamble nibble through final FCS nibble.
    input  RX_ER,  // Receive coding error. Asserted by PHY to flag invalid line symbols in the current frame. Also used (with RXD = 1110, RX_DV = 0) to signal False Carrier.
    input  CRS,  // Carrier Sense. Asserted whenever TX or RX medium is non-idle; held throughout a collision condition. Half-duplex only (ignored in full-duplex).
    input  COL,  // Collision Detect. Asserted on half-duplex collision; behaviour undefined in full-duplex.
    input  GTX_CLK,  // Gigabit transmit clock — 125 MHz, sourced by MAC. Used at 1 Gb/s; replaces TX_CLK direction.
    input  RGMII,  // Reduced-pin GMII — DDR data path at 125 MHz; 12 wires total (vs GMII's 24).
    input  MDC,  // Management Data Clock; ≤ 2.5 MHz; aperiodic; period ≥ 400 ns; H + L ≥ 160 ns each.
    inout  MDIO,  // Serial management data. 1.5 kΩ pull-up at PHY; 2 kΩ pull-down at STA (per Clause 22.4.4.2).
    inout  MDI_pair_s,  // Line-coded signal to the network medium per PMD class (Manchester / MLT-3 / NRZI / PAM5 / 8B/10B-NRZ / PAM4).
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
    ethernet u_ethernet (
        .TX_CLK(PCLK),
        .TXD(TXD),
        .TX_EN(TX_EN),
        .TX_ER(TX_ER),
        .RX_CLK(RX_CLK),
        .RXD(RXD),
        .RX_DV(RX_DV),
        .RX_ER(RX_ER),
        .CRS(CRS),
        .COL(COL),
        .GTX_CLK(GTX_CLK),
        .RGMII(RGMII),
        .MDC(MDC),
        .MDIO(MDIO),
        .MDI_pair_s(MDI_pair_s),
        .RESET(PRESETn),
        .INT(INT),
        .VDD_GND(VDD_GND)
    );

endmodule

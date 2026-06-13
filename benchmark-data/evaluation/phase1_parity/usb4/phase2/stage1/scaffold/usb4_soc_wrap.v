// Auto-generated SoC integration wrapper (APB-lite).
// Wraps usb4 and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: usb4
// Register file present (L4): no

`timescale 1ns/1ps

module usb4_soc_wrap (
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
    input  TX1_TX1,  // High-speed lane 0 transmit.
    input  RX1_RX1,  // High-speed lane 0 receive.
    input  TX2_TX2,  // High-speed lane 1 transmit (bonded with lane 0).
    input  RX2_RX2,  // High-speed lane 1 receive.
    inout  SBU1_SBU2,  // Sideband management channel between adjacent routers.
    inout  CC1_CC2,  // USB-C Configuration Channel; USB Power Delivery + orientation.
    input  VBUS,  // Bus power per negotiated PD contract (up to 100 W / 240 W EPR).
    input  D_D,  // USB 2.0 backward-compatibility pair.
    input  GND  // Common ground.
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
    usb4 u_usb4 (
        .TX1_TX1(TX1_TX1),
        .RX1_RX1(RX1_RX1),
        .TX2_TX2(TX2_TX2),
        .RX2_RX2(RX2_RX2),
        .SBU1_SBU2(SBU1_SBU2),
        .CC1_CC2(CC1_CC2),
        .VBUS(VBUS),
        .D_D(D_D),
        .GND(GND),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

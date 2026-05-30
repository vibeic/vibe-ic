// Auto-generated SoC integration wrapper (APB-lite).
// Wraps hdmi and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: hdmi
// Register file present (L4): yes

`timescale 1ns/1ps

module hdmi_soc_wrap (
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
    inout  SDA,  // Serial Data Line. Carries address byte + data bytes + ACK/NACK bit. Open-drain, wired-AND: any device can pull LOW; HIGH is achieved by all devices releasing the line.
    input  SCL,  // Serial Clock Line. Master drives clock pulses; slave may pull LOW to stretch. 9 pulses per byte (8 data + 1 ACK).
    input  VDD,  // Supply voltage. Determines VIL (0.3 VDD) and VIH (0.7 VDD) thresholds for non-legacy devices.
    input  Rp,  // Pull-up resistor on SDA and SCL to VDD; sized per mode and bus capacitance.
    input  GND,  // Common ground reference for all devices on the bus.
    input  hsync,
    input  vsync,
    input  dken,
    input  de,
    output dvi
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 15 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          VEN_ID [16b, r]
    // offset          DEV_ID [16b, r]
    // offset          REV_ID [8b, r]
    // offset          RESERVED_07_05 [24b, r]
    // offset          CTL_1_MODE [8b, rw]
    // offset          CTL_2_MODE [8b, rw]
    // offset          CTL_3_MODE [8b, rw]
    // offset          CFG [8b, r]
    // offset          DE_DLY [8b, rw]
    // offset          DE_CTL [8b, rw]
    // offset          DE_TOP [8b, rw]
    // offset          DE_CNT [11b, rw]
    // offset          DE_LIN [11b, rw]
    // offset          H_RES [11b, r]
    // offset          V_RES [11b, r]

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
    hdmi u_hdmi (
        .SDA(SDA),
        .SCL(SCL),
        .VDD(VDD),
        .Rp(Rp),
        .GND(GND),
        .hsync(hsync),
        .vsync(vsync),
        .dken(dken),
        .de(de),
        .dvi(dvi),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

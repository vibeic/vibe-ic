// Auto-generated SoC integration wrapper (APB-lite).
// Wraps chip_top and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: chip_top
// Register file present (L4): yes

`timescale 1ns/1ps

module chip_top_soc_wrap (
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
    output TXp,  // Positive line of the differential transmit pair.
    output TXn,  // Negative line of the differential transmit pair.
    input  RXp,  // Positive line of the differential receive pair.
    input  RXn,  // Negative line of the differential receive pair.
    input  WAKE,  // Pulled LOW to resume from L2/L3.
    input  VBUS,  // Bus power per the USB Power Delivery contract.
    input  GND,  // Common ground.
    input  clk,
    input  reset_n,
    input  id_bus
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 4 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          IR [2b, shift-in / shift-out via tdi / tdo in shiftir; parallel-latched to current-instruction on falling edge of tck in updateir.]
    // offset          Bypass [1b, shift-in / shift-out via tdi / tdo in shiftdr (when bypass / clamp / highz is current).]
    // offset          BSR [1b, shift-in / shift-out via tdi / tdo in shiftdr (when sample/preload / extest / intest is current).]
    // offset          IDCODE [32b, shift-out via tdo in shiftdr (when idcode / usercode is current). the register is parallel-loaded with the device id in capturedr; shifted contents into tdi are typically ignored.]

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
    chip_top u_chip_top (
        .TXp(TXp),
        .TXn(TXn),
        .RXp(RXp),
        .RXn(RXn),
        .REFCLK(PCLK),
        .PERST(PRESETn),
        .WAKE(WAKE),
        .VBUS(VBUS),
        .GND(GND),
        .clk(clk),
        .reset_n(reset_n),
        .id_bus(id_bus)
    );

endmodule

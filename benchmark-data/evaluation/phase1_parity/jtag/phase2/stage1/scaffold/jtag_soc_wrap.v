// Auto-generated SoC integration wrapper (APB-lite).
// Wraps jtag and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: jtag
// Register file present (L4): yes

`timescale 1ns/1ps

module jtag_soc_wrap (
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
    inout  TCK,  // Test Clock. Tester-generated free-running clock; FSM samples TMS + TDI on the rising edge; TDO updates on the falling edge.
    inout  TMS,  // Test Mode Select. Drives the 16-state TAP FSM transitions; sampled on TCK rising edge. TMS=1 × 5 TCKs forces TestLogicReset.
    inout  TDI,  // Test Data In. Shift input to selected register (IR in ShiftIR, selected DR in ShiftDR); sampled LSB-first on TCK rising edge.
    inout  TDO,  // Test Data Out. Shift output of selected register; driven LSB-first on TCK falling edge; high-impedance outside ShiftIR / ShiftDR.
    inout  TRST,  // Optional asynchronous Test Reset (active LOW). When LOW, forces TAP FSM to TestLogicReset independent of TCK / TMS.
    input  VDD_IO_per_device,  // Drives the TAP pins' I/O voltage; per-device datasheet.
    input  GND  // Common ground reference for the tester and all devices in the chain.
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
    jtag u_jtag (
        .TCK(TCK),
        .TMS(TMS),
        .TDI(TDI),
        .TDO(TDO),
        .TRST(TRST),
        .VDD_IO_per_device(VDD_IO_per_device),
        .GND(GND),
        .clk(PCLK)
    );

endmodule

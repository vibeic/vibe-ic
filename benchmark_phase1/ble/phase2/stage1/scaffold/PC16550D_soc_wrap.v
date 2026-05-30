// Auto-generated SoC integration wrapper (APB-lite).
// Wraps PC16550D and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: PC16550D
// Register file present (L4): yes

`timescale 1ns/1ps

module PC16550D_soc_wrap (
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
    inout  ANT,  // 2.4 GHz antenna interface; single-ended or differential depending on radio architecture.
    input  RF_GND,  // Ground reference for RF signal.
    input  VDD,  // Radio + baseband supply 1.8 / 3.0 / 3.3 V.
    input  VSS,  // Common ground.
    input  Sleep_Clock,  // Sleep clock for deep-sleep wake-up; 21..500 ppm SCA options.
    input  clk  // System clock (auto-added by scaffold)
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 51 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x9E8B00 MEMMAP_LOW_009E8B00 [8b, ro]
    // offset 0x9E8B3F MEMMAP_HIGH_009E8B3F [8b, ro]
    // offset 0x0040   MEMMAP_LOW_00000040 [8b, ro]
    // offset 0xFFFF   MEMMAP_HIGH_0000FFFF [8b, ro]
    // offset 0x0020   MEMMAP_LOW_00000020 [8b, ro]
    // offset 0x003E   MEMMAP_HIGH_0000003E [8b, ro]
    // offset 0x007F   MEMMAP_HIGH_0000007F [8b, ro]
    // offset 0x0001   MEMMAP_LOW_00000001 [8b, ro]
    // offset 0x0EFF   MEMMAP_HIGH_00000EFF [8b, ro]
    // offset 0x0100   MEMMAP_LOW_00000100 [8b, ro]
    // offset 0x01FF   MEMMAP_HIGH_000001FF [8b, ro]
    // offset 0x0300   MEMMAP_LOW_00000300 [8b, ro]
    // offset 0x03FF   MEMMAP_HIGH_000003FF [8b, ro]
    // offset 0x0500   MEMMAP_LOW_00000500 [8b, ro]
    // offset 0x05FF   MEMMAP_HIGH_000005FF [8b, ro]
    // offset 0x0700   MEMMAP_LOW_00000700 [8b, ro]
    // offset 0x07FF   MEMMAP_HIGH_000007FF [8b, ro]
    // offset 0x0900   MEMMAP_LOW_00000900 [8b, ro]
    // offset 0x09FF   MEMMAP_HIGH_000009FF [8b, ro]
    // offset 0x0B00   MEMMAP_LOW_00000B00 [8b, ro]
    // offset 0x0BFF   MEMMAP_HIGH_00000BFF [8b, ro]
    // offset 0x3FFF   MEMMAP_HIGH_00003FFF [8b, ro]
    // offset 0x0000   MEMMAP_LOW_00000000 [8b, ro]
    // offset 0x0007   MEMMAP_LOW_00000007 [8b, ro]
    // offset 0x0002   MEMMAP_LOW_00000002 [8b, ro]
    // offset 0x000F423F MEMMAP_HIGH_000F423F [8b, ro]
    // offset 0xFF     MEMMAP_HIGH_000000FF [8b, ro]
    // offset 0x80     MEMMAP_LOW_00000080 [8b, ro]
    // offset 0x9F     MEMMAP_HIGH_0000009F [8b, ro]
    // offset 0xE0     MEMMAP_LOW_000000E0 [8b, ro]
    // offset 0x05     MEMMAP_LOW_00000005 [8b, ro]
    // offset 0x0D     MEMMAP_LOW_0000000D [8b, ro]
    // offset 0x0F     MEMMAP_HIGH_0000000F [8b, ro]
    // offset 0xFFFFFFFE MEMMAP_HIGH_FFFFFFFE [8b, ro]
    // offset 0x25     MEMMAP_LOW_00000025 [8b, ro]
    // offset 0x27     MEMMAP_HIGH_00000027 [8b, ro]
    // offset 0xEF     MEMMAP_HIGH_000000EF [8b, ro]
    // offset 0x03     MEMMAP_HIGH_00000003 [8b, ro]
    // offset 0x04     MEMMAP_LOW_00000004 [8b, ro]
    // offset 0x08     MEMMAP_LOW_00000008 [8b, ro]
    // offset 0x0B     MEMMAP_HIGH_0000000B [8b, ro]
    // offset 0x0C     MEMMAP_LOW_0000000C [8b, ro]
    // offset 0x10     MEMMAP_LOW_00000010 [8b, ro]
    // offset 0x13     MEMMAP_HIGH_00000013 [8b, ro]
    // offset 0x4B     MEMMAP_HIGH_0000004B [8b, ro]
    // offset 0x3F     MEMMAP_HIGH_0000003F [8b, ro]
    // offset 0x28     MEMMAP_LOW_00000028 [8b, ro]
    // offset 0x00A4   MEMMAP_LOW_000000A4 [8b, ro]
    // offset 0x2148   MEMMAP_HIGH_00002148 [8b, ro]
    // offset 0x001B   MEMMAP_LOW_0000001B [8b, ro]
    // offset 0x14     MEMMAP_HIGH_00000014 [8b, ro]

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
    PC16550D u_PC16550D (
        .ANT(ANT),
        .RF_GND(RF_GND),
        .VDD(VDD),
        .VSS(VSS),
        .Active_Clock(PCLK),
        .Sleep_Clock(Sleep_Clock),
        .clk(clk),
        .rst_n(PRESETn)
    );

endmodule

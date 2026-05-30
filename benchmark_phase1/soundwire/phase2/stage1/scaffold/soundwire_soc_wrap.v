// Auto-generated SoC integration wrapper (APB-lite).
// Wraps soundwire and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: soundwire
// Register file present (L4): yes

`timescale 1ns/1ps

module soundwire_soc_wrap (
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
    input  SoundWire_Data_Lane_0,  // Carries the embedded 48-bit Control Word + audio Payload (PCM, PDM, raw DATA, BRA blocks) + PHY arbitration. Modified-NRZI: Logic 1 = active level change, Logic 0 = passive unchanged level held by bus-keeper. DDR — two BitSlots per Clock period.
    output SoundWire_Data_Lane_1_7_optional,  // Optional additional Data lanes for higher aggregate bandwidth. Lane 0 is shared between all devices (Col 0 Rows 0..47 reserved for Command Word). Lanes 1..7 may be shared or private to a group of devices; for device-to-device lanes a bus-keeper must be enabled on one of the devices. No restrictions on Lane 1..7 — all bits including Col 0 can be used.
    input  VDD,  // Supply voltage (1.2 V or 1.8 V typical) for SoundWire I/O drivers.
    input  GND,  // Common ground reference for all devices on the bus.
    input  Bus_Keeper  // Required active circuit (typically on Master) that weakly holds the last driven level on SoundWire_Data; can be disabled via M_KeeperOff PHY Test Mode for replacement by external test equipment.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 8 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x0      MEMMAP_LOW_00000000 [8b, ro]
    // offset 0xFFF    MEMMAP_HIGH_00000FFF [8b, ro]
    // offset 0x1000   MEMMAP_LOW_00001000 [8b, ro]
    // offset 0x17FF   MEMMAP_HIGH_000017FF [8b, ro]
    // offset 0x2000   MEMMAP_LOW_00002000 [8b, ro]
    // offset 0xFFFF   MEMMAP_HIGH_0000FFFF [8b, ro]
    // offset 0x10000  MEMMAP_LOW_00010000 [8b, ro]
    // offset 0x3FFFFFFF MEMMAP_HIGH_3FFFFFFF [8b, ro]

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
    soundwire u_soundwire (
        .SoundWire_Clock(PCLK),
        .SoundWire_Data_Lane_0(SoundWire_Data_Lane_0),
        .SoundWire_Data_Lane_1_7_optional(SoundWire_Data_Lane_1_7_optional),
        .VDD(VDD),
        .GND(GND),
        .Bus_Keeper(Bus_Keeper),
        .rst_n(PRESETn)
    );

endmodule

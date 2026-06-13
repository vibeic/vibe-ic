// Auto-generated SoC integration wrapper (APB-lite).
// Wraps dali_control_gear_top and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: dali_control_gear_top
// Register file present (L4): yes

`timescale 1ns/1ps

module dali_control_gear_top_soc_wrap (
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
    input  VBUS,  // 9.5..22.5 V DC.
    input  IBUS,  // ≤ 250 mA total.
    input  BUS_IDLE_STATE,  // Passive HIGH; transmitters pull LOW.
    input  TE,  // Half-bit time = 416.67 μs.
    input  BIT_TIME,  // Full bit time = 833.33 μs.
    input  BYTE_ORDER  // MSB first within each byte.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 20 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          Power_On_Level [8b, dali write via store dtr as power on level / read via query]
    // offset 1        System_Failure_Level [8b, dali write via store dtr as system failure level / read via query]
    // offset 2        Minimum_Level [8b, dali write via store dtr as min level / read via query]
    // offset 3        Maximum_Level [8b, dali write via store dtr as max level / read via query]
    // offset 4        Fade_Rate [8b, dali write via store dtr as fade rate / read via query]
    // offset 5        Fade_Time [8b, dali write via store dtr as fade time / read via query]
    // offset 6        Short_Address [8b, dali write via store dtr as short address / special program / read via special query short address]
    // offset 7        Group_0_7 [8b, dali write via add/remove from group]
    // offset 8        Group_8_15 [8b, dali write via add/remove from group]
    // offset 9..24    Scene_0_15 [8b, dali write via store dtr as scene n / remove from scene n / read via query scene level n]
    // offset 25..27   Random_Address [24b, internal — randomize generated; compare/withdraw compare]
    // offset 28       Fast_Fade_Time [8b, dali write via store dtr as fast fade time / read via query]
    // offset 29       Failure_Status [8b, internal status latched on fault; read via query 0x92/0x94]
    // offset 30       Operating_Mode [8b, internal / vendor-specific]
    // offset 31       Dimming_Curve [8b, internal — vendor-defined]
    // offset RAM-only DTR [8b, dali special command dtr (0xa3)]
    // offset RAM-only DTR1 [8b, dali special command dtr1 (0xc3)]
    // offset RAM-only DTR2 [8b, dali special command dtr2 (0xc5)]
    // offset RAM-only Search_Address [24b, dali special search h/m/l (0xb1/0xb3/0xb5)]
    // offset RAM      Actual_Level [8b, internal — read via query actual level (0xa0)]

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
    dali_control_gear_top u_dali_control_gear_top (
        .VBUS(VBUS),
        .IBUS(IBUS),
        .BUS_IDLE_STATE(BUS_IDLE_STATE),
        .TE(TE),
        .BIT_TIME(BIT_TIME),
        .BYTE_ORDER(BYTE_ORDER),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

// Auto-generated SoC integration wrapper (APB-lite).
// Wraps modbus_server_top and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: modbus_server_top
// Register file present (L4): yes

`timescale 1ns/1ps

module modbus_server_top_soc_wrap (
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
    input  BUS_IDLE_STATE,  // Serial line idle = UART mark (HIGH).
    input  TCP_PORT_502,  // IANA-reserved server port for MODBUS TCP.
    input  BIG_ENDIAN_ORDER  // All multi-byte numerical quantities are MSB-first on the wire.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 2 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x80     MEMMAP_LOW_00000080 [8b, ro]
    // offset 0xFF     MEMMAP_HIGH_000000FF [8b, ro]

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
    modbus_server_top u_modbus_server_top (
        .BUS_IDLE_STATE(BUS_IDLE_STATE),
        .TCP_PORT_502(TCP_PORT_502),
        .BIG_ENDIAN_ORDER(BIG_ENDIAN_ORDER),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

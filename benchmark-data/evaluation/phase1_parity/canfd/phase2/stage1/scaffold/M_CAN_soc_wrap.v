// Auto-generated SoC integration wrapper (APB-lite).
// Wraps M_CAN and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: M_CAN
// Register file present (L4): yes

`timescale 1ns/1ps

module M_CAN_soc_wrap (
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
    inout  CAN_bus_single_channel,  // Single shared serial channel.
    input  Generic_Slave_Interface_Host_CPU,  // 8/16/32-bit register access.
    input  Generic_Master_Interface_Message_RAM,  // Read / write to Message RAM.
    input  Interrupt_lines,  // Two CPU lines m_can_int0 + m_can_int1.
    input  Extension_Interface,  // All IR flags + selected status/control signals.
    input  TSU_Interface,  // 32-bit external timestamping.
    input  DMU_Interface,  // Debug-on-CAN hand-off.
    input  Power_down_Interface  // Clock-stop handshake.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 7 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x00     MEMMAP_LOW_00000000 [8b, ro]
    // offset 0x1F     MEMMAP_HIGH_0000001F [8b, ro]
    // offset 0x1      MEMMAP_LOW_00000001 [8b, ro]
    // offset 0xF      MEMMAP_HIGH_0000000F [8b, ro]
    // offset 0x7F     MEMMAP_HIGH_0000007F [8b, ro]
    // offset 0x1FF    MEMMAP_HIGH_000001FF [8b, ro]
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
    M_CAN u_M_CAN (
        .CAN_bus_single_channel(CAN_bus_single_channel),
        .Generic_Slave_Interface_Host_CPU(Generic_Slave_Interface_Host_CPU),
        .Generic_Master_Interface_Message_RAM(Generic_Master_Interface_Message_RAM),
        .Interrupt_lines(Interrupt_lines),
        .Extension_Interface(Extension_Interface),
        .TSU_Interface(TSU_Interface),
        .DMU_Interface(DMU_Interface),
        .Power_down_Interface(Power_down_Interface),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

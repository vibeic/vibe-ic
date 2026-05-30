// Auto-generated SoC integration wrapper (APB-lite).
// Wraps lin_node and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: lin_node
// Register file present (L4): yes

`timescale 1ns/1ps

module lin_node_soc_wrap (
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
    inout  CAN_bus_single_channel,  // Single shared serial channel carrying NRZ-coded bit stream; dominant overrides recessive on simultaneous transmission.
    input  response_error,  // 1-bit scalar published by every slave in one of its transmitted unconditional frames. Cluster-wide health indicator.
    input  NAD,  // 8-bit Node Address for Diagnostics, used in master-request / slave-response frames to address a specific slave.
    input  Supplier_ID_Function_ID_Variant  // 16-bit + 16-bit + 8-bit slave identification, returned by Read by Identifier.
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
    // offset 0xB8     MEMMAP_LOW_000000B8 [8b, ro]
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
    lin_node u_lin_node (
        .CAN_bus_single_channel(CAN_bus_single_channel),
        .response_error(response_error),
        .NAD(NAD),
        .Supplier_ID_Function_ID_Variant(Supplier_ID_Function_ID_Variant),
        .clk(PCLK),
        .rst_n(PRESETn)
    );

endmodule

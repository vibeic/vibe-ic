// servile_ram_if.v
// GENERATED (authored from L8 spec) — Servile wrapper RF/RAM interface adapter.
//
// Role (L8.2.2 / L8.2.5): converge the core's 32-bit word memory bus onto the
// chip-level byte-wide external SRAM bus (I-mem + D-mem + RF share one SRAM).
//
// The external bus is byte-wide (8-bit data) with a 10-bit byte address per L3.
// This adapter performs a 4-beat byte gather on reads (little-endian) and a
// byte-enabled scatter on writes, presenting a single-word handshake to the core.
//
// Clean-room implementation. Single clock, synchronous active-high reset.

module servile_ram_if #(
    parameter integer AW = 10
) (
    input  wire            i_clk,
    input  wire            i_rst,
    // core-side word bus
    input  wire [AW-1:0]   i_core_addr,
    input  wire [31:0]     i_core_wdata,
    output reg  [31:0]     o_core_rdata,
    input  wire            i_core_we,
    input  wire            i_core_re,
    input  wire [3:0]      i_core_be,
    input  wire            i_core_cyc,
    output reg             o_core_ack,   // pulses high for one cycle when the word access completes
    // chip-side byte SRAM bus
    output reg  [AW-1:0]   o_sram_addr,
    output reg  [7:0]      o_sram_wdata,
    input  wire [7:0]      i_sram_rdata,
    output reg             o_sram_we,
    output reg             o_sram_cyc
);

    // 4-beat byte sequencer
    localparam [2:0] B_IDLE = 3'd0;
    localparam [2:0] B_B0   = 3'd1;
    localparam [2:0] B_B1   = 3'd2;
    localparam [2:0] B_B2   = 3'd3;
    localparam [2:0] B_B3   = 3'd4;

    reg [2:0]  bstate;
    reg [31:0] wdata_lat;
    reg [3:0]  be_lat;
    reg        we_lat;
    reg [AW-1:0] base_addr;
    reg [31:0] rd_acc;

    always @(posedge i_clk) begin
        if (i_rst) begin
            bstate       <= B_IDLE;
            o_sram_addr  <= {AW{1'b0}};
            o_sram_wdata <= 8'b0;
            o_sram_we    <= 1'b0;
            o_sram_cyc   <= 1'b0;
            o_core_ack   <= 1'b0;
            o_core_rdata <= 32'b0;
            wdata_lat    <= 32'b0;
            be_lat       <= 4'b0;
            we_lat       <= 1'b0;
            base_addr    <= {AW{1'b0}};
            rd_acc       <= 32'b0;
        end else begin
            o_core_ack <= 1'b0;  // single-cycle ack default
            case (bstate)
                B_IDLE: begin
                    o_sram_we  <= 1'b0;
                    o_sram_cyc <= 1'b0;
                    if (i_core_cyc) begin
                        base_addr   <= i_core_addr;
                        wdata_lat   <= i_core_wdata;
                        be_lat      <= i_core_be;
                        we_lat      <= i_core_we;
                        o_sram_addr <= i_core_addr;
                        o_sram_we   <= i_core_we & i_core_be[0];
                        o_sram_wdata<= i_core_wdata[7:0];
                        o_sram_cyc  <= 1'b1;
                        bstate      <= B_B0;
                    end
                end
                B_B0: begin
                    rd_acc[7:0] <= i_sram_rdata;
                    o_sram_addr <= base_addr + {{(AW-1){1'b0}}, 1'b1};
                    o_sram_we   <= we_lat & be_lat[1];
                    o_sram_wdata<= wdata_lat[15:8];
                    bstate      <= B_B1;
                end
                B_B1: begin
                    rd_acc[15:8] <= i_sram_rdata;
                    o_sram_addr  <= base_addr + 2;
                    o_sram_we    <= we_lat & be_lat[2];
                    o_sram_wdata <= wdata_lat[23:16];
                    bstate       <= B_B2;
                end
                B_B2: begin
                    rd_acc[23:16] <= i_sram_rdata;
                    o_sram_addr   <= base_addr + 3;
                    o_sram_we     <= we_lat & be_lat[3];
                    o_sram_wdata  <= wdata_lat[31:24];
                    bstate        <= B_B3;
                end
                B_B3: begin
                    o_core_rdata <= {i_sram_rdata, rd_acc[23:0]};
                    o_sram_we    <= 1'b0;
                    o_sram_cyc   <= 1'b0;
                    o_core_ack   <= 1'b1;   // word access complete this cycle
                    bstate       <= B_IDLE;
                end
                default: bstate <= B_IDLE;
            endcase
        end
    end

endmodule

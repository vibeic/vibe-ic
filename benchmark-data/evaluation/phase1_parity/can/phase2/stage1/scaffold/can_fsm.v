// Auto-generated FSM skeleton.
// 17 states — transitions are TODO; only state enum + reset path are generated.
// Top module: can

`timescale 1ns/1ps

module can_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_TX_BUS_IDLE = 5'd0;
    localparam [4:0] S_TX_SOF = 5'd1;
    localparam [4:0] S_TX_ARBITRATION = 5'd2;
    localparam [4:0] S_TX_CONTROL = 5'd3;
    localparam [4:0] S_TX_DATA = 5'd4;
    localparam [4:0] S_TX_CRC = 5'd5;
    localparam [4:0] S_TX_ACK_SLOT = 5'd6;
    localparam [4:0] S_TX_ACK_DELIM = 5'd7;
    localparam [4:0] S_TX_EOF = 5'd8;
    localparam [4:0] S_TX_INTERMISSION = 5'd9;
    localparam [4:0] S_TX_SUSPEND = 5'd10;
    localparam [4:0] S_RX_BUS_IDLE = 5'd11;
    localparam [4:0] S_RX_HARD_SYNC = 5'd12;
    localparam [4:0] S_RX_ARBITRATION = 5'd13;
    localparam [4:0] S_RX_DATA_COLLECT = 5'd14;
    localparam [4:0] S_RX_ACK_GEN = 5'd15;
    localparam [4:0] S_RX_VALIDATE = 5'd16;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_TX_BUS_IDLE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

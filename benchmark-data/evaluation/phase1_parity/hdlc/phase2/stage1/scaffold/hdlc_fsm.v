// Auto-generated FSM skeleton.
// 16 states — transitions are TODO; only state enum + reset path are generated.
// Top module: hdlc

`timescale 1ns/1ps

module hdlc_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_TX_IDLE = 4'd0;
    localparam [3:0] S_TX_OPEN_FLAG = 4'd1;
    localparam [3:0] S_TX_ADDRESS = 4'd2;
    localparam [3:0] S_TX_CONTROL = 4'd3;
    localparam [3:0] S_TX_INFO = 4'd4;
    localparam [3:0] S_TX_FCS = 4'd5;
    localparam [3:0] S_TX_CLOSE_FLAG = 4'd6;
    localparam [3:0] S_TX_ABORT = 4'd7;
    localparam [3:0] S_RX_HUNT = 4'd8;
    localparam [3:0] S_RX_FLAG_LOCKED = 4'd9;
    localparam [3:0] S_RX_ADDRESS = 4'd10;
    localparam [3:0] S_RX_CONTROL = 4'd11;
    localparam [3:0] S_RX_INFO = 4'd12;
    localparam [3:0] S_RX_FCS_CHECK = 4'd13;
    localparam [3:0] S_RX_ABORT = 4'd14;
    localparam [3:0] S_RX_DELIVER = 4'd15;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_TX_IDLE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

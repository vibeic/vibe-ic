// Auto-generated FSM skeleton.
// 26 states — transitions are TODO; only state enum + reset path are generated.
// Top module: M_CAN

`timescale 1ns/1ps

module M_CAN_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_STORED = 5'd0;
    localparam [4:0] S_THREE = 5'd1;
    localparam [4:0] S_TX_BUS_IDLE = 5'd2;
    localparam [4:0] S_TX_SOF = 5'd3;
    localparam [4:0] S_TX_ARBITRATION = 5'd4;
    localparam [4:0] S_TX_CONTROL_CL = 5'd5;
    localparam [4:0] S_TX_CONTROL_FD = 5'd6;
    localparam [4:0] S_TX_DATA = 5'd7;
    localparam [4:0] S_TX_STUFF_CNT = 5'd8;
    localparam [4:0] S_TX_CRC = 5'd9;
    localparam [4:0] S_TX_BRS_OFF = 5'd10;
    localparam [4:0] S_TX_ACK_SLOT = 5'd11;
    localparam [4:0] S_TX_ACK_DELIM = 5'd12;
    localparam [4:0] S_TX_EOF = 5'd13;
    localparam [4:0] S_TX_INTERMISSION = 5'd14;
    localparam [4:0] S_TX_SUSPEND = 5'd15;
    localparam [4:0] S_TX_PAUSE = 5'd16;
    localparam [4:0] S_RX_BUS_IDLE = 5'd17;
    localparam [4:0] S_RX_HARD_SYNC = 5'd18;
    localparam [4:0] S_RX_ARBITRATION = 5'd19;
    localparam [4:0] S_RX_FDF_DETECT = 5'd20;
    localparam [4:0] S_RX_BRS_DETECT = 5'd21;
    localparam [4:0] S_RX_DATA_COLLECT = 5'd22;
    localparam [4:0] S_RX_CRC_CHECK = 5'd23;
    localparam [4:0] S_RX_ACK_GEN = 5'd24;
    localparam [4:0] S_RX_VALIDATE = 5'd25;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_STORED;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

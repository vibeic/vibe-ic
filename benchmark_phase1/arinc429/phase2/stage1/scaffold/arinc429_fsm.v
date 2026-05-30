// Auto-generated FSM skeleton.
// 15 states — transitions are TODO; only state enum + reset path are generated.
// Top module: arinc429

`timescale 1ns/1ps

module arinc429_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_TX_IDLE = 4'd0;
    localparam [3:0] S_TX_GAP = 4'd1;
    localparam [3:0] S_TX_LABEL = 4'd2;
    localparam [3:0] S_TX_SDI = 4'd3;
    localparam [3:0] S_TX_DATA = 4'd4;
    localparam [3:0] S_TX_SSM = 4'd5;
    localparam [3:0] S_TX_PARITY = 4'd6;
    localparam [3:0] S_TX_RETURN_TO_IDLE = 4'd7;
    localparam [3:0] S_RX_IDLE = 4'd8;
    localparam [3:0] S_RX_GAP_DETECT = 4'd9;
    localparam [3:0] S_RX_BIT_SAMPLE = 4'd10;
    localparam [3:0] S_RX_DESHIFT_WORD = 4'd11;
    localparam [3:0] S_RX_PARITY_CHECK = 4'd12;
    localparam [3:0] S_RX_LABEL_FILTER = 4'd13;
    localparam [3:0] S_RX_SSM_DECODE = 4'd14;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_TX_IDLE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

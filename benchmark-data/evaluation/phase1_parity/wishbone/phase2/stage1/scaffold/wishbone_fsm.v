// Auto-generated FSM skeleton.
// 9 states — transitions are TODO; only state enum + reset path are generated.
// Top module: wishbone

`timescale 1ns/1ps

module wishbone_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_ENOUGH = 4'd0;
    localparam [3:0] S_FIND = 4'd1;
    localparam [3:0] S_DIFFICULT = 4'd2;
    localparam [3:0] S_PREDICT = 4'd3;
    localparam [3:0] S_NEEDED = 4'd4;
    localparam [3:0] S_SUPERVISE = 4'd5;
    localparam [3:0] S_STATE = 4'd6;
    localparam [3:0] S_WAIT4ACK = 4'd7;
    localparam [3:0] S_IDLE = 4'd8;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_ENOUGH;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

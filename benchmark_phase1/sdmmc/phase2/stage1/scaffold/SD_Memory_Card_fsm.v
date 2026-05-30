// Auto-generated FSM skeleton.
// 25 states — transitions are TODO; only state enum + reset path are generated.
// Top module: SD_Memory_Card

`timescale 1ns/1ps

module SD_Memory_Card_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_PROGRAMMING = 5'd0;
    localparam [4:0] S_CMD42 = 5'd1;
    localparam [4:0] S_MANDATORY = 5'd2;
    localparam [4:0] S_INITIALIZE = 5'd3;
    localparam [4:0] S_ZERO = 5'd4;
    localparam [4:0] S_ABLE = 5'd5;
    localparam [4:0] S_SELECT = 5'd6;
    localparam [4:0] S_BACK = 5'd7;
    localparam [4:0] S_STAND = 5'd8;
    localparam [4:0] S_HOST = 5'd9;
    localparam [4:0] S_RESERVE = 5'd10;
    localparam [4:0] S_REFER = 5'd11;
    localparam [4:0] S_TABLE = 5'd12;
    localparam [4:0] S_RESPOND = 5'd13;
    localparam [4:0] S_IDENTIFICATION = 5'd14;
    localparam [4:0] S_SENT = 5'd15;
    localparam [4:0] S_ALLOWS = 5'd16;
    localparam [4:0] S_ASSIGNED = 5'd17;
    localparam [4:0] S_COMMAND = 5'd18;
    localparam [4:0] S_SWITCH = 5'd19;
    localparam [4:0] S_RETURN = 5'd20;
    localparam [4:0] S_USED = 5'd21;
    localparam [4:0] S_VERIFY = 5'd22;
    localparam [4:0] S_FORCE = 5'd23;
    localparam [4:0] S_TRAN = 5'd24;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_PROGRAMMING;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

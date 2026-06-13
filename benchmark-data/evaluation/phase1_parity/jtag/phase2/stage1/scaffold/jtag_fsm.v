// Auto-generated FSM skeleton.
// 15 states — transitions are TODO; only state enum + reset path are generated.
// Top module: jtag

`timescale 1ns/1ps

module jtag_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_RUN = 4'd0;
    localparam [3:0] S_RESPONDS = 4'd1;
    localparam [3:0] S_ADJACENT = 4'd2;
    localparam [3:0] S_USED = 4'd3;
    localparam [3:0] S_SPECIFY_SIG = 4'd4;
    localparam [3:0] S_GOES = 4'd5;
    localparam [3:0] S_DREXIT1 = 4'd6;
    localparam [3:0] S_DRPAUSE = 4'd7;
    localparam [3:0] S_CONFIGURED = 4'd8;
    localparam [3:0] S_TEST = 4'd9;
    localparam [3:0] S_PERFORM = 4'd10;
    localparam [3:0] S_TIME_SIG = 4'd11;
    localparam [3:0] S_MARKET = 4'd12;
    localparam [3:0] S_RELATIONSHIP = 4'd13;
    localparam [3:0] S_TESTABILITY = 4'd14;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_RUN;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

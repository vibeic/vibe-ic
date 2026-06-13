// Auto-generated FSM skeleton.
// 8 states — transitions are TODO; only state enum + reset path are generated.
// Top module: NVMe_Controller

`timescale 1ns/1ps

module NVMe_Controller_fsm (
    input  clk,
    input  rst_n,
    output reg [2:0] state
);

    // State encoding
    localparam [2:0] S_REFER = 3'd0;
    localparam [2:0] S_FIGURE = 3'd1;
    localparam [2:0] S_UNABLE = 3'd2;
    localparam [2:0] S_SUCCESSFULLY = 3'd3;
    localparam [2:0] S_SUBJECT = 3'd4;
    localparam [2:0] S_SECTION = 3'd5;
    localparam [2:0] S_D3HOT = 3'd6;
    localparam [2:0] S_PTPL = 3'd7;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_REFER;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

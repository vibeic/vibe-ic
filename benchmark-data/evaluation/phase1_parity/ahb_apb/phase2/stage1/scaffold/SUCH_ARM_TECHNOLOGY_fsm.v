// Auto-generated FSM skeleton.
// 3 states — transitions are TODO; only state enum + reset path are generated.
// Top module: SUCH_ARM_TECHNOLOGY

`timescale 1ns/1ps

module SUCH_ARM_TECHNOLOGY_fsm (
    input  clk,
    input  rst_n,
    output reg [1:0] state
);

    // State encoding
    localparam [1:0] S_SETUP = 2'd0;
    localparam [1:0] S_ACCESS = 2'd1;
    localparam [1:0] S_IDLE = 2'd2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_SETUP;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

// Auto-generated FSM skeleton.
// 9 states — transitions are TODO; only state enum + reset path are generated.
// Top module: ONFI_NAND_Target

`timescale 1ns/1ps

module ONFI_NAND_Target_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_PERFORM = 4'd0;
    localparam [3:0] S_USED = 4'd1;
    localparam [3:0] S_DESCRIBE = 4'd2;
    localparam [3:0] S_STATES = 4'd3;
    localparam [3:0] S_ACCOMPLISH = 4'd4;
    localparam [3:0] S_PRIOR = 4'd5;
    localparam [3:0] S_INDICATE = 4'd6;
    localparam [3:0] S_MACHINE = 4'd7;
    localparam [3:0] S_INDICATED = 4'd8;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_PERFORM;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

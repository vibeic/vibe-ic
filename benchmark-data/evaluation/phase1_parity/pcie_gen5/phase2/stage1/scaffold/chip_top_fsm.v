// Auto-generated FSM skeleton.
// 3 states — transitions are TODO; only state enum + reset path are generated.
// Top module: chip_top

`timescale 1ns/1ps

module chip_top_fsm (
    input  clk,
    input  rst_n,
    output reg [1:0] state
);

    // State encoding
    localparam [1:0] S_DOWN = 2'd0;
    localparam [1:0] S_EXTENDED = 2'd1;
    localparam [1:0] S_TRAIN = 2'd2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_DOWN;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

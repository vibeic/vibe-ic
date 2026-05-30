// Auto-generated FSM skeleton.
// 4 states — transitions are TODO; only state enum + reset path are generated.
// Top module: ethercat

`timescale 1ns/1ps

module ethercat_fsm (
    input  clk,
    input  rst_n,
    output reg [1:0] state
);

    // State encoding
    localparam [1:0] S_INHERENT = 2'd0;
    localparam [1:0] S_CHECKSUM = 2'd1;
    localparam [1:0] S_SCAN = 2'd2;
    localparam [1:0] S_PROVIDED = 2'd3;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_INHERENT;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

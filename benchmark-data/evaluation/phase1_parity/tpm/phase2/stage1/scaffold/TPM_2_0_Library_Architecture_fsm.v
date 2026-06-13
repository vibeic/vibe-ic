// Auto-generated FSM skeleton.
// 2 states — transitions are TODO; only state enum + reset path are generated.
// Top module: TPM_2_0_Library_Architecture

`timescale 1ns/1ps

module TPM_2_0_Library_Architecture_fsm (
    input  clk,
    input  rst_n,
    output reg [0:0] state
);

    // State encoding
    localparam [0:0] S_STATE_CLEAR_DATA = 1'd0;
    localparam [0:0] S_STATE_RESET_DATA = 1'd1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_STATE_CLEAR_DATA;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

// Auto-generated FSM skeleton.
// 4 states — transitions are TODO; only state enum + reset path are generated.
// Top module: SPI

`timescale 1ns/1ps

module SPI_fsm (
    input  clk,
    input  rst_n,
    output reg [1:0] state
);

    // State encoding
    localparam [1:0] S_IDLE = 2'd0;
    localparam [1:0] S_MASTER_TRANSMIT = 2'd1;
    localparam [1:0] S_SLAVE_TRANSMIT_RECEIVE = 2'd2;
    localparam [1:0] S_MODE_FAULT = 2'd3;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

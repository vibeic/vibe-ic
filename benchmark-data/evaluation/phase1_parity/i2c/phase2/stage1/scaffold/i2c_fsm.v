// Auto-generated FSM skeleton.
// 10 states — transitions are TODO; only state enum + reset path are generated.
// Top module: i2c

`timescale 1ns/1ps

module i2c_fsm (
    input  clk,
    input  rst_n,
    output reg [3:0] state
);

    // State encoding
    localparam [3:0] S_IDLE = 4'd0;
    localparam [3:0] S_START_DETECT = 4'd1;
    localparam [3:0] S_ADDR_TRANSMIT = 4'd2;
    localparam [3:0] S_ADDR_ACK_WAIT = 4'd3;
    localparam [3:0] S_DATA_TRANSMIT = 4'd4;
    localparam [3:0] S_DATA_ACK_WAIT = 4'd5;
    localparam [3:0] S_CLOCK_STRETCH = 4'd6;
    localparam [3:0] S_ARBITRATION_LOSS = 4'd7;
    localparam [3:0] S_STOP_GENERATE = 4'd8;
    localparam [3:0] S_REPEATED_START = 4'd9;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

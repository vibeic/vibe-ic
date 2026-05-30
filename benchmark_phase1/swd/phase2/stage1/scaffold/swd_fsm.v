// Auto-generated FSM skeleton.
// 24 states — transitions are TODO; only state enum + reset path are generated.
// Top module: swd

`timescale 1ns/1ps

module swd_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_CAPTURE = 5'd0;
    localparam [4:0] S_SHIFT = 5'd1;
    localparam [4:0] S_CONNECTION = 5'd2;
    localparam [4:0] S_INTERFACE = 5'd3;
    localparam [4:0] S_REFERRING = 5'd4;
    localparam [4:0] S_DBGTAPSM = 5'd5;
    localparam [4:0] S_POSSIBLE = 5'd6;
    localparam [4:0] S_VARY = 5'd7;
    localparam [4:0] S_PROTOCOL = 5'd8;
    localparam [4:0] S_ENSURE = 5'd9;
    localparam [4:0] S_DORMANT = 5'd10;
    localparam [4:0] S_ZERO = 5'd11;
    localparam [4:0] S_EQUAL = 5'd12;
    localparam [4:0] S_SEVEN = 5'd13;
    localparam [4:0] S_WRAP = 5'd14;
    localparam [4:0] S_RETURNS = 5'd15;
    localparam [4:0] S_BRFIFO1 = 5'd16;
    localparam [4:0] S_BRFIFO4 = 5'd17;
    localparam [4:0] S_BWFIFO1 = 5'd18;
    localparam [4:0] S_BWFIFO4 = 5'd19;
    localparam [4:0] S_REGISTERS = 5'd20;
    localparam [4:0] S_ACCESS = 5'd21;
    localparam [4:0] S_ACCESSES = 5'd22;
    localparam [4:0] S_DBGTAP = 5'd23;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_CAPTURE;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

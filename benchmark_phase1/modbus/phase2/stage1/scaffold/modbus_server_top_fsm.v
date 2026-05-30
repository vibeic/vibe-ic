// Auto-generated FSM skeleton.
// 18 states — transitions are TODO; only state enum + reset path are generated.
// Top module: modbus_server_top

`timescale 1ns/1ps

module modbus_server_top_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_USED = 5'd0;
    localparam [4:0] S_READ = 5'd1;
    localparam [4:0] S_WRITE = 5'd2;
    localparam [4:0] S_OUTPUT = 5'd3;
    localparam [4:0] S_EITHER = 5'd4;
    localparam [4:0] S_REQUEST = 5'd5;
    localparam [4:0] S_REMOTE = 5'd6;
    localparam [4:0] S_DEVICE = 5'd7;
    localparam [4:0] S_RETURN = 5'd8;
    localparam [4:0] S_IDENTICAL = 5'd9;
    localparam [4:0] S_FORCE = 5'd10;
    localparam [4:0] S_COILS = 5'd11;
    localparam [4:0] S_SPECIFIC = 5'd12;
    localparam [4:0] S_PERFORM = 5'd13;
    localparam [4:0] S_MODIFY = 5'd14;
    localparam [4:0] S_ALLOWS = 5'd15;
    localparam [4:0] S_ASKED = 5'd16;
    localparam [4:0] S_REFER = 5'd17;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_USED;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

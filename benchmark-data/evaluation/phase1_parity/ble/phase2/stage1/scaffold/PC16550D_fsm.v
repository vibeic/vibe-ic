// Auto-generated FSM skeleton.
// 32 states — transitions are TODO; only state enum + reset path are generated.
// Top module: PC16550D

`timescale 1ns/1ps

module PC16550D_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_S_TO_M_PHY = 5'd0;
    localparam [4:0] S_WAIT_DISCONNECT = 5'd1;
    localparam [4:0] S_ENHANCEMENTS = 5'd2;
    localparam [4:0] S_L2CAP = 5'd3;
    localparam [4:0] S_IMPROVEMENTS = 5'd4;
    localparam [4:0] S_SECURITY = 5'd5;
    localparam [4:0] S_ADDED = 5'd6;
    localparam [4:0] S_DEFINED = 5'd7;
    localparam [4:0] S_SUPPORT = 5'd8;
    localparam [4:0] S_ALLOCATED = 5'd9;
    localparam [4:0] S_IDENTIFY = 5'd10;
    localparam [4:0] S_ZERO = 5'd11;
    localparam [4:0] S_TRANSACTION = 5'd12;
    localparam [4:0] S_SUCCEED = 5'd13;
    localparam [4:0] S_CLARIFY = 5'd14;
    localparam [4:0] S_CORRESPONDS = 5'd15;
    localparam [4:0] S_REQUESTED = 5'd16;
    localparam [4:0] S_FINALLY = 5'd17;
    localparam [4:0] S_MOVE = 5'd18;
    localparam [4:0] S_CHANNEL = 5'd19;
    localparam [4:0] S_ANOTHER = 5'd20;
    localparam [4:0] S_RELATE = 5'd21;
    localparam [4:0] S_CORRECTLY = 5'd22;
    localparam [4:0] S_SPECIFICATIONS = 5'd23;
    localparam [4:0] S_THEIR = 5'd24;
    localparam [4:0] S_BELONGING = 5'd25;
    localparam [4:0] S_RELATED = 5'd26;
    localparam [4:0] S_CONFIGURATION = 5'd27;
    localparam [4:0] S_NECESSARY = 5'd28;
    localparam [4:0] S_SEND = 5'd29;
    localparam [4:0] S_DIRECTLY = 5'd30;
    localparam [4:0] S_APPLY = 5'd31;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_S_TO_M_PHY;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

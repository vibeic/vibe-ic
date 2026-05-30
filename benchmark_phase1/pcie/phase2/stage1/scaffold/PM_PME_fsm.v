// Auto-generated FSM skeleton.
// 32 states — transitions are TODO; only state enum + reset path are generated.
// Top module: PM_PME

`timescale 1ns/1ps

module PM_PME_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_ELECTRICAL = 5'd0;
    localparam [4:0] S_PERMITTED = 5'd1;
    localparam [4:0] S_OPTIMIZE = 5'd2;
    localparam [4:0] S_REQUIRED = 5'd3;
    localparam [4:0] S_SUPPORT = 5'd4;
    localparam [4:0] S_USED = 5'd5;
    localparam [4:0] S_MOVE = 5'd6;
    localparam [4:0] S_SOLVING = 5'd7;
    localparam [4:0] S_INTERNAL = 5'd8;
    localparam [4:0] S_INFORMATION = 5'd9;
    localparam [4:0] S_MACHINE = 5'd10;
    localparam [4:0] S_PERFORM = 5'd11;
    localparam [4:0] S_ENTRY = 5'd12;
    localparam [4:0] S_DL_INACTIVE = 5'd13;
    localparam [4:0] S_DEFAULT_SIG = 5'd14;
    localparam [4:0] S_ENTRANCE = 5'd15;
    localparam [4:0] S_DL_INIT = 5'd16;
    localparam [4:0] S_TRANSITION = 5'd17;
    localparam [4:0] S_PASSED = 5'd18;
    localparam [4:0] S_ADDITION = 5'd19;
    localparam [4:0] S_EXCHANGE = 5'd20;
    localparam [4:0] S_MEANS = 5'd21;
    localparam [4:0] S_SEND = 5'd22;
    localparam [4:0] S_EXIT = 5'd23;
    localparam [4:0] S_CONFIG_SIG = 5'd24;
    localparam [4:0] S_NUMBERS = 5'd25;
    localparam [4:0] S_CONTROL = 5'd26;
    localparam [4:0] S_PRIOR = 5'd27;
    localparam [4:0] S_INITIALIZED = 5'd28;
    localparam [4:0] S_POLLING = 5'd29;
    localparam [4:0] S_CONFIGURATION = 5'd30;
    localparam [4:0] S_DIRECTED = 5'd31;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_ELECTRICAL;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule

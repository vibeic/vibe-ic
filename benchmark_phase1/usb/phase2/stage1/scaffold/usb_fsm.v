// Auto-generated FSM skeleton.
// 32 states — transitions are TODO; only state enum + reset path are generated.
// Top module: usb

`timescale 1ns/1ps

module usb_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_RESETTING = 5'd0;
    localparam [4:0] S_REQUIRED = 5'd1;
    localparam [4:0] S_DECODE = 5'd2;
    localparam [4:0] S_MACHINE = 5'd3;
    localparam [4:0] S_SPECIFY = 5'd4;
    localparam [4:0] S_REFERENCE = 5'd5;
    localparam [4:0] S_ANOTHER = 5'd6;
    localparam [4:0] S_USED = 5'd7;
    localparam [4:0] S_CONNECT = 5'd8;
    localparam [4:0] S_RELATES = 5'd9;
    localparam [4:0] S_JOIN = 5'd10;
    localparam [4:0] S_TIME = 5'd11;
    localparam [4:0] S_PROCESS = 5'd12;
    localparam [4:0] S_RESPOND = 5'd13;
    localparam [4:0] S_RESPONSES = 5'd14;
    localparam [4:0] S_RETURN = 5'd15;
    localparam [4:0] S_USING = 5'd16;
    localparam [4:0] S_BACK = 5'd17;
    localparam [4:0] S_INITIALIZED = 5'd18;
    localparam [4:0] S_DATA0 = 5'd19;
    localparam [4:0] S_MECHANISM = 5'd20;
    localparam [4:0] S_GUARANTEE = 5'd21;
    localparam [4:0] S_PROPAGATION = 5'd22;
    localparam [4:0] S_INDICATION = 5'd23;
    localparam [4:0] S_SYNCHRONIZED = 5'd24;
    localparam [4:0] S_SIGNALING = 5'd25;
    localparam [4:0] S_EMULATE = 5'd26;
    localparam [4:0] S_SOP_FD = 5'd27;
    localparam [4:0] S_ENTRY = 5'd28;
    localparam [4:0] S_SIGNAL = 5'd29;
    localparam [4:0] S_LABELING = 5'd30;
    localparam [4:0] S_IDENTIFY = 5'd31;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_RESETTING;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule
